"""brain_lessons.py: Timing Sync report + lessons (report only). No network. Run: cd backend && python3 test_brain_lessons.py"""
import os, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_lessons as BL
import smart_brain as B

ok = 0
def check(cond, msg):
    global ok
    assert cond, "FAIL: " + msg
    ok += 1

ORD = {"same": "both on the same candle", "z12": "Z candle came first (1-2 candles before)", "z35": "Z candle came first (3-5 candles before)",
       "m12": "main chart came first (1-2 candles before)", "m35": "main chart came first (3-5 candles before)",
       "zonly": "main chart gave nothing in the last 5 candles", "monly": "Z candle gave nothing in the last 5 candles",
       "opp": "Z candle gave the OPPOSITE signal in the last 5 candles"}
SRC = {"same": "BOTH", "z12": "MAIN", "z35": "MAIN", "m12": "Z", "m35": "Z", "zonly": "Z", "monly": "MAIN", "opp": "MAIN"}
n_id = [0]
def tr(key, net, side=10, tsi=True, sym="ETHUSDT", status="closed"):
    n_id[0] += 1
    return {"id": n_id[0], "s": sym, "t": 1000 + n_id[0], "status": status, "net": net, "src": SRC[key],
            "tg": {"order": ORD[key], "tsi_zero": "TSI with the trade (above/below 0)" if tsi else "TSI against the trade",
                   "side_main_pct": side, "side_z_pct": side}}

# 1. every order text lands in the right group
for k in ORD:
    check(BL.classify(tr(k, 1.0)) == k, "classify " + k)
check(BL.classify({"tg": {"order": "old unknown text"}, "src": "Z"}) is None, "unknown order = None")

# 2. too few finished trades = collecting, nothing else
r = BL.timing_report([tr("same", 5.0) for _ in range(10)])
check(r["status"] == "collecting" and "Collecting" in r["text"] and r["groups"] == [] and r["lessons"] == [], "collecting")

# 3. planted data: same candle wins, Main only loses, BTC and open trades are ignored
trades = ([tr("same", 10.0) for _ in range(20)] + [tr("monly", -10.0) for _ in range(20)] + [tr("zonly", -2.0) for _ in range(12)]
          + [tr("z12", 5.0) for _ in range(12)] + [tr("m35", 4.0) for _ in range(3)]
          + [tr("same", -50.0, sym="BTCUSDT") for _ in range(5)] + [tr("same", 99.0, status="open") for _ in range(5)])
r = BL.timing_report(trades)
g = {x["key"]: x for x in r["groups"]}
check(r["status"] == "ready" and r["done"] == 67, "ready, BTC + open left out: %s" % r["done"])
check(g["same"]["n"] == 20 and g["same"]["pnl"] == 200.0 and g["same"]["win_pct"] == 100, "same candle numbers (margin 100, +10 ROI = +10 USDT)")
check(g["monly"]["pnl"] == -200.0 and g["monly"]["ready"], "main only loses")
check(not g["m35"]["ready"] and "tsi_with" not in g["m35"], "small group: no verdict")
check("Best timing: Same candle" in r["text"] and "Worst: Main only" in r["text"], "headline names best and worst: " + r["text"])
tones = [x["tone"] for x in r["lessons"]]
check(len(r["lessons"]) <= 10 and r["lessons"][-1]["tone"] == "info", "lessons capped, last = honest note")
check(any("SAME candle" in x["text"] and x["tone"] == "good" for x in r["lessons"]), "same-candle lesson is good")
check(any("Main is the weaker" in x["text"] or "Main only" in x["text"] for x in r["lessons"]), "one-indicator lesson")
check(any("TSI with the trade" in x["text"] for x in r["lessons"]), "TSI lesson")

# 4. steady check: older half wins, newer half loses -> told to be careful
flip = [tr("same", 10.0) for _ in range(12)] + [tr("same", -10.0) for _ in range(12)] + [tr("monly", -1.0) for _ in range(10)] + [tr("zonly", -1.0) for _ in range(10)]
r = BL.timing_report(flip)
g = {x["key"]: x for x in r["groups"]}
check(g["same"]["steady"] is False, "halves disagree")
check(any("older and the newer half disagree" in x["text"] for x in r["lessons"]), "lesson warns")

# 5. deep clean candidate: both within 1-2 candles + TSI with + not sideways
mix = ([tr("same", 8.0, side=10, tsi=True) for _ in range(12)] + [tr("same", -8.0, side=90, tsi=True) for _ in range(10)]
       + [tr("monly", -3.0, side=10, tsi=False) for _ in range(12)])
r = BL.timing_report(mix)
check(r["deep"]["n"] == 12 and r["deep"]["ready"] and r["deep"]["pnl"] == 96.0, "deep clean count")
check(r["deep"]["rest"]["n"] == 22, "rest = everything else")

# 6. it lands in the Brain view and never crashes it
v = B._timing_view(mix)
check(v["status"] == "ready" and "groups" in v, "view hook")
check(B._timing_view([{"bad": 1}])["status"] == "collecting", "junk trades = collecting, no crash")
print("brain_lessons OK: %d checks" % ok)
