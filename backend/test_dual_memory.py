"""Dual Bot Part B (dual_memory.py + the sideways tags): no network. Run: cd backend && python3 test_dual_memory.py"""
import math, os, random, sys, tempfile, time
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dual_lab as D, dual_memory as MD, filter_lab as FL, tag_lab as TL
from recovered_bot import ai_ind_features as F
from recovered_bot.strategy import ABCDStrategy

ok = 0
def check(c, m):
    global ok
    assert c, "FAIL: " + m
    ok += 1

def series(n, seed, drift=0.0, vol=0.004, end=None):
    rnd = random.Random(seed); step = FL.TF_MS["5m"]
    end = end or (int(time.time() * 1000) // step) * step - step
    p, out = 100.0, []
    for k in range(n):
        o = p; p = max(1.0, p * (1 + drift + rnd.gauss(0, vol) + 0.0008 * math.sin(k / 30.0)))
        out.append({"timestamp": end - (n - 1 - k) * step, "open": o, "high": max(o, p) * 1.001, "low": min(o, p) * 0.999, "close": p, "volume": 1.0})
    return out

# 1. sideways %: a steady trend scores lower than a flat noisy range, and both stay in 0..100
def side_avg(cs):
    S = F.build(cs); Z = TL.z_series(S)
    v = [TL.sideways(S, Z, i) for i in range(F.MIN_BARS, S["n"])]
    return sum(a for a, _ in v) / len(v), sum(b for _, b in v) / len(v), v
tm, tz, tv = side_avg(series(900, 1, drift=0.003, vol=0.0015))
fm, fz, fv = side_avg(series(900, 2, drift=0.0, vol=0.004))
check(all(0 <= a <= 100 and 0 <= b <= 100 for a, b in tv + fv), "sideways stays 0..100")
check(tm < fm, f"trend is less sideways than a noisy range (main {tm:.0f} vs {fm:.0f})")
check("side_main" in TL.DIMS and "side_z" in TL.DIMS, "sideways tags are normal tags")

# 2. fake / real labels
tg = {"side_main_pct": 80, "side_z_pct": 20, "order": "", "tsi_zero": "", "z_ema": ""}
check(MD.label_trade(tg, -12.0, "SL", 0) == ("fake", "Sideways market: a pane was choppy when it entered."), "sideways SL = fake")
check(MD.label_trade({"side_main_pct": 10, "side_z_pct": 10}, 30.0, "TP", 4)[0] == "real", "TP = real")
check(MD.label_trade({"side_main_pct": 10, "side_z_pct": 10, "tsi_zero": "TSI against the trade"}, -9.0, "SL", 0)[1] == "TSI was against the trade.", "TSI reason")
check(MD.label_trade({}, -1.0, "BE", 1)[0] == "real", "TP1 reached then stop at entry is not fake")
check(MD.label_trade({}, -3.0, "TIMEOUT", 0)[0] == "unclear", "small time-out loss is unclear")

# 3. look-alikes: planted history where the tag "x" always loses; only OLDER rows may be used (no peeking)
nd = len(TL.DIMS); bi = list(TL.EXITS).index(TL.BOT)
def row(t, same, loss):
    tgs = ["a"] * nd; tgs[2] = "x" if same else "y"
    nets = [0.0] * len(TL.EXITS); nets[bi] = -10.0 if loss else 10.0
    return ["AAA", "5m", t, 1, tgs, nets]
rows = [row(t, True, True) for t in range(100, 140)] + [row(t, False, False) for t in range(140, 180)] + [row(1000, True, False)]
new = ["a"] * nd; new[2] = "x"
m = MD.lookalikes(rows, new, 500)
check(m and m["n"] == 30 and m["loss_pct"] == 100 and m["warn"], f"old mistake found ({m})")
check("TSI vs zero" in (m["worst"] or ""), "names the worst tag")
check(MD.lookalikes(rows, new, 100) is None, "nothing older than the trade = no look-alikes (no peeking)")
check(MD.lookalikes(rows[:5], new, 500) is None, "too little memory = None")

# 4. real flow: a live signal gets a look-alike note, and after the candles come it gets a fake / real label
strat, TLm = ABCDStrategy(), TL
found = None
for seed in range(1, 80):
    cs = series(760, seed)
    for e_idx in range(500, 700):
        S = F.build(cs[:e_idx + 1]); Z = TL.z_series(S)
        if S["n"] and D._entry(S, Z, S["n"] - 1, "5m", strat, TL, FL):
            found = (seed, e_idx); break
    if found: break
check(found, "the fake market gives at least one signal")
seed, e_idx = found
cs = series(760, seed)
data = {"rows": {}, "trades": [], "seen": {}, "boot": {}, "fetched": {}}
names = list(TL.EXITS)
now_ms = int(time.time() * 1000)
D.process(data, "AAAUSDT", "5m", cs[:e_idx + 1], True, now_ms, None, names)      # history + the live signal on the last candle
tr = [t for t in data["trades"] if t["s"] == "AAAUSDT"]
check(len(tr) == 1 and "mem" in tr[0], "new trade carries the look-alike note field")
D.process(data, "AAAUSDT", "5m", cs, False, now_ms, None, names)                  # the candles after it arrive
t = data["trades"][0]
if t["status"] in ("closed", "skipped_done"):
    check(t["label"] in ("real", "fake", "unclear") and t["reason"], "finished trade is labelled")
sl = D.slim(t)
check({"label", "reason", "mem", "side"} <= set(sl) and len(sl["side"]) == 2, "the app view has the new fields")
check("Sideways: main chart" in sl["scn"], "scenario text shows the sideways percent")

# 5. lessons: the repeat check counts warned vs not warned
tr = [{"status": "closed", "label": "fake", "reason": "r1", "net": -5, "mem": {"warn": True}},
      {"status": "closed", "label": "real", "reason": "ok", "net": 9, "mem": {"warn": False}},
      {"status": "closed", "label": "fake", "reason": "r1", "net": -2, "mem": None}]
ls = MD.lessons(tr)
check(ls["fake"] == 2 and ls["top_reasons"][0]["n"] == 2 and ls["repeat"]["warned_lost"] == 1 and ls["repeat"]["not_warned"] == 1, "lessons counts")

# 6. old memory file with fewer tags is dropped once and read again
old = {"rows": {"k": ["A", "5m", 1, 1, ["a"] * 13, [0.0] * 9]}, "trades": [], "seen": {}, "boot": {"A|5m": 1}, "fetched": {}}
view = D.make_view(old, None, {"best": [], "worst": []}, names, "", "", True)
check("lessons" in view, "view has lessons")
# 7. Part C scenario finder on planted history: tag "x" loses with the bot exit, tag "y" wins with exit 4 (no cap); 3 days
day = 86_400_000
def srow(t, tagv):
    tgs = ["a"] * nd; tgs[2] = tagv
    nets = [0.0] * len(TL.EXITS); bars = [10] * len(TL.EXITS)
    if tagv == "x": nets[bi] = -8.0
    else: nets[bi] = 1.0; nets[4] = 9.0; bars[4] = 20
    return ["AAA", "5m", t, 1, tgs, nets, bars]
rr = {f"k{i}": srow(i * day * 3 // 160, "x" if i % 2 else "y") for i in range(160)}
sc = D.scenarios({"rows": rr}, names)
check(sc["status"] == "ready" and sc["days"] >= 2.9, f"scenarios ready after 3 days ({sc['status']}, {sc['days']})")
byname = {c["name"]: c for c in sc["cards"]}
cx, cy = byname.get("TSI vs zero: x"), byname.get("TSI vs zero: y")
check(cx and cx["verdict"] == "SKIP" and cx["bot_win"] == 0, f"losing situation = SKIP ({cx})")
check(cy and cy["verdict"] == "USE" and cy["best_exit"] == names[4] and cy["mins"] == 100, f"winning situation = USE with the best exit and its time ({cy})")
check(cy["per_day"] > 20 and any(t.startswith("Skip: TSI vs zero: x") for t in sc["tips"]), "repeat per day + plain tips")
check(D.scenarios({"rows": {k: v for k, v in list(rr.items())[:130]}}, names)["status"] == "ready" and
      D.scenarios({"rows": {k: srow(i, "x") for i, k in enumerate(rr)}}, names)["status"] == "collecting", "under 2 days of data = collecting")
print(f"PASS test_dual_memory ({ok} checks)")
