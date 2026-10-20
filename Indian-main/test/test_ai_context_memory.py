"""ai_context + ai_coin_memory on FAKE data (no network). Run: python3 test/test_ai_context_memory.py"""
import os, random, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_context as X, ai_coin_memory as M, ai_exit_learn as XL, ai_ind_features as F

tmp = tempfile.mkdtemp()
M._file_override = os.path.join(tmp, "cm.json")
XL._file_override = os.path.join(tmp, "xl.json")
M._cfg = lambda: (10.0, 1.0)            # leverage 10, fee 1 ROI point

def candles(seed, n=300, drift=0.0, vol=0.004):
    """flat noise first, the trend only in the last 60 candles (like a real coin that just started to run)"""
    rnd, px, out = random.Random(seed), 100.0, []
    for k in range(n):
        o = px
        px = max(1.0, px * (1 + rnd.gauss(drift if k >= n - 60 else 0.0, vol)))
        out.append({"timestamp": 1_700_000_000_000 + k * 3_600_000, "open": o, "high": max(o, px) * 1.001,
                    "low": min(o, px) * 0.999, "close": px, "volume": 1.0})
    return out

# 1) trend labels
up = X._trend_of(F.build(candles(1, drift=0.008)))
dn = X._trend_of(F.build(candles(2, drift=-0.008)))
assert up and up["trend"] in ("UP", "TURN_DOWN"), up
assert dn and dn["trend"] in ("DOWN", "TURN_UP"), dn
assert X._trend_of(F.build(candles(3, n=20))) is None            # too little history -> None, not a guess
print("trend ok", up["trend"], dn["trend"])

# 2) tag relative to trade direction (cache only, no network)
X._cache.clear()
X._cache.update({("AAAUSDT", "1h"): {"t": 1, "trend": "UP"}, ("AAAUSDT", "4h"): {"t": 1, "trend": "UP"},
                 ("AAAUSDT", "1d"): {"t": 1, "trend": "UP"}})
t_long, t_short = X.tag("AAAUSDT", "BUY"), X.tag("AAAUSDT", "SELL")
assert t_long["align"] == "WITH" and t_short["align"] == "AGAINST", (t_long, t_short)
assert "btc" not in t_long                                         # BTC is no longer part of the picture
assert X.tag("NEWUSDT", "BUY")["align"] == "UNKNOWN"             # nothing downloaded yet -> UNKNOWN
assert not hasattr(X, "market")
print("tag ok")

# 3) refresh is budgeted: never more than MAX_FETCH downloads per call, fresh cache is not downloaded again
calls = []
X._fetch = lambda sym, mins: (calls.append((sym, mins)) or candles(len(calls), drift=0.003))
X._cache.clear(); X._fail.clear()
X.refresh(["AAAUSDT", "BBBUSDT"])
assert len(calls) == X.MAX_FETCH, calls
n1 = len(calls); X.refresh(["AAAUSDT", "BBBUSDT"]); assert len(calls) > n1   # next call continues with what is missing
X.refresh(["AAAUSDT", "BBBUSDT"]); n2 = len(calls)
X.refresh(["AAAUSDT", "BBBUSDT"]); assert len(calls) == n2               # everything fresh -> no download
X._fetch = lambda sym, mins: (_ for _ in ()).throw(RuntimeError("net down"))
X._cache.clear(); X._fail.clear(); X.refresh(["CCCUSDT"])                 # failure keeps going, no raise
print("refresh ok")

# 4) coin status: Watching -> Learning -> Trusted / Avoid, only when BOTH halves agree
M._coins.clear(); M._ctx.clear(); M._loaded = True
assert M.status("ZZZUSDT")["status"] == "Watching"
for k in range(5):
    M.learn_replay("ZZZUSDT", 0.5, "s%d" % k)
assert M.status("ZZZUSDT")["status"] == "Watching"                         # 5 < MIN_SEEN
for k in range(5, 60):
    M.learn_replay("ZZZUSDT", 0.5, "s%d" % k)                              # +0.5% price = +5 ROI at 10x, minus fee
assert M.status("ZZZUSDT")["status"] == "Trusted", M.status("ZZZUSDT")
for k in range(60):
    M.learn_replay("BADUSDT", -0.5, "b%d" % k)
assert M.status("BADUSDT")["status"] == "Avoid"
rnd = random.Random(5)
for k in range(80):                                                         # winners and losers mixed -> no verdict
    M.learn_replay("MIXUSDT", 0.6 if rnd.random() < 0.5 else -0.6, "m%d" % k)
assert M.status("MIXUSDT")["status"] in ("Learning",), M.status("MIXUSDT")
print("status ok")

# 5) WITH vs AGAINST: honest until enough data, then compares
assert "Still collecting" in M.ctx_summary()["text"]
for k in range(40):
    M.on_close("ZZZUSDT", 6.0, 10, "WITH", "w%d" % k)
    M.on_close("ZZZUSDT", -4.0, 10, "AGAINST", "a%d" % k)
s = M.ctx_summary()
assert "WITH the bigger trend did better" in s["text"], s
assert s["rows"]["WITH"]["n"] == 40 and s["rows"]["AGAINST"]["avg"] < 0
M.on_close("ZZZUSDT", 1.0, 10, "UNKNOWN", "u1")                             # UNKNOWN never enters the table
assert "UNKNOWN" not in M._ctx
print("ctx ok")

# 6) exit_learn feeds the coin memory once per signal; summary shape; save + reload
M._coins.clear(); M._ctx.clear()
S = F.build(candles(9, n=700, vol=0.004))
i = 420; e = S["c"][i]
XL._stats.clear(); XL._seen.clear(); XL._loaded = True
ok = XL.learn("QQQUSDT|3m|1000|B", S, i, True, e, e * 0.97, [e * 1.01, e * 1.02, e * 1.03, e * 1.04])
if ok:
    assert M._coins["QQQUSDT"]["h"][0] + M._coins["QQQUSDT"]["h"][2] == 1
    XL.learn("QQQUSDT|3m|1000|B", S, i, True, e, e * 0.97, [e * 1.01, e * 1.02, e * 1.03, e * 1.04])
    assert M._coins["QQQUSDT"]["h"][0] + M._coins["QQQUSDT"]["h"][2] == 1        # second call: not counted again
sm = M.summary(["ZZZUSDT"])
assert set(sm) == {"coins", "counts", "total", "ctx"}
M._dirty = True; M._save(force=True)
M._coins.clear(); M._loaded = False; M._load()
assert M._file() and os.path.exists(M._file())
print("feed + save ok")
print("ALL OK")
