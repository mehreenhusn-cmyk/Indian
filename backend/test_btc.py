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
check("dual summary adds both with their own margin", abs(sm["pnl"] - 55.0) < 1e-9)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
