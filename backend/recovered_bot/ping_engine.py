"""Ping rule engine: detect BUY/SELL pings from closed 1m candles,
track rolling counts, colours, absorbed, EMA30/50.
"""
import statistics
import time
from collections import deque

# ---- constants (starting guesses) ----
PING_MIN_USDT = 20_000.0
PING_Z = 3.0
NET_WINDOW = 60
ABSORB_MOVE_PCT = 0.15
EPISODE_GAP_SEC = 15 * 60  # quiet time after which a new ping episode starts
ABSORB_PINGS = 3
ABSORB_WINDOW_SEC = 5 * 60
EMA_FAST = 30
EMA_SLOW = 50
YELLOW_MIN = 3
RED_MIN = 5


def _ema_update(prev, price, period):
    if prev is None:
        return price
    k = 2.0 / (period + 1)
    return price * k + prev * (1.0 - k)


class CoinState:
    __slots__ = (
        "symbol", "net_hist", "ping_times_buy", "ping_times_sell",
        "pings_hour_buy", "pings_hour_sell", "hour_key",
        "first_ping_ts", "first_ping_side", "first_ping_price",
        "last_ping_ts", "last_ping_side",
        "ema30", "ema50", "close_hist",
        "recent_total", "recent_vol_pct", "recent_net",
        "price", "quote_vol_24h", "in_watchlist",
        "last_candle_ts", "high_hist", "low_hist", "open_hist",
    )

    def __init__(self, symbol):
        self.symbol = symbol
        self.net_hist = deque(maxlen=NET_WINDOW)
        self.ping_times_buy = deque()
        self.ping_times_sell = deque()
        self.pings_hour_buy = 0
        self.pings_hour_sell = 0
        self.hour_key = None
        self.first_ping_ts = None
        self.first_ping_side = None
        self.first_ping_price = None
        self.last_ping_ts = None
        self.last_ping_side = None
        self.ema30 = None
        self.ema50 = None
        self.close_hist = deque(maxlen=EMA_SLOW + 5)
        self.recent_total = 0.0
        self.recent_vol_pct = 0.0
        self.recent_net = 0.0
        self.price = 0.0
        self.quote_vol_24h = 0.0
        self.in_watchlist = False
        self.last_candle_ts = 0
        self.high_hist = deque(maxlen=15)
        self.low_hist = deque(maxlen=15)
        self.open_hist = deque(maxlen=15)


class PingEngine:
    def __init__(self):
        self.coins = {}
        self._events = []

    def get(self, symbol):
        if symbol not in self.coins:
            self.coins[symbol] = CoinState(symbol)
        return self.coins[symbol]

    def on_closed_candle(self, symbol, total_q, taker_buy_Q, close_price, candle_ts_ms,
                         quote_vol_24h=0.0, in_watchlist=False,
                         high=None, low=None, open_=None):
        try:
            total = float(total_q)
            tb = float(taker_buy_Q)
            close = float(close_price)
            ts = int(candle_ts_ms) / 1000.0
        except (TypeError, ValueError):
            return None
        net = 2.0 * tb - total
        cs = self.get(symbol)
        cs.price = close
        cs.quote_vol_24h = float(quote_vol_24h or 0.0)
        cs.in_watchlist = bool(in_watchlist)
        cs.last_candle_ts = ts
        cs.recent_total = total
        cs.recent_net = net
        if cs.quote_vol_24h > 0:
            cs.recent_vol_pct = (total / cs.quote_vol_24h) * 100.0
        else:
            cs.recent_vol_pct = 0.0

        cs.close_hist.append(close)
        try:
            cs.high_hist.append(float(high) if high is not None else close)
            cs.low_hist.append(float(low) if low is not None else close)
            cs.open_hist.append(float(open_) if open_ is not None else close)
        except (TypeError, ValueError):
            cs.high_hist.append(close)
            cs.low_hist.append(close)
            cs.open_hist.append(close)
        cs.ema30 = _ema_update(cs.ema30, close, EMA_FAST)
        cs.ema50 = _ema_update(cs.ema50, close, EMA_SLOW)

        abs_net = abs(net)
        cs.net_hist.append(abs_net)
        if len(cs.net_hist) >= 5:
            try:
                med = statistics.median(cs.net_hist)
            except statistics.StatisticsError:
                med = 0.0
        else:
            med = 0.0
        T = max(PING_MIN_USDT, PING_Z * med)

        hour_key = int(ts // 3600)
        if cs.hour_key is None:
            cs.hour_key = hour_key
        elif hour_key != cs.hour_key:
            cs.pings_hour_buy = 0
            cs.pings_hour_sell = 0
            cs.hour_key = hour_key

        side = None
        if net >= T:
            side = "BUY"
        elif net <= -T:
            side = "SELL"

        if side is None:
            return None

        if side == "BUY":
            cs.ping_times_buy.append(ts)
            cs.pings_hour_buy += 1
        else:
            cs.ping_times_sell.append(ts)
            cs.pings_hour_sell += 1

        # A new "episode" starts after a quiet gap or when the side flips, so the
        # first-ping price (used by the chase guard and absorption) never goes stale.
        if cs.first_ping_ts is not None and (
            cs.first_ping_side != side
            or (cs.last_ping_ts and ts - cs.last_ping_ts > EPISODE_GAP_SEC)
        ):
            cs.first_ping_ts = None
            cs.first_ping_side = None
            cs.first_ping_price = None

        if cs.first_ping_ts is None:
            cs.first_ping_ts = ts
            cs.first_ping_side = side
            cs.first_ping_price = close
        cs.last_ping_ts = ts
        cs.last_ping_side = side

        self._prune_old(cs, ts)

        event = {
            "symbol": symbol,
            "side": side,
            "ts": ts,
            "net": net,
            "total": total,
            "price": close,
            "T": T,
        }
        self._events.append(event)
        return event

    def _prune_old(self, cs, now):
        cutoff = now - 3600
        while cs.ping_times_buy and cs.ping_times_buy[0] < cutoff:
            cs.ping_times_buy.popleft()
        while cs.ping_times_sell and cs.ping_times_sell[0] < cutoff:
            cs.ping_times_sell.popleft()

    def _count_in(self, times, now, minutes):
        cutoff = now - minutes * 60
        return sum(1 for t in times if t >= cutoff)

    def _color(self, pings_15m):
        if pings_15m >= RED_MIN:
            return "red"
        if pings_15m >= YELLOW_MIN:
            return "yellow"
        return "none"

    def _absorbed(self, cs, side, now):
        times = cs.ping_times_buy if side == "BUY" else cs.ping_times_sell
        recent = [t for t in times if t >= now - ABSORB_WINDOW_SEC]
        if len(recent) < ABSORB_PINGS:
            return False
        if cs.first_ping_price is None or cs.price <= 0:
            return False
        if cs.first_ping_side != side or cs.first_ping_price <= 0:
            return False
        move = (cs.price - cs.first_ping_price) / cs.first_ping_price * 100.0
        if side == "SELL":
            move = -move
        return move < ABSORB_MOVE_PCT

    def row_for(self, symbol, now=None, side=None):
        cs = self.coins.get(symbol)
        if cs is None:
            return None
        now = now if now is not None else time.time()
        self._prune_old(cs, now)

        buy_5 = self._count_in(cs.ping_times_buy, now, 5)
        buy_15 = self._count_in(cs.ping_times_buy, now, 15)
        buy_60 = self._count_in(cs.ping_times_buy, now, 60)
        sell_5 = self._count_in(cs.ping_times_sell, now, 5)
        sell_15 = self._count_in(cs.ping_times_sell, now, 15)
        sell_60 = self._count_in(cs.ping_times_sell, now, 60)

        if side is None:
            if cs.last_ping_side:
                side = cs.last_ping_side
            elif buy_15 >= sell_15:
                side = "BUY"
            else:
                side = "SELL"

        if side == "BUY":
            p5, p15, p60 = buy_5, buy_15, buy_60
            p_hour = cs.pings_hour_buy
        else:
            p5, p15, p60 = sell_5, sell_15, sell_60
            p_hour = cs.pings_hour_sell

        net_vol_usdt = cs.recent_net
        net_vol_pct = 0.0
        if cs.quote_vol_24h > 0:
            net_vol_pct = (cs.recent_net / cs.quote_vol_24h) * 100.0

        move_since = 0.0
        if cs.first_ping_price and cs.first_ping_price > 0 and cs.price > 0:
            raw = (cs.price - cs.first_ping_price) / cs.first_ping_price * 100.0
            if cs.first_ping_side == "SELL":
                raw = -raw
            move_since = raw

        absorbed = self._absorbed(cs, side, now)

        return {
            "symbol": symbol,
            "side": side,
            "color": self._color(p15),
            "pings_5m": p5,
            "pings_15m": p15,
            "pings_60m": p60,
            "pings_hour": p_hour,
            "net_vol_usdt": round(net_vol_usdt, 2),
            "net_vol_pct": round(net_vol_pct, 4),
            "recent_total": round(cs.recent_total, 2),
            "recent_vol_pct": round(cs.recent_vol_pct, 4),
            "recent_net": round(cs.recent_net, 2),
            "price": cs.price,
            "move_since_first_ping_pct": round(move_since, 4),
            "absorbed": absorbed,
            "first_ping_ts": cs.first_ping_ts,
            "last_ping_ts": cs.last_ping_ts,
            "in_watchlist": cs.in_watchlist,
            "ema30": cs.ema30,
            "ema50": cs.ema50,
        }

    def all_rows(self, now=None, only_with_pings=True):
        now = now if now is not None else time.time()
        rows = []
        for sym in list(self.coins.keys()):
            cs = self.coins[sym]
            if only_with_pings and cs.last_ping_ts is None:
                continue
            row = self.row_for(sym, now=now)
            if row:
                rows.append(row)
        rows.sort(key=lambda r: r.get("last_ping_ts") or 0, reverse=True)
        return rows

    def pop_events(self):
        ev = self._events
        self._events = []
        return ev

    def drop_quiet(self, candidates, quiet_min, now=None):
        now = now if now is not None else time.time()
        drop = []
        for sym in list(candidates):
            cs = self.coins.get(sym)
            if cs is None or cs.in_watchlist:
                continue
            if cs.last_ping_ts is None:
                continue
            if now - cs.last_ping_ts >= quiet_min * 60:
                drop.append(sym)
        return drop
