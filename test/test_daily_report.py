"""Yesterday report (never disappears). Run: python3 test/test_daily_report.py"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import daily_report as D, trade_store as T
now = time.time(); y = now - (now % 86400) - 3600
rows = [{"symbol": "AAAUSDT", "pnl_usdt": 5.0, "closed_at_ts": y, "reason": "TP4"},
        {"symbol": "BBBUSDT", "pnl_usdt": -6.0, "closed_at_ts": y - 10, "reason": "SL"},
        {"symbol": "CCCUSDT", "pnl_usdt": -1.0, "closed_at_ts": y - 20, "reason": "REVERSED"},
        {"symbol": "DDDUSDT", "pnl_usdt": 2.0, "closed_at_ts": now - 5, "reason": "SL", "trailed_sl": True}]
T.get_all_closed = lambda limit=5000, net=True: rows
r = D.build()
assert r["yesterday"]["trades"] == 3 and r["yesterday"]["net"] == -2.0 and r["today"]["trades"] == 1
assert r["yesterday"]["worst"]["sym"] == "BBBUSDT" and len(r["days"]) == 7 and r["days"][1]["title"] == "Yesterday"
assert "Yesterday: 3 trades closed" in r["headline"]
T.get_all_closed = lambda limit=5000, net=True: []
assert D.build()["headline"].endswith("closed no trade.")
T.get_all_closed = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
assert "error" in D.build()                                   # never raises
print("daily_report: all OK")
