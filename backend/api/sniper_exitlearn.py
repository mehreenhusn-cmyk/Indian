"""api/sniper_exitlearn.py - OwlSniper BOOKING LEARNER route + self-relearn loop (R4). ONE read-only route: GET /api/v2/sniper_exitlearn.
R5: the same route and loop also run the better-entry learner (owl_sniper_entrylearn, writes ONLY v2_sniper_entrylearn.json) and answer under "entry" (state EXPLORE_ENTRY / LEARNED_ENTRY, rules, fill_pct, compare; ADVICE ONLY, nothing live uses it).
Answer: state (EXPLORE_EXIT / LEARNED_EXIT / NOT_LEARNED_YET), reasons (plain English), rules (best LIVE-capable profit line per market state), advice (best of all rules, incl. break-even / trail / time: advice only),
compare (unseen days: fixed 2R vs the learned choice, in R after fees), left_on_table (best move after entry minus what the default booked), n_train, n_test, days, paper_only (always true).
Making the router starts ONE daemon thread: first run 5 min after start (the autopilot runs at 2 min), then every 30 min it re-learns from all saved trades (owl_sniper_exitlearn.run, persist=True) and writes ONLY v2_sniper_exitlearn.json.
No trade is opened here. The paper LEARN lane reads the result through owl_sniper_exitlearn.live_tp_r (see owl_sniper_paper._learned_tp); the owner switch is the file v2_exitlearn_off.
The thread sleeps while the file v2_sniper_off exists. Same switch as the other V2 routes: 404 until v2_api_enabled exists. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_entrylearn as EL
import owl_sniper_exitlearn as XL
import owl_sniper_feed as F
import owl_sniper_tpsl as TS
import owl_sniper_xrules as XR
from api.sniper import api_enabled

VERSION = "api/sniper_exitlearn 1 (R4)"
PATH = "/api/v2/sniper_exitlearn"
FIRST_DELAY, EVERY = 300, 1800
_state = {"started": False, "last": None, "turns": 0, "running": False}
_lock = threading.Lock()


def _off(d):
    return os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE))


def short(st):
    st = st or {}
    return {"state": st.get("state") or "EXPLORE_EXIT", "reasons": st.get("reasons") or [], "rules": st.get("rules") or {}, "advice": st.get("advice") or {}, "compare": st.get("compare"),
            "left_on_table": st.get("left_on_table"), "n_train": st.get("n_train"), "n_test": st.get("n_test"), "days": st.get("days"), "feed": st.get("feed"), "made": st.get("made"),
            "default": st.get("default")}


def short_entry(st):
    st = st or {}
    return {"state": st.get("state") or "NOT_LEARNED_YET", "reasons": st.get("reasons") or [], "rules": st.get("rules") or {}, "fill_pct": st.get("fill_pct"), "mean_r_all": st.get("mean_r_all"),
            "compare": st.get("compare"), "n_train": st.get("n_train"), "n_test": st.get("n_test"), "days": st.get("days"), "made": st.get("made"), "advice_only": True}


def short_tpsl(st):
    """R32a: the TP/SL combo learner (owl_sniper_tpsl, own file v2_sniper_tpsl.json). Paper LEARN lane only; v2_tpsl_off switches it off."""
    st = st or {}
    return {"state": st.get("state") or "NOT_LEARNED_YET", "reasons": st.get("reasons") or [], "rules": st.get("rules") or {}, "grid": st.get("grid") or {}, "compare": st.get("compare"),
            "n_train": st.get("n_train"), "n_test": st.get("n_test"), "days": st.get("days"), "made": st.get("made"), "default": st.get("default"), "switch_off": False}


def answer(d, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if _off(d):
        return 200, {"state": "off", "paper_only": True, "reasons": ["The Sniper is switched off (file v2_sniper_off)."]}
    st = XL.load(d)
    last = {"entry": short_entry(EL.load(d)), "turns": _state["turns"], "running": _state["running"], "last_run": _state["last"], "learn_lane_switch_off": os.path.exists(os.path.join(os.path.realpath(d), XL.OFF_FILE)),
            "ab": XR.view(d),
            "tpsl": dict(short_tpsl(TS.load(d)), switch_off=os.path.exists(os.path.join(os.path.realpath(d), TS.OFF_FILE)))}
    if st is None:
        return 200, dict(short(None), paper_only=True, version=VERSION, state="NOT_LEARNED_YET", age_sec=None,
                         reasons=["The booking learner has not run yet. First run starts about 5 minutes after the backend starts, then every 30 minutes."], **last)
    return 200, dict(short(st), paper_only=True, version=VERSION, age_sec=round(now - (st.get("made") or now), 1), **last)


def _loop(d):
    time.sleep(FIRST_DELAY)
    while True:
        try:
            if not _off(d) and _lock.acquire(blocking=False):
                _state["running"] = True
                try:
                    t0 = time.time()
                    st = XL.run(d, persist=True)
                    EL.run(d, persist=True)                              # R5: the entry learner runs right after (own file, advice only)
                    TS.run(d, persist=True)                              # R32a: the TP/SL combo learner (own file, paper LEARN lane only)
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
    threading.Thread(target=_loop, args=(d,), name="owl-sniper-exitlearn", daemon=True).start()
    return True


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_exitlearn():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)

    start_loop(data_dir)
    return r
