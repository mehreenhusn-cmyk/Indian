"""api/route_timing.py - R21: how long does every API route take? (read-only, memory only, no file, no network)
The server middleware (api_server.py, the one that already feeds recovered_bot/load_report.py) calls note(path, ms) after every /api/ answer.
This file keeps the last SAMPLES answers per route (path with ids made generic) for the last WINDOW_SEC seconds and says which routes are slow:
  slow(now)  -> list of {route, n, avg_ms, max_ms, last_ms} for routes with at least MIN_CALLS calls where avg > SLOW_AVG_MS or max > SLOW_MAX_MS, worst first.
  summary(now) -> {routes_timed, calls, since} for the 'nothing timed yet' line.
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
