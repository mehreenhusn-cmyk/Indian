"""Part 22 test (written, NOT RUN when delivered - owner asked for no test runs from Part 22): chart data-hole markers, forming / closed label, legend '--' before the bot's EMA exists.
Static checks of frontend/lib/widgets/candle_chart.dart + a Python mirror of chartGapIndexes. Dart cannot be compiled in the sandbox; the owner's APK build is the compile proof.
Run:  python3 test/test_v2_chart_marks.py"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "frontend", "lib", "widgets", "candle_chart.dart"), encoding="utf-8").read()


def gap_indexes(ts, step):                      # mirror of chartGapIndexes
    return [] if step <= 0 else [i for i in range(1, len(ts)) if ts[i] - ts[i - 1] > step * 1.5]


class Marks(unittest.TestCase):
    def test_gap_rule(self):
        s = 300000
        ts = [0, s, 2 * s, 4 * s, 5 * s, 9 * s]          # candle 3 follows one missing candle, candle 5 follows three
        self.assertEqual(gap_indexes(ts, s), [3, 5])
        self.assertEqual(gap_indexes([0, s, 2 * s], s), [])
        self.assertEqual(gap_indexes([0, int(s * 1.4)], s), [])      # small jitter is not a hole
        self.assertEqual(gap_indexes(ts, 0), [])                      # unknown step = no marks

    def test_source_has_the_marks(self):
        for t in ("List<int> chartGapIndexes(List<int> ts, int stepMs) {", "if (ts[i] - ts[i - 1] > stepMs * 1.5) out.add(i);",
                  "final gaps = chartGapIndexes(s.ts, gapStepMs).toSet();", "if (gaps.contains(i)) started = false;",
                  "_dashed(canvas, Offset(gx, 0), Offset(gx, plotH)", "forming ? '   forming' : '   closed'",
                  "s.ts[n - 1] + timeframeMs! > nowMs!", "idx >= 29 ? _fmtPrice(s.e30[idx]) : '--'", "idx >= 49 ? _fmtPrice(s.e50[idx]) : '--'"):
            self.assertIn(t, SRC)

    def test_no_new_import(self):
        self.assertNotIn("dart:io", SRC)


if __name__ == "__main__":
    unittest.main()
