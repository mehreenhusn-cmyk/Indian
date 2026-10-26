"""brain_week.py (F3 weekly report card + time-of-day cap). No network. Run: cd backend && python3 test_brain_week.py"""
import json, os, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_own as BO
import brain_week as BW
ok = 0
def check(c, m):
    global ok
    assert c, "FAIL: " + m
    ok += 1

DAY = 86_400_000
NOW = (1_800_000_000_000 // DAY) * DAY + 13 * 3_600_000     # 13:00 UTC = block 12-18
check(BW.block_of(NOW) == "12-18 UTC" and BW.block_of(NOW - 13 * 3_600_000) == "00-06 UTC" and BW.block_of(NOW + 8 * 3_600_000) == "18-24 UTC", "6-hour UTC blocks")

def tr(opened, net, closed=None):
    return {"s": "AAAUSDT", "f": "15m", "d": 1, "t": opened, "closed_at": closed if closed is not None else opened + 60_000, "net": net, "status": "closed"}

# 1. collecting: few trades, few days
own = {"since": NOW - 2 * DAY, "open": [], "closed": [tr(NOW - DAY + i * 1000, 5) for i in range(10)]}
r = BW.report(own, NOW)
check(r["status"] == "collecting" and not r["ready"] and "Collecting" in r["text"] and len(r["days"]) == 7, "collecting")
check(r["week_n"] == 10 and r["best"]["n"] == 10, "week totals and best day")
check(BW.blocked(own, NOW, 0) is False, "never blocks while collecting")

# 2. ready: 8 days, 320 trades; block 12-18 loses in both halves, the others win
closed = []
for k in range(8):
    base = NOW - (k + 1) * DAY
    for i in range(20):
        closed.append(tr(base - 13 * 3_600_000 + 14 * 3_600_000 + i * 1000, -4))      # 14:00 UTC: 12-18 block, losing
    for i in range(20):
        closed.append(tr(base - 13 * 3_600_000 + 2 * 3_600_000 + i * 1000, 3))        # 02:00 UTC: 00-06 block, winning
own = {"since": NOW - 9 * DAY, "open": [], "closed": closed}
r = BW.report(own, NOW)
check(r["ready"] and r["status"] == "limit_on" and r["bad"] == ["12-18 UTC"] and r["active"], "limit ON for the losing block only")
check(len(r["blocks"]) == 4 and next(b for b in r["blocks"] if b["block"] == "00-06 UTC")["bad"] is False, "winning block is not limited")

# 3. cap: TOD_CAP per day inside the bad block, other times free
own["open"] = [tr(NOW - 1000 * (i + 1), 0) for i in range(BW.TOD_CAP - 1)]
check(BW.blocked(own, NOW, 0) is False, "2 today: third still allowed")
check(BW.blocked(own, NOW, 1) is True, "3 today: next one blocked")
check(own["tod_skip"]["n"] == 1 and BW.report(own, NOW)["skipped"] == 1, "skip counted for today")
check(BW.blocked(own, NOW - 11 * 3_600_000, 0) is False, "a different block (02:00 UTC) is never limited")

# 4. enough data but nothing loses in both halves -> limit_off
good = [tr(NOW - (k + 1) * DAY + i * 1000, 3) for k in range(8) for i in range(40)]
r = BW.report({"since": NOW - 9 * DAY, "open": [], "closed": good}, NOW)
check(r["ready"] and r["status"] == "limit_off" and not r["bad"], "limit OFF")

# 5. summary carries it; bad input safe
sm = BO.summary({"since": NOW - DAY, "open": [], "closed": [tr(NOW - 5000, 2)]})
check(sm["week"]["status"] == "collecting", "summary has week")
json.dumps(sm)
check(BW.report(None, NOW)["ready"] is False and BW.blocked({}, NOW, 0) is False, "bad input is safe")
print("OK %d checks" % ok)
