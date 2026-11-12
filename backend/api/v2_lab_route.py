"""api/v2_lab_route.py - R9 / Lab backend A: ONE route for the indicator study results. GET /api/v2/lab_results[?family=zsma|sd_bands|pairs|combos|brain|exit|dual|ignored|wick|regime|scalp|loss|exitrule][&verdict=EDGE|DIAGNOSIS_ONLY|LOSING|NO_EDGE|NOT_ENOUGH_DATA].
Answer: {summary {total, by_verdict, by_family, line}, results [TestResult, EDGE first], meta {family: state}, refresh {last run}, running, paper_only, advice_only}. TestResult shape and verdict rules: v2_testresults.py. Sources: v2_testresults_src.py.
The route itself only READS four small saved files (cheap). ONE daemon thread builds them: first run 10 minutes after the backend starts, then every 6 hours (v2_testresults_src.refresh: each study reads the saved candles, read only). It writes ONLY v2_sniper_zsma.json, v2_sniper_sdbands.json, v2_sniper_ind_pairs.json, v2_sniper_combo.json and (R10) v2_lab_results_b.json, and sleeps while the file v2_sniper_off exists.
R12 adds GET /api/v2/lab_exit (9 exit rules x market state, file v2_lab_exit.json). R11 adds GET /api/v2/lab_loss (the loss-source card: Entry / Exit / Sideways) and the replay file v2_lab_loss.json. Same switch as the other V2 routes: 404 until v2_api_enabled exists. Mounted by api/sniper_mount.py. No trade is opened or changed.
"""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import v2_testresults as T
import v2_testresults_src as SRC
from api.sniper import api_enabled

VERSION = "api/v2_lab_route 5 (R9 to R12 + Part 20 report)"
PATH = "/api/v2/lab_results"
PATH_LOSS = "/api/v2/lab_loss"
PATH_EXIT = "/api/v2/lab_exit"
PATH_REPORT, PATH_REPORT_SAVE = "/api/v2/lab_report", "/api/v2/lab_report_save"
FIRST_DELAY, EVERY = 600, 21600
_state = {"started": False, "last": None, "runs": 0, "running": False}
_lock = threading.Lock()


def _off(d):
    return os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE))


def answer(d, family=None, verdict=None, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if _off(d):
        return 200, {"state": "off", "paper_only": True, "results": [], "summary": T.summary([]), "note": "The Sniper is switched off (file v2_sniper_off)."}
    rs, meta = SRC.collect(d, now)
    summ = T.summary(rs)                                         # the summary counts ALL tests, the filter only trims the list
    if family in T.FAMILIES:
        rs = [r for r in rs if r["family"] == family]
    if verdict in T.VERDICTS:
        rs = [r for r in rs if r["verdict"] == verdict]
    note = None if summ["total"] else "No study result yet. The first run starts about 10 minutes after the backend starts and takes a few minutes."
    return 200, {"version": VERSION, "paper_only": True, "advice_only": True, "summary": summ, "results": rs, "shown": len(rs), "meta": meta, "refresh": _state["last"],
                 "runs": _state["runs"], "running": _state["running"], "filter": {"family": family if family in T.FAMILIES else None, "verdict": verdict if verdict in T.VERDICTS else None}, "note": note}


def _g(v, nd=2):
    return "n/a" if not isinstance(v, (int, float)) or isinstance(v, bool) else str(round(v, nd))


def report_text(d, now=None):
    """Part 20: ONE text report of the whole Study Lab Results board (every test: verdict, n, win %, R each, lift, train / test halves, coins). For the app Share / Copy button, same idea as the Filter Lab report. Read only. -> text, or None when the V2 data API is off. Never raises."""
    try:
        st, body = answer(d, None, None, now)
        if st != 200:
            return None
        rs, summ = body.get("results") or [], body.get("summary") or {}
        out = ["OWL STUDY LAB RESULTS REPORT", "time: " + time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(time.time() if now is None else now)), "",
               "HOW TO READ: R = one unit of risk (1R = the stop loss). Paper replay of saved candles (+2R / -1R, 30 candles, fees in), NOT real trades, NOT a promise.",
               "EDGE = 30+ cases and the same sign in BOTH halves (train / test). CANDIDATE (DIAGNOSIS_ONLY) = looked good, not proven. NOT_ENOUGH_DATA = fewer than the needed cases. NO_EDGE = nothing. LOSING = costs money.",
               "A verdict is evidence for a LOG test, not an order. No test here changes a trade. Paper money only. Not financial advice.", ""]
        out.append("SUMMARY: %s tests. %s" % (summ.get("total"), summ.get("line") or ""))
        out.append("by verdict: %s" % summ.get("by_verdict"))
        out.append("by family: %s" % summ.get("by_family"))
        out.append("")
        for v in T.VERDICTS:
            grp = [r for r in rs if r.get("verdict") == v]
            out.append("=== %s (%d) ===" % (v, len(grp)))
            for r in grp:
                out.append("- [%s] %s | %s %s | n %s of %s | win %s%% | %s R each | lift %s R | halves %s / %s | %s%% of coins" % (
                    r.get("family"), r.get("title"), r.get("side") or "", r.get("context") or "", r.get("have_n", r.get("n")), r.get("need_n"),
                    _g(r.get("win_pct"), 0), _g(r.get("exp_r")), _g(r.get("lift_r")), _g(r.get("lift_train")), _g(r.get("lift_test")), _g(r.get("coins_beat_pct"), 0)))
                if r.get("headline"):
                    out.append("    " + str(r.get("headline"))[:240])
                if v == "NOT_ENOUGH_DATA" and r.get("reason_missing"):
                    out.append("    missing: " + str(r.get("reason_missing"))[:160])
            out.append("")
        return "\n".join(out)
    except Exception as e:
        return "OWL STUDY LAB RESULTS REPORT\nreport failed: %s: %s" % (type(e).__name__, str(e)[:120])


def answer_loss(d, now=None):
    """R11: GET /api/v2/lab_loss = where the money is lost (Entry / Exit / Sideways) + the two fix checks, for the Lab card. -> (http status, body). Never raises."""
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if _off(d):
        return 200, {"state": "off", "paper_only": True, "buckets": [], "line": "The Sniper is switched off (file v2_sniper_off)."}
    return 200, dict(SRC.loss(d, now), paper_only=True, advice_only=True)


def answer_exit(d, now=None):
    """R12: GET /api/v2/lab_exit = the 9 exit rules x market state table (mean R after fees, train pick, unseen-days verdict), for the Lab card. -> (http status, body). Never raises."""
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if _off(d):
        return 200, {"state": "off", "paper_only": True, "states": [], "rules": [], "line": "The Sniper is switched off (file v2_sniper_off)."}
    return 200, dict(SRC.exits(d, now), paper_only=True, advice_only=True)


def _loop(d):
    time.sleep(FIRST_DELAY)
    while True:
        try:
            if not _off(d) and _lock.acquire(blocking=False):
                _state["running"] = True
                try:
                    t0 = time.time()
                    res = SRC.refresh(d)
                    _state["last"] = {"at": int(time.time()), "seconds": round(time.time() - t0, 1), "result": res}
                    _state["runs"] += 1
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
    threading.Thread(target=_loop, args=(d,), name="owl-lab-results", daemon=True).start()
    return True


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_lab_results(family: str = None, verdict: str = None):
        st, body = await asyncio.to_thread(answer, data_dir, family, verdict)
        return JSONResponse(body, status_code=st)

    # Part 20: same as /api/v2/filter_report: no token (the app's report card sends none), read only.
    @r.get(PATH_REPORT)
    async def v2_lab_report():
        from fastapi.responses import PlainTextResponse
        txt = await asyncio.to_thread(report_text, data_dir)
        if txt is None:
            return PlainTextResponse("The V2 data API is off.", status_code=404)
        return PlainTextResponse(txt)

    @r.get(PATH_REPORT_SAVE)
    async def v2_lab_report_save():
        return JSONResponse({"ok": False, "hint": "The backend runs on the VPS, so it cannot save into the phone. Use Share or Copy."})

    @r.get(PATH_LOSS, dependencies=[Depends(require_api_token)])
    async def v2_lab_loss():
        st, body = await asyncio.to_thread(answer_loss, data_dir)
        return JSONResponse(body, status_code=st)

    @r.get(PATH_EXIT, dependencies=[Depends(require_api_token)])
    async def v2_lab_exit():
        st, body = await asyncio.to_thread(answer_exit, data_dir)
        return JSONResponse(body, status_code=st)

    start_loop(data_dir)
    return r
