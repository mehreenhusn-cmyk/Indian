"""AI Coach logic test on FAKE data (no network, no bot). Run: python3 test/test_ai_coach.py"""
import os, sys, random, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_coach as C, ai_ind_features as F

CFG = {"leverage": 10, "fee_roi_pct": 0.0, "coach_enabled": True}
C._cfg = lambda n, d: CFG.get(n, d)
C._tf_min = lambda tf: 3
C._load(); C._file = None

def candles(n, drift, seed=1):
    r = random.Random(seed); p = 100.0; out = []
    for i in range(n):
        o = p; p = p * (1 + drift + r.uniform(-0.004, 0.004))
        out.append({"timestamp": 1_700_000_000_000 + i * 180000, "open": o, "high": max(o, p) * 1.001, "low": min(o, p) * 0.999, "close": p})
    return out

cs = candles(420, 0.0006); S = F.build(cs); i = S["n"] - 1
lb = C.labs_of(S, i, "BUY"); assert len(lb) >= 12 and "z_zone" in lb and "tsi_vs_sig" in lb, lb
sl = C.labs_of(S, i, "SELL"); assert sl.get("z_tsi") != lb.get("z_tsi") or sl.get("zma_vs_trade") != lb.get("zma_vs_trade")
ks = C._keys(lb); assert len(ks) == len(lb) + len(lb) * (len(lb) - 1) // 2          # singles + every pair

# 1) probabilities: AI discovers a bad and a good situation on its own; no verdict before the counts exist
bad = {"z_zone": "Z -1..+1s", "tsi_vs_sig": "TSI below signal", "z_tsi": "Z and TSI both AGAINST trade"}
good = {"z_zone": "Z -1..+1s", "tsi_vs_sig": "TSI above signal", "z_tsi": "Z and TSI both WITH trade"}
out, mode, _ = C.decide_exit(bad, 0.1); assert not out                           # little progress: nothing yet
out, mode, _ = C.decide_exit(bad, 0.5); assert out and mode == "BASIC"           # still collecting: basic rule
for k in range(60): C._count(good, k < 36, 0.3 if k < 36 else -0.3)              # 60% go my way
for k in range(60): C._count(bad, k < 12, 0.3 if k < 12 else -0.4)               # 20% go my way
out, mode, why = C.decide_exit(bad, 0.0); assert out and mode == "LEARNED" and "20%" in why, why
assert C.decide_exit(good, 0.9)[0] is False
L = C._learned(); assert L["worst"] and L["best"] and L["samples"] == 120 and L["worst"][0]["p"] == 20

# 2) a virtual trade: protect at 60% of the way to TP1, then SL on pullback; memo + watch written
bp = {"id": 7, "symbol": "TESTUSDT", "action": "BUY", "timeframe": "3m", "signal_stop_loss": 99.0, "signal_tp1": 102.0,
      "signal_tp2": 103.0, "signal_tp3": 104.0, "signal_tp4": 105.0, "leverage": 10, "invest_usdt": 100.0}
v = C._new_trade(bp, 100.0); C._state["open"]["7"] = v
assert C._step(v, 101.3, {}, {"7"}) is False and v["best"] == 101.3
v["be"] = False; assert 0.6 <= C._progress(v) <= 0.7
C.on_bar(v, S, i)                                       # protect rule fires inside on_bar
assert v["be"] is True and v["sl"] == 100.0
assert C._step(v, 99.9, {}, {"7"}) is True
rec = C._state["closed"][-1]; assert rec["reason"].startswith("SL at entry") and abs(rec["roi"]) < 0.01   # closes at the stop = entry
assert "7" in C._state["watch"] and any("closed:" in m["text"] for m in C._state["memo"])

# 3) pending samples resolve exactly FWD_BARS later; SELL counted relative to its own direction
n0 = C._state["stats"]["ALL"][0]
C._state["pending"].append({"sym": "X", "tf": "3m", "t": S["t"][-10], "side": "SELL", "px": S["c"][-10], "labs": good})
C.resolve_pending("X", "3m", S)
assert C._state["stats"]["ALL"][0] == n0 + 1 and not [s for s in C._state["pending"] if s["sym"] == "X"]

# 4) watch after exit
w = {"sym": "T", "side": "BUY", "tf": "3m", "px": S["c"][-30], "t1": S["t"][-30] / 1000.0, "lev": 10, "bot_id": 1}
n, b, wr = C.update_watch(w, S); assert n == C.WATCH_BARS and b >= wr
assert "early" in C._after_text(12, -1) and "good" in C._after_text(1, -9) and "neutral" in C._after_text(2, -2)

# 4b) SD event fact exists and flips with the trade side
assert "sd_event" in lb and ("WITH trade" in lb["sd_event"] or "AGAINST trade" in lb["sd_event"] or "no SD touch" in lb["sd_event"]), lb.get("sd_event")
ev_b, ev_s = C.sd_event(S, i, "BUY"), C.sd_event(S, i, "SELL")
if "no SD" not in str(ev_b):
    assert ("WITH" in ev_b) != ("WITH" in ev_s)

# 4c) margin: balance for 2 trades; 3rd signal frees a sideways trade, 4th is skipped
C._state["open"].clear(); C._state["closed"].clear(); C._state["skips"].clear(); C._state["cfg"] = {"balance": 200.0}
def mk(i_, age_min):
    b = dict(bp, id=100 + i_, symbol="S%dUSDT" % i_, invest_usdt=100.0)
    t = C._new_trade(b, 100.0); t["t0"] = time.time() - age_min * 60; C._state["open"][str(b["id"])] = t; return t
a_, b_ = mk(1, 45), mk(2, 5)
assert C._free(100.0) == 0.0
assert C.pick_victim({"S1USDT": 100.1, "S2USDT": 100.0}) is a_                  # old + flat = sideways, the young one is not
assert C.pick_victim({"S1USDT": 103.0, "S2USDT": 100.0}) is None                # old one is working (+30% roi at 10x) -> keep
C._close(a_, 100.1, "MARGIN: test", "MARGIN")
assert abs(C._free(100.0) - (100.0 + C._state["cfg"]["realized"])) < 1e-6
assert C._state["closed"][-1]["freed"] is True
v = C._margin_view(); assert v["slots"] == 2 and v["freed"] == 1 and v["per_trade"] == 100.0
assert C.set_balance(500)["balance"] == 500.0 and C._balance(100.0) == 500.0

# 5) page data builds
C._state["cfg"] = {}; d = C.build(); assert d["compare"]["n"] == 0 and d["learned"]["worst"] and d["memo"] and "ready" in d["compare"]
print("ai_coach ok")

# ---- Bot vs AI rows are driven by the BOT's trades (open + closed); AI copy or a reason why there is none
from recovered_bot import ai_path_logger as PL, trade_store as TS
_now = time.time(); _op = _now - 1800
_key = PL.make_key(7, _op)
PL.read_keys = lambda keys, max_lines=0: {_key: {"s": [[i * 15, i * 0.2, 0, 0] for i in range(100)], "levels": {"sl": -5, "tp1": 3}, "ind": [[15, 0.5, 10.0, 9.0]]}}
TS.get_recent_closed = lambda n, net=False: [{"id": 7, "symbol": "AAA", "action": "BUY", "timeframe": "3m", "leverage": 10, "entry_price": 100.0,
                                                "opened_at_ts": _op, "closed_at_ts": _op + 900, "status": "CLOSED_SL",
                                                "roi_pct": -4.0, "gross_roi_pct": -3.0, "pnl_usdt": -4.0}]
# bot holds 9 (AI has a copy) and 11 (opened before the AI was on -> no copy); 7 is closed (AI closed too)
C._bot_open_full = lambda: [
    {"id": 9, "symbol": "BBB", "action": "BUY", "entry_price": 100.0, "opened_at_ts": _now - 300, "timeframe": "3m", "leverage": 10, "ltp": 100.4},
    {"id": 11, "symbol": "CCC", "action": "SELL", "entry_price": 50.0, "opened_at_ts": _now - 5000, "timeframe": "3m", "leverage": 10, "ltp": 49.9}]
C._price_cached = lambda s: {"BBB": 100.5, "CCC": 49.9}.get(s)
C._state["cfg"]["started"] = _now - 3000
C._state["seen"] = {"9": _now - 290, "7": _op + 1}
C._state["skips"] = []
C._state["open"] = {"9": {"bot_id": 9, "sym": "BBB", "side": "BUY", "tf": "3m", "entry": 100.0, "lev": 10, "best": 100.2, "hit": 0,
                          "be": False, "mode": "BASIC", "inv": 100.0, "entry_ts": 0, "t0": _now - 300, "bot_opened": _now - 300,
                          "labs": {"z_zone": "Z high"}}}
C._state["closed"] = [{"bot_id": 7, "sym": "AAA", "side": "BUY", "tf": "3m", "roi": 1.5, "peak": 3, "reason": "x", "mode": "LEARNED",
                       "hit": 1, "t0": _op + 2, "t1": _op + 600, "inv": 100, "pnl": 1.5, "bot_roi": -4, "bot_pnl": -4.0,
                       "bot_opened": _op, "facts": ["Z up"], "entry": 100.0}]
pr = C._pairs()
by = {p["id"]: p for p in pr}
assert set(by) == {"9", "11", "7"}, list(by)
assert [p["id"] for p in pr][:2] in (["9", "11"], ["11", "9"]) and pr[-1]["id"] == "7", [p["id"] for p in pr]   # live rows first
n9 = by["9"]; assert n9["bot"]["state"] == "open" and n9["ai"]["state"] == "open" and n9["ai"]["roi"] is not None and n9["live"], n9
assert abs(n9["ai"]["peak"] - n9["ai"]["roi"]) < 1e-6 or n9["ai"]["peak"] >= n9["ai"]["roi"], n9["ai"]
n11 = by["11"]; assert n11["ai"]["state"] == "none" and "before the AI was switched on" in n11["ai"]["why"], n11["ai"]
c = by["7"]
assert c["bot"]["state"] == "closed" and c["bot"]["reason"] == "SL" and c["bot"]["exit_sec"] == 900, c["bot"]
assert c["ai"]["state"] == "closed" and c["ai"]["exit_sec"] == 600 and c["ai"]["facts"] == ["Z up"] and len(c["path"]) > 5 and c["levels"]["sl"] == -5, c
b = C.build()
assert "pairs" in b and "digest" in b and "ts" in b and "tick_age" in b
assert c["has_ind"] is True and isinstance(c["tags"], list)
rp = C.replay(7, _op)
assert rp["ok"] and rp["ind"] and rp["ai_exit"] == 600 and rp["levels"]["sl"] == -5, rp
# bulk price helper never raises and prefers the live feed
C._price_cached = lambda s: 1.0 if s == "X" else None
assert C._prices_for(["X"])["X"] == 1.0
print("pairs ok")

# ---- v9: fast copier, row status, "is the AI ready" meter, today digest, replay reason
C._state["open"].clear(); C._state["closed"].clear(); C._state["seen"].clear(); C._state["skips"].clear(); C._state["cfg"] = {}
_t = time.time()
nb = {"id": 21, "symbol": "NEWUSDT", "action": "SELL", "entry_price": 10.0, "signal_stop_loss": 10.5, "signal_tp1": 9.5, "signal_tp2": 9.0,
      "signal_tp3": 8.5, "signal_tp4": 8.0, "opened_at_ts": _t - 2.0, "timeframe": "3m", "leverage": 10, "invest_usdt": 100.0}
with C._lock:
    C._copy_new([nb], _t, {})                                     # no prices, no network: the copy still opens
assert "21" in C._state["open"] and C._state["open"]["21"]["entry"] == 10.0
assert 1.5 <= C._state["open"]["21"]["copy_after"] <= 2.5, C._state["open"]["21"]
with C._lock:
    C._copy_new([nb], _t + 1, {})                                 # same position again: never copied twice
assert len(C._state["open"]) == 1
old_nb = dict(nb, id=22, opened_at_ts=_t - 5000)                  # opened long before: not copied, but marked as seen
with C._lock:
    C._copy_new([old_nb], _t, {})
assert "22" not in C._state["open"] and "22" in C._state["seen"]
assert C._status({"state": "open"}, {"state": "open"})[0] == "both_running"
assert C._status({"state": "open"}, {"state": "closed"})[0] == "bot_running"
assert C._status({"state": "closed"}, {"state": "open"})[0] == "ai_running"
assert C._status({"state": "closed"}, {"state": "closed"})[0] == "both_closed"
assert C._status({"state": "open"}, {"state": "none"})[0] == "ai_waiting" and C._status({"state": "closed"}, {"state": "none"})[0] == "no_copy"
mk_ = lambda n, a, b: [{"pnl": a, "bot_pnl": b}] * n
assert C._ready_view(mk_(10, 1, 0), 10, 0, 10, 0)["level"] == "low"
assert C._ready_view(mk_(50, 1, 0), 50, 0, 50, 0)["level"] == "mid"
assert C._ready_view(mk_(120, 1, 0), 120, 0, 120, 0)["level"] == "good"
assert C._ready_view(mk_(120, -1, 0), -120, 0, 0, 0)["level"] == "mid"
mkp = lambda dt, a, b: {"t0": _t - dt, "ai": {"state": "closed", "roi": a}, "bot": {"state": "closed", "roi": b}, "tags": [["bad", "Bot gave back profit (x)"]]}
dg = C._digest([mkp(10, 2, 0), mkp(20, 1, 0), mkp(30, 0, 3)])
assert dg.startswith("Today: 3 finished signals. AI was better in 2, bot was better in 1.") and "Bot gave back profit" in dg, dg
assert C._digest([mkp(10, 2, 0)]).startswith("Last 1 finished signals"), C._digest([mkp(10, 2, 0)])
PL.read_keys = lambda keys, max_lines=0: {}
PL.open_path_full = lambda key: None
rp = C.replay(999, _now); assert rp["ok"] is False and "No price path" in rp["why"], rp
h = C.health(); assert "copier_ago_s" in h and h["open_ai_trades"] == 1
b2 = C.build(); assert b2["ready"]["need"] == 100 and "text" in b2["ready"]
print("v9 ok")
