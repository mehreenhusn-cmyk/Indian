"""India fast-data tests: /ticks is lock-free and reads the pushed WebSocket price; candles() downloads outside the runtime lock;
the chart note explains slow / missing data. No network. Run: python3 backend/test_india_ticks.py"""
import os, sys, tempfile, threading, time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot.india_runtime import IndiaRuntime, ALL_UNDERLYINGS
from recovered_bot import fyers_provider as FP, india_chain

# 1) demo mode: ticks has a price for every index, mode DEMO, live False
rt = IndiaRuntime(tempfile.mkdtemp())
t = rt.ticks()
assert t["live"] is False and t["mode"] == "DEMO" and set(t["spots"]) == set(ALL_UNDERLYINGS), t
assert all(v["lp"] > 0 for v in t["spots"].values())
assert "Demo data" in rt.candles("NIFTY", 50)["note"]

# 2) live-like provider: ticks reads the pushed price WITHOUT the runtime lock and without any broker call
class FakeFeed:
    def __init__(self):
        self.lock = threading.Lock()
        self.ticks = {FP.INDEX_SYM["NIFTY"]: (time.time() - 0.4, {"lp": 22850.15, "src": "ws"})}


class FakeLive:
    is_live = True
    label = "fake"
    def __init__(self, base):
        self.base, self.feed, self._last_spot, self.calls = base, FakeFeed(), {"BANKNIFTY": 50000.5}, 0
        self.lock_free = None
    def feed_mode(self):
        return {"mode": "WEBSOCKET", "note": "WebSocket live"}
    def now(self):
        return self.base.now()
    def get_spot(self, u):
        self.calls += 1
        raise AssertionError("ticks() must not call the broker")
    def get_candles(self, u, tf, limit):
        res = []
        th = threading.Thread(target=lambda: res.append(rt.lock.acquire(timeout=1.0) and (rt.lock.release() or True)))
        th.start(); th.join(2.0)
        self.lock_free = bool(res and res[0])          # another thread could take the runtime lock WHILE we "download"
        return self.base.get_candles(u, tf, limit)
    def get_forming_candle(self, u, tf):
        return None


demo = rt.provider
fake = FakeLive(demo)
rt.live, rt.provider = fake, fake
rt.lock.acquire()                                     # even with the runtime lock held elsewhere ticks() must answer
out = []
th = threading.Thread(target=lambda: out.append(rt.ticks())); th.start(); th.join(2.0)
rt.lock.release()
assert out, "ticks() waited for the runtime lock"
t = out[0]
assert t["live"] is True and t["mode"] == "WEBSOCKET", t
n = t["spots"]["NIFTY"]; assert n["lp"] == 22850.15 and n["src"] == "ws" and 300 <= n["age_ms"] < 5000, n
b = t["spots"]["BANKNIFTY"]; assert b["lp"] == 50000.5 and b["src"] == "rest", b
assert "FINNIFTY" not in t["spots"] and fake.calls == 0

india_chain.market_status = lambda now: "OPEN"      # the note must not depend on the clock of the test machine
# 3) candles(): the provider download runs outside the lock, and the note says where prices come from
c = rt.candles("NIFTY", 60)
assert fake.lock_free is True, "get_candles ran while the runtime lock was held"
assert c["live"] is True and len(c["candles"]) > 10 and c["feed_mode"] == "WEBSOCKET"
assert c["note"], c
print("note:", c["note"])
fake.feed_mode = lambda: {"mode": "REST", "note": "WebSocket not live"}
assert "REST" in rt.candles("NIFTY", 60)["note"]
india_chain.market_status = lambda now: "CLOSED"; assert "closed" in rt.candles("NIFTY", 60)["note"].lower()
india_chain.market_status = lambda now: "OPEN"
# a failing download keeps the app alive and shows the reason
fake.get_candles = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Fyers limit reached - waiting 30s"))
c2 = rt.candles("NIFTY", 60); assert c2["candles"] == [] and "limit" in c2["note"].lower(), c2["note"]
print("PASS test_india_ticks")
