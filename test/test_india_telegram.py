"""India Telegram: card text, 5m/15m timing, nothing in demo, no duplicates, token never leaks, bot untouched."""
import os
import sys
import tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "backend"))

from recovered_bot import india_telegram as T          # noqa: E402
from recovered_bot import india_runtime as R           # noqa: E402
from recovered_bot.india_data import IST               # noqa: E402
from recovered_bot.strategy import Signal              # noqa: E402

TOKEN = "123456:TEST-TOKEN-NOT-REAL"


def sig(action="BUY", entry=24512.35):
    long_ = action == "BUY"
    d = 1 if long_ else -1
    return Signal(symbol="NIFTY", action=action, entry_price=entry, stop_loss=entry - d * 40,
                  tp1=entry + d * 30, tp2=entry + d * 60, tp3=entry + d * 90, tp4=entry + d * 120,
                  signal_time="x", current_price=entry)


def test_card():
    opened = datetime(2026, 10, 19, 14, 15, tzinfo=IST)
    sent = opened + timedelta(minutes=15, seconds=7)
    c = T.format_card(sig("BUY"), "NIFTY", 15, 7, opened, sent, itm_depth=1)
    assert c.startswith("🟢 LONG SIGNAL") and "Signal #   : 7" in c and "Timeframe  : 15m" in c
    assert "NIFTY 24500 CE" in c, c                    # nearest in-the-money strike (same helper the bot uses)
    assert "(7s after close)" in c and "14:15 - 14:30" in c and "tradingview" not in c.lower()
    assert "Stop Loss  : 24472.35 (0.16%)" in c
    p = T.format_card(sig("SELL"), "BANKNIFTY", 5, 1, opened, sent)
    assert p.startswith("🔴 SHORT SIGNAL") and " PE" in p and "SELL (Put)" in p


def test_boundary_and_session():
    now = datetime(2026, 10, 19, 14, 31, 5, tzinfo=IST)
    assert T.boundary(now, 15).strftime("%H:%M") == "14:30"
    assert T.boundary(now, 5).strftime("%H:%M") == "14:30"
    c = lambda h, m: datetime(2026, 10, 19, h, m, tzinfo=IST)
    assert not T.in_session(c(9, 15), 15) and T.in_session(c(9, 30), 15) and T.in_session(c(15, 30), 15)
    assert not T.in_session(c(15, 45), 15) and T.in_session(c(9, 20), 5) and not T.in_session(c(9, 15), 5)


class FakeLive:
    is_live = True
    name = "fyers"

    def __init__(self, opened):
        self.opened, self.calls = opened, 0

    def get_candles(self, u, tf, limit):
        self.calls += 1
        return [{"t": self.opened, "o": 1, "h": 1, "l": 1, "c": 1, "v": 0}]


class FakeStrategy:
    def __init__(self, s):
        self.s, self.n = s, 0

    def generate_signal(self, candles, symbol, tf_min=None):
        self.n += 1
        return self.s


def make(tmp):
    rt = R.IndiaRuntime(tmp)
    return rt, rt.tg


def run():
    posted = []
    tmp = tempfile.mkdtemp()
    rt, tg = make(tmp)
    tg._post = lambda text, token, chat, kind: (posted.append((text, kind)) or (True, "sent"))
    day = datetime(2026, 10, 19, 14, 30, 8, tzinfo=IST)          # a Monday, 8s after the 14:30 close
    opened = datetime(2026, 10, 19, 14, 15, tzinfo=IST)

    # 1) disabled / demo / no credentials -> nothing, and the feed is not even asked
    assert tg.tick(day) == [] and tg.note == "Off"
    rt.update_settings({"tg_enabled": True, "tg_tf": 15, "underlyings": ["NIFTY"]})
    tg.strategy = FakeStrategy(sig())
    assert tg.tick(day) == [] and "demo" in tg.note                 # rt.live is None
    rt.live = FakeLive(opened)
    assert tg.tick(day) == [] and "not set" in tg.note              # no token yet
    tg.save_creds(TOKEN, "999")
    assert tg.strategy.n == 0 and rt.live.calls == 0

    # 2) token is saved on the server only and the API view is masked
    assert TOKEN not in str(tg.info()) and tg.info()["token_saved"] and tg.info()["chat_id"] == "999"
    assert TOKEN not in str(rt.settings)
    assert oct(os.stat(os.path.join(tmp, "india_broker.json")).st_mode & 0o777) == "0o600"

    # 3) a closed 15m candle -> exactly one card; same candle again -> nothing
    out = tg.tick(day)
    assert len(out) == 1 and len(posted) == 1 and posted[0][1] == "signal" and "Signal #   : 1" in out[0]
    assert tg.tick(day) == [] and tg.tick(day + timedelta(seconds=30)) == [] and len(posted) == 1
    assert rt.live.calls == 1                                       # one candle fetch for the whole candle

    # 4) a restart does not repeat the same signal
    rt2, tg2 = make(tmp)
    tg2._post = tg._post
    rt2.update_settings({"tg_enabled": True, "underlyings": ["NIFTY"]})
    rt2.live = FakeLive(opened)
    tg2.strategy = FakeStrategy(sig())
    assert tg2.tick(day) == [] and len(posted) == 1

    # 5) feed late: wait, then give up (never a stale signal later); a different candle is never signalled
    rt3, tg3 = make(tempfile.mkdtemp())
    tg3._post = tg._post
    rt3.update_settings({"tg_enabled": True, "tg_tf": 5, "underlyings": ["NIFTY"]})
    tg3.save_creds(TOKEN, "1")
    tg3.strategy = FakeStrategy(sig())
    rt3.live = FakeLive(datetime(2026, 10, 19, 14, 20, tzinfo=IST))   # feed still on the 14:20 candle
    t5 = datetime(2026, 10, 19, 14, 30, 10, tzinfo=IST)               # 5m candle 14:25-14:30 expected
    assert tg3.tick(t5) == [] and tg3.strategy.n == 0 and tg3._checked == {}
    assert tg3.tick(t5 + timedelta(seconds=130)) == [] and tg3._checked      # gave up, marked done
    assert "late" in tg3.note and tg3.strategy.n == 0

    # 6) market closed / weekend -> silent
    rt3.live = FakeLive(opened)
    assert tg3.tick(datetime(2026, 10, 19, 16, 0, tzinfo=IST)) == []
    assert tg3.tick(datetime(2026, 10, 17, 11, 0, tzinfo=IST)) == []        # Saturday

    # 7) telegram errors never contain the token
    assert TOKEN not in T._clean(f"HTTPSConnectionPool url=/bot{TOKEN}/sendMessage", TOKEN)

    # 8) settings validation
    try:
        rt.update_settings({"tg_tf": 3})
        raise AssertionError("tg_tf 3 must be rejected")
    except ValueError:
        pass
    assert rt.settings["tg_tf"] == 15
    # the bot's own runner is not the watcher's strategy object
    assert tg.strategy is not rt.runner.strategy


if __name__ == "__main__":
    test_card()
    test_boundary_and_session()
    run()
    print("india telegram tests: OK")
