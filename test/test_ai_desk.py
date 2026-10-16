"""AI Desk logic test on FAKE data (no network, no bot). Run: python3 test/test_ai_desk.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_desk as D, ai_exit_study as X

CFG = {"leverage": 1, "fee_roi_pct": 0.0, "desk_enabled": True}
D._cfg = lambda n, d: CFG.get(n, d)

def row(i, move, zt, v):
    return {"t": i, "sym": "C", "a": "BUY", "lab": {"move": move, "z_tsi": zt}, "v": {X.LIVE: v}}

T, S = "trending WITH trade", "sideways (small range, flat EMA)"
BOTH, MIX = "Z and TSI both WITH trade", "Z WITH but TSI AGAINST"
hist = [row(i, T, BOTH, 1.0) for i in range(60)] + [row(100 + i, S, MIX, -1.5) for i in range(60)] \
     + [row(200 + i, T, MIX, 0.9 if i % 2 else -0.9) for i in range(40)]
# 1) good situation -> LE, bad -> SKIP, flat -> WAIT, unknown -> WAIT
assert D.decide("3m", "BUY", {"move": T, "z_tsi": BOTH}, hist)["call"] == "LE"
assert D.decide("3m", "BUY", {"move": S, "z_tsi": MIX}, hist)["call"] == "SKIP"
assert D.decide("3m", "BUY", {"move": T, "z_tsi": MIX}, hist)["call"] == "WAIT"
assert D.decide("3m", "BUY", {"move": "new thing"}, hist)["call"] == "WAIT"
assert D.decide("3m", "SELL", {"move": T, "z_tsi": BOTH}, hist)["call"] == "WAIT"      # other side: no data
# 2) good only in the old half -> not LE
h2 = [row(i, T, BOTH, 2.0 if i < 30 else -0.2) for i in range(60)]
assert D.decide("3m", "BUY", {"move": T, "z_tsi": BOTH}, h2)["call"] != "LE"
# 1b) SD size/shape + SD level/TSI combos: BOTH indicators are used, a trusted bad combo vetoes
def row2(i, lab, v):
    return {"t": i, "sym": "C", "a": "BUY", "lab": lab, "v": {X.LIVE: v}}
big, tight = "SD ballooned", "SD tight"
exp, shr = "SD expanding", "SD shrinking"
h3 = [row2(i, {"move": T, "z_tsi": BOTH, "sd_size": tight, "sd_shape": shr}, 1.0) for i in range(40)] \
   + [row2(100 + i, {"move": S, "z_tsi": MIX, "sd_size": big, "sd_shape": exp}, -1.5) for i in range(40)]
good_lab = {"move": T, "z_tsi": BOTH, "sd_size": tight, "sd_shape": shr}
assert D.decide("3m", "BUY", good_lab, h3)["call"] == "LE"
# market+Z/TSI looks good, but the SD size+shape combo is bad -> SKIP (the second indicator vetoes)
mixed = {"move": T, "z_tsi": BOTH, "sd_size": big, "sd_shape": exp}
h4 = h3 + [row2(300 + i, {"move": T, "z_tsi": BOTH, "sd_size": big, "sd_shape": exp}, -1.5) for i in range(40)]
assert D.decide("3m", "BUY", mixed, h4)["call"] == "SKIP"
print("combos ok")

# 1c) learned(): lists good and bad situations that reached 30 old signals
_keep = X.lab_rows
X.lab_rows = lambda tf, lev, fee: h3
D._learn_cache.update(key=None, t=0.0, v=None)
L = D.learned("3m")
assert L["rows"] == 80 and L["ready"] > 0 and L["good"] and L["bad"], L
assert all(c["n"] >= D.MIN_N for c in L["good"] + L["bad"]) and L["good"][0]["avg"] > 0 > L["bad"][0]["avg"]
X.lab_rows = lambda tf, lev, fee: h3[:5]
D._learn_cache.update(key=None, t=0.0, v=None)
L = D.learned("3m"); assert L["ready"] == 0 and "pakka nahi" in L["msg"], L
X.lab_rows = _keep; D._learn_cache.update(key=None, t=0.0, v=None)
print("learned ok:", L["msg"])
print("decide ok")

# 3) virtual trade life: BUY entry 100, SL 98, TPs 101..104
bp = {"id": 7, "symbol": "C", "action": "BUY", "timeframe": "3m", "leverage": 1,
      "signal_stop_loss": 98, "signal_tp1": 101, "signal_tp2": 102, "signal_tp3": 103, "signal_tp4": 104}
def life(prices, target=4, side="BUY", tps=(101, 102, 103, 104), sl=98):
    D._state.update(open={}, closed=[], decisions=[], seen={})
    b = dict(bp, action=side, signal_stop_loss=sl, **{f"signal_tp{i+1}": t for i, t in enumerate(tps)})
    v = D._open_virtual(b, 100.0, "LE", "t", target); D._state["open"]["7"] = v
    for p in prices:
        if D._step(v, p, {}, {"7"}):
            break
    return D._state["closed"][-1] if D._state["closed"] else None
c = life([99, 98]);                       assert c["reason"] == "SL" and abs(c["roi"] + 2) < 1e-6, c
c = life([100.5, 101.2, 100]);            assert "BE" in c["reason"] and abs(c["roi"]) < 1e-6, c      # TP1 then back = breakeven
c = life([101.2, 102.3], target=2);       assert c["reason"].startswith("TP2") and abs(c["roi"] - 2) < 1e-6, c
c = life([103.5, 104.2, 108, 106.2, 105.9]);  assert c["reason"].startswith("TRAIL") and c["roi"] > 4, c   # held beyond TP4, trail = best - max(TP gap, signal risk)
c = life([103.5, 104.2, 106, 105.2, 104.9]);  assert c is None, c       # a normal bounce (smaller than the signal's own risk) must NOT stop the AI out after TP4
c = life([103.5, 104.2, 106, 105.2, 104.9], sl=99.6);  assert c["reason"].startswith("TRAIL"), c   # tiny-risk signal: the TP3->TP4 gap still rules (old behaviour)
c = life([99.0, 97.0], side="SELL", tps=(99, 98, 97, 96), sl=102)           # SELL short: price falls = profit
assert c is None or c["roi"] > 0 or c["reason"] == "SL"
c = life([99.5, 98.5, 97.5, 96.5, 95.5, 94.0, 95.0, 96.2], side="SELL", tps=(99, 98, 97, 96), sl=102)
assert c["roi"] > 3 and c["side"] == "SELL", c
print("exit ok")

# 4) hold-beyond-TP4 is switched OFF when it loses on its own trades
D._state["closed"] = [{"beyond_extra": -0.5, "roi": 3, "bot_id": i, "sym": "C", "side": "BUY", "t1": 0, "reason": "x"} for i in range(10)]
assert D._hold_beyond_on() is False
real = D._hold_beyond_on; D._hold_beyond_on = lambda: False
c = life([103.5, 104.1]);                 assert c["reason"] == "TP4", c; D._hold_beyond_on = real                              # now closes at TP4 like the bot
print("beyond-off ok")

# 5) end to end tick with fake bot + lab + price
D._state.update(open={}, closed=[], decisions=[], seen={}); D._loaded = True
now = 1_700_000_000.0
D._bot_open = lambda: [dict(bp, entry_price=100.0, opened_at_ts=now, invest_usdt=100.0)]
D._bot_closed = lambda: {}
D._price = lambda s: 100.2
D._labels_for = lambda *a: {"move": T, "z_tsi": BOTH}
X.lab_rows = lambda tf, lev, fee: hist
X.build = lambda tf="": {"scenarios": []}
D._tick()
assert len(D._state["decisions"]) == 1 and D._state["decisions"][0]["call"] == "LE" and len(D._state["open"]) == 1
# FAIR: the live price is 100.2 a few seconds later, but the AI trade must open at the BOT's exact entry 100.0
assert list(D._state["open"].values())[0]["entry"] == 100.0, D._state["open"]
print("entry fairness ok: AI entry == bot entry")
D._tick()
assert len(D._state["decisions"]) == 1          # the same bot trade is never decided twice
out = D.build()
assert out["calls"]["LE"] == 1 and out["open"][0]["sym"] == "C" and out["headline"]
print("tick+build ok:", out["headline"])

# 5b) bot-vs-AI money table: bot made +3 on a SKIPped signal's twin etc.
D._state.update(open={}, closed=[], decisions=[], seen={})
def dec(i, call, bpnl):
    return {"t": i, "bot_id": i, "sym": "C", "side": "BUY", "tf": "3m", "call": call, "why": "w", "cells": [], "px": 1,
            "inv": 100.0, "bot_roi": bpnl, "bot_pnl": bpnl}
D._state["decisions"] = [dec(1, "LE", -2.0), dec(2, "LE", 1.0), dec(3, "SKIP", -3.0), dec(4, "WAIT", 4.0), dec(5, "SKIP", -1.0), dec(6, "LE", None)]
D._state["closed"] = [{"bot_id": 1, "sym": "C", "side": "BUY", "tf": "3m", "roi": -1.0, "pnl": -1.0, "reason": "SL", "t1": 1, "hit": 0, "t0": 0, "why": ""},
                      {"bot_id": 2, "sym": "C", "side": "BUY", "tf": "3m", "roi": 2.5, "pnl": 2.5, "reason": "TRAIL", "t1": 1, "hit": 4, "t0": 0, "why": ""}]
D._bot_closed = lambda: {}
o = D.build()
assert o["signals"] == 6 and o["bot"]["traded"] == 6 and o["bot"]["closed"] == 5 and o["bot"]["open"] == 1
assert abs(o["bot"]["pnl"] - (-2 + 1 - 3 + 4 - 1)) < 1e-9
assert o["ai"]["traded"] == 3 and o["ai"]["closed"] == 2 and abs(o["ai"]["pnl"] - 1.5) < 1e-9
assert o["skipped"]["n"] == 3 and abs(o["skipped"]["bot_pnl"] - 0.0) < 1e-9
c = o["compare"]
assert c["n"] == 5 and abs(c["bot"] + 1.0) < 1e-9 and abs(c["ai"] - 1.5) < 1e-9 and abs(c["diff"] - 2.5) < 1e-9, c
assert abs(c["diff"] - (c["entry_effect"] + c["exit_effect"])) < 1e-9, c       # the two reasons add up to the total
print("money table ok:", o["headline"])

# 5c) scorecard: SKIP/WAIT + bot lost = RIGHT, SKIP/WAIT + bot won = WRONG, LE + AI lost = WRONG, LE + AI won = RIGHT
sc = o["scorecard"]
# decisions: 1 LE (AI -1.0 -> WRONG), 2 LE (AI +2.5 -> RIGHT), 3 SKIP bot -3 (RIGHT), 4 WAIT bot +4 (WRONG), 5 SKIP bot -1 (RIGHT), 6 LE open (skipped)
assert sc["n"] == 5 and sc["right"] == 3 and sc["wrong"] == 2 and abs(sc["right_pct"] - 60.0) < 1e-9, sc
assert {m["call"] for m in sc["mistakes"]} == {"LE", "WAIT"}, sc
print("scorecard ok:", sc["right"], "right /", sc["wrong"], "wrong")

# 6) persistence + reset
d = tempfile.mkdtemp(); D.init(d); D._mark(); D._save(force=True)
assert os.path.exists(os.path.join(d, "ai_desk.json"))
assert D.reset()["ok"] and not D._state["open"]
print("ALL OK")
