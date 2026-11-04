"""api/sniper_lessons.py - OwlSniper LESSONS route + self-relearn loop (R7). ONE read-only route: GET /api/v2/sniper_lessons.
Answer: state (NO_TRADES_YET / LEARNING / ERROR / NOT_LEARNED_YET), trades, counts (GOOD / EXIT_ERROR / SIDEWAYS_LOSS / ENTRY_ERROR / OTHER_LOSS / UNKNOWN), setups ({regime|side: n, mistakes, mistake_share, penalty}),
week ({trades, good, mistakes, lessons: up to 3 plain sentences with numbers}), recent (last 8 trades with their tag), advice_only + paper_only (always true).
ONE daemon thread: first run 9 minutes after start, then every 30 minutes (owl_sniper_lessons.run, persist=True). It writes ONLY v2_sniper_lessons.json and sleeps while the file v2_sniper_off exists. No trade is opened or changed.
Same switch as the other V2 routes: 404 until v2_api_enabled exists. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_lessons as LS
from api.sniper import api_enabled

VERSION = "api/sniper_lessons 1 (R7)"
PATH = "/api/v2/sniper_lessons"
FIRST_DELAY, EVERY = 540, 1800
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
    st = LS.load(d)
    extra = {"turns": _state["turns"], "running": _state["running"], "last_run": _state["last"]}
    if st is None:
        return 200, dict(state="NOT_LEARNED_YET", paper_only=True, advice_only=True, version=VERSION, counts={}, setups={}, week={}, age_sec=None,
                         reasons=["The lessons memory has not run yet. First run starts about 9 minutes after the backend starts, then every 30 minutes."], **extra)
    return 200, dict(st, version=VERSION, age_sec=round(now - (st.get("made") or now), 1), **extra)


def _loop(d):
    time.sleep(FIRST_DELAY)
    while True:
        try:
            if not _off(d) and _lock.acquire(blocking=False):
                _state["running"] = True
                try:
                    t0 = time.time()
                    st = LS.run(d, persist=True)
                    _state["last"] = {"at": int(time.time()), "state": st.get("state"), "seconds": round(time.time() - t0, 1), "trades": st.get("trades")}
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
    threading.Thread(target=_loop, args=(d,), name="owl-sniper-lessons", daemon=True).start()
    return True


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_lessons():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)

    start_loop(data_dir)
    return r
