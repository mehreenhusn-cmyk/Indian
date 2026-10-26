"""brain_retest.py (F2 retest own book). No network. Run: cd backend && python3 test_brain_retest.py"""
import json, os, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_own as BO
import brain_retest as BR
ok = 0
def check(c, m):
    global ok
    assert c, "FAIL: " + m
    ok += 1

class FakeTL:                       # sim_rule stand-in: net = +4 when the fill price is below 100.5 for a BUY, else -4
    @staticmethod
    def sim_rule(S, Z, j, d, fill, sl, tps, lev, fee, **rule):
        return {"net": 4.0 if fill < 100.5 else -4.0}

def series(bars):                   # bars: (open, high, low) per candle
    n = len(bars)
    return {"o": [b[0] for b in bars], "h": [b[1] for b in bars], "l": [b[2] for b in bars], "n": n + 1,
            "e50": [100.0] * n, "std": [1.0] * n}

sl, tps = 95.0, [110.0, 112.0]
# BUY at candle 0. EMA50 100, zone = 100 + 0.25*1 = 100.25: a dip to it at candle 2 = retest fill at min(zone, open)
S = series([(101, 101.5, 100.8), (101, 101.2, 100.6), (100.9, 101.0, 100.1), (101, 101.5, 100.9)])
check(BR.twin(S, None, 0, 1, sl, tps, {}, FakeTL, 10.0, 1.0) == (4.0, 2), "retest touched at candle 2 -> enters there")
# TP1 reached first -> never came back
S = series([(101, 101.5, 100.8), (101, 111.0, 100.9)])
check(BR.twin(S, None, 0, 1, sl, tps, {}, FakeTL, 10.0, 1.0) == (None, None), "ran to TP1 first = missed")
# stop level first -> missed
S = series([(101, 101.5, 100.8), (101, 101.2, 94.0)])
check(BR.twin(S, None, 0, 1, sl, tps, {}, FakeTL, 10.0, 1.0) == (None, None), "stop level first = missed")
# SELL mirror: zone = 100 - 0.25 = 99.75, touched by a high
S = series([(99, 99.2, 98.5), (99.4, 99.9, 99.1)])
check(BR.twin(S, None, 0, -1, 105.0, [90.0, 88.0], {}, FakeTL, 10.0, 1.0)[1] == 1, "sell retest works the other way round")
# retest only after more than the longest wait -> missed
S = series([(101, 101.5, 100.8)] * 30)
check(BR.twin(S, None, 0, 1, sl, tps, {}, FakeTL, 10.0, 1.0) == (None, None), "never touched inside 24 candles")

# report: collecting, early, unsteady, better
def tr(i, net, rt):
    return {"s": "AAAUSDT", "f": "15m", "d": 1, "t": i, "closed_at": i, "net": net, "rt": rt, "status": "closed"}
r = BR.report({"closed": [tr(i, -3, [2.0, 2]) for i in range(5)]})
check(r["status"] == "collecting" and "Collecting" in r["text"], "collecting under 10")
r = BR.report({"closed": [tr(i, -3, [2.0, 2]) for i in range(20)]})
check(r["status"] == "early" and r["gain"] == 20 * 5.0 and r["entered"] == 20 and "hint" in r["text"], "early: numbers + hint (retest +2, normal -3 -> +5 each)")
mix = [tr(i, -3, [2.0, 2]) for i in range(60)] + [tr(100 + i, 3, [-2.0, 2]) for i in range(60)]
r = BR.report({"closed": mix})
check(r["status"] == "unsteady" and not r["steady"], "halves disagree -> unsteady")
good = [tr(i, -3, [2.0, 2]) for i in range(80)] + [tr(100 + i, -1, [1.0, 2]) for i in range(40)] + [tr(300 + i, -3, [None, None]) for i in range(10)]
r = BR.report({"closed": good})
check(r["status"] == "better" and r["steady"] and r["came"] == 120 and r["missed"] == 10 and r["gain"] > 0, "100+ came back, both halves agree -> better")
bad = [tr(i, 3, [-2.0, 2]) for i in range(110)]
check(BR.report({"closed": bad})["status"] == "worse", "waiting loses in both halves -> worse")
check(BR.report({"closed": [tr(0, 1, None)]})["status"] == "collecting" and BR.report(None)["status"] == "collecting", "old trades without rt / empty are safe")

# summary carries it and is JSON-safe
sm = BO.summary({"since": 1, "open": [], "closed": [tr(i, -3, [2.0, 2]) for i in range(20)]})
check(sm["retest_book"]["status"] == "early", "summary has retest_book")
json.dumps(sm)
print("OK %d checks" % ok)
