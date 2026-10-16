"""Trailing stop steps (trail_mode off/step1/step2). Run: python3 test/test_trail_modes.py"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import paper_trader as P, settings_store as S, status

E, SL = 100.0, 98.0
TP = {1: 102.0, 2: 104.0, 3: 106.0, 4: 108.0}
STEP = 3 * 60_000


def pos(**kw):
    d = {"id": 1, "symbol": "TESTUSDT", "action": "BUY", "entry_price": E, "leverage": 10.0, "invest_usdt": 10.0,
         "signal_stop_loss": SL, "signal_tp1": TP[1], "signal_tp2": TP[2], "signal_tp3": TP[3], "signal_tp4": TP[4],
         "opened_at_ts": 0, "tp_hit_levels": [], "max_roi_pct": 0.0, "min_roi_pct": 0.0}
    d.update(kw)
    return d


def candles(path):
    """path = list of (high, low) per candle, starting after the entry candle."""
    out = [{"timestamp": 0, "open": E, "high": E, "low": E, "close": E, "volume": 1}]
    for i, (h, l) in enumerate(path, start=1):
        out.append({"timestamp": i * STEP, "open": E, "high": h, "low": l, "close": E, "volume": 1})
    return out


def run(mode, path, **kw):
    S.update(trail_mode=mode)
    P.exchange.GRANULARITY_MIN = 3
    out, hits, _b, _w, extra = P._evaluate_candles(pos(**kw), candles(path), 0.0, 0)
    return out, hits, extra


# floor helper
for mode, n, want in [("step1", 1, E), ("step1", 2, 102.0), ("step1", 3, 104.0),
                      ("step2", 1, None), ("step2", 2, E), ("step2", 3, 102.0), ("off", 3, None)]:
    got = P._trail_floor_price(mode, E, TP, set(range(1, n + 1)))
    assert got == want, (mode, n, got, want)

# SELL side mirror
tps_s = {1: 98.0, 2: 96.0, 3: 94.0, 4: 92.0}
assert P._trail_floor_price("step1", E, tps_s, {1, 2}) == 98.0
assert P._sl_tightens(102.0, 100.0, False) and not P._sl_tightens(99.0, 100.0, False)

# touches TP1, TP2 then falls back to TP1 level:
path = [(102.5, 101), (104.5, 103), (104, 101.9)]
o, hits, _ = run("off", path)
assert o is None or o["reason"] != "SL" or o["exit_price"] == E          # off: stop is entry (BE after TP1)
o, hits, _ = run("step1", path)
assert o and o["reason"] == "SL" and o["exit_price"] == 102.0, o          # step1: stop = TP1 -> profit lock
o, hits, _ = run("step2", path)
assert o is None, o                                                       # step2: stop = entry, still running

# TP1 then back to entry: off/step1 stop at entry, step2 stays alive (original SL)
path = [(102.5, 101), (101.5, 99.9)]
o, _, _ = run("off", path);   assert o and o["exit_price"] == E
o, _, _ = run("step1", path); assert o and o["exit_price"] == E
o, _, _ = run("step2", path); assert o is None

# TP2 then back to entry: step2 stops at entry
path = [(102.5, 101), (104.5, 103), (103, 99.9)]
o, _, _ = run("step2", path); assert o and o["exit_price"] == E

# step2 after TP3 -> TP1
path = [(102.5, 101), (104.5, 103), (106.5, 105), (105, 101.9)]
o, _, _ = run("step2", path); assert o and o["exit_price"] == 102.0
# step1 after TP3 -> TP2
o, _, _ = run("step1", path); assert o and o["exit_price"] == 104.0

# full run to TP4 still wins in every mode
path = [(102.5, 101), (104.5, 103), (106.5, 105), (108.5, 107)]
for m in ("off", "step1", "step2"):
    o, _, _ = run(m, path); assert o and o["reason"] == "TP4", (m, o)

# a manually trailed stop further out is never loosened
path = [(104.5, 103.5), (104.2, 103.2)]
o, _, ex = run("step1", path, trailed_sl=103.0, opened_at_ts=1)
assert o is None and ex["trail_sl"] is None, (o, ex)
S.update(trail_mode="bogus"); assert P._trail_mode() == "off"
print("trail modes: all OK")
