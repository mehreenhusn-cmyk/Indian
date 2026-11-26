"""api/top10_route.py - GET /api/top10_7d: the coins that were in Binance's top 10 gainers / top 10 losers in the last 7 days, with their live numbers.
Read-only. The list is built once per UTC day by top10_7d.py (a worker thread that ends by itself). Never raises: a problem answers {"state": "error"}."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import top10_7d as T

VERSION = "api/top10_route 1 (26 Nov 2026)"


def _safe(base):
    try:
        return T.view(base)
    except Exception as e:
        return {"state": "error", "err": "%s: %s" % (type(e).__name__, str(e)[:120])}


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    r = APIRouter()

    @r.get("/api/top10_7d", dependencies=[Depends(require_api_token)])
    async def top10_7d():
        return await asyncio.to_thread(_safe, data_dir)

    return r
