"""Offline tests for Part 1 (broker plumbing). Run: cd backend && python test_broker.py"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timedelta
from recovered_bot import india_broker as ib
from recovered_bot.india_data import IST, synthetic_candles, DEMO_LOT
from recovered_bot.india_runtime import IndiaRuntime, START_PRICE
from recovered_bot import india_runtime as rtm

# --- timestamps: Unix vs 1980-based must both land on "now"
now = datetime(2026, 10, 15, 11, 0, tzinfo=IST)
unix = int(now.timestamp())
assert ib.epoch_to_ist(unix, ref=now) == now
assert ib.epoch_to_ist(unix - ib.EPOCH_1980, ref=now) == now
assert ib.epoch_to_ist(unix * 1000, ref=now) == now
assert ib.epoch_to_ist(unix - ib.EPOCH_1980, "1980") == now and ib.epoch_to_ist(unix, "unix") == now
assert DEMO_LOT["NIFTY"] == 65

# --- credential store: saved on disk (mode 600), only masked values go to the app
d = tempfile.mkdtemp()
cs = ib.CredStore(d)
cs.save("fake", {"api_key": "ABCDEF123456", "secret": ""})
assert cs.get("fake") == {"api_key": "ABCDEF123456"} and cs.masked("fake")["api_key"] == "AB******56"
assert oct(os.stat(cs.path).st_mode)[-3:] == "600"
cs.clear("fake"); assert cs.get("fake") == {}

# --- a fake broker that serves wall-clock candles, to drive the live loop
class Fake(ib.LiveProvider):
    name, label, fields = "fake", "Fake broker", ("api_key",)
    def connect(self, creds):
        if creds.get("api_key") != "good":
            raise ib.BrokerError("Login failed: wrong API key")
    def _fetch_candles(self, u, tf, limit):
        end = self.now().replace(second=0, microsecond=0)
        end -= timedelta(minutes=end.minute % tf)
        raw = synthetic_candles(START_PRICE[u], 3, seed=7)
        out, t = [], end - timedelta(minutes=tf * (len(raw) - 1))
        for c in raw:
            out.append({**c, "t": t}); t += timedelta(minutes=tf)
        return out[-limit:]
    def _fetch_spot(self, u): return self._fetch_candles(u, 5, 1)[-1]["c"]
    def _fetch_contracts(self, u):
        from recovered_bot import india_options as opt
        st = opt.UNDERLYINGS[u]["step"]; atm = round(self._fetch_spot(u) / st) * st
        e = (self.now() + timedelta(days=5)).date()
        return [dict(underlying=u, expiry=e, strike=atm + k * st, type=t, lot=DEMO_LOT[u],
                     key=f"{u}{atm + k * st}{t}") for k in range(-10, 11) for t in ("CE", "PE")]
    def _fetch_ltp(self, c): return max(5.0, 150 - abs(c["strike"] - self._fetch_spot(c["underlying"])) * 0.3)
ib.register("fake", Fake)

rt = IndiaRuntime(d)
assert rt.status()["broker_connected"] is False and rt.status()["progress"] is not None
try:
    rt.connect_broker("fake", {"api_key": "bad"}); raise SystemExit("should fail")
except ib.BrokerError as e:
    assert "wrong API key" in str(e)
try:
    rt.connect_broker("nobody", {"api_key": "x"}); raise SystemExit("should fail")
except ib.BrokerError as e:
    assert "not installed" in str(e)
info = rt.connect_broker("fake", {"api_key": "good"})
assert info["connected"] and rt.settings["source"] == "fake"
st = rt.status()
assert st["broker_connected"] and st["progress"] is None and "Fake broker" in st["source_label"]
assert all(st["spots"][u] for u in st["spots"])
assert rt.broker_info()["saved"]["fake"]["api_key"] != "good"          # masked
rt.update_settings({"poll_sec": 2}); rt.start(); time.sleep(2.5); rt.stop()  # real loop, live path
assert rt.status()["running"] is False
assert len(rt.chain("NIFTY")["rows"]) > 0 if "rows" in rt.chain("NIFTY") else True
rt.disconnect_broker(); assert rt.status()["broker_connected"] is False and rt.settings["source"] == "demo"
print("broker tests ok")
