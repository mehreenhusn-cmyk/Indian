"""Part U3 (Z2a): the Dual Bot DESK numbers for the app - small, read-only, from the permanent archive (dual_archive.db).

Trading day = 00:00 UTC (= 5:30 AM IST). For trades opened since the day started we count, per source and per timeframe:
  n = finished trades, wins, net = USDT (margin x ROI% / 100: BTC 1000, other coins 100, same as dual_lab._mg), open = trades still open.
Source (read-only, from universe_log.json, no trade row is changed): today = coin in today's top list (or BTC), d7 = coin that is
on the list ONLY because it was a top coin in the last 7 days, other = trade older than the log / coin left the list.
Also returns tags {symbol: today|d7} for the coins on the list now, so the app can put a source chip on any open trade.
Never raises. Result cached 8 seconds. Route: GET /api/dual_desk.
"""
import os
import sqlite3
import time

import btc_lab as BL
import dual_today as DT
import universe_7d as U

BTC, BTC_MARGIN, MARGIN = "BTCUSDT", 1000.0, 100.0
TFS = ("5m", "15m")
GROUPS = ("today", "d7", "other")
_C = {"t": 0.0, "v": None}


def _blank():
    return {g: {tf: {"n": 0, "wins": 0, "net": 0.0, "open": 0} for tf in TFS} for g in GROUPS}


def _add(groups, grp, tf, status, net, sym):
    if tf not in TFS:
        return
    c = groups[grp][tf]
    if status == "open":
        c["open"] += 1
    elif status == "closed" and net is not None:
        c["n"] += 1
        c["wins"] += 1 if net > 0 else 0
        c["net"] += (BTC_MARGIN if sym == BTC else MARGIN) * net / 100.0


def desk(base=None, now_s=None):
    now = time.time() if now_s is None else now_s
    if base is None and now_s is None and _C["v"] is not None and now - _C["t"] < 8:
        return dict(_C["v"])
    day_ms = U.day_start_ms(now)
    out = {"state": "none", "day": U.day_name(day_ms), "since_ms": day_ms, "groups": _blank(), "tags": {}, "err": ""}
    btc = {"btc": {tf: {"n": 0, "wins": 0, "net": 0.0, "open": 0} for tf in TFS}}      # R16b: BTC is the indicator test coin, kept OUT of the groups (own numbers here)
    try:
        log = U.load_log(base)
        e = log.get(out["day"]) or {}
        out["tags"] = dict({s: "d7" for s in e.get("extra", [])}, **{s: "today" for s in e.get("today", [])})
        path = os.path.join(U._dir(base), "dual_archive.db")
        if os.path.exists(path):
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
            try:
                for sym, tf, t, status, net in con.execute("SELECT sym, tf, t, status, net FROM trades WHERE t >= ?", (day_ms,)):
                    if BL.skip(sym, base):
                        _add(btc, "btc", tf, status, net, sym)
                    else:
                        _add(out["groups"], U.tag_of(sym, t, log), tf, status, net, sym)
            finally:
                con.close()
            out["state"] = "ok"
        out["today"] = DT.today(base, now_s)         # R16a: THE one "Dual today" (closed since 00:00 UTC, alts only, BTC apart). The Dashboard reads this; the Dual screen gets the same numbers through dual_today.overlay
        out["btc"], out["btc_in_counts"] = btc["btc"], BL.counts_btc(base)
        for g in list(out["groups"].values()) + [btc["btc"]]:           # round once at the end
            for c in g.values():
                c["net"] = round(c["net"], 2)
    except Exception as ex:
        out["state"], out["err"] = "error", "%s: %s" % (type(ex).__name__, str(ex)[:100])
    if base is None and now_s is None:
        _C["t"], _C["v"] = now, dict(out)
    return out
