"""Lag fix: heavy AI answers are cached, shared, serial and stale-served. Run: python3 test/test_swr.py"""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py"), encoding="utf-8").read()
a, b = src.index("# ---- LAG FIX"), src.index("_FLAG_CACHE = {}")
class A: pass
_ns = {"asyncio": asyncio, "sys": sys, "threading": threading, "time": time}
exec(src[a:b], _ns)                       # the real helper code (fastapi is not needed to test it)
for _k, _v in _ns.items():
    setattr(A, _k, _v)

calls, active, peak = [], [0], [0]
lock = threading.Lock()

def slow(tag):
    with lock:
        active[0] += 1; peak[0] = max(peak[0], active[0])
    time.sleep(0.3)
    with lock:
        active[0] -= 1
    calls.append(tag)
    return {"n": len(calls), "tag": tag}

async def main():
    # 1) 5 simultaneous first requests -> ONE build, all get the same answer
    r = await asyncio.gather(*[A._swr("k1", 5.0, slow, "a") for _ in range(5)])
    assert len(calls) == 1 and all(x == r[0] for x in r), (calls, r)
    # 2) fresh -> no new build
    await A._swr("k1", 5.0, slow, "a"); assert len(calls) == 1
    # 3) stale -> OLD answer returned at once, new one built behind it
    t0 = time.time(); old = await A._swr("k1", 0.0, slow, "a")
    assert time.time() - t0 < 0.1 and old["n"] == 1, old
    await asyncio.sleep(0.5); assert len(calls) == 2
    new = await A._swr("k1", 5.0, slow, "a"); assert new["n"] == 2
    # 4) two different heavy builds never run at the same time
    await asyncio.gather(A._swr("k2", 5.0, slow, "b"), A._swr("k3", 5.0, slow, "c"))
    assert peak[0] == 1, peak
    # 5) a failing refresh keeps the old answer
    def bad(): raise RuntimeError("x")
    await A._swr("k4", 0.0, lambda: 7); A._SWR_JOBS["k4"] = (bad, ())
    v = await A._swr("k4", 0.0, bad); await asyncio.sleep(0.1)
    assert v == 7 and A._SWR["k4"]["v"] == 7
    # 6) event loop stays responsive while a heavy build runs
    ticks = []
    async def ticker():
        for _ in range(8):
            ticks.append(time.time()); await asyncio.sleep(0.05)
    def burn():
        t = time.time()
        while time.time() - t < 0.4: sum(i * i for i in range(2000))
        return 1
    await asyncio.gather(ticker(), A._swr("k5", 5.0, burn))
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert max(gaps) < 0.2, gaps
    print("swr ok: max loop gap while a heavy build ran = %.0f ms" % (max(gaps) * 1000))

    # 7) Bot vs AI ("coach") has its own lane: it is NOT queued behind a long heavy job, and the timing is recorded
    def long_heavy():
        time.sleep(1.2); return 1
    def quick_coach():
        return {"ok": 1}
    heavy_task = asyncio.ensure_future(A._swr("miner_like", 5.0, long_heavy))
    await asyncio.sleep(0.2)
    assert A._HEAVY_NOW["key"] == "miner_like", A._HEAVY_NOW           # health endpoint can name who holds the lock
    t0 = time.time(); v = await A._swr("coach", 5.0, quick_coach); dt = time.time() - t0
    assert v == {"ok": 1} and dt < 0.5, dt
    assert A._TIMING["coach"][0] < 0.5 and A._TIMING["coach"][1] < 0.5, A._TIMING
    await heavy_task
    assert A._HEAVY_NOW["key"] is None and A._TIMING["miner_like"][1] >= 1.1
    print("coach lane ok: coach answered in %.0f ms while a heavy job held the lock" % (dt * 1000))
asyncio.run(main())
print("ALL PASS")
