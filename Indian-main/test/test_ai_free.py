"""Free AI (own entry / own stop / own exit / flip / learning). Run: python3 test/test_ai_free.py"""
import os, sys, random, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_selfsignal as S, ai_pick as P, ai_shadow_lab as L, ai_ind_features as F

TF = "3m"; STEP = L.TF_MS[TF]
def series(n, seed=5, t_end=None):
    rnd = random.Random(seed); px = 100.0; out = []
    t0 = (t_end or int(time.time()*1000)) - n * STEP
    for i in range(n):
        px *= 1 + rnd.gauss(0, 0.004)
        hi, lo = px * (1 + abs(rnd.gauss(0, 0.002))), px * (1 - abs(rnd.gauss(0, 0.002)))
        out.append({"timestamp": t0 + i * STEP, "open": px, "high": hi, "low": lo, "close": px, "volume": 100})
    return out

ALL = series(1400)
cut = {"n": 800}
def vis(sym, tf, limit):
    c = ALL[:cut["n"]]
    # pretend the newest visible candle just closed
    return c[-limit:]
L._watchlist = lambda: ["TESTUSDT"]
L._fetch_limit = vis
L._ctx_series = lambda sym: {}
P._tf = lambda: TF
S._file = None; S._loaded = True
S._cfg = lambda name, default: default
assert S.free() and S.gate()[0]
# the stale-candle guard compares with the wall clock: make "now" = just after the visible candle each time
real_time = time.time
def fake_now(): return (ALL[cut["n"]-1]["timestamp"] + STEP + 1000) / 1000.0
S.time.time = fake_now  # module-level 'time' object is shared; restored at the end
random.seed(1)

# 1) free entries happen with NO rule: over many candles some trades open, each with own SL, no TP list, a plain reason
opened = 0
for k in range(300):
    cut["n"] = 800 + k
    S._next_eval.clear()
    S._free_scan("TESTUSDT")
    for v in S._state["open"].values():
        assert v["mode"] == "free" and v["tps"] == [] and v["sl"] != v["entry"] and v["why"]
        r = abs(v["entry"] - v["sl"]) / v["entry"] * 100
        assert r >= S.MIN_RISK_PCT - 1e-6 and r <= 90.0 + 1e-6, r
        assert v["stop_style"] in S.STOP_STYLES and set(v["xs"]) == {"pb", "loss", "trail"}
assert len(S._state["done"]) + len(S._state["open"]) >= 5, (len(S._state["done"]), len(S._state["open"]))

# 2) every finished trade has an exit reason, a roi and fed the learning table
assert S._state["done"]
for d in S._state["done"]:
    assert d["how"] and d.get("exit_why") and isinstance(d["roi"], float)
assert S._state["learn"], "nothing learned"
n_learn = sum(v[0] for k, v in S._state["learn"].items() if (k.endswith("|BUY") or k.endswith("|SELL")) and not k.startswith(("stop|", "exit|")))
assert any(k.startswith("stop|") for k in S._state["learn"]) and any(k.startswith("exit|") for k in S._state["learn"])
assert n_learn == len(S._state["done"]), (n_learn, len(S._state["done"]))

# 3) one trade per coin at a time
cut["n"] = 1300; S._state["open"].clear(); S._free_scan("TESTUSDT")
assert len(S._state["open"]) <= 1

# 4) stop is hit -> STOP; profit trail never moves a stop the wrong way
Sx = F.build(ALL[:900]); i = 700
e = Sx["c"][i]; sl = e * 0.99
for xs in ({"pb": "tsi", "loss": False, "trail": "none"}, {"pb": "z", "loss": True, "trail": "be"}, None):
    r = S._free_replay(Sx, i, "BUY", e, sl, xs)
    assert r["state"] in ("OPEN", "CLOSED") and r["sl"] >= sl
r2 = S._free_replay(Sx, i, "SELL", e, e * 1.01)
assert r2["sl"] <= e * 1.01

# 5) screen answer in free mode: entry / sl / now / pnl / chart for each live trade
cut["n"] = 1000
for kk in range(40):
    cut["n"] = 1000 + kk; S._next_eval.clear(); S._free_scan("TESTUSDT")
b = S.build()
assert b.get("free") is True and "error" not in b, b.get("error")
for lv in b["live"]:
    for key in ("entry", "sl", "now", "pnl", "chart", "why"):
        assert key in lv
assert b["learned"]["buckets"] >= 1
S.time.time = real_time
print("test_ai_free OK: done=%d open=%d buckets=%d" % (len(S._state["done"]), len(S._state["open"]), len(S._state["learn"])))
