"""Part 90a test: backend/v2_bt_health.py + route /api/v2/brain_health (Brain Health, read-only). Offline, FAKE trades in a temp folder.
Questions: no file = honest 'not ready'? a state under 30 trades = listed as missing, never green? does a USE row with newer winning trades CONFIRM (the old 88c bug judged it the other way round)?
is LIVE always OFF? does a silent auto-runner show up? does a bad source / interval give an error?
Run:  python3 test/test_v2_bt_health.py"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "backend", "api"))
import v2_bt_health as H
import v2_bt_store as B

DEF = {"indicators": ["ema50"], "entry": "x", "stop": "x", "target": "x", "max_hold": 24, "fee_pct": 0.05, "slippage_pct": 0.02, "size_usdt": 100}
T0 = 1_700_000_000


def add(con, i, state, net_pct, source="PAPER", sample="TRAIN", iv="5m"):
    ts = T0 + i * 300
    B.add_decision(con, {"version": "BT-01", "source": source, "symbol": "BTCUSDT", "interval": iv, "close_ts": ts, "side": "LONG", "decision": "OPEN_LONG", "sample": sample,
                         "state": state, "snapshot": {"tags": {"zone": "ZONE_X"}}, "data_upto_ts": ts})
    tid = B.open_trade(con, {"version": "BT-01", "source": source, "symbol": "BTCUSDT", "interval": iv, "side": "LONG", "open_ts": ts, "entry": 100, "sl": 99, "tp": 102, "size_usdt": 100, "sample": sample})
    B.close_trade(con, tid, {"close_ts": ts + 600, "exit_price": 101, "exit_reason": "TARGET", "gross_pct": net_pct + 0.07, "fee_pct": 0.05, "slip_pct": 0.02, "hold_candles": 2})


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="v2h_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def fill(self):
        con = B.connect(self.d)
        B.register_version(con, "BT-01", DEF)
        for i in range(40):                                      # TREND: 40 winning trades, the newest 12 are HOLDOUT
            add(con, i, "TRENDING_UP", 0.5, sample="HOLDOUT" if i >= 28 else "TRAIN")
        for i in range(40, 45):
            add(con, i, "SIDEWAYS", -0.3)
        con.close()

    def tick(self, age):
        with open(os.path.join(self.d, "v2_bt_auto_status.json"), "w") as f:
            json.dump({"last_tick": {"ts": 2_000_000_000 - age}}, f)

    def test_no_file(self):
        r = H.build(self.d, now=2_000_000_000)
        self.assertFalse(r["ready"])
        self.assertEqual(r["live"], "LOCKED")

    def test_states_missing_and_not_green(self):
        self.fill()
        r = H.build(self.d, now=2_000_000_000)
        st = {s["key"]: s for s in r["coverage"]["states"]}
        self.assertTrue(st["TREND"]["enough"])
        self.assertEqual(st["SIDEWAYS"]["n"], 5)
        self.assertFalse(st["SIDEWAYS"]["enough"])
        self.assertTrue(any("Sideways" in m for m in r["missing"]))
        self.assertEqual(r["graduation"][0]["state"], "PASS")        # 45 closed paper trades
        self.assertEqual(r["graduation"][1]["state"], "PENDING")     # no shadow trades
        self.assertEqual(r["headline"]["verdict"], "NOT READY")

    def test_use_row_holdout_confirms(self):
        self.fill()
        r = H.build(self.d, now=2_000_000_000)
        self.assertGreaterEqual(r["holdout"]["confirms"], 1)         # winners stay winners: CONFIRMS (before the fix: AGAINST)
        self.assertEqual(r["holdout"]["against"], 0)
        self.assertTrue(next(s for s in r["pipeline"] if s["key"] == "holdout")["done"])
        self.assertFalse(next(s for s in r["pipeline"] if s["key"] == "gate")["done"])

    def test_live_always_off(self):
        self.fill()
        r = H.build(self.d, now=2_000_000_000)
        live = r["graduation"][2]
        self.assertEqual((live["label"], live["state"]), ("LIVE", "OFF"))
        self.assertEqual(r["live"], "LOCKED")

    def test_runner(self):
        self.fill()
        self.assertEqual(H.build(self.d, now=2_000_000_000)["runner"]["state"], "NOT_RUNNING")
        self.tick(120)
        self.assertEqual(H.build(self.d, now=2_000_000_000)["runner"]["state"], "RUNNING")
        self.tick(3600)
        r = H.build(self.d, now=2_000_000_000)
        self.assertEqual(r["runner"]["state"], "STALE")
        self.assertTrue(r["missing"][0].startswith("Auto-runner"))

    def test_bad_input(self):
        self.fill()
        with self.assertRaises(ValueError):
            H.build(self.d, "LIVE")
        with self.assertRaises(ValueError):
            H.build(self.d, "PAPER", None, "1h")

    def test_route(self):
        import v2_data as D
        self.fill()
        self.assertIn("brain_health", D.ROUTES)
        self.assertIn("brain_health", D.VIEWS)
        os.makedirs(self.d, exist_ok=True)
        with open(os.path.join(self.d, D.FLAG_NAME), "w") as f:
            f.write("1")
        code, body = D.dispatch("brain_health", {"interval": "15m"}, self.d, 2_000_000_000)
        if code == 200:
            self.assertEqual(body["coverage"]["interval"], "15m")
        code, body = D.dispatch("brain_health", {"source": "LIVE"}, self.d, 2_000_000_000)
        self.assertIn(code, (400, 404))


if __name__ == "__main__":
    unittest.main(verbosity=2)
