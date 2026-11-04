"""Part U5 (Z3a): the Brain card "Edge by universe" - do the 7-day coins earn more or less than today's coins, and what kind of day was it.

READ-ONLY. Reads finished Dual Bot trades of the last WINDOW_DAYS days from the permanent archive (dual_archive.db, opened read-only)
and sorts each one by the coin source tag from universe_log.json (today / d7 / other, see universe_7d.tag_of). Changes nothing, no new
indicator, no trading rule. Money = USDT (margin x ROI / 100: BTC 1000, other coins 100, same as dual_desk).

Day feel (cycle phase), judged from how LONG and SHORT trades did that UTC day (00:00 UTC = 5:30 AM IST):
  pump = longs made money and shorts lost | drift = shorts made money and longs lost | sideways = both lost | mixed = both made money
  early = fewer than MIN_DAY_N finished trades that day.
A group verdict needs MIN_N finished trades in BOTH groups, before that it only shows the numbers ("learning"). Never raises. Cached 60 s.
"""
import os
import sqlite3
import time

import btc_lab as BL
import universe_7d as U

BTC, BTC_MARGIN, MARGIN = "BTCUSDT", 1000.0, 100.0
WINDOW_DAYS, SHOW_DAYS, MIN_N, MIN_DAY_N, SAME = 10, 7, 30, 20, 0.05
_C = {"t": 0.0, "v": None}


def _usdt(sym, net):
    return (BTC_MARGIN if sym == BTC else MARGIN) * float(net) / 100.0


def phase_of(long_net, short_net, n):
    if n < MIN_DAY_N:
        return "early"
    if long_net > 0 and short_net < 0:
        return "pump"
    if short_net > 0 and long_net < 0:
        return "drift"
    if long_net <= 0 and short_net <= 0:
        return "sideways"
    return "mixed"


def _group(c):
    n = c["n"]
    return {"n": n, "wins": c["wins"], "win_pct": round(100.0 * c["wins"] / n) if n else None,
            "net": round(c["net"], 2), "avg": round(c["net"] / n, 3) if n else None}


def build(trades, log, now_s):
    """trades = [(sym, tf, t_ms, side, net_percent)] finished only. Pure function (the tests use it directly)."""
    g = {k: {"n": 0, "wins": 0, "net": 0.0} for k in ("today", "d7", "other")}
    day0 = U.day_start_ms(now_s)
    days = {U.day_name(day0 - i * U.DAY_MS): {"n": 0, "long": 0.0, "short": 0.0} for i in range(SHOW_DAYS)}
    for sym, tf, t, side, net in trades:
        if BL.skip(sym):                                  # R16b: BTC is the indicator test coin, never inside a Brain total
            continue
        u = _usdt(sym, net)
        c = g[U.tag_of(sym, t, log)]
        c["n"] += 1
        c["wins"] += 1 if u > 0 else 0
        c["net"] += u
        d = days.get(U.day_name(int(t)))
        if d is not None:
            d["n"] += 1
            d["long" if side and side > 0 else "short"] += u
    groups = {k: _group(v) for k, v in g.items()}
    out_days = [{"day": k, "n": v["n"], "long": round(v["long"], 2), "short": round(v["short"], 2),
                 "phase": phase_of(v["long"], v["short"], v["n"])} for k, v in sorted(days.items())]
    t_, d_ = groups["today"], groups["d7"]
    lines = []
    if t_["n"] >= MIN_N and d_["n"] >= MIN_N:
        diff = d_["avg"] - t_["avg"]
        word = "about the same as" if abs(diff) < SAME else ("better than" if diff > 0 else "worse than")
        lines.append("7-day coins earn %+.2f USDT per trade, %s today's coins (%+.2f)." % (d_["avg"], word, t_["avg"]))
        status = "ready"
    else:
        lines.append("Learning: needs %d finished trades in BOTH groups (today's coins %d, 7-day coins %d so far)." % (MIN_N, t_["n"], d_["n"]))
        status = "learning" if (t_["n"] + d_["n"]) else "none"
    if groups["other"]["n"]:
        lines.append("%d older trades (before the coin log started) are not in either group." % groups["other"]["n"])
    return {"status": status, "groups": groups, "days": out_days, "lines": lines, "need": MIN_N, "window_days": WINDOW_DAYS,
            "phase_now": out_days[-1]["phase"] if out_days else "early", "text": lines[0], "err": ""}


def report(base=None, now_s=None):
    now = time.time() if now_s is None else now_s
    if base is None and now_s is None and _C["v"] is not None and now - _C["t"] < 60:
        return dict(_C["v"])
    out = {"status": "none", "groups": {}, "days": [], "lines": [], "need": MIN_N, "window_days": WINDOW_DAYS, "phase_now": "early",
           "text": "Archive not started yet.", "err": ""}
    try:
        path = os.path.join(U._dir(base), "dual_archive.db")
        if os.path.exists(path):
            since = U.day_start_ms(now) - (WINDOW_DAYS - 1) * U.DAY_MS
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
            try:
                rows = con.execute("SELECT sym, tf, t, side, net FROM trades WHERE status = 'closed' AND net IS NOT NULL AND t >= ?", (since,)).fetchall()
            finally:
                con.close()
            out = build(rows, U.load_log(base), now)
    except Exception as ex:
        out["status"], out["err"] = "error", "%s: %s" % (type(ex).__name__, str(ex)[:100])
        out["text"] = "Edge by universe error: " + out["err"]
    if base is None and now_s is None:
        _C["t"], _C["v"] = now, dict(out)
    return out
