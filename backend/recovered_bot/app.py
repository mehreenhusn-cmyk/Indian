import os
import time
import threading
import queue
import collections
import concurrent.futures
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from .telegram import TelegramNotifier
from .strategy import ABCDStrategy
from .paper_trader import open_paper_trade, paper_trade_monitor_loop
from . import paper_trader
from . import binance_trader
from . import status
from . import settings_store
from . import trade_store
from . import db
from .http_client import get_session
from . import exchange
from . import market_ws
from . import dns_fallback
from . import protection_manager
from . import execution_router
from . import reconciliation
from . import timeframe_manager
from . import telemetry
from . import day_gate

BOT_TOKEN = os.getenv("BOT_TOKEN") or settings_store.get("telegram_bot_token", "")
CHAT_ID = os.getenv("CHAT_ID") or settings_store.get("telegram_chat_id", "")
# Every exchange-specific call below goes through exchange.py, which
# dispatches to binance_client.py (the sole supported exchange - see
# exchange.py's own docstring). Signal engine below (process_candle/
# strategy.generate_signal) is completely exchange-agnostic and untouched.
CANDLE_INTERVAL_MIN = exchange.GRANULARITY_MIN  # exchange's raw default granularity (informational only -
                                                  # the strategy/scanner itself now reads the CONFIGURABLE
                                                  # timeframe fresh every call via exchange.active_strategy_timeframe_min(),
                                                  # see fetch_initial_history()/_fetch_kline_for() below)
WATCHLIST_REFRESH_INTERVAL = 10
last_watchlist_refresh = 0
_diag_last_logged = {}  # symbol -> time.time() of last DIAG alert (throttle, see get_current_movers)
POLL_INTERVAL = 8
# 259 = the scanner's window exactly (260 candles fetched, forming one dropped).
# EMA50 is SMA-seeded from the first candle of this window, so the window length
# must match the scanner's for identical crossover results.
INITIAL_HISTORY_LIMIT = 259
POLL_WORKERS = 10
# NOTE: the old x-mbx-used-weight-1m header adaptive throttle was removed
# here. POLL_INTERVAL is currently fixed; revisit with a proper
# rate-limit/backoff if 429s show up during paper testing.

# 1:1 PINE SCRIPT PARITY GATES (both applied in _open_signal, right before
# an order - paper OR live - is actually dispatched):
#   - MAX_SIGNAL_AGE_SEC: a signal is only actionable if the closed candle
#     it fired on is still fresh. generate_signal() runs the instant the
#     poll loop sees a newly-closed candle, so under normal operation this
#     age is only a couple of seconds - this is a hard safety ceiling, not
#     the expected normal latency. Anything older than this means the poll
#     cycle stalled (network hiccup, thread pool backlog, etc.) and the
#     candle this signal was computed from is no longer "the current bar"
#     - skip rather than fire a stale, Pine-Script-divergent order.
#   - CHASE_GUARD_PCT: if live price has already run away from the
#     signal's own entry_price (the candle's close) by more than this by
#     the time the order is about to be sent, skip instead of chasing -
#     filling meaningfully away from the strategy's intended entry would
#     silently corrupt the SL/TP1-4 ladder (all computed off entry_price).
MAX_SIGNAL_AGE_SEC = 25
CHASE_GUARD_PCT = 1.0   # was 0.15 - too tight for small coins (skipped valid trades at 0.18%)

bot = TelegramNotifier(bot_token=BOT_TOKEN, chat_id=CHAT_ID)
# Strategy params are read from settings_store (Settings screen) at import time.
# settings_store.init() is called by main.py's build() before this module is
# first imported (in safe_start), so the saved values are already loaded here.
# Changing ema_length/lookback_len in Settings takes effect on the NEXT bot
# start (app restart) - not live, since this object is only built once.
strategy = ABCDStrategy(
    lookback_len=int(settings_store.get("lookback_len", 200) or 200),
    ema_length=int(settings_store.get("ema_length", 50) or 50),
)
watchlist = set()
history_cache = {}
lock = threading.Lock()
BOT_START_TIME = int(time.time() * 1000)
_open_lock = threading.Lock()   # serialises claim+open across the WS worker and the REST poll thread
_last_close_ms = {}             # symbol -> exact close time (ms) of the candle a signal was just computed from
_lag_samples = collections.deque(maxlen=50)   # candle-close -> order-dispatch seconds (last 50 trades)
last_processed_candle = {}  # symbol -> close_time (ms) of the last CLOSED candle the strategy already ran on
_active_timeframe_min = None  # last-seen configured strategy timeframe (minutes) - see _check_timeframe_change()


def _check_timeframe_change():
    """If the configured Strategy Timeframe (Settings) changed since the
    last check, wipe every symbol's cached candle history + closed-candle
    dedup marker so the next poll cycle does a full, gap-free re-fetch at
    the NEW timeframe instead of silently mixing old-timeframe candles
    with new-timeframe ones (which would corrupt EMA/SD math and could
    fire bogus signals). Cheap - just a settings_store read - so it's
    called every poll_klines() cycle."""
    global _active_timeframe_min
    current = exchange.active_strategy_timeframe_min()
    if _active_timeframe_min is not None and current != _active_timeframe_min:
        with lock:
            history_cache.clear()
            last_processed_candle.clear()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Timeframe] Changed "
              f"{_active_timeframe_min}m -> {current}m - candle history cleared, re-fetching")
    _active_timeframe_min = current

def fetch_initial_history(symbol: str) -> List[Dict]:
    # STALE-SIGNAL FIX: exchange.get_klines() ALREADY enforces closed-candles-
    # only internally (_enforce_closed_candles in exchange.py drops a still-
    # forming trailing row itself and backfills so the caller still gets
    # exactly `limit` CLOSED candles). This function used to ALSO drop the
    # last row here (data[:-1]) on top of that - a double-drop that silently
    # discarded the true latest closed candle from history at startup, one
    # candle-period stale before a single poll had even run. get_klines()'s
    # own docstring is explicit about this ("caller gets exactly `limit`
    # CLOSED candles, not limit-1") - so no extra trim belongs here.
    try:
        # CONFIGURABLE STRATEGY TIMEFRAME: read fresh every call (never
        # cached) via exchange.active_strategy_timeframe_min(), so a
        # Timeframe change in Settings applies to the very next
        # watchlist/history refresh - no app restart needed.
        tf_min = exchange.active_strategy_timeframe_min()
        data = exchange.get_klines(symbol, limit=INITIAL_HISTORY_LIMIT, tf=tf_min)
        return data or []
    except Exception:
        return []

IST_OFFSET = timedelta(hours=5, minutes=30)
DAY_RESET_HOUR, DAY_RESET_MINUTE = 5, 30  # crypto/Indian-trading-day rollover the user goes by


def _ist_now():
    return datetime.now(timezone.utc) + IST_OFFSET


def _current_trading_day_key(ist_dt=None):
    """Trading-day key that rolls over at 5:30 AM IST (not UTC midnight, and
    not Binance's own rolling 24h window). Returns 'YYYY-MM-DD' for whichever
    trading day is currently in progress - e.g. at 2 AM IST this still
    returns yesterday's date, since the new trading day hasn't started yet."""
    ist_dt = ist_dt or _ist_now()
    reset_today = ist_dt.replace(hour=DAY_RESET_HOUR, minute=DAY_RESET_MINUTE, second=0, microsecond=0)
    trading_date = ist_dt.date() if ist_dt >= reset_today else (ist_dt - timedelta(days=1)).date()
    return trading_date.isoformat()


BTC_SYMBOL = "BTCUSDT"


def _is_btc(symbol):
    return str(symbol).upper() == BTC_SYMBOL


def _btc_fixed():
    """BTCUSDT always on the watchlist with its own paper size (Settings keys btc_fixed / btc_margin / btc_leverage)."""
    try:
        return bool(settings_store.get("btc_fixed", True))
    except Exception:
        return True


_last_ranked = []     # full {symbol, pct24h, price} ranking of the last successful movers fetch


def get_current_movers():
    """Top-10 gainers + top-10 losers on Binance USDT-M Futures, ranked by
    OUR OWN (current vs UTC-day-open) %-change calc - see
    binance_client.py's docstring for why we never trust a raw exchange
    field here (this app got burned twice doing that). This 20-symbol list IS the
    watchlist (see refresh_watchlist() below) - the whole universe the bot
    ever scans or trades, on purpose (the old wider "top-up" scan beyond
    this list has been removed - see PRODUCTION HARDENING note near
    poll_klines())."""
    try:
        ranked = exchange.get_ranked_movers()
        if not ranked:
            return [], [], []
        global _last_ranked
        _last_ranked = ranked
        top = ranked[:10]
        bottom = ranked[-10:][::-1]  # biggest loser first, matches old behavior
        gainers = [d['symbol'] for d in top]
        losers = [d['symbol'] for d in bottom]

        movers = [
            {"symbol": d['symbol'], "change_pct": d['pct24h'], "price": d['price'], "category": "gainer"}
            for d in top
        ] + [
            {"symbol": d['symbol'], "change_pct": d['pct24h'], "price": d['price'], "category": "loser"}
            for d in bottom
        ]
        return gainers, losers, movers
    except Exception as e:
        # Categorize instead of showing the raw exception - a DNS/no-internet
        # blip used to look identical to an exchange-side error in the log.
        try:
            from . import http_client
            label = http_client.error_label(e)
        except Exception:
            label = str(e)
        status.update(last_error=f"Movers fetch: {label}")
        return [], [], []

def _held_symbols():
    """Coins we currently HOLD (paper + live). They must keep being scanned and
    priced for their EXIT signal even after they fall out of the top-10
    gainers/losers - otherwise an opposite EMA cross on them is never seen and
    the trade just sits open (the AI then learns from a wrong exit)."""
    held = set()
    try:
        held |= {str(x).upper() for x in paper_trader.open_symbols()}
    except Exception:
        pass
    try:
        held |= market_ws.held_symbols()
    except Exception:
        pass
    return held


def _scan_symbols():
    """Everything the candle scanner must look at: the top-20 universe PLUS
    held coins. New ENTRIES are still only allowed inside the top-20.
"""
    with lock:
        base = set(watchlist)
    return base | _held_symbols()


def _owner_of(symbol):
    """'b1' if the coin is in the top-10 gainers/losers list, else None."""
    with lock:
        if symbol in watchlist:
            return "b1"
    return None


def refresh_watchlist():
    global watchlist
    gainers, losers, movers = get_current_movers()
    if not movers:
        # The movers fetch failed (timeout / no internet / exchange hiccup).
        # BUG FIXED: this used to fall through with an empty new_watch, which
        # replaced the watchlist with an EMPTY set and dropped every symbol's
        # cached candle history - so one network blip made the bot go blind
        # (no polling at all) until the next successful refresh, then
        # re-download ~250 candles x 20 symbols. Keep the last good
        # watchlist instead; the error is already shown via last_error.
        with lock:
            current = set(watchlist)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [Watchlist] Refresh failed - keeping {len(current)} symbols")
        return current
    new_watch = set(gainers + losers)
    if _btc_fixed():
        new_watch.add(BTC_SYMBOL)     # BTC is always scanned, top-10 or not
    with lock:
        old_watch = watchlist
        dropped = old_watch - new_watch - _held_symbols()
        watchlist = new_watch
        # A symbol that rotates OUT of the top-10 and later rotates back IN
        # keeps a gap in its cached candles; clear on drop to force a full,
        # gap-free re-fetch when it comes back (EMA50/SD-200 need a
        # continuous series).
        for sym in dropped:
            history_cache.pop(sym, None)
            last_processed_candle.pop(sym, None)
        for sym in watchlist:
            if sym not in history_cache or len(history_cache.get(sym, [])) == 0:
                history_cache[sym] = fetch_initial_history(sym)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [Watchlist] Updated: {len(watchlist)} symbols")
    update_kwargs = dict(status="Running", symbols_tracked=len(watchlist), watchlist=sorted(watchlist),
                         market_movers=movers, market_synced_at=time.time())
    # A successful fetch clears the stale "Movers fetch: ..." banner - it used
    # to stay on the Dashboard forever after one blip.
    cur_err = status.get().get("last_error") or ""
    if cur_err.startswith(("Movers fetch", "Poll loop")):
        update_kwargs["last_error"] = None
    status.update(**update_kwargs)
    return watchlist

def _daily_target_hit(bot_id="b1") -> bool:
    """True if today's paper-trading P&L has already reached the configured daily target."""
    try:
        target = float(settings_store.get("daily_target_usdt", 0) or 0)
        if target <= 0:
            return False
        today_pnl = trade_store.get_today_stats(bot_id).get("today_pnl_usdt", 0.0)
        return today_pnl >= target
    except Exception:
        return False

def _daily_loss_limit_hit(bot_id="b1") -> bool:
    """True if today's paper-trading P&L has already dropped to/past the configured daily loss limit."""
    try:
        limit = float(settings_store.get("daily_loss_limit_usdt", 0) or 0)
        if limit <= 0:
            return False
        today_pnl = trade_store.get_today_stats(bot_id).get("today_pnl_usdt", 0.0)
        return today_pnl <= -limit
    except Exception:
        return False

def _today_str():
    return datetime.now(timezone.utc).date().isoformat()

def _bump_signal_count(bot_id="b1", symbol=None):
    # Persisted via trade_store (survives app restarts within the same UTC
    # day) instead of the old plain in-memory counter, which used to reset
    # to 0 on every restart and could hand out a signal_no already used
    # earlier that day by a currently-open or already-closed position.
    # BTC has its own counter: it never changes the alt "signals today" number.
    if symbol is not None and _is_btc(symbol) and str(bot_id or "b1").lower() != "b2":
        return trade_store.bump_signal_count(bot_id, btc=True)
    count = trade_store.bump_signal_count(bot_id)
    status.update(signals_today=count)
    return count

def _skip_meta(signal, symbol, count, why, bot_id="b1"):
    """Detail for a 'signal skipped' alert card - same numbers Telegram shows."""
    # Every skipped signal passes through here. If it points the OPPOSITE way of a
    # position that is still open on this coin, that position is now outdated
    # (its REVERSED close only happens when the new trade actually opens).
    try:
        paper_trader.flag_outdated(symbol, signal.action, why)
    except Exception:
        pass
    return dict(
        bot=bot_id,
        symbol=symbol, side=signal.action, signal_no=count, entry=signal.entry_price,
        sl=signal.stop_loss,
        tp={"1": signal.tp1, "2": signal.tp2, "3": signal.tp3, "4": signal.tp4},
        skip_reason=why,
    )


def _live_trader():
    """Binance is the sole supported exchange's private trading module -
    see exchange.py's docstring (KuCoin fully excluded)."""
    return binance_trader


def _open_live_trade(signal, symbol) -> bool:
    """Strict LIVE dispatch (live_trading_enabled == True): sends a real
    balance-safe-sized order straight to the active exchange's trader
    module. Does NOT touch paper_trader at all - no paper position/record
    is created for this signal. Failures are logged to Alerts (via the
    trader module's own status.add_alert calls) and never raise here, so a
    live-order failure can't crash the scan loop.

    PRODUCTION HARDENING: now returns True only once the exchange has
    actually confirmed a filled order (order_id is not None), and False on
    ANY failure - a rejected order, an unconfirmed fill, or an exception.
    The caller (_open_signal) uses this return value to decide whether the
    signal is logged/shown as opened=True; a failed live order must never
    be recorded as an opened trade just because we attempted one.

    FINAL ROUND: the signal's own stop_loss_price is now actually passed
    through to open_market_order() (binance_trader.py already accepted
    this param - it just wasn't being sent from here, so every live entry
    was silently falling back to the generic emergency-%% stop instead of
    the strategy's real SL). Right after a confirmed fill (order_id not
    None), the signal's EXACT tp1-4/SL are also persisted via
    protection_manager.save_trade_meta() - this is what makes Part 2's
    live_trade_meta.json store non-empty in the first place, so
    execution_router._resolve_live_level_price()'s "exact stored level"
    path and reconciliation.py's "stored SL over emergency %%" path
    actually have real data to read for every future position, not just
    ones opened before this round."""
    try:
        order_id = _live_trader().open_market_order(
            symbol, signal.action.upper(), float(signal.entry_price),
            stop_loss_price=float(signal.stop_loss) if signal.stop_loss is not None else None,
        )
    except Exception as e:
        status.add_alert("manual", f"LIVE ORDER FAILED (exception): {symbol} - {e}")
        return False
    if order_id is None:
        # Trader module already logged the specific reason to Alerts
        # (balance fetch failed, exchange rejected the order, fill never
        # confirmed, etc.) - nothing more to add here, just report failure.
        return False
    if exchange.active() == "binance":
        try:
            protection_manager.save_trade_meta(
                symbol, signal.action.upper(), float(signal.entry_price), signal.stop_loss,
                tp1=signal.tp1, tp2=signal.tp2, tp3=signal.tp3, tp4=signal.tp4,
            )
        except Exception as e:
            status.add_alert("manual", f"LIVE {symbol}: order placed but TP1-4/SL meta could not be saved - {e}")
        # TP4 as a resting TAKE_PROFIT_MARKET on Binance: the full booking happens on the exchange
        # even if the phone/Termux is offline. SL ladder (TP1->entry, TP2->TP1, TP3->TP2) is moved by
        # protection_manager.guard_tick().
        try:
            if signal.tp4 is not None:
                _tp_id = protection_manager.set_target_tp(symbol, signal.action.upper(), float(signal.tp4))
                if _tp_id is None:
                    status.add_alert("manual", f"LIVE {symbol}: TP4 order NOT placed on Binance - check the exchange app")
        except Exception as e:
            status.add_alert("manual", f"LIVE {symbol}: TP4 order could not be placed - {e}")
    # Save entry tags + signal levels so the close can be recorded later
    # (History / Today's P&L / daily loss limit / AI) - see live_recorder.py.
    try:
        from . import live_recorder
        live_recorder.remember_open(signal, symbol)
    except Exception as e:
        print(f"[app] live_recorder.remember_open failed for {symbol}: {e}")
    return True


def _record_signal_lag(symbol):
    """Seconds from candle CLOSE (Binance-synced clock) to the moment this
    signal cleared every gate and is being dispatched. Feeds the app's
    Diagnostics 'Signal lag' row (last / average / worst of the last 50)."""
    try:
        close_ms = _last_close_ms.get(symbol)
        if close_ms is None:
            return
        lag = max(0.0, exchange.now_sec() - close_ms / 1000.0)
        _lag_samples.append(lag)
        status.update(
            signal_lag_last_s=round(lag, 2),
            signal_lag_avg_s=round(sum(_lag_samples) / len(_lag_samples), 2),
            signal_lag_worst_s=round(max(_lag_samples), 2),
            signal_lag_n=len(_lag_samples),
        )
        print(f"[LAG] {symbol}: candle close -> dispatch {lag:.2f}s")
    except Exception:
        pass


def _coin_category(symbol):
    """'gainer' / 'loser' if the coin is in today's top-10 lists, else None."""
    try:
        for m in (status.get().get("market_movers") or []):
            if m.get("symbol") == symbol:
                return m.get("category")
    except Exception:
        pass
    return None


def _sd0_last_cross(symbol, look=150):
    """Where price sits against SD0 (the rolling mean of the last `lookback_len` closes):
    'down'  = last time it crossed SD0 it went from above to below,
    'up'    = last cross was from below to above,
    'below' / 'above' = no cross inside the last `look` candles, price is just below / above.
    None = not enough candles. Pure read of history_cache, only runs when a gated signal fires."""
    with lock:
        c = [float(x["close"]) for x in (history_cache.get(symbol) or [])]
    L = int(strategy.lookback_len)
    if len(c) < L + 2:
        return None
    pre = [0.0]
    for v in c:
        pre.append(pre[-1] + v)

    def mean_at(i):
        j0 = max(0, i - L + 1)
        return (pre[i + 1] - pre[j0]) / (i + 1 - j0)

    for i in range(len(c) - 1, max(1, len(c) - look) - 1, -1):
        m1, m0 = mean_at(i), mean_at(i - 1)
        if c[i - 1] >= m0 and c[i] < m1:
            return "down"
        if c[i - 1] <= m0 and c[i] > m1:
            return "up"
    return "below" if c[-1] < mean_at(len(c) - 1) else "above"


def _extra_entry_block(signal, symbol, bot_id="b1"):
    """Reason text if a NEW entry must be skipped by the daily schedule, the max-open-trades
    limit or the gainer/loser SD0 rules - else None. Called inside _open_lock, so the open-trade
    count cannot race."""
    try:
        ok, why = day_gate.entries_allowed()
        if not ok:
            return why
    except Exception:
        pass
    try:
        # Smart Brain skip switch (default OFF, needs earned trust + solid luck test). Returns None in every other case.
        import smart_brain
        _sb = smart_brain.gate_reason(symbol, signal.action)
        if _sb:
            return _sb
    except Exception:
        pass
    try:
        # Part 7 (README_FILTER): gates made from the filter study. Default OFF (setting f7_gates_mode). Current bot only. Any problem = take the trade.
        if bot_id == "b1":
            import v2_f7_gates
            _g7 = v2_f7_gates.gate_reason(signal, symbol, list(history_cache.get(symbol) or []))
            if _g7:
                return _g7
    except Exception:
        pass
    try:
        # Part 4 bot side (README_OWNER): US-session gate. Setting f9_session_mode, default "log" = only writes a line, stops nothing. Any problem = take the trade.
        if bot_id == "b1":
            import v2_f9_session
            _g9 = v2_f9_session.gate_reason(signal, symbol)
            if _g9:
                return _g9
    except Exception:
        pass
    try:
        # Part 9 bot side (README_OWNER): entry snapshot logger. Writes the state numbers of the signal, NEVER blocks (setting f11_snap_mode, default on). Any problem = nothing happens.
        if bot_id == "b1":
            import v2_f11_snap
            v2_f11_snap.log_signal(signal, symbol, list(history_cache.get(symbol) or []))
    except Exception:
        pass
    try:
        mx = int(settings_store.get("max_open_trades", 0) or 0)
        if mx > 0 and not _is_btc(symbol):      # BTC has its own slot: never blocked by, never counted in, the alt limit
            if settings_store.get("live_trading_enabled", False):
                # LIVE account: count only REAL Binance positions (old paper trades must not
                # fill the slots). Fresh read; if Binance cannot be read, block - never guess.
                try:
                    from . import live_snapshot
                    held = live_snapshot.held_live_symbols_strict()
                except Exception as e:
                    return f"Cannot read open positions from Binance ({str(e)[:60]}) - entry skipped for safety"
            else:
                try:
                    held = {str(x).upper() for x in paper_trader.open_symbols()}
                except Exception:
                    held = _held_symbols()
            held.discard(BTC_SYMBOL)
            if str(symbol).upper() not in held and len(held) >= mx:
                return f"Max open trades ({mx}) already open"
    except Exception:
        pass
    try:
        act = str(signal.action).upper()
        cat = None if _is_btc(symbol) else _coin_category(symbol)     # BTC is exempt from the gainer/loser SD0 rules
        if act == "SELL" and cat == "gainer" and settings_store.get("block_sell_on_gainer", False):
            if _sd0_last_cross(symbol) not in ("down", "below"):
                return "Gainer coin: SELL waits until price crosses SD0 from above to below"
        if act == "BUY" and cat == "loser" and settings_store.get("block_buy_on_loser", False):
            if _sd0_last_cross(symbol) not in ("up", "above"):
                return "Loser coin: BUY waits until price crosses SD0 from below to above"
    except Exception:
        pass
    return None


def _open_signal(signal, symbol, source="watchlist", bot_id="b1"):
    """Send to Telegram, log it, and (if every gate passes) open the
    paper trade. Returns True if a trade was actually opened."""
    count = _bump_signal_count(bot_id, symbol)
    signal.signal_no = count
    bot.send_signal(signal)
    _rec_signal = lambda *a, **k: db.record_signal(*a, bot=bot_id, **k)
    _skip_b = lambda *a: _skip_meta(*a, bot_id=bot_id)
    _add_sig = status.add_signal if bot_id == "b1" else (lambda _t: None)
    ts = datetime.now().strftime("%H:%M:%S")
    status.set_last_signal(symbol, signal.action, ts)
    symbol_mode = settings_store.get_symbol_mode(symbol, "BOTH")
    symbol_auto_on = symbol_mode != "OFF"
    direction_ok = symbol_mode == "BOTH" or symbol_mode == signal.action.upper()
    global_auto_on = settings_store.get("auto_execute", True)
    # FINAL ROUND: master trading pause/resume toggle (Dashboard header
    # pill) - independent of auto_execute/symbol-mode/daily limits above,
    # and independent of live_trading_enabled (paper vs live routing).
    # execution_router.is_trading_enabled() reads settings_store fresh
    # every call, defaulting to True/ON so nothing changes for anyone who
    # never taps the pill. Market data/LTP polling (poll_klines/market_ws)
    # and manual position closes are NOT gated by this - only new signals
    # reaching this function are.
    trading_paused = not execution_router.is_trading_enabled()
    _extra_block = _extra_entry_block(signal, symbol, bot_id)
    target_hit = _daily_target_hit(bot_id)
    loss_hit = _daily_loss_limit_hit(bot_id)
    if _is_btc(symbol) and _btc_fixed():
        target_hit = loss_hit = False      # BTC trades 10x bigger than the alts: the alt daily target / loss limit must not block it
    # Pre-trade health check: confirm this symbol actually has a live price
    # right now before ever opening a position on it. This is the fix for
    # the 2U2USDTM bug class - a signal firing on a thin/invalid/delisted
    # symbol that the price feed can never track afterwards, leaving the
    # position with frozen P&L and unclosable via the normal Close flow.
    # Candle history was already required to reach generate_signal() at
    # all, so this only needs to check the live-price side.
    # get_best_live_price() returns (price, source, error) - 3 values. Unpacking
    # into 2 raised ValueError on EVERY signal (after the Telegram send, before
    # db.record_signal / any trade), so signals reached Telegram but never the app.
    _live_price = market_ws.get_best_live_price(symbol)[0]
    _price_ok = _live_price is not None
    # STALE-DATA CIRCUIT BREAKER (PART 4) - per-symbol, NOT scanner-wide.
    # See timeframe_manager.py's is_fresh() docstring for why this replaced
    # the old global market_ws live-tick gate. Only blocks a NEW entry on
    # THIS symbol; every other symbol in the watchlist and every already-
    # open position's protection/monitoring loop are untouched by this
    # check.
    _data_fresh = timeframe_manager.is_fresh(symbol)
    # 1:1 PINE SCRIPT PARITY - signal-age gate: generate_signal() stamps
    # signal_time from the closed candle's own timestamp (UTC). If this
    # signal is only reaching _open_signal() more than MAX_SIGNAL_AGE_SEC
    # after that candle closed (poll cycle stalled, thread-pool backlog,
    # etc.), the bar this signal was computed from is no longer "the
    # current bar" by the time an order would go out - skip it instead of
    # firing a stale, Pine-Script-divergent trade. A signal with no
    # parsable signal_time (should not normally happen) is let through
    # rather than blocked, since there is nothing to measure staleness
    # against.
    _age_sec = None
    _age_ok = True
    if signal.signal_time:
        try:
            _sig_dt = datetime.strptime(signal.signal_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            _age_sec = exchange.now_sec() - _sig_dt.timestamp()
            _age_ok = _age_sec <= MAX_SIGNAL_AGE_SEC
        except (ValueError, TypeError):
            _age_sec = None
            _age_ok = True
    # 1:1 PINE SCRIPT PARITY - chase/slippage guard: compare the CURRENT
    # live price against the signal's own entry_price (the closed candle's
    # close, per strategy.py). If price has already run more than
    # CHASE_GUARD_PCT away from that by the time we're about to dispatch
    # the order, filling here would enter meaningfully away from the
    # price the strategy's SL/TP1-4 ladder was actually computed for -
    # skip rather than chase. Only evaluated when a live price is
    # available at all (the earlier _price_ok gate already handles "no
    # price feed").
    _slip_pct = None
    _slip_ok = True
    if _price_ok and signal.entry_price:
        _slip_pct = abs(_live_price - signal.entry_price) / signal.entry_price * 100.0
        _slip_ok = _slip_pct <= CHASE_GUARD_PCT
    # TRADE PIPELINE DIAGNOSTIC: one line per evaluated signal, console +
    # Telegram, so "why aren't trades opening" can be root-caused from the
    # log alone instead of guessing. Reason mirrors exactly the gate that
    # the if/elif chain below will actually act on - never a separate/
    # out-of-sync computation.
    if not _data_fresh:
        _stale_age = timeframe_manager.seconds_since_fetch(symbol)
        _stale_desc = (f"{_stale_age:.1f}s old" if _stale_age is not None else "never fetched yet")
        _health_pass, _health_reason = False, f"Candle data stale for this symbol ({_stale_desc})"
    elif not _price_ok:
        _health_pass, _health_reason = False, "No live price feed (thin/invalid/delisted symbol)"
    elif not _age_ok:
        _health_pass, _health_reason = False, f"Signal stale ({_age_sec:.1f}s > {MAX_SIGNAL_AGE_SEC}s max age)"
    elif not _slip_ok:
        _health_pass, _health_reason = False, f"Chase guard - price slipped {_slip_pct:.3f}% > {CHASE_GUARD_PCT}% from entry"
    elif trading_paused:
        _health_pass, _health_reason = False, execution_router.TRADING_PAUSED_MESSAGE
    elif _extra_block:
        _health_pass, _health_reason = False, _extra_block
    elif not symbol_auto_on:
        _health_pass, _health_reason = False, "Auto-trade OFF for this coin"
    elif not direction_ok:
        _health_pass, _health_reason = False, f"Coin is {symbol_mode}-only, {signal.action} signal ignored"
    elif not global_auto_on:
        _health_pass, _health_reason = False, "Global Auto-Trade OFF"
    elif target_hit:
        _health_pass, _health_reason = False, "Daily target already reached"
    elif loss_hit:
        _health_pass, _health_reason = False, "Daily loss limit already hit"
    else:
        _health_pass, _health_reason = True, "OK - dispatching order now"
        _record_signal_lag(symbol)
    _diag_line = (f"[SIGNAL CHECK] Symbol: {symbol} | Pattern: Valid ({signal.action}) | "
                  f"Health Check: {'Pass' if _health_pass else 'Fail'} ({_health_reason})")
    print(_diag_line)
    # Telegram gets only the FAIL cases (a Pass immediately gets its own
    # full send_signal() card below/above anyway) - keeps this from doubling
    # Telegram traffic on every successful trade while still surfacing every
    # skip reason there too, not just in the console.
    if not _health_pass and bot_id == "b1":
        try:
            bot.send_text(_diag_line)
        except Exception:
            pass
    # Each possible skip reason gets its own distinct log line, so the
    # Dashboard's Recent Signals list can never look identical for a
    # successfully-opened trade and a skipped one.
    if not _data_fresh:
        _reason = f"Candle data stale for this symbol ({_stale_desc})"
        _add_sig(f"#{count} {symbol} @ {ts} - Stale symbol data, trade skipped")
        status.add_alert("skip", f"#{count} {symbol} - {_reason}, trade skipped",
                          **_skip_b(signal, symbol, count, _reason))
        _rec_signal(signal, symbol, opened=False, skip_reason=_reason)
    elif not _price_ok:
        _add_sig(f"#{count} {symbol} @ {ts} - No live price feed, trade skipped")
        status.add_alert("skip", f"#{count} {symbol} - No live price feed available, trade skipped",
                          **_skip_b(signal, symbol, count, "Symbol has no live price data (thin/invalid/delisted)"))
        _rec_signal(signal, symbol, opened=False, skip_reason="No live price feed for symbol")
    elif not _age_ok:
        _reason = f"Signal stale - {_age_sec:.1f}s old (max {MAX_SIGNAL_AGE_SEC}s)"
        _add_sig(f"#{count} {symbol} @ {ts} - Stale signal ({_age_sec:.1f}s), trade skipped")
        status.add_alert("skip", f"#{count} {symbol} - {_reason}, trade skipped",
                          **_skip_b(signal, symbol, count, _reason))
        _rec_signal(signal, symbol, opened=False, skip_reason=_reason)
    elif not _slip_ok:
        _reason = f"Chase guard - price slipped {_slip_pct:.3f}% from entry (max {CHASE_GUARD_PCT}%)"
        _add_sig(f"#{count} {symbol} @ {ts} - Chase guard tripped ({_slip_pct:.3f}%), trade skipped")
        status.add_alert("skip", f"#{count} {symbol} - {_reason}, trade skipped",
                          **_skip_b(signal, symbol, count, _reason))
        _rec_signal(signal, symbol, opened=False, skip_reason=_reason)
    elif trading_paused:
        _add_sig(f"#{count} {symbol} @ {ts} - Bot PAUSED by master toggle, trade skipped")
        status.add_alert("skip", f"#{count} {symbol} - {execution_router.TRADING_PAUSED_MESSAGE}",
                          **_skip_b(signal, symbol, count, execution_router.TRADING_PAUSED_MESSAGE))
        _rec_signal(signal, symbol, opened=False, skip_reason=execution_router.TRADING_PAUSED_MESSAGE)
    elif _extra_block:
        _add_sig(f"#{count} {symbol} @ {ts} - {_extra_block}, trade skipped")
        status.add_alert("skip", f"#{count} {symbol} - {_extra_block}", **_skip_b(signal, symbol, count, _extra_block))
        _rec_signal(signal, symbol, opened=False, skip_reason=_extra_block)
    elif global_auto_on and symbol_auto_on and direction_ok and not target_hit and not loss_hit:
        # PHASE 2 - EXCLUSIVE LIVE/PAPER ROUTING: live_trading_enabled is the
        # single switch that decides which engine handles this signal, never
        # both. When it's ON, this goes to the active exchange's real trader
        # ONLY - paper_trader.open_paper_trade() is not called at all, so no
        # paper position/record is created and the paper side stays
        # completely silent for as long as live stays on. When it's OFF,
        # paper trading runs exactly as before.
        if settings_store.get("live_trading_enabled", False):
            live_opened = _open_live_trade(signal, symbol)
            if not live_opened:
                # PRODUCTION HARDENING: a live order that failed/rejected/
                # never confirmed a fill must NEVER be recorded as
                # opened=True - that used to happen unconditionally here
                # regardless of _open_live_trade's outcome. Distinct
                # skip-style entry instead, same as every other skip case
                # above, so the Signals screen shows the truth.
                reason = "Live order failed (exchange rejected the order or fill could not be confirmed)"
                _add_sig(f"#{count} {symbol} @ {ts} - LIVE order failed, no position opened")
                status.add_alert("skip", f"#{count} {symbol} - {reason}", **_skip_b(signal, symbol, count, reason))
                _rec_signal(signal, symbol, opened=False, skip_reason=reason)
                return False
        else:
            open_paper_trade(signal, source=source, bot=bot_id)
        _add_sig(f"#{count} {symbol} @ {ts}")
        _rec_signal(signal, symbol, opened=True)
        return True
    elif not symbol_auto_on:
        _add_sig(f"#{count} {symbol} @ {ts} - Auto OFF, trade skipped")
        status.add_alert("skip", f"#{count} {symbol} - Auto OFF for this symbol, trade skipped", **_skip_b(signal, symbol, count, "Auto-trade is OFF for this coin"))
        _rec_signal(signal, symbol, opened=False, skip_reason="Auto OFF for this symbol")
    elif not direction_ok:
        _add_sig(f"#{count} {symbol} @ {ts} - {symbol_mode}-only, {signal.action} signal skipped")
        status.add_alert("skip", f"#{count} {symbol} - set to {symbol_mode}-only, {signal.action} signal skipped", **_skip_b(signal, symbol, count, f"Coin is {symbol_mode}-only, {signal.action} signal ignored"))
        _rec_signal(signal, symbol, opened=False, skip_reason=f"{symbol_mode}-only, {signal.action} skipped")
    elif not global_auto_on:
        _add_sig(f"#{count} {symbol} @ {ts} - Global Auto-Trade OFF, trade skipped")
        status.add_alert("skip", f"#{count} {symbol} - Global Auto-Trade OFF, trade skipped", **_skip_b(signal, symbol, count, "Global Auto-Trade is OFF"))
        _rec_signal(signal, symbol, opened=False, skip_reason="Global Auto-Trade OFF")
    elif target_hit:
        _add_sig(f"#{count} {symbol} @ {ts} - Daily target reached, trade skipped")
        status.add_alert("target", f"Daily target reached - #{count} {symbol} skipped", **_skip_b(signal, symbol, count, "Daily target reached"))
        _rec_signal(signal, symbol, opened=False, skip_reason="Daily target reached")
    elif loss_hit:
        _add_sig(f"#{count} {symbol} @ {ts} - Daily loss limit hit, trade skipped")
        status.add_alert("loss", f"Daily loss limit hit - #{count} {symbol} skipped", **_skip_b(signal, symbol, count, "Daily loss limit hit"))
        _rec_signal(signal, symbol, opened=False, skip_reason="Daily loss limit hit")
    return False


def _scan_missed_signals(symbol, candles, tf_min, max_back=80):
    """After a restart the first candle we see is too old to trade, and any
    signal that fired while the bot was off is never replayed. If this coin
    still has an OPEN position, replay the candles closed since it opened and
    flag the position OUTDATED when an opposite EMA-cross happened in between.
    Flag only - never opens or closes anything."""
    try:
        opened = {}
        _st = status.get()
        for p in (_st.get("open_positions") or []):
            if p.get("symbol") == symbol:
                opened[p.get("action")] = float(p.get("opened_at_ts") or 0)
        if not opened or not candles or not tf_min:
            return
        since_ms = min(opened.values()) * 1000.0
        n = len(candles)
        for i in range(max(1, n - max_back), n):
            close_ms = int(candles[i]["timestamp"]) + int(tf_min) * 60_000
            if close_ms <= since_ms:
                continue
            sig = strategy.generate_signal(candles[: i + 1], symbol, tf_min=tf_min)
            if sig and sig.action.upper() in ("BUY", "SELL") and sig.action.upper() not in opened:
                when = datetime.fromtimestamp(close_ms / 1000).strftime("%H:%M")
                # Bot was off/restarting = a DATA problem (not a user choice), so
                # the old position is also closed as REVERSED at that cross
                # candle's close - exactly what the live flow would have done.
                # reconcile_first replays the gap so an SL/TP touched before the
                # cross still closes the trade for the right reason.
                paper_trader.flag_outdated(
                    symbol, sig.action,
                    f"{sig.action} cross at {when} happened while the bot was off/restarting - never processed",
                    close_price=float(sig.entry_price), auto_close=True, reconcile_first=True)
                return
    except Exception as e:
        print(f"[MissedScan] {symbol}: {e}")


def _exit_only_signal(signal, symbol):
    """Opposite EMA cross on a held coin that is outside the top-20 list:
    close the old paper position as REVERSED, open nothing."""
    try:
        n = paper_trader.close_on_opposite_cross(
            symbol, signal.action, float(signal.entry_price),
            why="(coin left the top-10 gainers/losers list: exit only, no new entry)")
        if n:
            status.add_alert(
                "sync",
                f"EXIT: {symbol} {signal.action} cross closed {n} open trade(s). "
                f"Coin is outside the top-20 list, so no new trade was opened.",
                kind="outdated", symbol=symbol)
        # Live mode: Binance positions are not closed from here - just flag.
        if settings_store.get("live_trading_enabled", False):
            paper_trader.flag_outdated(symbol, signal.action, "coin left the top-20 list")
    except Exception as e:
        print(f"[ExitOnly] {symbol}: {e}")


def process_candle(symbol: str, kline_data: dict):
    global history_cache, last_processed_candle
    close_time = int(kline_data['t'])
    with lock:
        if symbol not in history_cache or len(history_cache[symbol]) == 0:
            history_cache[symbol] = fetch_initial_history(symbol)
        candles = history_cache[symbol]
        if candles and candles[-1]['timestamp'] == close_time:
            candles[-1] = {
                'timestamp': close_time,
                'open': float(kline_data['o']),
                'high': float(kline_data['h']),
                'low': float(kline_data['l']),
                'close': float(kline_data['c']),
                'volume': float(kline_data['v'])
            }
        else:
            new_candle = {
                'timestamp': close_time,
                'open': float(kline_data['o']),
                'high': float(kline_data['h']),
                'low': float(kline_data['l']),
                'close': float(kline_data['c']),
                'volume': float(kline_data['v'])
            }
            candles.append(new_candle)
            if len(candles) > INITIAL_HISTORY_LIMIT:
                candles = candles[-INITIAL_HISTORY_LIMIT:]
            history_cache[symbol] = candles

        # Closed-candle guarantee: this same closed candle can arrive again on
        # every poll cycle (every POLL_INTERVAL seconds) until Binance rolls
        # over to the next 3m candle - only let the strategy evaluate it once
        # per symbol, instead of re-running generate_signal() ~20+ times for
        # the same closed candle.
        already_processed = last_processed_candle.get(symbol) == close_time
        # STARTUP-STALE FIX: the first candle seen for a symbol after a
        # restart / timeframe change / watchlist re-entry was closed long
        # ago (up to a full candle). Running the strategy on it only
        # produced "Signal stale - 200s old" skip alerts. If that first
        # candle is already older than the signal-age gate, just mark it
        # seen and move on; a genuinely fresh first candle still trades.
        _first_seen = symbol not in last_processed_candle
        _missed_args = None
        if not already_processed:
            last_processed_candle[symbol] = close_time
        if _first_seen and not already_processed:
            try:
                _tf_first = exchange.active_strategy_timeframe_min()
                _close_age = exchange.now_sec() - (close_time + int(_tf_first) * 60_000) / 1000.0
                if _close_age > MAX_SIGNAL_AGE_SEC:
                    already_processed = True
                    _missed_args = (symbol, list(candles), _tf_first)
            except Exception:
                pass

    # Runs OUTSIDE `lock`: the missed-reversal catch-up may now close a
    # position (and replay candles over REST), which must never block the scanner.
    if _missed_args:
        _scan_missed_signals(*_missed_args)

    if already_processed:
        return

    try:
        _tf_min = exchange.active_strategy_timeframe_min()
        _last_close_ms[symbol] = close_time + int(_tf_min) * 60_000
        _pickup_lag = exchange.now_sec() - _last_close_ms[symbol] / 1000.0
        # Per-symbol pickup line only when it is actually late (or when
        # OWL_VERBOSE_SCAN=1) - on time it fires 20x per candle and buries
        # the real signal/trade lines in the Termux console.
        if _pickup_lag > 2.0 or os.getenv("OWL_VERBOSE_SCAN") == "1":
            print(f"[PICKUP] {symbol}: candle closed {_pickup_lag:.2f}s ago when picked up")
    except Exception:
        _tf_min = None
    signal = strategy.generate_signal(history_cache[symbol], symbol, tf_min=_tf_min)
    if signal:
        # PRODUCTION HARDENING: dedup guard now backed by db.py's sqlite
        # `idempotency` table instead of the RAM-only `sent_signals` set -
        # a restart no longer forgets which signals were already acted on,
        # so a crash/restart right after a signal fired can't replay it
        # into a second, duplicate trade.
        # DUPLICATE-TRADE RACE FIX: claim_signal() is one atomic
        # check-and-mark step (see db.py) instead of the old separate
        # is_duplicate() + mark_processed() calls, which left a window
        # where two threads could both pass the check before either one
        # marked it, and both open a trade for the same signal.
        sig_key = f"{symbol}_{signal.signal_time}"
        # EXIT-ONLY: a coin we still hold but which has dropped out of the top-10
        # gainers/losers list. Its opposite cross must still CLOSE the open
        # trade (the AI learns from exits), but no new trade opens on it -
        # entries stay limited to the top-20 universe.
        _owner = _owner_of(symbol)
        _in_universe = _owner is not None
        if not _in_universe:
            with _open_lock:
                if not db.claim_signal(sig_key):
                    return
                _exit_only_signal(signal, symbol)
            return
        # One dispatcher at a time: candles can now arrive from BOTH the
        # Binance WS worker and the REST poll thread, and the max-open-
        # positions / daily-limit checks inside _open_signal must not race.
        with _open_lock:
            if not db.claim_signal(sig_key):
                return
            _open_signal(signal, symbol, bot_id=_owner)
    else:
        # TRADE PIPELINE DIAGNOSTIC: confirms the strategy actually ran on
        # this closed candle and simply found no EMA cross - console-only
        # (no Telegram) since this fires once per symbol per closed candle,
        # every candle, and would otherwise flood the chat.
        if os.getenv("OWL_VERBOSE_SCAN") == "1":
            print(f"[SIGNAL CHECK] Symbol: {symbol} | Pattern: None | Health Check: N/A (no signal to evaluate)")

# SINGLE-FLIGHT: if two threads ask for the same (symbol, timeframe) candle at
# the same moment (burst poller + a reconnect catch-up, overlapping cycles...)
# only ONE HTTP request goes out; the others wait for and share its result.
_kl_sf = {}
_kl_sf_lock = threading.Lock()


def _fetch_kline_for(symbol):
    try:
        key = (symbol, int(exchange.active_strategy_timeframe_min()))
    except Exception:
        return _fetch_kline_raw(symbol)
    with _kl_sf_lock:
        slot = _kl_sf.get(key)
        leader = slot is None
        if leader:
            slot = {"ev": threading.Event(), "res": None}
            _kl_sf[key] = slot
    if not leader:
        telemetry.count("singleflight_hits")
        slot["ev"].wait(timeout=15)
        return slot["res"]
    try:
        slot["res"] = _fetch_kline_raw(symbol)
        return slot["res"]
    finally:
        with _kl_sf_lock:
            _kl_sf.pop(key, None)
        slot["ev"].set()


def _fetch_kline_raw(symbol):
    try:
        # Same configured-timeframe read as fetch_initial_history() above -
        # must always match it, otherwise a closed 5m candle could get
        # compared/appended against a history cache built from 15m candles
        # (or vice versa) after a mid-session Timeframe change.
        tf_min = exchange.active_strategy_timeframe_min()
        data = exchange.get_klines(symbol, limit=2, tf=tf_min)
        if not data:
            return None
        # STALE-SIGNAL FIX: get_klines() already returns CLOSED candles only
        # (it drops the still-forming trailing row internally - see
        # exchange.py's _enforce_closed_candles). data[-1] IS the latest
        # closed candle. Taking data[-2] here on top of that was a
        # double-drop that made the bot trade one whole candle-period late
        # (e.g. 300s on a 5m timeframe) - the exact cause of the
        # "Signal stale - 310s old (max 25s)" skips: by the time a signal
        # off that stale candle reached the age gate, it was already one
        # full candle old before the gate even started counting.
        k = data[-1]  # latest CLOSED candle
        return symbol, {
            't': k['timestamp'],
            'o': k['open'],
            'h': k['high'],
            'l': k['low'],
            'c': k['close'],
            'v': k['volume'],
        }
    except requests.exceptions.RequestException as e:
        # Network-level failure (DNS, connection drop, timeout) - already
        # retried internally by the shared session; just skip this symbol
        # for this cycle instead of taking down the whole poll loop.
        print(f"[Poll] Network error for {symbol}: {e}")
        return None
    except Exception as e:
        print(f"[Poll] Error for {symbol}: {e}")
        return None


# ---- CANDLE-CLOSE-ALIGNED POLLING (TradingView-speed signals) -------------
# Old behaviour: poll every POLL_INTERVAL (8s) blindly -> a signal could sit
# up to 8s+ before the bot even saw the closed candle. Now the loop wakes
# right at each candle boundary and, for ~BURST_WINDOW_SEC after it, keeps
# re-polling ONLY the symbols whose new closed candle hasn't been processed
# yet (BURST_RETRY_SEC apart) until every one is picked up. Between
# boundaries it behaves exactly like before (POLL_INTERVAL), so the
# freshness stamps used by the stale-data breaker are unchanged.
BURST_WINDOW_SEC = 10
BURST_RETRY_SEC = 0.35
BOUNDARY_LEAD_SEC = 0.10
WS_GRACE_SEC = 2.0   # REST fallback waits this long after a candle close if the WS feed is healthy


def _candle_clock():
    """(tf_ms, boundary_ms, expected_open_ms, now_ms) or None for very long
    timeframes where epoch alignment doesn't apply."""
    try:
        tf_min = int(exchange.active_strategy_timeframe_min())
    except Exception:
        return None
    if tf_min <= 0 or tf_min > 720:
        return None
    tf_ms = tf_min * 60_000
    now_ms = exchange.now_ms()
    boundary = (now_ms // tf_ms) * tf_ms
    return tf_ms, boundary, boundary - tf_ms, now_ms


def _rest_gap_symbols(symbols):
    """Routine (between-candle) REST sweep. While the WS candle feed is
    healthy it already delivers every closed candle AND keeps the stale-data
    freshness stamp alive (market_ws._stamp_fresh), so re-fetching the whole
    watchlist every 8s is pure duplicate work. REST now only covers real gaps:
      * symbols never processed yet (warm-up: builds their history once),
      * symbols the WS is not delivering klines for (rejected subscription,
        new to the watchlist, timeframe just changed).
    If the WS is not healthy it falls back to the old full sweep."""
    try:
        if not market_ws.candle_feed_healthy():
            return list(symbols)
        return [s for s in symbols
                if s not in last_processed_candle or not market_ws.ws_covers(s)]
    except Exception:
        return list(symbols)


def _pending_symbols(symbols, clock):
    """Inside the post-close burst window: only symbols still waiting for the
    just-closed candle. Otherwise: everything (normal cycle)."""
    if clock is None:
        return list(symbols)
    tf_ms, boundary, expected_open, now_ms = clock
    if now_ms - boundary > BURST_WINDOW_SEC * 1000:
        return _rest_gap_symbols(symbols)
    # WS is the primary source of closed candles. While it is healthy, give
    # it WS_GRACE_SEC to deliver before REST steps in as the safety net.
    try:
        if now_ms - boundary < WS_GRACE_SEC * 1000 and market_ws.candle_feed_healthy():
            return []
    except Exception:
        pass
    return [s for s in symbols if last_processed_candle.get(s) != expected_open]


def _sleep_until_next_poll(symbols):
    clock = _candle_clock()
    if clock is None:
        time.sleep(POLL_INTERVAL)
        return
    tf_ms, boundary, expected_open, now_ms = clock
    if now_ms - boundary <= BURST_WINDOW_SEC * 1000:
        if any(last_processed_candle.get(s) != expected_open for s in symbols):
            time.sleep(BURST_RETRY_SEC)
            return
    to_next = (boundary + tf_ms - now_ms) / 1000.0 + BOUNDARY_LEAD_SEC
    time.sleep(max(0.05, min(POLL_INTERVAL, to_next)))


def poll_klines():
    global watchlist, last_watchlist_refresh
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=POLL_WORKERS)
    while True:
        try:
            _check_timeframe_change()
            if time.time() - last_watchlist_refresh >= WATCHLIST_REFRESH_INTERVAL:
                # This refresh attempt must run BEFORE the empty-watchlist
                # check below, not after it. Bug: if the watchlist ever goes
                # empty (e.g. a DNS/offline blip during refresh_watchlist()),
                # the old order returned via `continue` on the empty-check
                # and never reached this refresh call again - permanently
                # stuck with an empty watchlist even after the network came
                # back, since nothing ever called refresh_watchlist() a
                # second time. Now it always gets attempted every cycle
                # regardless of current watchlist size.
                refresh_watchlist()
                last_watchlist_refresh = time.time()
            current_watch = list(_scan_symbols())
            if not current_watch:
                time.sleep(5)
                continue

            # Fetch all symbols concurrently instead of one-by-one - this was
            # the main source of the "signal/open is late" delay: with ~20
            # symbols polled serially (0.5s sleep each) a symbol near the end
            # of the list could be checked 15-25s after its candle closed.
            _clock = _candle_clock()
            _cycle_t0 = time.monotonic()
            _fetch_list = _pending_symbols(current_watch, _clock)
            for result in executor.map(_fetch_kline_for, _fetch_list):
                if result:
                    sym, kline_data = result
                    # STALE-DATA CIRCUIT BREAKER (PART 4): stamp "we just got
                    # good data for this symbol" the instant it arrives -
                    # _open_signal()'s timeframe_manager.is_fresh(sym) check
                    # reads this. Stamped here (not inside process_candle)
                    # so a symbol still counts as fresh even on a poll cycle
                    # where its candle hasn't actually closed yet - freshness
                    # is about "is the feed for this symbol alive", not
                    # "did a new candle close this tick".
                    timeframe_manager.mark_fetched(sym)
                    try:
                        process_candle(sym, kline_data)
                    except Exception as e:
                        print(f"[Poll] process_candle error for {sym}: {e}")
            # Stamped after every full cycle across the watchlist completes -
            # lets the UI show "data last captured Xs ago" so the user can
            # see for themselves whether polling is actually keeping up
            # (should never lag far behind POLL_INTERVAL) instead of just
            # trusting it blindly.
            status.update(last_poll_cycle_ts=time.time())
            telemetry.record_poll((time.monotonic() - _cycle_t0) * 1000.0,
                                  len(_fetch_list), len(current_watch) - len(_fetch_list))

            # Cheap, no network call - just flips the badge to STALE if the
            # WebSocket thread has gone quiet without technically closing.
            # Does not touch candle polling or signal generation at all.
            try:
                market_ws.stale_watchdog_tick()
            except Exception:
                pass

            # NOTE: the old adaptive throttle here doubled POLL_INTERVAL when
            # Binance's request-weight header got high - removed along with
            # the migration (see note near POLL_INTERVAL above). Fixed
            # interval for now.
            _sleep_until_next_poll(current_watch)
        except Exception as e:
            print(f"[Poll] Loop error: {e}")
            status.update(last_error=f"Poll loop: {e}")
            time.sleep(5)

# ---- WS-PRIMARY CANDLE INTAKE ---------------------------------------------
# market_ws pushes every CLOSED candle (kline event with x=true) here the
# instant Binance closes it. A queue + one worker keeps the WS reader thread
# free (order dispatch can take 100-300ms). The REST burst poller above stays
# as the safety net; process_candle() + db.claim_signal() make sure a candle
# that arrives via BOTH paths still yields exactly one evaluation.
_ws_candle_q = queue.Queue(maxsize=1000)


def on_ws_closed_candle(symbol, k):
    try:
        _ws_candle_q.put_nowait((symbol, k))
    except queue.Full:
        pass


def _ws_candle_worker():
    while True:
        symbol, k = _ws_candle_q.get()
        try:
            with lock:
                known = symbol in watchlist
            if not known and symbol not in _held_symbols():
                continue
            timeframe_manager.mark_fetched(symbol)
            telemetry.count("ws_candles")
            process_candle(symbol, {
                't': int(k['t']), 'o': k['o'], 'h': k['h'],
                'l': k['l'], 'c': k['c'], 'v': k['v'],
            })
        except Exception as e:
            print(f"[WS-candle] process error for {symbol}: {e}")


def _time_sync_loop():
    while True:
        try:
            off = exchange.sync_server_time()
            status.update(server_time_offset_ms=round(off, 1))
            print(f"[TimeSync] Binance clock offset: {off:+.0f} ms")
        except Exception:
            pass
        time.sleep(300)


def heartbeat():
    while True:
        time.sleep(60)
        with lock:
            sym_count = len(watchlist)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [Heartbeat] Bot zinda hai! Symbols: {sym_count}")

def main():
    print("Starting OWL Terminal bot (REST polling, pure Python)...")
    status.update(status="Starting bot...")
    # Must run before any network calls (refresh_watchlist, WS connect,
    # Telegram send, etc.) - see dns_fallback.py for why this exists.
    dns_fallback.ensure_dns_fallback()
    # FINAL ROUND: startup reconciliation - runs BEFORE refresh_watchlist()/
    # anything else assumes it knows what's open, per
    # reconciliation.reconcile_on_startup()'s own docstring. Queries
    # Binance directly for real open positions and makes sure every one
    # already has a resting protective stop (placing the strategy's own
    # stored SL if live_trade_meta.json has it, else an emergency %% stop -
    # see reconciliation.py). Honest no-op if live trading is off or
    # Binance isn't reachable yet - never raises, never blocks the rest of
    # startup.
    try:
        reconciliation.reconcile_on_startup()
    except Exception as e:
        status.update(last_error=f"Startup reconcile: {e}")
    # LIVE POSITION PROTECTION LOOP: continuous TP1->breakeven guard for
    # LIVE (exchange-routed) positions - protection_manager.guard_tick()
    # already existed with full idempotent breakeven-shift + resting-stop +
    # orphan-purge logic, but start_guard_loop() was never actually called
    # anywhere, so it never ran. It is an honest no-op every tick when live
    # trading is off or Binance isn't the active exchange (see
    # guard_tick()'s own early-return), so it is always safe to start here
    # regardless of current settings - it simply activates the moment live
    # trading is turned on.
    try:
        protection_manager.start_guard_loop()
    except Exception as e:
        status.update(last_error=f"Startup guard loop: {e}")
    try:
        refresh_watchlist()
    except Exception as e:
        status.update(last_error=f"Startup: {e}")
    t1 = threading.Thread(target=poll_klines, daemon=True)
    t2 = threading.Thread(target=heartbeat, daemon=True)
    t3 = threading.Thread(target=paper_trade_monitor_loop, daemon=True)
    t1.start()
    t2.start()
    t3.start()
    threading.Thread(target=_time_sync_loop, daemon=True).start()
    threading.Thread(target=_ws_candle_worker, daemon=True).start()
    try:
        market_ws.set_candle_callback(on_ws_closed_candle)
    except Exception as e:
        status.update(market_data_error=f"WS candle hook: {e}")

    # Market Watch live-ticker WebSocket - started LAST, wrapped so any
    # failure here (missing dependency, connection error, whatever) can
    # never prevent t1/t2/t3 (candle polling, heartbeat, paper trading) from
    # running. Market Watch just falls back to its REST snapshot value if
    # this doesn't come up - nothing else in the app depends on it.
    try:
        market_ws.start()
    except Exception as e:
        status.update(market_data_error=f"WebSocket startup: {e}")

    while True:
        time.sleep(10)

if __name__ == "__main__":
    main()
