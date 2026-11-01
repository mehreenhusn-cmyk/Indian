"""Part L1 test: backend/v2_bt_progress.py + route /api/v2/brain_progress (Learning Progress, read-only). Offline, FAKE trades in a temp folder.
Questions: today counted right (profit / loss / net / decisions / open)? 30 days and 5 weeks right? trend: under 30 = NOT ENOUGH DATA, 30 to 59 = EARLY HINT only, 60+ = IMPROVING / WORSE / NOT CLEAR?
a group that loses in both halves = a mistake, older loss + newer profit = fixed (a hint)? sources apart? LIVE refused?
Run:  python3 test/test_v2_bt_progress.py"""
import datetime
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "backend", "api"))
import v2_bt_progress as P
import v2_bt_store as B

DEF = {"indicators": ["ema50"], "entry": "x", "stop": "x", "target": "x", "max_hold": 24, "fee_pct": 0.05, "slippage_pct": 0.02, "size_usdt": 100}
DAY0 = int(datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc).timestamp())
NOW = DAY0 + 20 * 3600


def add(con, ts, net_pct, state="TRENDING_UP", source="PAPER", close=True, symbol="BTCUSDT"):
    """One trade that CLOSES at ts + 600 (the close time is what the Brain counts)."""
    B.add_decision(con, {"version": "BT-01", "source": source, "symbol": symbol, "interval": "5m", "close_ts": ts, "side": "LONG", "decision": "OPEN_LONG", "sample": "NEW", "state": state,
                         "snapshot": {"tags": {}}, "data_upto_ts": ts})
    tid = B.open_trade(con, {"version": "BT-01", "source": source, "symbol": symbol, "interval": "5m", "side": "LONG", "open_ts": ts, "entry": 100, "sl": 99, "tp": 102, "size_usdt": 100, "sample": "NEW"})
    if close:
        B.close_trade(con, tid, {"close_ts": ts + 600, "exit_price": 101, "exit_reason": "TARGET", "gross_pct": net_pct + 0.07, "fee_pct": 0.05, "slip_pct": 0.02, "hold_candles": 2})


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="v2pg_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def con(self):
        c = B.connect(self.d)
        B.register_version(c, "BT-01", DEF)
        return c

    def seq(self, nets, start=None, gap=3600, state="TRENDING_UP"):
        """Trades one after the other ending at NOW - 1h, so every trade lies before now."""
        c = self.con()
        t0 = (NOW - 3600 - gap * len(nets)) if start is None else start
        for i, n in enumerate(nets):
            add(c, t0 + i * gap, n, state)
        c.close()

    def test_no_file(self):
        self.assertFalse(P.build(self.d, now=NOW)["ready"])

    def test_today(self):
        c = self.con()
        add(c, DAY0 + 1000, 0.5)
        add(c, DAY0 + 2000, -0.2)
        add(c, DAY0 + 3000, 0.3)
        add(c, DAY0 + 4000, 0.4, close=False)                           # still open
        add(c, DAY0 - 5000, 9.0)                                        # yesterday
        B.add_decision(c, {"version": "BT-01", "source": "PAPER", "symbol": "ETHUSDT", "interval": "5m", "close_ts": DAY0 + 50, "side": "LONG", "decision": "SKIP", "sample": "NEW", "state": "SIDEWAYS",
                           "snapshot": {}, "data_upto_ts": DAY0 + 50})
        c.close()
        t = P.build(self.d, now=NOW)["today"]
        self.assertEqual((t["trades"], t["profit"], t["loss"], t["open_now"]), (3, 2, 1, 1))
        self.assertAlmostEqual(t["net_usdt"], 0.6, places=2)
        self.assertEqual((t["decisions"]["taken"], t["decisions"]["skipped"]), (4, 1))
        self.assertIn("3 trades", t["text"])

    def test_days_and_weeks(self):
        c = self.con()
        for k in range(3):
            add(c, DAY0 - k * 86400 + 1000, 0.1)                       # today, yesterday, the day before
        add(c, DAY0 - 10 * 86400 + 1000, -0.5)
        add(c, DAY0 - 40 * 86400 + 1000, 5.0)                          # older than 30 days and 5 weeks
        c.close()
        r = P.build(self.d, now=NOW)
        self.assertEqual([d["day"] for d in r["days"]][:3], ["2026-11-01", "2026-10-31", "2026-10-30"])
        self.assertEqual(len(r["days"]), 4)
        self.assertEqual(len(r["weeks"]), 5)
        self.assertEqual(r["weeks"][0]["trades"], 3)                    # days 0 to 6
        self.assertEqual(r["weeks"][1]["trades"], 1)                    # the -0.5 trade, 10 days ago
        self.assertEqual(sum(w["trades"] for w in r["weeks"]), 4)
        self.assertEqual(r["all_closed"], 5)

    def test_trend_words(self):
        self.seq([0.2] * 12)
        self.assertEqual(P.build(self.d, now=NOW)["trend"]["word"], "NOT ENOUGH DATA")
        shutil.rmtree(self.d)
        self.d = tempfile.mkdtemp(prefix="v2pg_")
        self.seq([-0.3] * 20 + [0.4] * 20)                              # 40 trades: only an early hint
        t = P.build(self.d, now=NOW)["trend"]
        self.assertEqual(t["word"], "EARLY HINT")
        self.assertIn("newer half looks better", t["text"])

    def test_improving_and_worse(self):
        self.seq([-0.3] * 30 + [0.4] * 30)
        t = P.build(self.d, now=NOW)["trend"]
        self.assertEqual(t["word"], "IMPROVING")
        self.assertEqual((t["older"]["loss_per_10"], t["newer"]["loss_per_10"]), (10.0, 0.0))
        self.assertIn("Luck", t["text"])
        shutil.rmtree(self.d)
        self.d = tempfile.mkdtemp(prefix="v2pg_")
        self.seq([0.4] * 30 + [-0.3] * 30)
        self.assertEqual(P.build(self.d, now=NOW)["trend"]["word"], "WORSE")
        shutil.rmtree(self.d)
        self.d = tempfile.mkdtemp(prefix="v2pg_")
        self.seq([0.1] * 30 + [1.0, -0.1] * 15)                          # newer average is higher but it loses MORE often: the two numbers disagree
        self.assertEqual(P.build(self.d, now=NOW)["trend"]["word"], "NOT CLEAR")

    def test_mistakes_fixed_learned(self):
        c = self.con()
        t0 = NOW - 3600 - 3600 * 160
        for i in range(40):                                              # group A: loses in both halves = a mistake
            add(c, t0 + i * 7200, -0.3, "SIDEWAYS")
        for i in range(40):                                              # group B: lost early, wins now = fixed (a hint)
            add(c, t0 + 3600 + i * 7200, -0.2 if i < 20 else 0.5, "TRENDING_UP")
        for i in range(40):                                              # group C: wins in both halves = learned
            add(c, t0 + 1800 + i * 7200, 0.3, "BREAKOUT")
        c.close()
        r = P.build(self.d, now=NOW)
        self.assertTrue(any("SIDEWAYS LONG" in x for x in r["mistakes"]))
        self.assertFalse(any("TRENDING_UP" in x for x in r["mistakes"]))
        self.assertTrue(any("TRENDING_UP LONG" in x for x in r["fixed"]))
        self.assertTrue(any("BREAKOUT LONG" in x for x in r["learned"]))
        self.assertEqual(r["worse"], [])

    def test_sources_apart_and_bad_source(self):
        c = self.con()
        for i in range(5):
            add(c, DAY0 + 1000 + i * 100, 0.2)
            add(c, DAY0 + 1000 + i * 100, -0.9, source="SHADOW", symbol="ETHUSDT")
        c.close()
        self.assertEqual(P.build(self.d, "PAPER", NOW)["today"]["trades"], 5)
        self.assertEqual(P.build(self.d, "SHADOW", NOW)["today"]["loss"], 5)
        with self.assertRaises(ValueError):
            P.build(self.d, "LIVE", NOW)

    def test_route(self):
        import v2_data as D
        self.seq([0.2] * 5)
        self.assertIn("brain_progress", D.ROUTES)
        self.assertIn("brain_progress", D.VIEWS)
        with open(os.path.join(self.d, D.FLAG_NAME), "w") as f:
            f.write("1")
        code, body = D.dispatch("brain_progress", {}, self.d, NOW)
        if code == 200:
            self.assertEqual(body["all_closed"], 5)
        code, body = D.dispatch("brain_progress", {"source": "LIVE"}, self.d, NOW)
        self.assertIn(code, (400, 404))


if __name__ == "__main__":
    unittest.main(verbosity=2)
