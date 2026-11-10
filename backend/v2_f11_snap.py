"""v2_f11_snap.py - FILTER STUDY Part 9 (bot side): ENTRY SNAPSHOT LOGGER. Paper bot only, current bot (b1). It NEVER stops a trade.
Why: all studies so far are replays of old trades (hindsight, price-shift bias). From now on every signal of the bot is written down WITH its state at that moment, so later the study can join the snapshot to the real result
(with the real entry price, with booking) and test AMD, Z lookback, pullback and the other ideas on REAL data, not on a replay.
One line per signal in v2_f11_snap.jsonl (data folder), written once per (coin, candle, side):
  t, sym, side, tf (5m / 15m), entry_price, tp1, tp4, hour_utc, session, cross (the bot's chop number),
  z100, z200 (Z of the close with the trade side), run (last 12 candles %, trade side), dist (distance from EMA50 %, trade side), slope (EMA50 slope over 6 candles %), width (SD/mean of 100 closes %),
  amd_basic / amd_reclaim / amd_video (same definition as study Part 6C), dropped_forming (true when the newest candle was still forming and was left out)
Numbers come only from the candles the bot already holds in memory: no network, no database, no engine. Setting f11_snap_mode: "on" (default) or "off". Any problem = nothing is written (fail-open).
File is cut at 5 MB (the old part is kept as .old). Read the counts by hand:  python3 v2_f11_snap.py"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "v2_f11_snap 1 (Filter Part 9 bot side)"
LOG_FILE, LOG_MAX = "v2_f11_snap.jsonl", 5 * 1024 * 1024
NEED = 210                      # candles needed (Z lookback 200 + a few)
_st = {"seen": 0, "written": 0, "skipped": 0, "error": "", "last": {}}


def _on():
    try:
        from recovered_bot import settings_store
        return str(settings_store.get("f11_snap_mode", "on") or "on").lower() != "off"
    except Exception:
        return True


def _root():
    import v2_inventory as I
    return os.path.realpath(I.find_data_dir())


def _z(c, i, n, side):
    w = c[i + 1 - n:i + 1]
    m = sum(w) / n
    sd = math.sqrt(max(sum(x * x for x in w) / n - m * m, 0.0))
    return None if sd <= 0 else round(side * (c[i] - m) / sd, 3)


def _ema(c, n):
    a, e, out = 2.0 / (n + 1), c[0], []
    for x in c:
        e = a * x + (1.0 - a) * e
        out.append(e)
    return out


def _amd(o, h, l, c, i, side):
    a, b = i - 2, i - 1
    if side == 1:
        basic = c[a] < o[a] and l[b] < l[a] and c[i] > o[i]
        return basic, basic and c[b] > l[a], basic and o[a] > o[b]
    basic = c[a] > o[a] and h[b] > h[a] and c[i] < o[i]
    return basic, basic and c[b] < h[a], basic and o[a] < o[b]


def numbers(signal, symbol, cache, now=None):
    """-> dict (one snapshot) or None when the numbers can not be made."""
    now = now or time.time()
    rows = []
    for k in cache or []:
        t = int(k["timestamp"])
        rows.append((t // 1000 if t > 10 ** 11 else t, float(k["open"]), float(k["high"]), float(k["low"]), float(k["close"])))
    if len(rows) < NEED + 1:
        return None
    step = rows[-1][0] - rows[-2][0]
    if step not in (300, 900) or now - rows[-1][0] > 4 * step:
        return None                                  # not 5m / 15m, or stale
    dropped = now - rows[-1][0] < step               # newest candle is still forming: leave it out
    if dropped:
        rows = rows[:-1]
    rows = rows[-(NEED + 60):]
    t, o, h, l, c = ([r[j] for r in rows] for j in range(5))
    i = len(c) - 1
    side = 1 if str(getattr(signal, "action", "")).upper() in ("BUY", "LONG") else -1
    e50 = _ema(c, 50)
    w = c[i - 99:i + 1]
    m = sum(w) / 100.0
    sd = math.sqrt(max(sum(x * x for x in w) / 100.0 - m * m, 0.0))
    amd = _amd(o, h, l, c, i, side)
    try:
        import v2_money_hour as M
        sess = M.session_of(time.gmtime(now).tm_hour)
    except Exception:
        sess = None
    return {"t": int(now), "bar_t": t[i], "sym": symbol, "side": "LONG" if side == 1 else "SHORT", "tf": "5m" if step == 300 else "15m",
            "entry_price": getattr(signal, "entry_price", None), "tp1": getattr(signal, "tp1", None), "tp4": getattr(signal, "tp4", None),
            "hour_utc": time.gmtime(now).tm_hour, "session": sess, "cross": getattr(signal, "regime_cross_n", None),
            "z100": _z(c, i, 100, side), "z200": _z(c, i, 200, side), "run": round(side * (c[i] / c[i - 12] - 1.0) * 100.0, 4),
            "dist": round(side * (c[i] - e50[i]) / e50[i] * 100.0, 4), "slope": round(side * (e50[i] - e50[i - 6]) / e50[i] * 100.0, 4),
            "width": round(sd / m * 100.0, 4) if m else None, "amd_basic": amd[0], "amd_reclaim": amd[1], "amd_video": amd[2], "dropped_forming": dropped}


def _write(line):
    p = os.path.join(_root(), LOG_FILE)
    if os.path.isfile(p) and os.path.getsize(p) > LOG_MAX:
        os.replace(p, p + ".old")
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, separators=(",", ":"), default=str) + "\n")


def log_signal(signal, symbol, cache):
    """Called by the current bot (b1) before it opens a paper trade. Writes one snapshot per (coin, candle, side). Always returns None (never blocks)."""
    if not _on():
        return None
    try:
        _st["seen"] += 1
        s = numbers(signal, symbol, cache)
        if s is None:
            _st["skipped"] += 1
            return None
        key = (symbol, s["bar_t"], s["side"])
        if _st["last"].get(symbol) == key:
            return None
        _st["last"][symbol] = key
        if len(_st["last"]) > 3000:
            _st["last"].clear()
        _write(s)
        _st["written"] += 1
    except Exception as e:
        _st["error"] = str(e)[:160]
    return None


def info():
    n = 0
    try:
        with open(os.path.join(_root(), LOG_FILE), "r", encoding="utf-8") as f:
            n = sum(1 for _ in f)
    except Exception:
        pass
    return {"tool": VERSION, "mode": "on" if _on() else "off", "log_lines": n, "seen_since_start": _st["seen"], "written_since_start": _st["written"], "skipped_no_numbers": _st["skipped"], "last_error": _st["error"]}


if __name__ == "__main__":
    print(json.dumps(info(), indent=1))
