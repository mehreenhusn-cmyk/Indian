"""api/route_timing.py - R21: how long does every API route take? (read-only, memory only, no file, no network)
The server middleware (api_server.py, the one that already feeds recovered_bot/load_report.py) calls note(path, ms) after every /api/ answer.
This file keeps the last SAMPLES answers per route (path with ids made generic) for the last WINDOW_SEC seconds and says which routes are slow:
  slow(now)  -> list of {route, n, avg_ms, max_ms, last_ms} for routes with at least MIN_CALLS calls where avg > SLOW_AVG_MS or max > SLOW_MAX_MS, worst first.
  summary(now) -> {routes_timed, calls, since} for the 'nothing timed yet' line.
  Part 2: begin/end watch every call while it RUNS, so a call that never ends (the app's "TimeoutException after 20 s") shows as WAITING; waiting(now) lists them;
  top(now) ranks routes by busy seconds per minute (calls per minute x average time) = who keeps the phone busy; GET /api/v2/slow_calls (make_router) gives the app both.
Never raises. Never stores a query string or a token. Max MAX_ROUTES routes are kept (the oldest idle one is dropped)."""
import re
import threading
import time
from collections import deque

SAMPLES, WINDOW_SEC, MIN_CALLS, MAX_ROUTES = 40, 1800, 3, 120
SLOW_AVG_MS, SLOW_MAX_MS = 1500.0, 6000.0
_ID = re.compile(r"/[0-9a-fA-F\-]{8,}|/\d+")
_lock = threading.Lock()
_routes = {}
_started = time.time()


def _name(path):
    return _ID.sub("/{id}", str(path).split("?", 1)[0])[:70]


def note(path, ms, now=None):
    """Remember one answer time. Never raises."""
    try:
        now = time.time() if now is None else now
        r = _name(path)
        with _lock:
            q = _routes.get(r)
            if q is None:
                if len(_routes) >= MAX_ROUTES:
                    idle = min(_routes, key=lambda k: _routes[k][-1][0] if _routes[k] else 0)
                    _routes.pop(idle, None)
                q = _routes[r] = deque(maxlen=SAMPLES)
            q.append((now, float(ms)))
    except Exception:
        pass


def _recent(now):
    out = {}
    with _lock:
        for r, q in _routes.items():
            xs = [ms for ts, ms in q if now - ts <= WINDOW_SEC]
            if xs:
                out[r] = xs
    return out


def slow(now=None):
    """Slow routes of the last WINDOW_SEC seconds, worst average first."""
    now = time.time() if now is None else now
    res = []
    try:
        for r, xs in _recent(now).items():
            if len(xs) < MIN_CALLS:
                continue
            avg, mx = sum(xs) / len(xs), max(xs)
            if avg > SLOW_AVG_MS or mx > SLOW_MAX_MS:
                res.append({"route": r, "n": len(xs), "avg_ms": int(avg), "max_ms": int(mx), "last_ms": int(xs[-1])})
        res.sort(key=lambda x: x["avg_ms"], reverse=True)
    except Exception:
        return []
    return res


def summary(now=None):
    now = time.time() if now is None else now
    try:
        rec = _recent(now)
        return {"routes_timed": len(rec), "calls": sum(len(v) for v in rec.values()), "since": int(_started)}
    except Exception:
        return {"routes_timed": 0, "calls": 0, "since": int(_started)}


# ---- Part 2: calls still running now, and who keeps the backend busy ----
TOP_WINDOW_SEC, WAIT_MIN_SEC, WAIT_DROP_SEC = 300, 3.0, 600
SELF = "/api/v2/slow_calls"
_inflight = {}
_seq = 0


def begin(path, now=None):
    """A call started. Returns a token for end(). Never raises (0 = not tracked)."""
    global _seq
    try:
        r = _name(path)
        if r == SELF:
            return 0
        with _lock:
            _seq += 1
            _inflight[_seq] = (r, time.time() if now is None else now)
            return _seq
    except Exception:
        return 0


def end(token):
    """The call finished (or failed). Never raises."""
    try:
        if token:
            with _lock:
                _inflight.pop(token, None)
    except Exception:
        pass


def waiting(now=None, min_sec=WAIT_MIN_SEC):
    """Calls still unanswered after min_sec seconds, longest first: [{route, waiting_sec}]."""
    now = time.time() if now is None else now
    out = []
    try:
        with _lock:
            for k in [k for k, (_, t0) in _inflight.items() if now - t0 > WAIT_DROP_SEC]:
                _inflight.pop(k, None)               # a call that never reported back is forgotten after 10 minutes
            items = list(_inflight.values())
        for r, t0 in items:
            if now - t0 >= min_sec:
                out.append({"route": r, "waiting_sec": int(now - t0)})
        out.sort(key=lambda x: x["waiting_sec"], reverse=True)
    except Exception:
        return []
    return out


def top(now=None, limit=5):
    """Routes ranked by busy seconds per minute over the last TOP_WINDOW_SEC: [{route, per_min, avg_ms, busy_sec_min}]."""
    now = time.time() if now is None else now
    res = []
    try:
        with _lock:
            snap = {r: [(ts, ms) for ts, ms in q if now - ts <= TOP_WINDOW_SEC] for r, q in _routes.items()}
        for r, xs in snap.items():
            if len(xs) < 2 or r == SELF:
                continue
            span = max(10.0, now - xs[0][0])
            per_min = len(xs) * 60.0 / span
            avg = sum(ms for _, ms in xs) / len(xs)
            res.append({"route": r, "per_min": round(per_min, 1), "avg_ms": int(avg), "busy_sec_min": round(per_min * avg / 1000.0, 1)})
        res.sort(key=lambda x: x["busy_sec_min"], reverse=True)
    except Exception:
        return []
    return res[:limit]


def answer(now=None):
    """The whole slow-calls answer for the app. Never raises."""
    now = time.time() if now is None else now
    try:
        w, sl, tp, sm = waiting(now), slow(now), top(now), summary(now)
        if w:
            head = "%d call(s) waiting: %s for %d s" % (len(w), w[0]["route"], w[0]["waiting_sec"])
        elif sl:
            head = "Slow: %s, average %d ms" % (sl[0]["route"], sl[0]["avg_ms"])
        elif sm["calls"] == 0:
            head = "Nothing timed yet since the backend started."
        else:
            head = "No slow calls."
        return {"state": "OK", "headline": head, "waiting": w[:5], "slow": sl[:5], "top": tp, "summary": sm, "read_only": True}
    except Exception as e:
        return {"state": "error", "headline": "Could not read the timing (%s)" % type(e).__name__, "waiting": [], "slow": [], "top": [], "read_only": True}


def make_router(require_api_token, data_dir):
    """1 GET route behind the app's token check (mounted by api/sniper_mount.py)."""
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(SELF, dependencies=[Depends(require_api_token)])
    async def v2_slow_calls():
        return JSONResponse(answer())

    return r
