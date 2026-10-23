#!/usr/bin/env python3
"""python3 test_own_free_money.py - AI Own FREE MONEY mode (paper): 100 USDT margin, 10x, no locks / caps / grade gate. No internet."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot import settings_store as S
from recovered_bot import ai_vision as V
from recovered_bot import ai_vision_own as O
from recovered_bot import ai_capital as CAP

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  OK  {name}")
    else: FAIL += 1; print(f" FAIL {name}")

S.init(os.path.join(tempfile.mkdtemp(), "settings.json"))
check("defaults: free mode on, margin 100, lev 10", S.get("vision_own_free_money") is True and S.get("vision_own_margin") == 100.0 and S.get("vision_own_lev") == 10)
check("bot leverage / invest not touched", S.get("leverage") == 1 and S.get("invest_amount") == 10.0)

# --- capital manager is off in free mode
check("capital manager disabled", CAP.enabled(V) is False)
rec = {"source": "own", "lev": 10}
check("gate lets everything through (even grade B)", CAP.gate(V, rec, 100.0, 98.0, "B") == (True, "", None, False))
check("no lock reason", CAP.lock_reason(V) == "")

# --- scanner is never blocked by loss cap / max open
O._own_day_net = lambda V_: -999.0
O._own_open_count = lambda V_: 99
Vq = type("Vq", (), {"quota_resume_at": staticmethod(lambda: 0)})
check("no daily loss cap / max open block", O._blocked_reason(Vq) == "")
check("own leverage 10", O.own_lev() == 10.0)

# --- stop rules: right side, inside liquidation, no 3% limit
lv = {"low12": 95.0, "high12": 105.0}
st, tg, bad = V._validate_take("BUY", 100.0, 94.0, 112.0, lv, "own")
check("6% stop allowed for AI Own", bad is None and st == 94.0)
st, tg, bad = V._validate_take("BUY", 100.0, 94.0, 112.0, lv, "bot")
check("6% stop still refused for the bot AI", bad is not None and "too far" in bad)
st, tg, bad = V._validate_take("SELL", 100.0, 95.0, 90.0, lv, "own")
check("SELL: stop above price gets fixed from the high", bad is None and st == 105.0)
st, tg, bad = V._validate_take("BUY", 100.0, 85.0, 120.0, lv, "own")
check("stop beyond liquidation (15% at 10x) refused", bad is not None and "too far" in bad)
st, tg, bad = V._validate_take("BUY", 100.0, 100.0, 110.0, {"low12": 100.0, "high12": 105.0}, "own")
check("no valid stop below price -> refused", bad is not None)

# --- opened trade: own margin and leverage
rec = {"id": "o1", "signal_no": 501, "symbol": "TESTUSDT", "side": "BUY", "tf_min": 5, "source": "own", "lev": 1.0, "reason": "t", "bar_ts": 1}
V._state["trades"].clear()
tr = V._open_trade(rec, 100.0, 97.0, 106.0)
check("own trade margin 100, lev 10", tr["invest"] == 100.0 and tr["lev"] == 10.0 and tr["id"] == "vo501")
rec2 = {"id": "b1", "signal_no": 502, "symbol": "BOTUSDT", "side": "BUY", "tf_min": 5, "source": "bot", "lev": 1.0, "reason": "t", "bar_ts": 1}
tb = V._open_trade(rec2, 100.0, 98.0, 104.0)
check("bot-signal AI trade keeps bot invest / lev", tb["invest"] == 10.0 and tb["lev"] == 1.0)

# --- result maths: +5% price = +50% ROI = +50 USDT before fee; fee 1% ROI = 1 USDT
V._close_trade(tr, 105.0, "target")
check("win: about +49 USDT after fee", abs(tr["pnl"] - 49.0) < 0.01)
tr2 = V._open_trade(dict(rec, id="o2", signal_no=503, symbol="T2USDT"), 100.0, 94.0, 110.0)
V._close_trade(tr2, 94.0, "stop")
check("stop at -6% = about -61 USDT", abs(tr2["pnl"] - (-61.0)) < 0.01)
tr3 = V._open_trade(dict(rec, id="o3", signal_no=504, symbol="T3USDT"), 100.0, 94.0, 110.0)
V._close_trade(tr3, 80.0, "gap")
check("gap past liquidation can never lose more than the margin", tr3["pnl"] >= -100.0 - 1e-9)

# --- safety switch still works: free mode OFF brings the old rules back
S.update(vision_own_free_money=False)
check("free OFF: capital manager on again", CAP.enabled(V) is True)
st, tg, bad = V._validate_take("BUY", 100.0, 94.0, 112.0, lv, "own")
check("free OFF: 3% stop limit back", bad is not None and "too far" in bad)
check("free OFF: own leverage = bot leverage", O.own_lev() == 1.0)

print(f"\n{PASS} passed, {FAIL} failed"); sys.exit(1 if FAIL else 0)
