"""BE2b test: one bulk call gives the live price of every asked coin (not only 14), cached, failure-safe. Run: python test_dual_live.py"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dual_live as L

ok = 0
def check(c, msg):
    global ok
    if not c:
        print("FAIL:", msg); sys.exit(1)
    ok += 1

calls = []
def fake():
    calls.append(1)
    return {f"C{i:02d}USDT": 1.0 + i for i in range(40)}

syms = [f"C{i:02d}USDT" for i in range(30)]
got = L.prices(syms, fetch=fake)
check(len(got) == 30, "all 30 coins get a price (old code stopped at 14)")
check(abs(got["C29USDT"] - 30.0) < 1e-9, "price value is right")
check(len(calls) == 1, "one request for all coins")
L.prices(syms, fetch=fake)
check(len(calls) == 1, "second call inside the cache time asks nothing")
check("NOPEUSDT" not in L.prices(["NOPEUSDT"], fetch=fake), "unknown coin is left out")
L._c.update({"t": 0.0, "map": {}})
check(L.prices(syms, fetch=lambda: 1 / 0) == {}, "a failing request returns {} (never raises)")
L._c.update({"t": 0.0, "map": {}})
check(L.prices(syms, fetch=lambda: {"C00USDT": -5, "C01USDT": "x"}) == {}, "bad prices are ignored")
print(f"PASS dual_live ({ok} checks)")
