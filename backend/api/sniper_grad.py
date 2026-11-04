"""api/sniper_grad.py - SNIPER GRADUATION CHECKLIST (R24b). ONE read-only route: GET /api/v2/sniper_grad.
Answer of owl_sniper_grad.build: overall (READY_TO_DISCUSS / NOT_YET / COLLECTING / ERROR), passed, total, checks [{key, name, status PASS|FAIL|WAIT, text}], reasons, paper_only (always true).
The app never swaps the bots by itself; this is a checklist for the owner. Reads only saved files, writes nothing, no loop. Cached 60 s.
Same switch as the other V2 routes: 404 until v2_api_enabled exists, off while v2_sniper_off exists. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_grad as G
from api.sniper import api_enabled

VERSION = "api/sniper_grad 1 (R24b)"
PATH = "/api/v2/sniper_grad"
CACHE_SEC = 60
_cache = {}


def answer(d, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
        return 200, {"overall": "off", "paper_only": True, "checks": [], "reasons": ["The Sniper is switched off (file v2_sniper_off)."]}
    hit = _cache.get("x")
    if hit and now - hit[0] < CACHE_SEC:
        return 200, hit[1]
    body = dict(G.build(d, now=now), version=VERSION)
    _cache["x"] = (now, body)
    return 200, body


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_grad():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)

    return r
