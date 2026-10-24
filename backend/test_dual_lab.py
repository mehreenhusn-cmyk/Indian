"""Dual Bot (dual_lab.py): ridge model, signals, paper trades, worker cycle on a FAKE market (no network). Run: cd backend && python3 test_dual_lab.py"""
import math, os, random, sys, tempfile, time
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dual_lab as D
import filter_lab as FL
import tag_lab as TL

ok = 0
def check(cond, msg):
    global ok
    assert cond, "FAIL: " + msg
    ok += 1

# 1. the linear solver
x = D._solve([[2.0, 1.0], [1.0, 3.0]], [[5.0, 1.0], [10.0, 0.0]])
check(abs(x[0][0] - 1.0) < 1e-9 and abs(x[1][0] - 3.0) < 1e-9, "solve")

# 2. the model learns a planted rule: feature a=1 earns +10, a=0 earns -10 (exit 0); exit 1 is always -3
random.seed(5)
samples = []
for k in range(400):
    a = random.choice(("a=1", "a=0"))
    samples.append((k, [a, random.choice(("b=1", "b=2", "b=3"))], [(10 if a == "a=1" else -10) + random.gauss(0, 3), -3 + random.gauss(0, 3)]))
mod = D.fit([(f, n) for _, f, n in samples], 2)
p1, p0 = D.predict(mod, ["a=1", "b=2"]), D.predict(mod, ["a=0", "b=2"])
check(p1[0] > 7 and p0[0] < -7 and abs(p1[1] + 3) < 2, "ridge finds the planted rule")

# 3. a fake market: random-walk candles that end on the newest closed candle
def candles(tf, n, seed):
    rnd = random.Random(seed)
    step = FL.TF_MS[tf]
    latest = (int(time.time() * 1000) // step) * step - step
    p, out = 100.0, []
    for k in range(n):
        o = p
        p = max(1.0, p * (1 + rnd.gauss(0, 0.004) + 0.0008 * math.sin(k / 30.0)))
        out.append({"timestamp": latest - (n - 1 - k) * step, "open": o, "high": max(o, p) * 1.001, "low": min(o, p) * 0.999, "close": p, "volume": 1.0})
    return out

COINS = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
seedof = lambda sym, tf: sum(map(ord, sym + tf))
def fetch_range(sym, tf, start):
    return candles(tf, int((time.time() * 1000 - start) / FL.TF_MS[tf]) + 1, seedof(sym, tf))
def fetch_limit(sym, tf, limit):
    return candles(tf, limit, seedof(sym, tf))[-limit:]

data = {"rows": {}, "trades": [], "seen": {}, "boot": {}, "fetched": {}, "started": time.time()}
pushed = []
st = {"model": None, "push": lambda: pushed.append(1), "push_t": 0}
t0 = time.time()
n = D.cycle(data, st, fetch_limit, fetch_range, lambda: COINS)
check(n == len(COINS) * 2, f"cycle processed all coins ({n})")
check(len(pushed) >= 1, "the cycle sends progress to the app while it loads history")
check(len(data["rows"]) >= 60, f"history rows were remembered ({len(data['rows'])})")
check(set(data["boot"]) == {f"{c}|{t}" for c in COINS for t in D.TFS}, "boot marked")
n2 = D.cycle(data, st, fetch_limit, fetch_range, lambda: COINS)
check(len(data["fetched"]) == 6, "second cycle does not refetch a candle it already read")

# 4. train + decide
names = list(TL.EXITS.keys())
rows_list = [(r[2], D.feats_of(r[4], r[1], r[3]), r[5]) for r in data["rows"].values()]
model = D.train(rows_list, names) if len(rows_list) >= D.MIN_TRAIN else None
if model is None:                                     # the fake market gave fewer rows than the real one: pad by repeating (shape test only)
    rows_list = (rows_list * 4)[:max(D.MIN_TRAIN, len(rows_list))]
    rows_list = [(t + k, f, n) for k, (t, f, n) in enumerate(rows_list)]
    model = D.train(rows_list, names)
check(model is not None and model["mode"] in ("EXPLORE", "LEARNED") and "val" in model, "model trained, mode " + str(model and model["mode"]))
fs = rows_list[0][1]
take, xi, mode, pred, why = D.decide(None, fs, names)
check(take and names[xi] == TL.BOT and mode == "explore", "no model -> take with the bot exit")
model["mode"] = "EXPLORE"
check(D.decide(model, fs, names)[0] is True, "EXPLORE takes every signal")
model["mode"] = "LEARNED"
random.seed(1)
res = [D.decide(model, fs, names) for _ in range(300)]
check(all(r[2] in ("learned", "skip", "test") for r in res), "LEARNED modes")

# 5. paper trades: open on a signal, finish later
tr_open = [t for t in data["trades"] if t["status"] == "open"]
sk = [t for t in data["trades"] if t["status"] == "skipped"]
check(all(t["take"] for t in tr_open) and not sk, "explore mode opened trades, none skipped")
# force a trade whose answer is known: long, SL far below, TP1 just above -> hits TP1 on the next candle that reaches it
c = candles("5m", 470, 7)
S = __import__("recovered_bot.ai_ind_features", fromlist=["x"]).build(c)
i = 440
entry = S["c"][i]
tps = [entry * 1.004, entry * 1.01, entry * 1.02, entry * 1.03]
fake = {"id": "x", "s": "AAAUSDT", "f": "5m", "ct": S["t"][i], "t": S["t"][i] + 299999, "d": 1, "src": "MAIN", "entry": entry, "sl": entry * 0.5, "tps": tps,
        "exit": "close all at TP1", "take": True, "mode": "test", "pred": None, "why": "", "status": "open", "opened": time.time(), "tg": {}}
d2 = {"rows": {}, "trades": [fake], "seen": {}, "boot": {}, "fetched": {}}
D.process(d2, "AAAUSDT", "5m", c, False, int(time.time() * 1000), None, names)
if fake["status"] == "closed":
    check(fake["end"] in ("TP", "REV", "TIMEOUT") and isinstance(fake["net"], float), "trade finished " + fake["end"])
else:
    check(fake["status"] == "open" and "live" in fake, "trade still running shows a live number")

# 5b. a new signal on the last candle opens a paper trade (find a cut of the fake chart that ends on a signal)
d3 = {"rows": {}, "trades": [], "seen": {}, "boot": {}, "fetched": {}}
cc = candles("5m", 900, 11)
for cut in range(420, 900):
    D.process(d3, "BBBUSDT", "5m", cc[:cut], False, int(time.time() * 1000), None, names)
    if d3["trades"]:
        break
check(len(d3["trades"]) >= 1 and d3["trades"][0]["status"] == "open" and d3["trades"][0]["take"], "a signal opened a paper trade")
nb = len(d3["trades"])
D.process(d3, "BBBUSDT", "5m", cc[:cut], False, int(time.time() * 1000), None, names)
check(len(d3["trades"]) == nb, "the same signal is never opened twice")
for cut2 in range(cut, 900, 3):
    D.process(d3, "BBBUSDT", "5m", cc[:cut2], False, int(time.time() * 1000), None, names)
check(any(t["status"] == "closed" and t.get("end") for t in d3["trades"]), "later candles finished a trade")
check(all(t["status"] != "closed" or t["net"] is not None for t in d3["trades"]), "closed trades have a result")
model["mode"] = "LEARNED"
sk_n = 0
for cut3 in range(420, 900):
    d4 = {"rows": {}, "trades": [], "seen": {}, "boot": {}, "fetched": {}}
    model["W"] = [[-50.0, -50.0] + [-50.0] * (len(names) - 2) for _ in model["W"]]     # a model that expects losses everywhere
    D.process(d4, "BBBUSDT", "5m", cc[:cut3], False, int(time.time() * 1000), model, names)
    sk_n += sum(1 for t in d4["trades"] if t["status"] == "skipped")
    if sk_n:
        break
check(sk_n >= 1, "LEARNED mode skips a signal it expects to lose (and keeps following it)")

# 5c. chart facts: the stop path, exit price / time, plain-English text, open trades always in the view
import tag_lab as _TL
_n = 14
_S = {"h": [100 + 2 * k + 1 for k in range(_n)], "l": [100 + 2 * k - 1 for k in range(_n)], "c": [100 + 2 * k for k in range(_n)],
      "t": [1_000_000 + 300_000 * k for k in range(_n)], "n": _n, "xup": [False] * _n, "xdn": [False] * _n}
_Z = {"up": [False] * _n, "dn": [False] * _n}
_r = _TL.sim_rule(_S, _Z, 0, 1, 100.0, 98.0, [101.0, 110.0, 120.0, 130.0], 10.0, 1.0, cap=None, be=True, xmode=None, trail=1.5, allow_open=True)
check(_r is not None and _r["path"] and all(isinstance(j, int) and p_ > 0 for j, p_ in _r["path"]), "sim_rule returns the stop path")
check(all(_r["path"][k][1] <= _r["path"][k + 1][1] for k in range(len(_r["path"]) - 1)), "a long trade's stop only moves up")
check(_r["px"] == _S["c"][-1] and _r["why"] == "OPEN", "open trade ends at the latest close")
_b = D._bits(_S, 0, 300_000, _r, live=True)
check(_b["lpx"] == _r["px"] and "xpx" not in _b and _b["path"][0][0] > _S["t"][0], "live chart bits")
_t = {"s": "AAAUSDT", "f": "5m", "d": 1, "src": "BOTH", "exit": "NO CAP, trail 1.5R", "mode": "test", "why": "", "status": "open", "t": 1, "ct": 1_000_000,
      "entry": 100.0, "sl": 98.0, "tps": [101.0, 110.0, 120.0, 130.0], "live": 12.5, "lbars": 7, "path": _b["path"], "tg": {"tsi_zero": "TSI with the trade (above/below 0)"}}
_sl = D.slim(_t)
check(_sl["scn"].startswith("Both indicators gave BUY") and "TSI with the trade" in _sl["scn"], "scenario in plain words")
check("Open for 35 min" in _sl["what1"] and "+12.50 USDT" in _sl["what1"] and "moved" in _sl["what2"], "open trade summary: " + _sl["what1"])
_t2 = dict(_t, status="closed", net=-3.4, end="SL", bars=3, path=[])
_s2 = D.slim(_t2)
check("Stop loss was hit after 15 min" in _s2["what1"] and "-3.40 USDT" in _s2["what1"] and "did not move" in _s2["what2"], "closed trade summary: " + _s2["what1"])
_dd = {"rows": {}, "trades": [dict(_t, t=k, status="closed", net=1.0, end="TP", bars=2) for k in range(60)] + [dict(_t, t=-5)], "seen": {}, "boot": {}, "fetched": {}}
_v = D.make_view(_dd, None, {"best": [], "worst": []}, names, "", "", True)
check(sum(1 for x in _v["recent"] if x["status"] == "open") == 1 and len(_v["recent"]) == 41, "every open trade is always in the view")


# 6. report numbers and the small view file
ins = D.insights(data, names)
check(isinstance(ins["best"], list) and isinstance(ins["worst"], list), "insights")
sm = D.summary(data, model, names)
check({"closed", "pnl", "open", "skipped_pnl", "by_src"} <= set(sm), "summary keys")
D._save("dual_lab_view.json", D.make_view(data, model, ins, names, "x", "", True))
s = D.status()
check(s["running"] is True and s["enabled"] is True and len(s["recent"]) <= 60, "status reads the view")
check(D.status().get("margin") == 100.0 and D.status().get("lev") == 10.0, "status always has margin and leverage")
D.set_enabled(False)
check(D.status()["enabled"] is False and D.ensure_running() is False, "stopped = no spawn")
D.set_enabled(True)
check(D._lock() is not None, "lock free in the test")
print(f"PASS test_dual_lab ({ok} checks, {time.time() - t0:.1f}s, rows={len(data['rows'])}, trades={len(data['trades'])}, mode={model['mode']})")
