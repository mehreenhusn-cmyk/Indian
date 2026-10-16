"""Daily P&L calendar: groups pnl_events by the 5:30 AM IST trading day, month filter, bad input falls back."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import trade_store as T

now = time.time()
today = T._today_utc()
T._data["pnl_events"] = [[now, 2.5], [now, -1.0], [now - 3 * 86400, -4.0], [now - 400 * 86400, 9.0]]

c = T.get_daily_calendar(today[:7])
by = {d["date"]: d for d in c["days"]}
assert c["month"] == today[:7] and c["today"] == today
assert abs(by[today]["pnl"] - 1.5) < 1e-9 and by[today]["trades"] == 2 and by[today]["wins"] == 1, by[today]
assert c["month_trades"] == sum(d["trades"] for d in c["days"])
assert abs(c["month_pnl"] - sum(d["pnl"] for d in c["days"])) < 1e-9
assert c["first_month"] < today[:7]                     # the 400-day-old trade sets the earliest month
assert T.get_daily_calendar("garbage")["month"] == today[:7]
assert T.get_daily_calendar("2026-13")["month"] == today[:7]
assert T.get_daily_calendar("2001-01")["days"] == []
print("calendar ok")
