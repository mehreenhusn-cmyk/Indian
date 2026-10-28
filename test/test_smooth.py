"""Smoothness test (no network): loop watchdog finds a blocking call, socket cap works, REST handlers are off the loop.
Run: python3 test/test_smooth.py"""
import asyncio, inspect, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import loop_watch as LW

def blocking_culprit():
    time.sleep(2.2)           # what a stuck lock / slow disk call looks like to the loop

async def main():
    LW.start()
    await asyncio.sleep(0.5)
    blocking_culprit()        # freezes the loop for 2.2 s
    await asyncio.sleep(0.6)
    s = LW.snapshot()
    assert s["stalls_10min"] >= 1, s
    assert "blocking_culprit" in s["last_stall"]["where"], s
    assert s["last_stall"]["ms"] >= 1500, s
    print("loop watch ok:", s["last_stall"]["ms"], "ms stall, found in", s["last_stall"]["where"].split(" <- ")[0])
asyncio.run(main())

# api_server needs fastapi (not installed in every test box), so read its source instead of importing it
import ast
SRC = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py")).read()
TREE = ast.parse(SRC)
kinds = {n.name: type(n).__name__ for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
# NEXT-6f: the REST handlers moved into api/status.py (inside make_router_* factories), so look there too
_ST = ast.parse(open(os.path.join(os.path.dirname(__file__), "..", "backend", "api", "status.py")).read())
for _n in ast.walk(_ST):
    if isinstance(_n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        kinds.setdefault(_n.name, type(_n).__name__)
for name in ["get_status", "get_positions", "get_market", "get_signals", "get_alerts", "get_history", "get_equity"]:
    assert kinds[name] == "FunctionDef", name        # plain def => FastAPI thread pool, not the event loop
assert "await send(_snapshot_msg())" not in SRC       # the snapshot (exchange call in live mode) is built in a thread
print("rest handlers off the event loop ok")

cls = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "ConnectionManager")
ns = {"asyncio": asyncio, "WebSocket": object, "MAX_SOCKETS": 3, "SEND_TIMEOUT_SEC": 10.0}
exec(compile(ast.Module([cls], []), "cm", "exec"), ns)
A_CM = ns["ConnectionManager"]

class FakeWS:
    def __init__(self): self.closed = False
    async def accept(self): pass
    async def close(self): self.closed = True

async def sockets():
    m = A_CM()
    ws = [FakeWS() for _ in range(6)]
    for w in ws: await m.connect(w)
    assert len(m.active_connections) == 3
    assert all(w.closed for w in ws[:3]) and not any(w.closed for w in ws[3:])
    print("socket cap ok: kept newest 3 of 6")
asyncio.run(sockets())
print("ALL PASS")

# ---- v5: the heavy AI badge job must never run on the event loop --------------------------------------
import threading, tempfile, json as _json
fn_src = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "_cached_flags")
calls = {"n": 0}
class _Miner:
    @staticmethod
    def open_flags(ps):
        calls["n"] += 1
        time.sleep(1.5)                       # the real one took 60-90 s
        return {"1": {"verdict": "AVOID"}}
import types
fake_pkg = types.ModuleType("recovered_bot"); fake_pkg.ai_miner = _Miner; fake_pkg.ai_ml = _Miner
sys.modules["recovered_bot_fake"] = fake_pkg
ns2 = {"time": time, "threading": threading, "_FLAG_CACHE": {}, "_FLAG_TTL_S": 1.0, "_FLAG_BUSY": set(),
       "_HEAVY_LOCK": threading.Semaphore(1)}
src = ast.get_source_segment(SRC, fn_src).replace("from recovered_bot import ai_miner", "ai_miner = sys.modules['recovered_bot_fake'].ai_miner") \
                                           .replace("from recovered_bot import ai_ml", "ai_ml = sys.modules['recovered_bot_fake'].ai_ml")
ns2["sys"] = sys
exec(src, ns2)
t0 = time.perf_counter()
first = ns2["_cached_flags"]("miner", [{"id": 1}])
dt = time.perf_counter() - t0
assert first == {} and dt < 0.2, (first, dt)           # answered at once, nothing computed on the caller
ns2["_cached_flags"]("miner", [{"id": 1}])             # second call while busy: no second worker
time.sleep(1.8)
assert calls["n"] == 1
assert ns2["_cached_flags"]("miner", [{"id": 1}]) == {"1": {"verdict": "AVOID"}}
print("badge job runs in a worker thread ok: caller waited", round(dt * 1000), "ms, 1 worker only")

# ---- v5: archive is parsed once per change ------------------------------------------------------------
from recovered_bot import trade_store as TS
d = tempfile.mkdtemp(); TS._archive = os.path.join(d, "arch.jsonl")
with open(TS._archive, "w") as f:
    for i in range(50): f.write(_json.dumps({"id": i, "closed_at_ts": i, "roi_pct": 1.0, "fee_applied": True}) + "\n")
parses = {"n": 0}; real = TS.json.loads
TS.json.loads = lambda s, *a, **k: (parses.__setitem__("n", parses["n"] + 1), real(s, *a, **k))[1]
a = TS.get_all_closed(20); b = TS.get_all_closed(20); c = TS.get_all_closed(20, net=False)
assert parses["n"] == 50 and len(a) == 20 and a[-1]["id"] == 49, parses
a[0]["roi_pct"] = 999; assert TS.get_all_closed(20)[0]["roi_pct"] == 1.0     # editing a result never corrupts the cache
with open(TS._archive, "a") as f: f.write(_json.dumps({"id": 50, "closed_at_ts": 50, "fee_applied": True}) + "\n")
assert TS.get_all_closed(5)[-1]["id"] == 50 and parses["n"] == 101           # new row -> re-read once
TS.json.loads = real
print("archive cache ok: 50 rows parsed once for 3 calls, re-read only after a change")
print("ALL PASS v5")
