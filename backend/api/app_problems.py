"""api/app_problems.py - APP PROBLEMS route (Part 47 / FILE 56): ONE route GET /api/v2/app_problems
The owner wants ONE place where everything that fails or does not perform is listed, so he can take a screenshot or press Copy and send it to Claude to fix.
This route is that list (backend side). READ ONLY: it reads the backend's own status and files, writes nothing, sends nothing, no network, no order, no setting changed.
Checks (each in its OWN try / except: one broken check never hides the others, it becomes one WARN line):
  Route    a Sniper route that did not start (api/sniper_mount.py STATUS: name + reason) or mount_all never ran
  Switch   file v2_sniper_off exists (Sniper off), candle collector switch v2_candles_enabled off
  Kill     LEARN kill switch ON, Sniper exec kill switch ON, a broken state file, LEARN switched off
  Health   every BAD / WARN card of System Health (v2_sys_health.build): feed age, collector, Brain tick, disk ...
  Candles  candle gaps saved in gap_log during the last 48 hours, worst coins first, with the command that refills them
  Waiting  a report that says NOT ENOUGH DATA (LEARN has n of 30 trades)
  Not measured  one INFO line: slow routes are NOT timed by the backend yet; the app's own failed fetches are listed by the app (Part 48), not here.
Item = {id, sev BAD / WARN / INFO, area, where (route, file or screen), text (plain, says what failed), fix (one plain step), ts, when (UTC text)}. Sorted BAD, WARN, INFO. Max 60.
Answer: state (OK / PROBLEMS / off), headline, counts {BAD, WARN, INFO}, items, checked (list of check names), copy_text (the whole list as plain lines for the Copy all button), answer_age_sec, read_only (always true).
Light on the phone: built at most once per CACHE_SEC (30 s), ONE build at a time (a second call gets the old answer, or state "busy" when there is none).
Same switch as the other V2 routes: 404 until the file v2_api_enabled holds 1 (so while it is off the app only sees a 404, and the app's own error log (Part 48) shows that).
Mounted by api/sniper_mount.py (one line in its ROUTES list). Times over 60 minutes are shown as hours + minutes."""
import asyncio
import os
import sqlite3
import sys
import threading
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.sniper import api_enabled

VERSION = "api/app_problems 1 (Part 47)"
PATH = "/api/v2/app_problems"
CACHE_SEC, MAX_ITEMS, GAP_HOURS = 30, 60, 48
ORDER = {"BAD": 0, "WARN": 1, "INFO": 2}
_cache = {"ts": 0.0, "body": None}
_build_lock, _mem_lock = threading.Lock(), threading.Lock()


def dur(sec):
    """Plain time text; over 60 minutes = hours + minutes (owner rule)."""
    m = max(0, int(sec)) // 60
    if m < 1:
        return "%d s" % max(0, int(sec))
    if m < 60:
        return "%d min" % m
    h, m = divmod(m, 60)
    if h < 24:
        return "%d h %d min" % (h, m)
    d, h = divmod(h, 24)
    return "%d d %d h %d min" % (d, h, m)


def _when(ts):
    return time.strftime("%d %b %H:%M UTC", time.gmtime(ts))


def _item(sev, area, where, text, fix, ts):
    return {"id": "%s:%s" % (area.lower(), where), "sev": sev, "area": area, "where": where, "text": text, "fix": fix, "ts": int(ts), "when": _when(ts)}


def check_routes(d, now):
    from api import sniper_mount as M
    st, out = M.STATUS, []
    for s in st.get("skipped") or []:
        out.append(_item("BAD", "Route", s.get("name", "?"), "The %s route did not start: %s" % (s.get("name", "?"), s.get("why", "no reason saved")),
                         "Fix the file named in the reason, then restart the backend.", now))
    if not st.get("mounted") and not st.get("skipped"):
        out.append(_item("WARN", "Route", "api_server.py", "The Sniper routes were never mounted (mount_all did not run at start).",
                         "Check the mount block in api_server.py and the startup log.", now))
    return out


def check_switches(d, now):
    import owl_sniper_feed as F
    import v2_candles as K
    out = []
    if os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
        out.append(_item("WARN", "Switch", F.OFF_FILE, "The Sniper is switched off (file %s exists). No Sniper report or signal is made." % F.OFF_FILE, "Delete that file to switch it on again.", now))
    if not K.is_enabled(d):
        out.append(_item("WARN", "Switch", K.FLAG_NAME, "The candle collector is switched off (file %s is missing or not 1). No new candles are saved." % K.FLAG_NAME,
                         "Write 1 into that file to switch it on.", now))
    return out


def check_kill(d, now):
    import owl_sniper_exec as X
    import owl_sniper_learn as L
    out = []
    s = L.status(d, now)
    if s.get("state") == "broken":
        out.append(_item("BAD", "Kill", "v2_sniper_learn.json", "The LEARN state file is broken: %s" % str(s.get("text", ""))[:160], "Send this line to Claude. The file is never overwritten by itself.", now))
    elif (s.get("kill") or {}).get("on"):
        out.append(_item("BAD", "Kill", "LEARN kill switch", "The LEARN kill switch is ON (%s). No new LEARN paper trade until the owner resets it." % ((s["kill"].get("reason")) or "no reason saved"),
                         "Look at why first. Reset only with: python3 backend/owl_sniper_learn.py --data DIR reset_kill", now))
    elif s.get("enabled") is False:
        out.append(_item("INFO", "Kill", "LEARN switch", "LEARN is switched off, so no LEARN paper trade is opened.", "Switch it on with: python3 backend/owl_sniper_learn.py --data DIR on", now))
    e = X.status(d, now)
    if not e.get("ok", True):
        out.append(_item("BAD", "Kill", "v2_sniper_exec.json", "The Sniper exec state file is broken: %s" % str(e.get("text", ""))[:160], "Send this line to Claude.", now))
    elif (e.get("kill") or {}).get("on"):
        out.append(_item("BAD", "Kill", "Sniper exec kill switch", "The Sniper exec kill switch is ON (%s). No Sniper paper order until the owner resets it." % ((e["kill"].get("reason")) or "no reason saved"),
                         "Look at why first. Reset only with: python3 backend/owl_sniper_exec.py --data DIR reset", now))
    return out


def check_health(d, now):
    import v2_sys_health as SH
    out = []
    for c in (SH.build(d, now).get("cards") or []):
        if c.get("state") in ("BAD", "WARN"):
            out.append(_item("BAD" if c["state"] == "BAD" else "WARN", "Health", "System Health: %s" % c.get("title", "?"),
                             "%s: %s%s" % (c.get("title", "?"), c.get("value", "-"), (" - " + c["sub"]) if c.get("sub") else ""), "Open the Diagnostics tab for this card. Send this line to Claude.", now))
    return out


def check_candle_gaps(d, now):
    p = os.path.join(os.path.realpath(d), "v2_market.db")
    if not os.path.isfile(p):
        return [_item("INFO", "Candles", "v2_market.db", "There is no candle store file yet, so no gap can be checked.", "Switch the candle collector on (see Switch lines).", now)]
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(p), uri=True, timeout=5)
    try:
        rows = con.execute("SELECT symbol, interval, COUNT(*), MIN(from_ts), MAX(to_ts), MAX(logged_ts) FROM gap_log WHERE kind='candle' AND logged_ts>=? "
                           "GROUP BY symbol, interval ORDER BY COUNT(*) DESC LIMIT 8", (int(now) - GAP_HOURS * 3600,)).fetchall()
        total = con.execute("SELECT COUNT(DISTINCT symbol || interval) FROM gap_log WHERE kind='candle' AND logged_ts>=?", (int(now) - GAP_HOURS * 3600,)).fetchone()[0]
    finally:
        con.close()
    out = []
    for sym, iv, n, a, b, lg in rows:
        out.append(_item("WARN", "Candles", "%s %s" % (sym, iv), "%s %s: %d candle gap(s) saved, from %s to %s (the exchange gave no candle; nothing was invented)." % (sym, iv, n, _when(a), _when(b)),
                         "Refill what the exchange has: python3 backend/v2_candles_deep.py --once", lg or now))
    if total > len(rows):
        out.append(_item("INFO", "Candles", "gap_log", "%d more coin + interval pair(s) have gaps in the last %d hours (the worst %d are listed)." % (total - len(rows), GAP_HOURS, len(rows)), "Same fix as above.", now))
    return out


def check_waiting(d, now):
    import owl_sniper_learn as L
    p = L.progress(d)
    if p.get("state") == "ok" and p.get("n", 0) < p.get("target", 30):
        return [_item("INFO", "Waiting", "LEARN verdict", "LEARN has %d of %d paper trades. Reports that need %d trades say NOT ENOUGH DATA until then." % (p["n"], p["target"], p["target"]),
                      "Nothing to fix. It fills as LEARN paper trades close.", now)]
    return []


def check_not_measured(d, now):
    return [_item("INFO", "Not measured", "route speed", "Slow routes are not timed by the backend yet, so a slow route is not listed here. The app lists its own failed or slow fetches (Part 48).",
                  "Nothing to fix. Check the app's own error log on the Problems page.", now)]


CHECKS = (("routes", check_routes), ("switches", check_switches), ("kill switches", check_kill), ("system health", check_health),
          ("candle gaps", check_candle_gaps), ("waiting reports", check_waiting), ("not measured", check_not_measured))


def build(data_dir, now=None):
    """-> the answer body. Never raises."""
    now = time.time() if now is None else now
    items, checked = [], []
    for name, fn in CHECKS:
        checked.append(name)
        try:
            items += fn(data_dir, now)
        except Exception as e:                                           # one broken check never hides the others
            items.append(_item("WARN", "Check", name, "The check '%s' could not run (%s: %s)." % (name, type(e).__name__, str(e)[:120]), "Send this line to Claude.", now))
    items.sort(key=lambda i: (ORDER.get(i["sev"], 3), i["area"], i["where"]))
    items = items[:MAX_ITEMS]
    c = {k: sum(1 for i in items if i["sev"] == k) for k in ORDER}
    head = ("%d red, %d yellow problem(s) found" % (c["BAD"], c["WARN"])) if (c["BAD"] or c["WARN"]) else "No problems found by these checks"
    lines = ["OWL APP PROBLEMS %s - %s" % (_when(now), head)] + ["[%s] %s | %s | %s | Fix: %s" % (i["sev"], i["area"], i["where"], i["text"], i["fix"]) for i in items]
    return {"state": "PROBLEMS" if (c["BAD"] or c["WARN"]) else "OK", "headline": head, "counts": c, "items": items, "checked": checked,
            "copy_text": "\n".join(lines), "read_only": True, "paper_only": True}


def problems_answer(data_dir, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    with _mem_lock:
        body, ts = _cache["body"], _cache["ts"]
    if body is None or now - ts >= CACHE_SEC:
        if _build_lock.acquire(blocking=False):
            try:
                body, ts = build(data_dir, now), now
                with _mem_lock:
                    _cache["ts"], _cache["body"] = ts, body
            finally:
                _build_lock.release()
        elif body is None:
            return 200, {"state": "busy", "headline": "The problem list is being made. Open this page again in a few seconds.", "items": [], "counts": {}, "copy_text": "", "read_only": True}
    return 200, dict(body, answer_age_sec=round(now - ts, 1), route_version=VERSION)


def make_router(require_api_token, data_dir):
    """1 GET route behind the app's token check."""
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_app_problems():
        st, body = await asyncio.to_thread(problems_answer, data_dir)
        return JSONResponse(body, status_code=st)

    return r
