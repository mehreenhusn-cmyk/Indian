"""india_calendar.py - NSE trading days (weekends + exchange holidays).

HOLIDAYS below is the 2026 NSE equity list as I know it - VERIFY it against the
current NSE circular. Add or fix days without touching code: put one ISO date per
line (YYYY-MM-DD, '#' for comments) in  <data folder>/india_holidays.txt .
"""
import os
from datetime import date, timedelta

# NSE equity-derivatives trading holidays 2026, copied from NSE circular NSE/FAOP/71777 (12 Dec 2025).
# BSE equity follows the same weekday holidays; if BSE ever differs, add dates in india_holidays.txt.
HOLIDAY_NAMES = {
    date(2026, 1, 26): "Republic Day", date(2026, 3, 3): "Holi", date(2026, 3, 26): "Shri Ram Navami",
    date(2026, 3, 31): "Shri Mahavir Jayanti", date(2026, 4, 3): "Good Friday",
    date(2026, 4, 14): "Dr. Ambedkar Jayanti", date(2026, 5, 1): "Maharashtra Day",
    date(2026, 5, 28): "Bakri Id", date(2026, 6, 26): "Muharram", date(2026, 9, 14): "Ganesh Chaturthi",
    date(2026, 10, 2): "Mahatma Gandhi Jayanti", date(2026, 10, 20): "Dussehra",
    date(2026, 11, 10): "Diwali Balipratipada", date(2026, 11, 24): "Guru Nanak Jayanti",
    date(2026, 12, 25): "Christmas",
}
HOLIDAYS = set(HOLIDAY_NAMES)
# Special Sunday session: Diwali Muhurat trading, 8 Nov 2026. NSE announces the timings later by circular,
# so the bot does NOT trade it by itself - add the date to india_holidays.txt style handling only after the circular.
MUHURAT = {date(2026, 11, 8): "Diwali Muhurat trading (timings: see NSE circular)"}
_extra = set()


def load_extra(path):
    """Read optional extra holidays (one ISO date per line). Safe if the file is missing."""
    global _extra
    out = set()
    try:
        with open(path) as f:
            for line in f:
                s = line.split("#", 1)[0].strip()
                if s:
                    try:
                        out.add(date.fromisoformat(s))
                    except ValueError:
                        pass
    except OSError:
        pass
    _extra = out


def holiday_name(d):
    if d in HOLIDAY_NAMES:
        return HOLIDAY_NAMES[d]
    if d in _extra:
        return "Exchange holiday"
    return "Weekend" if d.weekday() >= 5 else ""


def market_note(d):
    """Short text for the app header, e.g. 'Closed - Dussehra. Next open Wed 21 Oct'."""
    if d in MUHURAT:
        return MUHURAT[d]
    if is_trading_day(d):
        return ""
    nxt = next_trading_day(d + timedelta(days=1))
    return f"Closed - {holiday_name(d)}. Next open {nxt.strftime('%a %d %b')}"


def upcoming_holidays(d, n=5):
    return [{"date": x.isoformat(), "name": HOLIDAY_NAMES.get(x, "Exchange holiday")}
            for x in sorted(HOLIDAYS | _extra) if x >= d][:n]


def is_holiday(d):
    return d in HOLIDAYS or d in _extra


def is_trading_day(d):
    return d.weekday() < 5 and not is_holiday(d)


def prev_trading_day(d):
    """Latest trading day on or before d."""
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def next_trading_day(d):
    """First trading day on or after d."""
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def trading_days_back(end, n):
    """The n trading days ending at `end` (oldest first); `end` itself is moved back if closed."""
    out, d = [], prev_trading_day(end)
    while len(out) < n:
        out.append(d)
        d = prev_trading_day(d - timedelta(days=1))
    return out[::-1]


def shift_expiry(d):
    """An expiry that falls on a holiday moves to the previous trading day (e.g. Tue 20 Oct -> Mon 19 Oct)."""
    return prev_trading_day(d)
