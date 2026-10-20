"""Daily sleep schedule for NEW entries (all times IST = UTC+5:30).

  09:30 -> 01:30   bot awake (master toggle decides)
  01:30 -> 05:30   bot switched OFF automatically; if you switch it ON yourself it stays ON
                   until 05:30
  05:30 -> 09:30   bot switched OFF automatically and NO new trade opens, even if you switch it
                   on. At 09:30 (the 4h candle close after the 1D candle open) it switches ON again.

Only NEW entries are gated. Price feed, open-trade SL/TP management and manual closes are never
touched. The tick below is a tiny time compare every 15 s - no network, no heavy work.
"""
import threading
import time
from datetime import datetime, timezone, timedelta

from . import settings_store, status

_IST = timedelta(hours=5, minutes=30)
# (minute-of-day IST, stage name, master toggle value to apply once at that time)
_EVENTS = ((90, "night", False), (330, "morning", False), (570, "day", True))
_TICK_SEC = 15

_started = False
_lock = threading.Lock()


def _ist_now():
    return datetime.now(timezone.utc) + _IST


def _enabled():
    return bool(settings_store.get("daily_gate_enabled", True))


def _stage(now=None):
    """(key, name, apply_value) of the latest schedule event that already happened."""
    now = now or _ist_now()
    m = now.hour * 60 + now.minute
    best = None
    for em, name, val in _EVENTS:
        if em <= m:
            best = (em, name, val)
    day = now.date()
    if best is None:                       # before 01:30: the last event was yesterday's 09:30
        best = _EVENTS[-1]
        day = day - timedelta(days=1)
    return "%s:%s" % (day.isoformat(), best[1]), best[1], best[2]


def entries_allowed(now=None):
    """(ok, reason). Hard block only inside 05:30-09:30 IST."""
    if not _enabled():
        return True, ""
    now = now or _ist_now()
    m = now.hour * 60 + now.minute
    if 330 <= m < 570:
        return False, "Bot sleeping 05:30-09:30 IST (new day start) - no new trades"
    return True, ""


def info(now=None):
    """Small dict for the app's status screen."""
    now = now or _ist_now()
    if not _enabled():
        return {"enabled": False, "state": "off", "text": "Daily schedule OFF"}
    m = now.hour * 60 + now.minute
    if 330 <= m < 570:
        state, text = "sleep", "Sleeping until 09:30 IST"
    elif m < 90 or m >= 570:
        state, text = "awake", "Awake until 01:30 IST"
    else:
        state, text = "night", "Night OFF (you can switch ON until 05:30 IST)"
    return {"enabled": True, "state": state, "text": text, "ist": now.strftime("%H:%M")}


def _apply_once():
    key, name, val = _stage()
    if settings_store.get("gate_last_key", "") == key:
        return
    # one-time record first, so a crash can never flip the toggle twice for the same event
    settings_store.update(gate_last_key=key, trading_enabled=val)
    try:
        status.add_alert("manual", "Daily schedule (%s): bot switched %s" % (name, "ON" if val else "OFF"))
    except Exception:
        pass


def _migrate_once():
    """One-time: ladder SL (TP1->entry, TP2->TP1, TP3->TP2) and 5m default, as requested."""
    if settings_store.get("gate_v1_migrated", False):
        return
    settings_store.update(gate_v1_migrated=True, trail_mode="step1", timeframe="5m")


def _loop():
    while True:
        try:
            if _enabled():
                _apply_once()
            status.update(day_gate=info())
        except Exception as e:
            print("[day_gate] tick error: %s" % e)
        time.sleep(_TICK_SEC)


def start():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    try:
        _migrate_once()
    except Exception as e:
        print("[day_gate] migrate skipped: %s" % e)
    threading.Thread(target=_loop, name="day-gate", daemon=True).start()
