"""Vision results: indicator_use counts and lesson notes. Run: python3 test/test_vision_indicator_use.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_vision as V

decs = [
    {"decision": "TAKE", "checklist": {"ema": "30 above 50", "sd_zone": "inside 1 SD", "tsi": "buy side", "zscore": "Z up"}},
    {"decision": "SKIP", "checklist": {"ema": "flat", "sd_zone": "", "tsi": "", "zscore": ""}},      # EMA only
    {"decision": "WAIT", "checklist": {"ema": "", "sd_zone": "stretched", "tsi": "cooling", "zscore": ""}},
    {"decision": None, "checklist": {}},                                                                # not judged yet
]
u = V._indicator_use(decs)
assert u == {"n": 3, "ema": 2, "sd": 2, "tsi": 2, "zscore": 1, "both": 2}, u
assert V._indicator_use([])["n"] == 0
s = V.snapshot(5)
assert "indicator_use" in s and "n" in s["indicator_use"], s.keys()
print("PASS test_vision_indicator_use")
