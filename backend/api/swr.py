"""api/swr.py - the SWR cache core of the API server (moved out of api_server.py, NEXT-6a).

Same code, same names. api_server.py imports every name back, so nothing else changed.
What it does: cached answers + an old answer is served at once while a fresh one is built behind it,
one heavy build at a time, own thread pools. State (dicts / pools) lives here ONCE; api_server shares the same objects.
"""
import asyncio
import sys
import threading
import time

# ---- LAG FIX: heavy AI screens never block the price stream -------------------------------------------------
# Backend and app run on the SAME phone. Opening the AI tab used to fire 6-7 heavy builds at once (insights, book,
# ab_board, advice, desk ...), all pure Python in threads, fighting the price broadcaster for the CPU (tick cost
# 1318 ms of 250 ms, socket dropped). Now: (1) answers are cached and an OLD answer is served at once while a fresh one
# is built behind it, (2) the same build never runs twice at the same time, (3) only ONE heavy build runs at a time,
# (4) screens opened in the last 2 minutes are refreshed in the background, so a tap finds a warm answer.
sys.setswitchinterval(0.001)       # the event loop (price stream) gets the CPU back within 1 ms, not 5 ms
_SWR = {}                          # key -> {"t": built at, "v": value, "hot": last request}
_SWR_TASK = {}                     # key -> running refresh task
_SWR_JOBS = {}                     # key -> (fn, args) so the warmer can refresh it again
_HEAVY_LOCK = threading.Semaphore(1)
_HOT_S = 120.0
# Own thread pools. Heavy builds used to wait for _HEAVY_LOCK INSIDE the shared default pool: 8-10 waiting builds could
# use up every worker thread, and then even a tiny request (Trade Book) found no free thread = "Load ho raha hai..." forever.
# Now: heavy builds queue in a 2-thread pool of their own; cheap screens (Book, replay) have a separate 4-thread pool.
from concurrent.futures import ThreadPoolExecutor as _TPE
_HEAVY_POOL = _TPE(max_workers=2, thread_name_prefix="ai-heavy")
_LIGHT_POOL = _TPE(max_workers=4, thread_name_prefix="ai-light")
_REPLAY_POOL = _TPE(max_workers=2, thread_name_prefix="ai-replay")      # replay has its own threads: never queues behind other screens


def _heavy_call(fn, *a):
    with _HEAVY_LOCK:
        return fn(*a)


# Bot vs AI ("coach") is a light, read-only build. It used to queue behind the heavy jobs (miner, A/B board, prewarm),
# so the screen got an old answer for minutes. It now has its own lane: 4-thread pool, no heavy lock.
_LIGHT_KEYS = {"coach", "daily_report", "doctor"}
_HEAVY_NOW = {"key": None, "since": 0.0}      # who holds the heavy lock right now (shown by /api/ai/health)
_TIMING = {}                                   # key -> [last wait s, last run s, finished at]


def _timed_call(key, t_sub, heavy, fn, *a):
    """Runs fn and records how long it WAITED for a thread / the heavy lock and how long it RAN. Slow ones are printed,
    so the Termux log shows who is blocking whom instead of us guessing."""
    def run():
        t_run = time.time()
        try:
            return fn(*a)
        finally:
            t_end = time.time()
            _TIMING[key] = [round(t_run - t_sub, 2), round(t_end - t_run, 2), t_end]
            if (t_run - t_sub) > 3.0 or (t_end - t_run) > 3.0:
                print(f"[swr] {key} waited {t_run - t_sub:.1f}s, ran {t_end - t_run:.1f}s"
                      f"{' (heavy lock was held by ' + str(_HEAVY_NOW['key']) + ')' if heavy and (t_run - t_sub) > 3.0 else ''}")
    if not heavy:
        return run()
    with _HEAVY_LOCK:
        _HEAVY_NOW.update(key=key, since=time.time())
        try:
            return run()
        finally:
            _HEAVY_NOW.update(key=None, since=0.0)


_SWR_MAX_RUN_S = 60.0           # a refresh running longer than this is treated as stuck and replaced
_SWR_STARTED = {}               # key -> time its current refresh task started


_SWR_SLOW_X = 8.0               # a build that takes T seconds is not repeated more often than every 8 x T seconds
_SWR_SLOW_MAX_S = 600.0


def _eff_ttl(key, ttl):
    """SMOOTH FIX: A/B board took 18-68 s per build but was re-built every 15 s while the AI tab was open, so the phone
    CPU was busy ~100% of the time (event loop stalls, 15 s app time-outs). The slower a build is, the less often it
    repeats. Fast builds (< 1 s) keep their own short ttl, so nothing that is cheap gets slower."""
    run = (_TIMING.get(key) or [0, 0, 0])[1]
    return max(ttl, min(_SWR_SLOW_MAX_S, run * _SWR_SLOW_X)) if run > 2.0 else ttl


async def _swr_refresh(key):
    fn, a = _SWR_JOBS[key]
    heavy = key not in _LIGHT_KEYS and not (isinstance(key, str) and key.startswith("vision_state"))
    # SMOOTH FIX 2: a screen that only needs ~1 s (diary 0.5 s, observer 0.9 s) used to wait 6-32 s behind the 40 s
    # A/B board build. Once a screen has been MEASURED as cheap it uses the light lane and never takes the heavy lock.
    _t = _TIMING.get(key)
    if heavy and _t is not None and _t[1] < 3.0:
        heavy = False
    v = await asyncio.get_running_loop().run_in_executor(_HEAVY_POOL if heavy else _LIGHT_POOL, _timed_call, key, time.time(), heavy, fn, *a)
    ent = _SWR.get(key) or {"hot": time.time()}
    ent.update(t=time.time(), v=v)
    _SWR[key] = ent
    return v


def _swr_start(key):
    task = _SWR_TASK.get(key)
    # A refresh that never finished used to block ALL later refreshes of that screen for ever (the app showed
    # "Data updated 48 min ago" while the engine itself was fine). Light screens get a fresh task after 60 s.
    if task is not None and key in _LIGHT_KEYS and time.time() - _SWR_STARTED.get(key, time.time()) > _SWR_MAX_RUN_S:
        print(f"[swr] {key} refresh was stuck for >{_SWR_MAX_RUN_S:.0f}s - starting a new one")
        _SWR_TASK.pop(key, None)
        task = None
    if task is None:
        task = asyncio.ensure_future(_swr_refresh(key))
        _SWR_TASK[key] = task
        _SWR_STARTED[key] = time.time()

        def _done(t, k=key):
            if _SWR_TASK.get(k) is t:
                _SWR_TASK.pop(k, None)
            if not t.cancelled() and t.exception() is not None:
                print(f"[swr] {k} refresh failed (old answer kept, screen shows 'Data updated N min ago'): {type(t.exception()).__name__}: {str(t.exception())[:160]}")
        task.add_done_callback(_done)
    return task


async def _swr(key, ttl, fn, *a):
    """Cached answer of fn(*a). Fresh -> returned. Stale -> returned at once, a refresh runs behind it.
    Never built yet -> waits for the one shared build."""
    _SWR_JOBS[key] = (fn, a)
    now = time.time()
    ent = _SWR.get(key)
    if ent is not None:
        ent["hot"] = now
        if now - ent["t"] < _eff_ttl(key, ttl):
            return ent["v"]
        _swr_start(key)
        return ent["v"]
    task = _swr_start(key)
    out = await asyncio.shield(task)
    _SWR[key]["hot"] = time.time()
    return out


async def _swr_warmer():
    """Every 10s: refresh the answers somebody opened in the last 2 minutes and are older than 15s (one at a time)."""
    await asyncio.sleep(45)
    while True:
        await asyncio.sleep(10)
        try:
            now = time.time()
            for key, ent in list(_SWR.items()):
                if ent and now - ent["hot"] < _HOT_S and now - ent["t"] > _eff_ttl(key, 15.0) and key not in _SWR_TASK:
                    await asyncio.shield(_swr_start(key))
                    await asyncio.sleep(1.0)
        except Exception as e:
            print(f"[swr] warmer error (ignored): {type(e).__name__}")
