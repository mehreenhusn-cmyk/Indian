"""
ai_ind_tracker.py - records the Z-score and the TSI (the 2 indicators in the lower pane)
WHILE a paper trade is open.

Why: the bot trades on the EMA50 cross. Z-score and TSI are NOT used by the bot, but the AI
should learn when they warn that a running trade is about to give its profit back. Until now
only the entry-time numbers existed; nothing was saved about what Z / TSI did AFTER entry.
Once per CLOSED candle of each open trade this module saves:
    [seconds since entry, z, tsi, tsi_signal]
  z          = (close - mean200) / std200   (same maths as ai_ind_features / the Pine script)
  tsi        = True Strength Index (25, 13)
  tsi_signal = EMA13 of the TSI  (TSI - signal = the "Bj candle" histogram)
The samples go into ai_path_logger (same JSON line as ROI / SD / slope path) and
ai_observer replays "exit when TSI turns against the trade AND Z falls back" on them.

Safety (same rules as ai_sd_tracker / ai_slope_tracker):
  - runs in its OWN daemon thread, never inside the trading/monitor loop
  - read-only: only exchange.get_klines (closed candles) + recording
  - at most MAX_FETCH candle downloads per cycle; backs off after repeated failures
  - setting ind_track_enabled (default True) turns it off completely
  - every error is swallowed; nothing here is used by any trading decision
  - data exists ONLY for trades opened after this module started (older trades have none)
"""
import threading
import time

LOOKBACK = 330          # Z needs 200 candles, TSI needs ~100 to settle
CYCLE_S = 20
MAX_FETCH = 3           # candle downloads per cycle (bigger fetch than the other trackers)
_started = False
_fail = 0
_pause_until = 0.0
_last_bar = {}          # key -> last bar open time (s) already logged


def ind_sample(candles):
    """(z, tsi, tsi_signal) of the LAST closed candle, or None while not computable."""
    try:
        from . import ai_ind_features
        S = ai_ind_features.build(candles)
        z, tsi, tsl = S["z"][-1], S["tsi"][-1], S["tsl"][-1]
        if z is None or tsi is None or tsl is None:
            return None
        return round(z, 3), round(tsi, 2), round(tsl, 2)
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
    if not settings_store.get("ind_track_enabled", True):
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
            st = ind_sample(candles)
        except Exception:
            continue
        if not st:
            continue
        t_sec = round(max(0.0, last_ts + step - float(opened)), 1)   # bar CLOSE time since entry
        if t_sec <= 0:
            _last_bar[key] = bar_open
            continue
        ai_path_logger.add_ind(key, [t_sec, st[0], st[1], st[2]])
        _last_bar[key] = bar_open
    if len(_last_bar) > 500:
        for k in list(_last_bar):
            if k not in seen:
                _last_bar.pop(k, None)


def _loop():
    time.sleep(35)
    while True:
        try:
            _cycle()
        except Exception as e:
            print(f"[IndTracker] cycle error (ignored): {e}")
        time.sleep(CYCLE_S)


def start():
    """Start the background thread once. Safe to call repeatedly."""
    global _started
    if _started:
        return
    _started = True
    try:
        threading.Thread(target=_loop, name="ai-ind-tracker", daemon=True).start()
    except Exception as e:
        print(f"[IndTracker] could not start: {e}")
