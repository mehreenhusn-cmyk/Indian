"""Radar: watch all USDT-M futures via !miniTicker@arr.

Every 60 s compute quote-volume added in that minute. Flag a coin when
minute volume >= RADAR_K x its own rolling median of the last 60 minutes
AND > RADAR_MIN_USDT.
"""
import statistics
import time
from collections import defaultdict, deque

# ---- constants (starting guesses) ----
RADAR_K = 4.0
RADAR_MIN_USDT = 50_000.0
RADAR_MEDIAN_WINDOW = 60
RADAR_TICK_SEC = 60
RADAR_REFLAG_SEC = 15 * 60  # a coin can be flagged again after this long


def parse_mini_ticker(t):
    """One item of !miniTicker@arr -> (symbol, quote_vol_24h, close, change_pct) or None.

    miniTicker has NO price-change-percent field (only c, o, h, l, v, q), so the
    24h change is computed from open (o) and close (c).
    """
    try:
        sym = (t.get("s") or "").upper()
        if not sym.endswith("USDT"):
            return None
        c = float(t.get("c"))
        o = float(t.get("o"))
        qv = float(t.get("q"))
    except (TypeError, ValueError, AttributeError):
        return None
    if o <= 0 or c <= 0:
        return None
    return sym, qv, c, (c - o) / o * 100.0


class PingRadar:
    def __init__(self):
        self._vol_hist = defaultdict(lambda: deque(maxlen=RADAR_MEDIAN_WINDOW + 1))
        self._last_qv = {}
        self._last_price = {}
        self._change_pct = {}
        self._last_eval_ts = 0.0
        self.flagged = {}

    def on_ticker(self, symbol, quote_vol_24h, price, change_pct=None):
        if not symbol or not symbol.endswith("USDT"):
            return
        try:
            qv = float(quote_vol_24h)
            px = float(price)
        except (TypeError, ValueError):
            return
        self._last_qv[symbol] = qv
        self._last_price[symbol] = px
        if change_pct is not None:
            try:
                self._change_pct[symbol] = float(change_pct)
            except (TypeError, ValueError):
                pass

    def maybe_evaluate(self, now=None):
        now = now if now is not None else time.time()
        if now - self._last_eval_ts < RADAR_TICK_SEC:
            return []
        minute_ts = int(now // 60) * 60
        if self._last_eval_ts > 0 and int(self._last_eval_ts // 60) * 60 == minute_ts:
            return []
        self._last_eval_ts = now
        newly = []
        for sym, qv in list(self._last_qv.items()):
            hist = self._vol_hist[sym]
            if hist and hist[-1][0] == minute_ts:
                continue
            prev_qv = hist[-1][1] if hist else qv
            delta = max(0.0, qv - prev_qv)
            hist.append((minute_ts, qv))
            if len(hist) < 3:
                continue
            deltas = []
            prev = None
            for ts, v in hist:
                if prev is not None:
                    deltas.append(max(0.0, v - prev))
                prev = v
            if len(deltas) < 5:
                continue
            try:
                med = statistics.median(deltas[-RADAR_MEDIAN_WINDOW:])
            except statistics.StatisticsError:
                continue
            threshold = max(RADAR_MIN_USDT, RADAR_K * med)
            if delta >= threshold and delta > RADAR_MIN_USDT:
                if sym not in self.flagged or now - self.flagged[sym] > RADAR_REFLAG_SEC:
                    newly.append(sym)
                self.flagged[sym] = now
        return newly

    def top_bottom_by_change(self, n=10):
        items = [(s, self._change_pct.get(s, 0.0)) for s in self._last_price]
        if not items:
            return [], []
        items.sort(key=lambda x: x[1], reverse=True)
        gainers = [s for s, _ in items[:n]]
        losers = [s for s, _ in items[-n:][::-1]]
        return gainers, losers

    def price(self, symbol):
        return self._last_price.get(symbol)

    def quote_vol_24h(self, symbol):
        return self._last_qv.get(symbol, 0.0)

    def all_symbols(self):
        return list(self._last_price.keys())
