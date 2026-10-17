"""Part 1A: entry_context tags + strategy still fires + post-exit tracker. Run: python3 test/test_part1a.py"""
import os, sys, tempfile, time, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import entry_context, ai_post_exit
from recovered_bot.strategy import ABCDStrategy


def _candles(n, drift=0.0, amp=1.0, start=100.0):
    out, p = [], start
    for i in range(n):
        o = p
        p = p + drift + amp * math.sin(i / 3.0)
        out.append({"timestamp": 1_700_000_000_000 + i * 300_000, "open": o, "high": max(o, p) + 0.3,
                    "low": min(o, p) - 0.3, "close": p, "volume": 100.0})
    return out


def test_adx_trend_higher_than_chop():
    trend = entry_context.adx(_candles(120, drift=0.8, amp=0.2))
    chop = entry_context.adx(_candles(120, drift=0.0, amp=1.0))
    assert trend is not None and chop is not None and trend > chop


def test_short_input_returns_none_not_error():
    assert entry_context.adx(_candles(10)) is None
    assert entry_context.htf_trend(_candles(30)) is None
    assert entry_context.ema_gap_atr(_candles(5), 100.0) is None
    assert entry_context.build([], None) == (None, None, None)


def test_htf_trend_direction():
    assert entry_context.htf_trend(_candles(250, drift=0.5, amp=0.1)) == "up"
    assert entry_context.htf_trend(_candles(250, drift=-0.5, amp=0.1, start=500)) == "down"


def test_gap_is_positive_number():
    c = _candles(60)
    g = entry_context.ema_gap_atr(c, c[-1]["close"] - 2.0)
    assert g is not None and g > 0


def test_strategy_signal_carries_tags_and_never_breaks():
    s = ABCDStrategy()
    fired = None
    c = _candles(260, drift=0.0, amp=2.0)
    for end in range(max(s.lookback_len, s.ema_length) + 2, len(c)):
        sig = s.generate_signal(c[:end], "TESTUSDT", 5)
        if sig:
            fired = sig
            break
    assert fired is not None
    assert hasattr(fired, "adx") and hasattr(fired, "ema_gap_atr") and hasattr(fired, "htf_trend")


def test_post_exit_tracks_and_writes():
    d = tempfile.mkdtemp()
    ai_post_exit.init(d)
    ai_post_exit.WATCH_MIN = 0          # finish on the first poll
    ai_post_exit.POLL_S = 0.05
    ai_post_exit._price = lambda s: 110.0
    pos = {"id": 7, "opened_at_ts": time.time() - 600, "symbol": "TESTUSDT", "action": "BUY", "entry_price": 100.0,
           "exit_price": 105.0, "leverage": 10, "closed_at_ts": time.time() - 1, "timeframe": "5m"}
    ai_post_exit.start(pos, "TP4")
    for _ in range(60):
        rows = ai_post_exit.read_all()
        if rows:
            break
        time.sleep(0.1)
    assert rows and rows[0]["best_after"] > 0 and rows[0]["symbol"] == "TESTUSDT"


def test_post_exit_bad_input_is_ignored():
    ai_post_exit.start({}, "SL")        # must not raise


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); n += 1; print("ok", name)
    print(n, "tests passed")
