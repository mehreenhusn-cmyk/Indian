"""loop_watch.py - finds out WHY the server froze (the real reason behind "WS disconnect").

The price stream, every REST answer and every WebSocket share ONE event loop. If anything blocks that loop
for a few seconds, the app hears nothing, thinks the connection died and reconnects (which piles even more
work on the stuck server). This module does not change trading or data; it only WATCHES:

  * a tiny task on the loop writes a heartbeat every 100 ms and measures how late it was;
  * a separate plain thread checks the heartbeat; if it is older than STALL_S it records the stack the
    loop is stuck in right now (file:line of the blocking call) and what the other threads are doing.

Labels (so the Load Report / AI assistant can tell cause at a glance):
  * OUR CODE BUSY  – watcher got a live stack from the event-loop thread while it was stuck
                     (sync work or a long await holding the loop).
  * PHONE PAUSED?  – no stack captured in time; Android may have frozen Termux (battery / Doze).
                     Set Termux battery to Unrestricted and lock the app in Recents.

Result: print("[STALL] ...") in ~/owl_backend.log and a small block in /api/system (System Load card).
Read-only, never raises, cost ~0.
"""
import asyncio
import sys
import threading
import time
import traceback
from collections import deque

STALL_S = 0.8            # loop silent for this long = a stall worth recording
_DUMP_EVERY_S = 15.0     # at most one stack dump per this many seconds (log stays readable)

_beat = 0.0              # perf_counter() of the last heartbeat
_loop_tid = None
_last_lag_ms = 0.0
_lags = deque(maxlen=600)      # (wall ts, lag ms) of the last ~60 s
_stalls = deque(maxlen=30)     # finished stalls: {"ts", "ms", "where", "cause"}
_pending_where = None
_pending_cause = None
_last_dump = 0.0
_started = False


def _is_idle(fr):
    """True when the loop thread is parked in the selector (epoll/select) = waiting for events, running none of our code."""
    try:
        return fr is not None and fr.f_code.co_name == "select" and fr.f_code.co_filename.endswith("selectors.py")
    except Exception:
        return False


def _short(frame, depth=4):
    try:
        st = traceback.extract_stack(frame)[-depth:]
        return " <- ".join(f"{f.filename.split('/')[-1]}:{f.lineno} {f.name}" for f in reversed(st))
    except Exception:
        return "?"


async def _beat_task():
    global _beat, _loop_tid, _last_lag_ms, _pending_where, _pending_cause
    _loop_tid = threading.get_ident()
    last = time.perf_counter()
    while True:
        await asyncio.sleep(0.1)
        now = time.perf_counter()
        lag = max(0.0, (now - last - 0.1) * 1000.0)
        last = now
        _beat = now
        _last_lag_ms = lag
        _lags.append((time.time(), lag))
        if lag >= STALL_S * 1000.0:
            where = _pending_where or "(not captured)"
            cause = _pending_cause or ("OUR CODE BUSY" if _pending_where else "PHONE PAUSED?")
            _stalls.append({
                "ts": time.time(),
                "ms": int(lag),
                "where": where,
                "cause": cause,
            })
            print(f"[STALL] {cause} event loop was frozen {lag / 1000.0:.1f}s in: {where}")
            _pending_where = None
            _pending_cause = None


def _watch():
    global _last_dump, _pending_where, _pending_cause
    while True:
        time.sleep(0.5)
        try:
            if not _beat:
                continue
            age = time.perf_counter() - _beat
            if age < STALL_S or time.time() - _last_dump < _DUMP_EVERY_S:
                continue
            _last_dump = time.time()
            frames = sys._current_frames()
            if _loop_tid in frames:
                fr = frames.get(_loop_tid)
                where = _short(fr)
                # If the loop is sitting in the selector (epoll/select) it is IDLE, waiting for events: none of our code is running.
                # Then the loop was not woken on time = the phone / OS paused or starved Termux, not our code.
                idle = _is_idle(fr)
                cause = "PHONE PAUSED?" if idle else "OUR CODE BUSY"
            else:
                where = "(not captured)"
                cause = "PHONE PAUSED?"
            _pending_where = where
            _pending_cause = cause
            names = {t.ident: t.name for t in threading.enumerate()}
            others = []
            for tid, fr in frames.items():
                if tid in (_loop_tid, threading.get_ident()):
                    continue
                others.append(f"{names.get(tid, tid)}@{_short(fr, 1)}")
            print(f"[STALL] {cause} loop blocked {age:.1f}s in: {where}")
            print("[STALL] other threads: " + " | ".join(others[:8]))
        except Exception:
            pass


def start():
    """Call once from the server startup (inside the running loop)."""
    global _started
    if _started:
        return
    _started = True
    try:
        asyncio.ensure_future(_beat_task())
        threading.Thread(target=_watch, name="loop-watch", daemon=True).start()
    except Exception:
        pass


def snapshot():
    try:
        now = time.time()
        recent = [l for t, l in list(_lags) if now - t < 60]
        last = _stalls[-1] if _stalls else None
        out = {
            "loop_lag_ms": int(_last_lag_ms),
            "loop_lag_max_60s": int(max(recent)) if recent else 0,
            "stalls_10min": sum(1 for s in list(_stalls) if now - s["ts"] < 600),
            "last_stall": None,
        }
        if last:
            out["last_stall"] = {
                "ago_s": int(now - last["ts"]),
                "ms": last["ms"],
                "where": last.get("where", "?"),
                "cause": last.get("cause", "PHONE PAUSED?" if last.get("where") in (None, "(not captured)") else "OUR CODE BUSY"),
            }
        return out
    except Exception:
        return {}
