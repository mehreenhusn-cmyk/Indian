"""ai_exit_learn on FAKE candles (no network). Run: python3 test/test_ai_exit_learn.py"""
import os, random, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_exit_learn as XL, ai_ind_features as F

XL._file_override = os.path.join(tempfile.mkdtemp(), "ai_exit_learn.json")

def candles(seed, n=700, drift=0.0):
    rnd, px, out = random.Random(seed), 100.0, []
    for k in range(n):
        o = px
        px = max(1.0, px * (1 + rnd.gauss(drift, 0.004)))
        out.append({"timestamp": 1_700_000_000_000 + k * 180_000, "open": o, "high": max(o, px) * 1.001,
                    "low": min(o, px) * 0.999, "close": px, "volume": 1.0})
    return out

S = F.build(candles(1))
i = 420
# 1) state(): both directions, labels relative to the trade
a, b = XL.state(S, 450, 1.0), XL.state(S, 450, -1.0)
assert a and b and set(a) == {"tsi", "zz", "ema", "sd"}
assert a["sd"] == b["sd"] and a["tsi"] != b["tsi"] or a["zz"] != b["zz"]          # SD is direction free, the rest flips
assert XL.state(S, 5, 1.0) is None                                               # not enough history -> no label
print("state ok")

# 2) replay: a long that is stopped out fast -> final = SL result, events only for candles that survived
e = S["c"][i]
r = XL.replay(S, i, True, e, e * 0.9995, [e * 1.5, e * 1.6, e * 1.7, e * 1.8])      # tiny SL: stopped almost at once
assert r is not None and r[1] < 0, r
# unreachable levels + wide SL -> either ends by cross/timeout; must not raise and must be finished
r2 = XL.replay(S, i, True, e, e * 0.5, [e * 1.5, e * 1.6, e * 1.7, e * 1.8])
assert r2 is None or isinstance(r2[1], float)
# a trade that runs out of data is NOT learned (None)
assert XL.replay(S, S["n"] - 3, True, S["c"][-3], S["c"][-3] * 0.5, [1e9, 1e9, 1e9, 1e9]) is None
print("replay ok")

# 3) trail after TP4 uses max(TP gap, signal risk): a bounce smaller than the risk must not end the trade
import copy
n = 60
T = {"n": n, "h": [], "l": [], "c": [], "xup": [False] * n, "xdn": [False] * n}
px = [100, 101, 102, 103, 104, 105, 104.4, 105.2, 106, 105.4, 103.0] + [103.0] * (n - 11)
for v in px:
    T["h"].append(v + 0.05); T["l"].append(v - 0.05); T["c"].append(v)
for k in ("z", "diff", "e50", "std", "width"):
    T[k] = [None] * n                                   # no labels -> only the ending matters here
r3 = XL.replay(T, 0, True, 100.0, 98.0, [101.0, 102.0, 103.0, 104.0])
# risk 2.0 > TP gap 1.0: best high 106.05 -> trail 104.05; the 104.4 dip stays above, the drop to 103 closes the trade at 104.05 (+4.05%)
assert r3 is not None and abs(r3[1] - 4.05) < 1e-6, r3
print("trail ok")

# 4) learn(): counted once per signal, first appearance of each situation only, two halves
XL.reset()
WIDE = (e, e * 0.5, [e * 1.5, e * 1.6, e * 1.7, e * 1.8])        # survives many candles -> has events
assert XL.replay(S, i, True, *WIDE) is not None and XL.replay(S, i, True, *WIDE)[0]
ok = XL.learn("SIG|3m|1|B", S, i, True, *WIDE)
again = XL.learn("SIG|3m|1|B", S, i, True, *WIDE)
assert ok and not again
tot = sum(v[0] + v[2] for v in XL._stats.values())
assert tot > 0 and all(v[0] + v[2] <= 1 for v in XL._stats.values())               # one trade = at most one sample per key
XL._save(force=True)
XL._stats.clear(); XL._seen.clear(); XL._loaded = False; XL._load()
assert XL._stats and XL._seen                                                      # survives a restart
print("learn ok")

# 5) evaluate(): needs >= MIN_HALF trades in BOTH halves, same sign in both, big enough
lab = {"tsi": "T-down", "zz": "Zagainst/down", "ema": "EMA-", "sd": "SDwide"}
K = {k: c for k, c in XL.keys(lab)}
def tab(avg_a, avg_b, n=20):
    return {k: [n, avg_a * n, n, avg_b * n] for k in K}
assert XL.evaluate(lab, 10, tab(-0.3, -0.3))["call"] == "BOOK"                      # -3 ROI pts in both halves
assert XL.evaluate(lab, 10, tab(-0.3, +0.3))["call"] == "NONE"                      # halves disagree
assert XL.evaluate(lab, 10, tab(-0.3, -0.3, n=5))["call"] == "NONE"                 # too few trades
assert XL.evaluate(lab, 10, tab(-0.05, -0.05))["call"] == "NONE"                    # -0.5 ROI pts: too small
assert XL.evaluate(lab, 1, tab(-0.3, -0.3))["call"] == "NONE"                       # same price move is -0.3 ROI at 1x
assert XL.evaluate(lab, 10, tab(0.3, 0.3))["call"] == "HOLD"
mixed = tab(-0.3, -0.3); mixed["tsi=T-down & zz=Zagainst/down"] = [20, 6.0, 20, 6.0]   # one pair says HOLD, three say BOOK
assert XL.evaluate(lab, 10, mixed)["call"] == "BOOK"
singles_only = {k: v for k, v in tab(-0.3, -0.3).items() if " & " not in k}
assert XL.evaluate(lab, 10, singles_only)["call"] == "BOOK"
one = {list(singles_only)[0]: list(singles_only.values())[0]}
assert XL.evaluate(lab, 10, one)["call"] == "NONE"                                  # a lonely single is not enough
print("evaluate ok")
print("ALL OK")
