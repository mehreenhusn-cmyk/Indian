"""Partial P&L, stop tighten, zone stats SMALL SAMPLE."""
import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from recovered_bot import ai_vision_exits as XE

def test_partial_math():
    tr = {"side": "BUY", "entry": 100.0, "lev": 1, "invest": 10.0, "fee_roi": 1.0, "partial_done": False, "sl": 99.0}
    # price 102 -> gross ROI 2%, frac 0.5, fee 0.5 -> net 0.5% of full -> pnl 0.05? 
    # apply_partial: net = gross*frac - fee*frac... uses fee_roi * frac
    pnl = XE.apply_partial(tr, 102.0, 0.5)
    assert tr["partial_done"] is True
    assert abs(tr["invest"] - 5.0) < 1e-6
    assert pnl is not None
    # second partial blocked
    assert XE.apply_partial(tr, 103.0, 0.5) is None
    print("partial OK", pnl, tr["partial_pnl"])

def test_stop_never_loosened():
    tr = {"side": "BUY", "sl": 100.0}
    assert XE.tighten_stop_only(tr, 99.0) is False
    assert XE.tighten_stop_only(tr, 101.0) is True and tr["sl"] == 101.0
    tr2 = {"side": "SELL", "sl": 100.0}
    assert XE.tighten_stop_only(tr2, 101.0) is False
    assert XE.tighten_stop_only(tr2, 99.0) is True
    print("stop tighten OK")

def test_zone_stats_small():
    with tempfile.TemporaryDirectory() as td:
        XE.init(td)
        XE._loaded = True
        XE._state = {"rows": [], "stats": {}}
        for i in range(5):
            XE.record_closed({
                "id": f"t{i}", "symbol": "BTCUSDT", "side": "BUY", "source": "bot",
                "peak_roi": 2.0 if i < 3 else 0.5, "roi": -1.0 if i < 2 else 1.0,
                "pnl": -0.5 if i < 2 else 0.5, "tgt_bar": 1 if i == 0 else 0,
            })
        snap = XE.snapshot()
        assert snap["total"] == 5
        assert any("SMALL SAMPLE" in x for x in snap["plain"])
        print("zone stats OK", snap["plain"])

if __name__ == "__main__":
    test_partial_math()
    test_stop_never_loosened()
    test_zone_stats_small()
    print("ALL test_vision_exits passed")
