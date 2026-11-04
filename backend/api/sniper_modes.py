"""api/sniper_modes.py - OwlSniper MODES route + self-relearn loop (R6a). ONE read-only route: GET /api/v2/sniper_modes.
Answer: state (EXPLORE_MODE / LEARNED_MODE / NOT_LEARNED_YET), reasons (plain English), modes ({regime|tf: {mode SCALP / SHORT_SWING / SWING, median_speed, n}}), compare (unseen days: fixed 2R vs the mode lines, in R after fees),
n_train, n_test, days, lookback (R6b: weekly tuning summary from owl_sniper_lookback.py), advice_only + paper_only (always true).
ONE daemon thread: first run 7 minutes after start, then every 30 minutes (owl_sniper_modes.run, persist=True). It writes ONLY v2_sniper_modes.json and sleeps while the file v2_sniper_off exists. No trade is opened or changed.
Same switch as the other V2 routes: 404 until v2_api_enabled exists. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_lookback as LB
import owl_sniper_modes as M
from api.sniper import api_enabled

VERSION = "api/sniper_modes 2 (R6a + R6b)"
PATH = "/api/v2/sniper_modes"
FIRST_DELAY, EVERY = 420, 1800
_state = {"started": False, "last": None, "turns": 0, "running": False}
_lock = threading.Lock()


def _off(d):
    return os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE))


def answer(d, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if _off(d):
        return 200, {"state": "off", "paper_only": True, "reasons": ["The Sniper is switched off (file v2_sniper_off)."]}
    st = M.load(d)
    extra = {"turns": _state["turns"], "running": _state["running"], "last_run": _state["last"]}
    if st is None:
        return 200, dict(state="NOT_LEARNED_YET", paper_only=True, advice_only=True, version=VERSION, modes={}, age_sec=None, lookback={"built": False},
                         reasons=["The modes learner has not run yet. First run starts about 7 minutes after the backend starts, then every 30 minutes."], **extra)
    return 200, dict(st, lookback=LB.summary(d), version=VERSION, age_sec=round(now - (st.get("made") or now), 1), **extra)


def _loop(d):
    time.sleep(FIRST_DELAY)
    while True:
        try:
            if not _off(d) and _lock.acquire(blocking=False):
                _state["running"] = True
                try:
                    t0 = time.time()
                    st = M.run(d, persist=True)
                    _state["last"] = {"at": int(time.time()), "state": st.get("state"), "seconds": round(time.time() - t0, 1), "note": (st.get("reasons") or [""])[0][:120]}
                    _state["turns"] += 1
                    LB.run(d)                            # R6b: gates itself, real work only once a week
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
    threading.Thread(target=_loop, args=(d,), name="owl-sniper-modes", daemon=True).start()
    return True


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_modes():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)

    start_loop(data_dir)
    return r
