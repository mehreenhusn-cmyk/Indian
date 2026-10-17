"""Market CLOSED: the loop must never hold the runtime lock while it sleeps, so /doctor etc. answer fast."""
import importlib.util, os, sys, tempfile, threading, time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))
sys.path.insert(0, os.path.join(HERE, "..", "backend", "recovered_bot"))


def load(path=None):
    path = path or os.path.join(HERE, "..", "backend", "recovered_bot", "india_runtime.py")
    spec = importlib.util.spec_from_file_location("recovered_bot.india_runtime", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["recovered_bot.india_runtime"] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeLive:
    is_live = True
    def now(self): return datetime(2026, 10, 17, 12, 0)          # a Saturday
    def ensure_session(self): time.sleep(0.05)
    def set_tf(self, tf): pass


def run(path=None, closed_sleep=30.0):
    m = load(path)
    rt = m.IndiaRuntime(tempfile.mkdtemp())
    rt.provider = FakeLive()
    m.india_chain.market_status = lambda now: "CLOSED"
    rt.settings["poll_sec"] = closed_sleep
    rt.running = True
    if hasattr(rt, "_stop_evt"): rt._stop_evt.clear()
    th = threading.Thread(target=rt._loop, daemon=True); th.start()
    time.sleep(0.3)                                                  # loop is now in its market-closed sleep
    out = {}
    for name, fn in (("doctor", rt.doctor), ("trades", rt.trades)):
        t0 = time.time(); fn(); out[name] = (time.time() - t0) * 1000
    t0 = time.time()
    rt.stop()
    th.join(3)
    out["stop_wakes_loop_ms"] = (time.time() - t0) * 1000
    out["loop_alive_after_stop"] = th.is_alive()
    return out


def test_closed_market_endpoints_fast():
    r = run()
    print(r)
    assert r["doctor"] < 500 and r["trades"] < 500
    assert not r["loop_alive_after_stop"] and r["stop_wakes_loop_ms"] < 1500


if __name__ == "__main__":
    if len(sys.argv) > 1:
        print("OLD CODE:", run(sys.argv[1], closed_sleep=5.0))
    else:
        test_closed_market_endpoints_fast(); print("PASS")
