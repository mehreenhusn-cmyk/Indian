"""Background snapshot of the REAL Binance account (open positions + USDT wallet).

Why this exists: in LIVE mode every status tick used to ask Binance for the positions and the app
waited for that answer (the "tick slow 464 ms" warning, pull-to-refresh spinning). Now ONE small
background thread asks Binance every ~1.5 s and everybody else (status, websocket, wallet card)
only reads the last answer from memory - no network wait on the price/status path.

Safe by design: it only runs while live_trading_enabled is on; it never places or changes orders.
"""
import threading
import time

from . import settings_store

POS_EVERY_SEC = 1.5          # positions refresh while LIVE is on
WALLET_EVERY_SEC = 4.0       # wallet changes slower than positions
IDLE_SEC = 3.0               # LIVE off: just check the flag again

_lock = threading.Lock()
_pos = {"ts": 0.0, "val": [], "ok": False}
_wallet = {"ts": 0.0, "val": None}
_started = False


def _live_on():
    try:
        if not settings_store.get("live_trading_enabled", False):
            return False
        from . import exchange
        return exchange.active() == "binance"
    except Exception:
        return False


def _fetch_positions():
    try:
        from . import exchange
        val = exchange.get_open_positions()
        with _lock:
            _pos["ts"] = time.time()
            _pos["val"] = val
            _pos["ok"] = True
        return val
    except Exception:
        return None


def _fetch_wallet():
    try:
        from . import binance_trader
        w = binance_trader.get_wallet_summary()
    except Exception as e:
        w = {"ok": False, "error": str(e)[:160], "ts": time.time()}
    with _lock:
        _wallet["ts"] = time.time()
        _wallet["val"] = w
    return w


def _loop():
    last_wallet = 0.0
    while True:
        try:
            if not _live_on():
                time.sleep(IDLE_SEC)
                continue
            _fetch_positions()
            if time.time() - last_wallet >= WALLET_EVERY_SEC:
                _fetch_wallet()
                last_wallet = time.time()
        except Exception:
            pass
        time.sleep(POS_EVERY_SEC)


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="live-snapshot", daemon=True).start()


def get_positions():
    """Last known real positions. Never waits for Binance, except the very first call
    (nothing cached yet) or when the thread has been silent for 10+ s."""
    with _lock:
        age = time.time() - _pos["ts"]
        val = list(_pos["val"])
    if _pos["ts"] == 0.0 or age > 10.0:
        fresh = _fetch_positions()
        if fresh is not None:
            return list(fresh)
    return val


def get_wallet():
    """Last known wallet dict ({"ok": ..}) or None before the first fetch."""
    with _lock:
        w = _wallet["val"]
        age = time.time() - _wallet["ts"]
    if w is None or age > 30.0:
        w = _fetch_wallet()
    return dict(w) if isinstance(w, dict) else None


def peek_wallet():
    """Memory-only wallet read for the status path (never calls Binance, safe on the event loop)."""
    with _lock:
        w = _wallet["val"]
    if isinstance(w, dict):
        return dict(w)
    return {"ok": False, "error": "Loading wallet...", "loading": True}


def held_live_symbols_strict():
    """Fresh (not cached) set of symbols with a REAL open position. Raises if Binance cannot be
    read - the max-open check must then BLOCK the entry instead of guessing "nothing open"."""
    from . import binance_trader
    rows = binance_trader.get_open_positions(strict=True)
    return {str(p.get("symbol")).upper() for p in rows if p.get("symbol")}
