"""v2_scalp_large3.py - Part 55: SCALP LAB 6 of 8 (backend, read-only, HYPOTHETICAL replay). Large-trade replay on 3m candles: "my BIG real trades - what if the entry had been split into smaller pieces?"
It reads the owner's closed real / paper trades through Part 5 (v2_pnl) and the saved 3m candles; it NEVER writes (no ledger, no trade file, no setting) and never rewrites a real trade. The real trade stays exactly as recorded; every number here is a hypothetical beside it.
Part 56 uses the same engine for 5m (build(..., interval="5m")) and puts real and hypothetical side by side.
WHICH TRADES: every box is its own world and is NEVER added to another (real_live, live_estimated, paper_b1, paper_b2). LARGE = notional (invest_usdt x leverage) in the top quarter of that box (the cut-off is shown); a box with fewer than 4 trades with a notional has no cut-off and nothing is replayed.
THE REPLAY (candle-close execution, nothing looks ahead; the owner's REAL entry and REAL exit moments are used as given, no new exit rule, no hindsight rule):
  E = the 3m candle that holds the real entry time, X = the candle that holds the real exit time; prices are candle CLOSES (the first price anybody could use after the moment). Needs E..X in ONE gap-free run of saved candles and X after E.
  ONE = the whole size in at close(E), out at close(X)  (the real trade re-drawn on candle closes, so the split is compared with the same costs and the same price source).
  IN3 = three equal pieces in at close(E), close(E+2), close(E+4); a piece whose candle is not before X is NOT bought (filled_share shows it, it counts 0, never a guess); all out at close(X).
  COSTS: fee + slippage per side of v2_replay on every piece (net = gross - 2 x (fee + slippage)). Raw price % of the planned size, not leveraged ROI.
Status per trade: REPLAYED, NO_CANDLES (the saved candles do not reach back / that coin was not collected), GAP (a candle gap inside E..X), TOO_SHORT (entry and exit in the same candle), BAD_ROW (no side / time / price). Nothing is counted as 0.
Older replayed trades = TRAIN, newest 30% by entry time = HOLDOUT (v2_replay.holdout_cut). Under 30 replayed = "too few to say anything". No win rate, no prediction, no order, no advice to change a real trade.
All numbers (3 pieces, 2 candles apart, top quarter = large, costs 0.05 + 0.02 % per side) are starting values, not validated.
Run (Termux):  python3 backend/v2_scalp_large3.py [--data DIR] [--days N]     Route: GET /api/v2/scalp_large3[?days=N] (api/v2_data.py), N = 1 to 365 (default: all)."""
import argparse
import json
import math
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_defs as D
import v2_pnl as P
import v2_replay as R
import v2_store as S

VERSION = "v2_scalp_large3 1 (Part 55)"
INTERVAL = "3m"
PIECES = 3
PIECE_GAP = 2                    # candles between the pieces (NV)
LARGE_FRAC = 0.25                # the top quarter of a box by notional (NV)
MIN_BOX = 4
MAX_ROWS = 100
SIDES = {"BUY": "LONG", "LONG": "LONG", "SELL": "SHORT", "SHORT": "SHORT"}
STATUSES = ("REPLAYED", "NO_CANDLES", "GAP", "TOO_SHORT", "BAD_ROW")
DEFINITION = {"large": "top %d%% of the box by notional (invest x leverage)" % int(LARGE_FRAC * 100), "ONE": "all in at close of the entry candle, all out at close of the exit candle",
              "IN3": "%d equal pieces at close of the entry candle and %d / %d candles later (only if before the exit candle), all out at close of the exit candle" % (PIECES, PIECE_GAP, 2 * PIECE_GAP),
              "fees": "%.2f%% per side (v2_replay)" % R.FEE_PCT, "slippage": "%.2f%% per side (v2_replay)" % R.SLIP_PCT, "window": "saved candles of one gap-free run, execution at candle close, the real entry and exit moments as given"}


def _side(t):
    return SIDES.get(str(t.get("action") or t.get("side") or "").upper())


def notional(t):
    inv, lev = P.num(t, "invest_usdt"), P.num(t, "leverage")
    return None if not inv or inv <= 0 else inv * (lev if lev and lev > 0 else 1.0)


def _entry_exit(t):
    a, b = P.num(t, "opened_at_ts"), P.num(t, "closed_at_ts")
    return (a, b) if a and b and a > 0 and b > a else (None, None)


def replay(con, t, side, a, b, interval=INTERVAL):
    """One real trade -> (status, dict). Read-only. a / b = real entry / exit time (seconds)."""
    step = D.STEP[interval]
    sym = str(t.get("symbol") or "").upper().replace("/", "").replace("-", "")
    e0, x0 = int(a) - int(a) % step, int(b) - int(b) % step
    if x0 <= e0:
        return "TOO_SHORT", {}
    good, _bad = D.clean_candles(D.candles_from_store(con, sym, interval, e0, x0), interval)
    if not good or good[0][0] != e0:
        return "NO_CANDLES", {}
    if len(good) != (x0 - e0) // step + 1 or any(good[i + 1][0] - good[i][0] != step for i in range(len(good) - 1)):
        return ("GAP" if good[-1][0] == x0 else "NO_CANDLES"), {}
    sg, cost, x = (1 if side == "LONG" else -1), R.cost_pct(), len(good) - 1
    px_out = good[x][4]

    def net(i):
        return sg * (px_out - good[i][4]) / good[i][4] * 100.0 - cost
    idx = [k * PIECE_GAP for k in range(PIECES) if k * PIECE_GAP < x]
    one = net(0)
    in3 = sum(net(i) for i in idx) / PIECES
    return "REPLAYED", {"entry_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(e0)), "entry_ts": e0, "hold_candles": x, "ONE_net_pct": round(one, 4), "IN3_net_pct": round(in3, 4),
                        "filled_share": round(len(idx) / float(PIECES), 3), "delta_pct": round(in3 - one, 4)}


def _stat(vals):
    n = len(vals)
    return {"n": n, "median": None if n < R.MIN_N else round(R._med(vals), 4), **({"note": "too few to say anything (under %d replayed trades)" % R.MIN_N} if n < R.MIN_N else {})}


def _summary(rows):
    d = [r["delta_pct"] for r in rows]
    s = {"n": len(rows), "ONE_net_pct": _stat([r["ONE_net_pct"] for r in rows]), "IN3_net_pct": _stat([r["IN3_net_pct"] for r in rows]), "delta_IN3_minus_ONE": _stat(d),
         "IN3_better": sum(1 for x in d if x > 0), "IN3_worse": sum(1 for x in d if x < 0), "same": sum(1 for x in d if x == 0)}
    return s


def box_report(con, items, interval, first_ts):
    nots = sorted(n for n in (notional(t) for t in items) if n)
    rep = {"trades": len(items), "with_notional": len(nots), "large_cutoff_notional": None, "large_trades": 0, "statuses": {k: 0 for k in STATUSES}, "replayed": 0}
    if len(nots) < MIN_BOX:
        rep["note"] = "fewer than %d trades with a notional: no cut-off, nothing replayed" % MIN_BOX
        return rep
    cut = nots[len(nots) - int(math.ceil(len(nots) * LARGE_FRAC))]
    rep["large_cutoff_notional"] = round(cut, 2)
    rows = []
    for t in items:
        n = notional(t)
        if not n or n < cut:
            continue
        rep["large_trades"] += 1
        a, b = _entry_exit(t)
        side = _side(t)
        if side is None or a is None:
            rep["statuses"]["BAD_ROW"] += 1
            continue
        if a < first_ts:
            rep["statuses"]["NO_CANDLES"] += 1
            continue
        st, r = replay(con, t, side, a, b, interval)
        rep["statuses"][st] += 1
        if st == "REPLAYED":
            entry, ex = P.num(t, "entry_price"), P.num(t, "exit_price")
            real = None if not (entry and ex and entry > 0 and ex > 0) else round((ex - entry) / entry * 100.0 * (1 if side == "LONG" else -1), 4)
            rows.append(dict(r, id=str(t.get("id") or t.get("trade_id") or ""), symbol=t.get("symbol"), side=side, notional=round(n, 2), real_raw_move_pct=real))
    rep["replayed"] = len(rows)
    cutt = R.holdout_cut([r["entry_ts"] for r in rows])
    rep["TRAIN"] = _summary([r for r in rows if R.sample_of(r["entry_ts"], cutt) == "TRAIN"])
    rep["HOLDOUT"] = _summary([r for r in rows if R.sample_of(r["entry_ts"], cutt) == "HOLDOUT"])
    rep["holdout_from_utc"] = None if cutt is None else time.strftime("%Y-%m-%d %H:%M", time.gmtime(cutt))
    rep["rows"] = sorted(rows, key=lambda r: r["entry_ts"])[-MAX_ROWS:]
    return rep


def build(con, data_dir, now=None, days=None, interval=INTERVAL):
    """-> the report dict (read-only). days = 1 to 365 limits the real trades by entry time (default all). Raises ValueError on a bad days value."""
    now = int(time.time() if now is None else now)
    if days not in (None, "") and (not str(days).isdigit() or not 1 <= int(days) <= 365):
        raise ValueError("days must be a whole number from 1 to 365")
    since = 0 if days in (None, "") else now - int(days) * 86400
    root = os.path.realpath(data_dir)
    if not os.path.isdir(root):
        return {"ready": False, "version": VERSION, "note": "data folder not found"}
    items, seen, srcs = {b: [] for b in P.BOXES}, {b: set() for b in P.BOXES}, {}
    for name, file_bot in P.FILES:
        rows, st = P.read_jsonl(os.path.join(root, name), [root])
        srcs[name] = st
        for t in rows:
            a, _b = _entry_exit(t)
            b, k = P.box_of(t, file_bot), P.tkey(t)
            if k in seen[b]:
                continue
            seen[b].add(k)
            if a is None or a >= since:
                items[b].append(t)
    row = con.execute("SELECT MIN(open_ts) FROM candles WHERE interval=?", (interval,)).fetchone()
    first_ts = row[0] if row and row[0] else None
    rep = {"ready": True, "version": VERSION, "interval": interval, "days": days or "all", "definition": DEFINITION, "candles_from_utc": None if first_ts is None else time.strftime("%Y-%m-%d %H:%M", time.gmtime(first_ts)),
           "sources": srcs, "boxes": {},
           "notes": ["HYPOTHETICAL replay of saved candles, no order, nothing written; the real trades are never changed",
                     "each box (real_live, live_estimated, paper_b1, paper_b2) is its own world and is never added to another",
                     "ONE re-draws the real trade on candle closes; IN3 splits only the entry; both pay the same fees and slippage; raw price %, not leveraged",
                     "trades older than the saved candles are NO_CANDLES, never 0; under 30 replayed = too few to say anything",
                     "all numbers (3 pieces, 2 candles apart, top quarter = large, costs) are starting values, not validated"]}
    if first_ts is None:
        rep["note"] = "no %s candles saved yet: nothing can be replayed" % interval
    for b in P.BOXES:
        rep["boxes"][b] = box_report(con, items[b], interval, first_ts if first_ts is not None else 10 ** 12)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--days", default="")
    a = ap.parse_args(argv)
    path = S.store_path(a.data)
    if not os.path.isfile(path):
        print(json.dumps({"ready": False, "note": "the market store is not created yet"}))
        return 0
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    try:
        con.execute("PRAGMA query_only=ON")
        rep = build(con, a.data, None, a.days)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    finally:
        con.close()
    for bx in rep.get("boxes", {}).values():
        bx["rows"] = bx.get("rows", [])[-3:]
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
