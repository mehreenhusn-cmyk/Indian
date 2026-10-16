"""Decision card + Risk ticks data + Stage 2 hooks of the AI Coach - FAKE data, no network.
Run: python3 test/test_ai_decision.py"""
import os, random, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_coach as C, ai_exit_learn as XL, ai_ind_features as F

CFG = {"leverage": 10, "fee_roi_pct": 0.0, "coach_enabled": True}
C._cfg = lambda n, d: CFG.get(n, d)
C._tf_min = lambda tf: 3
C._load(); C._file = None
XL._file_override = os.path.join(tempfile.mkdtemp(), "x.json")

rnd, px, cs = random.Random(3), 100.0, []
for k in range(420):
    o = px; px *= 1 + 0.0004 + rnd.uniform(-0.004, 0.004)
    cs.append({"timestamp": 1_700_000_000_000 + k * 180000, "open": o, "high": max(o, px) * 1.001, "low": min(o, px) * 0.999, "close": px})
S = F.build(cs); i = S["n"] - 1; last = S["c"][i]
lab = XL.state(S, i, 1.0); assert lab


def trade(entry, bid, side="BUY"):
    k = 1 if side == "BUY" else -1
    bp = {"id": bid, "symbol": "TESTUSDT", "action": side, "timeframe": "3m", "signal_stop_loss": entry * (1 - 0.1 * k),
          "signal_tp1": entry * (1 + 0.2 * k), "signal_tp2": entry * (1 + 0.3 * k), "signal_tp3": entry * (1 + 0.4 * k),
          "signal_tp4": entry * (1 + 0.5 * k), "leverage": 10, "invest_usdt": 100.0}
    v = C._new_trade(bp, entry); C._state["open"][str(bid)] = v
    return v


C.decide_exit = lambda labs, prog: (False, "BASIC", "")

# 1) no table, in loss -> the card says HOLD by the basic rule and explains that the stop stays
XL._stats.clear()
v = trade(last * 1.01, 1)
assert C.on_bar(v, S, i) is False
d = v["decision"]; assert d["call"] == "HOLD" and d["src"] == "BASIC" and "loss" in d["why"].lower(), d

# 2) no table, in profit -> HOLD with the basic-rule reason
v = trade(last * 0.99, 2)
C.on_bar(v, S, i)
assert v["decision"]["call"] == "HOLD" and "profit" in v["decision"]["why"].lower(), v["decision"]

# 3) a trusted HOLD from the learned table -> LEARNED source with the table's reason
XL._stats.update({k: [20, 10.0, 20, 10.0] for k, _c in XL.keys(lab)})
v = trade(last * 0.99, 3)
assert C.on_bar(v, S, i) is False
assert v["decision"]["call"] == "HOLD" and v["decision"]["src"] == "LEARNED" and v["decision"]["why"], v["decision"]
XL._stats.clear()

# 4) scalp flag -> SCALP decision
v = trade(last * 0.99, 4); v["scalp"] = True
C.on_bar(v, S, i)
assert v["decision"]["call"] == "SCALP", v["decision"]

# 5) build(): R numbers. Entry 100, stop 90 -> risk 10 ; price 105 -> +0.5R ; TP1 120 -> +2R ; stop -1R
C._state["open"].clear()
v = trade(100.0, 5); v["px"] = 105.0
C._price_cached = lambda sym: 105.0
row = [o for o in C.build()["open"] if o["sym"] == "TESTUSDT"][0]
assert row["r_now"] == 0.5 and row["stop_r"] == -1.0 and row["tp_r"] == [2.0, 3.0, 4.0, 5.0], row
v["be"], v["sl"] = True, 100.0                      # stop moved to entry -> 0R, risk unit stays the ORIGINAL risk
row = [o for o in C.build()["open"] if o["sym"] == "TESTUSDT"][0]
assert row["stop_r"] == 0.0 and row["r_now"] == 0.5, row
v["trail"] = 112.0                                   # trailing stop locks +1.2R
row = [o for o in C.build()["open"] if o["sym"] == "TESTUSDT"][0]
assert row["stop_r"] == 1.2 and row["trail"] is True, row
# SHORT mirrors it
C._state["open"].clear()
v = trade(100.0, 6, "SELL"); C._price_cached = lambda sym: 95.0
row = [o for o in C.build()["open"] if o["sym"] == "TESTUSDT"][0]
assert row["r_now"] == 0.5 and row["stop_r"] == -1.0 and row["tp_r"][0] == 2.0, row

# 6) hooks reach the real-account executor with the right kinds, and a broken executor never breaks the coach
seen = []
from recovered_bot import ai_live_executor as LX
LX.submit = lambda kind, v, px=None, reason="": seen.append(kind)
C._state["open"].clear()
v = trade(100.0, 7); C._close(v, 101.0, "test", "-")
assert seen == ["close"], seen
def boom(*a, **k): raise RuntimeError("executor down")
LX.submit = boom
v = trade(100.0, 8); C._close(v, 101.0, "test", "-")        # must not raise
assert str(8) not in C._state["open"]
print("ALL OK")
