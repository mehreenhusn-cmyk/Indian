"""Part X1 test: backend/v2_bt_compare.py + route /api/v2/brain_compare (Owl Brain vs Current Bot vs Take-All, read-only). Offline, FAKE trades and FAKE candles in a temp folder.
Questions: the three arms kept apart (paper_b2 never added)? gross / fees / slippage right? decisions counted? Take-All takes WAIT / SKIP ideas, one trade per coin at a time, leaves an unknown end out?
bad day or source = error? no file = honest empty answer?
Run:  python3 test/test_v2_bt_compare.py"""
import datetime
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "backend", "api"))
import v2_bt_compare as C
import v2_bt_sim as SM
import v2_bt_state as ST
import v2_bt_store as B
import v2_defs as D
import v2_results as RS

DEF = {"indicators": ["ema50"], "entry": "x", "stop": "x", "target": "x", "max_hold": 24, "fee_pct": 0.05, "slippage_pct": 0.02, "size_usdt": 100}
DAY0 = int(datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc).timestamp())
NOW = DAY0 + 20 * 3600
STEP = D.STEP["5m"]
N = 40


def fake_run():
    """40 rising candles from the start of the day: every LONG idea (stop 1.0 below, target 1.5 above) hits the target in the NEXT candle."""
    return [(DAY0 + k * STEP, 100.0 + k * 0.5, 100.0 + k * 0.5 + 2.0, 100.0 + k * 0.5 - 0.3, 100.0 + k * 0.5, 10.0) for k in range(N)]


def fake_ctx(run):
    return {"ind": {"sd_std": [1.0] * len(run), "close": [c[4] for c in run]}}


def dec(con, source, decision, ts, side="LONG", state="TRENDING_UP", symbol="BTCUSDT"):
    B.add_decision(con, {"version": "BT-01", "source": source, "symbol": symbol, "interval": "5m", "close_ts": ts, "side": side, "decision": decision, "sample": "NEW", "state": state,
                         "snapshot": {}, "data_upto_ts": ts})


def trade(con, ts, net_pct, source="PAPER", symbol="BTCUSDT"):
    dec(con, source, "OPEN_LONG", ts, symbol=symbol)
    tid = B.open_trade(con, {"version": "BT-01", "source": source, "symbol": symbol, "interval": "5m", "side": "LONG", "open_ts": ts, "entry": 100, "sl": 99, "tp": 102, "size_usdt": 100, "sample": "NEW"})
    B.close_trade(con, tid, {"close_ts": ts + 600, "exit_price": 101, "exit_reason": "TARGET", "gross_pct": net_pct + 0.07, "fee_pct": 0.05, "slip_pct": 0.02, "hold_candles": 2})


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="v2c_")
        self.keep = (SM.load_run, ST.prepare, RS.load)
        SM.load_run = lambda data_dir, symbol, interval: fake_run()
        ST.prepare = fake_ctx
        RS.load = lambda data_dir, fee: ({"paper_b1": [(DAY0 + 3600, 4.0, {}), (DAY0 + 7200, -1.0, {}), (DAY0 - 5000, 50.0, {})], "paper_b2": [(DAY0 + 3600, 99.0, {})]}, 0)

    def tearDown(self):
        SM.load_run, ST.prepare, RS.load = self.keep
        shutil.rmtree(self.d, ignore_errors=True)

    def con(self):
        c = B.connect(self.d)
        B.register_version(c, "BT-01", DEF)
        return c

    def test_no_file(self):
        r = C.build(self.d, now=NOW)
        self.assertFalse(r["ready"])
        self.assertEqual(r["brain"]["closed"], 0)
        self.assertEqual(r["current_bot"]["net_usdt"], 3.0)         # +4 and -1 on the day; the older +50 and paper_b2 are NOT in it

    def test_brain_numbers(self):
        c = self.con()
        for k in range(3):
            trade(c, DAY0 + 1000 + k * 1000, 0.5)
        dec(c, "PAPER", "SKIP", DAY0 + 50, state="SIDEWAYS")
        dec(c, "PAPER", "WAIT", DAY0 + 60, state="CONSOLIDATION")
        dec(c, "PAPER", "NO_OPINION", DAY0 + 70, state=None)
        c.close()
        r = C.build(self.d, now=NOW)
        b = r["brain"]
        self.assertEqual(b["closed"], 3)
        self.assertAlmostEqual(b["net_usdt"], 1.5, places=2)
        self.assertAlmostEqual(b["fees_usdt"], -0.15, places=2)
        self.assertAlmostEqual(b["slippage_usdt"], -0.06, places=2)
        self.assertAlmostEqual(b["gross_usdt"], b["net_usdt"] + 0.21, places=2)
        self.assertEqual(b["decisions"], {"taken": 3, "waited": 1, "skipped": 1, "no_opinion": 1, "total": 6})

    def test_take_all_one_trade_per_coin(self):
        c = self.con()
        for k, dc in ((5, "WAIT"), (6, "SKIP"), (10, "SKIP")):         # idea at 6 starts while the trade of 5 is still open -> left out
            dec(c, "PAPER", dc, DAY0 + k * STEP + STEP, state="SIDEWAYS")
        dec(c, "PAPER", "NO_OPINION", DAY0 + 20 * STEP + STEP, state="SIDEWAYS")     # never an idea
        dec(c, "PAPER", "SKIP", DAY0 + 30 * STEP + STEP, state=None)                  # a guard refusal has no state: not an idea
        dec(c, "PAPER", "WAIT", DAY0 + (N - 1) * STEP + STEP, state="SIDEWAYS")       # last candle: the end is not known
        c.close()
        r = C.build(self.d, now=NOW)["take_all"]
        self.assertEqual(r["ideas"], 4)
        self.assertEqual(r["taken"], 2)
        self.assertEqual(r["unknown_end"], 1)
        self.assertGreater(r["net_usdt"], 0)
        self.assertEqual(r["coins_used"], 1)

    def test_short_idea_and_bad_input(self):
        c = self.con()
        dec(c, "PAPER", "WAIT", DAY0 + 5 * STEP + STEP, side="SHORT", state="TRENDING_DOWN")      # the fake market only rises: a SHORT hits its stop
        c.close()
        self.assertLess(C.build(self.d, now=NOW)["take_all"]["net_usdt"], 0)
        with self.assertRaises(ValueError):
            C.build(self.d, "LIVE", now=NOW)
        with self.assertRaises(ValueError):
            C.build(self.d, day="1 Nov", now=NOW)

    def test_calendar_and_sources_apart(self):
        c = self.con()
        trade(c, DAY0 + 1000, 0.5)
        trade(c, DAY0 - 86400 + 1000, -0.2)
        trade(c, DAY0 + 2000, 9.0, source="SHADOW")
        c.close()
        r = C.build(self.d, now=NOW)
        cal = {x["day"]: x for x in r["calendar"]}
        self.assertEqual(r["calendar"][0]["day"], "2026-11-01")
        self.assertEqual(cal["2026-11-01"]["brain_trades"], 1)
        self.assertEqual(cal["2026-10-31"]["brain_usdt"], -0.2)
        self.assertEqual(r["brain"]["closed"], 1)                      # the SHADOW trade is not in the PAPER numbers

    def test_older_day_and_route(self):
        import v2_data as D2
        c = self.con()
        trade(c, DAY0 - 86400 + 1000, 0.3)
        c.close()
        self.assertEqual(C.build(self.d, day="2026-10-31", now=NOW)["brain"]["closed"], 1)
        self.assertIn("brain_compare", D2.ROUTES)
        self.assertIn("brain_compare", D2.VIEWS)
        with open(os.path.join(self.d, D2.FLAG_NAME), "w") as f:
            f.write("1")
        code, body = D2.dispatch("brain_compare", {"day": "2026-10-31"}, self.d, NOW)
        if code == 200:
            self.assertEqual(body["day"], "2026-10-31")
        code, body = D2.dispatch("brain_compare", {"day": "nonsense"}, self.d, NOW)
        self.assertIn(code, (400, 404))


if __name__ == "__main__":
    unittest.main(verbosity=2)
