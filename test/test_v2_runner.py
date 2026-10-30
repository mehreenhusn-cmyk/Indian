"""Part 72: backend/v2_runner.py (collector auto-start). NOT RUN in the delivery (owner rule). Offline, temp folders only, nothing is really started.
Run: python3 test/test_v2_runner.py"""
import ast
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_candles as K
import v2_collector as C
import v2_runner as R


class FirstOnTest(unittest.TestCase):
    def test_first_start_switches_on_once_only(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(R.first_on(d))
            self.assertTrue(C.is_enabled(d) and K.is_enabled(d))
            C.set_enabled(d, False)                      # the owner switches the ticker collector OFF
            self.assertFalse(R.first_on(d))              # a later start must NOT switch it back on
            self.assertFalse(C.is_enabled(d))

    def test_a_linked_switch_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            os.symlink(os.path.join(d, "elsewhere"), os.path.join(d, C.FLAG_NAME))
            with self.assertRaises(Exception):
                R.first_on(d)


class SpawnTest(unittest.TestCase):
    def setUp(self):
        self.calls, self.real = [], R.subprocess.Popen
        R.subprocess.Popen = lambda *a, **k: self.calls.append(a) or object()
        R._SPAWN["t"] = 0.0

    def tearDown(self):
        R.subprocess.Popen = self.real

    def test_starts_one_worker_when_no_heartbeat(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(R.ensure_running(d))
            self.assertEqual(len(self.calls), 1)
            self.assertFalse(R.ensure_running(d))        # started less than a minute ago
            self.assertEqual(len(self.calls), 1)

    def test_no_second_worker_while_the_heartbeat_is_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            R.write_beat(d)
            self.assertFalse(R.ensure_running(d))
            self.assertEqual(self.calls, [])

    def test_a_stale_heartbeat_starts_a_new_worker(self):
        with tempfile.TemporaryDirectory() as d:
            R.write_beat(d)
            old = time.time() - R.BEAT_STALE_S - 30
            os.utime(os.path.join(d, R.BEAT_FILE), (old, old))
            import json
            with open(os.path.join(d, R.BEAT_FILE), "w") as f:
                json.dump({"beat": old}, f)
            self.assertTrue(R.ensure_running(d))

    def test_never_raises_on_a_bad_folder(self):
        self.assertFalse(R.ensure_running("/definitely/not/here/\0"))


class StatusTest(unittest.TestCase):
    def test_status_reports_switches(self):
        with tempfile.TemporaryDirectory() as d:
            s = R.status(d)
            self.assertEqual((s["running"], s["ticker_switch"], s["candle_switch"], s["first_on_done"]), (False, "OFF", "OFF", False))


class GuardTest(unittest.TestCase):
    def test_runner_has_no_network_or_trading_code_of_its_own(self):
        src = open(os.path.join(ROOT, "backend", "v2_runner.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
        mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        for bad in ("socket", "requests", "urllib", "http", "ccxt", "execution_router", "paper_trader", "trade_archive", "smart_brain"):
            self.assertNotIn(bad, mods)

    def test_backend_starts_the_watchdog_in_a_wrapped_block(self):
        s = open(os.path.join(ROOT, "backend", "api_server.py"), encoding="utf-8").read()
        i = s.index("import v2_runner")
        self.assertIn("v2_runner.start_watchdog(DATA_DIR, 45.0)", s[i:i + 200])
        self.assertIn("v2 collector runner skipped", s[i:i + 400])


if __name__ == "__main__":
    unittest.main()
