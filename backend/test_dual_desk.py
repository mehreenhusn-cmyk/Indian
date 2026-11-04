"""Tests for dual_desk.py + universe_7d source tag (no network). Run: python test_dual_desk.py"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dual_desk as DK
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


def tr(i, sym, tf, status, net, t=None):
    return {"id": "T%d" % i, "t": (DAY + 60000 * (i + 1)) if t is None else t, "s": sym, "f": tf, "d": 1, "src": "MAIN", "status": status, "net": net, "exit": "x", "mode": "EXPLORE"}


with tempfile.TemporaryDirectory() as base:
    check(DK.desk(base, NOW)["state"] == "none", "no archive yet = state none, no crash")
    U._S["last"] = NOW
    U._log_day(["AAAUSDT", "BBBUSDT"], ["OLDUSDT", "AAAUSDT"], base, NOW)
    U._log_day(["AAAUSDT"], ["OLDUSDT"], base, NOW)
    log = U.load_log(base)
    e = log[U.day_name(DAY)]
    check(e["today"] == ["AAAUSDT", "BBBUSDT"] and e["extra"] == ["OLDUSDT", "AAAUSDT"], "log keeps names once, never loses one")
    check(U.tag_of("AAAUSDT", DAY + 5, log) == "today", "a coin in both lists counts as today")
    check(U.tag_of("OLDUSDT", DAY + 5, log) == "d7" and U.tag_of("ZZZUSDT", DAY + 5, log) == "other", "d7 / other")
    check(U.tag_of("BTCUSDT", DAY + 5, log) == "today" and U.tag_of("OLDUSDT", DAY - 86400000, log) == "other", "BTC = today; day without a log = other")
    data = {"trades": [tr(1, "AAAUSDT", "5m", "closed", 10.0), tr(2, "AAAUSDT", "5m", "closed", -4.0), tr(3, "OLDUSDT", "15m", "closed", 20.0),
                       tr(4, "OLDUSDT", "15m", "open", None), tr(5, "BTCUSDT", "5m", "closed", 5.0), tr(6, "ZZZUSDT", "5m", "closed", 1.0),
                       tr(7, "AAAUSDT", "5m", "skipped", None), tr(8, "AAAUSDT", "5m", "closed", 9.0, t=DAY - 1000)], "rows": {}, "rt": {}}
    check(TA.save_dual(data, {}, base) is True, "archive saved")
    d = DK.desk(base, NOW)
    g = d["groups"]
    check(d["state"] == "ok" and d["day"] == U.day_name(DAY), "state ok, day name")
    check(g["today"]["5m"]["n"] == 2 and g["today"]["5m"]["wins"] == 1, "today 5m: 2 finished (AAA, AAA), 1 won; BTC is outside (R16b)")
    check(abs(g["today"]["5m"]["net"] - (10 - 4)) < 0.01, "net USDT: margin 100 for AAA (10 - 4), BTC not inside")
    check(d["btc"]["5m"]["n"] == 1 and abs(d["btc"]["5m"]["net"] - 50.0) < 0.01, "BTC has its own numbers (margin 1000: +50)")
    check(g["d7"]["15m"]["n"] == 1 and g["d7"]["15m"]["open"] == 1 and abs(g["d7"]["15m"]["net"] - 20.0) < 0.01, "d7 15m: 1 finished + 1 open, +20 USDT")
    check(g["other"]["5m"]["n"] == 1, "unlogged coin = other")
    check(sum(c["n"] + c["open"] for gg in g.values() for c in gg.values()) == 5, "skipped, yesterday's trade and BTC are not counted")
    check(d["tags"].get("OLDUSDT") == "d7" and d["tags"].get("AAAUSDT") == "today", "tags for the coins on the list now")
    con = sqlite3.connect(os.path.join(base, "dual_archive.db"))
    con.close()
    bad = os.path.join(base, "x")
    os.makedirs(bad)
    check(DK.desk(bad, NOW)["state"] in ("none", "ok"), "empty folder never crashes")

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dual_desk.py"), encoding="utf-8").read().lower()
check("delete" not in src and "insert" not in src and "update " not in src and "mode=ro" in src, "desk only reads (read-only open, no write statements)")
print("OK", ok[0], "checks")
