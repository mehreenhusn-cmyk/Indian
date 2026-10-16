"""
ai_slope_tracker.py - records what the EMA50 SLOPE does WHILE a paper trade is open.

At entry the app saves one number: the EMA change over the last 3 candles
(ema_slope_pct). That says nothing about what the EMA does AFTER the trade
starts - e.g. a BUY that was opened with the EMA rising, but the EMA rolls
over 10 minutes later and the trade dies at SL (a "fake signal"). This module
adds, once per CLOSED candle of each open trade:
    [seconds since entry, slope3 %, ema, close_vs_ema %]
  slope3       = EMA change over the last 3 candles (same formula as the entry value)
  ema          = EMA50 value at that bar
  close_vs_ema = (close - ema) / ema * 100 - how far price sits from the EMA
The samples go into ai_path_logger (same JSON line as the ROI path and SD path),
and ai_miner learns from them (_slope_study).

Safety (same rules as ai_sd_tracker):
  - runs in its OWN daemon thread, never inside the trading/monitor loop
  - read-only: only exchange.get_klines (closed candles) + recording
  - at most MAX_FETCH candle downloads per cycle; backs off after repeated failures
  - setting slope_track_enabled (default True) turns it off completely
  - every error is swallowed; nothing here is used by any trading decision
  - data exists ONLY for trades opened after this module started (older trades have none)
"""
import threading
import time

LOOKBACK = 120          # candles fetched (EMA50 needs 50 + 10 for the slope)
CYCLE_S = 20
MAX_FETCH = 4           # candle downloads per cycle
_started = False
_fail = 0
_pause_until = 0.0
_last_bar = {}          # key -> last bar open time (s) already logged
_ema_fn = None


def _ema_series(closes):
    """EMA50 exactly as the strategy computes it (reuses its own function)."""
    global _ema_fn
    if _ema_fn is None:
        from .strategy import ABCDStrategy
        _ema_fn = ABCDStrategy()._compute_ema
    return _ema_fn(closes)


def slope_sample(closes):
    """(slope3_pct, ema, close_vs_ema_pct) from closed-candle closes, or None."""
    try:
        e = _ema_series(closes)
        a, b = e[-1], e[-4]
        if a is None or not b or a <= 0:
            return None
        return round((a - b) / b * 100.0, 4), a, round((closes[-1] - a) / a * 100.0, 4)
    except Exception:
        return None


def _tf_minutes(pos):
    try:
        from . import exchange
        return int(exchange.resolve_timeframe(pos.get("timeframe")))
    except Exception:
        return 5


def _cycle():
    global _fail, _pause_until
    from . import paper_trader, ai_path_logger, exchange, settings_store
    if not settings_store.get("slope_track_enabled", True):
        return
    if time.time() < _pause_until:
        return
    with paper_trader._lock:
        pos_list = [dict(p) for p in paper_trader._positions.values()]
    if not pos_list:
        _last_bar.clear()
        return
    seen = ai_path_logger.open_keys()
    fetched = {}
    budget = MAX_FETCH
    now = time.time()
    for pos in pos_list:
        opened = pos.get("opened_at_ts")
        if not opened:
            continue
        key = ai_path_logger.make_key(pos.get("id"), opened)
        if key not in seen:
            continue                      # ROI path not started yet (first price tick)
        tf = _tf_minutes(pos)
        step = tf * 60
        bar_open = int(now // step) * step - step      # open time (s) of the last CLOSED bar
        if _last_bar.get(key, 0) >= bar_open:
            continue
        ck = (pos.get("symbol"), tf)
        if ck not in fetched:
            if budget <= 0:
                continue
            budget -= 1
            try:
                fetched[ck] = exchange.get_klines(pos.get("symbol"), tf=tf, limit=LOOKBACK, fast=True)
                _fail = 0
            except Exception:
                _fail += 1
                fetched[ck] = None
                if _fail >= 6:
                    _pause_until = time.time() + 600
                    _fail = 0
                    return
        candles = fetched.get(ck)
        if not candles:
            continue
        try:
            last_ts = int(candles[-1]["timestamp"]) / 1000.0
            if last_ts < bar_open - 1:
                continue                  # exchange has not served the newest closed bar yet
            st = slope_sample([float(x["close"]) for x in candles])
        except Exception:
            continue
        if not st:
            continue
        slope, ema, dist = st
        t_sec = round(max(0.0, last_ts + step - float(opened)), 1)   # bar CLOSE time since entry
        if t_sec <= 0:
            _last_bar[key] = bar_open
            continue
        ai_path_logger.add_slope(key, [t_sec, slope, round(ema, 8), dist], pos.get("ema_slope_pct"))
        _last_bar[key] = bar_open
    if len(_last_bar) > 500:
        for k in list(_last_bar):
            if k not in seen:
                _last_bar.pop(k, None)


def _loop():
    time.sleep(25)
    while True:
        try:
            _cycle()
        except Exception as e:
            print(f"[SlopeTracker] cycle error (ignored): {e}")
        time.sleep(CYCLE_S)


def start():
    """Start the background thread once. Safe to call repeatedly."""
    global _started
    if _started:
        return
    _started = True
    try:
        threading.Thread(target=_loop, name="ai-slope-tracker", daemon=True).start()
    except Exception as e:
        print(f"[SlopeTracker] could not start: {e}")
