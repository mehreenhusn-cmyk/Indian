"""Part U2 hook test: 7-day-only coins are read LIVE (no 7-day replay), today's coins still replay as before. Run: python test_dual_hooks.py"""
import math
import os
import random
import sys
import tempfile
import time

os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dual_lab as D
import filter_lab as FL
import universe_7d as U

ok = [0]


def check(c, msg):
    if not c:
        print("FAIL", msg)
        sys.exit(1)
    ok[0] += 1
    print("PASS", msg)


def candles(tf, n, seed):
    rnd, step = random.Random(seed), FL.TF_MS[tf]
    latest = (int(time.time() * 1000) // step) * step - step
    p, out = 100.0, []
    for k in range(n):
        o = p
        p = max(1.0, p * (1 + rnd.gauss(0, 0.004) + 0.0008 * math.sin(k / 30.0)))
        out.append({"timestamp": latest - (n - 1 - k) * step, "open": o, "high": max(o, p) * 1.001, "low": min(o, p) * 0.999, "close": p, "volume": 1.0})
    return out


ranged, limited = [], []


def fetch_range(sym, tf, start):
    ranged.append(sym)
    return candles(tf, int((time.time() * 1000 - start) / FL.TF_MS[tf]) + 1, sum(map(ord, sym + tf)))


def fetch_limit(sym, tf, limit):
    limited.append(sym)
    return candles(tf, limit, sum(map(ord, sym + tf)))[-limit:]


check(D._U7 is U, "dual_lab loads universe_7d")
U._S["extra"] = {"OLDUSDT"}
check(U.is_extra("OLDUSDT") and not U.is_extra("AAAUSDT"), "is_extra tells 7-day-only coins")
data = {"rows": {}, "trades": [], "seen": {}, "boot": {}, "fetched": {}, "started": time.time()}
st = {"model": None, "push": lambda: None, "push_t": 0}
D.cycle(data, st, fetch_limit, fetch_range, lambda: ["AAAUSDT", "OLDUSDT"])
check("AAAUSDT" in ranged and "OLDUSDT" not in ranged, "today coin replays 7 days, 7-day coin does NOT")
check("OLDUSDT" in limited, "7-day coin gets the normal live candles")
check("OLDUSDT|5m" in data["boot"] and "OLDUSDT|15m" in data["boot"], "7-day coin is marked as booted (no later replay burst)")
n = len(ranged)
D.cycle(data, st, fetch_limit, fetch_range, lambda: ["AAAUSDT", "OLDUSDT"])
check(len(ranged) == n, "no replay on the next cycle")
U._S["extra"] = set()
print("OK", ok[0], "checks")
