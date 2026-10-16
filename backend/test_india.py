import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import date
from recovered_bot import india_options as opt, india_chain, india_reports
from recovered_bot.india_data import ReplayProvider as RP, synthetic_candles as sc
from recovered_bot.india_paper import IndiaPaperEngine as IPE
from recovered_bot.india_pricing import bs_price
from recovered_bot.strategy import ABCDStrategy
from recovered_bot.india_bridge import IndiaStrategyRunner, to_strategy_candles

# ---------------------------------------------------------------- picker ---
assert opt.itm_strike(24130, "CE", 50) == 24100 and opt.itm_strike(24130, "PE", 50) == 24150
assert opt.itm_strike(24150, "CE", 50) == 24100 and opt.itm_strike(24150, "PE", 50) == 24200
assert opt.itm_strike(52340, "CE", 100) == 52300 and opt.itm_strike(52340, "PE", 100) == 52400
assert opt.otm_strike(24130, "CE", 50) == 24150 and opt.otm_strike(24130, "PE", 50) == 24100
assert opt.otm_strike(24150, "CE", 50) == 24200 and opt.otm_strike(24150, "PE", 50) == 24100
assert opt.otm_strike(24130, "CE", 50, 2) == 24200 and opt.otm_strike(24130, "PE", 50, 2) == 24050
assert opt.atm_strike(24130, 50) == 24150 and opt.atm_strike(24120, 50) == 24100
assert opt.option_type_for("SHORT") == "PE" and opt.option_type_for("buy") == "CE"
t0 = date(2026, 10, 12)
assert opt.pick_expiry({date(2026, 10, 12), date(2026, 10, 20)}, t0) == date(2026, 10, 20)
assert opt.pick_expiry({date(2026, 10, 12)}, t0) == date(2026, 10, 12)
assert bs_price(24100, 24000, .02, .15, "CE") > bs_price(24000, 24000, .02, .15, "CE")

# ---------------------------------------------------------------- helpers ---
def mk(cash=200000.0, days=4, **st):
    d = {"NIFTY": sc(22700, days, seed=1)}
    p = RP(d)
    return p, d, IPE(p, {"capital": cash, **st})

def goto(p, hh, mm, day=0):
    d0 = p.c["NIFTY"][0]["t"].date()
    while True:
        n = p.now()
        if n.time().hour == hh and n.time().minute == mm and (n.date() - d0).days >= day:
            return
        assert p.step(), "time not found"

def craft(p, d, o, h, l, c):
    assert p.step()
    d["NIFTY"][p.i].update(o=o, h=h, l=l, c=c)

def enter(e, p, action="LONG", **kw):
    sp = p.get_spot("NIFTY")
    if action == "LONG":
        r = e.on_signal("NIFTY", "LONG", sp - 30, sp + 20, tps=[sp + 20, sp + 40, sp + 60, sp + 80])
    else:
        r = e.on_signal("NIFTY", "SHORT", sp + 30, sp - 20, tps=[sp - 20, sp - 40, sp - 60, sp - 80])
    return sp, r

# ------------------------------------------------------------------ fees ---
p, d, e = mk()
assert e.fees(100, 75, "SELL") > e.fees(100, 75, "BUY") > 0

# ---------------------------------------------------------- entry window ---
p, d, e = mk(); goto(p, 15, 5)
assert "window" in enter(e, p)[1]["reason"]

# ------------------------------------------- open / reject / flip -----------
p, d, e = mk(); goto(p, 10, 0); sp = p.get_spot("NIFTY")
assert not e.on_signal("NIFTY", "LONG", sp + 10, sp + 50)["ok"]
sp, r = enter(e, p)
assert r["ok"] and r["trade"]["contract"]["type"] == "CE" and r["trade"]["contract"]["strike"] < sp
assert r["trade"]["tag"] == "AUTO" and r["trade"]["product"] == "INTRADAY" and r["trade"]["target"] == 4
assert not enter(e, p)[1]["ok"]                                   # already open
r = enter(e, p, "SHORT")[1]
assert r["ok"] and r["trade"]["contract"]["type"] == "PE"
assert e.closed[-1]["reason"] == "OPPOSITE"

# ---------------------------------------- SL = candle CLOSE, not the wick ---
p, d, e = mk(); goto(p, 10, 0); sp, r = enter(e, p); assert r["ok"]
craft(p, d, sp, sp + 5, sp - 100, sp - 10)           # huge wick, closes above SL
assert e.on_tick() == [] and len(e.open) == 1
craft(p, d, sp - 5, sp, sp - 45, sp - 35)            # closes beyond SL(sp-30)
done = e.on_tick()
assert done and done[0]["reason"] == "SL" and done[0]["pnl"] < 0 and done[0]["exit_spot"] == sp - 35
assert done[0]["gross_pnl"] == round(done[0]["pnl"] + done[0]["fees"], 2)

# ------------------------------------------------------- gap through SL -----
p, d, e = mk(); goto(p, 10, 0); sp, r = enter(e, p)
craft(p, d, sp - 50, sp - 48, sp - 60, sp - 55)
done = e.on_tick()
assert done and done[0]["reason"] == "SL(GAP)" and done[0]["exit_spot"] == sp - 50

# -------------------------------- TP1 -> SL to entry (applies next candle) ---
p, d, e = mk(); goto(p, 10, 0); sp, r = enter(e, p)
craft(p, d, sp, sp + 25, sp - 5, sp + 10)
assert e.on_tick() == []
pos = list(e.open.values())[0]
assert pos["tp_hit"] == 1 and pos["sl_spot"] == sp                # moved to entry
craft(p, d, sp + 8, sp + 9, sp - 8, sp - 4)                       # closes under entry
done = e.on_tick()
assert done and done[0]["reason"] == "TSL"

# --------------------------------------------------------- trail step1 ------
p, d, e = mk(trail_mode="step1"); goto(p, 10, 0); sp, r = enter(e, p)
craft(p, d, sp, sp + 45, sp - 2, sp + 30)                         # TP1+TP2 touched
e.on_tick(); pos = list(e.open.values())[0]
assert pos["tp_hit"] == 2 and pos["sl_spot"] == sp + 20           # SL -> TP1
# step2: TP2 -> entry only
p, d, e = mk(trail_mode="step2"); goto(p, 10, 0); sp, r = enter(e, p)
craft(p, d, sp, sp + 25, sp - 2, sp + 10); e.on_tick()
assert list(e.open.values())[0]["sl_spot"] == sp - 30            # TP1 does not move it
craft(p, d, sp + 10, sp + 45, sp + 5, sp + 30); e.on_tick()
assert list(e.open.values())[0]["sl_spot"] == sp                 # TP2 -> entry

# --------------------------------------------------------- final targets ----
p, d, e = mk(); goto(p, 10, 0); sp, r = enter(e, p)
craft(p, d, sp, sp + 85, sp - 2, sp + 70)
done = e.on_tick()
assert done and done[0]["reason"] == "TP4" and done[0]["pnl"] > 0
p, d, e = mk(target_level=2); goto(p, 10, 0); sp, r = enter(e, p)
craft(p, d, sp, sp + 45, sp - 2, sp + 30)
assert e.on_tick()[0]["reason"] == "TP2"

# ---------------------------------------- emergency premium stop ------------
p, d, e = mk(emergency_pct=0.05); goto(p, 10, 0); sp, r = enter(e, p)
craft(p, d, sp, sp, sp - 25, sp - 25)
assert e.on_tick()[0]["reason"] == "ESL"

# ------------------------------------ INTRADAY square-off vs CARRY ----------
p, d, e = mk(); goto(p, 10, 0); sp, r = enter(e, p)
d["NIFTY"][p.i + 1:] = [dict(c, o=sp, h=sp + 1, l=sp - 1, c=sp) for c in d["NIFTY"][p.i + 1:]]
while p.step():
    if e.on_tick(): break
assert e.closed[-1]["reason"] == "SQUAREOFF" and (p.now().hour, p.now().minute) == (15, 15)
p, d, e = mk(product="CARRY"); goto(p, 10, 0); sp, r = enter(e, p)
assert r["ok"] and r["trade"]["product"] == "CARRY"
assert (r["trade"]["contract"]["expiry"] - p.now().date()).days >= 2   # CARRY avoids near expiry
d["NIFTY"][p.i + 1:] = [dict(c, o=sp, h=sp + 1, l=sp - 1, c=sp) for c in d["NIFTY"][p.i + 1:]]
goto(p, 15, 20)
for _ in range(3):
    p.step(); assert e.on_tick() == []
assert len(e.open) == 1                                           # still carried overnight
pos = list(e.open.values())[0]
pos["contract"] = {**pos["contract"], "expiry": p.now().date()}   # now it is expiry day
goto(p, 15, 15, day=(p.now().date() - p.c["NIFTY"][0]["t"].date()).days + 1)
assert e.on_tick()[0]["reason"] == "EXPIRY"

# ------------------------------------------- pins / day mode / fallback -----
p, d, e = mk(); goto(p, 10, 0); sp = p.get_spot("NIFTY")
e.set_day_mode("OTM", 1)
sp, r = enter(e, p); assert r["trade"]["contract"]["strike"] > sp and r["trade"]["tag"] == "DAY"
e.close_all()
e.set_pin("NIFTY", "CE", {"type": "strike", "strike": 22650})
sp, r = enter(e, p)
assert r["trade"]["contract"]["strike"] == 22650 and r["trade"]["tag"] == "PIN"   # pin beats day mode
e.close_all()
sp, r = enter(e, p, "SHORT"); assert r["trade"]["contract"]["type"] == "PE" and r["trade"]["tag"] == "DAY"
e.close_all()
e.set_pin("NIFTY", "CE", {"type": "premium", "target": 100})
sp, r = enter(e, p); c = r["trade"]["contract"]
ltps = {k["strike"]: p.get_option_ltp(k) for k in p.get_contracts("NIFTY") if k["type"] == "CE" and k["expiry"] == c["expiry"]}
assert abs(ltps[c["strike"]] - 100) == min(abs(v - 100) for v in ltps.values())
e.close_all(); e.clear_pins()
# unaffordable pin: fallback on, then off
p, d, e = mk(cash=20000); goto(p, 10, 0)
e.set_pin("NIFTY", "CE", {"type": "strike", "strike": 22550})
sp, r = enter(e, p)
assert (not r["ok"]) or r["trade"]["tag"] in ("FALLBACK", "PIN")
p, d, e = mk(cash=9000, pin_fallback=False); goto(p, 10, 0)
e.set_pin("NIFTY", "CE", {"type": "strike", "strike": 22550})
sp, r = enter(e, p); assert not r["ok"] and "pinned needs" in r["reason"]

# --------------------------------------------- fits-my-balance default ------
p, d, e = mk(cash=200000); goto(p, 10, 0); sp, r = enter(e, p); itm = r["trade"]["contract"]["strike"]
p, d, e = mk(cash=14000); goto(p, 10, 0); sp, r = enter(e, p)
if r["ok"]:
    assert r["trade"]["contract"]["strike"] >= itm            # stepped to cheaper (higher CE strike)
    assert r["trade"]["entry_premium"] * r["trade"]["qty"] <= 14000
p, d, e = mk(cash=1500); goto(p, 10, 0); sp, r = enter(e, p)
assert not r["ok"] and ("needs" in r["reason"] or "min premium" in r["reason"])
p, d, e = mk(cash=200000, min_premium=100000); goto(p, 10, 0)
assert "min premium" in enter(e, p)[1]["reason"]
p, d, e = mk(max_loss_pct=0.0001); goto(p, 10, 0)
assert "risk too high" in enter(e, p)[1]["reason"]

# ------------------------------------------ day rollover resets choices ------
p, d, e = mk(); goto(p, 10, 0); e.on_tick()
e.set_pin("NIFTY", "CE", {"type": "strike", "strike": 22650}); e.set_day_mode("OTM", 2)
goto(p, 9, 20, day=1); e.on_tick()
assert e.pins == {} and e.day_mode is None

# ---------------------------------------------- summary / reports / chain ---
p, d, e = mk(); goto(p, 10, 0); sp, r = enter(e, p)
craft(p, d, sp - 5, sp, sp - 45, sp - 35); e.on_tick()
sp, r = enter(e, p)
sm = e.summary()
assert sm["day_pnl"] == round(sm["realized_today"] + sm["unrealized"], 2) and sm["fees_today"] > 0
assert sm["trades_today"] == 1 and sm["total_pnl"] == round(sm["total_realized"] + sm["unrealized"], 2)
tr = india_reports.filter_trades(e.closed, underlying="nifty")
t = india_reports.totals(tr)
assert t["trades"] == 1 and t["net"] == round(t["gross"] - t["fees"], 2)
assert india_reports.daily_summary(tr)[0]["trades"] == 1
assert india_reports.equity_curve(tr, 200000)[-1]["equity"] == round(200000 + t["net"], 2)
assert india_reports.trades_csv(tr).count("\n") == 2
e.set_pin("NIFTY", "PE", {"type": "strike", "strike": 22800})
ch = india_chain.build_chain(e, "NIFTY")
assert ch["rows"] and sum(r["atm"] for r in ch["rows"]) == 1 and ch["trade_expiry"] in ch["expiries"]
for row in ch["rows"]:
    assert (row["CE"]["itm"], row["PE"]["itm"]) == (row["strike"] < ch["spot"], row["strike"] > ch["spot"])
assert any((r["PE"] or {}).get("pinned") for r in ch["rows"]) and ch["has_oi"] is False
assert india_chain.market_status(p.now()) in ("OPEN", "CLOSED")

# ---------------------------------------- real strategy via the bridge ------
fmt = to_strategy_candles(sc(22700, 2, seed=5))
assert set(fmt[0]) == {"timestamp", "open", "high", "low", "close", "volume"}
assert ABCDStrategy().generate_signal(fmt[:100], "NIFTY", tf_min=5) is None
data = {"NIFTY": sc(22700, 15, seed=1), "BANKNIFTY": sc(55480, 15, seed=2), "FINNIFTY": sc(24500, 15, seed=3)}
pr = RP(data, start=210); en = IPE(pr); rn = IndiaStrategyRunner(pr, en, ABCDStrategy())
sigs = 0
while pr.step():
    en.on_tick()
    for u in data:
        r = rn.run(u)
        if r and "signal" in r:
            sigs += 1
            if r["ok"]:
                tt, sg = r["trade"], r["signal"]
                assert tt["sl_spot"] == sg.stop_loss and len(tt["tps"]) == 4
                assert tt["contract"]["type"] == ("CE" if sg.action == "BUY" else "PE")
en.close_all("END")
assert sigs > 0 and en.stats()["trades"] > 0, (sigs, en.stats())
print("all tests ok;", sigs, "signals ->", en.stats()["trades"], "trades")
