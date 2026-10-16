import copy
import threading
import time

_lock = threading.Lock()
_status = {
    "status": "Starting...",
    "symbols_tracked": 0,
    "watchlist": [],
    "last_signals": [],
    "last_error": None,
    "today_pnl_usdt": 0.0,
    "total_trades": 0,
    "win_rate": 0.0,
    "open_positions": [],
    "signals_today": 0,
    "market_movers": [],
    "market_synced_at": None,  # time.time() of the last successful movers fetch, for "Last synced Xs ago"
    "last_signal_by_symbol": {},  # symbol -> {"action": "BUY"/"SELL", "time": "HH:MM:SS"}
    "alerts": [],  # newest first, capped MAX_ALERTS. Each: {"type","text","time","ts","d": {...detail...}}
    "alerts_rev": 0,  # bumped on every add_alert - lets the WebSocket skip re-sending the alert list when unchanged
    "api_weight_1m": 0,
    "ws_connected": False,       # price-feed state (live ticker cache only - signal engine is unaffected)
    "market_data_state": "DISCONNECTED",  # CONNECTING / LIVE / RECONNECTING / STALE / DISCONNECTED
    "ws_reconnect_count": 0,
    "market_data_error": None,
    "telegram_last_attempt_ts": None,
    "telegram_last_ok": None,
    "telegram_last_error": None,
    "last_poll_cycle_ts": None,
    # Result of the most recent "catch-up" check of open trades after a data gap /
    # restart / reconnect: {"ts","trigger","gap_s","checked","closed","still_open"}
    "last_reconcile": None,

    # ---- DIAGNOSTICS CARD TELEMETRY (real contract, no mock values) ----
    # Written by market_ws.py on every successful markPrice/kline tick:
    # server epoch-seconds timestamp of the last feed update this process
    # actually received - "Feed: X.Xs ago" is computed as
    # server_ts - feed_last_update_ts, never a client-guessed number.
    "feed_last_update_ts": None,
    # Exchange Event Time (Binance's own "E" field, ms) -> Engine Ingestion
    # (this process receiving+parsing the WS frame) network latency, ms.
    "feed_latency_net_ms": None,
    # Engine Ingestion -> cache-write-complete processing latency, ms (how
    # long this process itself took to apply the tick after receiving it).
    "feed_latency_engine_ms": None,
    # Result of the most recent protection guard_tick() pass (protection_manager.py):
    # {"ts","trigger","checked","sl_replaced","breakeven_moved","closed","failed","ok"}
    "last_guard_tick": None,
    # Symbols the most recent guard_tick() found with NO resting protective
    # stop on Binance (either still being fixed, or fix attempt failed) -
    # each: {"symbol","side","entry","mark_price","detected_ts"}. Empty list
    # means every open live position was confirmed protected as of that tick.
    "unprotected_positions": [],
    # Rolling log of raw Binance API error codes (e.g. -4120/-2019/-2022),
    # captured centrally at the signed-request layer in binance_trader.py
    # and protection_manager.py so every call path that can hit the
    # exchange feeds this same list. Newest first, capped at MAX_API_ERRORS.
    # Each: {"code","msg","symbol","endpoint","ts","time"}.
    "recent_api_errors": [],
}

MAX_ALERTS = 250
MAX_API_ERRORS = 30


# ---- Alerts survive a backend restart -----------------------------------
# The feed used to live only in memory, so every restart / new build emptied
# the Alerts tab. Now it is written (coalesced, atomic) to alerts.json and
# reloaded at startup. Never raises.
_alerts_file = None
_alerts_dirty = False
_alerts_writer_running = False


def init_alerts(path):
    global _alerts_file
    _alerts_file = path
    try:
        from . import safe_io
        saved, _src = safe_io.read_json_safe(path, "alerts")
        if isinstance(saved, list):
            with _lock:
                cur = _status.get("alerts", [])
                _status["alerts"] = (cur + [a for a in saved if isinstance(a, dict)])[:MAX_ALERTS] if cur else \
                    [a for a in saved if isinstance(a, dict)][:MAX_ALERTS]
                _status["alerts_rev"] = _status.get("alerts_rev", 0) + 1
    except Exception as e:
        print(f"[status] alerts load failed: {e}")


def _alerts_writer():
    global _alerts_dirty, _alerts_writer_running
    while True:
        time.sleep(2.0)
        try:
            with _lock:
                # Shallow per-alert copy only: the big deepcopy used to run UNDER the shared lock and froze the
                # event loop for 2-3 s (alerts_rev() waits on the same lock).
                snap = [dict(a) if isinstance(a, dict) else a for a in (_status.get("alerts", []) or [])]
                _alerts_dirty = False
            from . import safe_io
            import json as _json
            try:
                text = _json.dumps(snap, default=str)
            except Exception:           # an alert changed while serialising: take one consistent copy
                with _lock:
                    snap = copy.deepcopy(_status.get("alerts", []))
                text = _json.dumps(snap, default=str)
            safe_io.write_json_atomic(_alerts_file, text)
        except Exception as e:
            print(f"[status] alerts save failed: {e}")
        with _lock:
            if not _alerts_dirty:
                _alerts_writer_running = False
                return


def _mark_alerts_dirty():
    """Call AFTER the alerts list changed and the lock was released."""
    global _alerts_dirty, _alerts_writer_running
    if not _alerts_file:
        return
    with _lock:
        _alerts_dirty = True
        if _alerts_writer_running:
            return
        _alerts_writer_running = True
    threading.Thread(target=_alerts_writer, daemon=True).start()


def update(**kwargs):
    with _lock:
        _status.update(kwargs)


def add_signal(signal_text):
    with _lock:
        signals = _status.get("last_signals", [])
        signals.insert(0, signal_text)
        _status["last_signals"] = signals[:10]


def set_last_signal(symbol, action, ts):
    """Record the most recent signal seen for one symbol, for Market Watch
    display. Does not touch any other symbol's entry."""
    with _lock:
        sig_map = dict(_status.get("last_signal_by_symbol", {}))
        sig_map[symbol] = {"action": action, "time": ts}
        _status["last_signal_by_symbol"] = sig_map


def add_alert(alert_type, text, **detail):
    """Append one entry to the Alerts feed. alert_type is one of:
    'open', 'tp', 'sl', 'reversed', 'manual', 'target', 'loss', 'skip',
    'error', 'diag', 'sync' - used by the Alerts screen to pick a color/icon
    and to filter.

    `detail` (optional keyword args) is a structured, JSON-safe dict the
    Alerts screen renders as a detailed card: entry/exit/SL/TP, size, R:R,
    duration, trigger reason, catch-up info etc. `text` stays the one-line
    human summary so older app versions still show something sensible.
    Capped at MAX_ALERTS most-recent entries."""
    _live = detail.pop("live", None)
    if _live is None:
        _live = _live_mode_now()
    with _lock:
        alerts = _status.get("alerts", [])
        alerts.insert(0, {
            "type": alert_type,
            "text": text,
            "time": time.strftime("%H:%M:%S"),
            "ts": time.time(),
            "d": detail or None,
            "live": bool(_live),
        })
        _status["alerts"] = alerts[:MAX_ALERTS]
        _status["alerts_rev"] = _status.get("alerts_rev", 0) + 1
    _mark_alerts_dirty()


def upsert_trade_alert(trade_id, alert_type, text, **detail):
    """Same purpose as add_alert(), but for the OPEN/CLOSE lifecycle of one
    trade: instead of one card at open and a SEPARATE card at close (which
    used to clutter the Alerts feed with two entries per trade), this finds
    the existing card for `trade_id` (matched on d["trade_id"], always set
    from the positional trade_id arg below) and updates it IN PLACE - merging in the new
    detail (close adds exit/pnl/reason on top of the open card's
    entry/SL/TP/opened-time, never replacing them) and moving it to the top
    of the feed as the most recently active card. If no card exists yet for
    this trade_id (the normal open case), inserts a new one exactly like
    add_alert() does. `trade_id=None` always inserts a new entry (used by
    non-lifecycle alerts that don't belong to one specific trade)."""
    # Single source of truth for d["trade_id"]: always the positional
    # trade_id, not whatever (if anything) the caller's **detail happened to
    # carry. paper_trader._trade_meta() also returns a "trade_id" key (it's
    # the same value) - callers now strip that before unpacking as **detail,
    # since Python raises "got multiple values for argument 'trade_id'" if a
    # kwarg collides with an already-bound positional argument. Setting it
    # here instead keeps the open/close card-matching in idx lookup below
    # working regardless of what the caller's detail dict contains.
    detail = dict(detail or {})
    _live = detail.pop("live", None)
    if _live is None:
        _live = _live_mode_now()
    if trade_id is not None:
        detail["trade_id"] = trade_id
    with _lock:
        alerts = _status.get("alerts", [])
        idx = None
        if trade_id is not None:
            idx = next(
                (i for i, a in enumerate(alerts) if (a.get("d") or {}).get("trade_id") == trade_id),
                None,
            )
        now_time = time.strftime("%H:%M:%S")
        now_ts = time.time()
        if idx is not None:
            existing = alerts.pop(idx)
            merged_detail = dict(existing.get("d") or {})
            merged_detail.update(detail or {})
            entry = {"type": alert_type, "text": text, "time": now_time, "ts": now_ts, "d": merged_detail,
                     "live": bool(existing["live"]) if "live" in existing else bool(_live)}
        else:
            entry = {"type": alert_type, "text": text, "time": now_time, "ts": now_ts, "d": detail or None,
                     "live": bool(_live)}
        alerts.insert(0, entry)
        _status["alerts"] = alerts[:MAX_ALERTS]
        _status["alerts_rev"] = _status.get("alerts_rev", 0) + 1
    _mark_alerts_dirty()


def _live_mode_now():
    try:
        from . import settings_store
        return bool(settings_store.get("live_trading_enabled", False))
    except Exception:
        return False


def touch_alerts():
    """Bump the alerts revision so the feed is sent to the app again (used when LIVE/PAPER is switched)."""
    with _lock:
        _status["alerts_rev"] = _status.get("alerts_rev", 0) + 1


def add_alert_paper(alert_type, text, **detail):
    """add_alert() for events of a PAPER position (tagged paper, so LIVE mode never shows it)."""
    detail["live"] = False
    return add_alert(alert_type, text, **detail)


def upsert_trade_alert_paper(trade_id, alert_type, text, **detail):
    detail["live"] = False
    return upsert_trade_alert(trade_id, alert_type, text, **detail)


def alert_is_live(a):
    """True when an Alerts entry belongs to the REAL account. New entries carry a 'live' flag; older
    saved ones are recognised by their text / detail."""
    try:
        if "live" in a:
            return bool(a["live"])
        d = a.get("d") or {}
        return (str(a.get("text") or "").upper().startswith("LIVE")
                or d.get("source") == "live" or d.get("tp_mode") == "exchange")
    except Exception:
        return False


def add_api_error(code, msg, symbol=None, endpoint=None):
    """Rolling log of raw exchange API error codes - called from the
    signed-request layer in binance_trader.py and protection_manager.py
    (both catch a non-200 response there before it becomes a raised
    exception), so EVERY code path that can hit Binance (open, close,
    SL/TP placement, the continuous guard loop) feeds this one list. The
    Flutter DiagnosticsCard shows a dismissible inline banner whenever a
    known-actionable code (-4120 "would immediately trigger", -2019
    "margin insufficient", -2022 "ReduceOnly Order is rejected", etc.) has
    landed here recently - this function does no filtering itself, it
    just records the truth; the UI decides which codes are worth
    surfacing. Capped at MAX_API_ERRORS most-recent entries, newest
    first."""
    with _lock:
        errs = _status.get("recent_api_errors", [])
        errs.insert(0, {
            "code": code,
            "msg": msg,
            "symbol": symbol,
            "endpoint": endpoint,
            "ts": time.time(),
            "time": time.strftime("%H:%M:%S"),
        })
        _status["recent_api_errors"] = errs[:MAX_API_ERRORS]


def set_unprotected_positions(items):
    """Overwrites the live "currently unprotected" list - called once per
    guard_tick() pass (protection_manager.py) with the FULL current set,
    never appended to, so a symbol that got fixed since the last tick
    disappears from here immediately instead of lingering."""
    with _lock:
        _status["unprotected_positions"] = list(items or [])


def get(skip=()):
    """Deep copy so callers (e.g. the WebSocket json.dumps running on the
    event loop) never iterate a list another thread is mutating.

    `skip`: top-level keys to leave out of the copy. The 250ms broadcaster
    passes ("alerts",) while alerts haven't changed - the alert list (up to
    250 detail dicts) was being deep-copied 4x/sec only to be thrown away.
    Copying still happens under the lock, exactly as before."""
    with _lock:
        if skip:
            snap = copy.deepcopy({k: v for k, v in _status.items() if k not in skip})
        else:
            snap = copy.deepcopy(_status)
    snap["server_ts"] = time.time()
    return snap


def alerts_rev():
    """Cheap read of the alerts revision counter. Lock-free on purpose: this runs on the event loop every 250 ms, and
    reading one int out of a dict is atomic in CPython, so it must never wait behind a thread that holds _lock."""
    return _status.get("alerts_rev")


def get_watchlist():
    """Just the watchlist as a plain list copy. The price-stream watchdog used to call get() (deepcopy of the WHOLE
    status incl. up to 250 alerts, under the lock) every few seconds."""
    with _lock:
        return list(_status.get("watchlist") or [])
