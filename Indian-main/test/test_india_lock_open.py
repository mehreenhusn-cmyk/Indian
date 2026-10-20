"""Market OPEN with a slow broker (1 s per REST call): API calls must not wait, and no broker fetch may run while the
runtime lock is held. Run: python3 test/test_india_lock_open.py   (old code: ~2000 ms wait and fetches under the lock)"""
import importlib.util, sys, os, tempfile, time, threading, random
from datetime import datetime
HERE = os.path.dirname(os.path.abspath(__file__)); root = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(root, "backend")); sys.path.insert(0, os.path.join(root, "backend", "recovered_bot"))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "backend/recovered_bot/india_runtime.py")
spec = importlib.util.spec_from_file_location("recovered_bot.india_runtime", path)
m = importlib.util.module_from_spec(spec); sys.modules["recovered_bot.india_runtime"] = m; spec.loader.exec_module(m)
from recovered_bot.india_data import synthetic_candles


def run():
    random.seed(1)
    rt = m.IndiaRuntime(tempfile.mkdtemp())
    CS = synthetic_candles(24000, days=3, tf_min=5, seed=7)
    under_lock, fetches = [], []

    class Fake:
        is_live = True
        def __init__(s): s.c = {}
        def now(s): return datetime(2026, 10, 15, 11, 0)
        def ensure_session(s): time.sleep(0.05)
        def set_tf(s, tf): pass
        def _cached(s, key, ttl, fn):
            e = s.c.get(key)
            if e and time.time() - e[0] < ttl: return e[1]
            under_lock.append(rt.lock._is_owned()); fetches.append(key)
            time.sleep(1.0)
            v = fn(); s.c[key] = (time.time(), v); return v
        def get_candles(s, u, tf, history=300, **k): return s._cached(("c", u, tf, history), 3.0, lambda: CS[:])
        def get_spot(s, u): return s._cached(("s", u), 1.0, lambda: CS[-1]["c"])
        def get_last_candle(s, u): return s._cached(("lc", u), 0.3, lambda: CS[-1])
        def get_option_ltp(s, c): return 100.0

    fk = Fake(); rt.provider = fk; rt.runner.p = fk; rt.engine.p = fk
    m.india_chain.market_status = lambda now: "OPEN"
    rt.settings["poll_sec"] = 2.0; rt.running = True
    if hasattr(rt, "_stop_evt"): rt._stop_evt.clear()
    th = threading.Thread(target=rt._loop, daemon=True); th.start(); time.sleep(0.3)
    worst, t_end = 0.0, time.time() + 8
    while time.time() < t_end:
        t0 = time.time(); rt.doctor(); rt.trades(); worst = max(worst, (time.time() - t0) * 1000); time.sleep(0.15)
    rt.stop(); th.join(5)
    return len(fetches), sum(under_lock), worst


def test_open_market_no_fetch_under_lock_and_fast_api():
    n, locked, worst = run()
    print("fetches", n, "| under lock", locked, "| worst API wait %.0f ms" % worst)
    assert n > 0 and locked == 0 and worst < 500


if __name__ == "__main__":
    test_open_market_no_fetch_under_lock_and_fast_api(); print("PASS")
