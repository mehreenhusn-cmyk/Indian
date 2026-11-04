"""btc_lab.py - BTC LAB (R16b). READ ONLY: dual_archive.db is opened read-only, nothing is written, no network, no order code. Never raises.
Owner rule 23: BTC is the INDICATOR TEST COIN. The owner only watches how the indicators behave on BTC. So BTC must NOT count in today P&L, trades, win rate, signals or equity of Dual, Brain or Sniper.
(The Main / Current Bot already keeps BTC in its own bucket: recovered_bot/trade_store.py. Not touched.)
This file does two things:
  1. skip(sym) = the ONE question every counter asks: "is this BTC, and is BTC kept out of the counts?" Used by dual_desk, brain_universe and owl_sniper_bridge_src.
     Owner switch: the file v2_btc_in_counts in the data folder. File present = BTC counts again everywhere (the old behaviour). File absent (default) = BTC is kept out.
  2. lab(base, now_s) = BTC's OWN numbers for the one "BTC Lab" card: signals seen, finished, wins, hit rate, USDT (margin 1000), per timeframe, last 7 days, today.
Never added to any total. Source: the permanent Dual archive (the only book that holds BTC trades for every day).
Route: GET /api/v2/btc_lab (api/btc_lab_route.py)."""
import os
import sqlite3
import time

import dual_today as DT
import universe_7d as U

VERSION = "btc_lab 1 (R16b)"
BTC, BTC_MARGIN = "BTCUSDT", 1000.0
SWITCH = "v2_btc_in_counts"
TFS = ("5m", "15m")
_S = {"t": 0.0, "v": False}


def counts_btc(base=None):
    """True when the owner switch file exists (BTC counts again). Cached 5 seconds. Never raises."""
    now = time.time()
    if base is None and now - _S["t"] < 5:
        return _S["v"]
    try:
        v = os.path.exists(os.path.join(os.path.realpath(U._dir(base)), SWITCH))
    except Exception:
        v = False
    if base is None:
        _S["t"], _S["v"] = now, v
    return v


def skip(sym, base=None):
    """True = this row is BTC and BTC is kept out of the counts (the default)."""
    return sym == BTC and not counts_btc(base)


def _blank():
    return {"seen": 0, "skipped": 0, "open": 0, "closed": 0, "wins": 0, "net_usdt": 0.0, "hit_pct": None,
            "by_tf": {tf: {"closed": 0, "wins": 0, "net_usdt": 0.0} for tf in TFS}}


def lab(base=None, now_s=None):
    """BTC's own numbers. state: ok / none (no archive yet) / error."""
    now = time.time() if now_s is None else now_s
    d0 = U.day_start_ms(now)
    out = {"state": "none", "version": VERSION, "symbol": BTC, "margin_usdt": BTC_MARGIN, "in_counts": counts_btc(base), "switch_file": SWITCH,
           "all": _blank(), "days": [], "today": {}, "err": "",
           "note": "BTC is the indicator test coin: these numbers are never added to Dual, Brain, Sniper or Dashboard totals."}
    try:
        days = {U.day_name(d0 - i * U.DAY_MS): {"day": U.day_name(d0 - i * U.DAY_MS), "closed": 0, "net_usdt": 0.0} for i in range(7)}
        path = os.path.join(U._dir(base), "dual_archive.db")
        if os.path.exists(path):
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
            try:
                a = out["all"]
                for tf, t, status, net in con.execute("SELECT tf, t, status, net FROM trades WHERE sym = ?", (BTC,)):
                    a["seen"] += 1
                    if status == "open":
                        a["open"] += 1
                    elif status in ("skipped", "skipped_done"):
                        a["skipped"] += 1
                    elif status == "closed" and net is not None:
                        usdt = BTC_MARGIN * net / 100.0
                        a["closed"] += 1
                        a["wins"] += 1 if net > 0 else 0
                        a["net_usdt"] += usdt
                        if tf in TFS:
                            b = a["by_tf"][tf]
                            b["closed"] += 1
                            b["wins"] += 1 if net > 0 else 0
                            b["net_usdt"] += usdt
                        dd = days.get(U.day_name(int(t or 0)))           # by the day the trade OPENED
                        if dd is not None:
                            dd["closed"] += 1
                            dd["net_usdt"] += usdt
            finally:
                con.close()
            out["state"] = "ok"
        a = out["all"]
        a["hit_pct"] = round(100.0 * a["wins"] / a["closed"]) if a["closed"] else None
        a["net_usdt"] = round(a["net_usdt"], 2)
        for b in a["by_tf"].values():
            b["net_usdt"] = round(b["net_usdt"], 2)
        out["days"] = [dict(v, net_usdt=round(v["net_usdt"], 2)) for v in days.values()]
        out["today"] = DT.today(base, now_s).get("btc") or {}
    except Exception as ex:
        out["state"], out["err"] = "error", "%s: %s" % (type(ex).__name__, str(ex)[:100])
    return out
