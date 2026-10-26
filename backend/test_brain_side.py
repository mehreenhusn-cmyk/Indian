"""brain_side.py (F1 sideways self-rule). No network. Run: cd backend && python3 test_brain_side.py"""
import json, os, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_own as BO
import brain_side as BS
ok = 0
def check(c, m):
    global ok
    assert c, "FAIL: " + m
    ok += 1

SIDE, TREND = {"side_main_pct": 90, "side_z_pct": 90}, {"side_main_pct": 5, "side_z_pct": 5}
NOW = 1_800_000_000_000
def tr(i, tg, net, t=None):
    return {"s": "AAAUSDT", "f": "15m", "d": 1, "t": t if t is not None else NOW - 10 * 86_400_000 + i, "tg": tg, "net": net, "status": "closed"}

# 1. waiting: not enough data -> never blocks
own = {"open": [], "closed": [tr(i, SIDE, -5) for i in range(10)]}
st = BS.state(own, NOW)
check(not st["ready"] and not st["active"] and "Waiting" in st["text"], "waits for data")
check(BS.blocked(own, SIDE, NOW, 0) is False, "no block while waiting")

# 2. enough data, sideways losing in both halves -> ON, cap of DAY_CAP per day
own = {"open": [], "closed": [tr(i, SIDE, -5) for i in range(40)] + [tr(100 + i, TREND, 5) for i in range(70)]}
st = BS.state(own, NOW)
check(st["ready"] and st["active"] and st["side_pnl"] < 0 and st["n"] == 110 and st["n_side"] == 40, "rule is ON")
check(BS.blocked(own, TREND, NOW, 0) is False, "trending is never limited")
own["open"] = [tr(900 + i, SIDE, None, t=NOW) for i in range(BS.DAY_CAP - 1)]
check(BS.blocked(own, SIDE, NOW, 0) is False, "4 sideways today: 5th still allowed")
check(BS.blocked(own, SIDE, NOW, 1) is True, "5 sideways today: next one blocked")
check(own["side_skip"]["n"] == 1 and BS.state(own, NOW)["skipped"] == 1, "skip is counted for today")

# 3. sideways losing only in one half -> OFF
mix = [tr(i, SIDE, -5) for i in range(20)] + [tr(50 + i, SIDE, 8) for i in range(20)] + [tr(100 + i, TREND, 5) for i in range(70)]
st = BS.state({"open": [], "closed": mix}, NOW)
check(st["ready"] and not st["active"] and "OFF" in st["text"], "one good half = no limit")

# 4. summary carries it and stays JSON-safe; bad input never raises
own = {"since": NOW, "open": [], "closed": [tr(i, SIDE, -5) for i in range(3)]}
sm = BO.summary(own)
check(sm["side_rule"]["active"] is False and "Waiting" in sm["side_rule"]["text"], "summary has side_rule")
json.dumps(sm)
check(BS.state(None)["active"] is False and BS.blocked({}, None, NOW) is False, "bad input is safe")
print("OK %d checks" % ok)
