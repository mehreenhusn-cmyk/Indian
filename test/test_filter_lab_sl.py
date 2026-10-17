"""filter_lab SL variants + Bollinger gates. Run: python3 test/test_filter_lab_sl.py"""
import os, sys, random, time, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import filter_lab as FL
from recovered_bot import ai_ind_features as F, ai_shadow_lab as LAB


def candles(n, step_ms, seed, end_ms=None):
    rnd = random.Random(seed)
    end_ms = end_ms or int(time.time() * 1000) - 2 * step_ms
    t0 = end_ms - n * step_ms
    p, drift, out = 100.0, 0.0, []
    for k in range(n):
        if k % 60 == 0:
            drift = rnd.choice([-0.12, 0.0, 0.12])
        o = p
        p = max(1.0, p * (1 + (drift + rnd.gauss(0, 0.35)) / 100))
        out.append({"timestamp": t0 + k * step_ms, "open": o, "high": max(o, p) * (1 + abs(rnd.gauss(0, 0.1)) / 100),
                    "low": min(o, p) * (1 - abs(rnd.gauss(0, 0.1)) / 100), "close": p, "volume": 1000.0})
    return out


# 1. sim_trade with the bot's own SL and no buffer == the live replay rule T4 (same engine as ai_shadow_lab)
C = candles(1500, 300_000, 1)
S = F.build(C)
rnd = random.Random(5)
same = 0
for _ in range(300):
    i = rnd.randint(420, 1100)
    is_long = rnd.random() < 0.5
    e = S["c"][i]
    sl = S["l"][i] if is_long else S["h"][i]
    k = 1 if is_long else -1
    tps = [e * (1 + k * x / 100) for x in (0.3, 0.6, 0.9, 1.2)]
    ref = LAB._simulate(S, i, is_long, e, sl, tps)["T4"]
    got = FL.sim_trade(S, i, is_long, e, sl, tps[0], tps[3], 0.0)
    assert round(got[0], 4) == ref[0] and got[1] == ref[1] and got[2] == ref[2], (got, ref)
    same += 1
print("sim_trade == live rule on", same, "random trades")

# 2. variants are never tighter than the base SL; ATR/ swing give wider or equal
for _ in range(200):
    i = rnd.randint(420, 1100)
    is_long = rnd.random() < 0.5
    e = S["c"][i]
    base = S["l"][i] if is_long else S["h"][i]
    for name, sl in FL.sl_levels(S, i, is_long, e, base).items():
        assert (sl <= base) if is_long else (sl >= base), name
print("variants never tighter: ok")

# 3. fee buffer: after TP1 the stop sits above entry, so a stopped trade after TP1 exits in profit
up = [{"timestamp": k * 300000, "open": 100, "high": 100.05, "low": 99.95, "close": 100, "volume": 1} for k in range(500)]
up[450] = {"timestamp": 450 * 300000, "open": 100, "high": 100.5, "low": 99.99, "close": 100.4, "volume": 1}   # touches TP1
up[451] = {"timestamp": 451 * 300000, "open": 100.4, "high": 100.4, "low": 99.9, "close": 100.0, "volume": 1}     # falls back to entry
S2 = F.build(up)
r0 = FL.sim_trade(S2, 449, True, 100.0, 99.0, 100.3, 101.0, 0.0)
r1 = FL.sim_trade(S2, 449, True, 100.0, 99.0, 100.3, 101.0, 0.1)
assert r0[1] == "BE" and abs(r0[0]) < 1e-9, r0
assert r1[1] == "BE" and abs(r1[0] - 0.1) < 1e-9, r1
print("fee-buffer stop: ok")

# 4. Bollinger numbers
w, pb = FL.bb_series(S)
assert all(x is None for x in w[:19]) and w[400] > 0 and pb[400] is not None
flat = {"c": [100.0] * 50}
assert FL.bb_series(flat)[0][-1] is None            # no spread = no band (never divide by zero)
print("bollinger: ok")

# 5. old-format rows (no alt / bb) still work end to end
def old_row(i, rnd):
    return {"a": "BUY", "s": "X", "tf": "5m", "t": i * 300000, "e": 100.0, "sl": 99.0, "tp": [101.0, 102, 103, 104],
            "ind": {"z": 0.5, "dif": 1.0, "tsi": 5, "zd3": 0.1}, "sig": {"cross_n": 1, "zone": "z"}, "net": rnd.gauss(0, 8)}
rows = [old_row(i, random.Random(i)) for i in range(300)]
txt = FL.text_report(FL.analyse(rows), "5m", 7, 10, 1.0)
assert "SIMPLE VERDICT" in txt and "BOLLINGER" in txt
print("old rows: ok")

# 6. planted: a wider SL that is clearly better is found; pure noise is not called BETTER
def alt_rows(planted, seed, n=500):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        b = rnd.gauss(0, 8)
        r = old_row(i, rnd)
        r["net"] = b
        r["alt"] = {"base|be0": [b, "SL", 4, 0.3]}
        for bk in ("be0", "bef"):
            for sk, _ in FL.SL_NAMES:
                if f"{sk}|{bk}" != "base|be0":
                    d = (2.5 if (planted and sk == "prev1" and bk == "be0") else 0.0) + rnd.gauss(0, 3)
                    r["alt"][f"{sk}|{bk}"] = [b + d, "SL", 6, 0.5]
        out.append(r)
    return out
fp = 0
for sd in range(20):
    res = FL.sl_tests(alt_rows(False, sd))
    fp += sum(x["verdict"].startswith("BETTER") for x in res["rows"])
res = FL.sl_tests(alt_rows(True, 1))
hit = [x for x in res["rows"] if x["key"] == "prev1|be0"][0]
print("noise false BETTER:", fp, "of", 20 * 11, "| planted:", hit["verdict"])
assert fp <= 6 and hit["verdict"].startswith("BETTER")

# 7. loss avoided / profit missed
old, new = FL.split_rows(alt_rows(False, 3))
j = FL.judge(old, new, lambda r: r["net"] > 0)
assert j["avoided"] > 0 and j["missed"] == 0, j

# 8. full path on made-up candles (network replaced): collect -> analyse -> text
LAB._fetch_range = lambda sym, tf, start: candles(3000, FL.TF_MS[tf], hash(sym) % 1000)
rows = FL.collect("5m", 7, ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"], 10.0, 1.0, log=lambda m: None)
print("collect rows:", len(rows), "with alt:", sum(1 for r in rows if r.get("alt")), "with bb:", sum(1 for r in rows if r.get("bb")))
assert rows and any(r.get("alt") for r in rows) and any(r.get("bb") for r in rows)
for r in rows:
    if r.get("alt"):                 # the base variant must equal the replay's own result
        assert abs(r["alt"]["base|be0"][0] - r["net"]) < 0.01, (r["alt"]["base|be0"], r["net"])
txt = FL.text_report(FL.analyse(rows), "5m", 7, 10.0, 1.0)
print(txt[:1500])
print("PASS")
