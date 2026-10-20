"""Round B: AI own signals (shadow only). Run: python3 test/test_ai_selfsignal.py"""
import os, sys, random, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_selfsignal as S, ai_pick as P, ai_shadow_lab as L

TF = "3m"; STEP = L.TF_MS[TF]
def series(n, seed=3):
    rnd = random.Random(seed); px = 100.0; out = []; t0 = 1_700_000_000_000
    for i in range(n):
        px *= 1 + rnd.gauss(0, 0.004)
        hi, lo = px * (1 + abs(rnd.gauss(0, 0.002))), px * (1 - abs(rnd.gauss(0, 0.002)))
        out.append({"timestamp": t0 + i * STEP, "open": px, "high": hi, "low": lo, "close": px, "volume": 100 + rnd.random() * 50})
    return out

ALL = series(1100)
cut = {"n": 800}
L._watchlist = lambda: ["TESTUSDT"]
L._fetch_limit = lambda sym, tf, limit: ALL[:cut["n"]][-limit:]
L._ctx_series = lambda sym: {}
P._tf = lambda: TF
P._book = lambda tf, force=False: {"book": {}, "be": {}, "n": 0, "t": time.time()}
S._file = None; S._loaded = True

S.free = lambda: False; S.explore = lambda: False            # sections 1-4 test the OLD gate mode; explore mode has its own section 5
# 1) gate: a brand-new AI Pick must NOT start own signals yet
P._loaded = True
with P._lock:
    P._state["since"] = time.time()
ok, why = S.gate()
assert not ok and "Waiting" in why, (ok, why)

# 2) nothing proven -> decide() says WATCH -> no own signal is ever recorded
for k in range(30):
    cut["n"] = 800 + k; S._scan_one()
assert not S._state["open"] and not S._state["done"]

# 3) force TAKE: signals are recorded with entry/stop/targets and a plain-English reason
P.decide = lambda side, labels, book: {"call": "TAKE", "why": "TAKE: test", "cells": []}
S._state["rr"] = 0
opened = 0
for k in range(120):
    cut["n"] = 800 + k; S._scan_one()
    opened = max(opened, len(S._state["open"]) + len(S._state["done"]))
assert opened > 0, "no own signal was recorded"
for v in list(S._state["open"].values()) + S._state["done"]:
    assert v["sl"] != v["entry"] and len(v["tps"]) == 4 and v["why"].startswith("TAKE")
    if v["side"] == "BUY": assert v["sl"] < v["entry"] < v["tps"][0] or v["tps"][0] > v["entry"] * 0.9
    else: assert v["sl"] > v["entry"]

# 4) later candles finish them (shadow result after fee), and the scoreboard says it is too early / gives a verdict
cut["n"] = 1100; S._scan_one()
b = S.build()
assert b.get("error") is None, b
assert b["mine"]["n"] == len(S._state["done"]) and "Too early" in b["verdict"] or b["mine"]["n"] >= 30, b["verdict"]
assert b["open"] <= S.MAX_OPEN
# 5) EXPLORE MODE: no gate, no proven situation needed; the AI's own indicator reading decides; max 5 open
good = {"z_tsi": "Z and TSI both WITH trade", "zma_vs_trade": "Z avg-line WITH trade", "move": "trending WITH trade",
        "sd_zone": "0 to +1 SD", "warning": "no reversal arrow", "ema_dist": "price near EMA50"}
ok_, why_ = S._read("BUY", good); assert ok_ and "BUY" in why_ and "0 to +1 SD" in why_, why_
assert not S._read("BUY", dict(good, z_tsi="Z WITH but TSI AGAINST"))[0]
assert not S._read("BUY", dict(good, move="sideways (small range, flat EMA)"))[0]
assert not S._read("BUY", dict(good, ema_dist="price far from EMA50 (WITH trade)"))[0]      # no chasing
assert not S._read("BUY", dict(good, warning="reversal arrow DOWN"))[0] and S._read("SELL", dict(good, warning="reversal arrow DOWN"))[0]
S.explore = lambda: True
S._state.update(open={}, done=[], rr=0)
S._cfg = lambda name, default: 3 if name == "selfsignal_max_open" else default
assert S.max_open() == 3 and S.gate()[0] and "Explore" in S.gate()[1]
P.decide = lambda side, labels, book: {"call": "WATCH", "why": "WATCH: nothing proven", "cells": []}   # nothing proven at all
S._read = lambda side, lab: (True, "%s: test reading." % side)
L._watchlist = lambda: ["A1USDT", "A2USDT", "A3USDT", "A4USDT", "A5USDT"]
for k in range(40):
    cut["n"] = 900 + k; S._scan_one()
assert 0 < len(S._state["open"]) <= 3, len(S._state["open"])                    # entered although nothing is proven; capped at 3
assert all(v["mode"] == "explore" and v["why"].endswith("test reading.") for v in S._state["open"].values())
P.decide = lambda side, labels, book: {"call": "SKIP", "why": "SKIP: proven loser", "cells": []}
S._state.update(open={}, done=[])
for k in range(10):
    cut["n"] = 1000 + k; S._scan_one()
assert not S._state["open"], "a proven loser must still be avoided"
b = S.build(); assert b["explore"] is True and b["gate_open"] is True
print("ai_selfsignal: all OK  | own signals finished:", b["mine"]["n"], "open:", b["open"], "|", b["verdict"][:60])
