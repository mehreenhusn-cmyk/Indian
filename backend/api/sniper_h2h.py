"""api/sniper_h2h.py - CURRENT BOT vs OWLSNIPER on the SAME days (R24a). ONE read-only route: GET /api/v2/sniper_h2h?days=14.
Answer of owl_sniper_h2h.build: state (OK / NOT_ENOUGH_DATA / ERROR), verdict (SNIPER_AHEAD / CURRENT_AHEAD / TOO_CLOSE / NOT_ENOUGH_DATA), current + sniper {trades, net_usdt, wins, win_pct, avg_pct},
shared_days, per_day (last 7 shared days), reasons, paper_only (always true). Reads only the trade archive, writes nothing, no loop. Cached 60 s.
Same switch as the other V2 routes: 404 until v2_api_enabled exists, off while v2_sniper_off exists. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_h2h as H
from api.sniper import api_enabled

VERSION = "api/sniper_h2h 1 (R24a)"
PATH = "/api/v2/sniper_h2h"
CACHE_SEC = 60
_cache = {}


def answer(d, days=H.DEFAULT_DAYS, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
        return 200, {"state": "off", "paper_only": True, "reasons": ["The Sniper is switched off (file v2_sniper_off)."]}
    days = max(3, min(60, int(days)))
    hit = _cache.get(days)
    if hit and now - hit[0] < CACHE_SEC:
        return 200, hit[1]
    body = dict(H.build(d, now=now, days=days), version=VERSION)
    _cache.clear()
    _cache[days] = (now, body)
    return 200, body


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_h2h(days: int = H.DEFAULT_DAYS):
        st, body = await asyncio.to_thread(answer, data_dir, days)
        return JSONResponse(body, status_code=st)

    return r
