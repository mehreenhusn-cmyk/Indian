"""
daily_report.py - "What happened yesterday?" in plain English. READ-ONLY.

Why it exists: an update / alert that was shown once used to scroll away or be filtered out (the Alerts list is a
rolling list of 250 and the System notices are hidden by default). This report is NOT an alert: it is rebuilt from the
PERMANENT closed-trade archive every time, so it can never disappear. Touching the screen cannot remove it.

The bot's trading day starts at 00:00 UTC (= 5:30 AM IST), the same day border the Alerts screen uses.
Never opens, closes or changes a trade. Never raises.
"""
import time

from . import trade_store

DAY_S = 86400


def _f(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def _tag(t):
    r = str(t.get("reason") or t.get("exit_reason") or t.get("close_reason") or "").upper()
    if r.startswith("TP"):
        return "Target hit"
    if r == "SL":
        return "Stop loss (trailed)" if t.get("trailed_sl") else "Stop loss"
    if r == "REVERSED":
        return "Reversed (opposite signal)"
    if r == "MANUAL":
        return "Closed by hand"
    return "Other"


def _day(rows):
    n = len(rows)
    pnl = [_f(t.get("pnl_usdt")) for t in rows]
    wins = sum(1 for x in pnl if x > 0)
    out = {"trades": n, "wins": wins, "losses": n - wins, "net": round(sum(pnl), 2),
           "win_rate": round(wins / n * 100.0, 1) if n else 0.0, "by_exit": [], "best": None, "worst": None}
    if not n:
        return out
    groups = {}
    for t, p in zip(rows, pnl):
        g = groups.setdefault(_tag(t), [0, 0.0])
        g[0] += 1
        g[1] += p
    out["by_exit"] = [{"name": k, "n": v[0], "net": round(v[1], 2)} for k, v in sorted(groups.items(), key=lambda kv: kv[1][1])]
    bi, wi = max(range(n), key=lambda i: pnl[i]), min(range(n), key=lambda i: pnl[i])
    out["best"] = {"sym": rows[bi].get("symbol"), "pnl": round(pnl[bi], 2)}
    out["worst"] = {"sym": rows[wi].get("symbol"), "pnl": round(pnl[wi], 2)}
    return out


def _words(name, d):
    if not d["trades"]:
        return "%s: the bot closed no trade." % name
    s = "%s: %d trades closed, %d won and %d lost, net %+.2f USDT." % (name, d["trades"], d["wins"], d["losses"], d["net"])
    if d["by_exit"]:
        w = d["by_exit"][0]
        if w["net"] < 0:
            s += " Most money was lost on '%s' (%d trades, %+.2f USDT)." % (w["name"], w["n"], w["net"])
    return s


def build(days=7):
    try:
        now = time.time()
        today0 = now - (now % DAY_S)
        start = today0 - (int(days) - 1) * DAY_S
        rows = [t for t in trade_store.get_all_closed(5000, net=True, live_view=True) if _f(t.get("closed_at_ts")) >= start]
        by = {}
        for t in rows:
            by.setdefault(int((_f(t.get("closed_at_ts")) - start) // DAY_S), []).append(t)
        hist = []
        for i in range(int(days) - 1, -1, -1):          # newest day first
            day0 = start + i * DAY_S
            d = _day(by.get(i, []))
            d["date"] = time.strftime("%Y-%m-%d", time.gmtime(day0))
            d["title"] = "Today" if i == int(days) - 1 else "Yesterday" if i == int(days) - 2 else time.strftime("%d %b", time.gmtime(day0))
            hist.append(d)
        today, yest = hist[0], hist[1] if len(hist) > 1 else None
        week = round(sum(h["net"] for h in hist), 2)
        return {"ts": now, "today": today, "yesterday": yest, "days": hist, "week_net": week,
                "headline": (_words("Yesterday", yest) if yest else ""), "today_line": _words("Today so far", today),
                "note": "Built from the permanent trade archive, so it stays here even when alerts scroll away. "
                        "The trading day starts at 5:30 AM IST."}
    except Exception as e:
        return {"ts": time.time(), "today": None, "yesterday": None, "days": [], "week_net": 0.0, "headline": "",
                "today_line": "", "error": "%s: %s" % (type(e).__name__, e)}
