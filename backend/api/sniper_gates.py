"""api/sniper_gates.py - OwlSniper R26b: ONE read-only route GET /api/v2/sniper_gates = the 8-gate checklist + the mistakes journal (owl_sniper_why.build).
Answer: gates [{id, name, state PASS / FAIL / WAIT, text, lane}], explore {state, text}, real {state, text}, reason, cards, mistakes {state, trades, counts, blocked[], journal[], rule}.
Read only: it writes nothing (the mistakes file is written by the paper loop). 404 until v2_api_enabled exists, off while v2_sniper_off exists. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_why as W
from api.sniper import api_enabled

VERSION = "api/sniper_gates 1 (R26b)"
PATH = "/api/v2/sniper_gates"


def answer(d, now=None):
    """-> (http status, body). Never raises."""
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    try:
        return 200, W.build(d, time.time() if now is None else now)
    except Exception as e:
        return 200, {"state": "error", "text": "%s: %s" % (type(e).__name__, str(e)[:80]), "gates": [], "paper_only": True}


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_gates():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)
    return r
