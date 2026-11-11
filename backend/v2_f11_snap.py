"""v2_f11_snap.py - FILTER STUDY Part 9 + Part 10 (bot side): ENTRY SNAPSHOT LOGGER. Paper bot only, current bot (b1). It NEVER stops a trade.
Why: all studies so far are replays of old trades (hindsight, price-shift bias). From now on every signal of the bot is written down WITH its state at that moment, so later the study can join the snapshot to the real result
(with the real entry price, with booking) and test AMD, Z lookback, pullback and the other ideas on REAL data, not on a replay.
One line per signal in v2_f11_snap.jsonl (data folder), written once per (coin, candle, side):
  t, sym, side, tf (3m / 5m / 15m; 3m added in Part 10), entry_price, tp1, tp4, hour_utc, session, cross (the bot's chop number),
  z100, z200 (Z of the close with the trade side), run (last 12 candles %, trade side), dist (distance from EMA50 %, trade side), slope (EMA50 slope over 6 candles %), width (SD/mean of 100 closes %),
  amd_basic / amd_reclaim / amd_video (same definition as study Part 6C), dropped_forming (true when the newest candle was still forming and was left out)
PART 10 adds: spike_ago (candles ago that Z200 went beyond +3 in the trade direction, 0-48, None = none), spike_max (highest trade-direction Z200 in the last 49 candles), spike_bars (how many of those 49 candles had a Z; only trust spike_ago when it is 49),
  zsma (average of the last Z200 values in the trade direction = the video's Z-SMA), zsma_n (how many Z values it used; 200 = the real Z-SMA 200, less = the bot holds fewer candles), z_vs_sma (z200 minus zsma, trade direction: above 0 = the histogram is above the Z-SMA for a long / below it for a short), sig_id (signal id if the bot has one).
Numbers come only from the candles the bot already holds in memory: no network, no database, no engine. Setting f11_snap_mode: "on" (default) or "off". Any problem = nothing is written (fail-open).
File is cut at 5 MB (the old part is kept as .old). Read the counts by hand:  python3 v2_f11_snap.py"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "v2_f11_snap 2 (Filter Part 10 bot side)"
LOG_FILE, LOG_MAX = "v2_f11_snap.jsonl", 5 * 1024 * 1024
NEED = 210                      # candles needed (Z lookback 200 + a few)
TF_NAME = {180: "3m", 300: "5m", 900: "15m"}    # candle step in seconds -> timeframe name
KEEP = NEED + 250               # candles kept for the numbers (Z-SMA 200 needs about 400)
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


def _spike_sma(c, i, side, zlen=200):
    """Z200 history of the last 200 candles -> (spike_ago, spike_max, spike_bars, zsma, zsma_n), all in the trade direction.
    spike_ago = first k (0 = this candle) with Z beyond +3 in the trade direction inside the last 49 candles (same rule as study Part 6B), None = none."""
    zs = {}
    for j in range(max(zlen - 1, i - 199), i + 1):
        z = _z(c, j, zlen, 1)
        if z is not None:
            zs[j] = z
    ago, mx, bars = None, None, 0
    for k in range(0, 49):
        z = zs.get(i - k)
        if z is None:
            continue
        bars += 1
        d = side * z
        mx = d if mx is None or d > mx else mx
        if ago is None and d >= 3.0:
            ago = k
    vals = [zs[j] for j in sorted(zs)][-200:]
    zsma = round(side * sum(vals) / len(vals), 3) if vals else None
    return ago, None if mx is None else round(mx, 3), bars, zsma, len(vals)


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
    if step not in TF_NAME or now - rows[-1][0] > 4 * step:
        return None                                  # not 3m / 5m / 15m, or stale
    dropped = now - rows[-1][0] < step               # newest candle is still forming: leave it out
    if dropped:
        rows = rows[:-1]
    rows = rows[-KEEP:]
    t, o, h, l, c = ([r[j] for r in rows] for j in range(5))
    i = len(c) - 1
    side = 1 if str(getattr(signal, "action", "")).upper() in ("BUY", "LONG") else -1
    e50 = _ema(c, 50)
    w = c[i - 99:i + 1]
    m = sum(w) / 100.0
    sd = math.sqrt(max(sum(x * x for x in w) / 100.0 - m * m, 0.0))
    amd = _amd(o, h, l, c, i, side)
    sp = _spike_sma(c, i, side)
    z200 = _z(c, i, 200, side)
    try:
        import v2_money_hour as M
        sess = M.session_of(time.gmtime(now).tm_hour)
    except Exception:
        sess = None
    return {"t": int(now), "bar_t": t[i], "sym": symbol, "side": "LONG" if side == 1 else "SHORT", "tf": TF_NAME[step],
            "entry_price": getattr(signal, "entry_price", None), "tp1": getattr(signal, "tp1", None), "tp4": getattr(signal, "tp4", None),
            "hour_utc": time.gmtime(now).tm_hour, "session": sess, "cross": getattr(signal, "regime_cross_n", None),
            "z100": _z(c, i, 100, side), "z200": z200, "run": round(side * (c[i] / c[i - 12] - 1.0) * 100.0, 4),
            "dist": round(side * (c[i] - e50[i]) / e50[i] * 100.0, 4), "slope": round(side * (e50[i] - e50[i - 6]) / e50[i] * 100.0, 4),
            "width": round(sd / m * 100.0, 4) if m else None, "amd_basic": amd[0], "amd_reclaim": amd[1], "amd_video": amd[2], "dropped_forming": dropped,
            "spike_ago": sp[0], "spike_max": sp[1], "spike_bars": sp[2], "zsma": sp[3], "zsma_n": sp[4],
            "z_vs_sma": round(z200 - sp[3], 3) if z200 is not None and sp[3] is not None else None,
            "sig_id": getattr(signal, "id", None) or getattr(signal, "signal_id", None)}


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
