"""owl_sniper_days.py - OwlSniper R28b (Part 9): SNIPER TODAY and SNIPER 7 DAYS. PAPER ONLY, READ ONLY: reads the closed Sniper paper trades (owl_sniper_lessons.read_own), writes nothing, no order code.
Owner wish (rule 31): Sniper Today and Sniper 7 Days are two separate tabs on the Dashboard. A day starts 5:30 AM IST = 00:00 UTC (same as the Current Bot's today). BTC is the indicator test coin and NEVER counts here (rule 23).
Sniper trades only: source sniper / sniper_learn. Never added to the Current Bot, Dual or Brain numbers.
build(d, now) -> {today: block, week: block, days: [7 x {day, label, net, n, wins}], ...}
block = {n, wins, losses, win_pct, net, avg, best, worst, profit, loss, lanes {LEARN: {n, net}, ...}, coins_top[3], coins_worst[3], exits[3] (most frequent exit reasons), tags[3] (mistake tags)}.
Honest empty: n = 0 gives a plain text line, no made-up numbers. CLI: python3 backend/owl_sniper_days.py [--data DIR]"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_lessons as LS

VERSION = "owl_sniper_days 1 (R28b)"
DAY = 86400


def _num(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _is_btc(t):
    return str(t.get("symbol") or "").upper().startswith("BTC")


def _top(items, n=3, reverse=True):
    return sorted(items, key=lambda kv: kv[1], reverse=reverse)[:n]


def block(rows):
    """Numbers of one list of closed trades (dicts with pnl_usdt). n = 0 -> text only."""
    pn = [(t, _num(t.get("pnl_usdt"))) for t in rows]
    pn = [(t, p) for t, p in pn if p is not None]
    if not pn:
        return {"n": 0, "net": 0.0, "text": "No closed Sniper trade in this window yet."}
    vals = [p for _t, p in pn]
    wins = sum(1 for p in vals if p > 0)
    coins, lanes, exits, tags = {}, {}, {}, {}
    for t, p in pn:
        s = str(t.get("symbol") or "?")
        coins[s] = coins.get(s, 0.0) + p
        ln = "LEARN" if str(t.get("source") or "").lower() == "sniper_learn" else "REAL"
        e = lanes.setdefault(ln, {"n": 0, "net": 0.0})
        e["n"] += 1
        e["net"] = round(e["net"] + p, 2)
        x = str(t.get("clean_exit_reason") or t.get("exit_reason") or "?")
        exits[x] = exits.get(x, 0) + 1
        try:
            tg = LS.tag_trade(t)[0]
        except Exception:
            tg = None
        if tg and p < 0:
            tags[tg] = tags.get(tg, 0) + 1
    return {
        "n": len(vals), "wins": wins, "losses": sum(1 for p in vals if p < 0), "win_pct": round(100.0 * wins / len(vals), 1),
        "net": round(sum(vals), 2), "avg": round(sum(vals) / len(vals), 2), "best": round(max(vals), 2), "worst": round(min(vals), 2),
        "profit": round(sum(p for p in vals if p > 0), 2), "loss": round(sum(p for p in vals if p < 0), 2), "lanes": lanes,
        "coins_top": [{"symbol": k, "net": round(v, 2)} for k, v in _top(coins.items()) if v > 0],
        "coins_worst": [{"symbol": k, "net": round(v, 2)} for k, v in _top(coins.items(), reverse=False) if v < 0],
        "exits": [{"reason": k, "n": v} for k, v in _top(exits.items())],
        "tags": [{"tag": k, "n": v} for k, v in _top(tags.items())],
    }


def build(d, now=None):
    now = time.time() if now is None else now
    out = {"version": VERSION, "paper_only": True, "made": int(now), "btc_counts": False, "day_rule": "day starts 5:30 AM IST = 00:00 UTC"}
    try:
        rows, bad = LS.read_own(d)
        rows = [t for t in rows if not _is_btc(t) and _num(t.get("closed_at_ts"))]
        t0 = int(now // DAY) * DAY                                # start of today (00:00 UTC)
        days = []
        for i in range(6, -1, -1):
            a = t0 - i * DAY
            r = [t for t in rows if a <= _num(t["closed_at_ts"]) < a + DAY]
            b = block(r)
            lab = time.strftime("%a %d", time.gmtime(a + 3600))
            days.append({"day": time.strftime("%Y-%m-%d", time.gmtime(a + 3600)), "label": lab, "net": b["net"], "n": b["n"], "wins": b.get("wins", 0)})
        out.update(today=block([t for t in rows if _num(t["closed_at_ts"]) >= t0]), week=block([t for t in rows if _num(t["closed_at_ts"]) >= t0 - 6 * DAY]), days=days,
                   n_all=len(rows), source_note=("archive: " + bad) if bad and bad != "ok" else "")
    except Exception as e:
        out["state"], out["text"] = "error", "%s: %s" % (type(e).__name__, str(e)[:80])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper today / 7 days (paper only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    a = ap.parse_args(argv)
    print(json.dumps(build(a.data), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
