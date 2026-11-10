"""v2_f9_session.py - FILTER STUDY Part 4 (bot side): US-SESSION GATE. Paper bot only, current bot (b1).
Why: the study (Part 2) showed the US session (16:00-24:00 UTC = 21:30-05:30 IST) is the worst: net -4769 USDT, win 11.4%.
Mode is the setting f9_session_mode (default "log"):
  "off"   = nothing happens
  "log"   = only WRITES a line each time a new entry falls in the window (v2_f9_session_log.jsonl). No trade is stopped.
  "block" = the entry is skipped while the window is on.
Hours are the setting f9_session_utc, text "16-24" (start-end, UTC). Any problem = take the trade (fail-open).
Read the log by hand (normally not needed):  python3 v2_f9_session.py   (prints counts)"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "v2_f9_session 1 (Filter Part 4 bot side)"
LOG_FILE, LOG_MAX = "v2_f9_session_log.jsonl", 2 * 1024 * 1024
DEFAULT_HOURS = "16-24"
_st = {"seen": 0, "in_window": 0, "error": ""}


def _setting(key, default):
    try:
        from recovered_bot import settings_store
        return settings_store.get(key, default)
    except Exception:
        return default


def mode():
    m = str(_setting("f9_session_mode", "log") or "log").lower()
    return m if m in ("off", "log", "block") else "log"


def window():
    """(start_hour, end_hour) UTC from the setting text 'a-b'. Bad text -> the default."""
    for txt in (str(_setting("f9_session_utc", DEFAULT_HOURS) or ""), DEFAULT_HOURS):
        try:
            a, b = [int(x) for x in txt.replace(" ", "").split("-")]
            if 0 <= a <= 23 and 1 <= b <= 24 and a != b:
                return a, b
        except Exception:
            pass
    return 16, 24


def in_window(hour, a, b):
    return (a <= hour < b) if a < b else (hour >= a or hour < b)    # a > b = the window crosses midnight


def _root():
    import v2_inventory as I
    return os.path.realpath(I.find_data_dir())


def _log(line):
    try:
        p = os.path.join(_root(), LOG_FILE)
        if os.path.isfile(p) and os.path.getsize(p) > LOG_MAX:
            os.replace(p, p + ".old")
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, separators=(",", ":"), default=str) + "\n")
    except Exception:
        pass


def gate_reason(signal, symbol):
    """Called by the current bot (b1) before it opens a paper trade. A reason text ONLY in "block" mode inside the window, else None (= take it)."""
    m = mode()
    if m == "off":
        return None
    try:
        a, b = window()
        now = time.time()
        _st["seen"] += 1
        if not in_window(time.gmtime(now).tm_hour, a, b):
            return None
        _st["in_window"] += 1
        _log({"t": int(now), "sym": symbol, "side": str(getattr(signal, "action", "")), "mode": m, "window_utc": "%d-%d" % (a, b), "blocked": m == "block"})
        if m == "block":
            return "US-session gate (Part 4): entries stopped %02d:00-%02d:00 UTC" % (a, b % 24)
    except Exception as e:
        _st["error"] = str(e)[:160]
    return None


def info():
    a, b = window()
    lines = 0
    try:
        with open(os.path.join(_root(), LOG_FILE), "r", encoding="utf-8") as f:
            lines = sum(1 for _ in f)
    except Exception:
        pass
    return {"tool": VERSION, "mode": mode(), "window_utc": "%d-%d" % (a, b), "log_lines": lines, "seen_since_start": _st["seen"], "in_window_since_start": _st["in_window"], "last_error": _st["error"]}


if __name__ == "__main__":
    print(json.dumps(info(), indent=1))
