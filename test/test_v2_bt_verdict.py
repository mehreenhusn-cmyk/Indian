"""Part 91a test: backend/v2_bt_verdict.py + route /api/v2/brain_verdict (Simple Results, read-only). Offline, FAKE trades in a temp folder.
Questions: no file = honest 'not ready'? under 30 trades = NOT ENOUGH DATA, never PROFIT? 30+ winners in both halves = PROFIT? halves that disagree = MIXED?
is the max drawdown / losing streak right (checked by hand)? does PROFIT with a bigger dip say so? is the equity line short? are sources kept apart? is LIVE refused?
Run:  python3 test/test_v2_bt_verdict.py"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "backend", "api"))
import v2_bt_store as B
import v2_bt_verdict as V

DEF = {"indicators": ["ema50"], "entry": "x", "stop": "x", "target": "x", "max_hold": 24, "fee_pct": 0.05, "slippage_pct": 0.02, "size_usdt": 100}
T0 = 1_700_000_000
NOW = T0 + 400 * 300


def add(con, i, net_pct, source="PAPER", state="TRENDING_UP", zone="ZONE_X"):
    ts = T0 + i * 300
    B.add_decision(con, {"version": "BT-01", "source": source, "symbol": "BTCUSDT", "interval": "5m", "close_ts": ts, "side": "LONG", "decision": "OPEN_LONG", "sample": "TRAIN",
                         "state": state, "snapshot": {"tags": {"sd_zone": zone}}, "data_upto_ts": ts})
    tid = B.open_trade(con, {"version": "BT-01", "source": source, "symbol": "BTCUSDT", "interval": "5m", "side": "LONG", "open_ts": ts, "entry": 100, "sl": 99, "tp": 102, "size_usdt": 100, "sample": "TRAIN"})
    B.close_trade(con, tid, {"close_ts": ts + 60, "exit_price": 101, "exit_reason": "TARGET", "gross_pct": net_pct + 0.07, "fee_pct": 0.05, "slip_pct": 0.02, "hold_candles": 1})


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="v2v_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def make(self, nets, source="PAPER"):
        con = B.connect(self.d)
        B.register_version(con, "BT-01", DEF)
        for i, n in enumerate(nets):
            add(con, i, n, source)
        con.close()

    def test_no_file(self):
        r = V.build(self.d, now=NOW)
        self.assertFalse(r["ready"])
        self.assertEqual(r["live"], "LOCKED")

    def test_few_trades_never_profit(self):
        self.make([1.0] * 12)
        r = V.build(self.d, now=NOW)
        self.assertEqual(r["verdict"]["word"], "NOT ENOUGH DATA")
        self.assertIn("12 closed trades", r["verdict"]["text"])

    def test_profit_needs_both_halves(self):
        self.make([0.5] * 40)
        r = V.build(self.d, now=NOW)
        self.assertEqual(r["verdict"]["word"], "PROFIT")
        self.assertEqual(r["numbers"]["trades"], 40)
        self.assertEqual(r["numbers"]["losses"], 0)
        self.assertAlmostEqual(r["numbers"]["net_usdt"], 20.0, places=2)

    def test_loss_and_mixed(self):
        self.make([-0.4] * 35)
        self.assertEqual(V.build(self.d, now=NOW)["verdict"]["word"], "LOSS")
        shutil.rmtree(self.d)
        self.d = tempfile.mkdtemp(prefix="v2v_")
        self.make([0.8] * 20 + [-0.5] * 20)                       # older half wins, newer half loses: no clear answer
        r = V.build(self.d, now=NOW)
        self.assertEqual(r["verdict"]["word"], "MIXED")

    def test_drawdown_and_streak_by_hand(self):
        tr = [{"ts": i, "net": n} for i, n in enumerate([3, -1, -2, 1, -4, -1, 5])]      # line: 3 2 0 1 -3 -4 1, peak 3, trough -4 = fall 7
        dd = V.drawdown(V.equity(tr))
        self.assertEqual(dd["max_usdt"], 7.0)
        self.assertEqual(dd["ended_ts"], 5)
        self.assertEqual(dd["current_usdt"], 2.0)                 # now 1, peak 3
        self.assertEqual(V.streak(tr), {"longest": 2, "current": 0})
        self.assertEqual(V.streak(tr[:6]), {"longest": 2, "current": 2})

    def test_profit_with_bigger_dip_says_so(self):
        self.make([2.0] * 10 + [-1.9] * 10 + [-1.0] * 10 + [1.1] * 10)      # net +2, both halves +1, but it fell 29 from the peak of 20
        r = V.build(self.d, now=NOW)
        self.assertEqual(r["verdict"]["word"], "PROFIT")
        self.assertIn("worst dip", r["verdict"]["text"])
        self.assertGreater(r["risk"]["drawdown"]["max_usdt"], r["numbers"]["net_usdt"])

    def test_equity_is_short(self):
        self.make([0.2] * 300)
        r = V.build(self.d, now=NOW + 300 * 300)
        self.assertLessEqual(len(r["equity"]), V.POINTS)
        self.assertEqual(r["equity"][0]["v"], 0.0)
        self.assertAlmostEqual(r["equity"][-1]["v"], r["numbers"]["net_usdt"], places=1)

    def test_sources_apart(self):
        self.make([0.5] * 40, "PAPER")
        con = B.connect(self.d)
        for i in range(5):
            add(con, 100 + i, -1.0, "SHADOW")
        con.close()
        p, s = V.build(self.d, "PAPER", NOW), V.build(self.d, "SHADOW", NOW)
        self.assertEqual((p["numbers"]["trades"], s["numbers"]["trades"]), (40, 5))
        self.assertEqual({t["source"]: t["closed"] for t in p["tabs"]}, {"REPLAY": 0, "PAPER": 40, "SHADOW": 5})
        self.assertNotIn("LIVE", [t["source"] for t in p["tabs"]])

    def test_use_line_from_review(self):
        self.make([0.5] * 40)
        r = V.build(self.d, now=NOW)
        self.assertTrue(r["use"])
        self.assertEqual(r["stop"], [])

    def test_bad_source(self):
        self.make([0.5] * 3)
        with self.assertRaises(ValueError):
            V.build(self.d, "LIVE")

    def test_route(self):
        import v2_data as D
        self.make([0.5] * 40)
        self.assertIn("brain_verdict", D.ROUTES)
        self.assertIn("brain_verdict", D.VIEWS)
        with open(os.path.join(self.d, D.FLAG_NAME), "w") as f:
            f.write("1")
        code, body = D.dispatch("brain_verdict", {}, self.d, NOW)
        if code == 200:
            self.assertEqual(body["verdict"]["word"], "PROFIT")
        code, body = D.dispatch("brain_verdict", {"source": "LIVE"}, self.d, NOW)
        self.assertIn(code, (400, 404))


if __name__ == "__main__":
    unittest.main(verbosity=2)
