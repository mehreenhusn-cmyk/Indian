"""Net P&L sync: open positions go out NET of fee, Today Total = closed + open (one formula everywhere)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import api_server as A

fake = {"open_positions": [
    {"id": "1", "invest_usdt": 100.0, "pnl_usdt": 10.0, "roi_pct": 10.0, "fee_roi_pct": 1.0},
    {"id": "2", "invest_usdt": 200.0, "pnl_usdt": -4.0, "roi_pct": -2.0},          # no frozen fee -> setting (default 1.0)
], "today_pnl_usdt": -58.80, "server_ts": 100.0}
A.status.get = lambda skip=(): dict(fake)
A.settings_store.get = lambda k, d=None: (False if k == "live_trading_enabled" else (1.0 if k == "fee_roi_pct" else d))
A._cached_flags = lambda kind, ps: {}
d = A._display_status()
p1, p2 = d["open_positions"]
assert abs(p1["pnl_usdt"] - 9.0) < 1e-9 and abs(p1["roi_pct"] - 9.0) < 1e-9, p1
assert abs(p2["pnl_usdt"] - (-4.0 - 2.0)) < 1e-9 and abs(p2["roi_pct"] - (-3.0)) < 1e-9, p2
assert abs(d["open_pnl"] - 3.0) < 1e-9, d["open_pnl"]
assert abs(d["today_total_usdt"] - (-58.80 + 3.0)) < 1e-9
assert abs(d["open_pnl_gross"] - 6.0) < 1e-9 and p1["pnl_gross_usdt"] == 10.0
print("net pnl ok")
