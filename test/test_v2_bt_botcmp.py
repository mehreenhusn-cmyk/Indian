"""Part 87c test: backend/v2_bt_botcmp.py (Current Bot vs Brain on one coin, read-only). Offline, FAKE owl.db and FAKE closed-trade file in a temp folder.
Questions: open bot position found? only paper_b1 (not b2, not live)? last closed trade within 24 hours only? entry better / worse maths for LONG and SHORT? opposite side = no maths? nothing found = said plainly?
Run:  python3 test/test_v2_bt_botcmp.py"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_bt_botcmp as BC

NOW = 1_800_000_000.0


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="v2bc_")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def positions(self, rows):
        con = sqlite3.connect(os.path.join(self.d, "owl.db"))
        con.execute("CREATE TABLE positions (id TEXT PRIMARY KEY, data TEXT, updated_at REAL)")
        for i, r in enumerate(rows):
            con.execute("INSERT INTO positions VALUES (?,?,?)", (str(i), json.dumps(r), NOW))
        con.commit()
        con.close()

    def closed(self, rows):
        with open(os.path.join(self.d, "closed_trades_archive.jsonl"), "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")

    def test_nothing(self):
        r = BC.build(self.d, "BTCUSDT", 100.0, "LONG", NOW)
        self.assertEqual(r["state"], "NONE")
        self.assertNotIn("versus", r)

    def test_open_long_brain_better(self):
        self.positions([{"symbol": "BTCUSDT", "action": "BUY", "entry_price": 100.0, "ltp": 101.0, "opened_at_ts": NOW - 5400}])
        r = BC.build(self.d, "btcusdt", 99.5, "LONG", NOW)
        self.assertEqual((r["state"], r["side"], r["move_pct"], r["since"]), ("OPEN", "LONG", 1.0, "1h 30min"))
        self.assertEqual(r["versus"]["result"], "BETTER")
        self.assertEqual(r["versus"]["entry_better_pct"], 0.5)

    def test_short_maths_and_opposite(self):
        self.positions([{"symbol": "ETHUSDT", "action": "SELL", "entry_price": 200.0, "ltp": 198.0, "opened_at_ts": NOW - 600}])
        r = BC.build(self.d, "ETHUSDT", 199.0, "SHORT", NOW)
        self.assertEqual(r["move_pct"], 1.0)
        self.assertEqual(r["versus"], dict(r["versus"], result="WORSE", entry_better_pct=-0.5))      # a SHORT sells higher = better; 199 is lower than 200
        self.assertEqual(BC.build(self.d, "ETHUSDT", 199.0, "LONG", NOW)["versus"]["result"], "OPPOSITE")

    def test_only_paper_b1(self):
        self.positions([{"symbol": "BTCUSDT", "action": "BUY", "entry_price": 100.0, "ltp": 101.0, "bot": "b2"},
                        {"symbol": "BTCUSDT", "action": "BUY", "entry_price": 100.0, "ltp": 101.0, "source": "live"}])
        self.assertEqual(BC.build(self.d, "BTCUSDT", 99.0, "LONG", NOW)["state"], "NONE")

    def test_last_closed_within_24h(self):
        self.closed([{"id": "a", "symbol": "SOLUSDT", "action": "BUY", "entry_price": 50.0, "pnl_usdt": 1.5, "closed_at_ts": NOW - 3600},
                     {"id": "b", "symbol": "SOLUSDT", "action": "BUY", "entry_price": 40.0, "pnl_usdt": 9.0, "closed_at_ts": NOW - 90000}])
        r = BC.build(self.d, "SOLUSDT", 49.0, "LONG", NOW)
        self.assertEqual((r["state"], r["entry"], r["net_usdt"], r["since"]), ("LAST_CLOSED", 50.0, 1.5, "1h 00min"))
        self.assertEqual(r["versus"]["entry_better_pct"], 2.0)
        self.assertEqual(BC.build(self.d, "SOLUSDT", None, None, NOW + 86400)["state"], "NONE")        # a day later the trade is too old


if __name__ == "__main__":
    unittest.main(verbosity=2)
