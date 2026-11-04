"""api/sniper_autopilot.py - OwlSniper AUTOPILOT route + self-relearn loop (R3b). ONE read-only route: GET /api/v2/sniper_autopilot.
Answer: state (EXPLORE / LEARNED), reasons (plain English), counts (train / test trades, days), compare (unseen days: take-everything vs the model's picks, in R after fees), cut, age_sec, last_run, paper_only (always true). Model weights are NOT sent (too big, not for the screen).
Making the router starts ONE daemon thread: first run 2 min after start, then every 30 min it re-learns from ALL saved trades (owl_sniper_autopilot.run, persist=True) and writes ONLY v2_sniper_autopilot.json. No trade is opened, no order path, nothing live.
The thread sleeps while the file v2_sniper_off exists. Same switch as the other V2 routes: 404 until v2_api_enabled exists. Mounted by api/sniper_mount.py.
NOT connected to the paper executor yet (the next step does that, so the app first shows what the autopilot would do)."""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_autopilot as AP
import owl_sniper_feed as F
from api.sniper import api_enabled

VERSION = "api/sniper_autopilot 1 (R3b)"
PATH = "/api/v2/sniper_autopilot"
FIRST_DELAY, EVERY = 120, 1800
_state = {"started": False, "last": None, "turns": 0, "running": False}
_lock = threading.Lock()


def _off(d):
    return os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE))


def short(st):
    """State -> what the screen needs (no model weights)."""
    st = st or {}
    return {"state": st.get("state") or "EXPLORE", "reasons": st.get("reasons") or [], "cut": st.get("cut"), "compare": st.get("compare"),
            "n_train": st.get("n_train"), "n_test": st.get("n_test"), "days": st.get("days"), "feed": st.get("feed"), "made": st.get("made"), "model_ready": bool(st.get("model"))}


def answer(d, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if _off(d):
        return 200, {"state": "off", "paper_only": True, "reasons": ["The Sniper is switched off (file v2_sniper_off)."]}
    st = AP.load(d)
    last = {"turns": _state["turns"], "running": _state["running"], "last_run": _state["last"]}
    if st is None:
        return 200, dict(short(None), paper_only=True, version=VERSION, state="NOT_LEARNED_YET", age_sec=None,
                         reasons=["The autopilot has not learned yet. First run starts about 2 minutes after the backend starts, then every 30 minutes."], **last)
    return 200, dict(short(st), paper_only=True, version=VERSION, age_sec=round(now - (st.get("made") or now), 1), **last)


def _loop(d):
    time.sleep(FIRST_DELAY)
    while True:
        try:
            if not _off(d) and _lock.acquire(blocking=False):
                _state["running"] = True
                try:
                    t0 = time.time()
                    st = AP.run(d, persist=True)
                    _state["last"] = {"at": int(time.time()), "state": st.get("state"), "seconds": round(time.time() - t0, 1), "note": (st.get("reasons") or [""])[0][:120]}
                    _state["turns"] += 1
                finally:
                    _state["running"] = False
                    _lock.release()
        except Exception as e:                                   # the loop must never die
            _state["last"] = {"at": int(time.time()), "error": "%s: %s" % (type(e).__name__, str(e)[:100])}
        time.sleep(EVERY)


def start_loop(d):
    with _lock:
        if _state["started"]:
            return False
        _state["started"] = True
    threading.Thread(target=_loop, args=(d,), name="owl-sniper-autopilot", daemon=True).start()
    return True


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_autopilot():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)

    start_loop(data_dir)
    return r
