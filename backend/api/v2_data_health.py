"""api/v2_data_health.py - Part 17d: DATA HEALTH, ONE read-only route GET /api/v2/data_health. It puts on one page what was only in separate routes / files:
  candles   the candle switch (ON / OFF, and whether the OWNER switched it off), the runner heartbeat, newest saved 5m candle age is NOT here (see health_v2).
  history   what is missing for the Sniper's training data, per source (dual / brain / main, never added): the answer of api/sniper_hist (needs_fetch, too_old, known_gap ...), plain lines.
  learning  the autopilot file (state EXPLORE / LEARNED, examples train / test, days, reasons) and its age.
  jobs      when each background file was LAST WRITTEN (autopilot, exit-learn, watchlist, lab auto-run). It says only the age, it does not guess if a job is alive.
Reads only. Cached 60 s. Same switch as the other V2 routes (404 until v2_api_enabled exists). Mounted by api/sniper_mount.py. Nothing here can send an order.
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.sniper import api_enabled

VERSION = "api/v2_data_health 1 (Part 17d)"
PATH = "/api/v2/data_health"
CACHE_SEC = 60
_cache = {"ts": 0.0, "body": None}
JOBS = (("autopilot", "Autopilot (self-learning)", "v2_sniper_autopilot.json"), ("exitlearn", "Exit learner", "v2_sniper_exitlearn.json"),
        ("watch", "Watchlist scan", "v2_sniper_watch.json"), ("lab_auto", "Scalp Lab and Ledger run", "v2_lab_auto.json"))


def _age(path, now):
    try:
        return None if os.path.islink(path) else max(0, int(now - os.path.getmtime(path)))
    except OSError:
        return None


def _json(path):
    try:
        if os.path.islink(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def build(data_dir, now=None):
    now = time.time() if now is None else now
    d = os.path.realpath(data_dir)
    out = {"state": "OK", "paper_only": True, "version": VERSION}
    try:
        import v2_candles as K
        import v2_runner as RN
        rs = RN.status(d)
        out["candles"] = {"switch": "ON" if K.is_enabled(d) else "OFF", "owner_off": K.owner_off(d), "runner_running": rs.get("running"), "runner_beat_age_s": rs.get("beat_age_s")}
    except Exception as e:
        out["candles"] = {"switch": "UNKNOWN", "error": "%s: %s" % (type(e).__name__, str(e)[:80])}
    try:
        import v2_candles_ws as KW
        w = KW.read_status(d)
        if w:
            out["candles"]["ws"] = {k: w.get(k) for k in ("connected", "coins", "saved", "skipped_no_prev", "reconnects", "last_error", "note", "last_msg_ts", "written_ts")}
            out["candles"]["ws"]["status_age_s"] = _age(os.path.join(d, KW.STATUS_FILE), now)
    except Exception:
        pass
    try:
        import api.sniper_hist as SH
        st, body = SH.hist_answer(d, now)
        keep = ("state", "by_source", "tf_unsupported", "slots_missing", "requests_needed", "lines", "last_run", "turns", "age_sec")
        out["history"] = {k: body.get(k) for k in keep if k in body} if st == 200 else {"state": "off"}
    except Exception as e:
        out["history"] = {"state": "error", "lines": ["%s: %s" % (type(e).__name__, str(e)[:80])]}
    ap = _json(os.path.join(d, "v2_sniper_autopilot.json"))
    out["learning"] = {"state": ap.get("state"), "n_train": ap.get("n_train"), "n_test": ap.get("n_test"), "days": ap.get("days"),
                       "reasons": [str(x)[:140] for x in (ap.get("reasons") or [])[:3]], "age_s": _age(os.path.join(d, "v2_sniper_autopilot.json"), now)} if ap else {"state": None}
    out["jobs"] = [{"key": k, "label": lab, "age_s": _age(os.path.join(d, fn), now)} for k, lab, fn in JOBS]
    return out


def health_answer(data_dir, now=None):
    now = time.time() if now is None else now
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if _cache["body"] is not None and now - _cache["ts"] < CACHE_SEC:
        return 200, _cache["body"]
    try:
        body = build(data_dir, now)
    except Exception as e:
        body = {"state": "error", "text": "Data health could not be built: %s." % str(e)[:80], "paper_only": True}
    _cache["ts"], _cache["body"] = now, body
    return 200, body


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_data_health():
        st, body = await asyncio.to_thread(health_answer, data_dir)
        return JSONResponse(body, status_code=st)

    return r
