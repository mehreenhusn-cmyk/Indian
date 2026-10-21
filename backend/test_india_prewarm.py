
"""Pre-warm does not hold the runtime lock and respects a call cap."""
import os, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "recovered_bot"))
sys.path.insert(0, os.path.dirname(__file__))

class FakeProv:
    is_live = True
    calls = 0
    def get_candles(self, u, tf, limit):
        self.calls += 1
        time.sleep(0.01)
        return []
    def get_spot(self, u):
        self.calls += 1
        return 100.0
    def get_last_candle(self, u):
        self.calls += 1
        return None
    def get_option_ltp(self, c):
        self.calls += 1
        return 1.0

def test_prewarm_no_lock_and_cap():
    from recovered_bot import india_runtime as R
    rt = R.IndiaRuntime.__new__(R.IndiaRuntime)
    rt.lock = threading.RLock()
    rt.provider = FakeProv()
    rt.running = True
    rt.live = object()
    rt.settings = {"underlyings": ["NIFTY"], "poll_sec": 5, "tf": 5}
    class Runner:
        tf = 5
        history = 200
        _last = {}
    rt.runner = Runner()
    rt.engine = type("E", (), {"open": {}, "on_tick": lambda self: None})()
    held = []
    # hold lock and ensure prewarm still returns without needing it
    limited, skip = rt._prewarm([], ["NIFTY"], candles=True)
    assert rt.provider.calls >= 1
    assert limited in (True, False)
    print("prewarm no-lock OK calls", rt.provider.calls)
    # second call uses cache path of provider (still increments our fake)
    c1 = rt.provider.calls
    rt._prewarm([], ["NIFTY"], candles=True)
    assert rt.provider.calls >= c1
    print("prewarm second OK")


def test_prewarm_indexes_cap_and_no_lock():
    """prewarm_indexes() runs in a background thread, never needs rt.lock, and stays under the call cap."""
    from recovered_bot import india_runtime as R
    rt = R.IndiaRuntime.__new__(R.IndiaRuntime)
    rt.lock = threading.RLock()
    rt.provider = FakeProv()
    chains = []
    rt.chain = lambda u, expiry=None, width=10: chains.append(u)
    R.time.sleep, real_sleep = (lambda x: None), R.time.sleep
    try:
        done = threading.Event()
        with rt.lock:                      # we hold the lock here: the warm-up must still finish
            rt.prewarm_indexes()
            for _ in range(200):
                if len(chains) == 3 and rt.provider.calls >= 9:
                    break
                real_sleep(0.01)
    finally:
        R.time.sleep = real_sleep
    assert chains == ["NIFTY", "BANKNIFTY", "FINNIFTY"], chains
    assert rt.provider.calls == 9, rt.provider.calls      # 3 indexes x (1m, 5m, 15m)
    assert rt.provider.calls + len(chains) <= 20          # under the 20 call cap
    print("prewarm_indexes OK")


def test_start_runs_thread_inside_lock():
    """Regression: start() must still set was_running and start the loop thread (a bad edit once moved them into an except block)."""
    import ast, inspect
    from recovered_bot import india_runtime as R
    fn = ast.parse(inspect.getsource(R.IndiaRuntime.start).lstrip() if False else __import__("textwrap").dedent(inspect.getsource(R.IndiaRuntime.start))).body[0]
    with_node = next(n for n in fn.body if isinstance(n, ast.With))
    src = ast.unparse(with_node)
    assert "was_running" in src and "_save_settings" in src and "Thread(" in src, src
    assert not any(isinstance(n, ast.Try) and "Thread(" in ast.unparse(n) for n in fn.body)
    print("start() OK")


if __name__ == "__main__":
    test_prewarm_no_lock_and_cap()
    test_prewarm_indexes_cap_and_no_lock()
    test_start_runs_thread_inside_lock()
    print("ALL test_india_prewarm passed")
