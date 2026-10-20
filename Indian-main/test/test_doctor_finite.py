"""The Doctor reply must always be valid JSON, even if one trade holds inf / NaN. Run: python3 test/test_doctor_finite.py"""
import os, sys, json, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "backend"))
import test_strategy_doctor as T
from recovered_bot import strategy_doctor as D


def test_inf_values_cannot_break_the_json_reply():
    for field in ("peak_roi_pct", "roi_pct", "volume_ratio", "ema_gap_atr", "atr_pct"):
        d = T.make(400, 5)
        for t in d[:6]:
            t[field] = float("inf")
        d[7][field] = float("nan")
        out = D._finite(D.build_from(d))
        json.dumps(out, allow_nan=False)                 # raises if anything non-finite is left
    assert D._num(float("inf")) is None and D._num("-inf") is None and D._num(2) == 2.0


def test_finite_leaves_normal_numbers_alone():
    o = {"a": 1.5, "b": [2, {"c": 0.0}], "d": "x", "e": None, "f": float("nan")}
    assert D._finite(o) == {"a": 1.5, "b": [2, {"c": 0.0}], "d": "x", "e": None, "f": None}


if __name__ == "__main__":
    test_inf_values_cannot_break_the_json_reply(); test_finite_leaves_normal_numbers_alone(); print("PASS")
