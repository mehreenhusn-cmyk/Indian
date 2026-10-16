"""recovered_bot/timeframe_manager.py

PART 3 - SINGLE SOURCE OF TRUTH FOR THE ACTIVE CANDLE TIMEFRAME
(Binance USDT-M Futures only - KuCoin is completely excluded this round,
same as exchange.py/protection_manager.py/reconciliation.py).

Before this module, the "current timeframe" was read directly out of
settings_store in more than one place (exchange.py's
active_strategy_timeframe_min(), api_server.py's /api/candles handler)
with each call site doing its own default-handling/validation - two
places that could, in principle, drift out of agreement if one got edited
and the other didn't. TimeframeManager is now the ONE place that knows
"what timeframe is currently active" and "is this a supported timeframe" -
every other module (exchange.py included) asks this module instead of
reading settings_store's "timeframe" key directly.

Thread-safe module-level singleton: the process-wide active timeframe is
cached in-memory after the first read/set (avoids re-hitting the settings
file on every single scan-loop tick), guarded by a lock for the
lazy-init + read/write path, and always persisted back to settings_store
on set_active_timeframe() so the choice survives a backend restart.
"""
import logging
import threading
import time
from typing import Optional

from . import settings_store

log = logging.getLogger("timeframe_manager")

# The only timeframes this app - and Binance's native /fapi/v1/klines
# endpoint - supports. No exchange-specific rounding/substitution exists
# any more (that was a KuCoin-only concern; see exchange.py's docstring).
SUPPORTED_TIMEFRAMES = ("1m", "3m", "5m", "15m", "1h")
DEFAULT_TIMEFRAME = "5m"

_INTERVAL_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "1h": 60}

# --------------------------------------------------- stale-data circuit breaker --
# PART 4 - PER-SYMBOL CANDLE FRESHNESS (replaces the old global market_ws
# live-tick 8s-window gate that was deliberately removed on 2026-09-25: that
# gate was scanner-wide, so ONE slow/rate-limited symbol froze new entries
# for every symbol, which itself degraded the whole scanner under load - a
# self-inflicted slowdown, not a real safety win. This is scoped per symbol
# instead: only the symbol whose own candle data has actually gone stale
# gets its entries blocked; every other symbol, and all EXISTING open
# positions' protection/monitoring loops (which never call is_fresh()), are
# completely unaffected.
#
# STALE_DATA_MAX_AGE_SEC is deliberately a few poll cycles wide (app.py's
# POLL_INTERVAL is 8s) rather than exactly one cycle, so a single slow/
# retried HTTP call for one symbol doesn't false-trip the breaker - this is
# meant to catch a symbol that has gone genuinely quiet (delisted, thin,
# rate-limited, or the poll loop itself stalled on that symbol), not normal
# jitter.
STALE_DATA_MAX_AGE_SEC = 30


def _normalize(tf):
    """Lowercases/strips and validates against SUPPORTED_TIMEFRAMES.
    Anything unrecognised (None, empty, a typo, a stale KuCoin-era value)
    falls back to DEFAULT_TIMEFRAME - this function never raises and never
    returns a value outside SUPPORTED_TIMEFRAMES."""
    try:
        candidate = str(tf).strip().lower()
    except Exception:
        return DEFAULT_TIMEFRAME
    return candidate if candidate in SUPPORTED_TIMEFRAMES else DEFAULT_TIMEFRAME


class TimeframeManager:
    """Lightweight singleton - use module-level get_active_timeframe()/
    set_active_timeframe()/get_interval_minutes() below rather than
    instantiating this directly; they always operate on the one shared
    instance. Exists as a class (rather than bare module globals) so a
    future multi-account/multi-bot-instance build can hold more than one
    of these without a rewrite."""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._state_lock = threading.Lock()
                    inst._cached_tf = None  # populated lazily on first read/write
                    inst._fetch_lock = threading.Lock()
                    inst._last_fetch_ts = {}  # symbol -> time.time() of its last successful candle fetch
                    cls._instance = inst
        return cls._instance

    def get_active_timeframe(self) -> str:
        """Returns the currently active timeframe label (e.g. "5m").
        First call in a process reads+validates settings_store["timeframe"]
        and caches the result; every call after that returns the cached
        value instantly UNTIL set_active_timeframe() changes it - so a
        Settings-screen edit made through this module's own setter takes
        effect immediately, while a hot scan loop calling this every tick
        doesn't pay a settings-file read every time."""
        with self._state_lock:
            if self._cached_tf is not None:
                return self._cached_tf
            stored = settings_store.get("timeframe", DEFAULT_TIMEFRAME)
            self._cached_tf = _normalize(stored)
            return self._cached_tf

    def set_active_timeframe(self, tf: str) -> str:
        """Validates `tf`, updates the in-memory cache AND persists it to
        settings_store (so it survives a backend restart), and returns the
        value actually applied (which may differ from what was passed in,
        if it wasn't a supported timeframe - callers should use the
        return value, not assume their input was accepted verbatim)."""
        normalized = _normalize(tf)
        if str(tf).strip().lower() != normalized:
            log.warning("set_active_timeframe(%r) is not supported - using %r instead", tf, normalized)
        with self._state_lock:
            self._cached_tf = normalized
        try:
            settings_store.update(timeframe=normalized)
        except Exception as e:
            log.warning("set_active_timeframe(%r): could not persist to settings_store - %s", normalized, e)
        return normalized

    def get_interval_minutes(self, tf: str = None) -> int:
        """Minutes for `tf` (or the currently active timeframe if `tf` is
        omitted). Always returns a valid int from _INTERVAL_MINUTES - an
        unsupported `tf` is normalized first, so this can never raise or
        return a value for an unsupported timeframe."""
        label = _normalize(tf) if tf is not None else self.get_active_timeframe()
        return _INTERVAL_MINUTES[label]

    def mark_fetched(self, symbol: str) -> None:
        """Call this the moment a symbol's candle data is successfully
        fetched (app.py's poll_klines() loop, right after _fetch_kline_for
        returns a result) - stamps "now" as this symbol's last-known-good
        data time. Never raises; a bad `symbol` just becomes a harmless
        dict key."""
        with self._fetch_lock:
            self._last_fetch_ts[symbol] = time.time()

    def seconds_since_fetch(self, symbol: str) -> Optional[float]:
        """Seconds since mark_fetched(symbol) was last called, or None if
        this symbol has never been fetched successfully in this process
        (e.g. brand new to the watchlist, or backend just restarted)."""
        with self._fetch_lock:
            ts = self._last_fetch_ts.get(symbol)
        return None if ts is None else time.time() - ts

    def is_fresh(self, symbol: str, max_age_sec: float = None) -> bool:
        """True only if `symbol` has been successfully fetched within the
        last `max_age_sec` seconds (defaults to STALE_DATA_MAX_AGE_SEC).
        A symbol with NO recorded fetch yet is treated as NOT fresh - a
        fail-safe default, since "we don't know" should block a brand-new
        entry the same way "we know it's stale" does. This only gates
        whether _open_signal() may open a NEW position on this symbol;
        it is never checked by the protection/monitoring loop, so existing
        open positions keep being managed normally regardless of this
        symbol's current freshness."""
        age = self.seconds_since_fetch(symbol)
        if age is None:
            return False
        threshold = STALE_DATA_MAX_AGE_SEC if max_age_sec is None else max_age_sec
        return age <= threshold


# ------------------------------------------------------- module-level API --
# Preferred call style for the rest of the codebase - avoids every caller
# needing to instantiate/import the class itself.
_manager = TimeframeManager()


def get_active_timeframe() -> str:
    return _manager.get_active_timeframe()


def set_active_timeframe(tf: str) -> str:
    return _manager.set_active_timeframe(tf)


def get_interval_minutes(tf: str = None) -> int:
    return _manager.get_interval_minutes(tf)


def mark_fetched(symbol: str) -> None:
    _manager.mark_fetched(symbol)


def seconds_since_fetch(symbol: str) -> Optional[float]:
    return _manager.seconds_since_fetch(symbol)


def is_fresh(symbol: str, max_age_sec: float = None) -> bool:
    return _manager.is_fresh(symbol, max_age_sec)
