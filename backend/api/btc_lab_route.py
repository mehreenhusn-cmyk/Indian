"""api/btc_lab_route.py - BTC LAB route (R16b). ONE read-only route: GET /api/v2/btc_lab. Answers btc_lab.lab(): BTC's OWN numbers (signals seen, finished, wins, hit rate, USDT at margin 1000, 5m / 15m, last 7 days, today).
BTC is the indicator test coin: it is kept out of every Dual / Brain / Sniper / Dashboard total (file v2_btc_in_counts in the data folder puts it back). Nothing is written, no order code.
Same switch as the other V2 routes: 404 until v2_api_enabled exists. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import btc_lab as BL
from api.sniper import api_enabled

VERSION = "api/btc_lab_route 1 (R16b)"
PATH = "/api/v2/btc_lab"
_C = {"t": 0.0, "v": None}


def answer(d, now=None):
    """-> (http status, body). Cached 8 seconds. Never raises."""
    now = time.time() if now is None else now
    try:
        if not api_enabled(d):
            return 404, {"enabled": False, "note": "the V2 data API is off"}
        if _C["v"] is None or now - _C["t"] >= 8:
            _C["t"], _C["v"] = now, BL.lab(d)
        return 200, _C["v"]
    except Exception as e:
        return 200, {"state": "error", "err": "%s: %s" % (type(e).__name__, str(e)[:100])}


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_btc_lab():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)

    return r
