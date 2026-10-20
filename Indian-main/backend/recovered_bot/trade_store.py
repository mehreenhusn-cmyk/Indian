import atexit
import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta

# Shared telemetry builder (session tag, peak ROI, worst drawdown, duration,
# clean exit reason) - same enrichment ai_data_logger.py writes to its CSV,
# reused here so the rolling closed-trade cache and the CSV always agree.
# Safe direction of import: ai_data_logger has no dependency back on this
# module, so no circular-import risk.
from . import ai_data_logger
from . import safe_io
from . import settings_store

_lock = threading.Lock()
_file = None
_data = {
    "date": None,           # trading-day key this data belongs to (see _today_utc below)
    "today_pnl_usdt": 0.0,
    "total_trades": 0,
    "wins": 0,
    "closed_trades": [],    # capped history, most recent last
    "signal_count_today": 0,
    # Compact [close_ts, pnl_usdt] ledger used ONLY for equity curves. The
    # full closed_trades list is capped (MAX_HISTORY) and used to be the
    # equity source, so with ~100 trades/day a "7d" curve silently only
    # covered the last ~2 days. This ledger is tiny per entry, so it can
    # hold weeks of trades.
    "pnl_events": [],
}
MAX_HISTORY = 1500
MAX_PNL_EVENTS = 40000

# ---- BOT 2 (past-8-days coins) -------------------------------------------------
# Bot 2 trades are kept completely apart from Bot 1: own counters, own closed list,
# own P&L ledger and own archive file, so Bot 1's numbers, daily limits and every AI
# module that reads Bot 1's archive are never touched. Every public function below
# takes bot="b1" (default = exactly the old behaviour) or bot="b2".
_B2_KEY = "b2"


def _bk(bot):
    return _B2_KEY if str(bot or "b1").lower() == "b2" else "b1"


def _b2():
    """Bot 2's bucket inside _data (caller must hold _lock)."""
    b = _data.get(_B2_KEY)
    if not isinstance(b, dict):
        b = {}
        _data[_B2_KEY] = b
    for k, v in (("date", None), ("today_pnl_usdt", 0.0), ("total_trades", 0), ("wins", 0),
                 ("signal_count_today", 0)):
        b.setdefault(k, v)
    b.setdefault("closed_trades", [])
    b.setdefault("pnl_events", [])
    return b


def _bucket(bot):
    """Counters/lists for a bot (caller must hold _lock): _data itself for Bot 1."""
    return _b2() if _bk(bot) == "b2" else _data

# Mirrors app.py's _current_trading_day_key(): the user's trading day rolls
# over at 5:30 AM IST, not UTC midnight. This used to be a plain UTC-midnight
# date here while app.py's Market Watch gainers/losers already used the 5:30
# AM IST boundary - the two disagreed for the ~5.5 hour window between UTC
# midnight and 5:30 AM IST, so Today's P&L could reset at a different moment
# than the gainers/losers "today" did. Kept as a local copy (not imported
# from app.py) to avoid a circular import - app.py already imports this module.
_IST_OFFSET = timedelta(hours=5, minutes=30)
_DAY_RESET_HOUR, _DAY_RESET_MINUTE = 5, 30


def _today_utc():
    ist_dt = datetime.now(timezone.utc) + _IST_OFFSET
    reset_today = ist_dt.replace(hour=_DAY_RESET_HOUR, minute=_DAY_RESET_MINUTE, second=0, microsecond=0)
    trading_date = ist_dt.date() if ist_dt >= reset_today else (ist_dt - timedelta(days=1)).date()
    return trading_date.isoformat()


_archive = None   # append-only closed-trade history (never capped, never rewritten)
_archive_b2 = None


def init(path):
    global _file, _archive, _archive_b2
    _file = path
    _archive = os.path.join(os.path.dirname(path) or ".", "closed_trades_archive.jsonl") if path else None
    _archive_b2 = os.path.join(os.path.dirname(path) or ".", "closed_trades_archive_b2.jsonl") if path else None
    _load()
    _recover_from_archive()
    _check_rollover()


def _tkey(t):
    return f"{t.get('id')}|{t.get('closed_at_ts')}"


def _archive_append(trade, bot="b1"):
    """One JSON line per closed trade, appended forever. This is the long-term
    memory the AI learns from: trades.json is capped at MAX_HISTORY and can be
    lost on a wrong copy, this file is only ever appended to. Bot 2 trades go to
    their own file so the AI archive stays Bot-1-only."""
    target = _archive_b2 if _bk(bot) == "b2" else _archive
    if not target:
        return
    try:
        with open(target, "a") as f:
            f.write(json.dumps(trade, default=str) + "\n")
    except Exception as e:
        print(f"[trade_store] archive append failed: {e}")


def _trading_day_start_ts():
    ist_dt = datetime.now(timezone.utc) + _IST_OFFSET
    reset = ist_dt.replace(hour=_DAY_RESET_HOUR, minute=_DAY_RESET_MINUTE, second=0, microsecond=0)
    if ist_dt < reset:
        reset -= timedelta(days=1)
    return (reset - _IST_OFFSET).timestamp()


def _recover_from_archive():
    """Startup: merge any archived trade that is missing from trades.json
    (fresh/lost/short trades.json after a new build) back into the history, and
    - only if something was merged - rebuild today's counters from it. Also the
    one-time import for installs that have trades.json but no archive yet.
    Never raises."""
    if not _archive:
        return
    try:
        with _lock:
            have = {_tkey(t) for t in _data.get("closed_trades", [])}
            existing = list(_data.get("closed_trades", []))
        if not os.path.exists(_archive):
            for t in existing:          # first run with archive: seed it from trades.json
                _archive_append(t)
            return
        archived = []
        with open(_archive, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    archived.append(json.loads(line))
                except Exception:
                    continue
        seen = {_tkey(t) for t in archived}
        for t in existing:              # trades.json has trades the archive never saw
            if _tkey(t) not in seen:
                _archive_append(t)
                archived.append(t)
        missing = [t for t in archived if _tkey(t) not in have]
        if not missing:
            return
        with _lock:
            merged = existing + missing
            merged.sort(key=lambda t: float(t.get("closed_at_ts") or 0))
            _data["closed_trades"] = merged[-MAX_HISTORY:]
            ledger = {round(float(e[0]), 3) for e in _data.get("pnl_events", [])}
            events = _data.setdefault("pnl_events", [])
            for t in missing:
                ts = t.get("closed_at_ts")
                if ts and round(float(ts), 3) not in ledger:
                    events.append([float(ts), float(t.get("pnl_usdt", 0.0) or 0.0)])
            events.sort(key=lambda e: e[0])
            day0 = _trading_day_start_ts()
            today = [t for t in _data["closed_trades"] if float(t.get("closed_at_ts") or 0) >= day0]
            _data["date"] = _today_utc()
            _data["today_pnl_usdt"] = sum(float(t.get("pnl_usdt", 0.0) or 0.0) for t in today)
            _data["total_trades"] = len(today)
            _data["wins"] = sum(1 for t in today if float(t.get("pnl_usdt", 0.0) or 0.0) > 0)
        print(f"[trade_store] recovered {len(missing)} trades from archive")
        _save()
    except Exception as e:
        print(f"[trade_store] archive recovery skipped: {e}")


def _load():
    if not _file:
        with _lock:
            _data["date"] = _today_utc()
        return
    saved, _src = safe_io.read_json_safe(_file, "trades")
    if not isinstance(saved, dict):
        with _lock:
            _data["date"] = _today_utc()
        return
    with _lock:
        _data.update(saved)
        if not _data.get("pnl_events"):
            # Older data file: backfill the ledger from whatever closed
            # trades we still have.
            _data["pnl_events"] = [
                [t["closed_at_ts"], float(t.get("pnl_usdt", 0.0) or 0.0)]
                for t in _data.get("closed_trades", [])
                if t.get("closed_at_ts")
            ]
    if _src == "backup":
        _save()  # put a good main file back right away


# Saves are coalesced onto ONE background writer thread: trades.json can hold
# tens of thousands of P&L events, and rewriting it synchronously on every
# close made Close All / TP / SL exits slow (each close waited for a full
# file rewrite). Now a close only marks the data dirty; the writer writes the
# latest state ~0.3s later, atomically (see safe_io). atexit flushes on a
# clean shutdown.
_SAVE_DELAY_S = 0.3
_dirty = False
_writer_running = False
_writer_lock = threading.Lock()


def _write_now():
    global _dirty
    if not _file:
        return
    try:
        with _lock:
            text = json.dumps(_data)
            _dirty = False
        safe_io.write_json_atomic(_file, text)
    except Exception as e:
        _dirty = True
        print(f"[trade_store] SAVE FAILED: {e}")


def _writer_loop():
    global _writer_running
    while True:
        time.sleep(_SAVE_DELAY_S)
        if _dirty:
            _write_now()
        with _writer_lock:
            if not _dirty:
                _writer_running = False
                return


def _save():
    global _dirty, _writer_running
    if not _file:
        return
    _dirty = True
    with _writer_lock:
        if _writer_running:
            return
        _writer_running = True
    threading.Thread(target=_writer_loop, daemon=True).start()


def flush():
    """Write any pending change right now (used on shutdown)."""
    if _dirty:
        _write_now()


atexit.register(flush)


def reset():
    """Reset all trade history and today's stats."""
    with _lock:
        _data["today_pnl_usdt"] = 0.0
        _data["total_trades"] = 0
        _data["wins"] = 0
        _data["closed_trades"] = []
        _data["pnl_events"] = []
        _data["date"] = _today_utc()
    # An explicit reset must not be undone by the startup archive recovery:
    # the old archive is kept aside (renamed), not deleted.
    try:
        if _archive and os.path.exists(_archive):
            os.replace(_archive, f"{_archive}.reset-{int(time.time())}")
    except OSError:
        pass
    _save()


def _check_rollover():
    """Reset today's P&L/trades/wins when the trading day rolls over at
    5:30 AM IST - matches app.py's Market Watch trading-day boundary, not
    just app restart."""
    today = _today_utc()
    with _lock:
        changed = _data.get("date") != today
        if changed:
            _data["date"] = today
            _data["today_pnl_usdt"] = 0.0
            _data["total_trades"] = 0
            _data["wins"] = 0
            _data["signal_count_today"] = 0
        b = _b2()
        if b.get("date") != today:
            b["date"] = today
            b["today_pnl_usdt"] = 0.0
            b["total_trades"] = 0
            b["wins"] = 0
            b["signal_count_today"] = 0
            changed = True
    if changed:
        _save()
    return changed


def _sanitize_closed_trade(pos):
    """JSON-safe copy of a just-closed position for the rolling cache, with
    ai_data_logger's enrichment (session tag, peak ROI%, worst drawdown%,
    duration in minutes, clean exit reason) merged in. Every field the
    History UI already reads (symbol/side/entry/exit/roi_pct/pnl_usdt/
    opened_at/closed_at/duration_s/...) is kept as-is - this only rounds
    noisy floats and adds the new telemetry keys, never removes anything."""
    try:
        clean = dict(pos)
        for k in ("roi_pct", "pnl_usdt", "max_roi_pct", "min_roi_pct", "entry_price", "ltp"):
            v = clean.get(k)
            if isinstance(v, float):
                clean[k] = round(v, 4)
        clean.update(ai_data_logger.build_close_telemetry(pos))
        return clean
    except Exception:
        # Never let cache enrichment break the actual close/record path -
        # fall back to the raw position, same as before this change.
        return dict(pos)


def record_close(pos):
    """Call when a paper trade closes. pos must have pnl_usdt."""
    _check_rollover()
    pnl = float(pos.get("pnl_usdt", 0.0))
    enriched = _sanitize_closed_trade(pos)
    bot = _bk(pos.get("bot"))
    with _lock:
        b = _bucket(bot)
        b["today_pnl_usdt"] += pnl
        b["total_trades"] += 1
        if pnl > 0:
            b["wins"] += 1
        b["closed_trades"].append(enriched)
        b["closed_trades"] = b["closed_trades"][-MAX_HISTORY:]
        _archive_append(enriched, bot)
        ts = pos.get("closed_at_ts")
        if ts:
            events = b.setdefault("pnl_events", [])
            events.append([float(ts), pnl])
            if len(events) > MAX_PNL_EVENTS:
                del events[:len(events) - MAX_PNL_EVENTS]
    _save()


def bump_signal_count(bot="b1"):
    """Increment and persist today's signal counter. Persisted to disk (unlike
    a plain in-memory variable) so restarting the app mid-day doesn't reset
    numbering back to #1 and collide with signal numbers already used earlier
    that day for currently-open or already-closed positions."""
    _check_rollover()
    with _lock:
        b = _bucket(bot)
        b["signal_count_today"] += 1
        count = b["signal_count_today"]
    _save()
    return count


def get_today_stats(bot="b1"):
    _check_rollover()
    with _lock:
        b = _bucket(bot)
        total = b["total_trades"]
        wins = b["wins"]
        return {
            "today_pnl_usdt": b["today_pnl_usdt"],
            "total_trades": total,
            "win_rate": (wins / total * 100.0) if total else 0.0,
            "wins": wins,
            "losses": total - wins,
            "signal_count_today": b["signal_count_today"],
        }


_period_cache = {"ts": 0.0, "key": None, "val": None}
_period_cache_b2 = {"ts": 0.0, "key": None, "val": None}


def get_period_stats(bot="b1"):
    """Closed-trade P&L for the Today / 7D / 30D row (same 5:30 AM IST trading-day boundary as Today).
    Rolling windows made of whole trading days: 7D = today + the 6 days before it, 30D = today + 29 before.
    Built from pnl_events (every close, already net of fee), cached ~5 s because the status feed asks every second."""
    import time as _t
    start = _trading_day_start_ts()
    now = _t.time()
    with _lock:
        n_events = len(_bucket(bot).get("pnl_events", []))
    key = (start, n_events, _live_view_on())
    c = _period_cache_b2 if _bk(bot) == "b2" else _period_cache
    if c["val"] is not None and c["key"] == key and now - c["ts"] < 5.0:
        return c["val"]
    s7 = start - 6 * 86400
    s30 = start - 29 * 86400
    out = {"today_pnl": 0.0, "today_trades": 0, "d7_pnl": 0.0, "d7_trades": 0, "d30_pnl": 0.0, "d30_trades": 0}
    for ts, pnl in _events(bot, True):
        try:
            ts = float(ts)
            pnl = float(pnl)
        except Exception:
            continue
        if ts >= s30:
            out["d30_pnl"] += pnl
            out["d30_trades"] += 1
            if ts >= s7:
                out["d7_pnl"] += pnl
                out["d7_trades"] += 1
                if ts >= start:
                    out["today_pnl"] += pnl
                    out["today_trades"] += 1
    for k in ("today_pnl", "d7_pnl", "d30_pnl"):
        out[k] = round(out[k], 4)
    c.update(ts=now, key=key, val=out)
    return out


def get_recent_closed(limit=50, net=False, bot="b1", live_view=False):
    """Most recent closed trades first, for the History tab in Positions screen.
    net=True (AI use) takes the exchange fee off older paper trades too.
    live_view=True (screens only): in LIVE mode return REAL trades only, no paper rows."""
    with _lock:
        src = _bucket(bot)["closed_trades"]
        if live_view and _live_view_on() and _bk(bot) != "b2":
            src = [t for t in src if _is_live_trade(t)]
        rows = list(reversed(src[-limit:]))
    return [net_view(t) for t in rows] if net else rows


def net_view(t):
    """Copy of a closed trade with the exchange fee taken off (ROI % and USDT).
    Trades closed after the fee feature already carry it (fee_applied) and live
    trades carry the REAL Binance fee, so both pass through unchanged. Older
    paper trades had NO fee: for the AI they get the same fee as an ESTIMATE
    (fee_est=True). The stored archive is never rewritten."""
    try:
        if t.get("fee_applied") or t.get("source") == "live" or t.get("fee_est"):
            return t
        fee = float(settings_store.get("fee_roi_pct", 1.0) or 0.0)
        if fee <= 0:
            return t
        n = dict(t)
        roi = float(t.get("roi_pct") or 0.0)
        inv = float(t.get("invest_usdt") or 0.0)
        n.update(gross_roi_pct=roi, roi_pct=roi - fee, fee_roi_pct=fee, fee_est=True,
                 fee_usdt=inv * fee / 100.0,
                 pnl_usdt=float(t.get("pnl_usdt") or 0.0) - inv * fee / 100.0)
        return n
    except Exception:
        return t


_arch_cache = {"sig": None, "rows": None}
_arch_cache_lock = threading.Lock()


def get_all_closed(limit=5000, net=True, live_view=False):
    """Oldest -> newest closed trades from the permanent archive (falls back to
    the rolling cache). For AI cycle/regime statistics only."""
    try:
        if _archive and os.path.exists(_archive):
            st = os.stat(_archive)
            sig = (st.st_mtime_ns, st.st_size)
            with _arch_cache_lock:
                hit = _arch_cache if _arch_cache.get("sig") == sig else None
            out = hit["rows"] if hit else None
            if out is None:                      # parse once per archive change, not once per call
                out = []
                with open(_archive, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                out.append(json.loads(line))
                            except Exception:
                                pass
                out.sort(key=lambda t: float(t.get("closed_at_ts") or 0))
                with _arch_cache_lock:
                    _arch_cache.update(sig=sig, rows=out)
            if out:
                if live_view and _live_view_on():
                    out = [t for t in out if _is_live_trade(t)]
                part = [dict(t) for t in out[-limit:]]   # copies: callers may edit their rows
                return [net_view(t) for t in part] if net else part
    except Exception:
        pass
    with _lock:
        rows = list(_data["closed_trades"][-limit:])
    return [net_view(t) for t in rows] if net else rows


def get_audit_summary(limit=50):
    """Lightweight trade-audit summary, computed from the same enriched
    rolling cache get_recent_closed() already serves - powers
    GET /api/ai/trade-audit-context (api_server.py) and the AI Assistant's
    strategy/mistake-analysis context (ai_assistant.py). Pure read, no
    state change, never raises."""
    trades = get_recent_closed(limit)  # most-recent-first
    if not trades:
        return {
            "sample_size": 0,
            "current_streak": {"type": None, "count": 0},
            "best_session": None,
            "session_pnl": {},
            "common_exit_triggers": [],
        }

    # Current streak: walk from the most recent trade backwards while the
    # win/loss sign keeps matching the most recent trade's own result.
    streak_type = "win" if float(trades[0].get("pnl_usdt", 0.0) or 0.0) > 0 else "loss"
    streak_count = 0
    for t in trades:
        is_win = float(t.get("pnl_usdt", 0.0) or 0.0) > 0
        if (is_win and streak_type == "win") or (not is_win and streak_type == "loss"):
            streak_count += 1
        else:
            break

    session_pnl = {}
    session_count = {}
    exit_counts = {}
    for t in trades:
        sess = t.get("session_tag", "Unknown")
        session_pnl[sess] = session_pnl.get(sess, 0.0) + float(t.get("pnl_usdt", 0.0) or 0.0)
        session_count[sess] = session_count.get(sess, 0) + 1
        exit_r = t.get("clean_exit_reason", "UNKNOWN")
        exit_counts[exit_r] = exit_counts.get(exit_r, 0) + 1

    best_session = None
    if session_pnl:
        best_session = max(session_pnl, key=lambda s: session_pnl[s] / session_count[s])

    common_exit_triggers = sorted(exit_counts.items(), key=lambda kv: -kv[1])

    return {
        "sample_size": len(trades),
        "current_streak": {"type": streak_type, "count": streak_count},
        "best_session": best_session,
        "session_pnl": {k: round(v, 2) for k, v in session_pnl.items()},
        "common_exit_triggers": [{"reason": r, "count": c} for r, c in common_exit_triggers],
    }


def _trading_day_key_for_ts(ts):
    """Same 5:30 AM IST trading-day boundary as _today_utc(), but for an
    arbitrary past timestamp instead of 'now' - used to group closed trades
    by the trading day they actually closed on, for the equity curve."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc) + _IST_OFFSET
    reset_today = dt.replace(hour=_DAY_RESET_HOUR, minute=_DAY_RESET_MINUTE, second=0, microsecond=0)
    trading_date = dt.date() if dt >= reset_today else (dt - timedelta(days=1)).date()
    return trading_date.isoformat()


def _live_view_on():
    """True while the app is in LIVE mode: screens must then show REAL (Binance) trades only."""
    try:
        return bool(settings_store.get("live_trading_enabled", False))
    except Exception:
        return False


def _is_live_trade(t):
    return str(t.get("source") or "").lower() == "live"


def _live_events():
    """[ts, pnl] of every REAL (source=live) closed trade, rebuilt from the permanent archive."""
    out = []
    try:
        for t in get_all_closed(8000, net=False):
            if _is_live_trade(t):
                try:
                    out.append([float(t.get("closed_at_ts") or 0), float(t.get("pnl_usdt") or 0)])
                except Exception:
                    pass
    except Exception:
        pass
    return out


def _events(bot="b1", live_view=False):
    if live_view and _live_view_on() and _bk(bot) != "b2":
        return _live_events()
    with _lock:
        return list(_bucket(bot).get("pnl_events", []))


def get_equity_curve(days=30, bot="b1"):
    """Daily realized P&L + running cumulative total for the Dashboard equity
    curve. Buckets every closed trade by the trading day it closed on (5:30 AM
    IST boundary, same as Today's P&L) and returns EXACTLY the last `days`
    trading days ending today - days with no trades are included as 0 so the
    x-axis is continuous - preceded by a 0 "start" point, so even a single
    trading day always yields a drawable line (a 1-point series draws
    nothing, which is why the chart used to look empty).

    [{"date": "YYYY-MM-DD" | "start", "pnl": day_total, "cumulative": running_total}, ...]"""
    days = max(1, int(days))
    daily = {}
    for ts, pnl in _events(bot, True):
        day = _trading_day_key_for_ts(ts)
        daily[day] = daily.get(day, 0.0) + float(pnl)

    today = datetime.fromisoformat(_today_utc()).date()
    window = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]

    running = 0.0
    curve = [{"date": "start", "pnl": 0.0, "cumulative": 0.0}]
    for day in window:
        pnl = daily.get(day, 0.0)
        running += pnl
        curve.append({"date": day, "pnl": pnl, "cumulative": running})
    return curve


def get_daily_calendar(month=None, bot="b1"):
    """Daily closed-trade P&L for one calendar month (Binance-style PNL calendar).
    Same pnl_events and same 5:30 AM IST trading-day boundary as Today / 7D / 30D,
    so a day here always equals what the Dashboard ring showed that day.
    month = "YYYY-MM" (default: the current trading month). Only days that had
    trades are listed; the app draws the empty days itself.
    {"month","today","first_month","month_pnl","month_trades","month_wins",
     "days":[{"date","pnl","trades","wins"}]}"""
    today = _today_utc()
    m = str(month or "")[:7]
    try:
        y, mo = int(m[:4]), int(m[5:7])
        if not (1 <= mo <= 12 and 2000 <= y <= 2100) or m[4] != "-":
            raise ValueError
    except Exception:
        m = today[:7]
    days = {}
    first = None
    for ts, pnl in _events(bot, True):
        try:
            key = _trading_day_key_for_ts(float(ts))
            pnl = float(pnl)
        except Exception:
            continue
        if first is None or key < first:
            first = key
        if key[:7] != m:
            continue
        d = days.setdefault(key, {"date": key, "pnl": 0.0, "trades": 0, "wins": 0})
        d["pnl"] += pnl
        d["trades"] += 1
        if pnl > 0:
            d["wins"] += 1
    rows = [days[k] for k in sorted(days)]
    for r in rows:
        r["pnl"] = round(r["pnl"], 4)
    return {
        "month": m,
        "today": today,
        "first_month": (first or today)[:7],
        "month_pnl": round(sum(r["pnl"] for r in rows), 4),
        "month_trades": sum(r["trades"] for r in rows),
        "month_wins": sum(r["wins"] for r in rows),
        "days": rows,
    }


def get_equity_curve_intraday(bucket_minutes=15, num_buckets=32, bot="b1"):
    """Same idea as get_equity_curve() but bucketed by a fixed-size time
    window (minutes) ending now - powers the 15m/1h/2h/1d options. Empty
    buckets still appear (pnl 0) so the x-axis stays evenly spaced.

    [{"date": "HH:MM" (IST), "pnl": bucket_total, "cumulative": running_total}, ...]"""
    bucket_seconds = max(1, bucket_minutes) * 60
    now_ts = datetime.now(timezone.utc).timestamp()
    start_ts = now_ts - bucket_seconds * num_buckets

    buckets = {}
    for ts, pnl in _events(bot, True):
        if ts < start_ts:
            continue
        idx = int((ts - start_ts) // bucket_seconds)
        if 0 <= idx < num_buckets:
            buckets[idx] = buckets.get(idx, 0.0) + float(pnl)

    running = 0.0
    curve = []
    for i in range(num_buckets):
        pnl = buckets.get(i, 0.0)
        running += pnl
        bucket_end = datetime.fromtimestamp(
            start_ts + (i + 1) * bucket_seconds, tz=timezone.utc
        ) + _IST_OFFSET
        curve.append({"date": bucket_end.strftime("%H:%M"), "pnl": pnl, "cumulative": running})
    return curve
