"""Live-price feed for Market Watch + paper-trading TP/SL checks.

PART 3 - ZERO-LAG EXECUTION ENGINE (FAST LIVE PRICE PIPE)
-----------------------------------------------------------
Binance-only (see exchange.py - KuCoin fully excluded). Previous rounds
used Binance's combined ALL-symbol ticker array stream (!ticker@arr) -
every active USDT-M perpetual's LAST TRADE price, pushed whether anyone
cares about that symbol or not. This round replaces that with a single
connection carrying only the streams actually needed right now:

    {symbol}@markPrice@1s   - the mark price (same price Binance's own
                                STOP_MARKET/TAKE_PROFIT_MARKET orders
                                trigger off, since protection_manager.py
                                places every conditional order with
                                workingType=MARK_PRICE - so this feed now
                                shows EXACTLY the number that decides
                                whether a stop/target fires, not the last
                                traded price, which can differ from mark
                                price during a thin-liquidity wick)
    {symbol}@kline_5m       - live-updating 5m candle (for the chart)

for exactly two sets of symbols, kept in sync every SYMBOL_REFRESH_SEC:
  - every symbol currently in the app's watchlist (read from
    status.get()["watchlist"] - app.py's refresh_watchlist() already
    publishes this; nothing here needs to import app.py or duplicate its
    top-gainers/losers logic)
  - every symbol with a currently open Binance position (binance_trader.
    get_open_positions(), lazy-imported to avoid a needless dependency
    when live trading is off)

Subscriptions are added/dropped on the fly with Binance's own SUBSCRIBE/
UNSUBSCRIBE control messages sent over the ALREADY-OPEN socket (no
reconnect needed just because the watchlist changed) - this is what
keeps the feed "zero-lag, no bottleneck": one connection, only the
symbols that matter, updated within one SYMBOL_REFRESH_SEC cycle of a
watchlist change or a new position opening.

Public API (start/get_live/get_live_kline/get_best_live_price/
get_ws_state/stale_watchdog_tick) - app.py and paper_trader.py are
untouched by this; get_live_kline() is new/additive, everything else
keeps its exact previous signature and return shape.

SCOPE - READ THIS BEFORE TOUCHING ANYTHING ELSE IN THIS FILE:
This module ONLY feeds a live price/candle cache that Market Watch
(frontend), the chart, and paper_trader's TP/SL monitor loop can read
from for a fresher value than whatever REST snapshot they already have.
It does NOT touch, replace, or feed:
  - fetch_initial_history() / _fetch_kline_for() (candle fetch)
  - history_cache / process_candle() / strategy.generate_signal()
  - refresh_watchlist() / get_current_movers() (still decide WHICH symbols
    are top gainers/losers - unchanged, every WATCHLIST_REFRESH_INTERVAL)
This module can be deleted or disabled entirely and nothing about signal
generation, paper trading, or Telegram changes - callers just fall back to
their own REST snapshot/on-demand price, same as before this file existed.

Thread-safety: two dicts (price cache, kline cache) behind one lock. Reads
never block on the network - the feed thread writes to the caches,
everyone else only reads a snapshot. Subscription sends are guarded by
their own lock since they can be triggered both from the periodic
refresh check and (indirectly) from the connection's own on_open.
"""
import json
import os
import random
import threading
import time

from . import status

STALE_AFTER_SECONDS = 8    # cache older than this -> get_live() returns None (caller should fall back)
DISCONNECTED_AFTER_SECONDS = 15  # no successful update AT ALL for this long -> overall state STALE
MAX_BACKOFF = 30
SYMBOL_REFRESH_SEC = 8     # how often the desired (watchlist + open-position) symbol set is
                             # re-computed and SUBSCRIBE/UNSUBSCRIBE deltas sent - kept close to
                             # app.py's own WATCHLIST_REFRESH_INTERVAL (10s) so a watchlist change
                             # is reflected in the live feed within roughly one refresh cycle.
BACKUP_REST_SECONDS = 30   # infrequent safety-net REST snapshot (see _backup_reconcile_once) -
                             # NOT the primary price path any more (that's the WS push below);
                             # this only fills change_pct and covers a symbol the WS hasn't
                             # pushed for yet, without ever overwriting a fresher WS mark price.

_lock = threading.Lock()
_live_cache = {}          # symbol -> {"price": float, "change_pct": float, "updated_at": float}
_kline_cache = {}         # symbol -> {"open","high","low","close","volume","open_time","close_time","interval","is_closed","updated_at"}
_last_poll_success_time = 0.0
_ws_state = "DISCONNECTED"   # CONNECTING, LIVE, RECONNECTING, STALE, DISCONNECTED
_reconnect_count = 0
_last_error = None
_started = False

# DIAGNOSTICS CARD TELEMETRY - throttled push to status.py so the
# DiagnosticsCard's Feed-Age badge and Latency Split have real numbers.
# Binance's markPriceUpdate/kline frames both carry "E" (exchange event
# time, ms since epoch) - the gap between that and this process receiving
# the frame is the real network+queue latency, not a guess. Pushed at
# most once per _TELEMETRY_PUSH_MIN_SEC even though messages arrive far
# more often (one per subscribed symbol per second), so this never
# becomes the bottleneck the module docstring promises this feed isn't.
_TELEMETRY_PUSH_MIN_SEC = 0.5
_last_telemetry_push = 0.0


def start():
    """Start the feed supervisor thread if it isn't already running. Safe to
    call more than once - only the first call actually starts anything."""
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_supervisor_loop, daemon=True)
    t.start()
    threading.Thread(target=_rest_heartbeat_loop, daemon=True).start()


def get_live(symbol):
    """Returns {"price", "change_pct", "updated_at"} for symbol if the cache
    is fresh (<STALE_AFTER_SECONDS old), else None - callers should fall
    back to their own REST-snapshot value on None, never guess or hold a
    stale number silently."""
    with _lock:
        entry = _live_cache.get(symbol)
    if not entry:
        return None
    if time.time() - entry["updated_at"] > STALE_AFTER_SECONDS:
        return None
    return entry


def get_live_kline(symbol):
    """Returns the latest live-updating 5m candle for `symbol` ({"open",
    "high","low","close","volume","open_time","close_time","interval",
    "is_closed","updated_at"}) if the cache is fresh (<STALE_AFTER_SECONDS*3
    old - candles push far less often than mark price, ~once per closed
    bar plus intra-bar updates, so a looser staleness window is used here
    than get_live()'s), else None. New in PART 3 - additive, no existing
    caller depends on this."""
    with _lock:
        entry = _kline_cache.get(symbol)
    if not entry:
        return None
    if time.time() - entry["updated_at"] > STALE_AFTER_SECONDS * 3:
        return None
    return entry


def get_best_live_price(symbol):
    """Cache-first, single-symbol-REST-fallback live price - the source
    every paper-trading price read (TP/SL checks, manual close, Close All
    Profit/Loss, position LTP display) should go through instead of a bare
    request. Never returns a silently-stale number: if the push/poll cache
    has a fresh entry, uses it; otherwise makes one REST call for just this
    symbol (via exchange.py, so it respects whichever exchange is active);
    if both fail, returns (None, "OFFLINE", error) so the caller can skip
    that position this cycle rather than act on a guess.

    Returns (price, source, error) where source is one of
    'LIVE_WS' / 'REST_FALLBACK' / 'OFFLINE' and error is only set on
    OFFLINE."""
    live = get_live(symbol)
    if live:
        return live["price"], "LIVE_WS", None
    try:
        from . import exchange
        return exchange.get_price(symbol), "REST_FALLBACK", None
    except Exception as e:
        try:
            from . import http_client
            err = http_client.error_label(e)
        except Exception:
            err = str(e)
        return None, "OFFLINE", err


def get_ws_state():
    """Snapshot of feed health for a UI status badge (LIVE/STALE/etc)."""
    with _lock:
        age = (time.time() - _last_poll_success_time) if _last_poll_success_time else None
        return {
            "state": _ws_state,
            "connected": _ws_state == "LIVE",
            "last_update_age": age,
            "reconnect_count": _reconnect_count,
            "symbols_cached": len(_live_cache),
            "error": _last_error,
        }


_down_since = None      # time.time() when the feed first stopped being LIVE (None while healthy)
_down_alerted = False   # one "still down" alert per outage


def _set_state(new_state, error=None):
    global _ws_state, _last_error, _down_since, _down_alerted
    with _lock:
        if new_state != _ws_state:
            print(f"[market_ws] feed state {_ws_state} -> {new_state}" + (f" ({error})" if error else ""))
        _ws_state = new_state
        if error is not None:
            _last_error = error
    status.update(ws_connected=(new_state == "LIVE"), market_data_state=new_state)
    # Feed health -> Alerts screen. Short blips (<10s) stay silent; a real
    # outage produces one "down" alert (after 30s) and one "recovered" alert,
    # so the user can see WHEN data was missing - paper_trader then runs its
    # catch-up check on open trades for exactly that window.
    now = time.time()
    try:
        if new_state == "LIVE":
            if _down_since is not None and now - _down_since >= 10:
                dur = int(now - _down_since)
                status.add_alert("sync", f"Price feed recovered after {dur}s - open trades will be caught up",
                                 kind="feed_up", down_s=dur, error=_last_error)
            _down_since = None
            _down_alerted = False
        elif new_state in ("RECONNECTING", "STALE", "DISCONNECTED"):
            if _down_since is None:
                _down_since = now
            elif not _down_alerted and now - _down_since >= 30:
                _down_alerted = True
                status.add_alert("error", f"Price feed down for {int(now - _down_since)}s: {_last_error or new_state}",
                                 kind="feed_down", down_s=int(now - _down_since), error=_last_error)
    except Exception:
        pass


# ---------------------------------------------------------- supervisor -----
# Starts (and, if it ever dies, restarts) the single Binance WS feed thread.
# No exchange switching anymore - Binance is the only supported feed (see
# exchange.py - KuCoin fully excluded).

_stop_event = None
_feed_thread = None


def _supervisor_loop():
    global _stop_event, _feed_thread
    while True:
        try:
            if _feed_thread is None or not _feed_thread.is_alive():
                if _stop_event is not None:
                    _stop_event.set()
                with _lock:
                    _live_cache.clear()
                    _kline_cache.clear()
                _stop_event = threading.Event()
                _feed_thread = threading.Thread(target=_binance_ws_loop, args=(_stop_event,), daemon=True)
                _feed_thread.start()
        except Exception as e:
            print(f"[market_ws] supervisor error: {e}")
        time.sleep(2)


# ------------------------------------------------------ symbol selection ---
# What this feed should be subscribed to right now: the watchlist app.py
# already publishes to status.py, unioned with whatever symbols currently
# have an open Binance position. Neither lookup ever raises - a failure in
# either just means "nothing extra from that source this round", never a
# crash of the feed thread.

def _watchlist_symbols():
    try:
        wl = status.get_watchlist()
        out = {str(s).upper() for s in wl if s}
    except Exception:
        out = set()
    return out


_held_cache = set()


def held_symbols():
    """Last known set of symbols with an open position (paper + live). Pure
    memory read - app.py uses it to keep scanning a held coin for its EXIT
    signal even after it drops out of the top-10 gainers/losers."""
    return set(_held_cache)


def _open_position_symbols():
    global _held_cache
    paper = set()
    try:
        from . import paper_trader
        paper = {str(x).upper() for x in paper_trader.open_symbols()}
    except Exception:
        paper = set()
    live = _open_live_symbols()
    _held_cache = paper | live
    return _held_cache


def _open_live_symbols():
    # STRICT PAPER-MODE GATE: binance_trader.get_open_positions() makes a
    # SIGNED Binance REST call - calling it while live trading is off (or
    # while API keys simply aren't configured yet, which is the common
    # PAPER-mode case) used to fire every SYMBOL_REFRESH_SEC (~8s) and log
    # a "LIVE POSITIONS FETCH FAILED: No Binance API key/secret set" alert
    # on a loop, even though nothing live was ever attempted. In PAPER
    # mode there are no real Binance positions to union into the feed
    # anyway, so this is a clean no-op - not a degraded fallback.
    try:
        from . import settings_store
        if not settings_store.get("live_trading_enabled", False):
            return set()
        from . import exchange
        if exchange.active() != "binance":
            return set()
        from . import live_snapshot   # shared background snapshot: no extra signed Binance call from here
        return {str(p.get("symbol")).upper() for p in live_snapshot.get_positions() if p.get("symbol")}
    except Exception:
        return set()


def _desired_symbols():
    return _watchlist_symbols() | _open_position_symbols()


# ---- WS-PRIMARY CLOSED-CANDLE FEED ----------------------------------------
# The kline stream now follows the bot's ACTIVE timeframe (it used to be
# hard-wired to 5m). A kline event with x=true is Binance's own "this candle
# just closed" message: it is handed to app.py through the registered
# callback so the strategy runs within ~a fraction of a second of the close,
# instead of waiting for a REST poll. The REST poller remains as the fallback
# (app.py waits WS_GRACE_SEC, then polls whatever the WS did not deliver).
_candle_cb = None
_last_kline_event_ts = 0.0
_ws_bad_symbols = set()   # symbols Binance rejected on SUBSCRIBE -> REST-only, never retried


def set_candle_callback(fn):
    global _candle_cb
    _candle_cb = fn


def candle_feed_healthy():
    """True while the WS is LIVE and kline events are actually flowing."""
    return _ws_state == "LIVE" and (time.time() - _last_kline_event_ts) < 15.0


# ---- WS-primary candle coverage (used by app.py to skip routine REST sweeps)
_fresh_stamp = {}          # symbol -> last time we stamped timeframe_manager freshness
_iv_cache = [0.0, "5m"]    # [checked_at, interval] - avoids re-resolving ~80x/sec


def _cur_interval_cached():
    now = time.time()
    if now - _iv_cache[0] > 5.0:
        _iv_cache[1] = _cur_interval()
        _iv_cache[0] = now
    return _iv_cache[1]


def _stamp_fresh(sym, interval, ts):
    """A live kline tick for the CURRENT timeframe proves this symbol's candle
    feed is alive, so it counts as 'fresh' for the new-entry stale-data gate
    (timeframe_manager.is_fresh). Before, only the REST sweep stamped this;
    stamping here lets the sweep be skipped while the WS is healthy.
    Throttled to once/sec/symbol - costs ~nothing."""
    if ts - _fresh_stamp.get(sym, 0.0) < 1.0 or interval != _cur_interval_cached():
        return
    _fresh_stamp[sym] = ts
    try:
        from . import timeframe_manager
        timeframe_manager.mark_fetched(sym)
    except Exception:
        pass


def ws_covers(symbol):
    """True if the WS is delivering live klines for `symbol` on the current
    timeframe right now. False -> REST must keep covering it (rejected
    subscription, brand-new watchlist symbol, timeframe just changed...)."""
    if symbol in _ws_bad_symbols:
        return False
    with _lock:
        e = _kline_cache.get(symbol)
    return bool(e) and e.get("interval") == _cur_interval_cached() \
        and (time.time() - e["updated_at"]) < 6.0


def feed_info():
    """Small dict for the System Load card (telemetry.py)."""
    now = time.time()
    return {
        "state": _ws_state,
        "reconnects": _reconnect_count,
        "kline_age_s": round(now - _last_kline_event_ts, 2) if _last_kline_event_ts else None,
        "price_age_s": round(now - _last_poll_success_time, 2) if _last_poll_success_time else None,
        "symbols": len(_live_cache),
        "rest_only": len(_ws_bad_symbols),
    }


def _cur_interval():
    try:
        from . import exchange, binance_client
        return binance_client._interval_str(exchange.active_strategy_timeframe_min())
    except Exception:
        return "5m"


def _streams_for(symbols, interval=None, kline_only=False):
    interval = interval or _cur_interval()
    streams = []
    for s in symbols:
        ls = s.lower()
        if not kline_only:
            streams.append(f"{ls}@markPrice@1s")
        streams.append(f"{ls}@kline_{interval}")
    return streams


# -------------------------------------------------------------- Binance ----
# ROUTING FIX (Binance USDⓈ-M WebSocket upgrade, notice 2026-03-06): the old
# unrouted URL wss://fstream.binance.com/ws was decommissioned on 2026-04-23.
# The socket still OPENS there, but only /public data (depth/bookTicker) is
# pushed - markPrice and kline live on /market, so this bot got a connected
# socket that never delivered a single price ("Feed: REST" forever). We now
# connect to wss://fstream.binance.com/market/ws (with a /market/stream
# fallback, whose frames are wrapped and are unwrapped below).
# Raw single-stream endpoint (wss://fstream.binance.com/market/ws) with dynamic
# SUBSCRIBE/UNSUBSCRIBE control frames - unlike the /stream?streams=...
# combined endpoint, this delivers every event UNWRAPPED (exactly the
# stream's own payload, keyed by its own "e" event-type field) regardless
# of how many streams are currently subscribed, and lets the subscription
# list change at runtime without dropping the connection.

_WS_URLS = [
    u for u in (
        os.environ.get("OWL_BINANCE_WS_URL", "").strip(),
        "wss://fstream.binance.com/market/ws",
        "wss://fstream.binance.com/market/stream",
    ) if u
]
_NO_DATA_RECONNECT_SEC = 20   # socket open + subscribed but zero events this long -> try next URL


def _binance_ws_loop(stop_event):
    global _reconnect_count, _last_poll_success_time
    import websocket  # websocket-client, already in requirements_api.txt
    url_idx = 0

    backoff = 1
    _set_state("CONNECTING")

    send_lock = threading.Lock()
    subscribed = set()  # symbols (not raw stream names) currently subscribed on THIS connection
    sub_interval = [None]   # kline interval currently subscribed on THIS connection
    req_map = {}            # request id -> symbols in that SUBSCRIBE (to attribute an error ack)
    req_seq = [int(time.time()) % 1_000_000]
    ws_app_ref = [None]

    def _send(ws_app, payload):
        try:
            with send_lock:
                ws_app.send(json.dumps(payload))
            return True
        except Exception as e:
            print(f"[market_ws] send failed: {e}")
            return False

    def _next_id():
        req_seq[0] += 1
        return req_seq[0]

    def _subscribe_symbols(ws_app, symbols, interval, kline_only=False):
        """SUBSCRIBE in small batches so ONE bad symbol (e.g. a non-ASCII
        contract name Binance rejects) can no longer kill the whole feed.
        Non-ASCII names go one-per-request so a rejection is attributable."""
        ok_syms = [x for x in symbols if x not in _ws_bad_symbols]
        plain = [x for x in ok_syms if x.isascii()]
        odd = [x for x in ok_syms if not x.isascii()]
        batches = [plain[i:i + 10] for i in range(0, len(plain), 10)] + [[x] for x in odd]
        for b in batches:
            rid = _next_id()
            req_map[rid] = list(b)
            if _send(ws_app, {"method": "SUBSCRIBE", "params": _streams_for(b, interval, kline_only), "id": rid}):
                if not kline_only:
                    subscribed.update(b)

    def _sync_subscriptions(ws_app):
        """Diffs the desired symbol set against what THIS connection is
        currently subscribed to and sends only the delta - never a
        blanket unsubscribe-everything-then-resubscribe, so an unchanged
        symbol's stream is never interrupted just because another symbol
        was added/removed elsewhere in the watchlist. Also follows the
        active timeframe: if it changed, kline streams are swapped."""
        cur = _cur_interval()
        desired = _desired_symbols()
        # timeframe changed -> swap kline streams for everything already subscribed
        if sub_interval[0] is not None and sub_interval[0] != cur and subscribed:
            old = sub_interval[0]
            keep = [x for x in subscribed if x in desired]
            _send(ws_app, {"method": "UNSUBSCRIBE", "params": _streams_for(list(subscribed), old, True), "id": _next_id()})
            if keep:
                _subscribe_symbols(ws_app, keep, cur, kline_only=True)
            print(f"[market_ws] timeframe changed {old} -> {cur}: kline streams swapped")
        sub_interval[0] = cur
        to_add = desired - subscribed - _ws_bad_symbols
        to_remove = subscribed - desired
        if to_add:
            _subscribe_symbols(ws_app, sorted(to_add), cur)
        if to_remove:
            if _send(ws_app, {"method": "UNSUBSCRIBE", "params": _streams_for(sorted(to_remove), cur), "id": _next_id()}):
                subscribed.difference_update(to_remove)
                with _lock:
                    for sym in to_remove:
                        _live_cache.pop(sym, None)
                        _kline_cache.pop(sym, None)

    def _handle_ack(data):
        """Binance answers every SUBSCRIBE with {"result":null,"id":N} on
        success or {"error":{...},"id":N} on failure. Previously these were
        silently ignored - a rejected subscription looked exactly like
        'connected but no data' (Feed: CONNECTING forever)."""
        rid = data.get("id")
        syms = req_map.pop(rid, None)
        if not data.get("error"):
            return
        print(f"[market_ws] SUBSCRIBE rejected (id={rid}, symbols={syms}): {data.get('error')}")
        if not syms:
            return
        if len(syms) == 1:
            _ws_bad_symbols.add(syms[0])
            subscribed.discard(syms[0])
            print(f"[market_ws] {syms[0]} rejected by Binance WS -> REST fallback only")
            return
        # A batch failed: find the culprit by retrying each symbol on its own.
        w = ws_app_ref[0]
        if w is None:
            return
        for x in syms:
            subscribed.discard(x)
            r2 = _next_id()
            req_map[r2] = [x]
            if _send(w, {"method": "SUBSCRIBE", "params": _streams_for([x], sub_interval[0]), "id": r2}):
                subscribed.add(x)

    def _apply_mark_price(sym, data, ts):
        try:
            price = float(data.get("p"))
        except (TypeError, ValueError):
            return False
        with _lock:
            prev = _live_cache.get(sym, {})
            _kl = _kline_cache.get(sym)
            if _kl and ts - _kl["updated_at"] < 2.0:
                # A fresh last-traded price (kline close, ~250ms) already sits
                # in the cache - don't overwrite it with the slower, slightly
                # different mark price (would flicker between the two).
                # Just refresh the timestamp so the feed still counts as LIVE.
                _live_cache[sym] = {"price": prev.get("price", price),
                                    "change_pct": prev.get("change_pct", 0.0), "updated_at": ts}
            else:
                _live_cache[sym] = {"price": price, "change_pct": prev.get("change_pct", 0.0), "updated_at": ts}
        return True

    def _apply_kline(sym, data, ts):
        k = data.get("k") or {}
        try:
            entry = {
                "open": float(k.get("o")), "high": float(k.get("h")),
                "low": float(k.get("l")), "close": float(k.get("c")),
                "volume": float(k.get("v") or 0.0),
                "open_time": k.get("t"), "close_time": k.get("T"),
                "interval": k.get("i"), "is_closed": bool(k.get("x")),
                "updated_at": ts,
            }
        except (TypeError, ValueError):
            return False
        with _lock:
            _kline_cache[sym] = entry
            # LAST-TRADED PRICE (same number Binance's own chart/watchlist
            # shows). markPrice only ticks once per second; the kline stream
            # pushes every ~250ms and its close ("c") IS the last traded
            # price, so use it as the live price whenever it is available.
            _prev_live = _live_cache.get(sym, {})
            _live_cache[sym] = {
                "price": entry["close"],
                "change_pct": _prev_live.get("change_pct", 0.0),
                "updated_at": ts,
            }
        _stamp_fresh(sym, entry["interval"], ts)
        return True

    def _backup_reconcile_once():
        """Infrequent safety-net REST snapshot - fills change_pct (which
        the markPrice stream doesn't carry) and gives any symbol the WS
        hasn't pushed a price for yet a value to show, WITHOUT ever
        overwriting an already-fresher WS-sourced price. Not the primary
        path any more - see module docstring."""
        try:
            from . import binance_client
            price_map = binance_client.get_active_usdt_symbols()
            now = time.time()
            with _lock:
                for sym, p in price_map.items():
                    if sym not in _live_cache:
                        continue  # only for symbols we actually track (watchlist/positions)
                    entry = _live_cache[sym]
                    if now - entry["updated_at"] > STALE_AFTER_SECONDS:
                        _live_cache[sym] = {"price": p, "change_pct": entry.get("change_pct", 0.0), "updated_at": now}
            return True
        except Exception:
            return False

    while not stop_event.is_set():
        ws_app = None
        subscribed = set()
        sub_interval[0] = None
        req_map.clear()
        ws_app_ref[0] = None
        last_symbol_refresh = 0.0
        last_backup = 0.0
        watchdog_stop = threading.Event()
        got_data = [False]
        opened_at = [0.0]
        try:
            url = _WS_URLS[url_idx % len(_WS_URLS)]

            def on_message(_ws, message):
                nonlocal last_symbol_refresh, last_backup
                global _last_poll_success_time, _reconnect_count, _last_telemetry_push, _last_kline_event_ts
                try:
                    data = json.loads(message)
                except Exception:
                    return
                # /market/stream wraps every event as {"stream":..,"data":{..}}
                if isinstance(data, dict) and "stream" in data and isinstance(data.get("data"), dict):
                    data = data["data"]
                if isinstance(data, dict) and not data.get("e") and "id" in data:
                    _handle_ack(data)
                    return
                if isinstance(data, dict) and data.get("e"):
                    sym = data.get("s")
                    ts = time.time()
                    updated = False
                    if sym:
                        if data["e"] == "markPriceUpdate":
                            updated = _apply_mark_price(sym, data, ts) or updated
                        elif data["e"] == "kline":
                            updated = _apply_kline(sym, data, ts) or updated
                            _last_kline_event_ts = ts
                            _k = data.get("k") or {}
                            # x=true -> Binance says this candle just CLOSED.
                            if _k.get("x") and _candle_cb is not None and _k.get("i") == sub_interval[0]:
                                try:
                                    _candle_cb(sym, _k)
                                except Exception as _e:
                                    print(f"[market_ws] candle callback error: {_e}")
                    if updated:
                        got_data[0] = True
                        _last_poll_success_time = ts
                        _reconnect_count = 0
                        _set_state("LIVE")
                        # DIAGNOSTICS TELEMETRY - real Exchange-Event-Time ->
                        # Engine-Ingestion latency split, throttled (see
                        # _TELEMETRY_PUSH_MIN_SEC above). "E" is Binance's own
                        # event timestamp in ms; ts is when THIS process
                        # finished parsing+caching it. event_ms missing/junk
                        # -> skip this push entirely rather than publish a
                        # fabricated number.
                        if ts - _last_telemetry_push >= _TELEMETRY_PUSH_MIN_SEC:
                            event_ms = data.get("E")
                            if isinstance(event_ms, (int, float)):
                                # Binance's event time is on ITS clock: add the measured
                                # server-vs-local offset, else a phone clock that runs
                                # behind Binance clamps every sample to a fake 0 ms.
                                try:
                                    from . import binance_client as _bc
                                    _off = float(_bc.server_time_offset_ms() or 0.0)
                                except Exception:
                                    _off = 0.0
                                net_ms = max(0.0, ts * 1000.0 + _off - float(event_ms))
                                engine_ms = max(0.0, (time.time() - ts) * 1000.0)
                                status.update(
                                    feed_last_update_ts=ts,
                                    feed_latency_net_ms=round(net_ms, 1),
                                    feed_latency_engine_ms=round(engine_ms, 2),
                                )
                                _last_telemetry_push = ts
                # Periodic housekeeping, driven off message arrival (this
                # feed is push-based - there's always at least one message
                # per second once >=1 symbol is subscribed) rather than a
                # separate timer thread.
                now = time.time()
                if now - last_symbol_refresh >= SYMBOL_REFRESH_SEC:
                    last_symbol_refresh = now
                    _sync_subscriptions(_ws)
                if now - last_backup >= BACKUP_REST_SECONDS:
                    last_backup = now
                    _backup_reconcile_once()

            def on_error(_ws, error):
                print(f"[market_ws] Binance WS error: {error}")

            def on_close(_ws, *_args):
                pass

            # RESUBSCRIBE WATCHDOG - fixes a real "Feed: CONNECTING forever"
            # deadlock: _sync_subscriptions() was previously only re-run
            # from inside on_message's housekeeping block, which never
            # fires until at least one stream is already subscribed and
            # pushing data. If _desired_symbols() was empty at the exact
            # moment on_open fired (watchlist not published to status.py
            # yet, or a brief startup race), on_open's one subscribe call
            # sent nothing, no message ever arrived, and the connection
            # sat open but silent forever - state stuck at CONNECTING with
            # Socket: LIVE. This thread runs independently of message
            # arrival, so the desired symbol set is (re)checked and
            # subscribed every SYMBOL_REFRESH_SEC no matter what.
            def _resubscribe_watchdog(ws_app_):
                while not watchdog_stop.wait(SYMBOL_REFRESH_SEC):
                    try:
                        _sync_subscriptions(ws_app_)
                    except Exception:
                        pass
                    # Connected + subscribed but Binance never pushed one event:
                    # wrong/blocked endpoint. Drop the socket so the outer loop
                    # reconnects (rotating to the next candidate URL).
                    if (not got_data[0] and subscribed and opened_at[0]
                            and time.time() - opened_at[0] > _NO_DATA_RECONNECT_SEC):
                        print(f"[market_ws] no data {_NO_DATA_RECONNECT_SEC}s after subscribe on {url} - reconnecting on next endpoint")
                        try:
                            ws_app_.close()
                        except Exception:
                            pass
                        return

            def on_open(ws_app_):
                print(f"[market_ws] Binance WS connected {url} (dynamic markPrice@1s + kline_{_cur_interval()})")
                opened_at[0] = time.time()
                ws_app_ref[0] = ws_app_
                _sync_subscriptions(ws_app_)
                threading.Thread(target=_resubscribe_watchdog, args=(ws_app_,), daemon=True).start()

            ws_app = websocket.WebSocketApp(
                url, on_message=on_message, on_error=on_error, on_close=on_close, on_open=on_open,
            )
            # ping_interval/ping_timeout: instant heartbeat so a dead socket is
            # detected and reconnected quickly instead of silently going stale.
            # Binance also requires a PONG frame reply to ITS OWN server pings
            # within 10 minutes on Futures streams - websocket-client answers
            # those automatically at the protocol level, no app-code needed.
            ws_app.run_forever(ping_interval=15, ping_timeout=10)
        except Exception as e:
            print(f"[market_ws] Binance WS exception: {e}")
        finally:
            watchdog_stop.set()
            try:
                if ws_app is not None:
                    ws_app.close()
            except Exception:
                pass

        if stop_event.is_set():
            break
        if not got_data[0]:
            url_idx += 1   # this endpoint never delivered - try the next one
        _reconnect_count += 1
        status.update(ws_reconnect_count=_reconnect_count)
        _set_state("RECONNECTING", error="Binance WebSocket disconnected - reconnecting")
        if got_data[0]:
            backoff = 1          # this connection worked, so the next drop is retried fast (before: the wait stayed at 30 s for ever)
        wait_s = backoff * (0.8 + 0.4 * random.random())          # small random spread so retries never come in a burst
        print(f"[market_ws] disconnected (Errno 103 / reset). One reconnect in {wait_s:.1f}s")
        stop_event.wait(wait_s)
        backoff = min(backoff * 2, MAX_BACKOFF)

    _set_state("DISCONNECTED")


def stale_watchdog_tick():
    """Call periodically to flip overall state to STALE if nothing has
    successfully updated in a while. Cheap - just a time comparison."""
    if _last_poll_success_time and (time.time() - _last_poll_success_time) > DISCONNECTED_AFTER_SECONDS:
        if _ws_state == "LIVE":
            _set_state("STALE")


# ------------------------------------------------- REST feed heartbeat ------
# When the Binance WS is not LIVE (blocked network, still connecting, etc.)
# the Diagnostics card used to show "Feed: CONNECTING / No data yet" forever
# even though prices were flowing via REST fallback. This thread measures one
# real REST price round-trip every few seconds while the WS is not LIVE and
# publishes it as feed age + net latency, with state "REST" - honest label,
# it never claims LIVE and never touches the WS state machine.
REST_HEARTBEAT_SEC = 5


def _rest_heartbeat_loop():
    while True:
        time.sleep(REST_HEARTBEAT_SEC)
        try:
            if _ws_state == "LIVE":
                continue
            wl = sorted(_watchlist_symbols())
            if not wl:
                continue
            from . import exchange
            t0 = time.time()
            exchange.get_price(wl[0])
            t1 = time.time()
            if _ws_state == "LIVE":
                continue
            status.update(
                feed_last_update_ts=t1,
                feed_latency_net_ms=round((t1 - t0) * 1000.0, 1),
                feed_latency_engine_ms=None,
                market_data_state="REST",
            )
        except Exception:
            pass
