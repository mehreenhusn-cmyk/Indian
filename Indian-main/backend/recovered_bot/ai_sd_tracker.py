"""
ai_sd_tracker.py - records how the SD bands change WHILE a paper trade is open.

The strategy uses SD levels as take-profit levels and the SD width as the
volatility measure, but the bands are re-computed on every bar, so their SIZE
(width) and SHAPE (expanding / shrinking / centre drifting) can change a lot
after entry (see a coin that crashes and the bands balloon). Until now only the
entry-time SD was saved. This module adds, once per CLOSED candle of each open
trade:  [seconds since entry, width %, mean, k_now]
  width %  = 1 SD / mean * 100   (same formula as strategy.sd_width_pct)
  mean     = rolling mean of the last 200 closes (the centre line)
  k_now    = where the last close sits in LIVE SD units
The samples go into ai_path_logger (same JSON line as the ROI path).

Safety:
  - runs in its OWN daemon thread, never inside the trading/monitor loop
  - read-only: it only calls exchange.get_klines (closed candles) and records
  - at most MAX_FETCH candle downloads per cycle, backs off when downloads fail,
    and switches itself off for a while after repeated failures
  - setting sd_track_enabled (default True) turns it off completely
  - every error is swallowed; nothing here is used by any trading decision
"""
import threading
import time

LOOKBACK = 200          # same as Strategy.lookback_len
CYCLE_S = 20
MAX_FETCH = 4           # candle downloads per cycle
_started = False
_fail = 0
_pause_until = 0.0
_last_bar = {}          # key -> last bar timestamp (ms) already logged


def sd_stats(closes, lookback=LOOKBACK):
    """(width_pct, mean, std, k_now) from a list of closes, or None."""
    try:
        w = closes[-lookback:]
        n = len(w)
        if n < 30:
            return None
        mean = sum(w) / n
        std = (sum((x - mean) ** 2 for x in w) / n) ** 0.5
        if mean <= 0 or std <= 0:
            return None
        return std / mean * 100.0, mean, std, (closes[-1] - mean) / std
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
    if not settings_store.get("sd_track_enabled", True):
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
            continue                      # this bar is already logged
        ck = (pos.get("symbol"), tf)
        if ck not in fetched:
            if budget <= 0:
                continue
            budget -= 1
            try:
                c = exchange.get_klines(pos.get("symbol"), tf=tf, limit=LOOKBACK + 5, fast=True)
                fetched[ck] = c
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
            st = sd_stats([float(x["close"]) for x in candles])
        except Exception:
            continue
        if not st:
            continue
        w, mean, std, k = st
        sd0 = None
        if pos.get("sd_width_pct") is not None:
            sd0 = {"w": pos.get("sd_width_pct"), "mean": pos.get("sd_mean"), "std": pos.get("sd_std")}
        t_sec = round(max(0.0, last_ts + step - float(opened)), 1)   # bar CLOSE time since entry
        if t_sec <= 0:
            _last_bar[key] = bar_open
            continue
        ai_path_logger.add_sd(key, [t_sec, round(w, 4), round(mean, 8), round(k, 3)], sd0)
        _last_bar[key] = bar_open
    if len(_last_bar) > 500:
        keep = set(seen)
        for k in list(_last_bar):
            if k not in keep:
                _last_bar.pop(k, None)


def _loop():
    time.sleep(15)
    while True:
        try:
            _cycle()
        except Exception as e:
            print(f"[SDTracker] cycle error (ignored): {e}")
        time.sleep(CYCLE_S)


def start():
    """Start the background thread once. Safe to call repeatedly."""
    global _started
    if _started:
        return
    _started = True
    try:
        threading.Thread(target=_loop, name="ai-sd-tracker", daemon=True).start()
    except Exception as e:
        print(f"[SDTracker] could not start: {e}")
