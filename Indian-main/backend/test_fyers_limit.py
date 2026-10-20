"""Fyers request-limit tests (fake transport - no network): budget, 429 cooldown, batching, stale data, safe chain."""
import json, os, sys, tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot import fyers_client as FC, fyers_provider as FP, india_broker
from recovered_bot.india_runtime import IndiaRuntime

S = {"calls": 0, "mode": "ok", "urls": []}


def transport(method, url, headers, body, timeout=20):
    S["calls"] += 1
    S["urls"].append(url)
    if S["mode"] == "429":
        return 429, "Too many requests"
    if S["mode"] == "plan":
        return 200, json.dumps({"s": "error", "code": -429, "message": "You've reached the Standard plan limit of 50 requests/minute."})
    if "/data/quotes" in url:
        sy = url.split("symbols=")[1].replace("%3A", ":").replace("%2C", ",").replace("%20", " ")
        return 200, json.dumps({"s": "ok", "d": [{"n": x, "s": "ok", "v": {"lp": 100.0, "prev_close_price": 90.0}} for x in sy.split(",")]})
    if "/data/history" in url:
        return 200, json.dumps({"s": "ok", "candles": [[1760000000, 1, 2, 0.5, 1.5, 10]]})
    return 404, "{}"


def prov():
    c = FC.FyersClient(transport=transport)
    c.token, c.app_id = "T", "A"
    return FP.FyersProvider(client=c)


# 1) own budget: the 6th data call in a minute is refused WITHOUT touching the network
S.update(calls=0, mode="ok")
c = FC.FyersClient(transport=transport); c.token, c.app_id = "T", "A"; c.max_per_min = 5
for _ in range(5):
    c.quotes(["NSE:NIFTY50-INDEX"])
try:
    c.quotes(["NSE:NIFTY50-INDEX"]); raise SystemExit("should be limited")
except india_broker.RateLimited:
    pass
assert S["calls"] == 5 and c.limit_info()["calls_per_min"] == 5

# 2) HTTP 429 and the plan-limit message both start a cooldown; calls in the cooldown never reach Fyers
for mode in ("429", "plan"):
    S.update(calls=0, mode=mode)
    c = FC.FyersClient(transport=transport); c.token, c.app_id = "T", "A"
    try:
        c.history("X", 5, date.today(), date.today()); raise SystemExit("should be limited")
    except india_broker.RateLimited:
        pass
    assert S["calls"] == 1 and c.limit_info()["limited_now"]
    try:
        c.quotes(["X"]); raise SystemExit("should be in cooldown")
    except india_broker.RateLimited:
        pass
    assert S["calls"] == 1                                   # no second call during cooldown

# 3) one quotes call refreshes all three indices (and the bot, chart and header share it)
S.update(calls=0, mode="ok")
p = prov()
a, b, d = p._fetch_spot("NIFTY"), p._fetch_spot("BANKNIFTY"), p._fetch_spot("FINNIFTY")
assert S["calls"] == 1 and a == b == d == 100.0

# 4) option prices for a whole chain: batched (31 symbols = 1 call), not one call per strike
S.update(calls=0)
p = prov()
syms = [f"NSE:NIFTY26O2723{i:03d}CE" for i in range(31)]
p.prefetch(syms)
assert S["calls"] == 1 and all(s in p._qcache for s in syms)
p.prefetch(syms)                                             # cached: no new call
assert S["calls"] == 1

# 5) limit hit -> the LAST price is kept, no error
p.quote_ttl = 0.0
S.update(mode="429")
assert p._fetch_spot("NIFTY") == 100.0
assert p.get_prev_close("NIFTY") == 90.0

# 6) today's candles are not re-downloaded on every refresh
S.update(calls=0, mode="ok")
S["urls"].clear()
p = prov()
p._cached(("hist", "NIFTY", 5, 1), 600, lambda: [])         # pretend old days are already loaded
n = int(__import__("math").ceil(150 * 5 / 375.0 * 1.4)) + 3
p._cache[("hist", "NIFTY", 5, n)] = (__import__("time").time(), [])
p._fetch_candles("NIFTY", 5, 150); p._fetch_candles("NIFTY", 5, 150); p._fetch_candles("NIFTY", 5, 150)
assert sum("/data/history" in u for u in S["urls"]) == 1, S["urls"]

# 7) the chain never raises: last good chain (marked stale) or an empty one
rt = IndiaRuntime(tempfile.mkdtemp())
good = rt.chain("NIFTY", None, 5)
assert good["rows"] and not good.get("stale")
real = india_broker.RateLimited
orig = rt.engine.p.get_spot
rt.engine.p.get_spot = lambda u: (_ for _ in ()).throw(real("Fyers limit reached"))
st = rt.chain("NIFTY", None, 5)
assert st["stale"] and st["rows"] == good["rows"] and "limit" in st["error"]
empty = rt.chain("BANKNIFTY", None, 5)
assert empty["stale"] and empty["rows"] == [] and empty["status"] in ("OPEN", "CLOSED")
rt.engine.p.get_spot = orig
assert rt.status()["trading_mode"] == "PAPER"
print("fyers limit tests OK")
