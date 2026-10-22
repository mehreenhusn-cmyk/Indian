"""FastAPI router for Ping: only READS the snapshot written by ping_worker.

Never computes inside a request. If snapshot is old or missing -> {"stale": true}.
"""
import time
from fastapi import APIRouter

from . import ping_store

# ---- constants (starting guesses) ----
CACHE_TTL_SEC = 1.0
STALE_AFTER_SEC = 10.0

_cache = {"ts": 0.0, "data": None}


def _load_snapshot():
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < CACHE_TTL_SEC:
        return _cache["data"]
    data = ping_store.read_state()
    _cache["ts"] = now
    _cache["data"] = data if isinstance(data, dict) else {}
    return _cache["data"]


def _is_stale(snap):
    if not snap or not isinstance(snap, dict):
        return True
    ts = snap.get("ts")
    if ts is None:
        return True
    try:
        age = time.time() - float(ts)
    except (TypeError, ValueError):
        return True
    return age > STALE_AFTER_SEC


def make_router():
    r = APIRouter(prefix="/api/ping", tags=["ping"])

    @r.get("/status")
    def status():
        snap = _load_snapshot()
        if _is_stale(snap):
            return {
                "stale": True,
                "alive": False,
                "build_tag": None,
                "ws_state": None,
                "last_msg_age_sec": None,
                "candidate_count": 0,
            }
        h = snap.get("health") or {}
        return {
            "stale": False,
            "alive": bool(h.get("alive")),
            "build_tag": h.get("build_tag"),
            "ws_state": h.get("ws_state"),
            "last_msg_age_sec": h.get("last_msg_age_sec"),
            "candidate_count": h.get("candidate_count", 0),
            "uptime_sec": h.get("uptime_sec"),
        }

    @r.get("/live")
    def live():
        snap = _load_snapshot()
        if _is_stale(snap):
            return {"stale": True, "rows": [], "ts": None}
        rows = snap.get("rows") or []
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append({
                "symbol": row.get("symbol"),
                "side": row.get("side"),
                "color": row.get("color"),
                "pings_5m": row.get("pings_5m", 0),
                "pings_15m": row.get("pings_15m", 0),
                "pings_60m": row.get("pings_60m", 0),
                "pings_hour": row.get("pings_hour", 0),
                "net_vol_usdt": row.get("net_vol_usdt"),
                "net_vol_pct": row.get("net_vol_pct"),
                "recent_total": row.get("recent_total"),
                "recent_vol_pct": row.get("recent_vol_pct"),
                "recent_net": row.get("recent_net"),
                "price": row.get("price"),
                "move_since_first_ping_pct": row.get("move_since_first_ping_pct"),
                "absorbed": row.get("absorbed", False),
                "first_ping_ts": row.get("first_ping_ts"),
                "last_ping_ts": row.get("last_ping_ts"),
                "in_watchlist": row.get("in_watchlist", False),
            })
        return {"stale": False, "rows": out, "ts": snap.get("ts")}

    @r.get("/bot")
    def bot():
        snap = _load_snapshot()
        if _is_stale(snap):
            return {"stale": True, "open": [], "closed_recent": [], "sentence": "Worker offline."}
        b = snap.get("bot") or {}
        return {"stale": False, **b}

    @r.get("/score")
    def score():
        snap = _load_snapshot()
        if _is_stale(snap):
            return {"stale": True, "sentence": "Worker offline.", "small_sample": True}
        s = snap.get("score") or {}
        return {"stale": False, **s}

    @r.get("/lead")
    def lead():
        snap = _load_snapshot()
        if _is_stale(snap):
            return {"stale": True, "sentence": "Worker offline.", "small_sample": True}
        L = snap.get("lead") or {}
        return {"stale": False, **L}

    return r
