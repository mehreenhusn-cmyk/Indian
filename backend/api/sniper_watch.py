"""api/sniper_watch.py - OwlSniper R33a (Part 15): ONE read-only route GET /api/v2/sniper_watch = the ranked WATCHLIST (Market Watch favourites + biggest movers) with ARMED / NEAR / WATCH per coin (owl_sniper_watch).
?armed=1 = only the armed rows. Paper only, no order code. Writes only its own file v2_sniper_watch.json (at most one new scan per 5m candle). 404 until v2_api_enabled exists, off while v2_sniper_off exists. Cached 20 s (one scan at a time; if a new scan fails the last good list is served with stale_cache=true). Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_watch as W
from api.sniper import api_enabled

VERSION = "api/sniper_watch 2 (R33b)"
PATH = "/api/v2/sniper_watch"
_CACHE = {"t": 0.0, "body": None}
_LOCK = threading.Lock()  # R33b (Plan E): two phone refreshes at once make ONE scan, the second waits and reuses it


def answer(d, armed_only=False, now=None):
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
        return 200, {"state": "off", "paper_only": True, "text": "The Sniper is switched off (file v2_sniper_off)."}
    t = time.time() if now is None else now
    if now is not None:  # a test passes its own clock: no cache, no lock
        return 200, W.pick_rows(W.fresh(d, t), armed_only)
    with _LOCK:
        if _CACHE["body"] is None or t - _CACHE["t"] >= 20:
            body = W.fresh(d, t)
            good = _CACHE["body"]
            if body.get("state") != "OK" and good is not None and good.get("state") == "OK":
                # R33b: the new scan failed -> keep serving the last good list, marked stale (never an empty list because of one bad scan)
                _CACHE["t"] = t  # retry the scan in 20 s, not on every request
                body = dict(good, stale_cache=True, stale_age_sec=int(t - good.get("saved_at", t)), refresh_error=str(body.get("text") or body.get("state")))
            else:
                _CACHE["t"], _CACHE["body"] = t, body
        else:
            body = _CACHE["body"]
    return 200, W.pick_rows(body, armed_only)


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_watch(armed: int = 0):
        st, body = await asyncio.to_thread(answer, data_dir, bool(armed))
        return JSONResponse(body, status_code=st)
    return r
