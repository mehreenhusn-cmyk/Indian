"""Part 66: backend/v2_brain_ab.py. NOT RUN in the delivery (owner rule). Offline, temp folders only.  Run: python3 test/test_v2_brain_ab.py"""
import ast
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_brain_ab as B

D = B.DAY_MS


def make_db(base, trades=(), own=(), recs=()):
    c = sqlite3.connect(os.path.join(base, "dual_archive.db"))
    c.execute("CREATE TABLE trades (id TEXT PRIMARY KEY, t INTEGER, sym TEXT, tf TEXT, side INTEGER, src TEXT, status TEXT, net REAL, exit_rule TEXT, mode TEXT, saved REAL, js TEXT)")
    c.executemany("INSERT INTO trades (id, t, status, net) VALUES (?,?,?,?)", trades)
    c.commit()
    c.close()
    c = sqlite3.connect(os.path.join(base, "brain_archive.db"))
    c.execute("CREATE TABLE own (id TEXT PRIMARY KEY, t INTEGER, sym TEXT, tf TEXT, net REAL, stage TEXT, saved REAL, js TEXT)")
    c.execute("CREATE TABLE shadow_rec (id TEXT, t INTEGER, rule TEXT, st TEXT, roi REAL, tf TEXT, d INTEGER, rec TEXT, level TEXT, lean TEXT, why TEXT, ev TEXT, snap_t REAL, snap_trades INTEGER, saved REAL, PRIMARY KEY (id, t, rule))")
    c.executemany("INSERT INTO own (id, t, net) VALUES (?,?,?)", own)
    c.executemany("INSERT INTO shadow_rec (id, t, rule, roi, rec) VALUES (?,?,?,?,?)", recs)
    c.commit()
    c.close()


class ArmTest(unittest.TestCase):
    def test_drawdown_and_days(self):
        s = B.arm_stats([(0, 5), (1, -3), (2, -4), (D, 10)], target=5, loss=5)
        self.assertEqual(s["trades"], 4)
        self.assertEqual(s["total"], 8.0)
        self.assertEqual(s["max_drawdown"], 7.0)
        self.assertEqual((s["days"], s["days_up"], s["days_down"]), (2, 1, 1))
        self.assertEqual((s["best_day"], s["worst_day"]), (10.0, -2.0))
        self.assertEqual(s["days_at_target"], 2)
        self.assertEqual(s["days_at_loss"], 0)

    def test_empty(self):
        s = B.arm_stats([])
        self.assertEqual((s["trades"], s["expectancy"]), (0, None))


class PairedTest(unittest.TestCase):
    def test_thin_is_not_enough_data(self):
        self.assertEqual(B.paired([(i, 1.0) for i in range(10)])["verdict"], "NOT ENOUGH DATA")

    def test_clear_gain_is_a_hint(self):
        self.assertIn(B.paired([(i, 2.0 + (i % 3) * 0.1) for i in range(40)])["verdict"], ("EARLY HINT", "SUPPORTED"))

    def test_halves_must_agree(self):
        d = [(i, 5.0) for i in range(20)] + [(i + 20, -5.0) for i in range(20)]
        self.assertEqual(B.paired(d)["verdict"], "NO CLEAR PATTERN")


class ReportTest(unittest.TestCase):
    def test_protect_replaces_only_the_called_trade(self):
        with tempfile.TemporaryDirectory() as base:
            make_db(base, trades=[("a", 1, "closed", -5.0), ("b", 2, "closed", 3.0), ("c", 3, "open", 99.0)], own=[("o1", 4, 1.5)],
                    recs=[("a", 1, "r1", 2.0, "PROTECT_LOOKS_BETTER"), ("a", 2, "r1", 9.0, "PROTECT_LOOKS_BETTER"), ("b", 1, "r1", 1.0, "HOLD_OK")])
            r = B.build_report(base)
            self.assertEqual(r["arms"]["current_bot"]["total"], -2.0)
            self.assertEqual(r["arms"]["brain_protect_whatif"]["total"], 5.0)
            self.assertEqual(r["arms"]["brain_own"]["total"], 1.5)
            self.assertEqual(r["protect_vs_current"]["protect_calls"], 1)
            self.assertEqual(r["brain_filtered"]["status"], "NOT AVAILABLE")

    def test_missing_files_do_not_raise(self):
        with tempfile.TemporaryDirectory() as base:
            r = B.build_report(base)
            self.assertEqual(r["arms"]["current_bot"]["trades"], 0)
            self.assertTrue(r["notes"])

    def test_source_is_read_only_and_offline(self):
        src = open(os.path.join(ROOT, "backend", "v2_brain_ab.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
        mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        for bad in ("socket", "requests", "urllib", "http", "ccxt", "execution_router", "trade", "paper_trader"):
            self.assertNotIn(bad, mods)
        for bad in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP "):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
