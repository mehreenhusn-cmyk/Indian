"""brain_own.py: the Brain's own pretend trades. No network. Run: cd backend && python3 test_brain_own.py"""
import json, math, os, random, sys, tempfile, time
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_own as BO
import filter_lab as FL
import smart_brain as B
import tag_lab as TL
from recovered_bot import ai_ind_features as F
from recovered_bot.strategy import ABCDStrategy
ok = 0
def check(c, m):
    global ok
    assert c, "FAIL: " + m
    ok += 1

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

cs = candles("15m", 1200, 3)
S = F.build(cs)
strat = ABCDStrategy()
# 1. levels: find a candle and side with room; the rule must hold (stop on the right side, first target beyond entry)
plan, at = None, None
for i in range(F.MIN_BARS + 5, S["n"] - 300):
    for d in (1, -1):
        p = BO.plan_levels(S, i, d, strat)
        if p:
            plan, at = p, (i, d)
            break
    if plan:
        break
check(plan is not None, "found a candle with sensible room")
i, d = at
check((plan["sl"] < plan["entry"] < plan["tps"][0]) if d > 0 else (plan["tps"][0] < plan["entry"] < plan["sl"]), "stop and first target on the right sides")
check(plan["ct"] == S["t"][i] and len(plan["tps"]) == 4, "candle time and 4 targets")
sd0 = S["std"][i]
S["std"][i] = 0
check(BO.plan_levels(S, i, d, strat) is None, "no SD width = no plan")
S["std"][i] = sd0

# 2. opening: strips the plan, one per coin+side, one candle used once, cap respected
Z = TL.z_series(S)
tg = TL.make_tags(S, Z, i, d, "MAIN", S["t"][i])
def item(sym="AAAUSDT", dd=d):
    return {"s": sym, "f": "15m", "d": dd, "clean": 80, "div": 10, "prob": {"win_pct": 60, "n": 30}, "_plan": dict(plan), "_tg": tg}
own, w = {}, [item()]
check(BO.open_from(own, w) == 1 and len(own["open"]) == 1, "opens one pretend trade")
check("_plan" not in w[0] and "_tg" not in w[0], "plan removed from the watch list")
check(BO.open_from(own, [item()]) == 0, "same candle is not used twice")
p2 = dict(plan, ct=plan["ct"] + 900000)
x = item(); x["_plan"] = p2
check(BO.open_from(own, [x]) == 0 and len(own["open"]) == 1, "one open trade per coin and side")
y = item("BBBUSDT"); y["_plan"] = dict(plan, ct=plan["ct"] + 1800000)
check(BO.open_from(own, [y]) == 1 and len(own["open"]) == 2, "another coin opens")
check(BO.open_from(own, [{"s": "CCC", "f": "15m", "d": 1}]) == 0, "item without a plan is ignored")
big = {"closed": [{"net": 1.0, "t": 0}] * BO.EXPLORE_N}   # past the explore phase = normal cap
for k in range(BO.MAX_OPEN + 5):
    z = item("C%dUSDT" % k); z["_plan"] = dict(plan, ct=plan["ct"] + k * 900000)
    BO.open_from(big, [z])
check(len(big["open"]) == BO.MAX_OPEN, "cap on open trades")

# 2b. explore limits: at most 3 per round (cleanest first), 6 open, day loss cap stops new ones
ex = {}
many = []
for k in range(5):
    z = item("E%dUSDT" % k); z["clean"] = 50 + k; z["_plan"] = dict(plan, ct=plan["ct"] + (k + 40) * 900000); many.append(z)
check(BO.open_from(ex, many) == BO.EXPLORE_ROUND, "explore: only 3 new trades per round")
check([t["s"] for t in ex["open"]] == ["E4USDT", "E3USDT", "E2USDT"], "explore: the cleanest setups go first")
check(all(t["mg"] == BO.EXPLORE_MG and t["explore"] for t in ex["open"]), "explore trades are tagged and small")
ex["closed"] = [{"explore": True, "mg": 25.0, "net": -200.0, "t": 1, "closed_at": int(time.time() * 1000)}]
z = item("FUSDT"); z["_plan"] = dict(plan, ct=plan["ct"] + 99 * 900000)
check(BO.open_from(ex, [z]) == 0, "explore: day loss cap stops new trades")

# 3. following: the market data holds the future of the trade, so it must finish with a number
fetches = []
def fetch(sym, tf, limit):
    fetches.append(sym)
    return cs
for t in own["open"]:
    t["ct"] = S["t"][i]
    t["entry"], t["sl"], t["tps"] = plan["entry"], plan["sl"], plan["tps"]
now = int(time.time() * 1000)
n_done = BO.settle(own, fetch, now)
check(n_done == 2 and not own["open"] and len(own["closed"]) == 2, "both trades finished and moved to closed")
c0 = own["closed"][0]
check(isinstance(c0["net"], float) and c0["end"] in ("SL", "BE", "TRAIL", "TP", "REV", "TIMEOUT") and c0["status"] == "closed", "closed with a result and a reason")
check(set(fetches) == {"AAAUSDT", "BBBUSDT"}, "each coin downloaded once")

# 4. throttle: a trade checked a moment ago is not downloaded again; unknown candle = expired; empty data = stays open
e = {"open": [{"id": "k", "s": "DDDUSDT", "f": "15m", "d": 1, "ct": 123, "entry": 1, "sl": 0.9, "tps": [1.1, 1.2, 1.3, 1.4], "exit": BO.EXIT_NAME, "status": "open", "live": None, "chk": now}], "closed": [], "since": now}
fetches.clear()
BO.settle(e, fetch, now + 1000)
check(not fetches and len(e["open"]) == 1, "no download within one candle")
BO.settle(e, lambda *a: [], now + 2 * 900000)
check(len(e["open"]) == 1, "empty data keeps the trade open")
BO.settle(e, fetch, now + 4 * 900000)
check(not e["open"] and not e["closed"], "a candle that cannot be found is dropped, not counted")

# 5. summary
check(BO.summary({}) is None, "no summary before the book exists")
sm = BO.summary(own)
check(sm["n"] == 2 and sm["open"] == [] and "finished: 2" in sm["text"] and len(sm["recent"]) == 2, "summary counts and text")
check(all(t.get("explore") and t.get("mg") == BO.EXPLORE_MG for t in own["closed"]) and abs(sm["pnl"] - round(sum(BO.EXPLORE_MG * t["net"] / 100.0 for t in own["closed"]), 2)) < 0.011, "explore trades use the small 25 USDT margin")
sm_n = BO.summary({"since": 1, "open": [], "closed": [{"s": "X", "f": "15m", "d": 1, "net": 2.0, "t": 0}] * BO.EXPLORE_N})
check(not sm_n["exploring"] and abs(sm_n["pnl"] - round(BO.EXPLORE_N * 100.0 * 2.0 / 100.0, 2)) < 0.011 and sm_n["stage"] == "learning", "after the explore phase: normal stage and 100 margin")
so = BO.summary({"since": now, "open": [dict(own["closed"][0], status="open", live=2.5, mg=None)], "closed": []})
check(so["open"][0]["usdt"] == 2.5 and "None has finished" in so["text"], "open trade shows live USDT")
json.dumps(sm)

# 6. the Brain view carries it, and Dual Bot data is untouched
path = os.path.join(os.environ["OWL_DATA_DIR"], "dual_lab_data.json")
open(path, "w").write(json.dumps({"rows": {}, "trades": []}))
before = open(path, "rb").read()
v = B.build_view([], [], own=own)
check(v["own"]["n"] == 2 and B.build_view([], [])["own"] is None, "own block in Brain view")
json.dumps(v, default=str)
check(open(path, "rb").read() == before, "dual_lab_data.json untouched")
print("OK %d checks" % ok)
