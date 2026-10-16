"""
ai_cpu_meter.py - which background thread eats the phone's CPU?  (answer shown in /api/ai/health -> "cpu")

Every SAMPLE_S seconds it reads /proc/self/task/<tid>/stat (Linux / Android / Termux), turns the CPU ticks of each
thread into "% of one core" over the last interval, and keeps the top few.  If /proc is not readable it just
reports "unavailable".  One tiny thread, a few ms per sample.

READ-ONLY. Never touches a trade. Never raises.
"""
import os
import threading
import time

SAMPLE_S = 15.0
TOP_N = 8
_started = False
_lock = threading.Lock()
_prev = {}                       # tid -> cpu seconds at the last sample
_prev_t = 0.0
_out = {"available": None, "sampled_ago_s": None, "process_cpu_pct": None, "top_threads": []}
_out_t = 0.0

try:
    _TICK = float(os.sysconf("SC_CLK_TCK"))
except Exception:
    _TICK = 100.0


def _read_threads():
    """-> {tid: cpu_seconds}"""
    res = {}
    base = "/proc/self/task"
    for tid in os.listdir(base):
        try:
            with open(f"{base}/{tid}/stat", "r") as f:
                s = f.read()
            # the name sits in (...) and may contain spaces: split after the last ')'
            rest = s[s.rindex(")") + 2:].split()
            res[int(tid)] = (int(rest[11]) + int(rest[12])) / _TICK      # utime + stime
        except Exception:
            continue
    return res


def _names():
    out = {}
    for t in threading.enumerate():
        try:
            if t.native_id:
                out[t.native_id] = t.name
        except Exception:
            pass
    return out


def sample():
    global _prev, _prev_t, _out, _out_t
    try:
        now = time.time()
        cur = _read_threads()
        if not cur:
            raise RuntimeError("no /proc data")
        names = _names()
        if _prev_t and now > _prev_t:
            dt = now - _prev_t
            rows = []
            for tid, cpu in cur.items():
                d = cpu - _prev.get(tid, cpu)
                if d > 0:
                    rows.append((round(100.0 * d / dt, 1), names.get(tid, f"thread-{tid}")))
            rows.sort(reverse=True)
            total = round(sum(r[0] for r in rows), 1)
            with _lock:
                _out = {"available": True, "process_cpu_pct": total,
                        "top_threads": [{"thread": n, "cpu_pct_of_one_core": c} for c, n in rows[:TOP_N]]}
                _out_t = now
        _prev, _prev_t = cur, now
    except Exception as e:
        with _lock:
            _out = {"available": False, "reason": f"{type(e).__name__}: {e}", "top_threads": []}
            _out_t = time.time()


def _loop():
    time.sleep(20)
    while True:
        sample()
        time.sleep(SAMPLE_S)


def start():
    global _started
    if _started:
        return
    _started = True
    try:
        threading.Thread(target=_loop, name="ai-cpu-meter", daemon=True).start()
    except Exception as e:
        print(f"[cpu-meter] could not start: {e}")


def status():
    with _lock:
        o = dict(_out)
        t = _out_t
    o["sampled_ago_s"] = round(time.time() - t) if t else None
    if o.get("available") is None:
        o["note"] = "first sample comes about 35 seconds after the backend starts"
    return o
