"""v2_bt_verdict.py - Part 91a: SIMPLE RESULTS (backend, read-only). ONE answer for the Simple Results screen: is the Brain making money, in plain words?
Owner complaint (31 Oct): the old Results screen shows too much data. This file gives ONE verdict word and a few plain numbers; every detail stays in the old screens.
Parts of the answer (nothing new is invented, the closed trades come from v2_bt_review.closed_trades, net of fee + slippage, pretend money):
  verdict   PROFIT / LOSS / MIXED / NOT ENOUGH DATA + ONE sentence. Same rule as the whole Brain (v2_bt_review.grade): 30+ closed trades AND the same sign in the older and the newer half.
            PROFIT is never 'safe': if the worst dip is bigger than the profit, the sentence says so.
  numbers   closed trades, net USDT, average per trade (expectancy), wins and losses (counts only, no win-rate percent), today, last 7 days
  risk      max drawdown (biggest fall from a peak of the equity line, USDT) and the losing streak (longest and current, in a row)
  equity    the running net line, at most 60 points (the screen draws it)
  use / stop  plain USE and STOP sentences from the groups the night review already judged (30+ trades, same sign in both halves). Evidence, not an order.
  tabs      closed trades per source: PAPER / SHADOW / REPLAY. Sources are NEVER added together. LIVE is locked and not listed as a tab.
Reads v2_brain_trader.db read-only. No network, no write, no trading import. Starting limit (30 trades) is NV, not validated.
Run (Termux, optional):  python3 backend/v2_bt_verdict.py [--data DIR] [--source PAPER]  -> the plain lines."""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_review as RV
import v2_bt_store as B

VERSION = "v2_bt_verdict 1 (Part 91a)"
DAY = 86400
POINTS = 60                                             # equity line: at most this many points
WORD = {"USE": "PROFIT", "AVOID": "LOSS", "MIXED": "MIXED", "NOT ENOUGH DATA": "NOT ENOUGH DATA"}


def equity(trades):
    """Running net after each closed trade, oldest first. -> [(ts, running)], first point is 0 before the first trade."""
    run, out = 0.0, []
    for t in trades:
        run += t["net"]
        out.append((t["ts"], run))
    return out


def drawdown(eq):
    """Biggest fall from a peak of the equity line (the line starts at 0, so the first peak is 0). -> max, current (both >= 0, USDT) and when the max fall ended."""
    peak, worst, worst_ts, cur = 0.0, 0.0, None, 0.0
    for ts, v in eq:
        peak = max(peak, v)
        cur = peak - v
        if cur > worst:
            worst, worst_ts = cur, ts
    return {"max_usdt": round(worst, 2), "current_usdt": round(cur, 2), "ended_ts": worst_ts}


def streak(trades):
    """Losing trades in a row: the longest ever and the one running now (a trade with net below 0 is a loss)."""
    best = run = 0
    for t in trades:
        run = run + 1 if t["net"] < 0 else 0
        best = max(best, run)
    return {"longest": best, "current": run}


def thin(eq):
    """At most POINTS points, evenly spread, the first and the last always kept."""
    pts = [{"ts": None, "v": 0.0}] + [{"ts": ts, "v": round(v, 2)} for ts, v in eq]
    if len(pts) <= POINTS:
        return pts
    step = (len(pts) - 1) / float(POINTS - 1)
    return [pts[int(round(i * step))] for i in range(POINTS)]


def sentence(g, dd, n):
    """ONE honest sentence for the verdict card."""
    if g["verdict"] == "NOT ENOUGH DATA":
        return "Only %d closed trades so far. The Brain needs %d before it may say profit or loss." % (n, RV.MIN_N)
    if g["verdict"] == "MIXED":
        return "The older and the newer half of the trades disagree, so there is no clear answer yet."
    if g["verdict"] == "USE":
        s = "Net %+.2f USDT after fee in %d pretend trades, and both halves of the history are above zero." % (g["net_usdt"], n)
        return s + (" But the worst dip (%.2f USDT) is bigger than the profit." % dd["max_usdt"] if dd["max_usdt"] > g["net_usdt"] else "")
    return "Net %+.2f USDT after fee in %d pretend trades, and both halves of the history are below zero." % (g["net_usdt"], n)


def lines(trades, now):
    """Plain USE / STOP sentences from the night-review groups (30+ trades, same sign in both halves), the strongest 3 of each."""
    rows = [dict(r, dim=d["title"]) for d in RV.review(trades, now - now % DAY) for r in d["rows"]]
    use = sorted((r for r in rows if r["verdict"] == "USE"), key=lambda r: -r["net_usdt"])[:3]
    stop = sorted((r for r in rows if r["verdict"] == "AVOID"), key=lambda r: r["net_usdt"])[:3]
    f = "%s - %s: %+.2f USDT in %d trades, same in both halves."
    return [f % (r["dim"], r["label"], r["net_usdt"], r["n"]) for r in use], [f % (r["dim"], r["label"], r["net_usdt"], r["n"]) for r in stop]


def build(data_dir, source="PAPER", now=None):
    if source not in B.SOURCES:
        raise ValueError("source must be REPLAY, PAPER or SHADOW")
    now = int(time.time() if now is None else now)
    con = B.open_ro(data_dir)
    if con is None:
        return {"ready": False, "framework": VERSION, "source": source, "live": "LOCKED", "note": "No Brain Trader file yet: nothing has been saved. Run the Brain tick first."}
    try:
        trades = RV.closed_trades(con, source)
    finally:
        con.close()
    per = B.status(data_dir)["per_source"]
    g = RV.grade([(t["ts"], t["net"]) for t in trades])
    eq = equity(trades)
    dd, st = drawdown(eq), streak(trades)
    wk = [t for t in trades if t["ts"] >= now - 7 * DAY]
    today = [t for t in trades if t["ts"] >= now - now % DAY]
    use, stop = lines(trades, now)
    return {"ready": True, "framework": VERSION, "source": source, "live": "LOCKED",
            "tabs": [{"source": s, "closed": per[s]["closed"]} for s in B.SOURCES],
            "verdict": {"word": WORD[g["verdict"]], "text": sentence(g, dd, len(trades))},
            "numbers": {"trades": len(trades), "net_usdt": g["net_usdt"], "avg_usdt": g["avg_usdt"], "wins": sum(1 for t in trades if t["net"] > 0), "losses": sum(1 for t in trades if t["net"] < 0),
                        "older_net": g["older_net"], "newer_net": g["newer_net"], "today_usdt": round(sum(t["net"] for t in today), 2), "week_usdt": round(sum(t["net"] for t in wk), 2),
                        "week_trades": len(wk)},
            "risk": {"drawdown": dd, "streak": st}, "equity": thin(eq), "use": use, "stop": stop,
            "note": "Closed pretend trades of ONE source, net of fee + slippage. PROFIT / LOSS need 30+ trades and the same sign in both halves. Evidence, not an order; it never changes the live bot."}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--source", default="PAPER", choices=B.SOURCES)
    a = ap.parse_args(argv)
    r = build(a.data, a.source)
    if not r["ready"]:
        print(r["note"])
        return 0
    print("%s: %s" % (r["verdict"]["word"], r["verdict"]["text"]))
    n, k = r["numbers"], r["risk"]
    print("trades %d, net %+.2f USDT, avg %+.3f per trade, worst dip %.2f, losing streak %d (now %d)" % (n["trades"], n["net_usdt"], n["avg_usdt"], k["drawdown"]["max_usdt"], k["streak"]["longest"], k["streak"]["current"]))
    for x in r["use"]:
        print(" USE:", x)
    for x in r["stop"]:
        print(" STOP:", x)
    return 0


if __name__ == "__main__":
    sys.exit(main())
