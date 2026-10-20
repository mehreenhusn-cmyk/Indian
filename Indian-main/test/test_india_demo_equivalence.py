"""Same demo data (fixed random seed) -> the NEW loop must close exactly the same trades as the OLD loop.
Usage: python3 test/test_india_demo_equivalence.py <path to the OLD india_runtime.py>   (takes ~1-2 min)"""
import importlib.util, sys, os, tempfile, time, random
HERE = os.path.dirname(os.path.abspath(__file__)); root = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(root, "backend")); sys.path.insert(0, os.path.join(root, "backend", "recovered_bot"))


def run(path):
    for k in [k for k in sys.modules if k == "recovered_bot.india_runtime"]: del sys.modules[k]
    spec = importlib.util.spec_from_file_location("recovered_bot.india_runtime", path)
    m = importlib.util.module_from_spec(spec); sys.modules["recovered_bot.india_runtime"] = m; spec.loader.exec_module(m)
    random.seed(4242)                                  # BEFORE the runtime is built: it draws its demo seed there
    rt = m.IndiaRuntime(tempfile.mkdtemp()); rt.settings["speed_sec"] = 0.001; rt.start()
    t0 = time.time()
    while time.time() - t0 < 150:
        with rt.lock:
            if rt.finished or not rt.running: break
        time.sleep(0.2)
    with rt.lock:
        return [(t.get("underlying"), t.get("action"), round(float(t["pnl"]), 4), t.get("reason")) for t in rt.engine.closed]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("give the path of the OLD india_runtime.py"); sys.exit(0)
    a = run(sys.argv[1]); b = run(os.path.join(root, "backend/recovered_bot/india_runtime.py"))
    print("old", len(a), "new", len(b), "identical", a == b)
    assert a and a == b
    print("PASS")
