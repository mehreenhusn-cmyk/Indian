"""loop_watch labels: OUR CODE BUSY vs PHONE PAUSED?. Run: python3 test/test_stall_cause.py"""
import os
import sys
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from recovered_bot import loop_watch as lw


def test_snapshot_empty():
    s = lw.snapshot()
    assert isinstance(s, dict)
    assert "loop_lag_ms" in s
    assert "stalls_10min" in s
    assert s.get("last_stall") is None or isinstance(s["last_stall"], dict)


def test_cause_our_code_busy():
    """Simulate watcher capturing a stack -> OUR CODE BUSY."""
    # inject a finished stall directly
    lw._stalls.append({
        "ts": time.time(),
        "ms": 2200,
        "where": "api_server.py:2090 sleep",
        "cause": "OUR CODE BUSY",
    })
    s = lw.snapshot()
    last = s.get("last_stall")
    assert last is not None
    assert last["cause"] == "OUR CODE BUSY"
    assert "api_server" in (last.get("where") or "")


def test_cause_phone_paused():
    lw._stalls.append({
        "ts": time.time(),
        "ms": 5000,
        "where": "(not captured)",
        "cause": "PHONE PAUSED?",
    })
    s = lw.snapshot()
    last = s.get("last_stall")
    assert last is not None
    assert last["cause"] == "PHONE PAUSED?"


def test_short_stack():
    # just ensure _short never raises
    out = lw._short(sys._getframe())
    assert isinstance(out, str) and len(out) > 0


if __name__ == "__main__":
    test_snapshot_empty()
    test_cause_our_code_busy()
    test_cause_phone_paused()
    test_short_stack()
    print("PASS test_stall_cause")
