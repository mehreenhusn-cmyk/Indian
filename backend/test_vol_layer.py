"""Volume Context (vol_layer.py): numbers, follow-through, verdict, log, report, read-only, Brain status. No network.
Run: cd backend && python3 test_vol_layer.py"""
import copy, hashlib, json, os, random, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vol_layer as VL
import smart_brain as SB

ok = 0
def check(cond, msg):
    global ok
    assert cond, "FAIL: " + msg
    ok += 1

TF = 900_000
T0 = 1_700_000_000_000
def cndl(k, v, o=100.0, c=100.0):
    return {"timestamp": T0 + k * TF, "open": o, "high": max(o, c) + 0.5, "low": min(o, c) - 0.5, "close": c, "volume": v}
def quiet(n, v=100.0):
    return [cndl(k, v) for k in range(n)]

# 1. levels: signal at index 40, normal volume = 100
def at(v, o=100.0, c=101.0):
    return quiet(40) + [cndl(40, v, o, c)]
check(VL.features(at(100), 40, 1)["level"] == "normal", "normal")
check(VL.features(at(150), 40, 1)["level"] == "high" and VL.features(at(150), 40, 1)["vol_x"] == 1.5, "high")
check(VL.features(at(50), 40, 1)["level"] == "low", "low")
check(VL.features(at(400), 40, 1)["level"] == "climax", "climax")
check(VL.features(at(100), 10, 1) is None and VL.features(quiet(41, 0.0), 40, 1) is None, "cannot measure = None")

# 2. trend of the last 3 candles vs the 3 before, and candle direction
busy = quiet(37) + [cndl(37, 100), cndl(38, 100), cndl(39, 100), cndl(40, 130), cndl(41, 160)]
cs = quiet(38) + [cndl(38, 120), cndl(39, 140), cndl(40, 180, 100, 101)]
check(VL.features(cs, 40, 1)["trend"] == "rising" and VL.features(cs, 40, 1)["with_trade"] is True, "rising, buy candle closed up")
dead = quiet(37) + [cndl(37, 100), cndl(38, 100), cndl(39, 100), cndl(40, 40)]
cs = quiet(37, 200.0) + [cndl(37, 100), cndl(38, 90), cndl(39, 80), cndl(40, 60, 101, 100)]
check(VL.features(cs, 40, 1)["trend"] == "falling" and VL.features(cs, 40, 1)["with_trade"] is False, "falling, buy candle closed down")
check(VL.features(at(100, 101.0, 100.0), 40, -1)["with_trade"] is True, "sell candle closed down")

# 3. follow-through: next 3 candles vs signal candle
base = at(100)
check(VL.follow(base + [cndl(41, 150), cndl(42, 150), cndl(43, 150)], 40) == {"state": "building", "x": 1.5}, "building")
check(VL.follow(base + [cndl(41, 40), cndl(42, 40), cndl(43, 40)], 40)["state"] == "fading", "fading")
check(VL.follow(base + [cndl(41, 100), cndl(42, 100), cndl(43, 100)], 40)["state"] == "steady", "steady")
check(VL.follow(base + [cndl(41, 150)], 40)["state"] == "pending", "pending")

# 4. verdict
good = {"level": "high", "trend": "rising", "with_trade": True}
bad = {"level": "low", "trend": "falling", "with_trade": False}
check(VL.verdict(good) == (3, "supports") and VL.verdict(bad) == (-3, "against"), "verdict ends")
check(VL.verdict({"level": "climax", "trend": "flat", "with_trade": True})[1] == "unclear", "climax is not good news")
check(VL.verdict({"level": "normal", "trend": "flat", "with_trade": True})[1] == "unclear", "unclear")

# 5. the log
def trade(i, sym="ETHUSDT", d=1, st="closed", net=5.0):
    ct = T0 + 40 * TF
    return {"id": "%s|15m|%d" % (sym, i), "s": sym, "f": "15m", "ct": ct, "t": ct + TF - 1, "d": d, "status": st, "net": net, "tg": {}}
now = (T0 + 41 * TF) / 1000.0 + 600
full = at(150) + [cndl(41, 200), cndl(42, 200), cndl(43, 200), cndl(44, 200)]
calls = []
def fetch(s, f, n):
    calls.append(s)
    return full
trades, snap, log = [trade(1)], None, {}
snap = copy.deepcopy(trades)
r = VL.process(trades, log, fetch, now=now)
row = log["rows"][trades[0]["id"]]
check(r["added"] == 1 and row["f_"]["level"] == "high" and row["fw"]["state"] == "building" and trades == snap, "one trade logged, Dual Bot trade untouched")
check(VL.process(trades, log, fetch, now=now)["added"] == 0 and len(calls) == 1, "second pass: nothing new, no download")
early, log2 = at(150) + [cndl(41, 150)], {}
VL.process([trade(2)], log2, lambda s, f, n: early, now=now)
check(log2["rows"][trade(2)["id"]]["fw"]["state"] == "pending", "pending first")
r = VL.process([trade(2)], log2, lambda s, f, n: full, now=T0 / 1000.0 + 100 * TF / 1000.0)
check(r["follow_done"] == 1 and log2["rows"][trade(2)["id"]]["fw"]["state"] == "building", "follow-through finished later")
old = trade(3); old["t"] -= 4 * 86400 * 1000
check(VL.process([old], {}, fetch, now=now)["added"] == 0, "older than 3 days ignored")
ml = {}
VL.process([trade(4)], ml, lambda s, f, n: quiet(30), now=now)
check(ml.get("rows") == {}, "fresh trade whose candle is not there yet is retried later")
calls.clear()
VL.process([trade(i, sym="C%dUSDT" % i) for i in range(30)], {}, fetch, now=now, max_fetch=4)
check(len(calls) == 4, "at most max_fetch downloads per pass")

# 6. report. Planted rule: 'supports' trades win 75% (+10 / -5), 'against' 25%
random.seed(5)
rt, rl = [], {"rows": {}, "since": now - 2 * 86400}
for i in range(240):
    v = ("supports", "against", "unclear")[i % 3]
    win = random.random() < {"supports": 0.75, "against": 0.25, "unclear": 0.5}[v]
    t = trade(1000 + i, net=10.0 if win else -5.0)
    t["t"] = T0 + i * 1000
    rt.append(t)
    rl["rows"][t["id"]] = {"v": v, "t": t["t"], "f_": {"level": ("low", "normal", "high", "climax")[i % 4]}, "fw": {"state": ("building", "steady", "fading")[i % 3]}}
rep = VL.report(rt, rl, now=now)
g = {x["key"]: x for x in rep["verdicts"]}
check(rep["status"] == "ready" and rep["judged"] == 240 and rep["days"] == 2.0, "ready")
check(g["supports"]["n"] == 80 and rep["edge"] > 5 and rep["steady"] is True and "agree" in rep["text"], "planted rule found %s" % rep["edge"])
check(sum(x["n"] for x in rep["levels"]) == 240 and sum(x["n"] for x in rep["follows"]) == 240, "level and follow groups cover every trade")
check(VL.report(rt[:30], rl, now=now)["status"] == "collecting", "collecting when few")
check(VL.report([dict(t, status="open") for t in rt], rl, now=now)["judged"] == 0, "only finished trades count")

# 7. read-only + Brain status shows both layers
d = VL.PA._dir()
dual = os.path.join(d, "dual_lab_data.json")
json.dump({"rows": {}, "trades": [trade(77)]}, open(dual, "w"))
before = hashlib.md5(open(dual, "rb").read()).hexdigest()
tr, lg = VL.read_trades(), {}
VL.process(tr, lg, fetch, now=now)
VL._save(VL.LOG_NAME, lg)
check(hashlib.md5(open(dual, "rb").read()).hexdigest() == before and os.path.exists(os.path.join(d, VL.LOG_NAME)), "Dual Bot file untouched, own log written")
VL._save(VL.VIEW_NAME, {"beat": now, "report": {"status": "collecting"}})
import time as _t
VL._save(VL.VIEW_NAME, {"beat": _t.time(), "report": {"status": "collecting", "text": "x"}})
ly = SB.status()["layers"]
check(ly["vol"]["running"] is True and ly["vol"]["report"]["text"] == "x" and ly["pa"]["running"] is False and ly["pa"]["report"] is None, "Brain status shows both layers")
check(VL.status()["running"] is True, "layer status")
print("volume layer: %d checks passed" % ok)
