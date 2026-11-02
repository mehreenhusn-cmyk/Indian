"""api/sniper_paper.py - OwlSniper Round 30: the ONE write route of the Sniper, POST /api/v2/sniper_enter {"symbol": "BTCUSDT"} (the PAPER ENTER button), and the background loop that follows armed signals.
PAPER ONLY. Live orders do not exist. The route runs the SAME ten gates of owl_sniper_exec.py as the loop (armed, paper, signal, fresh, TRENDING, 85% floor proven, stop range, cap 1, kill switch, same signal never twice);
if the executor is not armed the answer is decision BLOCKED, gate "armed", text "The executor is OFF (not armed)." and nothing is opened. No route can arm: arming stays the 2-step Termux command.
Same switch as the other V2 routes: 404 until the file v2_api_enabled exists in the data folder, and off for good while the file v2_sniper_off exists.
The loop (a daemon thread started once when the router is made) wakes every LOOP_SEC seconds, never faster: owl_sniper_paper.step() closes the books of finished Sniper trades (net result to the executor, time limit exit) and,
ONLY while the executor is armed, offers the newest cards to the gates. It needs recovered_bot (paper_trader, trade_store) inside this process; a failure of any turn is swallowed so the backend never stops.
MOUNTED by api_server.py (Round 30, 5 added lines, try / except, owner ok "mount ok")."""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_paper as SP
from api.sniper import api_enabled

VERSION = "api/sniper_paper 1 (Round 30)"
ENTER_PATH = "/api/v2/sniper_enter"
LOOP_SEC = 20
_state = {"started": False, "last": None, "turns": 0}
_state_lock = threading.Lock()


def _modules():
    from recovered_bot import paper_trader, trade_store
    return paper_trader, trade_store


def enter_answer(data_dir, symbol, now=None):
    """-> (http status, body). Never raises."""
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    sym = str(symbol or "").strip().upper()
    if not sym.isalnum() or len(sym) > 24:
        return 400, {"decision": "BLOCKED", "gate": "input", "text": "The coin name is not valid.", "order": None}
    if os.path.exists(os.path.join(os.path.realpath(data_dir), F.OFF_FILE)):
        return 200, {"decision": "BLOCKED", "gate": "off", "text": "The Sniper is switched off (file v2_sniper_off).", "order": None}
    try:
        pt, ts = _modules()
    except Exception:
        return 503, {"decision": "BLOCKED", "gate": "paper", "text": "The paper trader is not available in this backend.", "order": None}
    body = SP.enter_symbol(data_dir, pt, ts, sym, now)
    body["paper_only"] = True
    return 200, body


def _loop(data_dir):
    while True:
        time.sleep(LOOP_SEC)
        try:
            if not api_enabled(data_dir) or os.path.exists(os.path.join(os.path.realpath(data_dir), F.OFF_FILE)):
                continue
            pt, ts = _modules()
            res = SP.step(data_dir, pt, ts)
            with _state_lock:
                _state["last"], _state["turns"] = res, _state["turns"] + 1
        except Exception:
            pass


def start_loop(data_dir):
    with _state_lock:
        if _state["started"]:
            return False
        _state["started"] = True
    threading.Thread(target=_loop, args=(data_dir,), name="owl-sniper-paper", daemon=True).start()
    return True


def make_router(require_api_token, data_dir):
    """Mounted by api_server.py (Round 30): 1 POST route behind the app's token check, plus the background loop."""
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.post(ENTER_PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_enter(payload: dict = None):
        st, body = await asyncio.to_thread(enter_answer, data_dir, (payload or {}).get("symbol"))
        return JSONResponse(body, status_code=st)

    start_loop(data_dir)
    return r
