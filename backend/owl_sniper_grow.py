"""owl_sniper_grow.py - OwlSniper GROWTH PLAN + GOOD / BAD DAY THROTTLE (Part 33 / FILE 28). PAPER ONLY, REPORT ONLY, PURE sums: opens nothing, closes nothing, writes nothing, no network, no order code. LIVE_ALLOWED is False.
Two questions: (1) "How is the small account growing, day by day and week by week?" (2) "Is today a good day or a bad day, so how many trades may Sniper take now?"
Input = closed paper trades the CALLER gives: [{ts (seconds or ms, close time), pnl_usdt, r_net (result in R after cost)}]. Books are never added: pass ONE book (Sniper paper) per call. This file measures nothing else.
THROTTLE (rules, the first that fits wins; limits are starting values the owner may tune inside LIMITS):
  STOP   = the daily loss limit is hit (today <= -daily_loss_pct of the start-of-day capital) OR LOSS_STREAK (5) losses in a row (kill criterion) -> no new trade today.
  SLOW   = today <= -1.5 R OR 3 losses in a row -> bad day: max open 1, at most 4 new trades, size HALF (risk x 0.5; smaller is always allowed).
  PUSH   = today >= +2 R AND the last trade is not a loss AND at least 3 trades today -> good day: ONE more open trade and more trades per day. The RISK PER TRADE IS NEVER RAISED (small capital changes only the count, never the risk rules).
  NORMAL = otherwise.
  Fewer than MIN_TODAY (3) trades today and no stop rule hit = NORMAL (one trade does not make a good or bad day).
  The answer carries `over` = values for owl_sniper_capital.cfg(over): {max_open, risk_pct}. The caller passes them on; the capital file still clamps them.
PLAN (compounding): from the MEASURED history only. Needs 30 closed trades and 3 days, else NOT_ENOUGH_DATA and NO number. Then: avg R per trade after cost (+ low end = mean - 2 SE), trades per day (days with data only), and the growth per day if the edge holds = avg R x risk % x trades/day, compounded for 7 and 30 days. It is a "what it would be IF the last measured edge holds" line, never a promise. If the low end of the avg R is not above 0 the plan says NO PROVEN EDGE and shows no growth number. A losing history shows its real loss.
VIEW: per day and per week (UTC): trades, wins, net USDT, net R, capital at the end (start capital + running sum). Days without trades are not invented.
API: day_key(ts), throttle(today_trades, day_start, c=None, cap_cfg=None), daily(trades, start_capital), weekly(daily_rows), plan(trades, capital, risk_pct=1.0), report(trades, start_capital, day_start=None, now=None, c=None, cap_cfg=None). CLI:
  python3 backend/owl_sniper_grow.py --file FILE.json   -> FILE = {"trades": [...], "start_capital": 10, "day_start": 10.2}"""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "owl_sniper_grow 1 (Part 33)"
LIVE_ALLOWED = False
MIN_TRADES = 30
MIN_DAYS = 3
MIN_TODAY = 3
DEFAULTS = {"slow_r": 1.5, "push_r": 2.0, "loss_streak": 5, "slow_streak": 3, "daily_loss_pct": 3.0, "base_trades": 10, "push_trades": 15, "slow_trades": 4}
LIMITS = {"slow_r": (0.5, 3.0), "push_r": (1.0, 5.0), "loss_streak": (3, 8), "slow_streak": (2, 5), "daily_loss_pct": (1.0, 5.0), "base_trades": (3, 30), "push_trades": (3, 40), "slow_trades": (1, 10)}


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def cfg(over=None):
    out = {}
    for k, dv in DEFAULTS.items():
        v = _num((over or {}).get(k))
        lo, hi = LIMITS[k]
        out[k] = dv if v is None else min(max(v, lo), hi)
    for k in ("loss_streak", "slow_streak", "base_trades", "push_trades", "slow_trades"):
        out[k] = int(out[k])
    return out


def day_key(ts):
    """UTC day 'YYYY-MM-DD' from seconds or ms; None when the time is not real."""
    t = _num(ts)
    if t is None or t <= 0:
        return None
    if t > 1e11:
        t /= 1000.0
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def _clean(trades):
    """-> list of (ts_seconds, pnl_usdt, r_net) sorted by time; rows without a real time / result are dropped (never guessed)."""
    out = []
    for t in trades or ():
        if not isinstance(t, dict):
            continue
        ts, p, r = _num(t.get("ts")), _num(t.get("pnl_usdt")), _num(t.get("r_net"))
        if ts is None or ts <= 0 or p is None or r is None:
            continue
        out.append((ts / 1000.0 if ts > 1e11 else ts, p, r))
    out.sort(key=lambda x: x[0])
    return out


def _streak(rows):
    n = 0
    for _, p, r in reversed(rows):
        if r < 0:
            n += 1
        else:
            break
    return n


def throttle(today_trades, day_start, c=None, cap_cfg=None):
    """Today's trades (closed, ONE book) -> level STOP / SLOW / NORMAL / PUSH + what Sniper may do now. `over` goes to owl_sniper_capital.cfg."""
    c = c or cfg()
    cc = cap_cfg or {}
    base_open, base_risk = int(cc.get("max_open", 3)), float(cc.get("risk_pct", 1.0))
    rows = _clean(today_trades)
    n, net_p, net_r = len(rows), sum(x[1] for x in rows), sum(x[2] for x in rows)
    ds, streak = _num(day_start), _streak(rows)
    base = {"version": VERSION, "trades_today": n, "net_usdt": round(net_p, 4), "net_r": round(net_r, 3), "loss_streak": streak, "paper_only": True, "live_allowed": LIVE_ALLOWED, "report_only": True}

    def out(level, text, mx, risk, tmax):
        d = dict(base, level=level, text=text, lines=[text], max_trades_today=tmax, new_trades_left=max(tmax - n, 0),
                 over={"max_open": mx, "risk_pct": round(risk, 4)})
        return d
    if ds is not None and ds > 0 and net_p <= -ds * c["daily_loss_pct"] / 100.0:
        return out("STOP", "Daily loss limit reached (%+.2f USDT): no new trade today." % net_p, 0, base_risk, n)
    if streak >= c["loss_streak"]:
        return out("STOP", "%d losses in a row: kill rule, no new trade today. Look at the Self Log before tomorrow." % streak, 0, base_risk, n)
    if n < MIN_TODAY:
        return out("NORMAL", "Normal day so far (%d trade%s today, too few to call it good or bad)." % (n, "" if n == 1 else "s"), base_open, base_risk, c["base_trades"])
    if net_r <= -c["slow_r"] or streak >= c["slow_streak"]:
        why = "%d losses in a row" % streak if streak >= c["slow_streak"] else "%+.1f R today" % net_r
        return out("SLOW", "Bad day (%s): fewer trades (max 1 open, %d for today) and half size." % (why, c["slow_trades"]), 1, base_risk * 0.5, c["slow_trades"])
    if net_r >= c["push_r"] and rows[-1][2] >= 0:
        return out("PUSH", "Good day (%+.1f R, %d trades): one more open trade allowed (max %d, %d for today). Risk per trade is NOT raised." % (net_r, n, min(base_open + 1, 5), c["push_trades"]), min(base_open + 1, 5), base_risk, c["push_trades"])
    return out("NORMAL", "Normal day (%+.1f R, %d trades)." % (net_r, n), base_open, base_risk, c["base_trades"])


def daily(trades, start_capital):
    """Per UTC day: trades, wins, net USDT, net R, capital at the end of the day. Only days with trades."""
    rows, cap = _clean(trades), _num(start_capital)
    days = {}
    for ts, p, r in rows:
        k = day_key(ts)
        d = days.setdefault(k, {"day": k, "trades": 0, "wins": 0, "net_usdt": 0.0, "net_r": 0.0})
        d["trades"] += 1
        d["wins"] += 1 if r > 0 else 0
        d["net_usdt"] += p
        d["net_r"] += r
    out, run = [], cap
    for k in sorted(days):
        d = days[k]
        run = None if run is None else run + d["net_usdt"]
        d.update(net_usdt=round(d["net_usdt"], 4), net_r=round(d["net_r"], 3), capital_end=None if run is None else round(run, 4))
        d["win_pct"] = round(100.0 * d["wins"] / d["trades"], 1)
        out.append(d)
    return out


def _week(day):
    t = time.strptime(day, "%Y-%m-%d")
    y, w, _ = (t.tm_year, int(time.strftime("%W", t)), 0)
    return "%d-W%02d" % (y, w)


def weekly(daily_rows):
    """Daily rows -> weekly rows (Monday start, UTC)."""
    wk = {}
    for d in daily_rows or ():
        k = _week(d["day"])
        w = wk.setdefault(k, {"week": k, "days": 0, "trades": 0, "wins": 0, "net_usdt": 0.0, "net_r": 0.0, "capital_end": None})
        w["days"] += 1
        w["trades"] += d["trades"]
        w["wins"] += d["wins"]
        w["net_usdt"] += d["net_usdt"]
        w["net_r"] += d["net_r"]
        w["capital_end"] = d["capital_end"]
    out = []
    for k in sorted(wk):
        w = wk[k]
        w.update(net_usdt=round(w["net_usdt"], 4), net_r=round(w["net_r"], 3), win_pct=round(100.0 * w["wins"] / w["trades"], 1))
        out.append(w)
    return out


def plan(trades, capital, risk_pct=1.0):
    """Compounding line from the MEASURED history only. Never a promise; no number below 30 trades / 3 days."""
    rows = _clean(trades)
    days = sorted({day_key(x[0]) for x in rows})
    base = {"version": VERSION, "paper_only": True, "live_allowed": LIVE_ALLOWED, "report_only": True, "n": len(rows), "days": len(days)}
    if len(rows) < MIN_TRADES or len(days) < MIN_DAYS:
        t = "NOT ENOUGH DATA for a growth plan: %d trades on %d days (needs %d trades on %d days). No number is shown." % (len(rows), len(days), MIN_TRADES, MIN_DAYS)
        return dict(base, state="NOT_ENOUGH_DATA", text=t, lines=[t])
    rs = [x[2] for x in rows]
    m = sum(rs) / len(rs)
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (len(rs) - 1))
    low = m - 2.0 * sd / math.sqrt(len(rs))
    tpd = len(rows) / float(len(days))
    base.update(avg_r=round(m, 4), avg_r_low=round(low, 4), trades_per_day=round(tpd, 2))
    cap, rp = _num(capital), (_num(risk_pct) or 1.0)
    if low <= 0:
        t = "NO PROVEN EDGE yet: avg %+.2f R per trade, low end %+.2f R (not above 0) over %d trades. No growth number is shown; the plan is to keep learning in paper." % (m, low, len(rows))
        return dict(base, state="NO_EDGE", text=t, lines=[t])
    g = m * rp / 100.0 * tpd
    base.update(growth_per_day_pct=round(100.0 * g, 3))
    rows7 = {}
    for nd in (7, 30):
        rows7["d%d" % nd] = None if cap is None else round(cap * (1.0 + g) ** nd, 2)
    lg = low * rp / 100.0 * tpd
    t = "IF the measured edge holds (avg %+.2f R, low end %+.2f R, %.1f trades/day, risk %.2f%%): about %+.2f%% per day." % (m, low, tpd, rp, 100.0 * g)
    lines = [t]
    if cap is not None:
        lines.append("From %.2f USDT: about %.2f in 7 days, %.2f in 30 days (low-end case: %.2f / %.2f). Rough, paper, not a promise." % (cap, rows7["d7"], rows7["d30"], cap * (1.0 + lg) ** 7, cap * (1.0 + lg) ** 30))
    return dict(base, state="OK", text=t, lines=lines, projection=rows7, projection_low={"d7": None if cap is None else round(cap * (1.0 + lg) ** 7, 2), "d30": None if cap is None else round(cap * (1.0 + lg) ** 30, 2)})


def report(trades, start_capital, day_start=None, now=None, c=None, cap_cfg=None):
    """Everything on one card: today's throttle, the plan, daily + weekly view. Reads only what it is given."""
    c = c or cfg()
    today = day_key(now if now is not None else time.time())
    t_today = [t for t in (trades or ()) if isinstance(t, dict) and day_key(t.get("ts")) == today]
    dly = daily(trades, start_capital)
    cap_now = dly[-1]["capital_end"] if dly else _num(start_capital)
    th = throttle(t_today, day_start if day_start is not None else cap_now, c, cap_cfg)
    pl = plan(trades, cap_now)
    return {"version": VERSION, "paper_only": True, "live_allowed": LIVE_ALLOWED, "report_only": True, "capital_now": cap_now, "throttle": th, "plan": pl,
            "daily": dly[-30:], "weekly": weekly(dly)[-12:], "lines": th["lines"] + pl["lines"]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper growth plan + day throttle (paper only, pure sums)")
    ap.add_argument("--file", required=True)
    a = ap.parse_args(argv)
    with open(a.file) as f:
        d = json.load(f)
    print(json.dumps(report(d.get("trades"), d.get("start_capital"), d.get("day_start")), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
