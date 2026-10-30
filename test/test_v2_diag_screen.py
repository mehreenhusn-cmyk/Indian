"""Part 25 (Diagnostics 3 of 4): static checks for diag_history.dart + diagnostics_screen.dart.
NOT RUN in the delivery (owner rule: no useless tests). No Dart compile here.
"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "frontend", "lib")


def _read(*parts):
    with open(os.path.join(LIB, *parts), encoding="utf-8") as f:
        return f.read()


class DiagScreenTest(unittest.TestCase):
    def setUp(self):
        self.hist = _read("models", "diag_history.dart")
        self.screen = _read("screens", "diagnostics_screen.dart")
        self.card = _read("widgets", "diagnostics_card.dart")

    def test_history_is_pure_dart_and_bounded(self):
        self.assertNotIn("package:flutter", self.hist)
        self.assertIn("maxEvents = 200", self.hist)
        self.assertIn("removeLast()", self.hist)

    def test_only_level_changes_are_stored(self):
        self.assertIn("if (prev == i.level) continue;", self.hist)
        self.assertIn("prev == null && i.level == DiagLevel.unknown", self.hist)

    def test_screen_uses_same_status_as_the_strip(self):
        self.assertIn("buildDiagStatus(provider)", self.screen)
        self.assertIn("show buildDiagStatus", self.screen)

    def test_header_pinned_and_history_scrolls_alone(self):
        self.assertIn("PINNED", self.screen)
        self.assertIn("Expanded(", self.screen)
        self.assertIn("controller: _scroll", self.screen)

    def test_no_auto_scroll_and_jump_chip(self):
        self.assertIn("Jump to latest", self.screen)
        self.assertIn("_frozen", self.screen)

    def test_screen_is_read_only(self):
        for bad in ("http.", "Dio(", "placeOrder", "closeAll", "setLeverage"):
            self.assertNotIn(bad, self.screen)

    def test_card_opens_screen_and_records(self):
        self.assertIn("DiagnosticsScreen()", self.card)
        self.assertIn("DiagHistory.instance.record(diag)", self.card)


if __name__ == "__main__":
    unittest.main()
