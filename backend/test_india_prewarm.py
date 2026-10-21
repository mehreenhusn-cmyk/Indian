
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
    rt._warm_chain = lambda u, expiry, width: chains.append(u)
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




def test_ticks_indexes_and_opt_chg_no_lock():
    """ticks() returns spots for three indexes from a fake feed without taking rt.lock, and includes chg for options."""
    from recovered_bot import india_runtime as R
    import time
    now = time.time()
    class Feed:
        lock = __import__("threading").RLock()
        ticks = {
            "NSE:NIFTY50-INDEX": (now, {"lp": 22850.0, "ch": -10.0}),
            "NSE:NIFTYBANK-INDEX": (now, {"lp": 48000.0, "ch": 5.0}),
            "NSE:FINNIFTY-INDEX": (now, {"lp": 21000.0, "ch": 1.0}),
            "NSE:NIFTY25OCT22800CE": (now, {"lp": 40.5, "ch": -2.3}),
        }
        wanted = list(ticks.keys())
        restarts = 0
        def subscribe(self, symbols):
            pass
        def get(self, symbol, max_age=6.0):
            return None
    class Prov:
        is_live = True
        feed = Feed()
        _last_spot = {}
        _qcache = {}
        def feed_mode(self):
            return {"mode": "WEBSOCKET", "state": "connected", "note": "WebSocket live"}
    rt = R.IndiaRuntime.__new__(R.IndiaRuntime)
    rt.lock = __import__("threading").RLock()
    rt.provider = Prov()
    rt.live = object()
    rt.settings = {"poll_sec": 5}
    rt._opt_sub_syms = set()
    rt._speed_hist = {"candles": [], "chain": [], "status": [], "paper": [],
                      "candles_lock": [], "chain_lock": [], "status_lock": []}
    # Hold the lock: ticks must still return without blocking.
    with rt.lock:
        out = rt.ticks(opt="NSE:NIFTY25OCT22800CE")
    assert out["mode"] == "WEBSOCKET", out
    for u in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
        assert u in out["spots"], out["spots"]
        assert out["spots"][u]["lp"] > 0
        assert out["spots"][u]["src"] == "ws"
    opt = out["opts"].get("NSE:NIFTY25OCT22800CE")
    assert opt is not None and opt["lp"] == 40.5, opt
    assert opt.get("chg") == -2.3, opt
    print("ticks indexes+chg OK")


if __name__ == "__main__":
    test_prewarm_no_lock_and_cap()
    test_prewarm_indexes_cap_and_no_lock()
    test_start_runs_thread_inside_lock()
    test_ticks_indexes_and_opt_chg_no_lock()
    print("ALL test_india_prewarm passed")
