"""Part 26 (Diagnostics 4 of 4): static checks for the pinned health strip. NOT RUN in the delivery."""
import os
import unittest

LIB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "lib")


def _read(*p):
    with open(os.path.join(LIB, *p), encoding="utf-8") as f:
        return f.read()


class PinnedStripTest(unittest.TestCase):
    def test_strip_is_outside_the_scroll_view(self):
        d = _read("screens", "dashboard_screen.dart")
        i = d.index("const DiagPinnedStrip()")
        j = d.index("SingleChildScrollView(", i)
        self.assertLess(i, j)
        self.assertIn("Expanded(", d[i:j])

    def test_same_status_source_as_card_and_page(self):
        s = _read("widgets", "diag_pinned_strip.dart")
        self.assertIn("buildDiagStatus(provider)", s)
        self.assertIn("DiagnosticsScreen()", s)

    def test_strip_is_read_only(self):
        s = _read("widgets", "diag_pinned_strip.dart")
        for bad in ("http.", "Dio(", "placeOrder", "closeAll"):
            self.assertNotIn(bad, s)


if __name__ == "__main__":
    unittest.main()
