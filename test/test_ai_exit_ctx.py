"""3B: the bigger-trend tag in the exit table. The tagged table answers first, only when it has enough data;
otherwise the plain table answers as before. Fake data only, no network."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_exit_learn as X
from recovered_bot import ai_context as CTX

X._loaded = True
X._stats.clear(); X._seen.clear()
lab = {"tsi": "T-recover", "zz": "Zagainst/down", "ema": "EMA-", "sd": "SDsteady"}

def fill(tag, n_each, per_trade_delta):
    for k, _c in X.keys(lab):
        kk = k + "@" + tag if tag else k
        X._stats[kk] = [n_each, n_each * per_trade_delta, n_each, n_each * per_trade_delta]

# plain table says HOLD (+3% price at lev 1 each), the AGAINST table says BOOK (-3%)
fill(None, 30, 3.0)
fill("A", 30, -3.0)
assert X.evaluate(lab, 1.0)["call"] == "HOLD"
r = X.evaluate(lab, 1.0, align="AGAINST")
assert r["call"] == "BOOK" and r["ctx"] == "A" and "ULTA" in r["why"], r
r = X.evaluate(lab, 1.0, align="WITH")                      # no WITH data yet -> plain table answers, exactly as before
assert r["call"] == "HOLD" and r["ctx"] is None, r
assert X.evaluate(lab, 1.0, align="UNKNOWN")["call"] == "HOLD"
assert X.evaluate(lab, 1.0, align=None)["call"] == "HOLD"
print("tag lookup ok")

# a tagged table with too little data (5 per half) is ignored
X._stats.clear(); fill(None, 30, 3.0); fill("A", 5, -3.0)
assert X.evaluate(lab, 1.0, align="AGAINST")["call"] == "HOLD"
print("thin tag ignored ok")

# learn(): the tag is recorded only for a young signal with a known picture; old signals feed the plain table only
assert X.bucket("WITH") == "W" and X.bucket("AGAINST") == "A" and X.bucket("SIDE") == "O" and X.bucket("UNKNOWN") is None
now = time.time()
S = {"t": [now - 600] * 5}
CTX._cache.clear()
for tf in ("1h", "4h", "1d"):
    CTX._cache[("AAAUSDT", tf)] = {"t": now, "trend": "UP"}
assert X._tag_of_signal("AAAUSDT|x", S, 0, True) == "W"
assert X._tag_of_signal("AAAUSDT|x", S, 0, False) == "A"
assert X._tag_of_signal("ZZZUSDT|x", S, 0, True) is None                  # nothing cached for that coin
assert X._tag_of_signal("AAAUSDT|x", {"t": [now - 5 * 3600]}, 0, True) is None   # too old: the cached picture is not that moment
print("tag of signal ok")

# the key text understands the tag
assert "SAATH" in X.nice("tsi=T+up@W") and "ULTA" in X.nice("tsi=T+up & ema=EMA+@A")
s = X.summary(1.0)
assert set(s["ctx_obs"]) == {"W", "A", "O"}
# end to end: a young finished signal feeds the plain table AND the bigger-trend table, once per signal
import random, tempfile
from recovered_bot import ai_ind_features as F
X._file_override = os.path.join(tempfile.mkdtemp(), "ai_exit_learn.json")
X._stats.clear(); X._seen.clear()
rnd, px, cs = random.Random(1), 100.0, []
t0 = time.time() - 700 * 180 - 60
for k in range(700):
    o = px; px = max(1.0, px * (1 + rnd.gauss(0, 0.004)))
    cs.append({"timestamp": int((t0 + k * 180) * 1000), "open": o, "high": max(o, px) * 1.001, "low": min(o, px) * 0.999, "close": px, "volume": 1.0})
S2 = F.build(cs)
X.TAG_MAX_AGE_S = 48 * 3600          # the age rule itself is tested above; this trade needs 300 candles of history to finish
i = 300
e = S2["c"][i]
ok = X.learn("AAAUSDT|sig1", S2, i, True, e, e * 0.5, [e * 1.5, e * 1.6, e * 1.7, e * 1.8])   # wide SL, ends by cross or time-out after surviving candles
assert ok
tagged = [k for k in X._stats if "@W" in k and not k.startswith("ctx")]
plain = [k for k in X._stats if "@" not in k]
assert tagged and plain, (tagged, plain)
assert X._stats["ctx@W"][0] + X._stats["ctx@W"][2] == 1
assert X.learn("AAAUSDT|sig1", S2, i, True, e, e * 0.5, [e * 1.5, e * 1.6, e * 1.7, e * 1.8]) is False   # same signal is never counted twice
print("learn tagged ok")
print("ALL OK")
