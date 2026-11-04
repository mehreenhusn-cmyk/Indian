"""Tests for dual_today.py (R16a). No network. Run: python test_dual_today.py"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dual_desk as DK
import dual_today as DT
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


def tr(i, sym, tf, status, net, t=None, closed_at=None):
    x = {"id": "T%d" % i, "t": (DAY + 60000 * (i + 1)) if t is None else t, "s": sym, "f": tf, "d": 1, "src": "MAIN", "status": status, "net": net, "exit": "x", "mode": "m"}
    if closed_at is not None:
        x["closed_at"] = closed_at
    return x


with tempfile.TemporaryDirectory() as base:
    check(DT.today(base, NOW)["state"] == "none", "no archive = state none")
    data = {"trades": [tr(1, "AAAUSDT", "5m", "closed", 10.0), tr(2, "AAAUSDT", "15m", "closed", -4.0), tr(3, "BTCUSDT", "5m", "closed", 5.0),
                       tr(4, "AAAUSDT", "5m", "open", None), tr(5, "AAAUSDT", "5m", "skipped", None),
                       tr(6, "BBBUSDT", "5m", "closed", 20.0, t=DAY - 3600000, closed_at=NOW),            # opened yesterday, closed today -> counts today
                       tr(7, "BBBUSDT", "5m", "closed", 30.0, t=DAY + 5000, closed_at=DAY / 1000.0 - 100)], "rows": {}, "rt": {}}    # closed before the day start -> not today
    check(TA.save_dual(data, {}, base) is True, "archive saved")
    t = DT.today(base, NOW)
    a, b = t["alts"], t["btc"]
    check(t["state"] == "ok" and a["closed"] == 3 and a["wins"] == 2 and a["losses"] == 1, "alts: 3 closed today (10, -4, +20), 2 won")
    check(abs(a["realized"] - (10 - 4 + 20)) < 0.01, "alts USDT = margin 100 x ROI / 100")
    check(b["closed"] == 1 and abs(b["realized"] - 50.0) < 0.01, "BTC apart: 1 trade, +50 USDT (margin 1000)")
    check(a["open"] == 1 and a["skipped"] == 1 and a["opened"] == 4, "open 1, skipped 1, opened today 4 (T1, T2, T4, T7; T6 opened yesterday)")
    check(a["by_tf"]["5m"]["closed"] == 2 and a["by_tf"]["15m"]["closed"] == 1, "split by interval")
    d = DK.desk(base, NOW)
    check(d["today"]["alts"]["closed"] == 3 and "groups" in d, "dual_desk carries the same today, groups untouched")
    view = {"summary": {"today": {"opened": 9, "closed": 1, "wins": 0, "losses": 1, "realized": -5.0, "open_pnl": 7.0, "total": 2.0, "open": 1}}}
    DT.overlay(view, base, NOW)
    td = view["summary"]["today"]
    check(td["closed"] == 3 and td["realized"] == 26.0 and td["total"] == 33.0 and td["open_pnl"] == 7.0 and td["open"] == 1, "overlay: closed / realized from the archive, total = realized + open pnl")
    check(DT.overlay({"x": 1}, base, NOW) == {"x": 1} and DT.overlay(None, base, NOW) is None, "odd views come back unchanged")
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dual_today.py"), encoding="utf-8").read().lower()
check("insert" not in src and "delete" not in src and "mode=ro" in src, "reads only")
print("OK", ok[0], "checks")
