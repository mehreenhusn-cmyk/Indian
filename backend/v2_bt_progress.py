"""v2_bt_progress.py - Part L1: LEARNING PROGRESS of the Brain (backend, read-only). The owner's question: "how many trades did the Brain take today, how many were profit and loss, and is it slowly making FEWER mistakes and MORE profit?"
For ONE source (PAPER by default; REPLAY and SHADOW are never added to it). Everything is counted from the Brain's CLOSED pretend trades, net of fee + slippage, in USDT. Nothing is saved, nothing is traded.
Parts of the answer:
  today     UTC day = the app's day: closed trades, profit trades, loss trades (counts), net, the Brain's decisions of the day (taken / waited / skipped / no opinion), open trades now, ONE plain sentence.
  days      the last 30 days, newest first: trades, profit, loss, net (days without a trade are left out).
  weeks     the last 5 weeks (7 days each, newest first): trades, profit, loss, net, average per trade and LOSING TRADES PER 10 (the 'mistake rate', a count, not a win-rate percent).
  trend     all closed trades split into an OLDER and a NEWER half: IMPROVING / WORSE / NOT CLEAR need 60+ trades (30 per half); 30 to 59 trades give only an EARLY HINT; under 30 = NOT ENOUGH DATA.
            IMPROVING = the newer half has the better average AND no higher share of losing trades. WORSE = the opposite on both. Luck can explain a lot of this, and the sentence says so.
  mistakes  the groups (market state + side, SD zone, SD width, TSI, Z, histogram, agreement, clash; 30+ trades each) that LOSE in BOTH halves of their history. In plain words, the 3 biggest.
  fixed     groups (30+ trades) whose OLDER half lost but whose NEWER half is positive: 'was a mistake, looks better now'. NOT proof; it needs more trades. And 'worse' = the opposite.
  learned   the 2 strongest groups that WIN in both halves.
Honest: no win-rate headline, no forecast, no promise that mistakes fall. The Brain never changes a rule by itself; BT-01 is frozen. Starting limits (30 trades) are NV (not validated).
Reads v2_brain_trader.db read-only. No network, no write, no trading import. The route /api/v2/brain_progress (api/v2_data.py) calls build().
Run (Termux, optional):  python3 backend/v2_bt_progress.py [--data DIR] [--source PAPER]  -> the plain lines."""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_review as RV
import v2_bt_store as B

VERSION = "v2_bt_progress 1 (Part L1)"
DAY = 86400
DAYS, WEEKS, TREND_N = 30, 5, 2 * RV.MIN_N


def counts(trades):
    """-> trades, profit trades, loss trades, net, average, losing trades per 10 (None without trades). A trade with net 0 is neither."""
    n = len(trades)
    net = sum(t["net"] for t in trades)
    loss = sum(1 for t in trades if t["net"] < 0)
    return {"trades": n, "profit": sum(1 for t in trades if t["net"] > 0), "loss": loss, "net_usdt": round(net, 2), "avg_usdt": round(net / n, 3) if n else None,
            "loss_per_10": round(loss / n * 10.0, 1) if n else None}


def trend(trades):
    """Older half vs newer half of ALL closed trades (by time). The word says how sure it is."""
    n = len(trades)
    old, new = counts(trades[:n // 2]), counts(trades[n // 2:])
    out = {"word": "NOT ENOUGH DATA", "older": old, "newer": new, "need": TREND_N, "text": "Only %d closed trades so far. The Brain needs %d (30 in each half) before it may say better or worse, and %d for an early hint." % (n, TREND_N, RV.MIN_N)}
    if n < RV.MIN_N:
        return out
    up = new["avg_usdt"] > old["avg_usdt"] and new["loss_per_10"] <= old["loss_per_10"]
    down = new["avg_usdt"] < old["avg_usdt"] and new["loss_per_10"] >= old["loss_per_10"]
    d = "better" if up else "worse" if down else "mixed"
    facts = "Older half: %+.3f USDT per trade, %.1f losing trades per 10. Newer half: %+.3f USDT per trade, %.1f losing per 10." % (old["avg_usdt"], old["loss_per_10"], new["avg_usdt"], new["loss_per_10"])
    if n < TREND_N:
        out.update(word="EARLY HINT", text="%s Early hint only (%d trades): the newer half looks %s. Luck can explain this; %d trades are needed for a real answer." % (facts, n, d, TREND_N))
    else:
        out.update(word="IMPROVING" if up else "WORSE" if down else "NOT CLEAR", text="%s %s Luck can still explain part of it." % (facts, "The newer half is better on both." if up else "The newer half is worse on both." if down else "The two numbers do not agree, so there is no clear answer."))
    return out


def groups_report(trades):
    """-> mistakes, fixed, worse, learned (plain sentences) from the groups with 30+ trades."""
    rows = []
    for dim, title in RV.DIMS:
        for lab, ts in RV.groups(trades, dim).items():
            g = RV.grade([(t["ts"], t["net"]) for t in ts])
            if g["n"] >= RV.MIN_N:
                rows.append(dict(g, label=lab, dim=title))
    f = "%s - %s: %+.2f USDT in %d trades (older half %+.2f, newer half %+.2f)."
    s = lambda r: f % (r["dim"], r["label"], r["net_usdt"], r["n"], r["older_net"], r["newer_net"])
    bad = sorted((r for r in rows if r["verdict"] == "AVOID"), key=lambda r: r["net_usdt"])[:3]
    good = sorted((r for r in rows if r["verdict"] == "USE"), key=lambda r: -r["net_usdt"])[:2]
    fixed = sorted((r for r in rows if r["older_net"] < 0 < r["newer_net"]), key=lambda r: -r["newer_net"])[:3]
    worse = sorted((r for r in rows if r["older_net"] > 0 > r["newer_net"]), key=lambda r: r["newer_net"])[:3]
    return [s(r) for r in bad], [s(r) for r in fixed], [s(r) for r in worse], [s(r) for r in good]


def today_of(con, source, trades, a, b):
    mine = [t for t in trades if a <= t["ts"] < b]
    cnt = dict(con.execute("SELECT decision, COUNT(*) FROM bt_decision WHERE source=? AND close_ts>=? AND close_ts<? GROUP BY decision", (source, a, b)).fetchall())
    still = con.execute("SELECT COUNT(*) FROM bt_trade_open o LEFT JOIN bt_trade_close c ON c.trade_id=o.trade_id WHERE o.source=? AND c.trade_id IS NULL", (source,)).fetchone()[0]
    c = counts(mine)
    c.update(decisions={"taken": cnt.get("OPEN_LONG", 0) + cnt.get("OPEN_SHORT", 0), "waited": cnt.get("WAIT", 0), "skipped": cnt.get("SKIP", 0), "no_opinion": cnt.get("NO_OPINION", 0)}, open_now=still)
    c["text"] = ("Today the Brain closed %d trades: %d profit, %d loss, net %+.2f USDT. %d still open." % (c["trades"], c["profit"], c["loss"], c["net_usdt"], still)) if c["trades"] else "The Brain has not closed a trade today. %d still open." % still
    return c


def build(data_dir, source="PAPER", now=None):
    if source not in B.SOURCES:
        raise ValueError("source must be REPLAY, PAPER or SHADOW")
    now = int(time.time() if now is None else now)
    con = B.open_ro(data_dir)
    if con is None:
        return {"ready": False, "framework": VERSION, "source": source, "live": "LOCKED", "note": "No Brain Trader file yet: nothing has been saved. Run the Brain tick first."}
    try:
        trades = RV.closed_trades(con, source)
        end = now - now % DAY + DAY
        today = today_of(con, source, trades, end - DAY, end)
    finally:
        con.close()
    days = []
    for k in range(DAYS):
        mine = [t for t in trades if end - (k + 1) * DAY <= t["ts"] < end - k * DAY]
        if mine:
            days.append(dict(counts(mine), day=time.strftime("%Y-%m-%d", time.gmtime(end - (k + 1) * DAY))))
    weeks = [dict(counts([t for t in trades if end - (k + 1) * 7 * DAY <= t["ts"] < end - k * 7 * DAY]), week=k, from_day=time.strftime("%Y-%m-%d", time.gmtime(end - (k + 1) * 7 * DAY))) for k in range(WEEKS)]
    mistakes, fixed, worse, learned = groups_report(trades)
    return {"ready": True, "framework": VERSION, "source": source, "live": "LOCKED", "all_closed": len(trades), "today": today, "days": days, "weeks": weeks, "trend": trend(trades),
            "mistakes": mistakes, "fixed": fixed, "worse": worse, "learned": learned,
            "note": "Closed pretend trades of ONE source, net of fee + slippage. 'Mistake' = a group that lost in both halves of its history (30+ trades). 'Fixed' is a hint, not proof. The Brain never changes BT-01 by itself and LIVE is locked."}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--source", default="PAPER", choices=B.SOURCES)
    a = ap.parse_args(argv)
    r = build(a.data, a.source)
    if not r["ready"]:
        print(r["note"])
        return 0
    print(r["today"]["text"])
    print("Trend: %s - %s" % (r["trend"]["word"], r["trend"]["text"]))
    for k in ("mistakes", "fixed", "worse", "learned"):
        for x in r[k]:
            print(" %s: %s" % (k.upper(), x))
    return 0


if __name__ == "__main__":
    sys.exit(main())
