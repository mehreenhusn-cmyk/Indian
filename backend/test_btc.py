#!/usr/bin/env python3
"""python3 test_btc.py - BTC rules (paper only): BTC always watched, its own 1000 USDT x 10x size, own slot, Dual Bot per-trade margin. No internet."""
import os, sys, tempfile, types
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
from recovered_bot import settings_store as S
S.init(os.path.join(tempfile.mkdtemp(), "settings.json"))
from recovered_bot import paper_trader as PT
import dual_lab as D

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  OK  {name}")
    else: FAIL += 1; print(f" FAIL {name}")

check("defaults: btc fixed, 1000 margin, 10x", S.get("btc_fixed") is True and S.get("btc_margin") == 1000.0 and S.get("btc_leverage") == 10)
check("alt defaults untouched (invest 10, leverage 1)", S.get("invest_amount") == 10.0 and S.get("leverage") == 1)

def sig(sym, action="BUY", px=100.0):
    return types.SimpleNamespace(symbol=sym, action=action, entry_price=px, signal_no=1, stop_loss=px * 0.99,
                                 tp1=px * 1.01, tp2=px * 1.02, tp3=px * 1.03, tp4=px * 1.04)
PT.reset()
PT.open_paper_trade(sig("BTCUSDT"))
PT.open_paper_trade(sig("ETHUSDT"))
pos = {p["symbol"]: p for p in PT._positions.values()}
check("BTC paper trade: 1000 USDT x 10", pos["BTCUSDT"]["invest_usdt"] == 1000.0 and pos["BTCUSDT"]["leverage"] == 10.0)
check("other coin keeps the normal size", pos["ETHUSDT"]["invest_usdt"] == 10.0 and pos["ETHUSDT"]["leverage"] == 1.0)
S.update(btc_fixed=False)
PT.reset()
PT.open_paper_trade(sig("BTCUSDT"))
p = list(PT._positions.values())[0]
check("btc_fixed OFF: BTC is a normal coin again", p["invest_usdt"] == 10.0 and p["leverage"] == 1.0)
S.update(btc_fixed=True)

# Dual Bot: margin per trade
check("dual: BTC 1000, others 100", D._mg({"s": "BTCUSDT"}) == 1000.0 and D._mg({"s": "ETHUSDT"}) == 100.0)
t_btc = {"s": "BTCUSDT", "status": "closed", "net": 5.0, "live": None}
t_eth = {"s": "ETHUSDT", "status": "closed", "net": 5.0, "live": None}
check("dual: 5% of margin = 50 USDT on BTC, 5 on ETH", abs(D._usdt(t_btc) - 50.0) < 1e-9 and abs(D._usdt(t_eth) - 5.0) < 1e-9)
sm = D.summary({"trades": [dict(t_btc, src="main", t=0, d=1, closed_at=0), dict(t_eth, src="main", t=0, d=1, closed_at=0)], "rows": {}}, None, [])
check("dual: alt totals have no BTC (ETH only = 5)", abs(sm["pnl"] - 5.0) < 1e-9 and sm["closed"] == 1)
check("dual: BTC totals are separate (BTC only = 50)", abs(sm["btc"]["pnl"] - 50.0) < 1e-9 and sm["btc"]["closed"] == 1)

# trade_store: BTC has its own counters, alt numbers never include it
import time
from recovered_bot import trade_store as TS
TS.init(os.path.join(tempfile.mkdtemp(), "trades.json"))
now = time.time()
def closed(sym, pnl, ts):
    return {"symbol": sym, "pnl_usdt": pnl, "closed_at_ts": ts, "opened_at_ts": ts - 60, "id": f"{sym}{ts}"}
TS.record_close(closed("BTCUSDT", 10.0, now - 86400))        # yesterday's trade (counters reset below, as the day rollover does)
TS._data["btc"].update(today_pnl_usdt=0.0, total_trades=0, wins=0)
TS.record_close(closed("ETHUSDT", 3.0, now))
TS.record_close(closed("BTCUSDT", -40.0, now))
alt = TS.get_today_stats()
btc = TS.get_btc_stats()
check("alt today P&L ignores BTC (3.0)", abs(alt["today_pnl_usdt"] - 3.0) < 1e-9 and alt["total_trades"] == 1)
check("BTC today P&L is its own (-40.0)", abs(btc["today_pnl_usdt"] + 40.0) < 1e-9 and btc["total_trades"] == 1 and btc["losses"] == 1)
check("alt 7D/30D P&L ignores BTC", abs(TS.get_period_stats()["d7_pnl"] - 3.0) < 1e-9)
days = TS.get_btc_closed_days(3)
check("BTC days: today -40 (1 lost), yesterday +10 (1 won)", days[0]["losses"] == 1 and abs(days[0]["pnl"] + 40.0) < 1e-9 and days[1]["wins"] == 1 and abs(days[1]["pnl"] - 10.0) < 1e-9)
a = TS.bump_signal_count(); b = TS.bump_signal_count(btc=True)
check("signal counters apart: alt #1, BTC starts at 9001", a == 1 and b == TS.BTC_NO_BASE + 1 and TS.get_today_stats()["signal_count_today"] == 1)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
