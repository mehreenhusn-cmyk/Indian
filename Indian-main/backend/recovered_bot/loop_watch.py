"""loop_watch.py - finds out WHY the server froze (the real reason behind "WS disconnect").

The price stream, every REST answer and every WebSocket share ONE event loop. If anything blocks that loop
for a few seconds, the app hears nothing, thinks the connection died and reconnects (which piles even more
work on the stuck server). This module does not change trading or data; it only WATCHES:

  * a tiny task on the loop writes a heartbeat every 100 ms and measures how late it was;
  * a separate plain thread checks the heartbeat; if it is older than STALL_S it records the stack the
    loop is stuck in right now (file:line of the blocking call) and what the other threads are doing.

Result: print("[STALL] ...") in ~/owl_backend.log and a small block in /api/system (System Load card).
Read-only, never raises, cost ~0.
"""
import asyncio
import sys
import threading
import time
import traceback
from collections import deque

STALL_S = 1.5            # loop silent for this long = a stall worth recording
_DUMP_EVERY_S = 15.0     # at most one stack dump per this many seconds (log stays readable)

_beat = 0.0              # perf_counter() of the last heartbeat
_loop_tid = None
_last_lag_ms = 0.0
_lags = deque(maxlen=600)      # (wall ts, lag ms) of the last ~60 s
_stalls = deque(maxlen=30)     # finished stalls: {"ts", "ms", "where"}
_pending_where = None
_last_dump = 0.0
_started = False
_cpu_last = [0.0]          # process CPU seconds at the last heartbeat


def _short(frame, depth=4):
    try:
        st = traceback.extract_stack(frame)[-depth:]
        return " <- ".join(f"{f.filename.split('/')[-1]}:{f.lineno} {f.name}" for f in reversed(st))
    except Exception:
        return "?"


async def _beat_task():
    global _beat, _loop_tid, _last_lag_ms, _pending_where
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
        cpu_now = time.process_time()
        cpu_used = cpu_now - _cpu_last[0]
        _cpu_last[0] = cpu_now
        if lag >= STALL_S * 1000.0:
            # Did THIS process use CPU while the loop was silent? ~0 = the phone / Android paused the app (battery saver,
            # doze, Termux in the background); high = some thread of ours hogged the CPU / GIL.
            wall = max(0.001, lag / 1000.0 + 0.1)
            cause = ("phone paused the app (it used almost no CPU)" if cpu_used / wall < 0.10
                     else "our own code was busy (CPU used %.0f%%)" % (100.0 * cpu_used / wall))
            label = "PHONE PAUSED" if cpu_used / wall < 0.10 else "OUR CODE BUSY"
            where = f"[{label}] " + (_pending_where or "(not captured)")   # label first: reports cut long lines at the end
            _stalls.append({"ts": time.time(), "ms": int(lag), "where": where})
            print(f"[STALL] event loop was frozen {lag / 1000.0:.1f}s - {cause}")
            _pending_where = None


def _watch():
    global _last_dump, _pending_where
    while True:
        time.sleep(0.5)
        try:
            if not _beat:
                continue
            age = time.perf_counter() - _beat
            if age < STALL_S:
                continue
            frames = sys._current_frames()
            where = _short(frames.get(_loop_tid)) if _loop_tid in frames else "?"
            names = {t.ident: t.name for t in threading.enumerate()}
            others, busy = [], []
            for tid, fr in frames.items():
                if tid in (_loop_tid, threading.get_ident()):
                    continue
                one = f"{names.get(tid, tid)}@{_short(fr, 1)}"
                others.append(one)
                if not any(w in one for w in ("wait", "sleep", "select", "accept", "recv", "get ")):
                    busy.append(one)        # a thread that is NOT just waiting = the likely culprit
            # captured on EVERY check (even when the print below is rate limited), so no stall stays "(not captured)"
            _pending_where = where + (" | busy threads: " + " ; ".join(busy[:3]) if busy else " | no busy thread")
            if time.time() - _last_dump < _DUMP_EVERY_S:
                continue
            _last_dump = time.time()
            print(f"[STALL] loop blocked {age:.1f}s in: {where}")
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
        return {
            "loop_lag_ms": int(_last_lag_ms),
            "loop_lag_max_60s": int(max(recent)) if recent else 0,
            "stalls_10min": sum(1 for s in list(_stalls) if now - s["ts"] < 600),
            "last_stall": ({"ago_s": int(now - last["ts"]), "ms": last["ms"], "where": last["where"]}
                           if last else None),
        }
    except Exception:
        return {}
