"""Part 24 (Diagnostics 2 of 4): static checks for the health strip in diagnostics_card.dart.
NOT RUN in the delivery (owner rule: no useless tests). No Dart compile here.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARD = os.path.join(ROOT, "frontend", "lib", "widgets", "diagnostics_card.dart")
MODEL = os.path.join(ROOT, "frontend", "lib", "models", "diag_status.dart")
API = os.path.join(ROOT, "backend", "recovered_bot", "status.py")


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


class DiagCardTest(unittest.TestCase):
    def setUp(self):
        self.card = _read(CARD)

    def test_uses_shared_model(self):
        self.assertIn("import '../models/diag_status.dart';", self.card)
        self.assertIn("DiagStatus.fromInputs(", self.card)
        self.assertIn("buildDiagStatus(provider)", self.card)

    def test_all_six_inputs_are_passed(self):
        for name in ("backendReachable", "wsConnected", "liveAgeSec", "marketDataState",
                     "scannerActive", "strategyReady", "executionHealthy"):
            self.assertRegex(self.card, name + r":")

    def test_status_keys_exist_in_backend(self):
        if not os.path.exists(API):
            self.skipTest("backend status.py not in this tree")
        status_py = _read(API)
        for key in ("last_poll_cycle_ts", "last_error", "symbols_tracked",
                    "last_guard_tick", "market_data_state"):
            self.assertIn('"%s"' % key, status_py)

    def test_unknown_is_never_green(self):
        # no input falls back to true: nothing like "?? true"
        self.assertNotRegex(self.card, r"\?\?\s*true")

    def test_strip_and_detail_widgets_exist(self):
        self.assertIn("class _HealthStrip", self.card)
        self.assertIn("class _HealthDetail", self.card)
        self.assertIn("_HealthStrip(diag: diag)", self.card)
        self.assertIn("_HealthDetail(diag: diag)", self.card)

    def test_old_rows_kept(self):
        for old in ("label: 'Socket'", "label: 'Feed'", "label: 'Latency'", "label: 'Signal lag'",
                    "_ApiErrorBanner(", "_syncTelemetryBaseline(provider)"):
            self.assertIn(old, self.card)

    def test_model_untouched_and_pure(self):
        model = _read(MODEL)
        self.assertNotIn("import ", model)

    def test_brackets_balanced(self):
        for a, b in ("()", "{}", "[]"):
            self.assertEqual(self.card.count(a), self.card.count(b))


if __name__ == "__main__":
    unittest.main()
