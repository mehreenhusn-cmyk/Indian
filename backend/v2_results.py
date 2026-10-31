"""v2_results.py - Part 80: RESULTS 1 of 2 (backend, read-only). Answers: "which group of my CLOSED trades makes money and which loses money?"

Reads the permanent closed-trade files (same files and same box rule as Part 5, v2_pnl.py) and NEVER writes, never touches a setting, a position or an order.
No network, no trading module, no API. The boxes (real / live estimated / paper bot 1 / paper bot 2) are NEVER added together.
Every number is NET of fee (old paper trades without a fee inside get the fee estimated, exactly like Part 5).

Groups (each trade lands in one group per list; a field the trade did not save is counted as "not saved", never guessed):
  BUY or SELL | how the trade ended (exit reason) | time of day (IST, when it opened) | how long it was open | coin | timeframe | entry zone | higher-timeframe trend
Verdict of a group (plain words, honest about luck):
  TOO_FEW        fewer than 30 trades -> no verdict, only the numbers
  MAKING_MONEY   30+ trades, net above 0, AND both halves of its history (older half, newer half) above 0
  LOSING         30+ trades, net below 0, AND both halves below 0
  MIXED          30+ trades but the halves disagree or net and halves do not match -> do not trust it yet
It is evidence, NOT an order: a group that made money in the past can stop. Route: GET /api/v2/results (Part 80, api/v2_data.py).
Run (Termux):  python3 backend/v2_results.py [--data DIR] [--fee-roi 1.0]
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_pnl as P

VERSION = "v2_results 1 (Part 80)"
MIN_N = 30
SYM_RE = re.compile(r"^[A-Z0-9]{2,20}$")
BOX_TITLE = {"real_live": "REAL live trades (Binance result)", "live_estimated": "LIVE trades (result estimated by the app)",
             "paper_b1": "PAPER - main bot", "paper_b2": "PAPER - old Bot 2 archive"}
HOLD = ((15, "under 15 min"), (60, "15 min to 1 h"), (240, "1 h to 4 h"), (720, "4 h to 12 h"), (None, "over 12 h"))
HOUR = (("05:00-09:00", 5, 9), ("09:00-13:00", 9, 13), ("13:00-17:00", 13, 17), ("17:00-21:00", 17, 21), ("21:00-01:00", 21, 25), ("01:00-05:00", 1, 5))
LIST_CAP = 12


def _text(v, n=24):
    s = "" if v is None else str(v).strip()
    s = re.sub(r"[^A-Za-z0-9 _.+/>-]", "", s)[:n].strip()
    return s or None


def d_side(t):
    s = str(t.get("side") or t.get("direction") or "").strip().upper()
    s = {"LONG": "BUY", "SHORT": "SELL"}.get(s, s)
    return s if s in ("BUY", "SELL") else None


def d_exit(t):
    return _text(t.get("clean_exit_reason") or t.get("reason") or t.get("status"), 30)


def d_coin(t):
    s = str(t.get("symbol") or "").strip().upper()
    return s if SYM_RE.match(s) else None


def d_hour(t):
    o = P.num(t, "opened_at_ts")
    if o is None or o <= 0:
        return None
    h = int(((o + 19800) % 86400) // 3600)          # IST = UTC + 5:30
    for label, a, b in HOUR:
        if a <= h < b or a <= h + 24 < b:
            return label
    return None


def d_hold(t):
    o, c = P.num(t, "opened_at_ts"), P.num(t, "closed_at_ts")
    if o is None or c is None or c < o:
        return None
    m = (c - o) / 60.0
    for lim, label in HOLD:
        if lim is None or m < lim:
            return label
    return None


def d_tf(t):
    return _text(t.get("timeframe"), 8)


def d_zone(t):
    return _text(t.get("entry_zone"), 20)


def d_htf(t):
    return _text(t.get("htf_trend"), 20)


DIMS = (("side", "BUY or SELL", d_side), ("exit", "How the trade ended", d_exit), ("hour", "Time of day (IST, when it opened)", d_hour),
        ("hold", "How long it was open", d_hold), ("coin", "Coin", d_coin), ("tf", "Timeframe", d_tf), ("zone", "Entry zone", d_zone),
        ("htf", "Higher-timeframe trend", d_htf))


def net_of(t, fee_roi):
    pnl = P.num(t, "pnl_usdt")
    if pnl is None:
        return None
    if P.fee_basis(t) == "none_old":                  # old paper trade: no fee inside -> estimate it (same rule as Part 5)
        pnl -= (P.num(t, "invest_usdt") or 0.0) * fee_roi / 100.0
    return pnl


def load(data_dir, fee_roi):
    root = os.path.realpath(data_dir)
    out = {b: [] for b in P.BOXES}
    seen = {b: set() for b in P.BOXES}
    skipped = 0
    for name, file_bot in P.FILES:
        rows, _st = P.read_jsonl(os.path.join(root, name), [root])
        for t in rows:
            b = P.box_of(t, file_bot)
            k = P.tkey(t)
            if k in seen[b]:
                continue                                # same trade twice: counted once
            seen[b].add(k)
            net, ts = net_of(t, fee_roi), P.num(t, "closed_at_ts")
            if net is None or ts is None:
                skipped += 1
                continue
            out[b].append((ts, net, t))
    return out, skipped


def stats(items):
    """items = [(close_ts, net), ...] oldest first."""
    n = len(items)
    net = sum(x[1] for x in items)
    wins = sum(1 for x in items if x[1] > 0)
    h = n // 2
    h1, h2 = sum(x[1] for x in items[:h]), sum(x[1] for x in items[h:])
    if n < MIN_N:
        v = "TOO_FEW"
    elif net > 0 and h1 > 0 and h2 > 0:
        v = "MAKING_MONEY"
    elif net < 0 and h1 < 0 and h2 < 0:
        v = "LOSING"
    else:
        v = "MIXED"
    return {"n": n, "wins": wins, "win_pct": round(100.0 * wins / n, 1), "net_usdt": round(net, 2), "avg_usdt": round(net / n, 2),
            "older_half_usdt": round(h1, 2), "newer_half_usdt": round(h2, 2), "verdict": v}


def group(trades, fn):
    g = {}
    unsaved = 0
    for ts, net, t in trades:
        k = fn(t)
        if k is None:
            unsaved += 1
            continue
        g.setdefault(k, []).append((ts, net))
    rows = []
    for k, v in g.items():
        s = stats(v)
        s["label"] = k
        rows.append(s)
    rows.sort(key=lambda r: -r["net_usdt"])
    return rows, unsaved


def _utc(ts):
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def box_report(trades):
    trades.sort(key=lambda x: x[0])
    rep = {"overall": stats([(a, b) for a, b, _t in trades]), "first_close_utc": _utc(trades[0][0]), "last_close_utc": _utc(trades[-1][0]), "dims": []}
    pool = []
    for key, title, fn in DIMS:
        rows, unsaved = group(trades, fn)
        hidden = 0
        shown = rows
        if len(rows) > LIST_CAP:
            shown = rows[:LIST_CAP // 2] + rows[-(LIST_CAP // 2):]       # best and worst only
            hidden = len(rows) - len(shown)
        for r in rows:
            if r["verdict"] in ("MAKING_MONEY", "LOSING"):
                pool.append(dict(r, dim=title))
        rep["dims"].append({"key": key, "title": title, "rows": shown, "hidden": hidden, "not_saved": unsaved, "saved": len(trades) - unsaved})
    rep["makes_money"] = sorted([r for r in pool if r["verdict"] == "MAKING_MONEY"], key=lambda r: -r["net_usdt"])[:5]
    rep["loses_money"] = sorted([r for r in pool if r["verdict"] == "LOSING"], key=lambda r: r["net_usdt"])[:5]
    o = rep["overall"]
    say = ["%d closed trades, net %+.2f USDT after fee, win rate %.1f%%." % (o["n"], o["net_usdt"], o["win_pct"])]
    say.append("%d group(s) made money in both halves of their history." % len(rep["makes_money"]) if rep["makes_money"]
               else "No group with %d+ trades made money in BOTH halves of its history yet. Nothing here is proven profit." % MIN_N)
    if rep["loses_money"]:
        w = rep["loses_money"][0]
        say.append("Biggest steady loser: %s = %s (%d trades, net %+.2f USDT)." % (w["dim"], w["label"], w["n"], w["net_usdt"]))
    rep["say"] = say
    return rep


def build(data_dir, fee_roi=1.0):
    if not os.path.isdir(os.path.realpath(data_dir)):
        return {"ready": False, "note": "data folder not found", "tool": VERSION}
    boxes, skipped = load(data_dir, fee_roi)
    out = {"ready": True, "tool": VERSION, "read_only": True, "made_utc": _utc(time.time()), "fee_roi_pct_used_for_old_trades": fee_roi,
           "skipped_without_pnl_or_time": skipped, "boxes": {}, "order": []}
    for b in sorted(P.BOXES, key=lambda x: -len(boxes[x])):
        if boxes[b]:
            out["boxes"][b] = dict(box_report(boxes[b]), title=BOX_TITLE[b])
            out["order"].append(b)
    out["note"] = "" if out["order"] else "No closed trades found in the data folder yet."
    out["notes"] = ["Closed trades only, NET of fee. The boxes are never added together: real money and paper money must not be mixed.",
                    "A group needs %d+ trades AND profit in both halves of its history before it is called MAKING_MONEY." % MIN_N,
                    "This is evidence, not an order. A group that made money before can stop."]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", ""))
    ap.add_argument("--fee-roi", type=float, default=1.0)
    a = ap.parse_args(argv)
    if not a.data:
        print("give --data DIR or set OWL_DATA_DIR")
        return 2
    print(json.dumps(build(a.data, a.fee_roi), indent=1, default=str)[:20000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
