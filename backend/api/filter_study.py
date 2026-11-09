"""api/filter_study.py - Part 8A (README_FILTER): the routes behind the app's Filter Lab tab. Study = read only. The ONLY thing that can change trading is the gate mode switch (Part 7), default OFF.
Same switch as the other V2 routes: 404 until the file v2_api_enabled exists in the data folder; every route is behind the app's token check.
  GET  /api/v2/filter            overview: gate (mode, rules, counters), study run (running, current Part, done, failed), the 9 Parts with the time of their saved summary, auto-run ON / OFF, last gate log lines   (read only)
  GET  /api/v2/filter_part       ?id=f1|f1b|f2|f3a|f3b|f4|f5a|f5b|f6  the saved summary of one Part {id, saved_ts, data} or {id, state: "none"}                                                    (read only)
  GET  /api/v2/filter_rules      the gate rules file (v2_f7_rules.json): status, rules with their TRAIN / TEST numbers, the numbers of all rules together                                                    (read only)
  POST /api/v2/filter_run        starts ONE study run in the background (Parts 1 to 6, low priority). 409 when one is already going on.                                               (writes only v2_filter_*.json)
  POST /api/v2/filter_gate       {"mode": "off" | "log" | "block"}  sets the setting f7_gates_mode (Part 7). off = nothing | log = only writes what it would block | block = skips the entry. Current bot, 5m only.
The study also starts by itself: a daemon thread (started once when the router is made) wakes every 10 min and starts a run when the last one finished more than 24 h ago (or never ran).
Setting f8_study_auto (default True) = False stops that. No order code. MOUNTED by api/sniper_mount.py (one line in ROUTES), in its own try / except."""
import asyncio
import json
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import v2_f7_gates as G
import v2_f8_runner as R
from api.sniper import api_enabled

VERSION = "api/filter_study 1 (Part 8A)"
PATH_MAIN, PATH_PART, PATH_RULES = "/api/v2/filter", "/api/v2/filter_part", "/api/v2/filter_rules"
PATH_RUN, PATH_GATE = "/api/v2/filter_run", "/api/v2/filter_gate"
PATH_REPORT, PATH_REPORT_SAVE = "/api/v2/filter_report", "/api/v2/filter_report_save"
PART_CAP = 120000  # max characters per Part in the report text
MODES = ("off", "log", "block")
LOOP_SEC, FIRST_WAIT_SEC, AUTO_EVERY_SEC = 600, 900, 24 * 3600
OFF_ANSWER = {"enabled": False, "note": "the V2 data API is off"}
_state = {"started": False}
_lock = threading.Lock()


def _root(data_dir):
    return os.path.realpath(data_dir)


def _read_json(path):
    try:
        if os.path.islink(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _auto_on():
    try:
        from recovered_bot import settings_store
        return bool(settings_store.get("f8_study_auto", True))
    except Exception:
        return True


def _log_tail(root, n=15):
    """The last n lines of the gate log (what the gate hit), newest last. Reads only the end of the file."""
    p = os.path.join(root, G.LOG_FILE)
    try:
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 65536))
            lines = f.read().decode("utf-8", "replace").splitlines()[-n:]
        out = []
        for x in lines:
            try:
                out.append(json.loads(x))
            except ValueError:
                pass
        return out
    except OSError:
        return []


def main_answer(data_dir):
    if not api_enabled(data_dir):
        return 404, OFF_ANSWER
    root = _root(data_dir)
    try:
        run = R.read_state(root)
        run["running"] = R.is_running(root)
        return 200, {"gate": G.info(), "run": run, "parts": [{"id": pid, "label": label, "saved_ts": R.summary_time(root, pid)} for pid, _s, label in R.PARTS],
                     "auto": _auto_on(), "gate_log": _log_tail(root), "paper_only": True}
    except Exception as e:
        return 500, {"error": "%s: %s" % (type(e).__name__, str(e)[:120])}


def part_answer(data_dir, pid):
    if not api_enabled(data_dir):
        return 404, OFF_ANSWER
    if pid not in R.PART_IDS:
        return 400, {"error": "id must be one of: " + ", ".join(R.PART_IDS)}
    root = _root(data_dir)
    data = _read_json(os.path.join(root, R.SUM_FILE % pid))
    if data is None:
        return 200, {"id": pid, "state": "none", "note": "No saved summary yet. The study run makes it."}
    return 200, {"id": pid, "saved_ts": R.summary_time(root, pid), "data": data}


def rules_answer(data_dir):
    if not api_enabled(data_dir):
        return 404, OFF_ANSWER
    rep = _read_json(os.path.join(_root(data_dir), G.RULES_FILE))
    if not isinstance(rep, dict):
        return 200, {"state": "none", "note": "No rules file yet. It is made after the gate mode is log or block (a few minutes)."}
    return 200, rep


def report_text(data_dir):
    """One text file with all saved Part summaries (for the app Share / Copy button). Read only."""
    if not api_enabled(data_dir):
        return None
    root = _root(data_dir)
    out = ["OWL FILTER LAB REPORT", "time: " + time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), ""]
    for pid, _s, label in R.PARTS:
        data = _read_json(os.path.join(root, R.SUM_FILE % pid))
        out.append("=== %s - %s ===" % (pid, label))
        if data is None:
            out += ["no saved summary yet", ""]
            continue
        txt = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        out += [txt[:PART_CAP] + (" ...cut" if len(txt) > PART_CAP else ""), ""]
    return "\n".join(out)


def run_answer(data_dir):
    if not api_enabled(data_dir):
        return 404, OFF_ANSWER
    ok, text = R.start(_root(data_dir))
    return (200 if ok else 409), {"started": ok, "note": text, "run": R.read_state(_root(data_dir))}


def gate_answer(data_dir, mode):
    if not api_enabled(data_dir):
        return 404, OFF_ANSWER
    mode = str(mode or "").lower()
    if mode not in MODES:
        return 400, {"error": "mode must be off, log or block"}
    try:
        from recovered_bot import settings_store
        settings_store.update(f7_gates_mode=mode)
    except Exception as e:
        return 500, {"error": "%s: %s" % (type(e).__name__, str(e)[:120])}
    return 200, {"mode": mode, "note": {"off": "Gate is OFF.", "log": "Gate only writes what it would block.", "block": "Gate skips the entry when a rule hits."}[mode]}


def _quiet():
    """Auto run only while the VPS is calm: 1-minute load below 60% of the CPU cores. A busy server is left alone (the live bot comes first)."""
    try:
        return os.getloadavg()[0] < max(0.8, (os.cpu_count() or 1) * 0.6)
    except Exception:
        return True


def _loop(data_dir):
    time.sleep(FIRST_WAIT_SEC)
    while True:
        try:
            root = _root(data_dir)
            if api_enabled(data_dir) and _auto_on() and _quiet() and not R.is_running(root):
                last = R.read_state(root).get("finished_ts")
                if not last or time.time() - last > AUTO_EVERY_SEC:
                    R.start(root)
        except Exception:
            pass
        time.sleep(LOOP_SEC)


def start_loop(data_dir):
    with _lock:
        if _state["started"]:
            return False
        _state["started"] = True
    threading.Thread(target=_loop, args=(data_dir,), name="owl-filter-study", daemon=True).start()
    return True


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse, PlainTextResponse
    r = APIRouter()

    # Same as /api/report/app: no token, because the app's report card sends none. Read only.
    @r.get(PATH_REPORT)
    async def v2_filter_report():
        txt = await asyncio.to_thread(report_text, data_dir)
        if txt is None:
            return PlainTextResponse("The V2 data API is off.", status_code=404)
        return PlainTextResponse(txt)

    @r.get(PATH_REPORT_SAVE)
    async def v2_filter_report_save():
        return JSONResponse({"ok": False, "hint": "The backend runs on the VPS, so it cannot save into the phone. Use Share or Copy."})

    @r.get(PATH_MAIN, dependencies=[Depends(require_api_token)])
    async def v2_filter():
        st, body = await asyncio.to_thread(main_answer, data_dir)
        return JSONResponse(body, status_code=st)

    @r.get(PATH_PART, dependencies=[Depends(require_api_token)])
    async def v2_filter_part(id: str = "f1"):
        st, body = await asyncio.to_thread(part_answer, data_dir, id)
        return JSONResponse(body, status_code=st)

    @r.get(PATH_RULES, dependencies=[Depends(require_api_token)])
    async def v2_filter_rules():
        st, body = await asyncio.to_thread(rules_answer, data_dir)
        return JSONResponse(body, status_code=st)

    @r.post(PATH_RUN, dependencies=[Depends(require_api_token)])
    async def v2_filter_run():
        st, body = await asyncio.to_thread(run_answer, data_dir)
        return JSONResponse(body, status_code=st)

    @r.post(PATH_GATE, dependencies=[Depends(require_api_token)])
    async def v2_filter_gate(payload: dict = None):
        st, body = await asyncio.to_thread(gate_answer, data_dir, (payload or {}).get("mode"))
        return JSONResponse(body, status_code=st)

    start_loop(data_dir)
    return r
