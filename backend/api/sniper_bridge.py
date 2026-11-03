"""api/sniper_bridge.py - OwlSniper LEARN BRIDGE status route (Part 9 / FILE 13): ONE read-only route GET /api/v2/sniper_bridge.
It answers "how many examples does the Sniper get from Dual Bot, Brain and the main bot, and what did the bridge model learn from their wins AND losses?"
Everything comes from owl_sniper_bridge_learn.build(): closed trades of the three bots (src) -> candle replay (replay) -> labels in R (label) -> bridge model (prob.learn_bridge). Nothing is written, no order, no network.
It reads files only. To keep the phone light the answer is cached for CACHE_SEC (10 minutes) and only ONE build runs at a time; a second call during a build gets the old answer (or state "busy" when there is none). Only the newest LIMIT (1500) trades are used here.
Same switch as the other V2 routes: 404 until the file v2_api_enabled exists in the data folder, and off for good while the file v2_sniper_off exists.
Answer: state (OK / NOT_ENOUGH_DATA / NO_EXAMPLES / busy / error), by_source {dual, brain, main: records, rows, labels, examples} (every step apart; sources are NEVER added together), src_info, replay_skipped, label_skipped (plain reason counts),
  split {train, test, test_from_ts, embargo_dropped}, learn (ok, train_n, test_n, base rates, curve, floor_check in R, lines; real_gate always false: the bridge model never opens the REAL 85% gate), per_source (TEST days, each source apart), lines (plain English), age_sec, paper_only (always true).
NOT MOUNTED yet. To mount (owner says "mount ok"), add 4 lines to api_server.py after the sniper paper block, same try / except style:
    try:
        from api.sniper_bridge import make_router as _sniper_bridge_router
        app.include_router(_sniper_bridge_router(require_api_token, DATA_DIR))
    except Exception as _e:
        print(f"[startup] sniper bridge route skipped: {_e}")"""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_bridge_learn as BL
import owl_sniper_feed as F
from api.sniper import api_enabled

VERSION = "api/sniper_bridge 1 (Part 9)"
PATH = "/api/v2/sniper_bridge"
CACHE_SEC = 600
LIMIT = 1500
_cache = {"ts": 0.0, "body": None}
_lock = threading.Lock()         # held while ONE build runs
_cache_lock = threading.Lock()


def _cached(now):
    with _cache_lock:
        return (_cache["body"], now - _cache["ts"]) if _cache["body"] is not None else (None, None)


def bridge_answer(data_dir, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(data_dir), F.OFF_FILE)):
        return 200, {"state": "off", "paper_only": True, "lines": ["The Sniper is switched off (file v2_sniper_off)."]}
    body, age = _cached(now)
    if body is not None and age < CACHE_SEC:
        return 200, dict(body, age_sec=round(age, 1))
    if not _lock.acquire(blocking=False):                      # another call is building right now
        if body is not None:
            return 200, dict(body, age_sec=round(age, 1), refreshing=True)
        return 200, {"state": "busy", "paper_only": True, "lines": ["The bridge is being read from the saved trades and candles. Open this page again in a minute."]}
    try:
        try:
            res = BL.build(data_dir, LIMIT)
        except Exception as e:                                 # a damaged file must never stop the backend
            res = {"state": "error", "lines": ["The bridge could not be built: %s." % str(e)[:80]]}
        res["paper_only"], res["version"] = True, VERSION
        if res.get("learn"):
            res["learn"]["real_gate"] = False
        with _cache_lock:
            _cache["ts"], _cache["body"] = now, res
        return 200, dict(res, age_sec=0.0)
    finally:
        _lock.release()


def make_router(require_api_token, data_dir):
    """Mounted by api_server.py only after the owner says "mount ok": 1 GET route behind the app's token check."""
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_bridge():
        st, body = await asyncio.to_thread(bridge_answer, data_dir)
        return JSONResponse(body, status_code=st)

    return r
