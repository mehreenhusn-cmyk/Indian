"""api/sniper_winners.py - ONE read-only route GET /api/v2/sniper_winners = what the winning past trades had in common (owl_sniper_winners.build). Paper only, writes nothing, no order.
Same switch as the other V2 routes: 404 until v2_api_enabled exists, off while v2_sniper_off exists. Cached 10 minutes, ONE build at a time. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_winners as W
from api.sniper import api_enabled

VERSION = "api/sniper_winners 1 (E4)"
PATH = "/api/v2/sniper_winners"
CACHE_SEC = 600
_cache = {"ts": 0.0, "body": None}
_lock = threading.Lock()


def answer(data_dir, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(data_dir), F.OFF_FILE)):
        return 200, {"state": "off", "paper_only": True, "lines": ["The Sniper is switched off (file v2_sniper_off)."]}
    body = _cache["body"]
    if body is not None and now - _cache["ts"] < CACHE_SEC:
        return 200, dict(body, age_sec=round(now - _cache["ts"], 1))
    if not _lock.acquire(blocking=False):
        if body is not None:
            return 200, dict(body, age_sec=round(now - _cache["ts"], 1), refreshing=True)
        return 200, {"state": "busy", "paper_only": True, "lines": ["The past trades are being studied. Open this page again in a minute."]}
    try:
        res = W.build(data_dir)
        res["paper_only"], res["route_version"] = True, VERSION
        _cache["ts"], _cache["body"] = now, res
        return 200, dict(res, age_sec=0.0)
    finally:
        _lock.release()


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_winners():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)

    return r
