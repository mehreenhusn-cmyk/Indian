"""api/chop.py - Part C3 (README_CHOP): the routes and the background loop of the both-indicator paper bot b3 (5m). PAPER ONLY. No order code. The current bot is not touched.
Same switch as the other V2 routes: 404 until the file v2_api_enabled exists in the data folder; every route is behind the app's token check.
  GET  /api/v2/chop           overview: ON / OFF, today and all-time numbers (profit, rally missed, loss avoided), open b3 trades with the last 5m close, last loop turn   (read only)
  GET  /api/v2/chop_log       ?limit=50  the newest decisions (TAKE / SKIP, score, rule, why, 9 parts, verdict) + the newest closed trades                                (read only)
  GET  /api/v2/chop_report    rule report (right / wrong per rule), Missed Rally alarm list, the learning suggestion (current weights, proposed weights, train / test edges)  (read only)
  POST /api/v2/chop_switch    {"on": true / false}  turns the b3 bot ON or OFF (default OFF). OFF = no new decisions, open trades and verdicts still finish.
  POST /api/v2/chop_apply     the owner's OK: saves the proposed weights (chop_b3_weights.json). Refuses when the data is not enough or no change is supported by train and test.
  POST /api/v2/chop_lab       {"interval": "5m" or "15m", "period": "today" / "month" / "all"}  starts the C2 REPLAY as ONE background job (409 if one is running)                 (writes only chop_b3_lab_*.json)
  GET  /api/v2/chop_lab       ?interval=5m&period=month  job progress + the last saved replay result of that interval and period                                          (read only)
Writes ONLY chop_b3.db, chop_b3_weights.json and chop_b3_lab_*.json. The loop (a daemon thread started once when the router is made) wakes every LOOP_SEC seconds and calls chop_bot.step(); a failed turn is swallowed.
MOUNTED by api/sniper_mount.py (one line in ROUTES), in its own try / except."""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import chop_bot as B
import chop_filter_lab as LAB
import chop_ledger as L
from api.sniper import api_enabled

VERSION = "api/chop 1 (Part C3)"
PATH_MAIN, PATH_LOG, PATH_REPORT = "/api/v2/chop", "/api/v2/chop_log", "/api/v2/chop_report"
PATH_SWITCH, PATH_APPLY, PATH_LAB = "/api/v2/chop_switch", "/api/v2/chop_apply", "/api/v2/chop_lab"
LOOP_SEC = 30
_state = {"started": False, "last": None, "turns": 0}
_lock = threading.Lock()
OFF_ANSWER = {"enabled": False, "note": "the V2 data API is off"}


def _run(data_dir, fn):
    """-> (http status, body). Opens the b3 database, calls fn(db), never raises."""
    if not api_enabled(data_dir):
        return 404, OFF_ANSWER
    try:
        db = B.open_db(data_dir)
        try:
            return 200, fn(db)
        finally:
            db.close()
    except Exception as e:
        return 500, {"error": "%s: %s" % (type(e).__name__, str(e)[:120])}


def main_answer(data_dir):
    def f(db):
        body = L.overview(db)
        body["open_trades"] = L.open_trades(db, B.last_prices(data_dir, [r["symbol"] for r in db.execute("SELECT symbol FROM trades WHERE status='OPEN'").fetchall()]))
        with _lock:
            body["loop"] = {"last": _state["last"], "turns": _state["turns"], "every_s": LOOP_SEC}
        body["paper_only"] = True
        return body
    return _run(data_dir, f)


def log_answer(data_dir, limit=50):
    n = max(1, min(int(limit or 50), 200))
    return _run(data_dir, lambda db: {"decisions": L.decisions(db, n), "closed_trades": L.closed_trades(db, n), "paper_only": True})


def report_answer(data_dir):
    return _run(data_dir, lambda db: {"rules": L.rule_report(db), "missed_rallies": L.missed_rallies(db), "learning": L.suggestions(db, data_dir),
                                      "alarm_pct": L.RALLY_ALARM_PCT, "paper_only": True})


def switch_answer(data_dir, on):
    if not isinstance(on, bool):
        return 400, {"error": "send {\"on\": true} or {\"on\": false}"}

    def f(db):
        B.set_on(db, on)
        return {"on": B.is_on(db), "paper_only": True}
    return _run(data_dir, f)


def apply_answer(data_dir):
    return _run(data_dir, lambda db: L.apply_weights(db, data_dir))


def lab_start_answer(data_dir, interval, period):
    if not api_enabled(data_dir):
        return 404, OFF_ANSWER
    ok, text = LAB.start_job(data_dir, interval, period)
    return (200 if ok else 409 if "already" in text else 400), {"started": ok, "note": text, "job": LAB.job_status()}


def lab_get_answer(data_dir, interval, period):
    if not api_enabled(data_dir):
        return 404, OFF_ANSWER
    if interval not in LAB.INTERVALS or period not in LAB.PERIODS:
        return 400, {"error": "interval must be 5m or 15m, period today, month or all"}
    return 200, {"job": LAB.job_status(), "result": LAB.load_result(data_dir, interval, period), "paper_only": True}


def _loop(data_dir):
    while True:
        time.sleep(LOOP_SEC)
        try:
            if not api_enabled(data_dir):
                continue
            res = B.step(data_dir)
            with _lock:
                _state["last"], _state["turns"] = res, _state["turns"] + 1
        except Exception:
            pass


def start_loop(data_dir):
    with _lock:
        if _state["started"]:
            return False
        _state["started"] = True
    threading.Thread(target=_loop, args=(data_dir,), name="owl-chop-b3", daemon=True).start()
    return True


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH_MAIN, dependencies=[Depends(require_api_token)])
    async def v2_chop():
        st, body = await asyncio.to_thread(main_answer, data_dir)
        return JSONResponse(body, status_code=st)

    @r.get(PATH_LOG, dependencies=[Depends(require_api_token)])
    async def v2_chop_log(limit: int = 50):
        st, body = await asyncio.to_thread(log_answer, data_dir, limit)
        return JSONResponse(body, status_code=st)

    @r.get(PATH_REPORT, dependencies=[Depends(require_api_token)])
    async def v2_chop_report():
        st, body = await asyncio.to_thread(report_answer, data_dir)
        return JSONResponse(body, status_code=st)

    @r.post(PATH_SWITCH, dependencies=[Depends(require_api_token)])
    async def v2_chop_switch(payload: dict = None):
        st, body = await asyncio.to_thread(switch_answer, data_dir, (payload or {}).get("on"))
        return JSONResponse(body, status_code=st)

    @r.post(PATH_APPLY, dependencies=[Depends(require_api_token)])
    async def v2_chop_apply():
        st, body = await asyncio.to_thread(apply_answer, data_dir)
        return JSONResponse(body, status_code=st)

    @r.post(PATH_LAB, dependencies=[Depends(require_api_token)])
    async def v2_chop_lab_start(payload: dict = None):
        p = payload or {}
        st, body = await asyncio.to_thread(lab_start_answer, data_dir, p.get("interval", "5m"), p.get("period", "month"))
        return JSONResponse(body, status_code=st)

    @r.get(PATH_LAB, dependencies=[Depends(require_api_token)])
    async def v2_chop_lab_get(interval: str = "5m", period: str = "month"):
        st, body = await asyncio.to_thread(lab_get_answer, data_dir, interval, period)
        return JSONResponse(body, status_code=st)

    start_loop(data_dir)
    return r
