"""Tests for brain_universe.py (Edge by universe + day feel). No network. Run: python test_brain_universe.py"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_universe as BU
import trade_archive as TA
import universe_7d as U

ok = [0]


def check(c, msg):
    if not c:
        print("FAIL", msg)
        sys.exit(1)
    ok[0] += 1
    print("PASS", msg)


NOW = 1793000000.0
DAY = U.day_start_ms(NOW)
LOG = {U.day_name(DAY): {"today": ["AAAUSDT"], "extra": ["OLDUSDT"]}}

check(BU.phase_of(5, -3, 25) == "pump" and BU.phase_of(-5, 3, 25) == "drift", "pump = longs win shorts lose; drift = the opposite")
check(BU.phase_of(-1, -2, 25) == "sideways" and BU.phase_of(1, 2, 25) == "mixed", "both lose = sideways; both win = mixed")
check(BU.phase_of(50, -50, 19) == "early", "under 20 trades = early, no label")
check(BU._usdt("BTCUSDT", 1.0) == 10.0 and BU._usdt("AAAUSDT", 1.0) == 1.0, "BTC margin 1000, others 100")

few = [("AAAUSDT", "5m", DAY + 1000, 1, 2.0), ("OLDUSDT", "5m", DAY + 2000, -1, -1.0)]
r = BU.build(few, LOG, NOW)
check(r["status"] == "learning" and "Learning" in r["text"], "few trades = learning, numbers only, no verdict")
check(r["groups"]["today"]["n"] == 1 and r["groups"]["d7"]["n"] == 1 and r["groups"]["d7"]["net"] == -1.0, "trades split by source tag")

many = [("AAAUSDT", "5m", DAY + 1000 + i, 1, 1.0) for i in range(30)] + [("OLDUSDT", "15m", DAY + 5000 + i, -1, 2.0) for i in range(30)]
r = BU.build(many, LOG, NOW)
check(r["status"] == "ready" and "better than" in r["text"], "30 + 30 trades = verdict; 7-day coins earn more -> better than")
check(r["groups"]["today"]["avg"] == 1.0 and r["groups"]["d7"]["avg"] == 2.0 and r["groups"]["d7"]["win_pct"] == 100, "average per trade and win % right")
same = [("AAAUSDT", "5m", DAY + i, 1, 1.0) for i in range(30)] + [("OLDUSDT", "5m", DAY + i, 1, 1.02) for i in range(30)]
check("about the same" in BU.build(same, LOG, NOW)["text"], "difference under 0.05 USDT = about the same")
check(BU.build(many, LOG, NOW)["days"][-1]["phase"] == "mixed", "today's day feel is filled from long / short nets (long +30, short +60 = mixed)")
old = [("ZZZUSDT", "5m", DAY - 3 * U.DAY_MS, 1, 3.0)]
r = BU.build(old, LOG, NOW)
check(r["groups"]["other"]["n"] == 1 and "older trades" in " ".join(r["lines"]), "trade before the coin log = other, one quiet line")
check(len(r["days"]) == BU.SHOW_DAYS and r["days"][0]["day"] < r["days"][-1]["day"], "7 days, oldest first")

with tempfile.TemporaryDirectory() as base:
    check(BU.report(base, NOW)["status"] == "none", "no archive = none, no crash")
    U._S["last"] = NOW
    U._log_day(["AAAUSDT"], ["OLDUSDT"], base, NOW)

    def tr(i, sym, status, net, t):
        return {"id": "T%d" % i, "t": t, "s": sym, "f": "5m", "d": 1, "src": "MAIN", "status": status, "net": net, "exit": "x", "mode": "EXPLORE"}
    data = {"trades": [tr(1, "AAAUSDT", "closed", 2.0, DAY + 100), tr(2, "OLDUSDT", "closed", -1.0, DAY + 200), tr(3, "OLDUSDT", "open", None, DAY + 300),
                       tr(4, "AAAUSDT", "closed", 5.0, DAY - 12 * U.DAY_MS)], "rows": {}, "rt": {}}
    check(TA.save_dual(data, {}, base) is True, "archive saved")
    r = BU.report(base, NOW)
    check(r["status"] == "learning" and r["groups"]["today"]["n"] == 1 and r["groups"]["d7"]["n"] == 1, "reads finished trades only (open skipped)")
    check(r["groups"]["other"]["n"] == 0, "trade older than the 10-day window is not read")
    check(BU.report(base, NOW)["err"] == "", "no error")

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "brain_universe.py"), encoding="utf-8").read()
check("DELETE" not in src.upper().replace("DELETE\n", "") or "mode=ro" in src, "opened read-only")
check("INSERT" not in src and "UPDATE" not in src and "DELETE" not in src, "source has no write statement")
print("ALL %d CHECKS PASSED" % ok[0])
