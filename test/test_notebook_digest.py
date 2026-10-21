import sys, os, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_notebook_digest as D


class FakeV:
    _lock = threading.RLock()
    _state = {"trades": []}


def _t(pnl, side="BUY", src="bot", reason="stop hit"):
    return {"status": "closed", "pnl": pnl, "side": side, "source": src, "exit_reason": reason}


def test_small_sample_is_neutral():
    FakeV._state = {"trades": [_t(1), _t(-1, "SELL")]}
    r = D.build(FakeV)
    assert r["closed_n"] == 2
    assert any("hint, not a rule" in u for u in r["use"])
    assert any("Too few" in l for l in r["trade_lines"])


def test_own_losing_rule():
    tr = [_t(1.0) for _ in range(25)] + [_t(-1.0, src="own") for _ in range(25)]
    FakeV._state = {"trades": tr}
    r = D.build(FakeV)
    assert any("AI Own is losing" in u for u in r["use"])


def test_trail_logged_and_chart_ok():
    from recovered_bot import ai_vision_exits as XE
    t = {"side": "BUY", "sl": 90.0}
    assert XE.tighten_stop_only(t, 95.0)
    assert t["trail"][-1]["kind"] == "stop" and t["trail"][-1]["sl"] == 95.0
