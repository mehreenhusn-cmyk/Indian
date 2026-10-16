"""Coach uses the learned exit-vs-hold table (ai_exit_learn) - FAKE data, no network. Run: python3 test/test_ai_exit_coach.py"""
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

def trade(entry, bid):
    bp = {"id": bid, "symbol": "TESTUSDT", "action": "BUY", "timeframe": "3m", "signal_stop_loss": entry * 0.9, "signal_tp1": entry * 1.2,
          "signal_tp2": entry * 1.3, "signal_tp3": entry * 1.4, "signal_tp4": entry * 1.5, "leverage": 10, "invest_usdt": 100.0}
    v = C._new_trade(bp, entry); C._state["open"][str(bid)] = v
    return v

def table(avg):
    return {k: [20, avg * 20, 20, avg * 20] for k, _c in XL.keys(lab)}

OLD_EXIT = lambda labs, prog: (True, "BASIC", "old rule exit")
C.decide_exit = OLD_EXIT

# 1) no table: a trade IN LOSS is never closed by the AI (old behaviour), a profitable one uses the old rule
XL._stats.clear()
v = trade(last * 1.01, 1); assert C.on_bar(v, S, i) is False and "1" in C._state["open"]
v = trade(last * 0.99, 2); assert C.on_bar(v, S, i) is True and C._state["closed"][-1]["reason"] == "old rule exit"
print("no table = old behaviour ok")

# 2) table says BOOK (closing now was better by 5 ROI pts in both halves): a trade IN LOSS is closed, reason + mode set
XL._stats.update(table(-0.5))
v = trade(last * 1.01, 3); assert C.on_bar(v, S, i) is True
rec = C._state["closed"][-1]; assert rec["reason"].startswith("INDICATOR EXIT") and rec["mode"] == "LEARNED" and rec["roi"] < 0, rec
assert v["read"]                                                                  # the screen can show what the AI reads
print("loss exit ok:", rec["reason"][:70])

# 3) table says HOLD: the weaker 'old rule' exit is skipped and the reason is kept for the screen
XL._stats.clear(); XL._stats.update(table(+0.5))
v = trade(last * 0.99, 4); assert C.on_bar(v, S, i) is False and "4" in C._state["open"] and v["hold_reason"]
print("hold ok")

# 4) table says nothing clear (halves disagree): old behaviour again
XL._stats.clear(); XL._stats.update({k: [20, -10.0, 20, +10.0] for k, _c in XL.keys(lab)})
v = trade(last * 0.99, 5); assert C.on_bar(v, S, i) is True and C._state["closed"][-1]["reason"] == "old rule exit"
print("unclear = old behaviour ok")

# 5) build() carries the new blocks for the screen
XL._stats.clear(); XL._stats.update(table(-0.5)); XL._seen[1] = 1
b = C.build()
assert "exit_learn" in b and b["exit_learn"]["book"] and b["exit_learn"]["studied"] == 1
v = trade(last * 0.99, 6); v["read"] = "x"; b = C.build(); assert any(o.get("read") == "x" for o in b["open"])
print("build ok")
print("ALL OK")
