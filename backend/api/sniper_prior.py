"""api/sniper_prior.py - OwlSniper STUDY VERDICTS route (Part 38 / FILE 46): ONE read-only route GET /api/v2/sniper_prior?tf=5m&fresh_days=30
For the Study Lab list "what was tested, what did it find, does Sniper use it": one plain row per finding (FILE 44, owl_sniper_prior_src.py) plus Sniper's own re-test of the usable ones (FILE 45, owl_sniper_prior_use.py).
READ ONLY, PAPER ONLY: it reads the study modules and the saved candles, nothing is written, no order, no network. Same switch as the other V2 routes: 404 until the file v2_api_enabled exists in the data folder, and off for good while the file v2_sniper_off exists.
Light on the phone: the build (all studies + the SD band re-test) is the slow part. It is built once and cached for CACHE_SEC (10 minutes), only ONE build runs at a time (a second call gets the old answer, or state "busy" when there is none). tf = 5m or 15m, fresh_days 0 to 365 (0 = all saved candles, default 30).
Each row = {id, source, kind, what, n, date, age_sec, verdict, line, entry_known, lean} (see FILE 44) + used_by_sniper (YES / TESTING / NO) + why (one short plain reason):
  YES      = Sniper re-tested the finding on its own fresh candles and CONFIRMED it (STEADY). Even then the Risk Box and the gates decide every trade.
  TESTING  = it is a candidate: Sniper is waiting for 30 independent cases (WAITING / NO_DATA) or it holds only SOMETIMES (PARTIAL, not used).
  NO       = REFUTED by Sniper's own data, or not a candidate (exit / management note, not known at entry, nothing to test, no matching Sniper test yet): the reason says which.
Answer: state (OK / busy / error / off), text, lines, rows, counts (per verdict), used_counts (YES / TESTING / NO), sources (which source worked: ok / unavailable / error), cands (the re-tested candidates with status CONFIRMED / PARTIAL / REFUTED / WAITING / NO_DATA), notes (exit / management notes), interval, fresh_days, cache_age_sec, paper_only (always true).
NOT MOUNTED yet. To mount (owner says "mount ok"), add 4 lines to api_server.py after the sniper paper block, same try / except style:
    try:
        from api.sniper_prior import make_router as _sniper_prior_router
        app.include_router(_sniper_prior_router(require_api_token, DATA_DIR))
    except Exception as _e:
        print(f"[startup] sniper prior route skipped: {_e}")"""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F
import owl_sniper_prior_src as PS
import owl_sniper_prior_use as PU
import owl_sniper_tf as TF
from api.sniper import api_enabled

VERSION = "api/sniper_prior 1 (Part 38)"
PATH = "/api/v2/sniper_prior"
CACHE_SEC, MAX_KEYS, MAX_ROWS = 600, 4, 300
_cache = {}
_build_lock, _mem_lock = threading.Lock(), threading.Lock()


def _bad(text, st=400):
    return st, {"state": "error", "text": text, "lines": [text], "paper_only": True}


def annotate(rows, use):
    """Rows (FILE 44) + the re-test (FILE 45) -> rows with used_by_sniper (YES / TESTING / NO) and one short reason. PURE."""
    cands = {c["id"]: c for c in (use.get("cands") or ())}
    skip = {s["id"]: s["reason"] for s in (use.get("skipped") or ())}
    out = []
    for r in rows or ():
        c, d = cands.get(r.get("id")), dict(r)
        if c is None:
            d["used_by_sniper"], d["why"] = "NO", skip.get(r.get("id")) or "not tested by Sniper"
        elif c["status"] == "CONFIRMED":
            d["used_by_sniper"], d["why"] = "YES", "Sniper's own fresh data confirms it (%d independent cases)" % c["n_independent"]
        elif c["status"] == "REFUTED":
            d["used_by_sniper"], d["why"] = "NO", "Sniper's own fresh data does not confirm it (%d independent cases)" % c["n_independent"]
        elif c["status"] == "PARTIAL":
            d["used_by_sniper"], d["why"] = "TESTING", "holds only sometimes on Sniper's data, not proven"
        else:
            d["used_by_sniper"], d["why"] = "TESTING", "Sniper is collecting cases: %d of %d" % (c["n_independent"], PU.MIN_N) if c["status"] == "WAITING" else "no saved candles to re-test on yet"
        out.append(d)
    return out


def _make(data_dir, tf, fresh, now):
    pr = PS.collect(data_dir, now)
    use = PU.build(data_dir, tf, fresh, rows=pr["rows"], now=now)
    if use.get("state") == "error":
        raise RuntimeError(use.get("text") or "the re-test failed")
    rows = annotate(pr["rows"], use)[:MAX_ROWS]
    used = {k: sum(1 for r in rows if r["used_by_sniper"] == k) for k in ("YES", "TESTING", "NO")}
    lines = ["%d findings read from %d sources. Verdicts: %s." % (len(pr["rows"]), sum(1 for i in pr["sources"].values() if i["state"] == "ok"), ", ".join("%s %d" % (k, v) for k, v in pr["counts"].items() if v))]
    lines.append("Sniper uses %d, is testing %d, does not use %d." % (used["YES"], used["TESTING"], used["NO"]))
    lines += use.get("lines") or []
    return {"state": "OK", "text": lines[1], "lines": lines, "rows": rows, "counts": pr["counts"], "used_counts": used, "sources": pr["sources"], "cands": use.get("cands") or [], "notes": use.get("notes") or [],
            "interval": tf, "fresh_days": fresh, "paper_only": True, "route_version": VERSION, "made": pr["made"]}


def prior_answer(data_dir, tf="5m", fresh_days=PU.FRESH_DAYS, now=None, make=None):
    """-> (http status, body). Never raises. `make` lets a caller give the builder (default: the real studies)."""
    now = time.time() if now is None else now
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(data_dir), F.OFF_FILE)):
        t = "The Sniper is switched off (file v2_sniper_off)."
        return 200, {"state": "off", "text": t, "lines": [t], "paper_only": True}
    if tf not in TF.SUPPORTED:
        return _bad("The interval must be one of: %s." % ", ".join(TF.SUPPORTED))
    try:
        fresh = int(fresh_days)
    except (TypeError, ValueError):
        return _bad("fresh_days must be a whole number (0 = all saved candles).")
    if not 0 <= fresh <= 365:
        return _bad("fresh_days must be 0 to 365.")
    key = (tf, fresh)
    with _mem_lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_SEC:
        return 200, dict(hit[1], cache_age_sec=round(now - hit[0], 1))
    if not _build_lock.acquire(blocking=False):
        if hit:
            return 200, dict(hit[1], cache_age_sec=round(now - hit[0], 1), refreshing=True)
        t = "The study list is being built. Open this page again in a minute."
        return 200, {"state": "busy", "text": t, "lines": [t], "paper_only": True}
    try:
        try:
            body = (make or _make)(data_dir, tf, fresh, now)
        except Exception as e:                                  # one broken study must never stop the backend; an old answer is better than none
            if hit:
                return 200, dict(hit[1], cache_age_sec=round(now - hit[0], 1), refreshing=False, stale=True)
            t = "The study list could not be built: %s." % str(e)[:80]
            return 200, {"state": "error", "text": t, "lines": [t], "paper_only": True}
        with _mem_lock:
            if len(_cache) >= MAX_KEYS:
                _cache.clear()
            _cache[key] = (now, body)
        return 200, dict(body, cache_age_sec=0.0)
    finally:
        _build_lock.release()


def make_router(require_api_token, data_dir):
    """Mounted by api_server.py only after the owner says "mount ok": 1 GET route behind the app's token check."""
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_prior(tf: str = "5m", fresh_days: int = PU.FRESH_DAYS):
        st, body = await asyncio.to_thread(prior_answer, data_dir, tf, fresh_days)
        return JSONResponse(body, status_code=st)

    return r
