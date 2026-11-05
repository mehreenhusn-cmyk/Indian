"""api/sniper_watch.py - OwlSniper R33a (Part 15): ONE read-only route GET /api/v2/sniper_watch = the ranked WATCHLIST (Market Watch favourites + biggest movers) with ARMED / NEAR / WATCH per coin (owl_sniper_watch).
?armed=1 = only the armed rows. Paper only, no order code. Writes only its own file v2_sniper_watch.json (at most one new scan per 5m candle). 404 until v2_api_enabled exists, off while v2_sniper_off exists. Cached 20 s. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_watch as W
from api.sniper import api_enabled

VERSION = "api/sniper_watch 1 (R33a)"
PATH = "/api/v2/sniper_watch"
_CACHE = {"t": 0.0, "body": None}


def answer(d, armed_only=False, now=None):
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
        return 200, {"state": "off", "paper_only": True, "text": "The Sniper is switched off (file v2_sniper_off)."}
    t = time.time() if now is None else now
    if _CACHE["body"] is None or t - _CACHE["t"] >= 20 or now is not None:
        body = W.fresh(d, t)
        if now is None:
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
