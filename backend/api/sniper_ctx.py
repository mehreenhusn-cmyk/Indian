"""api/sniper_ctx.py - OwlSniper R30 (Part 5): ONE read-only route GET /api/v2/sniper_ctx = the market context the Sniper now learns from (owl_sniper_ctx.view): BTC move over 1 / 3 / 12 candles, BTC trend, the session (ASIA / EUROPE / US / LATE US).
BTC here is only a set of NUMBERS for the Sniper. It is never added to any P&L, win rate or equity (btc_counts_in_pnl is always false).
Read only. 404 until v2_api_enabled exists, off while v2_sniper_off exists. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_ctx as CX
import owl_sniper_feed as F
from api.sniper import api_enabled

VERSION = "api/sniper_ctx 1 (R30)"
PATH = "/api/v2/sniper_ctx"


def answer(d, now=None):
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
        return 200, {"state": "off", "paper_only": True, "text": "The Sniper is switched off (file v2_sniper_off)."}
    return 200, CX.view(d, now)


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_ctx():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)
    return r
