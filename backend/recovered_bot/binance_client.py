"""Binance USDT-M Futures public REST client - candles, movers, live price.

Mirrors kucoin_client.py's public interface EXACTLY (same function names,
same argument shapes, same return shapes) so exchange.py can dispatch
between the two without anything upstream (strategy/paper_trader/
trade_store/Flutter) knowing or caring which exchange is active:
  - get_active_usdt_symbols(max_age=0.0) -> {symbol: last_price}
  - get_ranked_movers()                  -> [{"symbol","pct24h","price"}, ...]
  - get_price(symbol)                    -> float
  - get_klines(symbol, granularity_min, limit, fast) -> oldest-first list of
    {"timestamp","open","high","low","close","volume"} dicts

KEY DIFFERENCES FROM KUCOIN (read before touching anything here):
  - Symbols look like "BTCUSDT" (no "M" suffix), not KuCoin's "XBTUSDTM".
  - Binance's own 24hr ticker DOES include a ready-made priceChangePercent,
    but this app got burned twice in the past trusting an exchange's own
    rolling-window % field (see kucoin_client.py's docstring) - so, same as
    KuCoin, pct24h here is calculated OURSELVES as (current - UTC-day-open)
    / UTC-day-open * 100, using Binance's own 1-day kline for the day-open
    price. Same logic, same day-open cache shape as kucoin_client.py.
  - Binance's klines endpoint returns up to 1500 rows in ONE call (vs
    KuCoin's 200-row cap) - no pagination loop needed here.
  - Only USDT-margined PERPETUAL contracts are included (matches KuCoin's
    "active, USDT-quoted, no expireDate" filter) - quarterly/delivery
    contracts and coin-margined (COIN-M) symbols are excluded.
"""
import logging
import time
from datetime import datetime, timezone

from .http_client import get_session, get_fast_session

log = logging.getLogger("binance_client")

BASE_URL = "https://fapi.binance.com"
GRANULARITY_MIN = 5   # 5-minute candles - same timeframe as KuCoin, so switching exchanges
                        # mid-session doesn't change the strategy's own timeframe.
REQUEST_TIMEOUT_SEC = 10
FAST_TIMEOUT = (4, 10)

_INTERVAL_MAP = {1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m", 60: "1h",
                  120: "2h", 240: "4h", 480: "8h", 720: "12h", 1440: "1d"}


def _interval_str(granularity_min):
    return _INTERVAL_MAP.get(int(granularity_min), f"{int(granularity_min)}m")


def _get(path, params=None, fast=False, timeout=None):
    url = BASE_URL + path
    session = get_fast_session() if fast else get_session()
    resp = session.get(url, params=params, timeout=timeout or (FAST_TIMEOUT if fast else REQUEST_TIMEOUT_SEC))
    resp.raise_for_status()
    return resp.json()


# ---- SERVER TIME SYNC ------------------------------------------------------
# "Is this candle closed yet?" and "how old is this signal?" are decided with
# a clock. If the phone's clock is a few seconds off Binance's, candles look
# still-forming (delayed trades) or signals look older/younger than they are.
# We measure Binance's clock offset (round-trip corrected) and expose it.
_time_offset_ms = 0.0
_time_offset_last_sync = 0.0


def sync_server_time(samples=3):
    """Median of a few /fapi/v1/time samples -> offset (server - local) in ms.
    Never raises; keeps the previous offset if the network fails."""
    global _time_offset_ms, _time_offset_last_sync
    offs = []
    for _ in range(max(1, samples)):
        try:
            t0 = time.time()
            data = _get("/fapi/v1/time", fast=True, timeout=(3, 5))
            t1 = time.time()
            server_ms = float(data["serverTime"])
            offs.append(server_ms - ((t0 + t1) / 2.0) * 1000.0)
        except Exception:
            continue
    if offs:
        offs.sort()
        _time_offset_ms = offs[len(offs) // 2]
        _time_offset_last_sync = time.time()
    return _time_offset_ms


def server_time_offset_ms():
    return _time_offset_ms


def _current_utc_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_day_start_ms():
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp() * 1000)


_symbols_cache = {"ts": 0.0, "symbols": None}
_SYMBOLS_TTL = 3600  # which symbols are active USDT-M perpetuals basically never changes intraday


def _active_perpetual_symbols():
    """Cached set of tradeable USDT-margined PERPETUAL symbols, from
    /fapi/v1/exchangeInfo - used to filter the bulk ticker call down to
    exactly the same universe KuCoin's "USDT quote, no expireDate" filter
    covers."""
    now = time.time()
    if _symbols_cache["symbols"] is not None and now - _symbols_cache["ts"] <= _SYMBOLS_TTL:
        return _symbols_cache["symbols"]
    data = _get("/fapi/v1/exchangeInfo", timeout=(5, 15))
    out = set()
    for s in data.get("symbols", []):
        if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL" and s.get("status") == "TRADING":
            out.add(s.get("symbol"))
    if out:
        _symbols_cache["symbols"] = out
        _symbols_cache["ts"] = now
    return out or (_symbols_cache["symbols"] or set())


_price_cache = {"ts": 0.0, "map": {}}


def get_active_usdt_symbols(max_age=0.0):
    """{symbol: last_price} for every active USDT-M perpetual - one bulk
    REST call, same role as kucoin_client's function of the same name (also
    what market_ws.py's REST-poll path reuses when Binance's WebSocket feed
    is down)."""
    now = time.time()
    if max_age and _price_cache["map"] and now - _price_cache["ts"] <= max_age:
        return dict(_price_cache["map"])
    valid = _active_perpetual_symbols()
    data = _get("/fapi/v1/ticker/price", fast=True, timeout=(5, 15))
    out = {}
    for row in data:
        symbol = row.get("symbol")
        if valid and symbol not in valid:
            continue
        price = row.get("price")
        if symbol and price is not None:
            try:
                out[symbol] = float(price)
            except (TypeError, ValueError):
                continue
    if out:
        _price_cache["map"] = out
        _price_cache["ts"] = time.time()
    return out


_day_open_cache = {"date": None, "opens": {}, "no_data": set()}
DAY_OPEN_FIRST_FILL_BUDGET = 45
DAY_OPEN_TOPUP_BUDGET = 12
DAY_OPEN_TOPUP_BATCH = 60


def _fetch_day_open(symbol):
    try:
        from_ms = _utc_day_start_ms()
        data = _get("/fapi/v1/klines", {
            "symbol": symbol, "interval": "1d", "startTime": from_ms, "limit": 1,
        }, fast=True)
        if data:
            # Binance kline row: [openTime, open, high, low, close, volume, ...]
            return symbol, float(data[0][1]), "ok"
        return symbol, None, "no_data"
    except Exception:
        return symbol, None, "error"


def _refresh_day_opens(symbols):
    """Same incremental, time-budgeted fill as kucoin_client._refresh_day_opens
    - see that docstring for why this isn't one giant blocking burst."""
    import concurrent.futures as cf
    today = _current_utc_date()
    if _day_open_cache["date"] != today:
        _day_open_cache["date"] = today
        _day_open_cache["opens"] = {}
        _day_open_cache["no_data"] = set()

    opens = _day_open_cache["opens"]
    no_data = _day_open_cache["no_data"]
    missing = [s for s in symbols if s not in opens and s not in no_data]
    if not missing:
        return opens

    first_fill = len(opens) == 0
    budget = DAY_OPEN_FIRST_FILL_BUDGET if first_fill else DAY_OPEN_TOPUP_BUDGET
    batch = missing if first_fill else missing[:DAY_OPEN_TOPUP_BATCH]

    ex = cf.ThreadPoolExecutor(max_workers=12)
    futures = [ex.submit(_fetch_day_open, s) for s in batch]
    try:
        for fut in cf.as_completed(futures, timeout=budget):
            symbol, open_price, state = fut.result()
            if state == "ok" and open_price:
                opens[symbol] = open_price
            elif state == "no_data":
                no_data.add(symbol)
    except cf.TimeoutError:
        log.warning("Day-open fill hit its %ss budget; %d symbols still pending", budget, len(missing))
    finally:
        try:
            ex.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            ex.shutdown(wait=False)
    return opens


def get_ranked_movers():
    """Full list of {symbol, pct24h, price}, sorted descending by pct24h -
    same shape/role as kucoin_client.get_ranked_movers()."""
    try:
        price_map = get_active_usdt_symbols(max_age=6.0)
    except Exception:
        if _price_cache["map"] and time.time() - _price_cache["ts"] < 90:
            price_map = dict(_price_cache["map"])
        else:
            raise
    day_opens = _refresh_day_opens(list(price_map.keys()))

    calc = []
    for symbol, cur_price in price_map.items():
        open_price = day_opens.get(symbol)
        if not open_price:
            continue
        pct = (cur_price - open_price) / open_price * 100.0
        calc.append({"symbol": symbol, "pct24h": pct, "price": cur_price})

    calc.sort(key=lambda d: d["pct24h"], reverse=True)
    return calc


def get_daily_candles(symbol, limit=10):
    """[(open_time_ms, open, close), ...] oldest-first, UTC-day candles (they open at 00:00 UTC =
    5:30 AM IST, the app's trading-day change). The last row is today's still-forming candle.
    Daily candles for a symbol."""
    data = _get("/fapi/v1/klines", {"symbol": symbol, "interval": "1d", "limit": max(1, min(int(limit), 100))},
                fast=True)
    return [(int(r[0]), float(r[1]), float(r[4])) for r in data]


def get_price(symbol):
    data = _get("/fapi/v1/ticker/price", {"symbol": symbol}, fast=True)
    return float(data["price"])


# ---- ONE SHARED CANDLE STORE ----------------------------------------------
# Many parts of the backend ask for the same coin's candles. Before, each one called Binance on its own
# (~128 REST calls a minute). Now the rows are kept here and shared:
#   closed_only=True  (signals, trade management): the closed candles cannot change until the forming
#                     candle closes, so the stored rows are reused until then - no matter who asks.
#   closed_only=False (chart display with the live forming candle): reused for only a few seconds.
# Never raises from the cache itself; on any doubt it just asks Binance like before.
import threading as _threading

_KLINE_LIVE_TTL_S = 3.0
_KLINE_MAX_KEYS = 400
_kline_cache = {}                       # (symbol, interval) -> {"rows": [...], "at": epoch_s}
_kline_lock = _threading.Lock()
_kline_stats = {"hits": 0, "misses": 0}


def kline_cache_stats():
    with _kline_lock:
        d = dict(_kline_stats)
        d["keys"] = len(_kline_cache)
    n = d["hits"] + d["misses"]
    d["hit_pct"] = round(100.0 * d["hits"] / n, 1) if n else None
    return d


def _kline_now_ms():
    return time.time() * 1000.0 + _time_offset_ms


def _kline_cached(key, limit, closed_only, interval_ms):
    with _kline_lock:
        e = _kline_cache.get(key)
    if not e or len(e["rows"]) < limit:
        return None
    rows = e["rows"]
    if closed_only:
        # valid until the last stored (forming) candle has closed
        if _kline_now_ms() < int(rows[-1][0]) + interval_ms:
            return rows[-limit:]
        return None
    if time.time() - e["at"] < _KLINE_LIVE_TTL_S:
        return rows[-limit:]
    return None


def get_klines(symbol, granularity_min=None, limit=250, fast=False, closed_only=False):
    """Oldest-first candles, same dict shape as kucoin_client.get_klines().
    Binance returns up to 1500 rows per call - no pagination needed for any
    limit this app actually uses. Rows come from the shared candle store when they are still valid."""
    granularity_min = granularity_min or GRANULARITY_MIN
    interval = _interval_str(granularity_min)
    limit = max(1, min(int(limit), 1500))
    key = (symbol, interval)
    interval_ms = int(granularity_min) * 60000

    data = None
    try:
        data = _kline_cached(key, limit, closed_only, interval_ms)
    except Exception:
        data = None
    if data is not None:
        with _kline_lock:
            _kline_stats["hits"] += 1
    else:
        with _kline_lock:
            _kline_stats["misses"] += 1
        # fetch a little more than asked so a later, slightly bigger request is still a hit
        want = min(1500, max(limit, 300))
        data = _get("/fapi/v1/klines", {
            "symbol": symbol, "interval": interval, "limit": want,
        }, fast=fast)
        try:
            with _kline_lock:
                if len(_kline_cache) >= _KLINE_MAX_KEYS:
                    for k in sorted(_kline_cache, key=lambda k: _kline_cache[k]["at"])[:50]:
                        _kline_cache.pop(k, None)
                _kline_cache[key] = {"rows": data, "at": time.time()}
        except Exception:
            pass
        data = data[-limit:]

    candles = []
    for row in data:
        # Binance kline row: [openTime, open, high, low, close, volume, closeTime, ...]
        candles.append({
            "timestamp": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })
    return candles
