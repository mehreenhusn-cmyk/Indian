"""api/trade_timeline.py - Part 12A: GET /api/v2/trades = the trade timeline (open + last 3 days closed + last signals) for the app Trades screen. READ ONLY, no order code.
Same switch as the other V2 routes (404 until v2_api_enabled exists) and behind the app token. MOUNTED by api/sniper_mount.py (one line in ROUTES), in its own try / except."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import v2_f14_timeline as T
from api.sniper import api_enabled

VERSION = "api/trade_timeline 1 (Part 12A)"
PATH = "/api/v2/trades"
OFF_ANSWER = {"enabled": False, "note": "the V2 data API is off"}


def answer(data_dir):
    if not api_enabled(data_dir):
        return 404, OFF_ANSWER
    body = T.answer(data_dir)
    return (500 if "error" in body else 200), body


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_trades():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)

    return r
