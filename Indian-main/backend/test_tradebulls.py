"""Offline tests for the Tradebulls login/balance client (replies copied from the official doc).
Run: cd backend && python test_tradebulls.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot import india_broker as ib
from recovered_bot.tradebulls_client import TradebullsClient
from recovered_bot.tradebulls_provider import TradebullsProvider
from recovered_bot.india_runtime import IndiaRuntime

LOGIN_OK = {"status": "success", "code": "s-101", "message": "Success message", "data": {
    "access_token": "eyJTOKEN123456", "broadcast_access_token": "eyJBCAST987654",
    "user_name": "Rest Client", "login_time": "2020-03-10 10:10:10",
    "exchanges": ["NSE_EQ", "NSE_FO"], "product_types": ["INTRADAY", "DELIVERY"],
    "others": {"broadCastSocket": "wss://broadcast.server.com:4509",
               "messageSocket": "wss://socketio.server.com:4512"}}}
BAL_OK = {"status": "success", "code": "s-101", "message": "ok",
          "data": {"equity": {"net_available": 24966.45, "total_available": 24966.45, "total_utilised": 2496}}}
seen = []

def transport(method, url, headers, body):
    seen.append((method, url, dict(headers), body))
    if url.endswith("/authentication/v1/user/session") and method == "POST":
        if body["api_key"] != "GOODKEY1":
            return 400, json.dumps({"status": "error", "code": "e-101", "message": "Invalid API key"})
        return 200, json.dumps(LOGIN_OK)
    if url.endswith("/authentication/v1/user/session") and method == "DELETE":
        return 200, json.dumps({"status": "success", "code": "s-101", "message": "bye"})
    if url.endswith("/authentication/v1/user/balance"):
        if headers.get("Authorization") != "Bearer eyJTOKEN123456":
            return 401, json.dumps({"status": "error", "code": "e-401", "message": "bad token"})
        return 200, json.dumps(BAL_OK)
    return 404, "nope"

C = {"base_url": "https://api.example.com/", "user_id": "test1", "login_type": "password",
     "password": "Xyz@123", "second_auth": "QWERT1234Y", "api_key": "GOODKEY1"}

# --- request matches the doc exactly
cl = TradebullsClient(transport)
d = cl.login(C)
m, url, h, b = seen[-1]
assert (m, url) == ("POST", "https://api.example.com/authentication/v1/user/session")
assert b == {"user_id": "TEST1", "login_type": "PASSWORD", "password": "Xyz@123",
             "second_auth": "QWERT1234Y", "api_key": "GOODKEY1", "source": "WEBAPI"}
assert cl.token == "eyJTOKEN123456" and cl.broadcast_url.startswith("wss://broadcast")
bal = cl.balance()
assert seen[-1][2]["Authorization"] == "Bearer eyJTOKEN123456" and bal["net_available"] == 24966.45
assert all("Xyz@123" not in t and "GOODKEY1" not in t for _, _, t in cl.log)      # masked log
cl.logout(); assert cl.token is None and seen[-1][0] == "DELETE"

# --- readable errors
def err(c, **kw):
    try:
        TradebullsClient(transport).login({**c, **kw}); raise SystemExit("should fail")
    except ib.BrokerError as e:
        return str(e)
assert "Invalid API key" in err(C, api_key="WRONGKEY")
assert "second_auth" in err(C, second_auth="")
assert "base URL" in err(C, base_url="api.example.com")
assert "PASSWORD or MPIN" in err(C, login_type="FINGERPRINT")
c2 = TradebullsClient(transport); c2.login(C); c2.token = "stale"
try:
    c2.balance(); raise SystemExit("should fail")
except ib.BrokerError as e:
    assert "expired" in str(e)
try:
    TradebullsClient(lambda *a: (200, "<html>")).login(C); raise SystemExit("should fail")
except ib.BrokerError as e:
    assert "not JSON" in str(e)

# --- runtime: login -> live feed (fake socket), password never saved
import time
from recovered_bot import tradebulls_feed as tf
d = tempfile.mkdtemp()
class FakeWS:
    """Fake price socket: answers each 206 subscribe with one 209 price packet (paise)."""
    def __init__(self):
        self.q, self.sent = [], []
    def send_binary(self, b):
        txt = tf.decode_packets(b)[0]; self.sent.append(txt)
        m = tf.parse_message(txt)
        if m.get("64") == "206":
            px = {"26000": 2270055, "26009": 5548010, "26037": 2450030}.get(m["7"], 13050)
            self.q.append(tf.encode_packet(f"63=FT3.0|64=209|1={m['1']}|7={m['7']}|8={px}"))
    def recv(self):
        t0 = time.time()
        while not self.q:
            time.sleep(0.01)
            if time.time() - t0 > 5: raise TimeoutError("idle")
        return self.q.pop(0)
    def close(self): pass
fake = FakeWS()
class FakeFeed(tf.PriceFeed):
    def __init__(self, url, user, token, spec=None, on_tick=None):
        super().__init__(url, user, token, spec, connector=lambda u: fake, on_tick=on_tick)
class TB(TradebullsProvider):
    def __init__(self, tf_min=5):
        super().__init__(tf_min, TradebullsClient(transport), feed_factory=FakeFeed)
ib.register("tradebulls", TB)
rt = IndiaRuntime(d)
info = rt.connect_broker("tradebulls", C)
assert info["connected"] and info["data_ready"] and info["account"]["name"] == "Rest Client"
assert info["account"]["net_available"] == 24966.45
assert info["feed"]["price_scale"] == 100.0 and info["feed"]["premium_source"] == "MODEL"
assert any("64=101" in m and "eyJBCAST987654" in m for m in fake.sent)          # login uses broadcast token
assert rt.settings["source"] == "tradebulls"
assert abs(rt.provider.get_spot("NIFTY") - 22700.55) < 1e-6                     # paise -> rupees
assert abs(rt.provider.get_spot("BANKNIFTY") - 55480.10) < 1e-6
raw = open(os.path.join(d, "india_broker.json")).read()
assert "Xyz@123" not in raw and "QWERT1234Y" not in raw and "GOODKEY1" in raw
assert info["saved"]["tradebulls"]["api_key"] != "GOODKEY1"                    # masked to the app
assert "eyJBCAST987654" not in json.dumps(info)
try:
    rt.connect_broker("tradebulls", None); raise SystemExit("should fail")      # saved key, no password
except ib.BrokerError as e:
    assert "password" in str(e)
st = rt.status()
assert st["broker_connected"] and "Tradebulls" in st["source_label"] and st["spots"]["NIFTY"] == 22700.55
rt.disconnect_broker(); assert rt.broker_info()["connected"] is False and rt.settings["source"] == "demo"

# --- packets: framing, multi-frame, broken frame
a, b = tf.encode_packet("8=1|7=2"), tf.encode_packet("8=3|7=4")
assert tf.decode_packets(a + b) == ["8=1|7=2", "8=3|7=4"] and tf.decode_packets(a[:-3]) == []
assert tf.parse_message("63=FT3.0|1=2$7=45001|8=13050") == {"63": "FT3.0", "1": "2", "7": "45001", "8": "13050"}

# --- tick candles: 09:15 anchor, roll-up, date handling, out-of-session ticks ignored
from datetime import datetime, timedelta
IST = tf.IST
tc = tf.TickCandles()
base = datetime(2026, 10, 15, 9, 15, 5, tzinfo=IST)                              # a Thursday
for m, px in [(0, 100), (1, 103), (2, 99), (4, 101), (5, 102), (6, 98)]:
    assert tc.add("X", px, base + timedelta(minutes=m))
c5 = tc.candles("X", 5)
assert [c["t"].strftime("%H:%M") for c in c5] == ["09:15", "09:20"]
assert (c5[0]["o"], c5[0]["h"], c5[0]["l"], c5[0]["c"]) == (100, 103, 99, 101) and c5[1]["c"] == 98
assert tc.candles("X", 15)[0]["t"].strftime("%H:%M") == "09:15" and len(tc.candles("X", 1)) == 6
assert not tc.add("X", 100, datetime(2026, 10, 15, 8, 59, tzinfo=IST))           # before open
assert not tc.add("X", 100, datetime(2026, 10, 15, 15, 30, tzinfo=IST))          # at/after close
assert not tc.add("X", 100, datetime(2026, 10, 17, 10, 0, tzinfo=IST))           # Saturday
p = os.path.join(tempfile.mkdtemp(), "c.json"); t2 = tf.TickCandles(p); t2.add("X", 5, base); t2.save()
assert len(tf.TickCandles(p).candles("X", 5)) == 1                               # survives restart

# --- feed: reconnect after a dropped socket, no crash on junk packets
class Flaky:
    n = 0
    def __init__(self): self.sent, Flaky.n = [], Flaky.n + 1; self.k = 0
    def send_binary(self, b): self.sent.append(b)
    def recv(self):
        self.k += 1
        if Flaky.n == 1: raise ConnectionError("dropped")
        return [b"junk", tf.encode_packet("63=FT3.0|64=209|1=1|7=26000|8=2270055"), tf.encode_packet("8=abc|7=1")][min(self.k - 1, 2)] if self.k <= 3 else time.sleep(0.05) or tf.encode_packet("7=1|8=5")
    def close(self): pass
got = []
f = tf.PriceFeed("wss://x", "U", "T", connector=lambda u: Flaky(), on_tick=lambda k, p, t: got.append((k, p)))
f.subscribe("1_26000"); tf.time.sleep = time.sleep
f._stop.wait = lambda d: time.sleep(0.05) or False
f.start(); t0 = time.time()
while ("1_26000", 2270055.0) not in got and time.time() - t0 < 5: time.sleep(0.05)
f.stop(); assert ("1_26000", 2270055.0) in got and Flaky.n >= 2

# --- contract file: CSV with different header styles, real tokens used for premiums
csvp = os.path.join(tempfile.mkdtemp(), "c.csv")
exp = (datetime.now(IST) + timedelta(days=6)).strftime("%d-%b-%Y").upper()
open(csvp, "w").write("ScripCode,Symbol,ExpiryDate,StrikePrice,OptionType,LotSize\n"
                      f"45001,NIFTY,{exp},22700,CE,65\n45002,NIFTY,{exp},22700,PE,65\nbad,row\n")
cb = tf.ContractBook(); n, bad = cb.load_csv(csvp)
cs = cb.contracts("NIFTY"); assert n == 2 and len(cs) == 2 and cs[0]["feed_token"] == "2_45001" and cs[0]["lot"] == 65
open(csvp, "w").write("a,b\n1,2\n")
try:
    cb.load_csv(csvp); raise SystemExit("should fail")
except ib.BrokerError as e:
    assert "columns" in str(e)
# --- chart data: closed + forming candles, open-trade levels, bad name rejected
rt2 = IndiaRuntime(tempfile.mkdtemp()); cd = rt2.candles("NIFTY", 40)
assert len(cd["candles"]) == 40 and set(cd["candles"][0]) == {"ts", "o", "h", "l", "c", "x50", "lbl", "day", "date"} and cd["live"] is False
try:
    rt2.candles("XYZ"); raise SystemExit("should fail")
except ValueError:
    pass
print("tradebulls tests ok")
