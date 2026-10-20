"""Runtime telemetry for the System Load dashboard.

Design rules (so this can never slow the price / PnL path):
  * stdlib only (no psutil - it often fails to build on Termux/Android).
  * every record_*() call is a few arithmetic ops under one tiny lock and
    NEVER raises, so a telemetry bug can't break trading code.
  * CPU / RAM / disk are sampled by ONE background thread every
    SAMPLE_EVERY_SEC and cached. snapshot() only copies cached numbers, so
    the /api/system endpoint costs nothing no matter how often it is hit.
"""
import os
import shutil
import threading
import time
from collections import deque

SAMPLE_EVERY_SEC = 3.0
_PAGE = 4096
try:
    _PAGE = os.sysconf("SC_PAGE_SIZE")
except Exception:
    pass
_NCPU = os.cpu_count() or 1

_lock = threading.Lock()
_started = False
_start_ts = time.time()

# REST calls: (monotonic ts, endpoint). Bounded so it can't grow if nobody reads it.
_rest = deque(maxlen=6000)
_rest_total = 0

# WS broadcaster (api_server): cost of one 250ms tick.
_bc = {"ticks": 0, "ema_ms": 0.0, "max_ms": 0.0, "bytes": 0, "clients": 0,
       "dropped": 0, "build_ms": 0.0}

# Candle poll loop (app.py).
_poll = {"cycles": 0, "last_ms": 0.0, "fetched": 0, "skipped": 0,
         "rest_candle_calls": 0, "ws_candles": 0, "singleflight_hits": 0}

# AI assistant.
_ai = {"busy": 0, "calls": 0, "errors": 0, "last_ts": None, "last_ms": None,
       "avg_ms": 0.0}

# Bump on every backend change so the app (System Load card) can prove which
# Python files are actually running - an old backend shows an old/missing tag.
BUILD_TAG = "2026-10-20-partA"

_cached = {}          # filled by the sampler thread
_prev_cpu = None      # (wall, process_cpu)
_prev_sys = None      # (total_jiffies, idle_jiffies) from /proc/stat


# ---------------------------------------------------------------- recorders
def record_rest(url):
    """Count one outgoing REST request. `url` may be a full URL."""
    global _rest_total
    try:
        rest = str(url).split("?", 1)[0].split("://", 1)[-1]
        ep = "/" + rest.split("/", 1)[1] if "/" in rest else rest
        _rest.append((time.monotonic(), ep))
        _rest_total += 1
    except Exception:
        pass


def record_broadcast(total_ms, nbytes, clients, build_ms=0.0, dropped=0):
    try:
        with _lock:
            _bc["ticks"] += 1
            _bc["ema_ms"] = total_ms if _bc["ticks"] == 1 else _bc["ema_ms"] * 0.9 + total_ms * 0.1
            _bc["build_ms"] = build_ms if _bc["ticks"] == 1 else _bc["build_ms"] * 0.9 + build_ms * 0.1
            if total_ms > _bc["max_ms"]:
                _bc["max_ms"] = total_ms
            _bc["bytes"] = nbytes
            _bc["clients"] = clients
            _bc["dropped"] += dropped
    except Exception:
        pass


def record_poll(duration_ms, fetched, skipped):
    try:
        with _lock:
            _poll["cycles"] += 1
            _poll["last_ms"] = duration_ms
            _poll["fetched"] = fetched
            _poll["skipped"] = skipped
            _poll["rest_candle_calls"] += fetched
    except Exception:
        pass


def count(name, n=1):
    """Bump a named poll counter: 'ws_candles' or 'singleflight_hits'."""
    try:
        with _lock:
            if name in _poll:
                _poll[name] += n
    except Exception:
        pass


def ai_begin():
    try:
        with _lock:
            _ai["busy"] += 1
            _ai["calls"] += 1
    except Exception:
        pass
    return time.monotonic()


def ai_end(t0, ok=True):
    try:
        ms = (time.monotonic() - t0) * 1000.0
        with _lock:
            _ai["busy"] = max(0, _ai["busy"] - 1)
            if not ok:
                _ai["errors"] += 1
            _ai["last_ts"] = time.time()
            _ai["last_ms"] = ms
            n = _ai["calls"]
            _ai["avg_ms"] = ms if n <= 1 else _ai["avg_ms"] * 0.8 + ms * 0.2
    except Exception:
        pass


# ---------------------------------------------------------------- sampling
def _read_rss_bytes():
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * _PAGE
    except Exception:
        try:
            import resource
            r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return int(r) * 1024      # peak, KB on Linux/Android
        except Exception:
            return None


def _read_meminfo():
    try:
        total = avail = None
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    avail = int(line.split()[1]) * 1024
                if total is not None and avail is not None:
                    break
        return total, avail
    except Exception:
        return None, None


def _system_cpu_pct():
    """Whole-device CPU %. Android often blocks /proc/stat -> None, and the
    dashboard then simply shows the backend's own CPU."""
    global _prev_sys
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()[1:]
        vals = [int(x) for x in parts]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals)
        prev, _prev_sys = _prev_sys, (total, idle)
        if not prev or total <= prev[0]:
            return None
        return max(0.0, min(100.0, 100.0 * (1.0 - (idle - prev[1]) / (total - prev[0]))))
    except Exception:
        return None


def _feed_info():
    try:
        from . import market_ws
        return market_ws.feed_info()
    except Exception:
        return {}


def _sample_once():
    global _prev_cpu, _cached
    now = time.monotonic()
    cpu_now = time.process_time()
    proc_pct = None
    if _prev_cpu and now > _prev_cpu[0]:
        raw = 100.0 * (cpu_now - _prev_cpu[1]) / (now - _prev_cpu[0])   # % of ONE core
        proc_pct = max(0.0, min(100.0, raw / _NCPU))
        proc_core = max(0.0, raw)
    else:
        proc_core = None
    _prev_cpu = (now, cpu_now)

    rss = _read_rss_bytes()
    mem_total, mem_avail = _read_meminfo()
    try:
        du = shutil.disk_usage(os.getcwd())
        disk = {"used": du.used, "total": du.total,
                "pct": round(100.0 * du.used / du.total, 1) if du.total else None}
    except Exception:
        disk = {"used": None, "total": None, "pct": None}

    # REST calls in the last 60s, overall + top endpoints.
    cutoff = now - 60.0
    while _rest and _rest[0][0] < cutoff:
        _rest.popleft()
    per_ep = {}
    for _, ep in list(_rest):
        per_ep[ep] = per_ep.get(ep, 0) + 1
    top = sorted(per_ep.items(), key=lambda kv: kv[1], reverse=True)[:4]

    with _lock:
        bc = dict(_bc)
        _bc["max_ms"] = 0.0      # max is per sample window (~3s)
        poll = dict(_poll)
        ai = dict(_ai)

    snap = {
        "uptime_s": int(time.time() - _start_ts),
        "build": BUILD_TAG,
        "cpu": {"backend_pct": None if proc_pct is None else round(proc_pct, 1),
                "backend_core_pct": None if proc_core is None else round(proc_core, 1),
                "system_pct": _system_cpu_pct(), "cores": _NCPU},
        "mem": {"rss": rss, "sys_total": mem_total, "sys_avail": mem_avail,
                "sys_pct": (round(100.0 * (1 - mem_avail / mem_total), 1)
                            if mem_total and mem_avail is not None else None)},
        "disk": disk,
        "rest": {"per_min": len(_rest), "total": _rest_total,
                 "top": [{"ep": k, "n": v} for k, v in top]},
        "broadcast": {"avg_ms": round(bc["ema_ms"], 2), "max_ms": round(bc["max_ms"], 2),
                      "build_ms": round(bc["build_ms"], 2), "bytes": bc["bytes"],
                      "clients": bc["clients"], "ticks": bc["ticks"], "dropped": bc["dropped"]},
        "poll": {"cycle_ms": round(poll["last_ms"], 1), "cycles": poll["cycles"],
                 "fetched": poll["fetched"], "skipped_ws": poll["skipped"],
                 "rest_candle_calls": poll["rest_candle_calls"],
                 "ws_candles": poll["ws_candles"],
                 "singleflight_hits": poll["singleflight_hits"]},
        "ai": {"busy": ai["busy"] > 0, "calls": ai["calls"], "errors": ai["errors"],
               "last_ts": ai["last_ts"], "last_ms": None if ai["last_ms"] is None else round(ai["last_ms"]),
               "avg_ms": round(ai["avg_ms"])},
        "feed": _feed_info(),
        "ts": time.time(),
    }
    # Hint where mobile data may be going (18 GB/month was seen on Termux).
    # REST top + poll rest_candle_calls are the main suspects; WS is usually free-ish.
    try:
        top_eps = [t["ep"] for t in snap["rest"].get("top", [])]
        candle_heavy = any("klines" in e or "candles" in e or "/fapi/" in e for e in top_eps)
        snap["data_hint"] = {
            "rest_calls_last_min": snap["rest"]["per_min"],
            "rest_candle_calls_total": poll["rest_candle_calls"],
            "ws_candles": poll["ws_candles"],
            "likely_heavy": "Binance candle REST" if candle_heavy or poll["rest_candle_calls"] > 200
                            else ("REST top: " + ", ".join(top_eps[:3]) if top_eps else "unknown"),
            "tip": "If Termux data is high, check rest.top + poll.rest_candle_calls; prefer WS over REST.",
        }
    except Exception:
        snap["data_hint"] = {}
    snap["alerts"] = _alerts(snap)
    _cached = snap          # single reference swap: readers never see a half-built dict



def _alerts(s):
    out = []
    cpu = s["cpu"]["system_pct"] if s["cpu"]["system_pct"] is not None else s["cpu"]["backend_pct"]
    if cpu is not None and cpu >= 85:
        out.append({"level": "warn", "msg": f"CPU high ({cpu:.0f}%)"})
    sp = s["mem"]["sys_pct"]
    if sp is not None and sp >= 90:
        out.append({"level": "warn", "msg": f"Device RAM {sp:.0f}% used"})
    dp = s["disk"]["pct"]
    if dp is not None and dp >= 90:
        out.append({"level": "warn", "msg": f"Disk {dp:.0f}% full"})
    age = s["feed"].get("kline_age_s")
    if age is not None and age > 5:
        out.append({"level": "warn", "msg": f"Binance feed quiet for {age:.0f}s"})
    st = s["feed"].get("state")
    if st and st != "LIVE":
        out.append({"level": "warn", "msg": f"Binance WS {st}"})
    # LIVE mode ticks once per second (not every 250 ms), so the limit is 4x higher there.
    try:
        from . import settings_store
        _live = bool(settings_store.get("live_trading_enabled", False))
    except Exception:
        _live = False
    _tick, _limit = (1000, 600) if _live else (250, 150)
    if s["broadcast"]["avg_ms"] > _limit:
        out.append({"level": "warn", "msg": f"Broadcast tick slow ({s['broadcast']['avg_ms']:.0f}ms of {_tick}ms)"})
    rpm = s.get("rest", {}).get("per_min") or 0
    if rpm >= 120:
        out.append({"level": "warn", "msg": f"REST heavy ({rpm}/min) – check data_hint / top endpoints"})
    return out



def _loop():
    while True:
        try:
            _sample_once()
        except Exception:
            pass
        time.sleep(SAMPLE_EVERY_SEC)


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="telemetry-sampler", daemon=True).start()


def snapshot():
    """Cached numbers only - O(1), safe to call from any request."""
    if not _started:
        start()
    return dict(_cached)
