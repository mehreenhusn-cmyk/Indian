"""Stall cause test: a sleeping freeze is labelled PHONE PAUSED, a CPU-hogging freeze OUR CODE BUSY, and neither is "(not captured)".
Run: python3 test/test_stall_cause.py"""
import asyncio, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import loop_watch as LW

def sleeper():
    time.sleep(2.2)

def hog():
    t = time.perf_counter()
    while time.perf_counter() - t < 2.2:
        sum(range(1000))

async def main():
    LW.start()
    await asyncio.sleep(0.5)
    sleeper(); await asyncio.sleep(0.6)
    a = LW.snapshot()["last_stall"]["where"]
    assert a.startswith("[PHONE PAUSED]") and "sleeper" in a and "not captured" not in a, a
    await asyncio.sleep(1.0)
    hog(); await asyncio.sleep(0.6)
    b = LW.snapshot()["last_stall"]["where"]
    assert b.startswith("[OUR CODE BUSY]") and "hog" in b and "not captured" not in b, b
    print("stall cause ok:", a[:60], "|", b[:60])
asyncio.run(main())
print("ALL PASS")
