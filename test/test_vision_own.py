"""Own scanner caps, source split, id collision, old state as bot."""
import os, sys, tempfile, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from recovered_bot import ai_vision as V
from recovered_bot import ai_vision_own as OWN

def test_old_source_is_bot():
    with tempfile.TemporaryDirectory() as td:
        V.init(td)
        V._loaded = True
        with V._lock:
            V._state["trades"] = [{"id": "v1", "status": "closed", "pnl": 1.0, "side": "BUY"}]
            V._state["dec"] = []
        cmp = OWN.compare(V)
        assert cmp["bot"]["closed"] == 1
        assert cmp["own"]["closed"] == 0
        print("old source -> bot OK")

def test_ids_and_caps():
    a, b, n = OWN._next_own_ids()
    c, d, m = OWN._next_own_ids()
    assert a != c and b != d and n != m
    assert a.startswith("o") and b.startswith("vo")
    assert n >= 900000
    print("ids OK", a, b, n)

def test_stats_not_mixed():
    with tempfile.TemporaryDirectory() as td:
        V.init(td)
        V._loaded = True
        with V._lock:
            V._state["trades"] = [
                {"id": "v1", "status": "closed", "source": "bot", "side": "BUY", "pnl": 2.0, "roi": 5},
                {"id": "vo1", "status": "closed", "source": "own", "side": "SELL", "pnl": -1.0, "roi": -3},
                {"id": "vo2", "status": "open", "source": "own", "side": "BUY", "pnl": 0},
            ]
            V._state["dec"] = []
        cmp = OWN.compare(V)
        assert cmp["bot"]["closed"] == 1 and cmp["bot"]["net"] == 2.0
        assert cmp["own"]["closed"] == 1 and cmp["own"]["open"] == 1
        assert cmp["bot"]["buy"]["n"] == 1
        assert cmp["own"]["sell"]["n"] == 1
        assert cmp["own"]["small_sample"] is True
        print("per-source stats OK", cmp["bot"], cmp["own"])

def test_empty_watchlist_no_crash():
    # force empty
    orig = OWN._watchlist
    OWN._watchlist = lambda: []
    try:
        with tempfile.TemporaryDirectory() as td:
            V.init(td)
            V._loaded = True
            assert OWN.tick(V) is False
        print("empty watchlist OK")
    finally:
        OWN._watchlist = orig

if __name__ == "__main__":
    test_old_source_is_bot()
    test_ids_and_caps()
    test_stats_not_mixed()
    test_empty_watchlist_no_crash()
    print("ALL test_vision_own passed")
