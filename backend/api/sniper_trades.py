"""api/sniper_trades.py - OwlSniper R29a: ONE read-only route GET /api/v2/sniper_trades[?limit=30] = the Sniper trade record (owl_sniper_record.build): open trades, then closed trades newest first.
R29b: every OPEN trade also carries trade_id (the paper position id) so the app can join its live price and P&L.
Each trade: symbol, side, lane (EXPLORE / LEARN / REAL), signal, reason, basis[], regime, entry, stop_loss, take_profit, target_pct, stop_pct, rr, expected_usdt, risk_usdt, max_hold_sec, typical_hold_sec; closed ones add pnl_usdt, roi_pct, held_sec, exit_reason, tag, lesson, vs_expected.
Read only (the record file is written by the paper loop). 404 until v2_api_enabled exists, off while v2_sniper_off exists. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_record as REC
from api.sniper import api_enabled

VERSION = "api/sniper_trades 2 (R29b)"
PATH = "/api/v2/sniper_trades"


def answer(d, limit=30, now=None):
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
        return 200, {"state": "off", "paper_only": True, "open": [], "closed": [], "text": "The Sniper is switched off (file v2_sniper_off)."}
    try:
        return 200, REC.build(d, time.time() if now is None else now, max(1, min(int(limit), 100)))
    except Exception as e:
        return 200, {"state": "error", "text": "%s: %s" % (type(e).__name__, str(e)[:80]), "open": [], "closed": [], "paper_only": True}


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_trades(limit: int = 30):
        st, body = await asyncio.to_thread(answer, data_dir, limit)
        return JSONResponse(body, status_code=st)
    return r
