"""Join report (layers_join.py): Price Action + Volume + Brain on the same finished trades. No network.
Run: cd backend && python3 test_layers_join.py"""
import copy, os, random, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import layers_join as LJ

ok = 0
def check(cond, msg):
    global ok
    assert cond, "FAIL: " + msg
    ok += 1

NOW = 1_800_000_000.0
GOOD, BAD = {"side_main_pct": 10, "side_z_pct": 10}, {"side_main_pct": 90, "side_z_pct": 90}
check(LJ._agree("supports", "supports") == "both_support" and LJ._agree("supports", "unclear") == "one_support"
      and LJ._agree("unclear", "unclear") == "unclear" and LJ._agree("supports", "against") == "any_against"
      and LJ._agree("against", "unclear") == "any_against", "agreement rules")

def make(n, win_rate, days=12, seed=1, both_in_logs=True):
    """n trades; verdict pairs cycle through both_support / one_support / unclear / any_against; half the trades are Brain-good."""
    random.seed(seed)
    trades, pa, vol = [], {"rows": {}, "since": NOW - days * 86400.0}, {"rows": {}, "since": NOW - days * 86400.0}
    pairs = [("supports", "supports"), ("supports", "unclear"), ("unclear", "unclear"), ("against", "supports")]
    for i in range(n):
        p, v = pairs[i % 4]
        win = random.random() < win_rate[LJ._agree(p, v)]
        t = {"id": "ETHUSDT|15m|%d" % i, "s": "ETHUSDT", "f": "15m", "t": 1_700_000_000_000 + i * 1000, "d": 1, "status": "closed",
             "net": 10.0 if win else -5.0, "tg": GOOD if (i // 4) % 2 == 0 else BAD}
        trades.append(t)
        pa["rows"][t["id"]] = {"v": p, "t": t["t"]}
        if both_in_logs or i % 2:
            vol["rows"][t["id"]] = {"v": v, "t": t["t"]}
    return trades, pa, vol

# 1. layers add value: both_support wins 80%, any_against 20%
t, pa, vol = make(480, {"both_support": 0.8, "one_support": 0.5, "unclear": 0.5, "any_against": 0.2})
snap = copy.deepcopy(t)
r = LJ.report(t, pa, vol, now=NOW)
g = {x["key"]: x for x in r["groups"]}
b = {x["key"]: x for x in r["on_brain"]}
check(t == snap, "Dual Bot trades untouched")
check(r["status"] == "ready" and r["judged"] == 480 and r["days"] == 12.0, "ready")
check(g["both_support"]["n"] == 120 and g["any_against"]["n"] == 120 and g["both_support"]["avg"] > g["any_against"]["avg"], "groups")
check(b["brain_good"]["n"] == 240 and b["brain_good_support"]["n"] == 60 and b["brain_good_against"]["n"] == 60, "Brain-good split %s" % b["brain_good"]["n"])
check(r["adds_value"] is True and r["edge"] > 5 and r["steady"] is True and "look useful" in r["text"], "adds value")

# 2. layers do NOT add value (wrong way round): never calls them useful
t, pa, vol = make(480, {"both_support": 0.2, "one_support": 0.5, "unclear": 0.5, "any_against": 0.8})
r = LJ.report(t, pa, vol, now=NOW)
check(r["status"] == "ready" and r["adds_value"] is False and "Not proven" in r["text"] and "wrong way" in r["text"], "wrong way = not useful")

# 3. not ready too early: enough trades but only 4 days of data, and too few trades
t, pa, vol = make(480, {"both_support": 0.8, "one_support": 0.5, "unclear": 0.5, "any_against": 0.2}, days=4)
r = LJ.report(t, pa, vol, now=NOW)
check(r["status"] == "collecting" and "4.0 days" in r["text"] and "adds_value" not in r, "too early by days")
t, pa, vol = make(40, {"both_support": 0.8, "one_support": 0.5, "unclear": 0.5, "any_against": 0.2})
check(LJ.report(t, pa, vol, now=NOW)["status"] == "collecting", "too early by trades")

# 4. only trades read by BOTH layers count; open trades never count
t, pa, vol = make(480, {"both_support": 0.8, "one_support": 0.5, "unclear": 0.5, "any_against": 0.2}, both_in_logs=False)
check(LJ.report(t, pa, vol, now=NOW)["judged"] == 240, "needs both layers")
t, pa, vol = make(480, {"both_support": 0.8, "one_support": 0.5, "unclear": 0.5, "any_against": 0.2})
check(LJ.report([dict(x, status="open") for x in t], pa, vol, now=NOW)["judged"] == 0, "only finished trades")
check(LJ.report([], {}, {}, now=NOW)["status"] == "collecting", "empty logs")
print("join report: %d checks passed" % ok)
