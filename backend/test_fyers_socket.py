"""Fyers WebSocket tests - fake socket, no network."""
import json, os, sys, time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot import fyers_client as FC, fyers_provider as FP
from recovered_bot import fyers_socket as FS
from recovered_bot.india_data import IST

SOCKS = []


class FakeSock:
    def __init__(self, token, on_open, on_message, on_error, on_close):
        self.token, self.on_open, self.on_message, self.on_error, self.on_close = token, on_open, on_message, on_error, on_close
        self.subs, self.closed = [], False
        SOCKS.append(self)

    def connect(self):
        self.on_open()

    def subscribe(self, symbols):
        self.subs += list(symbols)

    def close(self):
        self.closed = True


def wait(cond, sec=2.0):
    t = time.time()
    while time.time() - t < sec:
        if cond():
            return True
        time.sleep(0.01)
    return False


# 1) connect, subscribe (also symbols added later), pushed prices, status messages ignored
f = FS.TickFeed(factory=FakeSock)
f.subscribe(["NSE:NIFTY50-INDEX"])
f.start("APP", "TOK1")
assert wait(lambda: f.state == "connected" and SOCKS)
s = SOCKS[-1]
assert s.token == "APP:TOK1" and s.subs == ["NSE:NIFTY50-INDEX"]
f.subscribe(["NSE:OPT1", "NSE:NIFTY50-INDEX"])                 # known symbol is not sent twice
assert s.subs == ["NSE:NIFTY50-INDEX", "NSE:OPT1"]
s.on_message({"type": "sub", "code": 200, "s": "ok"})          # status message: no price
assert f.get("NSE:OPT1") is None and not f.healthy()
s.on_message({"symbol": "NSE:OPT1", "ltp": 123.5, "prev_close_price": 100.0, "ch": 23.5, "chp": 23.5})
s.on_message([{"symbol": "NSE:NIFTY50-INDEX", "ltp": "23000.5"}])   # list form, text number
q = f.get("NSE:OPT1")
assert q["lp"] == 123.5 and q["prev_close"] == 100.0 and q["src"] == "ws"
assert f.get("NSE:NIFTY50-INDEX")["lp"] == 23000.5 and f.healthy()
assert f.get("NSE:OPT1", max_age=-1) is None                   # too old = REST should be used
s.on_message({"s": "error", "code": 11011, "message": "subscription failed"})
assert "11011" in f.error

# 2) watchdog: silent during market hours -> restart (with a pause); closed market -> no restart; new token -> restart
f.last_tick = time.time() - 100; f.started_at = time.time() - 100
f.check(market_open=False)
assert len(SOCKS) == 1
f.check(market_open=True)
assert wait(lambda: len(SOCKS) == 2) and f.restarts == 1
assert SOCKS[0].closed and "NSE:OPT1" in SOCKS[1].subs         # old socket closed, symbols re-subscribed
SOCKS[0].on_message({"symbol": "NSE:OPT1", "ltp": 1.0})        # a late message from the OLD socket is ignored
assert f.get("NSE:OPT1")["lp"] == 123.5
f.last_tick = time.time() - 100; f.started_at = time.time() - 100
f.check(market_open=True)                                      # inside the pause: no second restart
assert len(SOCKS) == 2
f._next_restart = 0
f.check(market_open=False, token="TOK2")                       # daily token renewed
assert wait(lambda: len(SOCKS) == 3) and SOCKS[-1].token == "APP:TOK2"

# 3) socket closes by itself -> state error -> watchdog restarts
SOCKS[-1].on_close("bye")
assert f.state == "error"
f._next_restart = 0
f.check(market_open=False, token="TOK2")
assert wait(lambda: len(SOCKS) == 4)
f.stop()
assert f.state == "off" and wait(lambda: SOCKS[-1].closed)


# 4) library missing -> "unavailable", never an exception, watchdog leaves it alone
def no_lib(*a):
    raise ImportError("no fyers_apiv3")
g = FS.TickFeed(factory=no_lib)
g.start("APP", "T")
assert wait(lambda: g.state == "unavailable") and "pip install fyers-apiv3" in g.error
g.check(True, "T"); assert g.state == "unavailable" and g.get("X") is None

# 5) provider: pushed prices mean NO REST call; REST is the fallback
CALLS = []


def transport(method, url, headers, body, timeout=20):
    CALLS.append(url)
    if "/data/quotes" in url:
        sy = url.split("symbols=")[1].replace("%3A", ":").replace("%2C", ",")
        return 200, json.dumps({"s": "ok", "d": [{"n": x, "s": "ok", "v": {"lp": 50.0, "prev_close_price": 40.0}} for x in sy.split(",")]})
    return 404, "{}"


SOCKS.clear()
c = FC.FyersClient(transport=transport); c.token, c.app_id = "T", "APP"
p = FP.FyersProvider(client=c, feed_factory=FakeSock)
p._start_feed()
assert wait(lambda: SOCKS and p.feed.connected())
SOCKS[-1].on_message({"symbol": "NSE:NIFTY50-INDEX", "ltp": 23100.0, "prev_close_price": 23000.0})
assert p._fetch_spot("NIFTY") == 23100.0 and p.get_prev_close("NIFTY") == 23000.0
assert CALLS == []                                             # nothing went through REST
assert p._fetch_spot("BANKNIFTY") == 50.0 and len(CALLS) == 1  # no push yet -> REST fallback (one call)
SOCKS[-1].on_message({"symbol": "NSE:OPTX", "ltp": 77.0})
p.prefetch(["NSE:OPTX", "NSE:OPTY"])                           # OPTX pushed, only OPTY needs REST
assert "OPTX" not in CALLS[-1] and "OPTY" in CALLS[-1]
assert "NSE:OPTX" in SOCKS[-1].subs and "NSE:OPTY" in SOCKS[-1].subs
assert p._ticks["NSE:OPTX"][-1][1] == 77.0                     # option chart gets the pushed price
fm = p.feed_mode()
assert fm["mode"] == "WEBSOCKET" and fm["ws_state"] == "connected"
p.disconnect()
assert p.feed.state == "off"

# 6) live price inside the current bar (chart): update / start the forming candle, nothing outside market hours
D = datetime(2026, 10, 16, 10, 7, 30, tzinfo=IST)               # bar 10:05 for 5m
mk = lambda h, m, o, hi, lo, cl: dict(t=datetime(2026, 10, 16, h, m, tzinfo=IST), o=o, h=hi, l=lo, c=cl, v=1.0)
cs = [mk(10, 0, 1, 2, 0.5, 1.5)]
out = FP.overlay_live(cs, 9.0, D, 5)                            # history is a bar behind: new forming candle
assert len(out) == 2 and out[-1]["t"].minute == 5 and out[-1]["o"] == out[-1]["c"] == 9.0
cs2 = cs + [mk(10, 5, 3, 4, 2.5, 3.5)]
out = FP.overlay_live(cs2, 5.0, D, 5)                           # existing forming candle: close/high move, open stays
assert out[-1]["c"] == 5.0 and out[-1]["h"] == 5.0 and out[-1]["o"] == 3 and cs2[-1]["c"] == 3.5
assert FP.overlay_live(cs, 9.0, D.replace(hour=16), 5) == cs and FP.overlay_live(cs, 9.0, D.replace(hour=9, minute=0), 5) == cs
print("fyers socket tests OK")
