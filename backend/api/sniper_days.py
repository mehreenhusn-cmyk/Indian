"""api/sniper_days.py - OwlSniper R28b (Part 9): ONE read-only route GET /api/v2/sniper_days = Sniper TODAY + Sniper 7 DAYS (owl_sniper_days.build): today block, week block, 7 day bars.
Paper only, BTC never counted, never added to the Current Bot / Dual / Brain. 404 until v2_api_enabled exists, off while v2_sniper_off exists. Cached 20 s. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_days as DY
import owl_sniper_feed as F
from api.sniper import api_enabled

VERSION = "api/sniper_days 1 (R28b)"
PATH = "/api/v2/sniper_days"
_CACHE = {"t": 0.0, "body": None}


def answer(d, now=None):
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
        return 200, {"state": "off", "paper_only": True, "text": "The Sniper is switched off (file v2_sniper_off)."}
    t = time.time() if now is None else now
    if _CACHE["body"] is not None and t - _CACHE["t"] < 20 and now is None:
        return 200, _CACHE["body"]
    body = DY.build(d, t)
    if now is None:
        _CACHE["t"], _CACHE["body"] = t, body
    return 200, body


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_days():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)
    return r
