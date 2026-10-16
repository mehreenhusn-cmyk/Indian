"""ai_planner + scalp mode + plan skips in the coach - FAKE data, no network. Run: python3 test/test_ai_planner.py"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_planner as P, ai_coin_memory as M, ai_coach as C

tmp = tempfile.mkdtemp()
P._file_override = os.path.join(tmp, "p.json"); P._loaded = True
M._file_override = os.path.join(tmp, "m.json"); M._loaded = True
M._cfg = lambda: (10.0, 1.0)
CFG = {"leverage": 10, "fee_roi_pct": 0.0, "coach_enabled": True}
C._cfg = lambda n, d: CFG.get(n, d)
NOW = 1_800_000_000.0 + 3600            # one hour into a day (00:00 UTC = 5:30 IST)
day0 = P.day_start(NOW)
rec = lambda pnl, t=NOW - 100: {"pnl": pnl, "t1": t}

# 1) nothing set: takes every signal (no data = no reason to skip)
take, mode, why = P.check("AAAUSDT", "BUY", [], [], 0, "Watching", NOW)
assert take and mode == "HUNT" and not P.view([], [], NOW)["on"]
print("default ok")

# 2) hard rule 1: loss cap (closed + open) stops the day; yesterday's loss does not count
P.set_config(loss_cap_usdt=5, target_usdt=4, max_open=2)
assert P.check("A", "BUY", [rec(-3)], [(10, -10.0)], 0, "Learning", NOW)[0]                   # -3 + -1 = -4: still allowed
t, m, w = P.check("A", "BUY", [rec(-3)], [(10, -30.0)], 0, "Learning", NOW)                    # -3 + -3 = -6 <= -5
assert (not t) and m == "STOPPED" and "Loss cap" in w, (t, m, w)
P._day.update(start=0)
t, m, _ = P.check("A", "BUY", [rec(-9, day0 - 5000)], [], 0, "Learning", NOW)                  # the loss is from yesterday
assert t and m == "HUNT"
print("loss cap ok")

# 3) hard rule 2: max open trades
t, m, w = P.check("A", "BUY", [], [], 2, "Learning", NOW)
assert (not t) and "Max open" in w
print("max open ok")

# 4) target reached -> DONE: only Trusted coins; then give-back -> REST
P._day.update(start=0, peak=0.0)
t, m, _ = P.check("A", "BUY", [rec(4.5)], [], 0, "Learning", NOW)
assert (not t) and m == "DONE"
assert P.check("A", "BUY", [rec(4.5)], [], 0, "Trusted", NOW)[0]
t, m, w = P.check("A", "BUY", [rec(2.0)], [], 0, "Trusted", NOW)                              # 4.5 peak -> 2.0 = gave back >50%
assert (not t) and m == "REST", (m, w)
print("done/rest ok")

# 5) a new day starts fresh
P.check("A", "BUY", [], [], 0, "Trusted", NOW + 86400)
assert P._day["mode"] == "HUNT" and P._day["peak"] == 0.0
print("new day ok")

# 6) Avoid coin skipped with the reason; settings: negative rejected
P.set_config(loss_cap_usdt=0, target_usdt=0, max_open=0)
t, m, w = P.check("BADUSDT", "SELL", [], [], 0, "Avoid", NOW)
assert (not t) and "Avoid" in w
P.set_config(target_usdt=-5)
assert P.config()["target_usdt"] == 0
v = P.view([], [], NOW)
assert v["journal"] and "text" in v["journal"][0]
print("avoid + settings ok")

# 7) scalp: only AFTER the data says against-trend trades pay less
M._coins.clear(); M._ctx.clear()
assert M.ctx_verdict() == "COLLECTING"
for k in range(40):
    M.on_close("ZZZUSDT", 6.0, 10, "WITH", "w%d" % k); M.on_close("ZZZUSDT", -4.0, 10, "AGAINST", "a%d" % k)
assert M.ctx_verdict() == "WITH_BETTER"
bp = {"id": 7, "symbol": "ZZZUSDT", "action": "BUY", "signal_stop_loss": 99.0, "signal_tp1": 101.0, "signal_tp2": 102.0,
      "signal_tp3": 103.0, "signal_tp4": 104.0, "timeframe": "3m", "leverage": 10, "invest_usdt": 10.0, "opened_at_ts": time.time()}
v = C._new_trade(bp, 100.0)
v["scalp"] = True
C._state["open"] = {"7": v}
closed = C._step(v, 102.1, {}, {"7"})
assert closed and C._state["closed"][-1]["mode"] == "SCALP" and abs(C._state["closed"][-1]["exit_px"] - 102.0) < 1e-9
v2 = C._new_trade(bp, 100.0); v2["bot_id"] = 8                                                # not flagged: keeps running to TP4
C._state["open"] = {"8": v2}
assert C._step(v2, 102.1, {}, {"8"}) is False
M._ctx.clear()
assert M.ctx_verdict() == "COLLECTING"                                                       # no data -> never flagged
print("scalp ok")
print("ALL OK")

# 8) the coach really skips a bot signal when the day plan says no, and still opens it when it says yes
P._day.update(start=0, peak=0.0); P.set_config(loss_cap_usdt=1, target_usdt=0, max_open=0)
C._state.update({"open": {}, "closed": [{"pnl": -2.0, "t1": time.time(), "bot_id": 1, "roi": -20, "inv": 10}], "skips": [], "seen": {}, "memo": [], "cfg": {}})
bp2 = dict(bp, id=21, opened_at_ts=time.time(), entry_price=100.0)
C._copy_one(bp2, time.time(), {})
assert "21" not in C._state["open"] and C._state["skips"][-1].get("plan") is True, C._state
assert any("day plan" in str(m) for m in C._state["memo"])
P.set_config(loss_cap_usdt=0)                                                                   # plan off again
bp3 = dict(bp, id=22, opened_at_ts=time.time(), entry_price=100.0)
C._copy_one(bp3, time.time(), {})
assert "22" in C._state["open"]
mv = C._margin_view()
assert mv["plan_skipped"] == 1 and mv["skipped"] == 0
print("coach skip ok")
print("ALL OK 2")

# 9) revenge mirror: honest until enough trades, then compares; blocks nothing
mk = lambda t0, roi, sym="A": {"t0": t0, "t1": t0 + 60, "roi": roi, "sym": sym}
assert "Still collecting" in P.mirror([mk(1000, -5), mk(1100, 2)])["text"]
cl = []
for k in range(15):                                   # a loss, then 11 min later a calm trade (not "right after")
    cl += [mk(10000 + k * 5000, -5, "X"), mk(10000 + k * 5000 + 700, 3, "Y")]
for k in range(15):                                   # a loss, then a trade 2 min later that also loses
    cl += [mk(200000 + k * 5000, -5, "X"), mk(200000 + k * 5000 + 120, -6, "Z")]
m = P.mirror(cl)
assert m["after_loss"]["n"] >= 15 and "did worse" in m["text"], m
print("mirror ok")
