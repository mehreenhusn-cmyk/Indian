"""Today / 7D / 30D closed-trade P&L row (trade_store.get_period_stats) + it is sent in /api/status."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import trade_store as T

day0 = T._trading_day_start_ts()
T._data["pnl_events"] = [
    [day0 + 60, 5.0],                 # today
    [day0 - 3 * 86400, -2.0],         # 3 days ago  -> 7D + 30D
    [day0 - 6 * 86400 + 5, 1.0],      # still inside 7D (today + 6 days)
    [day0 - 7 * 86400, 10.0],         # only 30D
    [day0 - 29 * 86400 + 5, 4.0],     # still inside 30D
    [day0 - 31 * 86400, 100.0],       # outside
]
T._period_cache.update(ts=0.0, key=None, val=None)
r = T.get_period_stats()
assert r["today_pnl"] == 5.0 and r["today_trades"] == 1, r
assert r["d7_pnl"] == 4.0 and r["d7_trades"] == 3, r
assert r["d30_pnl"] == 18.0 and r["d30_trades"] == 5, r
print("period pnl ok")

import api_server as A
fake = {"open_positions": [], "today_pnl_usdt": 5.0, "server_ts": 100.0, "stats_mode": "paper"}
A.status.get = lambda skip=(): dict(fake)
A.settings_store.get = lambda k, d=None: (False if k == "live_trading_enabled" else d)
A._cached_flags = lambda kind, ps: {}
d = A._display_status()
assert d["period_pnl"]["d7_pnl"] == 4.0, d.get("period_pnl")
print("status carries period_pnl ok")
