#!/usr/bin/env python3
"""python3 test/test_z_scenarios.py - no internet. Checks the Z cross maths, the scenario flags and the report on made-up data."""
import math, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import z_scenarios as ZS
from recovered_bot import ai_ind_features as F

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  OK  {name}")
    else: FAIL += 1; print(f" FAIL {name}")

check("cross up", ZS._cross([1, 3], [2, 2], 1) == 1)
check("cross down", ZS._cross([3, 1], [2, 2], 1) == -1)
check("no cross", ZS._cross([3, 4], [2, 2], 1) == 0)
check("touch then up counts (Pine crossover)", ZS._cross([2, 3], [2, 2], 1) == 1)
check("None safe", ZS._cross([None, 3], [2, 2], 1) == 0)

random.seed(7)
px, candles = 100.0, []
for k in range(700):
    px *= 1 + random.gauss(0, 0.004) + 0.0004 * math.sin(k / 25)
    candles.append({"timestamp": 1_700_000_000_000 + k * 300_000, "open": px, "high": px * 1.002, "low": px * 0.998, "close": px, "volume": 1.0})
S = F.build(candles)
r = {"a": "BUY", "ind": {"dif": 1.0}}
ZS.enrich(r, S, 650, 10, 1.0)
check("enrich adds zx", r.get("zx") and set(r["zx"]) == {"x0", "xn", "side", "ee"})
check("side matches the series", r["zx"]["side"] == (1 if S["z"][650] > ZS._z_emas(S)[1][650] else -1))

mk = lambda a, x0, xn, side, ee, dif, net: {"a": a, "t": 0, "net": net, "ind": {"dif": dif, "z": 0.5},
                                           "zx": {"x0": x0, "xn": xn, "side": side, "ee": ee}}
buy = mk("BUY", 1, 1, 1, 1, 1.0, 1.0); sell = mk("SELL", -1, -1, -1, -1, -1.0, 1.0)
check("buy: all three agree", ZS._votes(buy) == 3 and ZS._votes(sell) == 3)
check("buy with Z against = 1 vote", ZS._votes(mk("BUY", 0, 0, -1, -1, 1.0, 1.0)) == 1)
check("missing zx is safe", not ZS._z_now({"a": "BUY", "ind": {}}))

rows = []
for n in range(120):
    good = n % 2 == 0
    row = mk("BUY" if n % 4 < 2 else "SELL", 1 if good else 0, 1 if good else 0, 1 if good else -1, 1 if good else -1, 1.0 if good else -1.0, 1.0 if good else -1.0)
    if row["a"] == "SELL":
        row["zx"] = {k: -v for k, v in row["zx"].items()}; row["ind"]["dif"] = -row["ind"]["dif"]
    row["t"] = n * 300_000; row["tf"] = "5m"
    rows.append(row)
rep = ZS.analyse(rows)
check("report covers all scenarios", len(rep["scen"]) == len(ZS.SCENARIOS))
txt = ZS.text_report(rep, "5m", 7, 10, 1.0)
check("report prints answer + votes", "SHORT ANSWER" in txt and "opinions agree" in txt)
check("planted edge is found (Z black candle confirmed)", any("black candle" in l and l.startswith("  +") for l in txt.splitlines()))
print(f"\n{PASS} passed, {FAIL} failed"); sys.exit(1 if FAIL else 0)
