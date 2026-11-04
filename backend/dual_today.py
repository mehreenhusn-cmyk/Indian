"""dual_today.py - ONE SOURCE for "Dual Bot today" (R16a). READ ONLY: dual_archive.db is opened read-only, nothing is written, no network, no order code. Never raises.
Problem (owner screenshots, 5 Nov): the Dashboard said Dual today -3759.73 on 2974 trades, the Dual screen said -1696.19 on 466. Both are called "Today".
Cause found in code: the Dual screen reads dual_lab_data.json, and dual_lab.trim() keeps only the newest 600 trades there (trade_archive.py says so). With 600 rows shared by finished, open and skipped trades, "closed today" is cut short.
  The Dashboard reads dual_desk (the permanent archive, dual_archive.db: nothing is trimmed) but counted trades OPENED today, with BTC mixed into the sum.
Rule now (one definition, used by BOTH screens):
  day     = 00:00 UTC (= 5:30 AM IST), same as dual_lab._day_start_ms
  source  = dual_archive.db (permanent)
  closed  = finished trades whose CLOSE time (closed_at inside the saved trade, else the open time) is inside the day. A trade opened yesterday and closed today counts today.
  USDT    = margin x ROI% / 100 (alt coins 100, same as dual_lab._mg)
  BTC     = never inside the totals (owner rule 23: BTC is the indicator test coin). Its own numbers are under "btc" (margin 1000).
  open pnl and the open count stay with the live view (dual_lab): open trades are never trimmed, and only that view has the live price.
API: today(base=None, now_s=None) -> {state, day, since_ms, source, definition, alts {opened, closed, wins, losses, realized, skipped, open, by_tf}, btc {same}, err}
     overlay(view, base=None, now_s=None) -> the /api/dual_lab answer with summary.today replaced by these numbers (open_pnl kept, total = realized + open_pnl). Cached 8 seconds."""
import json
import os
import sqlite3
import time

import universe_7d as U

VERSION = "dual_today 1 (R16a)"
BTC, BTC_MARGIN, MARGIN = "BTCUSDT", 1000.0, 100.0
TFS = ("5m", "15m")
LOOKBACK_MS = 2 * 86400 * 1000          # a trade opened up to 2 days before the day start can still close today
DEFINITION = "Closed since 00:00 UTC (5:30 AM IST), by close time. Alt coins only; BTC has its own numbers. Source: permanent archive."
_C = {"t": 0.0, "v": None}


def _blank():
    z = lambda: {"opened": 0, "closed": 0, "wins": 0, "losses": 0, "realized": 0.0, "skipped": 0, "open": 0}
    out = z()
    out["by_tf"] = {tf: {"closed": 0, "wins": 0, "realized": 0.0} for tf in TFS}
    return out


def _closed_ms(t, js):
    """Close time in ms: closed_at of the saved trade (seconds), else the open time (the same fallback dual_lab uses)."""
    try:
        c = (json.loads(js) if js else {}).get("closed_at")
        if isinstance(c, (int, float)) and c > 0:
            return c * 1000.0
    except (TypeError, ValueError):
        pass
    return float(t or 0)


def today(base=None, now_s=None):
    now = time.time() if now_s is None else now_s
    if base is None and now_s is None and _C["v"] is not None and now - _C["t"] < 8:
        return dict(_C["v"])
    d0 = U.day_start_ms(now)
    out = {"state": "none", "day": U.day_name(d0), "since_ms": d0, "source": "dual_archive.db", "definition": DEFINITION, "alts": _blank(), "btc": _blank(), "err": ""}
    try:
        path = os.path.join(U._dir(base), "dual_archive.db")
        if os.path.exists(path):
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=5)
            try:
                for sym, tf, t, status, net, js in con.execute("SELECT sym, tf, t, status, net, js FROM trades WHERE t >= ?", (d0 - LOOKBACK_MS,)):
                    a = out["btc"] if sym == BTC else out["alts"]
                    if status == "open":
                        a["open"] += 1
                        a["opened"] += 1 if t >= d0 else 0
                    elif status == "closed" and net is not None:
                        a["opened"] += 1 if t >= d0 else 0
                        if _closed_ms(t, js) >= d0:
                            usdt = (BTC_MARGIN if sym == BTC else MARGIN) * net / 100.0
                            a["closed"] += 1
                            a["wins" if net > 0 else "losses"] += 1
                            a["realized"] += usdt
                            if tf in TFS:
                                b = a["by_tf"][tf]
                                b["closed"] += 1
                                b["wins"] += 1 if net > 0 else 0
                                b["realized"] += usdt
                    elif status in ("skipped", "skipped_done") and t >= d0:
                        a["skipped"] += 1
            finally:
                con.close()
            out["state"] = "ok"
        for a in (out["alts"], out["btc"]):                  # round once at the end
            a["realized"] = round(a["realized"], 2)
            for b in a["by_tf"].values():
                b["realized"] = round(b["realized"], 2)
    except Exception as ex:
        out["state"], out["err"] = "error", "%s: %s" % (type(ex).__name__, str(ex)[:100])
    if base is None and now_s is None:
        _C["t"], _C["v"] = now, dict(out)
    return out


def overlay(view, base=None, now_s=None):
    """The /api/dual_lab answer -> the same answer with summary.today made from the archive. Anything odd = the view is returned unchanged."""
    try:
        sm = (view or {}).get("summary")
        td = sm.get("today") if isinstance(sm, dict) else None
        t = today(base, now_s)
        if not isinstance(td, dict) or t["state"] != "ok":
            return view
        a = t["alts"]
        td.update(opened=a["opened"], closed=a["closed"], wins=a["wins"], losses=a["losses"], realized=a["realized"], skipped=a["skipped"], source="archive", definition=DEFINITION)
        td["total"] = round(a["realized"] + (td.get("open_pnl") or 0.0), 2)
        return view
    except Exception:
        return view
