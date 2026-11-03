"""api/sniper_selflog.py - OwlSniper SELF LOG route (Part 44 / FILE 53): ONE route GET /api/v2/sniper_selflog?limit=60
It gives the self log of owl_sniper_selflog.py: plain lines of what Sniper LEARNED, which MISTAKES it made, what CHANGED (newest first), with counts.
It is a GET but it does ONE small thing besides reading: it writes the self log's OWN file v2_sniper_selflog.json (atomic, temp + replace) so a lesson is listed once. No order, no setting of the Sniper, no network.
Light on the phone: the slow reports (edge decay + old-finding re-test) are read at most once per CACHE_SEC (10 minutes), ONE build at a time (a second call gets the old answer, or state "busy" when there is none). A failed build keeps the old answer.
limit = 1 to 200 lines (default 60). Same switch as the other V2 routes: 404 until the file v2_api_enabled exists in the data folder, and off for good while the file v2_sniper_off exists.
Answer: state (OK / EMPTY / broken / busy / error / off), text, lines, entries [{ts, kind LEARNED / MISTAKE / CHANGED, text, src}], counts, n_total, last_look, unsaved, answer_age_sec, paper_only (always true).
NOT MOUNTED yet. To mount (owner says "mount ok"), add 4 lines to api_server.py after the sniper paper block, same try / except style:
    try:
        from api.sniper_selflog import make_router as _sniper_selflog_router
        app.include_router(_sniper_selflog_router(require_api_token, DATA_DIR))
    except Exception as _e:
        print(f"[startup] sniper selflog route skipped: {_e}")"""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_selflog as SL
from api.sniper import api_enabled

VERSION = "api/sniper_selflog 1 (Part 44)"
PATH = "/api/v2/sniper_selflog"
CACHE_SEC = 600
_cache = {"ts": 0.0, "body": None}
_build_lock, _mem_lock = threading.Lock(), threading.Lock()


def _plain(state, text):
    return {"state": state, "text": text, "lines": [text], "entries": [], "counts": {}, "paper_only": True, "report_only": True}


def selflog_answer(data_dir, limit=60, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(data_dir), F.OFF_FILE)):
        return 200, _plain("off", "The Sniper is switched off (file v2_sniper_off).")
    try:
        limit = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        return 400, _plain("error", "The limit must be a number from 1 to 200.")
    with _mem_lock:
        body, ts = _cache["body"], _cache["ts"]
    if body is None or now - ts >= CACHE_SEC:
        if _build_lock.acquire(blocking=False):
            try:
                new = SL.build(data_dir, now=now)
                if new.get("state") in ("OK", "EMPTY", "broken"):      # a failed build keeps the old answer
                    with _mem_lock:
                        _cache["ts"], _cache["body"] = now, new
                    body, ts = new, now
                elif body is None:
                    return 200, dict(new, route_version=VERSION)
            finally:
                _build_lock.release()
        elif body is None:
            return 200, _plain("busy", "The self log is reading the saved reports. Open this page again in a minute.")
    out = dict(body, entries=(body.get("entries") or [])[:limit], answer_age_sec=round(now - ts, 1), route_version=VERSION, paper_only=True)
    return 200, out


def make_router(require_api_token, data_dir):
    """Mounted by api_server.py only after the owner says "mount ok": 1 GET route behind the app's token check."""
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_selflog(limit: int = 60):
        st, body = await asyncio.to_thread(selflog_answer, data_dir, limit)
        return JSONResponse(body, status_code=st)

    return r
