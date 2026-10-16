"""Part 1 smooth app: CPU meter + screen-first priority. Run: python3 test/test_ai_smooth_part1.py"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_cpu_meter as M, ai_priority as P

# priority: idle -> idle pace, after a request -> busy pace, after the window -> idle again
assert P.pace(0.3, 2.5) == 0.3 and not P.app_busy()
P.touch()
assert P.app_busy() and P.pace(0.3, 2.5) == 2.5
assert not P.app_busy(window=0.0)
assert P.status()["app_in_use"] is True

# cpu meter: two samples around some work must show the main thread using CPU
M.sample()
t0 = time.time()
while time.time() - t0 < 0.6:
    sum(i * i for i in range(20000))
M.sample()
s = M.status()
if s.get("available"):
    assert s["top_threads"] and s["process_cpu_pct"] > 0, s
else:                                   # no /proc (not Linux): must say so, never crash
    assert "reason" in s, s
print("ai_smooth_part1: all OK", s.get("process_cpu_pct"))
