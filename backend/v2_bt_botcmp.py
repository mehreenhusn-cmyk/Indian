"""v2_bt_botcmp.py - Part 87c (backend, read-only): CURRENT BOT vs BRAIN on ONE coin, for the signal detail screen (mock screens 03 and 09).
Question the owner asks: "the bot is already in this coin, the Brain waited: who has the better entry?"
Looks for the main paper bot (box paper_b1, never paper_b2, never a live copy) on that coin:
  OPEN         an open position saved in owl.db (table positions, read through the safe opener of Part 1): side, entry, last saved price, price move since entry (raw %, not leveraged), how long ago it opened.
  LAST_CLOSED  no open position: its newest CLOSED trade of that coin within 24 hours (closed_trades_archive.jsonl): side, entry, net USDT, how long ago it closed.
  NONE         neither. Said plainly.
Against the Brain's idea (entry price + side of the NOW answer, only when the Brain has an entry): if both sides are the same, 'entry_better_pct' = how much BETTER (positive) or worse (negative) the Brain's entry is,
in % of the bot's entry (LONG: lower is better, SHORT: higher is better). A different side = 'OPPOSITE', nothing is calculated. It is a comparison of two ENTRY PRICES, not of results: the bot's trade is still running or ended on its own rules.
No network, nothing is saved, no order code, LIVE does not exist. Run (Termux, optional):  python3 backend/v2_bt_botcmp.py --symbol XYZUSDT [--entry 67420 --side LONG]  -> JSON."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_inv_safe as S
import v2_pnl as P

VERSION = "v2_bt_botcmp 1 (Part 87c)"
RECENT_S = 24 * 3600
SIDE = {"BUY": "LONG", "SELL": "SHORT", "LONG": "LONG", "SHORT": "SHORT"}


def _side(p):
    return SIDE.get(str(p.get("action") or p.get("side") or p.get("direction") or "").strip().upper())


def _ago(now, ts):
    m = max(0, int((now - ts) // 60))
    return "%d min" % m if m < 60 else "%dh %02dmin" % (m // 60, m % 60)


def open_position(data_dir, symbol):
    """The newest OPEN paper_b1 position of the coin from owl.db, or None. Read-only (a WAL file is read by a copy)."""
    root = os.path.realpath(data_dir)
    try:
        with S.open_safe(os.path.join(root, "owl.db"), [root]) as db:
            rows = db.con.execute("SELECT data FROM positions").fetchall()
    except Exception:
        return None
    best = None
    for (data,) in rows:
        try:
            p = json.loads(data)
        except (ValueError, TypeError):
            continue
        if not isinstance(p, dict) or str(p.get("symbol") or "").upper() != symbol or str(p.get("source") or "").lower() == "live" or str(p.get("bot") or "b1").lower() == "b2":
            continue
        if _side(p) and P.num(p, "entry_price") and (best is None or (P.num(p, "opened_at_ts") or 0) > (P.num(best, "opened_at_ts") or 0)):
            best = p
    return best


def last_closed(data_dir, symbol, now):
    """The newest CLOSED paper_b1 trade of the coin that closed within 24 hours, or None."""
    root, best = os.path.realpath(data_dir), None
    rows, _st = P.read_jsonl(os.path.join(root, P.FILES[0][0]), [root])
    for t in rows:
        ts = P.num(t, "closed_at_ts")
        if str(t.get("symbol") or "").upper() == symbol and P.box_of(t, "b1") == "paper_b1" and _side(t) and P.num(t, "entry_price") and ts and 0 <= now - ts <= RECENT_S:
            if best is None or ts > P.num(best, "closed_at_ts"):
                best = t
    return best


def build(data_dir, symbol, brain_entry=None, brain_side=None, now=None):
    symbol = str(symbol or "").upper()
    now = float(time.time() if now is None else now)
    out = {"framework": VERSION, "symbol": symbol, "state": "NONE", "live": "LOCKED"}
    p = open_position(data_dir, symbol)
    if p is not None:
        e, ltp, ts = P.num(p, "entry_price"), P.num(p, "ltp"), P.num(p, "opened_at_ts")
        mv = None if not ltp else round(((ltp - e) if _side(p) == "LONG" else (e - ltp)) / e * 100.0, 3)
        out.update(state="OPEN", side=_side(p), entry=e, last_price=ltp, move_pct=mv, since=None if ts is None else _ago(now, ts))
        out["text"] = "The Current Bot is IN this coin (%s at %s)%s." % (out["side"], e, "" if ts is None else ", opened %s ago" % out["since"])
    else:
        t = last_closed(data_dir, symbol, now)
        if t is not None:
            out.update(state="LAST_CLOSED", side=_side(t), entry=P.num(t, "entry_price"), net_usdt=P.num(t, "pnl_usdt"), since=_ago(now, P.num(t, "closed_at_ts")))
            out["text"] = "The Current Bot is not in this coin now. Its last trade (%s at %s) closed %s ago." % (out["side"], out["entry"], out["since"])
        else:
            out["text"] = "The Current Bot has no open position and no closed trade in this coin in the last 24 hours."
    if out["state"] != "NONE" and brain_entry and brain_side in ("LONG", "SHORT"):
        if brain_side != out["side"]:
            out["versus"] = {"result": "OPPOSITE", "text": "The bot is %s, the Brain's idea is %s." % (out["side"], brain_side)}
        else:
            e = out["entry"]
            b = round(((e - brain_entry) if brain_side == "LONG" else (brain_entry - e)) / e * 100.0, 3)
            out["versus"] = {"result": "BETTER" if b > 0 else "WORSE" if b < 0 else "SAME", "entry_better_pct": b,
                             "text": "The Brain's entry (%s) is %.2f%% %s than the bot's (%s). Two entry prices, not two results." % (brain_entry, abs(b), "better" if b >= 0 else "worse", e)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--entry", type=float, default=None)
    ap.add_argument("--side", default=None, choices=("LONG", "SHORT"))
    a = ap.parse_args(argv)
    print(json.dumps(build(a.data, a.symbol, a.entry, a.side), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
