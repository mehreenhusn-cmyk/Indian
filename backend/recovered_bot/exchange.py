"""exchange.py - Binance Futures (/fapi) dispatcher.

PART 3 - KUCOIN FULLY EXCLUDED
--------------------------------
Binance USDT-M Futures (fapi.binance.com) is now the SOLE exchange this
module talks to, no matter what settings_store["active_exchange"] still
holds on disk - see active() below, which is hard-pinned to "binance".
kucoin_client.py/kucoin_trader.py are left completely alone in this repo
(out of scope for this round, not deleted) but exchange.py no longer
routes anything to them. Nothing upstream (strategy.py, paper_trader.py,
trade_store.py, the Flutter app) needed to change for this, since every
caller already went through this module's get_klines()/get_price()/
open_market_order()/etc. and never imported kucoin_client/kucoin_trader
directly.

PART 3 - NATIVE TIMEFRAMES, NO ROUNDING
------------------------------------------
KuCoin's missing-3-minute-granularity rounding fallback (3m -> 5m) is
gone entirely - Binance's kline endpoint natively supports every
timeframe this app offers (1m/3m/5m/15m/1h, see TIMEFRAME_LABEL_TO_MIN),
so resolve_timeframe() below no longer substitutes anything; a requested
timeframe either IS one of the five supported values or falls back to the
5m default, never silently rounded to a different value.
timeframe_manager.py is now the single source of truth for WHICH
timeframe is currently active (settings_store["timeframe"], read fresh
every call) - active_strategy_timeframe_min() below just resolves
whatever that module reports.

PART 3 - CLOSED CANDLES ONLY
--------------------------------
Binance's /fapi/v1/klines always includes the currently-forming candle as
its LAST row - trading a signal off that row means trading off a candle
that hasn't finished forming and can still change. get_klines() below
enforces "closed candles only": it fetches one extra row, and drops the
trailing row whenever that row's own close time (openTime + interval)
hasn't happened yet. Equivalent to always reading data[-2] instead of
data[-1] as "the latest candle" from the raw exchange response, while
still handing the caller exactly the `limit` closed candles they asked
for (not limit-1).
"""
import logging
import time

from . import settings_store, timeframe_manager  # noqa: F401  (settings_store kept for
                                                    # backward-compat callers reading
                                                    # exchange.settings_store indirectly)

log = logging.getLogger("exchange")

SUPPORTED = ("binance",)  # KuCoin fully excluded from active execution this round.

DEFAULT_TIMEFRAME_MIN = 5
SUPPORTED_TIMEFRAMES_MIN = (1, 3, 5, 15, 60)

# Label <-> minutes for the Settings screen's Timeframe selector
# (settings_store["timeframe"], a string like "5m"/"1h"). Mirrors
# timeframe_manager.SUPPORTED_TIMEFRAMES exactly - kept here too since
# several existing call sites (app.py, api_server.py's /api/candles) read
# these two dicts directly.
TIMEFRAME_LABEL_TO_MIN = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "1h": 60}
TIMEFRAME_MIN_TO_LABEL = {v: k for k, v in TIMEFRAME_LABEL_TO_MIN.items()}


def timeframe_label_to_min(label, default=DEFAULT_TIMEFRAME_MIN):
    """"1m"/"3m"/"5m"/"15m"/"1h" -> minutes. Unrecognised label -> default."""
    try:
        return TIMEFRAME_LABEL_TO_MIN.get(str(label).strip().lower(), default)
    except Exception:
        return default


def resolve_timeframe(tf=None):
    """Validate/normalize a requested candle timeframe. Accepts either
    minutes (int/str number, e.g. 5) or a label (e.g. "5m"/"1h"). Binance
    supports every timeframe this app offers natively - no exchange-
    specific rounding is applied any more (see module docstring).
    tf=None (or anything not resolvable) -> DEFAULT_TIMEFRAME_MIN (5m)."""
    if isinstance(tf, str) and tf.strip().lower() in TIMEFRAME_LABEL_TO_MIN:
        tf = TIMEFRAME_LABEL_TO_MIN[tf.strip().lower()]
    else:
        try:
            tf = int(tf) if tf is not None else DEFAULT_TIMEFRAME_MIN
        except (TypeError, ValueError):
            tf = DEFAULT_TIMEFRAME_MIN
    if tf not in SUPPORTED_TIMEFRAMES_MIN:
        tf = DEFAULT_TIMEFRAME_MIN
    return tf


def active_strategy_timeframe_min():
    """The CONFIGURED strategy/scanner timeframe, sourced from
    timeframe_manager (PART 3's single source of truth) rather than
    reading settings_store directly here - still resolved through
    resolve_timeframe() so an unsupported/corrupt stored value can never
    reach a caller. Read fresh on every call (timeframe_manager itself
    never caches across a settings change)."""
    label = timeframe_manager.get_active_timeframe()
    return resolve_timeframe(label)


def active():
    """Binance is the sole active exchange - KuCoin is fully excluded
    regardless of whatever settings_store["active_exchange"] still holds
    (that key/its Settings UI toggle are left alone, just no longer
    consulted here). Kept as a function, not a constant, so every existing
    caller (reconciliation.py's _binance_active(), execution_router.py's
    `exchange.active() != "binance"` guards) keeps working unchanged."""
    return "binance"


def _data_module():
    from . import binance_client
    return binance_client


def _trade_module():
    from . import binance_trader
    return binance_trader


def __getattr__(name):
    # PEP 562 module-level dynamic attribute - lets callers read
    # exchange.GRANULARITY_MIN exactly like they used to read
    # binance_client.GRANULARITY_MIN.
    if name == "GRANULARITY_MIN":
        return _data_module().GRANULARITY_MIN
    raise AttributeError(f"module 'exchange' has no attribute {name!r}")


# ---------------------------------------------------------------- data -----

def now_ms():
    """Binance-synced 'now' in ms (local clock + measured server offset)."""
    try:
        off = _data_module().server_time_offset_ms()
    except Exception:
        off = 0.0
    return int(time.time() * 1000 + off)


def now_sec():
    return now_ms() / 1000.0


def sync_server_time():
    try:
        return _data_module().sync_server_time()
    except Exception:
        return 0.0


def _enforce_closed_candles(candles, granularity_min):
    """Drops a trailing still-forming candle. `candles` is the data
    module's own oldest-first list of {"timestamp",...} dicts - this
    checks only the LAST one (the only row that can possibly still be
    open), so this is an O(1) check, not a re-scan of the whole list.
    Never raises and never mutates `candles` in place; falls back to
    returning the list unchanged if the check itself hits anything
    unexpected (a clock-skew edge case must never zero out a caller's
    candle history)."""
    if not candles:
        return candles
    try:
        interval_ms = int(granularity_min) * 60_000
        close_time_ms = int(candles[-1]["timestamp"]) + interval_ms
        if close_time_ms > now_ms():
            return candles[:-1]
    except Exception:
        return candles
    return candles


def get_klines(symbol, granularity_min=None, limit=250, fast=False, tf=None, include_forming=False):
    """tf is the preferred name for the requested timeframe (matches the
    /api/candles `tf` query param, see api_server.py) and always goes
    through resolve_timeframe() above. granularity_min is kept for every
    existing call site (app.py/paper_trader.py, which don't pass tf) - if
    both are given, tf wins. Always Binance now (see active()). Requests
    one extra row from the data module so that dropping a still-forming
    trailing candle (_enforce_closed_candles above) still leaves the
    caller with exactly `limit` CLOSED candles, not limit-1.

    include_forming=False (default): unchanged behaviour - the trailing
    still-forming candle is always dropped (_enforce_closed_candles), so
    every existing caller (app.py's signal generation, paper_trader.py's
    reconcile_position candle-replay) keeps trading strictly off CLOSED
    candles, exactly as before. Pass include_forming=True ONLY from a
    display/UI call site (api_server.py's /api/candles) that wants to draw
    Binance's real live forming candle as the chart's last bar - it must
    never be turned on anywhere a signal decision gets made."""
    resolved = resolve_timeframe(tf if tf is not None else granularity_min)
    fetch_limit = max(1, min(int(limit) + 1, 1500))
    candles = _data_module().get_klines(symbol, granularity_min=resolved, limit=fetch_limit, fast=fast)
    if not include_forming:
        candles = _enforce_closed_candles(candles, resolved)
    if len(candles) > limit:
        candles = candles[-limit:]
    return candles


def get_price(symbol):
    return _data_module().get_price(symbol)


def get_active_usdt_symbols(max_age=0.0):
    return _data_module().get_active_usdt_symbols(max_age=max_age)


def get_ranked_movers():
    return _data_module().get_ranked_movers()


# -------------------------------------------------------------- trading ----

def open_market_order(symbol, action, live_price):
    return _trade_module().open_market_order(symbol, action, live_price)


def close_position_market(symbol, position_action):
    return _trade_module().close_position_market(symbol, position_action)


def get_open_positions():
    """Real open positions on Binance - see binance_trader.get_open_positions().
    Always returns a list (never raises) - api_server.py uses this to show
    real exchange positions in place of paper ones while live_trading_enabled
    is on."""
    module = _trade_module()
    fn = getattr(module, "get_open_positions", None)
    if fn is None:
        return []
    try:
        return fn() or []
    except Exception:
        return []


def test_connection():
    return _trade_module().test_connection()
