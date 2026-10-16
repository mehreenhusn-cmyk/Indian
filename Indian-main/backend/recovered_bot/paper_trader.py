import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from . import status
from . import settings_store
from . import trade_store
from . import market_ws
from . import ai_data_logger
try:
    from . import ai_path_logger      # records each trade's real ROI path (display/analysis only)
except Exception:                     # never let the recorder break trading
    ai_path_logger = None
from . import exchange
from . import db

_lock = threading.Lock()
_positions = {}
_next_id = 1

def init(legacy_json_path=None):
    """Load any positions that were open before the app was killed/restarted.

    Open positions now live in db.py's SQLite `positions` table (row-level
    upserts, not a whole-file rewrite every second - see _save() below).
    `legacy_json_path`, if given, is only used once: to migrate a
    pre-SQLite install's positions.json into the new table so nothing open
    at upgrade time is lost (db.migrate_positions_json_if_needed - a no-op
    on every call after the first). db.init() must already have been
    called (api_server.py's startup sequence does this before calling
    here)."""
    global _positions, _next_id
    if legacy_json_path:
        db.migrate_positions_json_if_needed(legacy_json_path)
    with _lock:
        _positions, _next_id = db.load_positions()
    _refresh_status_positions()


def reset():
    """Clear all open positions."""
    global _positions
    with _lock:
        _positions.clear()
    _save()
    _refresh_status_positions()


def _save():
    """Persist the current in-RAM `_positions` to db.py's SQLite table.
    Replaces the old json.dump()-a-whole-file-every-second approach - see
    db.save_positions()'s docstring for why this is cheap enough to call
    on every monitor-loop tick (once a second) without the disk-I/O spike
    a full JSON rewrite caused."""
    with _lock:
        snapshot = dict(_positions)
        next_id_snapshot = _next_id
    try:
        db.save_positions(snapshot, next_id_snapshot)
    except Exception as e:
        print(f"[PaperTrade] position save failed: {e}")


def _get_live_price(symbol):
    """WS-first, REST-fallback. Returns just the price (None on total
    failure) - callers that also want to show the source (LIVE_WS/
    REST_FALLBACK/OFFLINE) should call market_ws.get_best_live_price()
    directly instead."""
    price, source, error = market_ws.get_best_live_price(symbol)
    if price is None:
        status.update(market_data_error=error)
    return price


# ------------------------------------------------------------------ alert detail ----

def _fmt_duration(secs):
    secs = int(max(0, secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s}s" if m else f"{s}s"


def _reason_label(reason, pos):
    if reason == "SL":
        return "Trailing SL hit" if pos.get("trailed_sl") else "Stop loss hit"
    if reason == "SCALP_TARGET":
        return "Universal TP % hit"
    if reason == "REVERSED":
        return "Reversed by opposite signal"
    if reason == "MANUAL":
        return "Closed manually"
    if reason.startswith("TP"):
        lvl = reason[2:3]
        return f"TP{lvl} target hit (picked manually)" if reason.endswith("_TARGET") else f"TP{lvl} hit"
    return reason


def _exit_tag(reason, pos):
    if reason == "SL":
        return "TSL" if pos.get("trailed_sl") else "SL"
    if reason == "SCALP_TARGET":
        return "SCALP"
    if reason == "REVERSED":
        return "REV"
    if reason == "MANUAL":
        return "MAN"
    if reason.startswith("TP"):
        return "TP"
    return "OTHER"


def _plan(pos):
    """Planned risk/reward for a position: original (untrailed) SL distance
    vs distance to its current full-close target. Used for the R:R shown on
    Alerts cards."""
    entry = pos.get("entry_price")
    orig = dict(pos)
    orig.pop("trailed_sl", None)
    sl0, _ = _effective_levels(orig)
    _sl_now, tps = _effective_levels(pos)
    valid = {k: v for k, v in tps.items() if v is not None}
    target_level = pos.get("user_target_tp") or (max(valid) if valid else None)
    target_price = tps.get(target_level) if target_level else None
    risk = abs(entry - sl0) if (entry and sl0 is not None) else None
    reward = abs(target_price - entry) if (entry and target_price is not None) else None
    rr = (reward / risk) if (risk and reward is not None) else None
    return {"sl0": sl0, "tps": tps, "target_level": target_level,
            "target_price": target_price, "risk": risk, "reward": reward, "rr": rr}


def _trade_meta(pos, exit_price=None, reason=None, note=None, recovered=False):
    """Structured detail attached to an Alerts entry (see status.add_alert).
    Everything is derived from data already on the position - nothing here
    changes trading behaviour."""
    plan = _plan(pos)
    sl_now, tps = _effective_levels(pos)
    entry = pos.get("entry_price")
    lev = float(pos.get("leverage", 1) or 1)
    invest = float(pos.get("invest_usdt", 0) or 0)
    d = {
        "trade_id": pos.get("id"),
        "bot": pos.get("bot") or "b1",
        "signal_no": pos.get("signal_no"),
        "symbol": pos.get("symbol"),
        "side": pos.get("action"),
        "entry": entry,
        "sl": sl_now,
        "sl_initial": plan["sl0"],
        "sl_trailed": bool(pos.get("trailed_sl")),
        "tp": {str(k): v for k, v in tps.items() if v is not None},
        "target_level": plan["target_level"],
        "size_usdt": invest,
        "leverage": lev,
        "notional": invest * lev,
        "rr_planned": plan["rr"],
        "trigger": pos.get("trigger"),
        "sl_type": pos.get("sl_type"),
        "source": pos.get("source"),
        "peak_roi": pos.get("max_roi_pct"),
        "worst_roi": pos.get("min_roi_pct"),
        "tp_hit_levels": list(pos.get("tp_hit_levels", [])),
        "opened_at": pos.get("opened_at"),
        "opened_at_ts": pos.get("opened_at_ts"),
    }
    if reason is not None:
        d["reason"] = reason
        d["reason_label"] = _reason_label(reason, pos)
        d["exit_tag"] = _exit_tag(reason, pos)
        d["exit"] = exit_price
        d["pnl"] = pos.get("pnl_usdt")
        d["roi"] = pos.get("roi_pct")
        d["closed_at"] = pos.get("closed_at")
        d["duration_s"] = pos.get("duration_s")
        if plan["sl0"] is not None and entry and plan["risk"]:
            move = (exit_price - entry) if pos.get("action") == "BUY" else (entry - exit_price)
            d["r_realized"] = move / plan["risk"]
    if note:
        d["note"] = note
    if recovered:
        d["recovered"] = True
    return d


def _push_today_stats():
    stats = trade_store.get_today_stats()
    status.update(**stats)


def open_symbols():
    """Symbols that currently have an open PAPER position (cheap, lock-only).
    app.py / market_ws.py use it so a coin that dropped out of the top-10
    gainers/losers is still scanned and priced while we hold it."""
    with _lock:
        return {p.get("symbol") for p in _positions.values() if p.get("symbol")}


def close_on_opposite_cross(symbol, new_action, price, signal_no=None, why="", bot=None):
    """EXIT-ONLY handling of an opposite EMA cross on a coin we still hold but
    which is no longer in the top-10 gainers/losers list: close the old
    position as REVERSED (same close the normal flow does) but never open a
    new trade on that coin. Returns how many positions were closed."""
    new_action = (new_action or "").upper()
    with _lock:
        ids = [tid for tid, p in _positions.items()
               if p.get("symbol") == symbol and p.get("action") != new_action
               and (bot is None or (p.get("bot") or "b1") == bot)]
    for tid in ids:
        _close_position(tid, "REVERSED", float(price),
                        note=f"Opposite {new_action} cross on {symbol} @ {float(price):g} {why}".strip())
    return len(ids)


def open_paper_trade(signal, source="watchlist", bot="b1"):
    global _next_id
    bot = "b2" if str(bot or "b1").lower() == "b2" else "b1"
    s = settings_store.get_all()
    entry = float(signal.entry_price)
    action = signal.action.upper()

    # Only the latest signal's trade should stay open per symbol - close any
    # existing open position(s) on this symbol first (same or opposite side).
    with _lock:
        existing_ids = [tid for tid, p in _positions.items()
                        if p["symbol"] == signal.symbol and (p.get("bot") or "b1") == bot]
    for tid in existing_ids:
        _close_position(tid, "REVERSED", entry,
                        note=f"Opposite {action} signal #{getattr(signal, 'signal_no', '?')} on {signal.symbol} @ {entry:g}")

    invest_amount = float(s.get("invest_amount", 10.0))
    ema_len = int(s.get("ema_length", 50) or 50)
    # CONFIGURABLE STRATEGY TIMEFRAME: was exchange.GRANULARITY_MIN (the raw
    # exchange default, always 5) - now reflects whatever timeframe the
    # signal actually fired on (settings_store["timeframe"]).
    tf_label = s.get("timeframe", "5m") or "5m"
    trigger = f"EMA{ema_len} cross {'up' if action == 'BUY' else 'down'} on {tf_label} close"
    if source == "topup":
        trigger += " (top-up scan)"
    if getattr(signal, "stop_loss", None) is not None:
        sl_type = f"Signal candle {'low' if action == 'BUY' else 'high'}"
    else:
        sl_type = f"Fixed {float(s.get('sl_value', 1.5)):g}%"
    with _lock:
        trade_id = _next_id
        _next_id += 1
        _positions[trade_id] = {
            "id": trade_id,
            "bot": bot,
            "signal_no": getattr(signal, "signal_no", None),
            "symbol": signal.symbol,
            "action": action,
            "entry_price": entry,
            "invest_usdt": invest_amount,
            "leverage": float(s.get("leverage", 1)),
            "tp_mode": s.get("tp_mode", "percent"),
            "tp_value": float(s.get("tp_value", 3.0)),
            "sl_value": float(s.get("sl_value", 1.5)),
            # The strategy's own absolute SL/TP levels (same numbers sent to
            # Telegram) - unchanged, straight from strategy.py. SL is FIXED
            # for the life of the trade (no trailing/moving) since that was
            # only ever needed for the old 25%-per-TP partial-booking system,
            # which has been removed. TP1-4 are reference lines only; the
            # position fully closes (100%, one trade, no partial chunks) the
            # moment price reaches whichever level is the current target -
            # user_target_tp if the user tapped a TP box, else TP4 by default.
            "signal_stop_loss": getattr(signal, "stop_loss", None),
            "signal_tp1": getattr(signal, "tp1", None),
            "signal_tp2": getattr(signal, "tp2", None),
            "signal_tp3": getattr(signal, "tp3", None),
            "signal_tp4": getattr(signal, "tp4", None),
            "user_target_tp": None,     # manual override from tapping a TP1-4 box (None = default target TP4)
            "tp_hit_levels": [],        # TP levels (1-4) price has ever reached, even if it later retraced -
                                         # monotonic (only grows) so the UI can show a permanent tick instead
                                         # of a live fill % that disappears again on a pullback.
            "breakeven_auto_shifted": False,  # TP Execution Mode: Strategy TP auto-shifts SL to entry once
                                               # TP1 is hit (see paper_trade_monitor_loop) - this flag makes
                                               # that a one-time action per trade, not re-armed every tick.
            "opened_at": datetime.now().strftime("%H:%M:%S"),
            "opened_at_ts": time.time(),
            "trigger": trigger,
            # Entry-context tags for the AI Assistant (see ai_stats.py) - pure
            # metadata copied straight from strategy.py's Signal, never read
            # by any trading decision. getattr keeps older/other Signal
            # objects (top-up scans etc.) working with None.
            "timeframe": tf_label,
            "entry_zone": getattr(signal, "entry_zone", None),
            "ema_slope_pct": getattr(signal, "ema_slope_pct", None),
            "volume_ratio": getattr(signal, "volume_ratio", None),
            # SD basis at entry (mean / std of the signal candle's lookback) so the
            # trade's SD path can be tracked while it is open (see _update_sd_path).
            "sd_mean": getattr(signal, "sd_mean", None),
            "sd_std": getattr(signal, "sd_std", None),
            # Market-regime tags at entry (metadata only - see strategy._regime_context).
            "regime_cross_n": getattr(signal, "regime_cross_n", None),
            "atr_pct": getattr(signal, "atr_pct", None),
            "sd_width_pct": getattr(signal, "sd_width_pct", None),
            # EMA slope shape at entry (metadata only - see strategy._slope_context).
            "ema_slope_prev_pct": getattr(signal, "ema_slope_prev_pct", None),
            "ema_slope10_pct": getattr(signal, "ema_slope10_pct", None),
            "ema_turn": getattr(signal, "ema_turn", None),
            "sl_type": sl_type,
            "source": source,
            "last_ok_ts": time.time(),   # last moment a live price was successfully checked against SL/TP -
                                          # a big gap here (restart/outage) triggers the catch-up check
            "fee_roi_pct": _fee_roi_pct(),   # round-trip fee (ROI %) frozen at open - see _close_position
            "max_roi_pct": 0.0,          # best / worst ROI seen while open (peak / drawdown for Alerts)
            "min_roi_pct": 0.0,
            "status": "OPEN",
            "ltp": entry,
            "pnl_usdt": 0.0,
            "roi_pct": 0.0,
        }
    status.add_signal(f"OPEN {signal.symbol} {action} @ {entry}")
    with _lock:
        _open_snapshot = dict(_positions.get(trade_id, {}))
    # _trade_meta() already includes "trade_id" in its returned dict (it's
    # how upsert_trade_alert matches an existing card) - pop it before
    # unpacking as **kwargs, otherwise it collides with the trade_id passed
    # positionally just above and Python raises "got multiple values for
    # argument 'trade_id'" (this was crashing the monitor loop silently,
    # swallowed by paper_trade_monitor_loop's try/except).
    _open_meta = _trade_meta(_open_snapshot)
    _open_meta.pop("trade_id", None)
    status.upsert_trade_alert_paper(trade_id, "open", f"#{trade_id} {signal.symbol} {action} @ {entry}",
                     **_open_meta)
    _save()
    _refresh_status_positions()

    # Background ML/analysis data collection - see ai_data_logger.py.
    # Never touches trading behavior; failures inside are swallowed there.
    try:
        with _lock:
            snapshot = dict(_positions.get(trade_id, {}))
        if snapshot and bot == "b1":      # Bot 2 trades stay out of Bot 1's AI learning data
            ai_data_logger.log_trade_opened(snapshot)
    except Exception:
        pass
    # ML shadow log: store what the model WOULD say about this trade (never used by the bot).
    try:
        if snapshot and bot == "b1" and settings_store.get("legacy_ai_enabled", False):   # old AI off = no extra work per trade
            from . import ai_ml
            ai_ml.shadow_open(snapshot)
    except Exception:
        pass

    # NOTE (Phase 2 - exclusive routing): this function is now PAPER-ONLY.
    # It used to also fire a best-effort mirrored live order here - that
    # mirror is removed. Routing between paper and live now happens one
    # level up in app.py's _open_signal(), BEFORE this function is ever
    # called: live_trading_enabled True -> exchange.open_market_order()
    # only (this function is skipped entirely); False -> this function
    # only. The two never run for the same signal anymore.
    return trade_id


def _sd_k(pos, price):
    """Where `price` sits in SD units (0 = mean, +1 = +1SD ...) using the SD
    basis saved at entry. None if the position has no SD basis (older trades)."""
    try:
        m, sd = pos.get("sd_mean"), pos.get("sd_std")
        if m is None or not sd or float(sd) <= 0 or price is None:
            return None
        return (float(price) - float(m)) / float(sd)
    except (TypeError, ValueError):
        return None


def _update_sd_path(pos, price, ts=None):
    """Track the farthest SD level price reached IN favour (best) and AGAINST
    (worst) the trade, plus when. Mutates `pos`; silent no-op without SD basis."""
    k = _sd_k(pos, price)
    if k is None:
        return
    if pos.get("sd_entry_k") is None:
        ek = _sd_k(pos, pos.get("entry_price"))
        if ek is None:
            return
        pos["sd_entry_k"] = round(ek, 3)
        pos["sd_best_k"] = round(ek, 3)
        pos["sd_worst_k"] = round(ek, 3)
    ts = ts or time.time()
    is_long = pos.get("action") == "BUY"
    if (k > pos["sd_best_k"]) if is_long else (k < pos["sd_best_k"]):
        pos["sd_best_k"] = round(k, 3)
        pos["sd_best_ts"] = ts
    if (k < pos["sd_worst_k"]) if is_long else (k > pos["sd_worst_k"]):
        pos["sd_worst_k"] = round(k, 3)
        pos["sd_worst_ts"] = ts


def _quality_tag(pos, reason, recovered):
    """How trustworthy this trade's data is for the AI to learn from:
    recovered (closed by catch-up from 5m candles) > outdated (an opposite
    signal was missed/skipped) > reversed > restart_affected (a data gap hit
    it while open) > clean."""
    if recovered:
        return "recovered"
    if pos.get("outdated_reason"):
        return "outdated"
    if reason == "REVERSED":
        return "reversed"
    if pos.get("restart_affected"):
        return "restart_affected"
    return "clean"


def flag_outdated(symbol, new_action, why, close_price=None, auto_close=False, reconcile_first=False):
    """An OPPOSITE signal on `symbol` was skipped or missed, so any open
    position on that symbol is now out of date. Always FLAGS it (badge + alert).

    auto_close=True (only when the signal was lost to a data problem - bot off,
    restart, stale candle/signal, chase guard - never for a choice the user
    made like Auto OFF / one-side-only / daily limit): the old position is also
    CLOSED as REVERSED, exactly what would have happened had the new signal
    opened normally. It keeps its "outdated" quality tag, so the AI does not
    learn patterns from it. Switch off with settings key auto_close_outdated=False.

    close_price: price to close at (the signal price for a missed signal, the
    live price for a late one). reconcile_first: for a long gap, replay candles
    first so an SL/TP touched in between closes it properly instead.
    Returns how many positions were newly flagged."""
    new_action = (new_action or "").upper()
    flagged = []
    with _lock:
        for tid, p in _positions.items():
            if p.get("symbol") == symbol and p.get("action") != new_action and not p.get("outdated_reason"):
                p["outdated_reason"] = str(why)[:160]
                p["outdated_at_ts"] = time.time()
                p["outdated_signal"] = new_action
                flagged.append((tid, p.get("action")))
    do_close = bool(auto_close) and bool(settings_store.get("auto_close_outdated", True))
    for tid, act in flagged:
        status.add_alert_paper(
            "sync",
            f"OUTDATED: #{tid} {symbol} {act} - a {new_action} signal came but was not acted on "
            f"({why}). " + ("Closing it now." if do_close else "Check this position."),
            kind="outdated", trade_id=tid, symbol=symbol, side=act, skip_reason=str(why),
        )
    if flagged:
        _save()
        _refresh_status_positions()
    if do_close:
        for tid, act in flagged:
            try:
                if reconcile_first:
                    r = reconcile_position(tid, trigger="gap", force=True)
                    if r and r.get("closed"):
                        continue          # SL/TP was touched first - already closed for the right reason
                with _lock:
                    still = _positions.get(tid)
                if not still:
                    continue
                px = close_price
                if px is None:
                    px, _src, _err = market_ws.get_best_live_price(symbol)
                if px is None:
                    px = still.get("ltp") or still.get("entry_price")
                if not px:
                    continue
                _close_position(
                    tid, "REVERSED", float(px),
                    note=f"Late reversal: {new_action} signal was missed/delayed ({why}). "
                         f"Closed @ {float(px):g} (estimate, not the exact signal-time fill)")
            except Exception as e:
                print(f"[Outdated] auto-close #{tid} {symbol} failed: {e}")
    return len(flagged)


def _calc_roi(pos, ltp):
    entry = pos["entry_price"]
    if entry == 0:
        return 0.0
    raw = (ltp - entry) / entry * 100.0 if pos["action"] == "BUY" else (entry - ltp) / entry * 100.0
    return raw * pos["leverage"]


def _fee_roi_pct():
    """Round-trip exchange fee as % of ROI (setting fee_roi_pct, default 1.0)."""
    try:
        return max(0.0, float(settings_store.get("fee_roi_pct", 1.0) or 0.0))
    except Exception:
        return 1.0


def _open_fee_roi_pct(pos):
    """Round-trip fee (ROI %) an open position will pay when it closes: the value frozen at open,
    or the current setting for older positions. Same rule _close_position uses."""
    fee = pos.get("fee_roi_pct")
    try:
        return _fee_roi_pct() if fee is None else float(fee or 0.0)
    except Exception:
        return _fee_roi_pct()


def _close_position(trade_id, reason, ltp, note=None, recovered=False):
    """Fully close the position - one trade, full invest amount, full P&L.
    No partial-booking chunks anymore, so there's nothing to double-count."""
    with _lock:
        pos = _positions.pop(trade_id, None)
    if not pos:
        return
    gross_roi = _calc_roi(pos, ltp)
    # Real exchanges charge a fee on every trade; paper used to charge none, which
    # made paper P&L (and everything the AI learned from it) look better than
    # real money. fee_roi_pct was frozen at open (older open trades use the setting).
    fee = pos.get("fee_roi_pct")
    fee = _fee_roi_pct() if fee is None else float(fee or 0.0)
    roi = gross_roi - fee
    pnl = pos["invest_usdt"] * (roi / 100.0)
    pos.update(gross_roi_pct=gross_roi, fee_roi_pct=fee, fee_usdt=pos["invest_usdt"] * fee / 100.0,
               fee_applied=True)
    now_ts = time.time()
    pos.update(status=f"CLOSED_{reason}", ltp=ltp, roi_pct=roi, pnl_usdt=pnl,
               exit_price=ltp,
               closed_at=datetime.now().strftime("%H:%M:%S"),
               closed_at_ts=now_ts,
               duration_s=max(0, now_ts - (pos.get("opened_at_ts") or now_ts)),
               recovered=bool(recovered))
    pos["quality_tag"] = _quality_tag(pos, reason, bool(recovered))
    if note:
        pos["close_note"] = note
    trade_store.record_close(pos)
    _push_today_stats()
    status.add_signal(f"{reason} {pos['symbol']} P&L {pnl:+.2f} USDT ({roi:+.2f}%)")
    # Background ML/analysis data collection - see ai_data_logger.py.
    _is_b1 = (pos.get("bot") or "b1") != "b2"
    try:
        if _is_b1:
            ai_data_logger.log_trade_closed(pos, reason)
    except Exception:
        pass
    try:
        if _is_b1 and settings_store.get("legacy_ai_enabled", False):
            from . import ai_ml
            ai_ml.shadow_close(pos)       # match the earlier shadow guess with the real result
    except Exception:
        pass
    try:
        if ai_path_logger is not None:
            ai_path_logger.finish(pos, reason)
    except Exception:
        pass
    # Same "type" vocabulary the Alerts screen already color-codes by
    # (tp/target=green, sl/loss=red, reversed=yellow, manual=grey) -
    # scalp-target closes are a profit-taking event same as a TP, so they
    # get the "tp" alert color too.
    if reason == "SCALP_TARGET":
        alert_type = "tp"
    elif reason.startswith("TP"):
        alert_type = "tp"
    elif reason == "SL":
        alert_type = "sl"
    elif reason == "REVERSED":
        alert_type = "reversed"
    elif reason == "MANUAL":
        alert_type = "manual"
    elif reason == "FORCE_CLOSED_STALE_FEED":
        alert_type = "manual"
    else:
        alert_type = "manual"
    text = f"{reason} #{trade_id} {pos['symbol']} P&L {pnl:+.2f} USDT ({roi:+.2f}%)"
    if recovered:
        text += " [catch-up]"
    # upsert (not add): this updates the SAME card open_paper_trade() created
    # for this trade_id in place (adding exit/pnl/reason on top of the
    # entry/SL/TP it already had) instead of creating a second "close" card -
    # exactly one persistent card per trade lifecycle in the Alerts feed.
    _close_meta = _trade_meta(pos, exit_price=ltp, reason=reason, note=note, recovered=recovered)
    _close_meta.pop("trade_id", None)
    status.upsert_trade_alert_paper(trade_id, alert_type, text, **_close_meta)
    _save()
    _refresh_status_positions()

    # Live KuCoin close (best-effort, same non-blocking pattern as the open
    # side above - see open_paper_trade()).
    # Live close on whichever exchange is currently active (same
    # non-blocking, best-effort pattern as the open side above).
    # A paper position closing here must NEVER send a real Binance order: in LIVE mode a leftover paper trade on the
    # same coin as a real position would close the REAL one. Real positions are closed by the guard / live_recorder.
    if str(pos.get("trade_id") or pos.get("id") or "").startswith("LIVE-"):
        try:
            exchange.close_position_market(pos["symbol"], pos["action"])
        except Exception as e:
            status.add_alert("manual", f"LIVE CLOSE FAILED (exception): {pos['symbol']} - {e}")


def _effective_levels(pos):
    """Returns (sl, {1: tp1, 2: tp2, 3: tp3, 4: tp4}) - the strategy's own
    signal_stop_loss/signal_tp1-4 if this position has them, otherwise
    synthesized from THIS position's own tp_value/sl_value % (the settings
    values captured at the moment it was opened) around its entry price.

    This is what makes the TP1-4 select panel universal: every open
    position gets tappable levels, not just ones whose signal happened to
    include strategy-calculated price levels. Only TP1 (half of tp_value%
    away) and TP2 (the full tp_value% away) are synthesized - there's no
    strategy concept of a TP3/TP4 for a plain percent target, so those
    stay None for a synthesized position (the ladder just shows two
    boxes instead of four, same idea as before, just never empty)."""
    sl = pos.get("trailed_sl") or pos.get("signal_stop_loss")
    tps = {
        1: pos.get("signal_tp1"),
        2: pos.get("signal_tp2"),
        3: pos.get("signal_tp3"),
        4: pos.get("signal_tp4"),
    }
    if sl is None and tps[1] is None:
        entry = pos.get("entry_price")
        tp_pct = pos.get("tp_value")
        sl_pct = pos.get("sl_value")
        if entry:
            is_long = pos["action"] == "BUY"
            direction = 1 if is_long else -1
            if tp_pct:
                tps = {
                    1: entry * (1 + direction * (tp_pct / 2) / 100.0),
                    2: entry * (1 + direction * tp_pct / 100.0),
                    3: None,
                    4: None,
                }
            if sl_pct:
                sl = entry * (1 - direction * sl_pct / 100.0)
    return sl, tps


def set_target_tp(trade_id, level):
    """Manual override from tapping a TP1-4 box on an open position card
    that price has NOT reached yet.

    level is 1-4, or None to clear back to the default target (TP4). There
    is no partial booking - the position fully closes the moment price
    reaches whichever level is the current target, nothing more."""
    with _lock:
        pos = _positions.get(trade_id)
        if not pos:
            return
        pos["user_target_tp"] = level
    _save()
    _refresh_status_positions()


def move_sl_to_breakeven(trade_id):
    """"Move SL to Break-Even" quick action from a position card - trails the
    stop loss up to this position's own entry price. Same tighten-only guard
    as trail_sl_to_level() (refuses if the SL is already at or past entry, so
    tapping it twice - or after price already ran further and the SL got
    trailed past entry via TP taps - is a safe no-op, not a step backward)."""
    with _lock:
        pos = _positions.get(trade_id)
        if not pos:
            return False
        entry = pos.get("entry_price")
        if entry is None:
            return False
        current_active_sl, _tps = _effective_levels(pos)
        is_long = pos["action"] == "BUY"
        if current_active_sl is not None:
            tightens = (entry > current_active_sl) if is_long else (entry < current_active_sl)
            if not tightens:
                return False
        pos["trailed_sl"] = entry
    _save()
    status.add_alert_paper("manual", f"Break-even: #{trade_id} {pos['symbol']} SL moved to entry ({entry:g})")
    _refresh_status_positions()
    return True


def trail_sl_to_level(trade_id, level):
    """Manual trailing SL - tapping a TP1-4 box that price has ALREADY
    passed moves the STOP LOSS up to that level's price instead of closing
    the trade (closing is what set_target_tp()/the monitor loop would do
    for an already-satisfied level otherwise). The full-close target
    (user_target_tp, whatever it currently is) is untouched - the trade
    keeps running toward it, just with a tighter/locked-in SL now.

    Refuses (does nothing) if the level's price isn't actually on the
    profit side of the CURRENT active SL, i.e. it would loosen the SL
    instead of tightening it - e.g. tapping TP1 after already trailing to
    TP2 is a no-op, not a step backward."""
    with _lock:
        pos = _positions.get(trade_id)
        if not pos:
            return False
        current_active_sl, tps = _effective_levels(pos)
        tp_price = tps.get(level)
        if tp_price is None:
            return False
        is_long = pos["action"] == "BUY"
        if current_active_sl is not None:
            tightens = (tp_price > current_active_sl) if is_long else (tp_price < current_active_sl)
            if not tightens:
                return False
        pos["trailed_sl"] = tp_price
    _save()
    status.add_alert_paper("manual", f"Trailing SL: #{trade_id} {pos['symbol']} SL moved to TP{level} ({tp_price:g})")
    _refresh_status_positions()
    return True


def _stale_target_level(tps, level, ltp, is_long):
    """A tapped TP1-4 level is 'stale' if the live price has already
    advanced past a FARTHER target too - meaning this level was skipped
    over while a later level was the active target, not freshly reached
    just now. E.g. price is already between TP2 and TP3, and the user
    taps TP1: TP1's price is technically satisfied, but TP2 (farther)
    is ALSO already satisfied, so this isn't a genuine "just hit TP1"
    event. Closing a stale target counts as an SL, not a TP profit.
    `tps` is the {1: tp1, 2: tp2, 3: tp3, 4: tp4} dict from
    _effective_levels() - works the same for a synthesized (percent-mode)
    position's TP1/TP2 as for a strategy-signal position's full TP1-4."""
    for higher in range(level + 1, 5):
        higher_price = tps.get(higher)
        if higher_price is None:
            continue
        if is_long and ltp >= higher_price:
            return True
        if not is_long and ltp <= higher_price:
            return True
    return False


def close_position_manual(trade_id):
    """Manually close an open paper trade at a fresh live price (WS first,
    REST fallback).

    Returns a dict {"ok": bool, "forced": bool, "symbol": str|None,
    "error": str|None} instead of a bare bool, so callers (api_server.py,
    Close All Profit/Loss, Flatten All) can tell the user WHY a close
    didn't happen the normal way, instead of a position just silently
    staying open forever.

    - Live price available: closes normally at that price. ok=True,
      forced=False.
    - Live price genuinely unreachable (dead/thin/delisted symbol feed -
      this is what happened with 2U2USDTM): NEVER leaves the trade stuck.
      Falls back to the last price this position actually saw (its own
      cached "ltp", updated by the monitor loop every tick) or, if it
      never saw one, its entry price - and force-closes at that price,
      tagged reason "FORCE_CLOSED_STALE_FEED" so it's clearly marked as
      not a normal live-priced exit in history/Alerts. ok=True, forced=True.
    - Position id doesn't exist at all: ok=False, error="not_found".
    """
    with _lock:
        pos = _positions.get(trade_id)
    if not pos:
        return {"ok": False, "forced": False, "symbol": None, "error": "not_found"}
    symbol = pos["symbol"]
    price, source, error = market_ws.get_best_live_price(symbol)
    if price is not None:
        _close_position(trade_id, "MANUAL", price)
        return {"ok": True, "forced": False, "symbol": symbol, "error": None}

    status.update(market_data_error=error, last_manual_close_error=f"{symbol}: {error}")
    fallback_price = pos.get("ltp") or pos.get("entry_price")
    if not fallback_price:
        # No live price AND no fallback price at all (should be rare - a
        # position always has an entry_price) - genuinely nothing to close at.
        return {"ok": False, "forced": False, "symbol": symbol, "error": error or "no_price"}
    _close_position(
        trade_id, "FORCE_CLOSED_STALE_FEED", fallback_price,
        note=f"No live price feed ({error}) - force-closed at last-known {fallback_price:g}",
    )
    return {"ok": True, "forced": True, "symbol": symbol, "error": error}


def _fresh_snapshot(bot=None):
    """Re-prices every open position at a fresh live price (WS-first,
    REST-fallback, one fetch per unique symbol) instead of trusting each
    position's cached pnl_usdt, which can be up to ~1s stale (the monitor
    loop's own tick) or older if the monitor loop is behind. Used by both
    the close-all-profit/loss selection below AND the preview endpoint, so
    "what will close" (preview) and "what actually closes" (the real call,
    moments later) are computed the same way - re-verified at each call,
    not read off a snapshot that may already be out of date.

    Returns a list of dicts: id, symbol, action, ltp, pnl_usdt, roi_pct -
    for every currently-open position. Skips (omits) a position only if a
    live price genuinely cannot be fetched at all for its symbol."""
    with _lock:
        positions = [p for p in _positions.values() if bot is None or (p.get("bot") or "b1") == bot]
    # Fetch every unique symbol's price IN PARALLEL. When the WebSocket
    # cache is cold each price is a ~200ms REST call; doing them one after
    # another made Close All / the confirm dialog take seconds.
    symbols = sorted({pos["symbol"] for pos in positions})
    price_cache = {}
    if symbols:
        with ThreadPoolExecutor(max_workers=min(8, len(symbols))) as ex:
            for sym, px in zip(symbols, ex.map(_get_live_price, symbols)):
                price_cache[sym] = px
    out = []
    for pos in positions:
        symbol = pos["symbol"]
        ltp = price_cache.get(symbol)
        if ltp is None:
            continue
        # NET (after the round-trip fee) - the same number the position card, the top
        # pill and the Dashboard show, so "Close All Profit/Loss" picks exactly the
        # trades the screen shows as green/red, and the confirm total matches.
        gross_roi = _calc_roi(pos, ltp)
        roi = gross_roi - _open_fee_roi_pct(pos)
        pnl = pos["invest_usdt"] * (roi / 100.0)
        out.append({
            "id": pos["id"],
            "symbol": symbol,
            "action": pos["action"],
            "ltp": ltp,
            "pnl_usdt": pnl,
            "roi_pct": roi,
        })
    return out


def preview_close_all(mode, bot=None):
    """Non-destructive - just re-prices every open position (see
    _fresh_snapshot()) and returns which ones WOULD close for
    mode='profit'/'loss', plus their total P&L, so the app can show the
    user a confirmation ("3 positions, +4.12 USDT total - close?") before
    actually closing anything."""
    snapshot = _fresh_snapshot(bot)
    if mode == "profit":
        matched = [p for p in snapshot if p["pnl_usdt"] >= 0]
    else:
        matched = [p for p in snapshot if p["pnl_usdt"] < 0]
    return {
        "positions": matched,
        "count": len(matched),
        "total_pnl_usdt": sum(p["pnl_usdt"] for p in matched),
    }


def _close_snapshot_items(items):
    """Close each snapshot item at the price ALREADY fetched for it (no second
    round of price fetches). Returns how many closed."""
    closed = 0
    for it in items:
        with _lock:
            still_open = it["id"] in _positions
        if not still_open:
            continue
        try:
            _close_position(it["id"], "MANUAL", it["ltp"])
            closed += 1
        except Exception as e:
            print(f"[PaperTrade] close failed for #{it['id']}: {e}")
    return closed


def close_all_profit(bot=None):
    """Manually close every open position currently in profit, judged and
    closed at the SAME fresh live price fetched right now (parallel fetch, see
    _fresh_snapshot). Returns how many were closed, so the app can show
    "3 positions closed" instead of looking broken when there simply weren't
    any profitable positions to close."""
    return _close_snapshot_items([p for p in _fresh_snapshot(bot) if p["pnl_usdt"] >= 0])


def close_all_loss(bot=None):
    """Same as close_all_profit() but for positions currently in loss."""
    return _close_snapshot_items([p for p in _fresh_snapshot(bot) if p["pnl_usdt"] < 0])


def close_all_with_detail(bot=None):
    """Flatten All - close EVERY currently open position, one at a time,
    via close_position_manual() (so a dead/thin-feed symbol still gets
    force-closed instead of silently skipped - see that function's
    docstring). Unlike _fresh_snapshot()-based close_all_profit/loss, this
    iterates the raw open-position list directly, so it can't ever "skip"
    a position for having no live price the way the profit/loss selectors
    would.

    Returns {"closed_count": int, "failed_count": int, "details": [
      {"id", "symbol", "ok", "forced", "error"}, ...
    ]} - api_server.py hands this straight back to the app so "Flatten
    All"'s result message always matches what actually happened."""
    with _lock:
        ids = [tid for tid, p in _positions.items() if bot is None or (p.get("bot") or "b1") == bot]
    details = []
    closed = 0
    failed = 0
    for tid in ids:
        result = close_position_manual(tid)
        result["id"] = tid
        details.append(result)
        if result.get("ok"):
            closed += 1
        else:
            failed += 1
    return {"closed_count": closed, "failed_count": failed, "details": details}


def _refresh_status_positions():
    with _lock:
        snapshot = []
        for p in _positions.values():
            d = dict(p)
            # Ship the resolved SL/TP1-4 (strategy signal levels, or this
            # position's own synthesized TP1/TP2/SL - see _effective_levels())
            # as effective_sl/effective_tp1-4, so the Flutter TP ladder/card
            # doesn't need to duplicate the synthesis formula itself and can
            # never drift from what the monitor loop actually checks against.
            eff_sl, eff_tps = _effective_levels(p)
            d["effective_sl"] = eff_sl
            d["effective_tp1"] = eff_tps.get(1)
            d["effective_tp2"] = eff_tps.get(2)
            d["effective_tp3"] = eff_tps.get(3)
            d["effective_tp4"] = eff_tps.get(4)
            snapshot.append(d)
    # Dashboard's "Open Positions" card reads status['open_count'] but this
    # key was never actually set anywhere - only the open_positions list was
    # pushed, so the card always showed 0 even with real open positions.
    # Bot 1's list stays exactly where every screen/AI module already reads it; Bot 2's trades
    # live in their own key so nothing built for Bot 1 ever sees them by accident.
    b1 = [d for d in snapshot if (d.get("bot") or "b1") != "b2"]
    b2 = [d for d in snapshot if (d.get("bot") or "b1") == "b2"]
    status.update(open_positions=b1, open_count=len(b1))


def get_open_symbols():
    """Symbols that currently have an open position - used by the
    min-open-positions top-up scan to avoid duplicating a symbol that's
    already open."""
    with _lock:
        return {p["symbol"] for p in _positions.values()}


def get_open_count():
    with _lock:
        return len(_positions)


# ------------------------------------------------------------------ catch-up ----
#
# The monitor loop below checks each open position against a LIVE price about
# once a second. If that stops for a while - the bot process was stopped or
# restarted, the phone/VPS slept, or the price feed / internet was down - a
# TP or SL could have been touched in the meantime and nobody saw it, so the
# trade would just sit "open" forever (or close at some unrelated later price).
#
# Every position remembers `last_ok_ts` = the last moment a live price was
# successfully checked against its SL/TP (persisted to positions.json every
# tick). When a position gets a price again and that timestamp is more than
# GAP_RECONCILE_S old, we pull the 5m candles covering the gap and walk them
# oldest -> newest looking for the first SL / target / universal-TP touch.
# If found, the trade is closed at THAT LEVEL's price (not at whatever the
# price is now) and flagged "recovered" so the Alerts card explains it.
#
# Candle limits: a 5m candle only tells us high/low, not which came first. If
# SL and a target are both inside the same candle we count it as SL (the
# conservative choice). The candle that contains the entry moment is skipped
# because part of its range happened before the trade existed.

GAP_RECONCILE_S = 30
_reconcile_lock = threading.RLock()
_reconcile_retry_at = {}   # trade_id -> earliest time.time() to retry after a failed candle fetch


# ---------------------------------------------------------------- TRAILING SL (setting trail_mode) ----
# trail_mode (Settings -> Trade Risk):
#   "off"   - current behaviour: SL moves to entry once TP1 is touched, nothing else.
#   "step1" - stop follows ONE TP behind: TP1 -> entry, TP2 -> TP1, TP3 -> TP2.
#   "step2" - slow trail (stop stays at the original SL after TP1): TP2 -> entry, TP3 -> TP1.
# TP4 (the default target) always closes the whole trade, so it never needs a step.
# Only used in "Strategy TP" mode (Universal TP % has no SL ladder). Tighten-only: a step can
# never loosen a stop (a manually trailed SL further out stays). Same rules for Bot 1 and Bot 2.
TRAIL_MODES = ("off", "step1", "step2")


def _trail_mode():
    m = str(settings_store.get("trail_mode", "off") or "off").strip().lower()
    return m if m in TRAIL_MODES else "off"


def _trail_step_reached(hits):
    """Highest of TP1..TP3 the price has touched (0 = none)."""
    n = 0
    for lvl in (1, 2, 3):
        if lvl in hits:
            n = lvl
    return n


def _trail_floor_price(mode, entry, tps, hits):
    """Price the stop should sit at for the TP levels touched so far, or None (no step yet)."""
    n = _trail_step_reached(hits)
    if mode == "step1":
        return {1: entry, 2: tps.get(1), 3: tps.get(2)}.get(n)
    if mode == "step2":
        return {2: entry, 3: tps.get(1)}.get(n)
    return None


def _sl_tightens(cur_sl, new_sl, is_long):
    if new_sl is None:
        return False
    return cur_sl is None or ((new_sl > cur_sl) if is_long else (new_sl < cur_sl))


def _evaluate_candles(pos, candles, scalp_target, since_ts):
    """Pure function (no I/O) - walk candles oldest->newest and return
    (outcome_or_None, tp_hit_levels, best_roi, worst_roi, extra).
    outcome = {"reason", "exit_price", "note"}.
    extra = {"be_shift": bool, "sd": {sd_* path fields}} - the breakeven shift
    the live loop would have made (TP1 touched while away) and the SD path."""
    entry = pos["entry_price"]
    is_long = pos["action"] == "BUY"
    lev = float(pos.get("leverage", 1) or 1)
    sl, tps = _effective_levels(pos)
    valid = {k: v for k, v in tps.items() if v is not None}
    target_level = pos.get("user_target_tp") or (max(valid) if valid else None)
    target_price = tps.get(target_level) if target_level else None
    if target_level:
        target_reason = f"TP{target_level}_TARGET" if pos.get("user_target_tp") else f"TP{target_level}"
    else:
        target_reason = None

    scalp_price = None
    if scalp_target > 0 and lev > 0 and entry:
        move = scalp_target / lev
        scalp_price = entry * (1 + move / 100.0) if is_long else entry * (1 - move / 100.0)

    opened_ms = (pos.get("opened_at_ts") or 0) * 1000
    since_ms = (since_ts or 0) * 1000
    step_ms = exchange.GRANULARITY_MIN * 60_000
    hits = set(pos.get("tp_hit_levels", []))
    best = float(pos.get("max_roi_pct", 0.0) or 0.0)
    worst = float(pos.get("min_roi_pct", 0.0) or 0.0)

    # Breakeven: once TP1 is touched the live loop moves SL to entry (Strategy-TP
    # mode only). While the bot was away that never ran, so replay it here: SL
    # moves to entry for every candle AFTER the one that touched TP1 (inside that
    # candle the order is unknown, so the original SL still counts - conservative).
    be_mode = scalp_target <= 0 and entry is not None
    be_active = bool(pos.get("breakeven_auto_shifted"))
    be_shift = False

    def _tightens(cur):
        return cur is None or ((entry > cur) if is_long else (entry < cur))

    # Trailing steps (trail_mode step1/step2) replace the plain TP1 breakeven. Same "applies from
    # the NEXT candle" rule as the breakeven above.
    t_mode = _trail_mode() if be_mode else "off"
    trail_sl = None
    if t_mode != "off":
        want = _trail_floor_price(t_mode, entry, tps, hits)
        if _sl_tightens(sl, want, is_long):
            sl, trail_sl = want, want                 # levels were already touched before the gap
    elif be_mode and not be_active and 1 in hits and _tightens(sl):
        sl, be_active, be_shift = entry, True, True   # TP1 was already hit before the gap

    sdp = {k: pos.get(k) for k in ("sd_mean", "sd_std", "action", "entry_price", "sd_entry_k",
                                    "sd_best_k", "sd_worst_k", "sd_best_ts", "sd_worst_ts")}

    for c in sorted(candles, key=lambda x: x["timestamp"]):
        start = c["timestamp"]
        if start + step_ms <= since_ms:
            continue                      # entirely before the gap - already watched live
        if start < opened_ms:
            continue                      # candle containing the entry moment - ambiguous
        h, l = float(c["high"]), float(c["low"])
        fav, adv = (h, l) if is_long else (l, h)
        best = max(best, _calc_roi(pos, fav))
        worst = min(worst, _calc_roi(pos, adv))
        _c_ts = start / 1000.0 + step_ms / 2000.0
        _update_sd_path(sdp, fav, _c_ts)
        _update_sd_path(sdp, adv, _c_ts)
        for lvl, price in valid.items():
            if (h >= price) if is_long else (l <= price):
                hits.add(lvl)

        when = datetime.fromtimestamp(start / 1000).strftime("%H:%M")
        sl_hit = sl is not None and ((l <= sl) if is_long else (h >= sl))
        be_tag = (" (trailing stop)" if (trail_sl is not None and sl == trail_sl)
                  else (" (breakeven stop)" if (be_active and sl == entry) else ""))
        cands = []
        if scalp_price is not None and ((h >= scalp_price) if is_long else (l <= scalp_price)):
            cands.append((abs(scalp_price - entry), "SCALP_TARGET", scalp_price))
        if target_price is not None and ((h >= target_price) if is_long else (l <= target_price)):
            cands.append((abs(target_price - entry), target_reason, target_price))

        extra = lambda: {"be_shift": be_shift, "sd": sdp, "trail_sl": trail_sl}
        if sl_hit and cands:
            return ({"reason": "SL", "exit_price": sl,
                     "note": f"While away: {when} candle touched both SL and a target - counted as SL (conservative){be_tag}"},
                    sorted(hits), best, worst, extra())
        if cands:
            cands.sort()
            _d, reason, price = cands[0]
            return ({"reason": reason, "exit_price": price,
                     "note": f"While away: {when} candle touched the target"},
                    sorted(hits), best, worst, extra())
        if sl_hit:
            return ({"reason": "SL", "exit_price": sl,
                     "note": f"While away: {when} candle touched the stop loss{be_tag}"},
                    sorted(hits), best, worst, extra())
        if t_mode != "off":
            want = _trail_floor_price(t_mode, entry, tps, hits)
            if _sl_tightens(sl, want, is_long):
                sl, trail_sl = want, want                 # applies from the NEXT candle
        elif be_mode and not be_active and 1 in hits and _tightens(sl):
            sl, be_active, be_shift = entry, True, True   # applies from the NEXT candle
    return None, sorted(hits), best, worst, {"be_shift": be_shift, "sd": sdp, "trail_sl": trail_sl}


def reconcile_position(trade_id, trigger="gap", force=False):
    """Catch-up check for ONE open position (see block comment above).
    Returns a small result dict, or None if candles could not be fetched (the
    caller retries later; last_ok_ts is left untouched so nothing is lost)."""
    with _reconcile_lock:
        with _lock:
            pos = _positions.get(trade_id)
            snapshot = dict(pos) if pos else None
        if snapshot is None:
            return {"id": trade_id, "outcome": "gone", "closed": False, "gap_s": 0}
        now = time.time()
        since = max(snapshot.get("last_ok_ts") or 0, snapshot.get("opened_at_ts") or 0)
        gap = now - since
        base = {"id": trade_id, "symbol": snapshot["symbol"], "side": snapshot["action"], "gap_s": gap}
        if gap < GAP_RECONCILE_S and not force:
            return {**base, "outcome": "open", "closed": False, "skipped": True}
        n = min(600, int(gap // (exchange.GRANULARITY_MIN * 60)) + 3)
        try:
            candles = exchange.get_klines(snapshot["symbol"], limit=n, fast=True)
        except Exception as e:
            print(f"[Reconcile] candle fetch failed for {snapshot['symbol']}: {e}")
            return None
        scalp_target = float(settings_store.get("scalp_close_roi_pct", 0.0) or 0.0)
        outcome, hits, best, worst, extra = _evaluate_candles(snapshot, candles, scalp_target, since)
        # A real catch-up happened: this trade's peak/drawdown now come from 5m
        # candles, not live ticks -> tag it, and apply the breakeven shift the
        # live loop missed. Done BEFORE a possible close so the close sees it.
        with _lock:
            live = _positions.get(trade_id)
            if live is not None:
                live["restart_affected"] = True
                for _k, _v in (extra.get("sd") or {}).items():
                    if _k.startswith("sd_") and _v is not None:
                        live[_k] = _v
                _ts = extra.get("trail_sl")
                if _ts is not None:
                    _cur_sl, _ = _effective_levels(live)
                    if _sl_tightens(_cur_sl, _ts, live["action"] == "BUY"):
                        live["trailed_sl"] = _ts
                        status.add_alert_paper(
                            "auto",
                            f"Trailing stop (catch-up): #{trade_id} {live['symbol']} TP levels were hit while "
                            f"the bot was away - SL moved to {_ts:g}",
                            bot=live.get("bot") or "b1", trade_id=trade_id,
                        )
                if extra.get("be_shift") and not live.get("breakeven_auto_shifted"):
                    live["trailed_sl"] = live.get("entry_price")
                    live["breakeven_auto_shifted"] = True
                    status.add_alert_paper(
                        "auto",
                        f"Breakeven auto-shift (catch-up): #{trade_id} {live['symbol']} TP1 was hit while "
                        f"the bot was away - SL moved to entry ({live.get('entry_price'):g})",
                        bot=live.get("bot") or "b1", trade_id=trade_id,
                    )
        if outcome:
            _close_position(trade_id, outcome["reason"], outcome["exit_price"],
                            note=outcome["note"], recovered=True)
            return {**base, "outcome": "closed", "closed": True, "reason": outcome["reason"],
                    "exit": outcome["exit_price"], "candles": len(candles)}
        with _lock:
            live = _positions.get(trade_id)
            if live is not None:
                live["tp_hit_levels"] = hits
                live["max_roi_pct"] = best
                live["min_roi_pct"] = worst
                live["last_ok_ts"] = time.time()
        _save()
        return {**base, "outcome": "open", "closed": False, "candles": len(candles)}


_TRIGGER_LABELS = {
    "restart": "after bot restart",
    "gap": "after data gap",
    "reconnect": "after app reconnect",
    "manual": "manual check",
}


def _report_reconcile(trigger, results):
    """One summary per catch-up round: status.last_reconcile (Dashboard) and,
    when it matters, one 'sync' alert with the per-trade outcomes."""
    results = [r for r in results if r and r.get("outcome") != "gone" and not r.get("skipped")]
    if not results:
        return
    n = len(results)
    closed = [r for r in results if r.get("closed")]
    gap = max(r.get("gap_s", 0) for r in results)
    status.update(last_reconcile={
        "ts": time.time(), "trigger": trigger, "gap_s": gap,
        "checked": n, "closed": len(closed), "still_open": n - len(closed),
    })
    if closed or gap >= 120 or trigger in ("restart", "reconnect", "manual"):
        label = _TRIGGER_LABELS.get(trigger, trigger)
        text = (f"Catch-up ({label}): checked {n} open trade(s) over a {_fmt_duration(gap)} gap - "
                f"{len(closed)} closed while away, {n - len(closed)} still open")
        status.add_alert_paper("sync", text, kind="catchup", trigger=trigger, gap_s=gap,
                         checked=n, closed=len(closed), still_open=n - len(closed),
                         items=[{"id": r.get("id"), "symbol": r.get("symbol"), "side": r.get("side"),
                                 "outcome": r.get("outcome"), "reason": r.get("reason"),
                                 "exit": r.get("exit")} for r in results])


def reconcile_all(trigger="manual", force=True):
    """Catch-up check for every open position - called by POST /api/reconcile
    (the app hits it right after its live connection comes back) and safe to
    call any time. Returns the summary dict."""
    with _lock:
        ids = list(_positions.keys())
    results = [reconcile_position(tid, trigger=trigger, force=force) for tid in ids]
    ok = [r for r in results if r is not None]
    _report_reconcile(trigger, ok)
    return {
        "checked": len(ok),
        "closed": len([r for r in ok if r.get("closed")]),
        "failed": len(results) - len(ok),
        "still_open": len([r for r in ok if not r.get("closed")]),
    }


def paper_trade_monitor_loop():
    print("[PaperTrade] Monitor loop started")
    first_tick = True
    while True:
        try:
            _push_today_stats()
            scalp_target = float(settings_store.get("scalp_close_roi_pct", 0.0) or 0.0)
            with _lock:
                ids = list(_positions.keys())
            gap_results = []
            gap_trigger = "restart" if first_tick else "gap"
            for tid in ids:
                with _lock:
                    pos = _positions.get(tid)
                if not pos:
                    continue
                price, source, price_error = market_ws.get_best_live_price(pos["symbol"])
                if source == "REST_FALLBACK":
                    # Minor throttle: when the price feed is down/stale, every
                    # open position falls back to its own individual REST
                    # call once per loop tick - a tiny stagger caps that.
                    time.sleep(0.15)
                if price is None:
                    # Never act on a stale/guessed price - skip this position
                    # this cycle, try again next tick. last_ok_ts is NOT
                    # advanced, so the outage is caught up once data returns.
                    status.update(market_data_error=price_error)
                    continue
                now = time.time()
                ref_ts = pos.get("last_ok_ts") or pos.get("opened_at_ts") or now
                if now - ref_ts > GAP_RECONCILE_S and now >= _reconcile_retry_at.get(tid, 0):
                    res = reconcile_position(tid, trigger=gap_trigger)
                    if res is None:
                        _reconcile_retry_at[tid] = now + 15
                    else:
                        _reconcile_retry_at.pop(tid, None)
                        gap_results.append(res)
                        if res.get("closed"):
                            continue
                    with _lock:
                        pos = _positions.get(tid)
                    if not pos:
                        continue
                ltp = price
                roi = _calc_roi(pos, ltp)
                pnl = pos["invest_usdt"] * (roi / 100.0)
                with _lock:
                    if tid in _positions:
                        p = _positions[tid]
                        p.update(ltp=ltp, roi_pct=roi, pnl_usdt=pnl, price_source=source,
                                 last_ok_ts=now)
                        if roi > (p.get("max_roi_pct") or 0.0):
                            p["max_roi_pct"] = roi
                        if roi < (p.get("min_roi_pct") or 0.0):
                            p["min_roi_pct"] = roi
                        _update_sd_path(p, ltp)
                # _effective_levels() returns the strategy's own SL/TP1-4 if
                # this position has them, else synthesizes TP1/TP2/SL from
                # this position's own tp_value/sl_value% around its entry.
                sig_sl, tps = _effective_levels(pos)
                if ai_path_logger is not None:
                    ai_path_logger.tick(pos, roi, sig_sl, tps)
                is_long_for_hits = pos["action"] == "BUY"
                newly_hit = []
                for lvl in (1, 2, 3, 4):
                    lvl_price = tps.get(lvl)
                    if lvl_price is None or lvl in pos.get("tp_hit_levels", []):
                        continue
                    reached = (ltp >= lvl_price) if is_long_for_hits else (ltp <= lvl_price)
                    if reached:
                        newly_hit.append(lvl)
                if newly_hit:
                    with _lock:
                        if tid in _positions:
                            hits = list(_positions[tid].get("tp_hit_levels", []))
                            for lvl in newly_hit:
                                if lvl not in hits:
                                    hits.append(lvl)
                            _positions[tid]["tp_hit_levels"] = hits
                            # When TP1 was FIRST touched - lets the AI measure how
                            # fast a trade got profit (fast vs sideways). Set once.
                            for _lvl in newly_hit:
                                if not _positions[tid].get(f"tp{_lvl}_ts"):
                                    _positions[tid][f"tp{_lvl}_ts"] = time.time()
                # TP EXECUTION MODE: "Strategy TP" auto breakeven-shift.
                # Universal ROI % mode (scalp_target > 0) closes the
                # whole position flat the moment its target ROI is hit,
                # so there's no SL to manage - this only applies while
                # the position is following the Pine Script / SD-level
                # ladder. Tighten-only, same guard as the manual
                # "SL -> BE" button, so this can never loosen a SL a
                # user already trailed further out via a TP tap.
                # Runs whenever TP1 is on record (not only the tick it is first
                # touched): after a restart/catch-up TP1 is already recorded, so
                # waiting for "newly hit" meant the shift never happened.
                _t_mode = _trail_mode()
                if scalp_target <= 0 and _t_mode != "off":
                    # TRAILING STEPS (step1 / step2) - see the trail_mode block above.
                    with _lock:
                        live = _positions.get(tid)
                        if live is not None:
                            _hits_now = set(live.get("tp_hit_levels") or [])
                            _cur_sl, _tps_t = _effective_levels(live)
                            _want = _trail_floor_price(_t_mode, live.get("entry_price"), _tps_t, _hits_now)
                            if _sl_tightens(_cur_sl, _want, is_long_for_hits):
                                live["trailed_sl"] = _want
                                live["trail_step"] = _trail_step_reached(_hits_now)
                                status.add_alert_paper(
                                    "auto",
                                    f"Trailing stop: #{tid} {live['symbol']} TP{live['trail_step']} hit - "
                                    f"SL moved to {_want:g}",
                                    bot=live.get("bot") or "b1", trade_id=tid,
                                )
                elif scalp_target <= 0 and (1 in newly_hit or 1 in (pos.get("tp_hit_levels") or [])):
                    with _lock:
                        live = _positions.get(tid)
                        if live is not None and not live.get("breakeven_auto_shifted"):
                            entry_px = live.get("entry_price")
                            cur_sl, _tps_be = _effective_levels(live)
                            if entry_px is not None:
                                tightens = cur_sl is None or (
                                    (entry_px > cur_sl) if is_long_for_hits else (entry_px < cur_sl)
                                )
                                if tightens:
                                    live["trailed_sl"] = entry_px
                                    live["breakeven_auto_shifted"] = True
                                    status.add_alert_paper(
                                        "auto",
                                        f"Breakeven auto-shift: #{tid} {live['symbol']} TP1 hit - "
                                        f"SL moved to entry ({entry_px:g})",
                                        bot=live.get("bot") or "b1", trade_id=tid,
                                    )
                is_long = pos["action"] == "BUY"
                # Universal TP % (scalp_close_roi_pct): checked BEFORE the
                # signal's own SL/TP levels, per position, on its own
                # leverage-adjusted roi_pct.
                if scalp_target > 0 and roi >= scalp_target:
                    _close_position(tid, "SCALP_TARGET", ltp); continue
                if sig_sl is not None and any(v is not None for v in tps.values()):
                    hit_sl = (ltp <= sig_sl) if is_long else (ltp >= sig_sl)
                    if hit_sl:
                        _close_position(tid, "SL", ltp); continue
                    default_target = max(lvl for lvl, price in tps.items() if price is not None)
                    target_level = pos.get("user_target_tp") or default_target
                    target_price = tps.get(target_level)
                    if target_price is not None:
                        hit_tp = (ltp >= target_price) if is_long else (ltp <= target_price)
                        if hit_tp:
                            if pos.get("user_target_tp") and _stale_target_level(tps, target_level, ltp, is_long):
                                _close_position(tid, "SL", ltp); continue
                            reason = f"TP{target_level}_TARGET" if pos.get("user_target_tp") else f"TP{target_level}"
                            _close_position(tid, reason, ltp); continue
                else:
                    if pnl >= pos["tp_value"]:
                        _close_position(tid, "TP", ltp); continue
                    if pnl <= -pos["sl_value"]:
                        _close_position(tid, "SL", ltp); continue
            if gap_results:
                _report_reconcile(gap_trigger, gap_results)
            first_tick = False if ids else first_tick
            _save()
            _refresh_status_positions()
        except Exception as e:
            print(f"[PaperTrade] Monitor error: {e}")
        time.sleep(1)
