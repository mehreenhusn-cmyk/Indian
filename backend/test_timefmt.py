"""Run: python test_timefmt.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timefmt import mins, span

cases = [(span(0), "0 s"), (span(45), "45 s"), (span(59.6), "1 min"), (span(60), "1 min"), (span(3599), "59 min"), (span(3600), "1 h"),
         (span(3660), "1 h 1 min"), (mins(70), "1 h 10 min"), (mins(130), "2 h 10 min"), (mins(220), "3 h 40 min"), (mins(280), "4 h 40 min"),
         (mins(59), "59 min"), (mins(60), "1 h"), (mins(1440), "1 d"), (mins(1700), "1 d 4 h"), (span(-5), "0 s"), (span(None), "-"), (mins("x"), "-")]
bad = [(a, b) for a, b in cases if a != b]
for a, b in bad:
    print("FAIL", repr(a), "!=", repr(b))
print("%d passed, %d failed" % (len(cases) - len(bad), len(bad)))
sys.exit(1 if bad else 0)
