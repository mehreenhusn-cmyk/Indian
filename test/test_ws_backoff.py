"""Binance WS reconnect wait: grows when nothing arrives, goes back to 1 s after a connection that worked.
No network. Run: python3 test/test_ws_backoff.py"""
import json
import os
import sys
import threading
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def main():
    from recovered_bot import market_ws as M

    script = []          # per connection: True = it delivers one price event, False = silent drop

    class FakeApp:
        def __init__(self, url, on_message=None, on_error=None, on_close=None, on_open=None):
            self.on_message, self.on_open = on_message, on_open

        def run_forever(self, **kw):
            ok = script.pop(0)
            if ok:
                self.on_message(self, json.dumps({"e": "markPriceUpdate", "s": "BTCUSDT", "p": "100.5", "E": 1}))

        def send(self, *a, **k):
            pass

        def close(self):
            pass

    fake = types.ModuleType("websocket")
    fake.WebSocketApp = FakeApp
    sys.modules["websocket"] = fake
    M._live_cache["BTCUSDT"] = {"price": 1.0, "change_pct": 0.0, "updated_at": 0.0}

    waits = []

    class Stop:
        def __init__(self):
            self.n = 0

        def is_set(self):
            return self.n >= len(plan)

        def wait(self, s):
            waits.append(s)
            self.n += 1
            return False

    # silent, silent, silent, then one that WORKED, then silent again
    plan = [False, False, False, True, False]
    script[:] = list(plan)
    M._binance_ws_loop(Stop())
    assert len(waits) == 5, waits
    base = [1, 2, 4, 1, 1]                       # 4th wait is back to 1 s because that connection delivered data; 5th: new drop
    expect = [1, 2, 4, 1, 2]
    for w, e in zip(waits, expect):
        assert 0.8 * e - 1e-9 <= w <= 1.2 * e + 1e-9, (waits, expect)
    assert len(set(round(w, 6) for w in waits[:2])) == 2          # not all identical: has a random spread

    print("PASS test_ws_backoff", [round(w, 2) for w in waits])


if __name__ == "__main__":
    main()
