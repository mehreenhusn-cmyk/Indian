"""
entry_context.py - extra entry-time tags saved with every signal (record only).

Adds three numbers that were never saved before, so Strategy Doctor can later
test "does this entry usually fail?" on real trades:
  adx          - trend strength, 0-100 (Wilder, period 14). Low = sideways / chop.
  ema_gap_atr  - how far the close is from EMA50, measured in ATRs. Tiny = the
                 cross happened with no real push away from the EMA.
  htf_trend    - "up" / "down" / "flat" / None. APPROXIMATE higher-timeframe trend:
                 the same candles are merged 5-to-1 (3m -> 15m, 5m -> 25m) and the
                 trend is read from EMA20 of the merged closes.

Rules: pure maths on the candles already fetched (no network, no pandas/numpy),
every function returns None instead of raising, nothing here decides a trade.
"""
from typing import Dict, List, Optional


def _f(c, k):
    return float(c[k])


def adx(candles: List[Dict], period: int = 14) -> Optional[float]:
    try:
        n = len(candles)
        if n < period * 2 + 1:
            return None
        tr, pdm, mdm = [], [], []
        for i in range(1, n):
            h, l, pc = _f(candles[i], "high"), _f(candles[i], "low"), _f(candles[i - 1], "close")
            ph, pl = _f(candles[i - 1], "high"), _f(candles[i - 1], "low")
            up, dn = h - ph, pl - l
            pdm.append(up if (up > dn and up > 0) else 0.0)
            mdm.append(dn if (dn > up and dn > 0) else 0.0)
            tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        s_tr, s_p, s_m = sum(tr[:period]), sum(pdm[:period]), sum(mdm[:period])
        dxs = []
        for i in range(period, len(tr) + 1):
            if i > period:
                s_tr = s_tr - s_tr / period + tr[i - 1]
                s_p = s_p - s_p / period + pdm[i - 1]
                s_m = s_m - s_m / period + mdm[i - 1]
            if s_tr <= 0:
                dxs.append(0.0)
                continue
            pdi, mdi = 100.0 * s_p / s_tr, 100.0 * s_m / s_tr
            dxs.append(100.0 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0.0)
        if len(dxs) < period:
            return None
        a = sum(dxs[:period]) / period
        for d in dxs[period:]:
            a = (a * (period - 1) + d) / period
        return round(a, 2)
    except Exception:
        return None


def ema_gap_atr(candles: List[Dict], ema_last: Optional[float], period: int = 14) -> Optional[float]:
    """|close - EMA50| / ATR(14). None if it cannot be computed."""
    try:
        if ema_last is None or len(candles) < period + 2:
            return None
        trs = []
        for i in range(len(candles) - period, len(candles)):
            h, l, pc = _f(candles[i], "high"), _f(candles[i], "low"), _f(candles[i - 1], "close")
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs) / len(trs)
        if atr <= 0:
            return None
        return round(abs(_f(candles[-1], "close") - float(ema_last)) / atr, 3)
    except Exception:
        return None


def htf_trend(candles: List[Dict], factor: int = 5, ema_len: int = 20) -> Optional[str]:
    try:
        m = len(candles) // factor
        if m < ema_len + 3:
            return None
        start = len(candles) - m * factor            # drop the oldest leftovers so the newest candle ends a group
        closes = [_f(candles[start + (i + 1) * factor - 1], "close") for i in range(m)]
        k = 2.0 / (ema_len + 1)
        e = sum(closes[:ema_len]) / ema_len
        series = [e]
        for c in closes[ema_len:]:
            e = c * k + e * (1 - k)
            series.append(e)
        last, back = series[-1], series[-3]
        if last <= 0:
            return None
        slope = (last - back) / last * 100.0
        if closes[-1] > last and slope > 0.02:
            return "up"
        if closes[-1] < last and slope < -0.02:
            return "down"
        return "flat"
    except Exception:
        return None


def build(candles: List[Dict], ema_last: Optional[float]):
    """(adx, ema_gap_atr, htf_trend) - each None if not computable. Never raises."""
    return adx(candles), ema_gap_atr(candles, ema_last), htf_trend(candles)
