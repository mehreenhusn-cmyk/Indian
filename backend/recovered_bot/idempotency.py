"""recovered_bot/idempotency.py

Signal-level idempotency guard - stops the exact same strategy signal
(same symbol + timeframe + candle-close-time + direction) from being acted
on twice: once from the normal scanner loop and again from a reconnect/
catch-up replay, an overlapping poll cycle after a slow request, or a
duplicate WebSocket message. Deliberately independent of trade_store.py's
signal_no counter (that numbers every signal for display; this only
answers "have I already opened/skipped this exact signal instance
already").

Persisted to a small JSON file - same house pattern as trade_store.py/
signal_log.py/settings_store.py - so a restart doesn't forget the last
batch of already-processed signals and immediately replay them against a
fresh scan. Self-locates its own file under backend/data/ (the same
directory api_server.py's DATA_DIR already points at) instead of requiring
an init() call from api_server.py's startup - that file is out of scope
for this round. init(path) is still exposed for whenever a future round
wants to wire it in there explicitly, right alongside settings_store.init()
etc.; calling it is optional, not required, for this module to work.
"""
import json
import os
import threading
import time

_lock = threading.Lock()

# backend/recovered_bot/idempotency.py -> parent is backend/recovered_bot,
# parent.parent is backend/ - matches api_server.py's
# `os.path.join(os.path.dirname(__file__), "data")` DATA_DIR exactly.
_DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_DEFAULT_PATH = os.path.join(_DEFAULT_DIR, "idempotency.json")

_file = None
_processed = {}  # signal_id -> ts first marked processed

MAX_ENTRIES = 500  # generous for a scanner ticking every few seconds across
                     # a ~20-symbol watchlist - old entries are pruned by age
                     # first, this is just a hard ceiling on file size.
MAX_AGE_SEC = 24 * 3600  # a signal_id encodes its own candle-close time, which
                           # never repeats - anything this old can never
                           # legitimately reappear, so pruning it is pure
                           # housekeeping, never a correctness risk.


def init(path):
    """Optional explicit wiring - e.g. from api_server.py's startup,
    alongside settings_store.init()/trade_store.init()/etc. Not required:
    every function below works fine against the self-located default path
    if this is never called."""
    global _file
    _file = path
    _load()


def _ensure_file():
    global _file
    if _file is None:
        os.makedirs(_DEFAULT_DIR, exist_ok=True)
        _file = _DEFAULT_PATH
        _load()


def _load():
    if _file and os.path.exists(_file):
        try:
            with open(_file, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                with _lock:
                    _processed.update(data)
        except Exception:
            pass  # a corrupt/unreadable file just means "nothing recalled yet" -
                    # never crash startup over this.


def _save():
    if not _file:
        return
    try:
        os.makedirs(os.path.dirname(_file), exist_ok=True)
        with open(_file, "w") as f:
            json.dump(_processed, f)
    except Exception:
        pass  # best-effort persistence - a failed write only costs replay
                # protection across the NEXT restart, not right now.


def _prune_locked():
    """Caller must already hold _lock. Age-based prune first, then a hard
    count cap (oldest-first) if still over MAX_ENTRIES."""
    now = time.time()
    for sid in [k for k, ts in _processed.items() if (now - ts) > MAX_AGE_SEC]:
        _processed.pop(sid, None)
    if len(_processed) > MAX_ENTRIES:
        oldest_first = sorted(_processed.items(), key=lambda kv: kv[1])
        for sid, _ts in oldest_first[: len(_processed) - MAX_ENTRIES]:
            _processed.pop(sid, None)


def generate_signal_id(symbol, tf, candle_time, side):
    """Deterministic id for one exact signal instance.

    - symbol: e.g. "BTCUSDT"
    - tf: whatever timeframe value the caller already has - a label
      ("5m") or minutes (5), just stay consistent per call site, it's an
      opaque string component here either way.
    - candle_time: the signal's own candle CLOSE time - epoch
      seconds/ms, or an ISO string, anything stable and unique per candle.
      Never pass "now"/time.time() here, that defeats the entire point.
    - side: the signal's action ("BUY"/"SELL").

    Plain, readable format on purpose (not hashed) - same debugging
    philosophy as binance_trader.py's clientOrderId: easy to eyeball in
    logs/alerts instead of a hex blob."""
    return f"{symbol}:{tf}:{candle_time}:{str(side).upper()}"


def is_already_processed(signal_id):
    """True if mark_processed() has already been called for this exact
    signal_id (and it hasn't aged out - see MAX_AGE_SEC)."""
    _ensure_file()
    with _lock:
        return signal_id in _processed


def mark_processed(signal_id):
    """Records this signal_id as handled - call this once a signal has
    actually been dispatched (opened live/paper, or deliberately skipped)
    so a duplicate delivery of the same signal is recognized next time.
    Idempotent itself: marking the same id twice just refreshes its
    timestamp, never duplicates or errors. Always returns True - this is
    a best-effort guard, not something that should ever raise into a
    scanner loop."""
    _ensure_file()
    with _lock:
        _processed[signal_id] = time.time()
        _prune_locked()
    _save()
    return True
