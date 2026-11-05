"""api/v2_grad_dual.py - Part 17c: GRADUATION GATE of the Dual Bot / Brain + the LAB AUTO-RUN state, ONE read-only route GET /api/v2/grad_dual.
It wires v2_graduation.py (Part 69, built but never called) to the app: \"has the PAPER bot earned a tiny live test?\" = 7 checks per arm, a verdict, never a switch.
(api/sniper_grad.py is a different file: the graduation of the SNIPER.) Also returns the last result of the automatic Scalp Lab / Ledger run (v2_lab_auto.json).
Answer: state (OK / error), grad {arms {current_bot, brain_own: {verdict, passed, failed, waiting, checks[], numbers}}, notes, limits}, auto {last_run_ts, runs, steps}, age_sec, paper_only.
Reads only (mode=ro inside v2_graduation). Cached 10 minutes, ONE build at a time. Same switch as the other V2 routes: 404 until v2_api_enabled exists. Nothing here can send an order.
Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.sniper import api_enabled

VERSION = "api/v2_grad_dual 1 (Part 17c)"
PATH = "/api/v2/grad_dual"
CACHE_SEC = 600
_cache = {"ts": 0.0, "body": None}
_lock = threading.Lock()


def grad_answer(data_dir, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    body = _cache["body"]
    if body is not None and now - _cache["ts"] < CACHE_SEC:
        return 200, dict(body, age_sec=round(now - _cache["ts"], 1))
    if not _lock.acquire(blocking=False):
        if body is not None:
            return 200, dict(body, age_sec=round(now - _cache["ts"], 1), refreshing=True)
        return 200, {"state": "busy", "paper_only": True}
    try:
        try:
            import v2_graduation as G
            import v2_lab_auto as LA
            res = {"state": "OK", "grad": G.build_report(os.path.realpath(data_dir)), "auto": LA.read_state(data_dir)}
        except Exception as e:                                   # a damaged archive must never stop the backend
            res = {"state": "error", "text": "The graduation report could not be built: %s." % str(e)[:80]}
        res["paper_only"], res["version"] = True, VERSION
        _cache["ts"], _cache["body"] = now, res
        return 200, dict(res, age_sec=0.0)
    finally:
        _lock.release()


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_grad_dual():
        st, body = await asyncio.to_thread(grad_answer, data_dir)
        return JSONResponse(body, status_code=st)

    return r
