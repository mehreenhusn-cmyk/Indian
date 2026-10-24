"""Special Master v6 Z-EMA 30/50 numbers + labels in ai_ind_features (raw numbers, no rule). Run: cd backend && python3 ../test/test_zema_features.py"""
import math, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from recovered_bot import ai_ind_features as F

random.seed(3)
p, cs = 100.0, []
for k in range(900):
    o = p
    p = p * (1 + random.gauss(0, 0.004) + 0.0005 * math.sin(k / 40))
    cs.append({"timestamp": k * 300000, "open": o, "high": max(o, p) * 1.001, "low": min(o, p) * 0.999, "close": p})
S = F.build(cs)
assert len(S["zef"]) == len(S["zes"]) == 900 and sum(S["zxu"]) > 0 and sum(S["zxd"]) > 0
j = [x for x in range(500, 900) if S["zxu"][x]][0]          # a black BUY candle
f = F.own_features(S, j)
assert f["zbn"] == 1 and f["zbx"] == 0 and f["zcs"] > 0
assert F.labels("BUY", f, {})["z_black"].startswith("Z black candle WITH trade, now")
assert F.labels("SELL", f, {})["z_black"].startswith("Z black candle AGAINST trade, now")
f2 = F.own_features(S, j + 2)
assert f2["zbx"] == 2 and "1-3 candles ago" in F.labels("BUY", f2, {})["z_black"]
assert abs(f["zcl"] - (f["zef"] - f["zes"])) < 0.002
print("PASS test_zema_features")
