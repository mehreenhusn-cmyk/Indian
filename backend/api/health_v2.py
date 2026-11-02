"""api/health_v2.py - OwlSniper Round 23: ONE read-only route GET /api/v2/sniper_health for the Diagnostics screen (Round 28). Same style as api/sniper.py.
It only READS files and the market store (read-only connection) and says in plain words whether the Sniper is healthy. It sends no order, writes nothing, changes no old file, and never calls the network.
Checks (state OK / WARN / BAD / NOT_AVAILABLE, each with one plain sentence):
  model        v2_sniper_model.json exists, how old, learned or not, is the 85% floor proven
  scan         v2_sniper_live.json: how old, status, how many coins were stale
  candles      newest saved 5m candle of any coin (age) + is the candle collector switch (v2_candles_enabled) on
  switches     v2_sniper_off (stops the self-start), the refresh lock, the 15m files
  executor     NOT_AVAILABLE until owl_sniper_exec.py (Round 22) exists; nothing is made up
Overall = the worst state of the measured checks. Same switch as the other V2 routes: 404 (enabled False) until the file v2_api_enabled exists in the data folder.
MOUNTED in Round 24 (api_server.py, try / except block next to the sniper route; owner gave "mount ok")."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_tf as TF
import v2_candles as VC

VERSION = "api/health_v2 1 (Round 23)"
PATH = "/api/v2/sniper_health"
FLAG_NAME = "v2_api_enabled"
ORDER = {"OK": 0, "NOT_AVAILABLE": 0, "WARN": 1, "BAD": 2}


def api_enabled(data_dir):
    p = os.path.join(os.path.realpath(data_dir), FLAG_NAME)
    try:
        if os.path.islink(p) or not os.path.isfile(p):
            return False
        with open(p, "r", encoding="utf-8") as f:
            return f.read(10).strip().lower() in ("1", "on", "true", "yes")
    except OSError:
        return False


def _age(ts, now):
    try:
        return max(0, int(now - int(ts)))
    except (TypeError, ValueError):
        return None


def _span(sec):
    return "%d min" % (sec // 60) if sec < 7200 else "%.1f h" % (sec / 3600.0)


def _c(cid, label, state, text, **extra):
    return dict({"id": cid, "label": label, "state": state, "text": text}, **extra)


def newest_candle_ts(d):
    """Newest saved 5m candle of any coin, or None (no store, no candles). Read-only."""
    con = F.open_ro(d)
    if con is None:
        return None
    try:
        return con.execute("SELECT MAX(open_ts) FROM candles WHERE interval='5m'").fetchone()[0]
    except Exception:
        return None
    finally:
        con.close()


def build(d, now):
    """The answer dict. Pure apart from reading files: no network, no write."""
    model, live = F.read_json(d, F.MODEL_FILE), F.read_json(d, F.LIVE_FILE)
    checks = []
    if not model:
        checks.append(_c("model", "Model", "WARN", "No model file yet. OwlSniper makes it by itself after the first scan."))
    else:
        age, st = _age(model.get("saved_at"), now), model.get("status")
        limit = F.MODEL_MAX_AGE.get(st, 6 * 3600) * 1.5
        state = "OK" if st == "OK" and age is not None and age <= limit else "WARN"
        txt = "Model status %s, made %s ago; the 85%% floor is %s." % (st or "unknown", "--" if age is None else _span(age), "proven" if model.get("floor_verified") else "NOT proven (no signal can pass)")
        checks.append(_c("model", "Model", state, txt, age_sec=age))
    if not live:
        checks.append(_c("scan", "Live scan", "WARN", "No scan file yet."))
    else:
        age = _age(live.get("saved_at"), now)
        state = "BAD" if age is None or age > 3600 else "WARN" if age > 3 * TF.LIVE_MAX_AGE["5m"] or live.get("status") != "OK" else "OK"
        checks.append(_c("scan", "Live scan", state, "Last scan %s ago, status %s, %d coins scanned, %d stale." % ("--" if age is None else _span(age), live.get("status"), live.get("coins_scanned") or 0, live.get("stale_coins") or 0), age_sec=age))
    last = newest_candle_ts(d)
    on = VC.is_enabled(d)
    if last is None:
        checks.append(_c("candles", "Candles", "WARN", "No saved 5m candles found. The candle collector is %s." % ("ON" if on else "OFF")))
    else:
        age = _age(last, now)
        state = "BAD" if age > 3600 else "WARN" if age > 900 or not on else "OK"
        checks.append(_c("candles", "Candles", state, "Newest saved 5m candle is %s old. Candle collector is %s%s." % (_span(age), "ON" if on else "OFF", "" if on else ", so the Sniper scans old candles"), age_sec=age))
    off = os.path.isfile(os.path.join(os.path.realpath(d), F.OFF_FILE))
    busy = F.lock_busy(d, now)
    f15 = F.read_json(d, TF.files("15m")[0]) is not None
    checks.append(_c("switches", "Switches", "WARN" if off else "OK", "Self-start is %s. A refresh is %s. 15m model file: %s." % ("OFF (file v2_sniper_off)" if off else "ON", "running now" if busy else "not running", "yes" if f15 else "not made yet")))
    checks.append(_c("executor", "Executor", "NOT_AVAILABLE", "The executor (owl_sniper_exec.py) is not built yet, so there is nothing to measure. OwlSniper is WATCH ONLY."))
    worst = max((c["state"] for c in checks), key=lambda s: ORDER[s])
    head = {"OK": "OwlSniper is healthy.", "WARN": "OwlSniper works, but something needs a look.", "BAD": "OwlSniper has a problem."}[worst if worst != "NOT_AVAILABLE" else "OK"]
    return {"version": VERSION, "overall": "OK" if worst == "NOT_AVAILABLE" else worst, "headline": head, "checks": checks, "watch_only": True, "saved_at": int(now)}


def answer(data_dir, now=None):
    """-> (http status, body dict). Never raises."""
    now = int(time.time() if now is None else now)
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    try:
        return 200, build(data_dir, now)
    except Exception:
        return 503, {"error": "the sniper health page could not be made right now"}


def make_router(require_api_token, data_dir):
    """Mounted by api_server.py in Round 24 (try / except block): 1 GET route behind the app's token check."""
    import asyncio
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_health():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)
    return r
