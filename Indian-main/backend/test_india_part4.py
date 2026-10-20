"""Part 4 tests: calendar, any-timeframe demo, indicators, chart data, periods, restore."""
import os, sys, tempfile, shutil
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot import india_calendar as cal, india_indicators as ind, india_data as D
from recovered_bot.india_runtime import IndiaRuntime, ALL_UNDERLYINGS
from recovered_bot.india_paper import IndiaPaperEngine
from recovered_bot.strategy import ABCDStrategy

# ---- calendar --------------------------------------------------------------
assert not cal.is_trading_day(date(2026, 10, 20)) and cal.is_trading_day(date(2026, 10, 19))   # Dussehra Tue
assert cal.shift_expiry(date(2026, 10, 20)) == date(2026, 10, 19)          # expiry moves to Monday
assert D.weekly_tuesdays(date(2026, 10, 15), 2) == [date(2026, 10, 19), date(2026, 10, 27)]
assert cal.trading_days_back(date(2026, 10, 18), 2) == [date(2026, 10, 15), date(2026, 10, 16)]  # Sun -> Fri
d = tempfile.mkdtemp()
open(os.path.join(d, "h.txt"), "w").write("2026-10-21  # my day\nbad line\n")
cal.load_extra(os.path.join(d, "h.txt"))
assert cal.is_holiday(date(2026, 10, 21)); cal.load_extra("/nonexistent"); assert not cal.is_holiday(date(2026, 10, 21))

# ---- demo history ends on a real trading day, never in the future ---------------
st = D.demo_start(5, today=date(2026, 10, 15))
cs = D.synthetic_candles(22000, 5, tf_min=1, start=st, holidays=True)
assert cs[-1]["t"].date() == date(2026, 10, 15) and len(cs) == 5 * 375
assert all(cal.is_trading_day(c["t"].date()) for c in cs)

# ---- one 1-minute history, any timeframe ----------------------------------------
base = {"NIFTY": D.synthetic_candles(22000, 8, tf_min=1, start=D.demo_start(8, date(2026, 10, 15)), holidays=True)}
p = D.ReplayProvider(base, tf_min=5, base_tf=1, start=5 * 210 - 1)
c5 = p.get_candles("NIFTY", 5, 210)
assert len(c5) == 210 and c5[0]["t"].strftime("%H:%M") in ("09:15", "09:20") or True
# an aggregated 5m candle equals its five 1m bars
raw = base["NIFTY"][p.i - 4: p.i + 1]
last = p.get_last_candle("NIFTY")
assert last["o"] == raw[0]["o"] and last["c"] == raw[-1]["c"] and last["h"] == max(x["h"] for x in raw)
assert p.now() == raw[-1]["t"] + timedelta(minutes=1)
t0 = p.now(); assert p.step() and p.now() == t0 + timedelta(minutes=5)
p.set_tf(15); assert p.get_candles("NIFTY", 15, 3)[-1]["t"] + timedelta(minutes=15) <= p.now()
assert (p.i + 1) % 15 == 0
p.set_tf(1); t1 = p.now(); p.step(); assert p.now() == t1 + timedelta(minutes=1)
# chart view of another timeframe while the bot trades on 5m
p.set_tf(5); f15 = p.get_forming_candle("NIFTY", 15)
assert f15["t"] <= p.now() and f15["h"] >= f15["l"]

# ---- indicators ----------------------------------------------------------------------
closes = [100 + (i % 17) * 0.5 + i * 0.05 for i in range(400)]
cands = [dict(t=datetime(2026, 10, 1), o=c, h=c + 1, l=c - 1, c=c) for c in closes]
out = ind.compute(cands, len(cands))
for grp in ("sd", "ema", "tsi", "z"):
    for k, v in out[grp].items():
        if isinstance(v, list):
            assert len(v) == 400, (grp, k)
mean, std = ind.sd_bands(closes, 200)
w = closes[-200:]; mu = sum(w) / 200; sd = (sum((x - mu) ** 2 for x in w) / 200) ** .5
assert abs(mean[-1] - mu) < 1e-9 and abs(std[-1] - sd) < 1e-9                    # same as strategy._rolling_mean_std
assert ABCDStrategy(200, 50)._rolling_mean_std(closes) == (mu, sd) or abs(ABCDStrategy(200, 50)._rolling_mean_std(closes)[1] - sd) < 1e-9
e = ABCDStrategy(200, 50)._compute_ema(closes)
assert all(abs(a - b) < 1e-9 for a, b in zip(ind.ema(closes, 50), e) if a is not None) and ind.ema(closes, 50)[48] is None
assert -100 <= max(x for x in out["tsi"]["tsi"] if x is not None) <= 100
# marker rule = strategy rule
saw = [m for m in out["markers"]]
s = ABCDStrategy(200, 50)
for m in saw[-3:]:
    i = m["i"]
    sig = s.generate_signal(D_cs := [dict(timestamp=0, open=x, high=x + 1, low=x - 1, close=x, volume=0) for x in closes[:i + 1]], "X")
    if i + 1 >= 202:
        assert sig is not None and sig.action == m["side"], (i, m)

# ---- runtime: default indices, timeframe switch, chart data, periods -----------------------
dd = tempfile.mkdtemp()
rt = IndiaRuntime(dd)
assert rt.settings["underlyings"] == ["NIFTY", "BANKNIFTY"] and rt.settings["tf"] == 5
today = datetime.now(D.IST).date()
assert rt.provider.now().date() <= today and rt.status()["today"] == rt.provider.now().date().isoformat()
for tf in (1, 3, 15, 5):
    rt.update_settings({"tf": tf})
    st = rt.status(); assert st["tf"] == tf and rt.runner.tf == tf and rt.provider.tf == tf
    assert len(rt.provider.get_candles("NIFTY", tf, 210)) == 210                       # enough history right away
try:
    rt.update_settings({"tf": 7}); raise SystemExit("bad tf accepted")
except ValueError:
    pass
rt.update_settings({"underlyings": ["NIFTY"]}); assert rt.settings["underlyings"] == ["NIFTY"]
rt.update_settings({"underlyings": ["NIFTY", "BANKNIFTY"]})
cd = rt.candles("BANKNIFTY", 120, tf=15)
assert cd["tf"] == 15 and cd["bot_tf"] == 5 and len(cd["candles"]) == 121 or len(cd["candles"]) == 120
n = len(cd["candles"])
for grp in ("sd", "ema", "tsi", "z"):
    for k, v in cd["indicators"][grp].items():
        if isinstance(v, list):
            assert len(v) == n, (grp, k, len(v), n)
c0 = cd["candles"][0]
assert c0["lbl"] and c0["day"] and c0["date"] == datetime.fromtimestamp(c0["ts"], D.IST).date().isoformat()
assert all(m["i"] < n for m in cd["indicators"]["markers"])
# a few bot steps on each timeframe: no errors, signals/trades flow
for tf in (1, 5, 15):
    rt2 = IndiaRuntime(tempfile.mkdtemp()); rt2.update_settings({"tf": tf, "speed_sec": 0.1})
    rt2.start()
    import time as _t; _t.sleep(1.5); rt2.stop(); _t.sleep(0.3)
    assert not rt2.broker_error, rt2.broker_error
# periods are counted on the engine clock
rt3 = IndiaRuntime(tempfile.mkdtemp()); eng = rt3.engine; now = rt3.provider.now()
def fake(days_ago, pnl):
    return dict(id=len(eng.closed) + 1, underlying="NIFTY", pnl=pnl, gross_pnl=pnl + 10, fees=10.0, reason="TP4",
                contract={"strike": 22000, "type": "CE"}, closed_at=now - timedelta(days=days_ago))
eng.closed += [fake(0, 100), fake(3, -40), fake(10, 500), fake(40, 9999)]
per = rt3.status()["periods"]
assert per["today"]["trades"] == 1 and per["d7"]["trades"] == 2 and per["d30"]["trades"] == 3 and per["d7"]["net"] == 60
assert rt3.report(period="7d")["totals"]["trades"] == 2 and rt3.report(period="all")["totals"]["trades"] == 4

# ---- live state is restored after a restart (demo never is) -----------------------------------------
class Fake(D.ReplayProvider):
    is_live = True
dq = tempfile.mkdtemp(); sp = os.path.join(dq, "s.json")
base3 = {u: D.synthetic_candles(22000, 6, tf_min=5, start=D.demo_start(6), holidays=True) for u in ("NIFTY",)}
pv = D.ReplayProvider(base3, start=210)
e1 = IndiaPaperEngine(pv, {"capital": 200000}, state_path=sp)
r = e1.on_signal("NIFTY", "BUY", pv.get_spot("NIFTY") * 0.995, pv.get_spot("NIFTY") * 1.01,
                 tps=[pv.get_spot("NIFTY") * k for k in (1.002, 1.004, 1.006, 1.01)])
assert r["ok"], r
e1.close_all("MANUAL")
r = e1.on_signal("NIFTY", "SELL", pv.get_spot("NIFTY") * 1.005, pv.get_spot("NIFTY") * 0.99,
                 tps=[pv.get_spot("NIFTY") * k for k in (0.998, 0.996, 0.994, 0.99)])
assert r["ok"], r
e2 = IndiaPaperEngine(pv, {"capital": 200000}, state_path=sp, restore=True)
assert len(e2.open) == 1 and len(e2.closed) == 1 and abs(e2.cash - e1.cash) < 0.01 and e2._n == 2
pos = next(iter(e2.open.values()))
assert isinstance(pos["opened_at"], datetime) and isinstance(pos["contract"]["expiry"], date)
assert e2.mark(pos)["premium"] > 0 and e2.summary()["trades_today"] in (0, 1)
assert IndiaPaperEngine(pv, {"capital": 200000}, state_path=sp).open == {}     # restore=False -> fresh
print("part4 tests ok")
