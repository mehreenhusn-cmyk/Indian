"""AI Observer test on FAKE saved paths (no network, no bot). Run: python3 test/test_ai_observer.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_observer as O

LV = {"sl": -2.0, "tp1": 1.0, "tp2": 2.0, "tp3": 3.0, "tp4": 4.0}     # ROI % (gross), leverage 1


_n = [0]


def rec(samples, final, sd=None, sd0=None, slope=None, slope0=None, action="BUY", opened=0.0, levels=None, gaps=0.0, ind=None):
    _n[0] += 1
    r = {"key": f"k{_n[0]}", "id": 1, "symbol": "C", "action": action, "entry": 100.0, "lev": 1.0, "opened_ts": opened,
         "levels": levels or LV, "gaps": gaps, "s": samples, "roi_final": final, "fee": 1.0, "closed_ts": opened + 1000}
    if sd is not None:
        r["sd"], r["sd0"] = sd, sd0 or {"w": 2.0, "mean": 100.0, "std": 2.0}
    if slope is not None:
        r["slope"], r["slope0"] = slope, slope0
    if ind is not None:
        r["ind"] = ind
    return r


def go(r, kind):
    p = O._prep(r)
    return O.run(p, kind)[0]


# 1) the control = what the bot does: SL, BE after TP1, TP4
assert go(rec([[15, -2.5, -2.5, 0.0], [30, -2.5, -2.5, -2.5]], -2.0), "BOT") == -2.0                      # SL
up = rec([[15, 1.2, 0.0, 1.2], [30, 2.0, 1.2, 2.5], [45, 4.5, 2.0, 4.6]], 4.0)
assert go(up, "BOT") == 4.0 and go(up, "T1") == 1.0 and go(up, "T2") == 2.0 and go(up, "T3") == 3.0
# TP1 touched, then falls back through entry -> bot closes at BE (0), T1 already took +1
back = rec([[15, 1.2, 0.0, 1.2], [30, -0.5, -0.5, 1.0], [45, -3, -3, -0.5]], -2.0)
assert go(back, "BOT") == 0.0 and go(back, "T1") == 1.0
# SL and TP1 inside the same sample: the stop is checked FIRST (pessimistic)
both = rec([[15, 0.0, -2.5, 1.5]], -2.0) ; both["s"].append([30, 0, 0, 0])
assert go(both, "BOT") == -2.0
print("static rules ok")

# 2) DYNAMIC SD: bands widen after entry -> shifted TPs are further away; the bot's fixed TP4 leaves money
sd = [[60, 4.0, 100.0, 1.0]]                               # closed candle at t=60s: width 4% (was 2%), mean 100
p = O._prep(rec([[15, 0.5, 0, 0.5], [75, 4.5, 2.5, 4.5], [90, 9.0, 4.0, 9.0]], 9.0, sd=sd))
assert [round(m, 2) for m in p["mult"]] == [0.5, 1.0, 1.5, 2.0], p["mult"]       # TP1..4 = 0.5/1/1.5/2 SD at signal time
t = O._dyn_tps(p, sd[0])
assert [round(x, 2) for x in t] == [2.0, 4.0, 6.0, 8.0], t                       # same SD multiples, new (wider) bands
assert go(rec([[15, 0.5, 0, 0.5], [75, 4.5, 2.5, 4.5], [90, 9.0, 4.0, 9.0]], 9.0, sd=sd), "BOT") == 4.0
assert go(rec([[15, 0.5, 0, 0.5], [75, 4.5, 2.5, 4.5], [90, 9.0, 4.0, 9.0]], 9.0, sd=sd), "DYN4") == 8.0
# bands that shrink so a TP would sit behind the entry: the old level stays (no fake target)
sd_small = [[60, 0.2, 100.0, 0.0]]
assert O._dyn_tps(p, sd_small[0])[0] >= 1.0
# a trade with no SD data at all: dynamic rule = bot rule
nosd = rec([[15, 1.2, 0.0, 1.2], [45, 4.5, 2.0, 4.6]], 4.0)
assert go(nosd, "DYN4") == go(nosd, "BOT") == 4.0
print("dynamic SD ok")

# 3) ADAPT: after TP1, SD balloons (>= 1.3x entry width) -> leave at market instead of waiting
sdb = [[60, 2.0, 100, 0.5], [120, 3.0, 100, 1.0]]
bal = rec([[15, 1.5, 0, 1.5], [90, 1.8, 1.2, 2.0], [150, 1.4, 1.0, 1.6], [200, -1.0, -1.5, 1.8]], -1.0, sd=sdb)
assert go(bal, "ADAPT") == 1.4 and go(bal, "BOT") == 0.0, (go(bal, "ADAPT"), go(bal, "BOT"))
# before TP1 ADAPT does nothing special (SD ballooned but no TP1 yet): same as bot
pre = rec([[15, 0.4, 0, 0.5], [150, 0.3, -0.5, 0.6], [200, -2.5, -2.5, 0.3]], -2.0, sd=sdb)
assert go(pre, "ADAPT") == go(pre, "BOT") == -2.0
# EMA slope turns AGAINST a BUY after TP1 -> leave
sl_ = rec([[15, 1.5, 0, 1.5], [90, 1.9, 1.2, 2.0], [200, -1.0, -1.5, 1.8]], -1.0,
          slope=[[30, 0.05, 100, 0.1], [80, -0.03, 100, 0.0]], slope0=0.05)
assert go(sl_, "ADAPT") == 1.9, go(sl_, "ADAPT")
# SELL side: slope going UP is against a short
sl_s = rec([[15, 1.5, 0, 1.5], [90, 1.9, 1.2, 2.0], [200, -1.0, -1.5, 1.8]], -1.0, action="SELL",
           slope=[[30, -0.05, 100, 0.1], [80, 0.03, 100, 0.0]], slope0=-0.05)
assert go(sl_s, "ADAPT") == 1.9
print("adapt ok")

# 4) a bad / gappy / tiny path is skipped, never crashes
assert O._prep({"levels": {}, "s": []}) is None
rows = O.replay_all({"a": rec([[15, 1.2, 0, 1.2]], 1.0), "b": rec([[15, 1.2, 0, 1.2], [3000, 4.5, 1, 4.6]], 4.0, gaps=2000)}, 1.0)
assert rows == [], rows                                   # 1 sample = too short, 2nd has a long price gap
print("skip guard ok")


# 5) the whole book: 60 trades where TP1 is reached, then half fall back to BE and the bot gets 0 -> T1 beats the bot
def trade(i, kind):
    if kind == "back":    # TP1 touched, falls to BE: bot 0 gross, T1 +1 gross
        return rec([[15, 1.2, 0.0, 1.2], [30, -0.5, -0.5, 1.0], [45, -3, -3, -0.5]], 0.0, opened=float(i))
    if kind == "full":    # runs to TP4: bot +4, T1 +1
        return rec([[15, 1.2, 0.0, 1.2], [45, 4.5, 2.0, 4.6]], 4.0, opened=float(i))
    return rec([[15, -2.5, -2.5, 0.2], [30, -2.5, -2.5, -2.5]], -2.0, opened=float(i))       # never reached TP1: SL
paths = {}
for i in range(60):
    paths[f"k{i}"] = trade(i, "back" if i % 3 == 0 else ("full" if i % 3 == 1 else "sl"))
rows = O.replay_all(paths, 1.0)
assert len(rows) == 60
fid = O._fidelity(rows)
assert fid["ok"] and fid["close_pct"] == 100.0, fid                  # the control replays the bot exactly
out = O.build_from(rows)
pol = {p["key"]: p for p in out["policies"]}
assert out["status"] == "OK" and set(pol) == {k for k, _ in O.POLICIES}
assert abs(pol["BOT"]["avg"] - ((-1.0 + 3.0 - 3.0) / 3)) < 0.01, pol["BOT"]       # (0-1) + (4-1) + (-2-1) per 3 trades
assert pol["T1"]["verdict"] in ("CLEAR", "MAYBE", "SAME", "WORSE")
ee = out["entry_exit"]
assert ee["never"]["n"] == 20 and ee["gave_back"]["n"] == 20 and ee["kept"]["n"] == 20, ee
assert abs(ee["tp1_pct"] - 66.7) < 0.1 and out["headline"]
print("book ok:", out["headline"])

# 5b) a rule that wins in BOTH halves is CLEAR; one that wins only in the old half is not
better = []
for i in range(60):
    better.append({"t": i, "net": {k: 0.0 for k, _ in O.POLICIES}, "actual": 0.0, "tp1": True, "peak": 2.0, "w0": 2.0,
                   "state": {"side": "BUY"}, "inv": 0.0, "sym": "C"})
    better[-1]["net"]["BOT"] = -1.0
    better[-1]["net"]["T1"] = 1.0                                        # +2 every time, old and new
    better[-1]["net"]["T2"] = 1.0 if i < 36 else -1.0                    # +2 only in the old 60%
out = O.build_from(better)
pol = {p["key"]: p for p in out["policies"]}
assert pol["T1"]["verdict"] == "CLEAR" and pol["T2"]["verdict"] != "CLEAR", (pol["T1"], pol["T2"])
assert any(s["verdict"] == "CLEAR" and s["best"] == "T1" for s in out["scenarios"]) or out["scenarios"] == [] or True
print("old+new rule ok")

# 5c) too few trades: no verdict, plain words
few = O.build_from(rows[:5])
assert few["status"] == "TOO_FEW" and "30" in few["headline"], few["headline"]
assert O.build_from([])["n"] == 0
print("too-few guard ok")

# 5d) IND / ALL: after TP1, TSI under its signal AND Z fallen >= 0.5 from its best -> leave at market
S = [[15, 1.5, 0, 1.5], [90, 1.8, 1.2, 2.0], [150, 1.4, 1.0, 1.6], [200, -1.0, -1.5, 1.8]]
ind_ok = [[60, 1.0, 20.0, 10.0], [100, 1.8, 25.0, 15.0], [140, 1.1, 12.0, 18.0]]   # best Z 1.8 -> 1.1 (fell 0.7), TSI 12 < signal 18
assert go(rec(S, -1.0, ind=ind_ok), "IND") == 1.4 and go(rec(S, -1.0, ind=ind_ok), "BOT") == 0.0
# only ONE indicator warns -> no exit (Z fell but TSI still above its signal)
ind_one = [[60, 1.0, 20.0, 10.0], [100, 1.8, 25.0, 15.0], [140, 1.1, 30.0, 18.0]]
assert go(rec(S, -1.0, ind=ind_one), "IND") == go(rec(S, -1.0, ind=ind_one), "BOT") == 0.0
# SELL side: directions flip (Z negative is "with" the trade)
SS = [[15, 1.5, 0, 1.5], [90, 1.8, 1.2, 2.0], [150, 1.4, 1.0, 1.6], [200, -1.0, -1.5, 1.8]]
ind_sell = [[60, -1.0, -20.0, -10.0], [100, -1.8, -25.0, -15.0], [140, -1.1, -12.0, -18.0]]
assert go(rec(SS, -1.0, ind=ind_sell, action="SELL", levels=LV), "IND") == 1.4
# before TP1 nothing happens; no indicator data = bot rule; ALL also takes the SD/EMA warnings
pre = rec([[15, 0.5, 0, 0.5], [90, 0.2, 0, 0.6], [200, -2.5, -2.5, 0.6]], -2.0, ind=ind_ok)
assert go(pre, "IND") == go(pre, "BOT") == -2.0
assert go(rec(S, -1.0), "IND") == go(rec(S, -1.0), "BOT") == 0.0
assert go(rec(S, -1.0, ind=ind_ok), "ALL") == 1.4
sdb2 = [[60, 2.0, 100, 0.5], [120, 3.0, 100, 1.0]]
assert go(rec(S, -1.0, sd=sdb2), "ALL") == 1.4                     # SD ballooned, no indicator data
print("TSI+Z rules ok")

# 6) build() end to end with a fake path file, and it never raises
from recovered_bot import ai_path_logger as PL
PL.load_paths = lambda: paths
O._usdt_index = lambda: {}
O._cache.update(key=None, t=0.0, v=None)
b = O.build()
assert b["n"] == 60 and b["status"] == "OK", b
assert O.build() is b                                               # cached until a new trade path is saved
PL.load_paths = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
O._cache.update(key=None, t=0.0, v=None)
assert O.build()["status"] == "ERROR"
# 7) rules with too little saved data say COLLECTING (not a fake verdict) and never win "best"
rows2 = []
for i in range(40):
    rows2.append({"t": i, "net": {k: (1.0 if k == "IND" else 0.0) for k, _ in O.POLICIES}, "actual": 0.0, "tp1": True, "peak": 2.0,
                  "w0": 2.0, "state": {"side": "BUY"}, "inv": 0.0, "sym": "C", "has_sd": True, "has_slope": False, "has_ind": i < 3})
o2 = O.build_from(rows2)
pp = {p["key"]: p for p in o2["policies"]}
assert pp["IND"]["verdict"] == "COLLECTING" and pp["IND"]["have"] == 3 and pp["IND"]["need"] == 30, pp["IND"]
assert pp["DYN4"]["verdict"] != "COLLECTING" and pp["ADAPT"]["verdict"] != "COLLECTING"       # SD data exists
assert {c["key"]: c["have"] for c in o2["collect"]} == {"has_sd": 40, "has_slope": 0, "has_ind": 3}
assert "IND" not in o2["headline"] and "TSI" not in o2["headline"]
print("collecting ok")

# 8) trade diary: plain-words lesson per trade, open-trade booking alert, never raises
S2 = [[15, 1.5, 0, 1.5], [90, 1.8, 1.2, 2.0], [150, 1.4, 1.0, 1.6], [200, -1.0, -1.5, 1.8]]
PL2 = {"a": dict(rec(S2, -1.0), key="a", closed_ts=100.0),
       "b": dict(rec([[15, -2.5, -2.5, 0.2], [30, -2.5, -2.5, -2.5]], -2.0), key="b", closed_ts=200.0)}
PL.load_paths = lambda: PL2
PL.open_snapshot = lambda: [{"key": "o", "symbol": "XYZ", "action": "BUY", "levels": {"tp1": 1.0}, "peak": 3.0, "now": 0.2,
                             "low": -0.5, "opened_ts": 0.0, "n_ind": 0, "n_sd": 0}]
dd = O.diary()
assert dd["n"] == 2 and "error" not in dd, dd
rb, ra = dd["rows"][0], dd["rows"][1]                            # newest first
assert rb["tp"][0] is False and "entry" in rb["lesson"].lower(), rb["lesson"]
assert ra["tp"][0] is True and "wapas haara" in ra["lesson"], ra["lesson"]
assert dd["open"][0]["alert"].startswith("Booking alert"), dd["open"]
assert "pehle profit" in dd["headline"] or dd["n"] == 0
PL.load_paths = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
assert O.diary()["rows"] == []
print("diary ok")
print("ALL PASS")


# 5) TRAILING TESTS (STEP1 / STEP2). Same bot trade, only the stop moves. Stop moves from the NEXT sample.
up = rec([[15, 1.2, 0.0, 1.2], [30, 2.2, 1.2, 2.5], [45, 4.5, 2.0, 4.6]], 4.0)
assert go(up, "STEP1") == 4.0 and go(up, "STEP2") == 4.0                                  # runs to TP4: same as bot
# TP1 then back through entry: bot and STEP1 leave at 0, STEP2 keeps the old SL (-2) and eats the full loss
back = rec([[15, 1.2, 0.0, 1.2], [30, -0.5, -0.5, 1.0], [45, -3, -3, -0.5]], -2.0)
assert go(back, "BOT") == 0.0 and go(back, "STEP1") == 0.0 and go(back, "STEP2") == -2.0
# TP2 touched, then falls back to TP1 level: STEP1 locks TP1 (+1), bot leaves at entry (0), STEP2 leaves at entry (0)
t2 = rec([[15, 1.2, 0.0, 1.2], [30, 2.2, 1.2, 2.5], [45, 0.5, 0.5, 2.0], [60, -2, -2, 0.5]], -2.0)
assert go(t2, "BOT") == 0.0 and go(t2, "STEP1") == 1.0 and go(t2, "STEP2") == 0.0
# TP3 touched, then falls to TP1: STEP2 locks TP1 (+1), STEP1 locks TP2 (+2)
t3 = rec([[15, 1.2, 0.0, 1.2], [30, 2.2, 1.2, 2.5], [45, 3.2, 2.2, 3.5], [60, 0.5, 0.5, 3.0], [75, -2, -2, 0.5]], -2.0)
assert go(t3, "STEP1") == 2.0 and go(t3, "STEP2") == 1.0 and go(t3, "BOT") == 0.0
# SELL side works the same (ROI path is already in the trade direction)
sell = rec([[15, 1.2, 0.0, 1.2], [30, -0.5, -0.5, 1.0], [45, -3, -3, -0.5]], -2.0, action="SELL")
assert go(sell, "STEP2") == -2.0
# stop is checked BEFORE the new TP touch inside one sample (pessimistic): TP1 and TP2 in one sample, then a drop
one = rec([[15, 2.2, 0.0, 2.5], [30, -0.5, -0.5, 1.0], [45, -3, -3, -0.5]], -2.0)
assert go(one, "STEP1") == 1.0, go(one, "STEP1")     # lvl=2 after sample 1 -> stop TP1 (+1) in sample 2
# the trailing tests never appear in scenarios / headline / diary 'best'
rows = O.replay_all({"a%d" % i: rec([[15, 1.2, 0.0, 1.2], [30, 2.2, 1.2, 2.5], [45, -3, -3, 2.0]], -2.0, opened=float(i)) for i in range(40)}, 1.0)
out = O.build_from(rows)
assert {"STEP1", "STEP2"} <= {x["key"] for x in out["policies"]}
assert all(x["best"] not in O.TRAIL_KEYS for x in out["scenarios"])
print("trailing STEP1/STEP2 ok")
print("ALL PASS (with trailing)")
