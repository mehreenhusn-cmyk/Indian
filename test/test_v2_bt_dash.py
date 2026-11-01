"""Part M3 test: backend/v2_bt_dash.py + route /api/v2/brain_dash (Brain Dashboard, read-only). Offline, FAKE trades in a temp folder.
Questions: today counted right (closed / net / pct / decisions)? open trades split long / short? daily loss cap used only by a LOSS, hit at the cap, kill switch shown?
30-day pace and the last 8 days right and in order? sources apart? trend sentence only with enough trades? LIVE refused? route registered?
Run:  python3 test/test_v2_bt_dash.py"""
import datetime
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "backend", "api"))
import v2_bt_dash as H
import v2_bt_guard as G
import v2_bt_store as B

DEF = {"indicators": ["ema50"], "entry": "x", "stop": "x", "target": "x", "max_hold": 24, "fee_pct": 0.05, "slippage_pct": 0.02, "size_usdt": 100}
DAY0 = int(datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc).timestamp())
NOW = DAY0 + 20 * 3600


def add(con, ts, net_pct, side="LONG", source="PAPER", close=True, symbol="BTCUSDT", decision=None):
    """One trade that CLOSES at ts + 600. net_usdt = net_pct because the size is 100 USDT."""
    dec = decision or ("OPEN_LONG" if side == "LONG" else "OPEN_SHORT")
    B.add_decision(con, {"version": "BT-01", "source": source, "symbol": symbol, "interval": "5m", "close_ts": ts, "side": side, "decision": dec, "sample": "NEW", "state": "TRENDING_UP",
                         "snapshot": {"tags": {}}, "data_upto_ts": ts})
    e, sl, tp = (100, 99, 102) if side == "LONG" else (100, 101, 98)
    tid = B.open_trade(con, {"version": "BT-01", "source": source, "symbol": symbol, "interval": "5m", "side": side, "open_ts": ts, "entry": e, "sl": sl, "tp": tp, "size_usdt": 100, "sample": "NEW"})
    if close:
        B.close_trade(con, tid, {"close_ts": ts + 600, "exit_price": 101, "exit_reason": "TARGET", "gross_pct": net_pct + 0.07, "fee_pct": 0.05, "slip_pct": 0.02, "hold_candles": 2})


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="v2dh_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def con(self):
        c = B.connect(self.d)
        B.register_version(c, "BT-01", DEF)
        return c

    def test_no_file(self):
        r = H.build(self.d, now=NOW)
        self.assertFalse(r["ready"])
        self.assertEqual(r["live"], "LOCKED")

    def test_today_and_decisions(self):
        c = self.con()
        add(c, DAY0 + 1000, 0.5)
        add(c, DAY0 + 2000, -0.2)
        add(c, DAY0 - 5000, 9.0)                                          # yesterday, not today
        B.add_decision(c, {"version": "BT-01", "source": "PAPER", "symbol": "ETHUSDT", "interval": "5m", "close_ts": DAY0 + 50, "side": "LONG", "decision": "SKIP", "sample": "NEW", "state": "SIDEWAYS",
                           "snapshot": {}, "data_upto_ts": DAY0 + 50})
        c.close()
        r = H.build(self.d, now=NOW)
        self.assertTrue(r["ready"])
        t = r["today"]
        self.assertEqual(t["closed"], 2)
        self.assertAlmostEqual(t["net_usdt"], 0.3, places=2)
        self.assertAlmostEqual(t["pct_of_capital"], 0.03, places=2)
        self.assertEqual(t["bot_net_usdt"], 0.0)
        self.assertEqual((r["decisions"]["taken"], r["decisions"]["skipped"]), (2, 1))

    def test_open_long_short(self):
        c = self.con()
        add(c, DAY0 + 1000, 0.5, "LONG", close=False)
        add(c, DAY0 + 2000, 0.5, "SHORT", close=False, symbol="ETHUSDT")
        add(c, DAY0 + 3000, 0.5, "SHORT", close=False, symbol="SOLUSDT")
        add(c, DAY0 + 4000, 0.5, "LONG")                                  # closed, not open
        c.close()
        o = H.build(self.d, now=NOW)["open"]
        self.assertEqual((o["long"], o["short"], o["total"]), (1, 2, 3))

    def test_risk_cap(self):
        c = self.con()
        add(c, DAY0 + 1000, 0.8)
        c.close()
        k = H.build(self.d, now=NOW)["risk"]
        self.assertEqual((k["cap_usdt"], k["cap_pct"], k["used_usdt"], k["hit"]), (20.0, 2.0, 0.0, False))      # profit day uses nothing
        c = self.con()
        add(c, DAY0 + 2000, -5.0)
        c.close()
        k = H.build(self.d, now=NOW)["risk"]
        self.assertAlmostEqual(k["used_usdt"], 4.2, places=2)
        self.assertAlmostEqual(k["used_pct"], 21.0, places=1)
        self.assertFalse(k["hit"])
        c = self.con()
        add(c, DAY0 + 3000, -20.0)
        c.close()
        self.assertTrue(H.build(self.d, now=NOW)["risk"]["hit"])

    def test_kill_switch_shown(self):
        c = self.con()
        self.assertFalse(H.build(self.d, now=NOW)["risk"]["kill_switch"])
        G.set_kill(c, True, "test")
        c.close()
        self.assertTrue(H.build(self.d, now=NOW)["risk"]["kill_switch"])

    def test_pace_and_recent(self):
        c = self.con()
        for k in range(10):                                                # today and 9 days back, 1 trade a day, +0.1 each
            add(c, DAY0 - k * 86400 + 1000, 0.1)
        add(c, DAY0 + 1500, 5.0, source="REPLAY")                          # another source: never counted
        c.close()
        r = H.build(self.d, now=NOW)
        self.assertEqual(r["pace30"]["brain_trades"], 10)
        self.assertAlmostEqual(r["pace30"]["brain_usdt"], 1.0, places=2)
        self.assertEqual(r["pace30"]["bot_trades"], 0)
        self.assertEqual(len(r["recent"]), 8)
        self.assertLess(r["recent"][0]["day"], r["recent"][-1]["day"])    # oldest first
        self.assertEqual(r["recent"][-1]["day"], "2026-11-01")
        self.assertAlmostEqual(r["all_time"]["net_usdt"], 1.0, places=2)
        self.assertEqual(r["all_time"]["closed"], 10)

    def test_sources_apart(self):
        c = self.con()
        add(c, DAY0 + 1000, 0.5, source="PAPER")
        add(c, DAY0 + 2000, 0.7, source="SHADOW")
        c.close()
        self.assertEqual(H.build(self.d, "SHADOW", NOW)["today"]["closed"], 1)
        self.assertAlmostEqual(H.build(self.d, "SHADOW", NOW)["today"]["net_usdt"], 0.7, places=2)
        self.assertAlmostEqual(H.build(self.d, "PAPER", NOW)["today"]["net_usdt"], 0.5, places=2)

    def test_why_needs_trades_and_live_refused(self):
        c = self.con()
        add(c, DAY0 + 1000, 0.5)
        c.close()
        w = H.build(self.d, now=NOW)["why"]
        self.assertEqual(w["word"], "NOT ENOUGH DATA")
        self.assertIn("closed trades", w["text"])
        with self.assertRaises(ValueError):
            H.build(self.d, "LIVE", NOW)

    def test_route(self):
        import v2_data as D
        c = self.con()
        add(c, DAY0 + 1000, 0.5)
        c.close()
        self.assertIn("brain_dash", D.ROUTES)
        self.assertIn("brain_dash", D.VIEWS)
        with open(os.path.join(self.d, D.FLAG_NAME), "w") as f:
            f.write("1")
        code, body = D.dispatch("brain_dash", {}, self.d, NOW)
        if code == 200:
            self.assertEqual(body["today"]["closed"], 1)
        code, body = D.dispatch("brain_dash", {"source": "LIVE"}, self.d, NOW)
        self.assertIn(code, (400, 404))


if __name__ == "__main__":
    unittest.main(verbosity=2)
