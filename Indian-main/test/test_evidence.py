"""Evidence engine: tags are side-relative, patterns need the 60/40 check, nothing is invented."""
import os, sys, threading, math, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from recovered_bot import ai_evidence as EV


def _candles(n=400):
    now = int(time.time() * 1000)
    out = []
    for i in range(n):
        p = 100 + 5 * math.sin(i / 15) + i * 0.02
        out.append({"timestamp": now - (n - i) * 900000, "open": p, "high": p + 0.6, "low": p - 0.6, "close": p + 0.2, "volume": 1000 + i})
    return out


def test_tags_side_relative():
    from recovered_bot import ai_vision as V
    f, _e, _lv = V._levels(_candles())
    b, s = EV.extra_tags(f, "BUY"), EV.extra_tags(f, "SELL")
    assert b and s and b["regime"] in ("TRENDING", "MIXED", "CHOPPY", "EXPANSION", "EXHAUSTION")
    assert b["tsi_zero"] != s["tsi_zero"], "TSI vs zero must flip with the side"
    assert b["sd_zone"] != s["sd_zone"] or b["sd_zone"] == "SD0..1"


class FakeV:
    _lock = threading.RLock()
    _state = {"dec": [], "trades": []}

    @staticmethod
    def _bot_outcomes():
        return {"closed": FakeV.closed}


def test_pattern_needs_both_halves():
    decs, closed = [], {}
    for i in range(60):
        good = i % 2 == 0
        decs.append({"id": f"s{i}", "signal_no": i, "source": "bot", "status": "skipped", "sig_time": 1000 + i,
                     "tags2": {"sd_zone": "SD>2" if good else "SD0..1"}, "feat": {}})
        closed[i] = -1.0 if good else 0.8        # SD>2 always loses, on old AND new part
    FakeV._state = {"dec": decs, "trades": []}
    FakeV.closed = closed
    r = EV.snapshot(FakeV, force=True)
    bad = r["bot_patterns"]["bad"]
    assert bad and "sd_zone=SD>2" in bad[0]["pattern"], bad
    assert r["bot_patterns"]["blocked_new"]["net"] < 0, "blocking them would have saved money on the NEW part"
    names = [t["name"] for t in r["table"]]
    assert "Bot alone (every signal)" in names and r["table"][0]["n"] == 60


def test_small_sample_says_so():
    FakeV._state = {"dec": [], "trades": []}
    FakeV.closed = {}
    r = EV.snapshot(FakeV, force=True)
    assert r["bot_patterns"]["good"] == [] and "Needs" in r["bot_patterns"]["note"]


if __name__ == "__main__":
    test_tags_side_relative()
    test_pattern_needs_both_halves()
    test_small_sample_says_so()
    print("ALL test_evidence passed")
