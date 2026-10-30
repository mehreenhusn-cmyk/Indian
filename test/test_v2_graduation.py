"""Part 69: backend/v2_graduation.py. NOT RUN in the delivery (owner rule). Offline, temp folders only.  Run: python3 test/test_v2_graduation.py"""
import ast
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "test"))
import v2_graduation as G
from test_v2_brain_ab import make_db

D = G.DAY_MS
NOW = 100 * 86400.0


def good(n=240, step=D // 8, start=0):
    """n trades, mostly small wins, a few small losses, spread over many days, ends just before NOW."""
    end = int(NOW * 1000) - 1000
    return [(end - (n - i) * step, (2.0 if i % 4 else -1.0)) for i in range(n)]


def state(r, key):
    return [c["state"] for c in r["checks"] if c["key"] == key][0]


class VerdictTest(unittest.TestCase):
    def test_no_trades_is_not_enough_data(self):
        r = G.evaluate([], NOW)
        self.assertEqual(r["verdict"], "NOT ENOUGH DATA")
        self.assertEqual(r["failed"], 0)

    def test_thin_data_never_fails_or_passes_the_result(self):
        r = G.evaluate([(NOW * 1000 - i * 1000, -3.0) for i in range(10)], NOW)
        self.assertEqual((state(r, "net"), state(r, "recovery")), ("wait", "wait"))
        self.assertEqual(r["verdict"], "NOT ENOUGH DATA")

    def test_healthy_long_history_passes_everything(self):
        r = G.evaluate(good(), NOW)
        self.assertEqual(r["verdict"], "GATE PASSED (paper)", r["checks"])
        self.assertEqual(r["passed"], 7)

    def test_a_losing_bot_is_not_ready(self):
        rows = [(t, -x) for t, x in good()]
        r = G.evaluate(rows, NOW)
        self.assertEqual(r["verdict"], "NOT READY")
        self.assertEqual(state(r, "net"), "fail")

    def test_deep_drawdown_fails_recovery(self):
        rows = good(240)
        rows = [(t, -40.0 if i == 60 else x) for i, (t, x) in enumerate(rows)]
        self.assertEqual(state(G.evaluate(rows, NOW), "recovery"), "fail")

    def test_a_bad_last_two_weeks_fails_recent(self):
        end = int(NOW * 1000) - 1000
        rows = good(240)[:200] + [(end - i * 1000, -5.0) for i in range(15)]
        self.assertEqual(state(G.evaluate(rows, NOW), "recent"), "fail")

    def test_old_data_only_waits_on_recent(self):
        self.assertEqual(state(G.evaluate(good(), NOW + 40 * 86400), "recent"), "wait")

    def test_same_rows_same_answer(self):
        self.assertEqual(G.evaluate(good(), NOW), G.evaluate(list(reversed(good())), NOW))


class ReportTest(unittest.TestCase):
    def test_two_arms_and_the_what_if_is_not_used(self):
        with tempfile.TemporaryDirectory() as base:
            make_db(base, trades=[("a", 1, "closed", 2.0)], own=[("o", 2, 1.0)], recs=[("a", 1, "r1", 9.0, "PROTECT_LOOKS_BETTER")])
            r = G.build_report(base, NOW)
            self.assertEqual(set(r["arms"]), {"current_bot", "brain_own"})
            self.assertEqual(r["arms"]["current_bot"]["numbers"]["total"], 2.0)
            self.assertTrue(r["paper_only"])

    def test_missing_files_do_not_raise(self):
        with tempfile.TemporaryDirectory() as base:
            r = G.build_report(base, NOW)
            self.assertEqual(r["arms"]["current_bot"]["verdict"], "NOT ENOUGH DATA")
            self.assertTrue(r["notes"])

    def test_source_is_read_only_and_offline(self):
        src = open(os.path.join(ROOT, "backend", "v2_graduation.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
        mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        for bad in ("socket", "requests", "urllib", "http", "ccxt", "execution_router", "paper_trader", "subprocess"):
            self.assertNotIn(bad, mods)
        for bad in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP "):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
