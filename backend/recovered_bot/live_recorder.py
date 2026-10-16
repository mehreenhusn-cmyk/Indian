"""
live_recorder.py - gives LIVE (real-money) Binance trades the same record a
paper trade gets, so History, "Today's P&L", the daily loss limit and the AI
Assistant all see them.

Before this module a live trade left no record at all: the bot knew a
position had disappeared but never saved how much it made or lost.

Flow
  1. app._open_live_trade() -> remember_open()   saves entry tags + signal levels
  2. guard loop, every few sec -> track_tick()    tracks best/worst ROI (MFE/MAE)
  3. guard / reconcile / manual close -> finalize_missing() / finalize_close()
        confirms the position is really flat, reads the REAL result from
        Binance (/fapi/v1/userTrades: realized P&L, fees, exit price), then
        calls trade_store.record_close() + ai_data_logger.log_trade_closed().

Safety
  - Every public function is wrapped in try/except and never raises into the
    trading code. A failure here only means a trade is not recorded.
  - A trade is recorded ONLY after a fresh Binance check says the position is
    flat (positionRisk == 0). A failed API call never counts as "closed".
  - Idempotent: a trade's context is removed once recorded, so it can never be
    counted twice (guard tick + reconcile + manual close can all call in).
  - If Binance trade history cannot be read after several tries, the trade is
    recorded from the last tracked price, flagged estimated=True.
"""
import threading
import time
from datetime import datetime

from . import settings_store, status, trade_store, ai_data_logger, safe_io

_lock = threading.Lock()
_file = None
_ctx = {}              # symbol -> open-trade context (persisted to disk)
_finalizing = set()    # symbols being finalized right now
_last_save = 0.0

_TOL = 0.0025          # exit within 0.25% of a level -> counts as that level
_FEE_ASSETS = ("USDT", "USDC", "BUSD")
_RETRY_DELAYS = (0, 2, 4, 8)   # seconds before each userTrades attempt
_MAX_ATTEMPTS = 6              # after this many failed finalize rounds -> estimate


def init(path):
    """path: directory for live_open_context.json (created if missing)."""
    global _file, _ctx
    try:
        import os
        os.makedirs(path, exist_ok=True)
        _file = os.path.join(path, "live_open_context.json")
        data, _src = safe_io.read_json_safe(_file, "live open context")
        with _lock:
            _ctx = data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[LiveRecorder] init failed (live trades will not be recorded): {e}")


def _save(force=False):
    global _last_save
    if not _file:
        return
    now = time.time()
    if not force and now - _last_save < 20:
        return
    try:
        with _lock:
            snap = dict(_ctx)
        safe_io.write_json_atomic(_file, snap)
        _last_save = now
    except Exception as e:
        print(f"[LiveRecorder] save failed: {e}")


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ open --

def remember_open(signal, symbol):
    """Call right after a live order is CONFIRMED filled."""
    try:
        now = time.time()
        action = str(signal.action).upper()
        ctx = {
            "symbol": symbol,
            "action": action,
            "opened_at_ts": now,
            "entry_price": _f(signal.entry_price),
            "invest_usdt": 0.0,      # real margin, filled in by track_tick()
            "leverage": _f(settings_store.get("live_leverage", 3), 1.0) or 1.0,
            "timeframe": settings_store.get("timeframe", "5m") or "5m",
            "signal_stop_loss": getattr(signal, "stop_loss", None),
            "signal_tp1": getattr(signal, "tp1", None),
            "signal_tp2": getattr(signal, "tp2", None),
            "signal_tp3": getattr(signal, "tp3", None),
            "signal_tp4": getattr(signal, "tp4", None),
            "entry_zone": getattr(signal, "entry_zone", None),
            "ema_slope_pct": getattr(signal, "ema_slope_pct", None),
            "volume_ratio": getattr(signal, "volume_ratio", None),
            "max_roi_pct": 0.0,
            "min_roi_pct": 0.0,
            "last_ltp": _f(signal.entry_price),
            "tp_hit_levels": [],
            "attempts": 0,
            "trade_id": f"LIVE-{symbol}-{int(now)}",
        }
        with _lock:
            _ctx[symbol] = ctx
        _save(force=True)
        # Same "features" CSV row a paper trade writes on open.
        pos_like = dict(ctx)
        pos_like["id"] = ctx["trade_id"]
        pos_like["opened_at"] = datetime.fromtimestamp(now).strftime("%H:%M:%S")
        pos_like["tp_mode"] = "exchange"
        ai_data_logger.log_trade_opened(pos_like)
    except Exception as e:
        print(f"[LiveRecorder] remember_open failed for {symbol}: {e}")


def track_tick(pos):
    """Call from the guard loop for every open Binance position (`pos` is one
    entry of binance_trader.get_open_positions()). Keeps real margin/entry
    and the best/worst ROI seen so far (MFE/MAE)."""
    try:
        symbol = pos.get("symbol")
        with _lock:
            ctx = _ctx.get(symbol)
            if not ctx:
                return
            if _f(pos.get("entry_price")) > 0:
                ctx["entry_price"] = _f(pos.get("entry_price"))
            if _f(pos.get("invest_usdt")) > 0:
                ctx["invest_usdt"] = _f(pos.get("invest_usdt"))
            if _f(pos.get("leverage")) > 0:
                ctx["leverage"] = _f(pos.get("leverage"))
            roi = _f(pos.get("roi_pct"))
            ctx["max_roi_pct"] = max(_f(ctx.get("max_roi_pct")), roi)
            ctx["min_roi_pct"] = min(_f(ctx.get("min_roi_pct")), roi)
            ltp = _f(pos.get("ltp"))
            if ltp > 0:
                ctx["last_ltp"] = ltp
                buy = ctx.get("action") == "BUY"
                hit = set(ctx.get("tp_hit_levels") or [])
                for n in (1, 2, 3, 4):
                    lvl = ctx.get(f"signal_tp{n}")
                    if lvl in (None, ""):
                        continue
                    if (buy and ltp >= _f(lvl)) or ((not buy) and ltp <= _f(lvl)):
                        hit.add(n)
                ctx["tp_hit_levels"] = sorted(hit)
        _save()
    except Exception:
        pass


# ----------------------------------------------------------------- close --

def finalize_missing(open_symbols):
    """Finalize every remembered trade whose symbol is not in `open_symbols`.
    Safe to call with a list built from a FAILED positions fetch - each trade
    is re-verified against Binance before anything is recorded."""
    try:
        with _lock:
            gone = [s for s in _ctx if s not in set(open_symbols or [])]
        for s in gone:
            finalize_close(s)
    except Exception:
        pass


def finalize_close(symbol, reason=None):
    """Record a closed live trade. Runs in a background thread so the guard
    loop / close button never wait on Binance. reason: e.g. "MANUAL"."""
    try:
        with _lock:
            if symbol not in _ctx or symbol in _finalizing:
                return
            _finalizing.add(symbol)
        threading.Thread(target=_finalize_worker, args=(symbol, reason), daemon=True).start()
    except Exception:
        pass


def _position_is_flat(symbol):
    """True only if Binance CONFIRMS zero position. Any error -> False."""
    from . import binance_trader
    rows = binance_trader._signed_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
    if not isinstance(rows, list):
        return False
    for p in rows:
        if p.get("symbol") == symbol and abs(_f(p.get("positionAmt"))) > 0:
            return False
    return True


def _fetch_trades(symbol, opened_ts):
    from . import binance_trader
    rows = binance_trader._signed_request(
        "GET", "/fapi/v1/userTrades",
        {"symbol": symbol, "startTime": int(opened_ts * 1000) - 5000, "limit": 1000},
    )
    return rows if isinstance(rows, list) else []


def _infer_reason(ctx, exit_price):
    """SL / TPn / EXCHANGE_CLOSE from where the exit price landed."""
    if exit_price <= 0:
        return "EXCHANGE_CLOSE"
    for n in (4, 3, 2, 1):
        lvl = ctx.get(f"signal_tp{n}")
        if lvl not in (None, "") and abs(exit_price - _f(lvl)) / _f(lvl) <= _TOL:
            return f"TP{n}"
    sl = ctx.get("signal_stop_loss")
    if sl not in (None, "") and abs(exit_price - _f(sl)) / _f(sl) <= _TOL:
        return "SL"
    entry = _f(ctx.get("entry_price"))
    if entry > 0 and ctx.get("tp_hit_levels") and abs(exit_price - entry) / entry <= 0.001:
        return "SL"   # stop was moved to breakeven after TP1
    return "EXCHANGE_CLOSE"


def _finalize_worker(symbol, reason):
    try:
        with _lock:
            ctx = dict(_ctx.get(symbol) or {})
        if not ctx:
            return

        # 1. Never record unless Binance confirms the position is flat.
        try:
            if not _position_is_flat(symbol):
                return
        except Exception as e:
            print(f"[LiveRecorder] {symbol}: could not confirm flat ({e}) - will retry later")
            return

        # 2. Read the real result from Binance trade history.
        opened_ts = _f(ctx.get("opened_at_ts"), time.time())
        action = ctx.get("action")
        close_side = "SELL" if action == "BUY" else "BUY"
        trades, closing = [], []
        for delay in _RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            try:
                trades = [t for t in _fetch_trades(symbol, opened_ts)
                          if _f(t.get("time")) >= opened_ts * 1000 - 5000]
            except Exception as e:
                print(f"[LiveRecorder] {symbol}: userTrades failed ({e})")
                trades = []
            closing = [t for t in trades if t.get("side") == close_side]
            if closing:
                break

        estimated = False
        if closing:
            gross = sum(_f(t.get("realizedPnl")) for t in trades)
            fees = sum(_f(t.get("commission")) for t in trades
                       if str(t.get("commissionAsset", "USDT")).upper() in _FEE_ASSETS)
            pnl = gross - fees
            cq = sum(_f(t.get("qty")) for t in closing)
            exit_price = (sum(_f(t.get("price")) * _f(t.get("qty")) for t in closing) / cq) if cq else 0.0
            opening = [t for t in trades if t.get("side") == action]
            oq = sum(_f(t.get("qty")) for t in opening)
            if oq:
                ctx["entry_price"] = sum(_f(t.get("price")) * _f(t.get("qty")) for t in opening) / oq
            closed_ts = max(_f(t.get("time")) for t in closing) / 1000.0
        else:
            # Could not read history yet. Retry on later ticks; after
            # _MAX_ATTEMPTS rounds fall back to an estimate from the last price.
            with _lock:
                live = _ctx.get(symbol)
                if live is not None:
                    live["attempts"] = int(live.get("attempts", 0)) + 1
                    attempts = live["attempts"]
                else:
                    attempts = 0
            if attempts < _MAX_ATTEMPTS:
                return
            estimated = True
            exit_price = _f(ctx.get("last_ltp"))
            entry = _f(ctx.get("entry_price"))
            lev = _f(ctx.get("leverage"), 1.0) or 1.0
            raw = 0.0
            if entry > 0 and exit_price > 0:
                raw = (exit_price - entry) / entry * 100.0
                raw = raw if action == "BUY" else -raw
            pnl = _f(ctx.get("invest_usdt")) * (raw * lev / 100.0)
            closed_ts = time.time()

        invest = _f(ctx.get("invest_usdt"))
        if invest <= 0:
            oq = sum(_f(t.get("qty")) for t in trades if t.get("side") == action)
            lev = _f(ctx.get("leverage"), 1.0) or 1.0
            invest = (oq * _f(ctx.get("entry_price")) / lev) if oq else 0.0
        roi = (pnl / invest * 100.0) if invest > 0 else 0.0

        why = reason or _infer_reason(ctx, exit_price)
        pos = dict(ctx)
        pos.update(
            id=ctx.get("trade_id"),
            status=f"CLOSED_{why}",
            close_reason=why,
            ltp=exit_price, exit_price=exit_price,
            invest_usdt=round(invest, 4),
            pnl_usdt=pnl, roi_pct=roi,
            opened_at=datetime.fromtimestamp(opened_ts).strftime("%H:%M:%S"),
            closed_at=datetime.fromtimestamp(closed_ts).strftime("%H:%M:%S"),
            closed_at_ts=closed_ts,
            duration_s=max(0.0, closed_ts - opened_ts),
            source="live",
            estimated=estimated,
        )

        # 3. Record it - exactly once.
        with _lock:
            if _ctx.pop(symbol, None) is None:
                return
        _save(force=True)
        trade_store.record_close(pos)
        try:
            status.update(**trade_store.get_today_stats())
        except Exception:
            pass
        try:
            ai_data_logger.log_trade_closed(pos, why)
        except Exception:
            pass
        atype = "sl" if why == "SL" else ("tp" if why.startswith("TP") else "manual")
        note = " (estimated - Binance history unreadable)" if estimated else ""
        status.add_signal(f"LIVE {why} {symbol} P&L {pnl:+.2f} USDT ({roi:+.2f}%)")
        status.add_alert(atype, f"LIVE CLOSED {symbol} {action} P&L {pnl:+.2f} USDT ({roi:+.2f}%) [{why}]{note}")
    except Exception as e:
        print(f"[LiveRecorder] finalize failed for {symbol}: {e}")
    finally:
        with _lock:
            _finalizing.discard(symbol)
