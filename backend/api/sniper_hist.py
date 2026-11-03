"""api/sniper_hist.py - OwlSniper HISTORY COVERAGE route + background download (R1 / Round 1 of OWL_BRIEF plan v2): ONE read-only route GET /api/v2/sniper_hist.
It answers "how many closed trades of Dual, Brain and the main bot can the learn bridge use, how many more can be made usable, and what is the history download doing?" (the TRAINING DATA HEALTH of the Sniper).
Answer: state, records, by_source {dual, brain, main: records, ready, needs_fetch, known_gap, too_old, too_recent, tf_unsupported, tf_unknown} (every source apart, never added), tf_unsupported {interval: n},
  symbols, slots_missing, requests_needed, lines (plain English), last_run (what the download did last), turns, age_sec, paper_only (always true).
Making the router also starts ONE daemon thread (owl_sniper_hist_net.loop_forever): every 10 minutes it downloads at most 60 requests of missing candles into the candle store (only while the candle switch v2_candles_enabled is ON and v2_sniper_off does not exist).
The route only reads. The thread writes ONLY candles and holes into v2_market.db. No trading file, no order path.
Same switch as the other V2 routes: 404 until the file v2_api_enabled exists in the data folder. Mounted by api/sniper_mount.py (owner said "mount ok" on 3 Nov 2026)."""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_hist as H
import owl_sniper_hist_net as HN
from api.sniper import api_enabled

VERSION = "api/sniper_hist 1 (R1)"
PATH = "/api/v2/sniper_hist"
CACHE_SEC = 300
_cache = {"ts": 0.0, "body": None}
_state = {"started": False, "last": None, "turns": 0}
_lock = threading.Lock()                 # held while ONE plan is built
_cache_lock = threading.Lock()


def hist_answer(data_dir, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(data_dir), F.OFF_FILE)):
        return 200, {"state": "off", "paper_only": True, "lines": ["The Sniper is switched off (file v2_sniper_off)."]}
    with _cache_lock:
        body, age = (_cache["body"], now - _cache["ts"]) if _cache["body"] is not None else (None, None)
    if body is not None and age < CACHE_SEC:
        return 200, dict(body, last_run=_state["last"], turns=_state["turns"], age_sec=round(age, 1))
    if not _lock.acquire(blocking=False):
        if body is not None:
            return 200, dict(body, last_run=_state["last"], turns=_state["turns"], age_sec=round(age, 1), refreshing=True)
        return 200, {"state": "busy", "paper_only": True, "lines": ["The saved trades and candles are being counted. Open this page again in a minute."]}
    try:
        res = H.short(H.plan(data_dir))
        res["paper_only"], res["version"] = True, VERSION
        with _cache_lock:
            _cache["ts"], _cache["body"] = now, res
        return 200, dict(res, last_run=_state["last"], turns=_state["turns"], age_sec=0.0)
    finally:
        _lock.release()


def start_loop(data_dir):
    with _cache_lock:
        if _state["started"]:
            return False
        _state["started"] = True
    threading.Thread(target=HN.loop_forever, args=(data_dir, _state), name="owl-sniper-hist", daemon=True).start()
    return True


def make_router(require_api_token, data_dir):
    """Mounted by api/sniper_mount.py: 1 GET route behind the app's token check, plus the history download thread."""
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_hist():
        st, body = await asyncio.to_thread(hist_answer, data_dir)
        return JSONResponse(body, status_code=st)

    start_loop(data_dir)
    return r
