"""Price Action Light (pa_layer.py): numbers, retest, verdict, log, report, read-only. No network.
Run: cd backend && python3 test_pa_layer.py"""
import copy, hashlib, json, os, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pa_layer as PA

ok = 0
def check(cond, msg):
    global ok
    assert cond, "FAIL: " + msg
    ok += 1

TF = 900_000
T0 = 1_700_000_000_000
def cndl(k, o, h, l, c):
    return {"timestamp": T0 + k * TF, "open": o, "high": h, "low": l, "close": c, "volume": 1.0}
def flat(n):                                   # price sits at 100, range 1 (EMA50 = 100)
    return [cndl(k, 100.0, 100.5, 99.5, 100.0) for k in range(n)]

# 1. EMA: seeded with the average, flat input stays flat, short input = no value
check(PA.ema([5.0] * 10, 50)[-1] is None, "too short")
check(abs(PA.ema([100.0] * 60, 50)[-1] - 100.0) < 1e-9, "flat ema")
check(PA.ema([1.0, 2.0, 3.0], 3)[2] == 2.0, "seed is the plain average")

# 2. features + verdict. BUY: previous candle high 100.5. Signal candle closes at its top, big tail below, breaks the previous high
cs = flat(70)
cs.append(cndl(70, 100.0, 101.2, 99.4, 101.2))
f = PA.features(cs, 70, 1)
check(f["close_pos"] == 1.0 and f["wick_against"] == 0.0 and f["wick_fav"] > 0.3 and f["broke_prev"] is True, "good buy candle %s" % f)
check(PA.verdict(f)[1] == "supports", "supports")
# weak buy: closes near the low with a long upper wick (sellers pushed back)
cs2 = flat(70) + [cndl(70, 100.0, 101.5, 99.8, 100.0)]
f2 = PA.features(cs2, 70, 1)
check(f2["wick_against"] >= 0.4 and f2["broke_prev"] is False and PA.verdict(f2)[1] == "against", "weak buy %s" % f2)
# SELL mirrors it
cs3 = flat(70) + [cndl(70, 100.0, 100.6, 98.8, 98.8)]
f3 = PA.features(cs3, 70, -1)
check(f3["close_pos"] == 1.0 and f3["broke_prev"] is True and PA.verdict(f3)[1] == "supports", "sell mirrors buy")
check(PA.features(flat(10), 5, 1) is None and PA.features(flat(70) + [cndl(70, 1, 1, 1, 1)], 70, 1) is None, "cannot measure = None")
check(PA.verdict({"close_pos": 0.5, "wick_fav": 0.1, "wick_against": 0.1, "broke_prev": False, "range_x": 1.0})[1] == "unclear", "unclear")

# 3. retest after the signal at index 70 (EMA stays about 100)
base = flat(70) + [cndl(70, 100.0, 101.2, 99.4, 101.2)]
held = base + [cndl(71, 101, 102, 100.9, 101.5), cndl(72, 101.5, 101.6, 99.9, 100.8)] + [cndl(73 + k, 101, 102, 100.8, 101.4) for k in range(5)]
r = PA.retest(held, 70, 1)
check(r["state"] == "held" and r["bars"] == 2, "held %s" % r)
broke = base + [cndl(71, 101, 101.2, 99.0, 99.2)] + [cndl(72 + k, 99, 99.5, 98.5, 99.0) for k in range(6)]
check(PA.retest(broke, 70, 1)["state"] == "broke", "broke through")
none = base + [cndl(71 + k, 101.5, 102.5, 101.2, 102.0) for k in range(7)]
check(PA.retest(none, 70, 1)["state"] == "none", "never came back")
check(PA.retest(base + [cndl(71, 101.5, 102.5, 101.2, 102.0)], 70, 1)["state"] == "pending", "pending, too few candles yet")
# a SELL retest looks upward
sell = flat(70) + [cndl(70, 100.0, 100.6, 98.8, 98.8), cndl(71, 98.8, 100.3, 98.5, 99.0)] + [cndl(72 + k, 99, 99.3, 98.6, 98.9) for k in range(6)]
check(PA.retest(sell, 70, -1)["state"] == "held", "sell retest held")

# 4. the log
def trade(i, sym="ETHUSDT", d=1, st="closed", net=5.0, age_s=600):
    ct = T0 + 70 * TF
    return {"id": "%s|15m|%d" % (sym, i), "s": sym, "f": "15m", "ct": ct, "t": ct + TF - 1, "d": d, "status": st, "net": net, "tg": {}}
now = (T0 + 70 * TF + TF) / 1000.0 + 600
calls = []
def fetch(sym, tf, n):
    calls.append(sym)
    return held
trades = [trade(1)]
snap = copy.deepcopy(trades)
log = {}
res = PA.process(trades, log, fetch, now=now)
row = log["rows"][trades[0]["id"]]
check(res["added"] == 1 and row["v"] == "supports" and row["rt"]["state"] == "held" and trades == snap, "one trade logged, Dual Bot trade untouched")
res = PA.process(trades, log, fetch, now=now)
check(res["added"] == 0 and len(calls) == 1, "second pass: nothing new, no download")
# pending retest finishes later
log2, early = {}, base + [cndl(71, 101.5, 102.5, 101.2, 102.0)]
PA.process([trade(2)], log2, lambda s, f, n: early, now=now)
check(log2["rows"][trade(2)["id"]]["rt"]["state"] == "pending", "pending first")
res = PA.process([trade(2)], log2, lambda s, f, n: held, now=T0 / 1000.0 + 100 * TF / 1000.0 + 10)
check(res["retests_done"] == 1 and log2["rows"][trade(2)["id"]]["rt"]["state"] == "held", "retest finished later")
# too old = ignored, candle missing = marked, fetch cap
old = trade(3); old["t"] = old["t"] - 4 * 86400 * 1000
check(PA.process([old], {}, fetch, now=now)["added"] == 0, "older than 3 days ignored")
miss_log = {}
PA.process([trade(4)], miss_log, lambda s, f, n: flat(60), now=now)
check(miss_log.get("rows") == {}, "fresh trade whose candle is not there yet is retried later, not marked")
many = [trade(i, sym="C%dUSDT" % i) for i in range(30)]
calls.clear()
PA.process(many, {}, fetch, now=now, max_fetch=4)
check(len(calls) == 4, "at most max_fetch downloads per pass")
big = {"rows": {"k%d" % i: {"t": i, "v": "unclear"} for i in range(PA.KEEP_ROWS + 5)}, "since": 1}
PA.process([], big, fetch, now=now)
check(len(big["rows"]) == PA.KEEP_ROWS, "log is capped")

# 5. report. Planted rule: 'supports' trades win +10 / lose -5 at 75%; 'against' win 25%. Margin 100 USDT -> net 10 = +10 USDT
import random
random.seed(3)
rtr, rlog = [], {"rows": {}, "since": now - 3 * 86400}
for i in range(240):
    v = ("supports", "against", "unclear")[i % 3]
    win = random.random() < {"supports": 0.75, "against": 0.25, "unclear": 0.5}[v]
    t = trade(1000 + i, net=10.0 if win else -5.0)
    t["t"] = T0 + i * 1000
    rtr.append(t)
    rlog["rows"][t["id"]] = {"v": v, "rt": {"state": ("held", "broke", "none")[i % 3]}, "t": t["t"]}
rep = PA.report(rtr, rlog, now=now)
g = {x["key"]: x for x in rep["verdicts"]}
check(rep["status"] == "ready" and rep["judged"] == 240 and rep["logged"] == 240 and rep["days"] == 3.0, "ready numbers")
check(g["supports"]["n"] == 80 and g["supports"]["avg"] > 4 and g["against"]["avg"] < 0 and rep["edge"] > 5, "planted rule found %s" % rep["edge"])
check(rep["steady"] is True and "agree" in rep["text"], "both halves agree")
check(sum(x["n"] for x in rep["retests"]) == 240, "retest groups cover every trade")
rep2 = PA.report(rtr[:30], rlog, now=now)
check(rep2["status"] == "collecting" and "Collecting" in rep2["text"], "collecting when few")
check(PA.report([dict(t, status="open") for t in rtr], rlog, now=now)["judged"] == 0, "only finished trades count")

# 6. read-only: Dual Bot's file is byte-for-byte the same after a full pass; we write only our own files
d = PA._dir()
dual = os.path.join(d, "dual_lab_data.json")
json.dump({"rows": {}, "trades": [trade(77)]}, open(dual, "w"))
before = hashlib.md5(open(dual, "rb").read()).hexdigest()
tr = PA.read_trades()
lg = {}
PA.process(tr, lg, fetch, now=now)
PA._save(PA.LOG_NAME, lg)
check(len(tr) == 1 and hashlib.md5(open(dual, "rb").read()).hexdigest() == before, "Dual Bot file untouched")
check(os.path.exists(os.path.join(d, PA.LOG_NAME)), "own log written")
check(PA.status()["running"] is False, "status without a worker")
print("price action layer: %d checks passed" % ok)
