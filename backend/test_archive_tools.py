"""Tests for archive_tools.py (check + CSV export). No network. Run: python test_archive_tools.py"""
import csv
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import archive_tools as AT
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


def tr(i, sym, status, net, t, d=1):
    return {"id": "T%d" % i, "t": t, "s": sym, "f": "5m", "d": d, "src": "MAIN", "status": status, "net": net, "exit": "x", "mode": "EXPLORE"}


with tempfile.TemporaryDirectory() as base:
    check(AT.check(base)["state"] == "none", "no archive = none")
    check(AT.export_csv(base).count("\n") == 1, "no archive = header only")
    U._S["last"] = NOW
    U._log_day(["AAAUSDT"], ["OLDUSDT"], base, NOW)
    trades = [tr(1, "AAAUSDT", "closed", 2.0, DAY + 10), tr(2, "OLDUSDT", "closed", -1.0, DAY + 20, d=-1), tr(3, "BTCUSDT", "closed", 1.0, DAY + 30), tr(4, "AAAUSDT", "open", None, DAY + 40)]
    check(TA.save_dual({"trades": trades, "rows": {}, "rt": {}}, {}, base) is True, "archive saved")
    check(AT.check(base)["text"].startswith("Archive exists, JSON"), "JSON missing = quiet text, no crash")
    with open(os.path.join(base, "dual_lab_data.json"), "w") as f:
        json.dump({"trades": trades}, f)
    r = AT.check(base)
    check(r["state"] == "match" and r["json_closed"] == 3 and r["db_closed"] == 3, "all JSON finished trades are in the archive = match")
    trades.append(tr(5, "AAAUSDT", "closed", 3.0, DAY + 50))
    with open(os.path.join(base, "dual_lab_data.json"), "w") as f:
        json.dump({"trades": trades}, f)
    r = AT.check(base)
    check(r["state"] == "differ" and r["missing"] == 1 and "stays on the JSON" in r["text"], "one trade missing in the archive = differ")
    rows = list(csv.reader(io.StringIO(AT.export_csv(base))))
    check(len(rows) == 4 and rows[0][0] == "id", "CSV: header + 3 finished trades (open skipped)")
    by = {x[2]: x for x in rows[1:]}
    check(by["AAAUSDT"][11] == "today" and by["OLDUSDT"][11] == "d7" and by["OLDUSDT"][4] == "SHORT", "CSV: source tag and side")
    check(by["BTCUSDT"][8] == "10.0" and by["AAAUSDT"][8] == "2.0", "CSV: USDT (BTC margin 1000)")
    check(len(list(csv.reader(io.StringIO(AT.export_csv(base, closed_only=False))))) == 5, "closed_only=False adds the open trade")
    check(len(list(csv.reader(io.StringIO(AT.export_csv(base, days=1, now_s=NOW))))) == 4, "days=1 keeps today")

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "archive_tools.py"), encoding="utf-8").read()
check(not any(w in src for w in ("INSERT", "UPDATE", "DELETE", "DROP")), "source has no write statement")
print("ALL %d CHECKS PASSED" % ok[0])
