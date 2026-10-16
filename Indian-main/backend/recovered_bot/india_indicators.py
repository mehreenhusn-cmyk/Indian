"""india_indicators.py - indicator series for the India chart (plain Python, no numpy).

Matches the bot's strategy where it matters:
  * EMA = Pine-style, SMA-seeded (same as ABCDStrategy._compute_ema). EMA50 is the signal line.
  * SD bands = mean +/- 1/2/3 population std-dev of the last `lookback` closes (same as the
    strategy's SD levels, but drawn for every candle; early candles use what history exists).
  * Markers = the same EMA50 cross rule the strategy uses (close crosses EMA50), on CLOSED candles.
Extras for the lower panels (not used for trading):
  * TSI(25,13) with a 13-EMA signal line, scale -100..100.
  * Z-score of the close inside the SD window, plus its 14-SMA.
Every list is aligned 1:1 with the candle list; None = not enough data yet.
"""
from math import sqrt


def ema(values, length):
    n, out = len(values), [None] * len(values)
    if n < length:
        return out
    k = 2.0 / (length + 1)
    prev = sum(values[:length]) / length
    out[length - 1] = prev
    for i in range(length, n):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _ema_opt(values, length):
    """EMA over a series that may start with None (TSI chains)."""
    idx = next((i for i, v in enumerate(values) if v is not None), None)
    out = [None] * len(values)
    if idx is None:
        return out
    sub = ema(values[idx:], length)
    out[idx:] = sub
    return out


def sma(values, length):
    out, s, q = [None] * len(values), 0.0, []
    for i, v in enumerate(values):
        if v is None:
            q, s = [], 0.0
            continue
        q.append(v)
        s += v
        if len(q) > length:
            s -= q.pop(0)
        if len(q) == length:
            out[i] = s / length
    return out


def sd_bands(closes, lookback=200, min_n=20):
    """Rolling mean and std over the last `lookback` closes (running sums, O(n))."""
    n = len(closes)
    mean, std = [None] * n, [None] * n
    s = s2 = 0.0
    for i, c in enumerate(closes):
        s += c
        s2 += c * c
        if i >= lookback:
            o = closes[i - lookback]
            s -= o
            s2 -= o * o
        m = min(i + 1, lookback)
        if m >= min_n:
            mu = s / m
            var = max(s2 / m - mu * mu, 0.0)
            mean[i], std[i] = mu, sqrt(var)
    return mean, std


def tsi(closes, long=25, short=13, signal=13):
    mom = [None] + [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    ab = [None if m is None else abs(m) for m in mom]
    num = _ema_opt(_ema_opt(mom, long), short)
    den = _ema_opt(_ema_opt(ab, long), short)
    t = [None if a is None or b in (None, 0) else 100.0 * a / b for a, b in zip(num, den)]
    return t, _ema_opt(t, signal)


def zscore(closes, mean, std, smooth=14):
    z = [None if m is None or not s else (c - m) / s for c, m, s in zip(closes, mean, std)]
    return z, sma(z, smooth)


def markers(closes, ema50):
    """Strategy cross rule on closed candles -> [{"i": index, "side": "BUY"|"SELL"}]."""
    out = []
    for i in range(1, len(closes)):
        a, b = ema50[i - 1], ema50[i]
        if a is None or b is None:
            continue
        if closes[i - 1] <= a and closes[i] > b:
            out.append({"i": i, "side": "BUY"})
        elif closes[i - 1] >= a and closes[i] < b:
            out.append({"i": i, "side": "SELL"})
    return out


def _r(xs, nd=2):
    return [None if x is None else round(x, nd) for x in xs]


def compute(candles, n_closed, lookback=200, ema_fast=30, ema_slow=50):
    """candles: dicts with o/h/l/c, oldest first (the last one may still be forming).
    n_closed = how many of them are closed (markers only use those)."""
    closes = [float(c["c"]) for c in candles]
    mean, std = sd_bands(closes, lookback)

    def band(k):
        return [None if m is None else m + k * s for m, s in zip(mean, std)]
    e_slow, e_fast = ema(closes, ema_slow), ema(closes, ema_fast)
    t, ts = tsi(closes)
    z, zs = zscore(closes, mean, std)
    return {
        "sd": {"mean": _r(mean), "p1": _r(band(1)), "p2": _r(band(2)), "p3": _r(band(3)),
               "m1": _r(band(-1)), "m2": _r(band(-2)), "m3": _r(band(-3))},
        "ema": {"fast": _r(e_fast), "slow": _r(e_slow), "fast_len": ema_fast, "slow_len": ema_slow},
        "tsi": {"tsi": _r(t), "signal": _r(ts)},
        "z": {"z": _r(z, 3), "sma": _r(zs, 3)},
        "markers": [m for m in markers(closes[:n_closed], e_slow[:n_closed])],
    }
