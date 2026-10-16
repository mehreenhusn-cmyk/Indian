"""
ai_data_logger.py - background CSV data collection for future ML/analysis.

Writes two CSVs, joinable on trade_id:
  ai_trade_features.csv  - one row the moment a trade OPENS (symbol, action,
                            entry price, SL/TP1-4 levels, invest/leverage,
                            time-of-day) - the "features" a model could later
                            learn from.
  ai_trade_outcomes.csv  - one row the moment a trade CLOSES (close reason,
                            exit price, pnl_usdt, roi_pct, duration) - the
                            "ground truth" label for that same trade_id.

Deliberately dumb and isolated: pure appends to disk, wrapped in try/except
everywhere, never raises into the caller. If this module breaks or the disk
is full, paper trading keeps working exactly as before - it just stops
collecting data. Not wired into the strategy/paper-trading decision path at
all, so it has zero effect on live behavior.
"""
import csv
import os
import threading
import time
from datetime import datetime, timezone

_lock = threading.Lock()
_data_dir = None
_features_file = None
_outcomes_file = None

_FEATURE_FIELDS = [
    "trade_id", "opened_at_ts", "opened_at", "symbol", "action",
    "entry_price", "invest_usdt", "leverage",
    "signal_stop_loss", "signal_tp1", "signal_tp2", "signal_tp3", "signal_tp4",
    "tp_mode", "tp_value", "sl_value", "hour_of_day", "day_of_week", "session_tag",
    # Entry context (strategy.py) - lets the AI see WHY a trade was taken.
    "timeframe", "entry_zone", "ema_slope_pct", "volume_ratio",
    # Market regime at entry (strategy._regime_context)
    "regime_cross_n", "atr_pct", "sd_width_pct",
    "ema_slope_prev_pct", "ema_slope10_pct", "ema_turn",
]

_OUTCOME_FIELDS = [
    "trade_id", "closed_at_ts", "closed_at", "symbol", "action",
    "close_reason", "exit_price", "pnl_usdt", "roi_pct",
    "duration_seconds", "tp_hit_levels",
    # Enriched telemetry (see build_close_telemetry below) - also reused
    # as-is by trade_store.py's rolling closed-trade cache, so the CSV
    # columns and the cache's JSON keys always agree.
    "session_tag", "peak_roi_pct", "worst_drawdown_pct",
    "duration_minutes", "clean_exit_reason",
    "timeframe", "entry_zone", "ema_slope_pct", "volume_ratio",
    # Data-quality tag (clean / recovered / reversed / outdated / restart_affected)
    # and the trade's SD path: where it entered (in SD units), the farthest SD
    # reached in favour (best) and against (worst), how far that is from entry,
    # which SD band that was, and how many minutes after entry it happened.
    "quality_tag", "sd_entry", "sd_best", "sd_worst", "sd_best_move", "sd_worst_move",
    "sd_best_band", "sd_worst_band", "sd_best_min", "sd_worst_min",
    # Speed + regime: minutes from entry to first TP1 touch (blank = never), and
    # the entry-time market-regime tags.
    "tp1_min", "tp2_min", "tp3_min", "tp4_min", "regime_cross_n", "atr_pct", "sd_width_pct",
    "ema_slope_prev_pct", "ema_slope10_pct", "ema_turn",
]

# UTC-hour trading sessions, per spec: Asian 00:00-08:00, London 08:00-13:00,
# New York 13:00-21:00. 21:00-24:00 UTC isn't covered by any of the three -
# labelled "Off-Session" rather than silently folded into one of them.
_SESSION_RANGES = (
    (0, 8, "Asian"),
    (8, 13, "London"),
    (13, 21, "New York"),
)


def session_tag(ts):
    """UTC-hour session label for a unix timestamp. Never raises - falls
    back to 'Unknown' for a missing/bad timestamp."""
    try:
        hour = datetime.fromtimestamp(float(ts), tz=timezone.utc).hour
    except (TypeError, ValueError, OSError):
        return "Unknown"
    for start, end, label in _SESSION_RANGES:
        if start <= hour < end:
            return label
    return "Off-Session"


def _clean_exit_reason(pos):
    """Collapses paper_trader's many close reasons (TP1/TP2_TARGET/SL/
    SCALP_TARGET/REVERSED/MANUAL/...) down to the small vocabulary this
    telemetry cares about: TP, SL, TSL, SCALP (plus REVERSED/MANUAL kept
    as-is since those aren't a strategy exit at all)."""
    reason = (pos.get("status") or "").replace("CLOSED_", "") or (pos.get("close_reason") or "")
    if reason == "SCALP_TARGET":
        return "SCALP"
    if reason == "SL":
        return "TSL" if pos.get("trailed_sl") else "SL"
    if reason.startswith("TP"):
        return "TP"
    return reason or "UNKNOWN"


_SD_BANDS = ((-3, "<-3sd"), (-2, "-3sd..-2sd"), (-1, "-2sd..-1sd"), (0, "-1sd..mean"),
             (1, "mean..+1sd"), (2, "+1sd..+2sd"), (3, "+2sd..+3sd"))


def sd_band_label(k):
    """SD-unit value -> band label (same names as strategy.py's entry_zone)."""
    try:
        k = float(k)
    except (TypeError, ValueError):
        return None
    for upper, label in _SD_BANDS:
        if k < upper:
            return label
    return ">+3sd"


def _sd_telemetry(pos):
    """SD path columns, or {} when the trade has no SD basis (older trades)."""
    try:
        e, b, w = pos.get("sd_entry_k"), pos.get("sd_best_k"), pos.get("sd_worst_k")
        if e is None or b is None or w is None:
            return {}
        opened = pos.get("opened_at_ts")

        def _mins(ts):
            return round((float(ts) - float(opened)) / 60.0, 1) if (ts and opened) else None

        return {
            "sd_entry": round(float(e), 2), "sd_best": round(float(b), 2), "sd_worst": round(float(w), 2),
            "sd_best_move": round(abs(float(b) - float(e)), 2),
            "sd_worst_move": round(abs(float(w) - float(e)), 2),
            "sd_best_band": sd_band_label(b), "sd_worst_band": sd_band_label(w),
            "sd_best_min": _mins(pos.get("sd_best_ts")), "sd_worst_min": _mins(pos.get("sd_worst_ts")),
        }
    except Exception:
        return {}


def _tp_minutes(pos, lvl):
    """Minutes from entry to the first touch of TP<lvl>, or None (never touched / unknown)."""
    try:
        t1, t0 = pos.get(f"tp{lvl}_ts"), pos.get("opened_at_ts")
        if t1 and t0 and float(t1) >= float(t0):
            return round((float(t1) - float(t0)) / 60.0, 1)
    except Exception:
        pass
    return None


def build_close_telemetry(pos):
    """Enriched, JSON-safe telemetry for a just-closed trade - the single
    source of truth used both for the outcomes CSV row here AND for
    trade_store.py's rolling closed-trade cache (so a query against either
    one sees the same numbers). Never raises; always returns a plain dict
    of primitives so it's always safe to json.dump."""
    try:
        opened_ts = pos.get("opened_at_ts")
        closed_ts = pos.get("closed_at_ts")
        duration_s = pos.get("duration_s")
        if duration_s is None and opened_ts and closed_ts:
            duration_s = closed_ts - opened_ts
        duration_s = float(duration_s or 0.0)
        return {
            "session_tag": session_tag(opened_ts),
            "peak_roi_pct": round(float(pos.get("max_roi_pct", 0.0) or 0.0), 2),
            "worst_drawdown_pct": round(float(pos.get("min_roi_pct", 0.0) or 0.0), 2),
            "duration_minutes": round(duration_s / 60.0, 2),
            "clean_exit_reason": _clean_exit_reason(pos),
            "quality_tag": pos.get("quality_tag") or "unknown",
            "tp1_min": _tp_minutes(pos, 1),
            "tp2_min": _tp_minutes(pos, 2),
            "tp3_min": _tp_minutes(pos, 3),
            "tp4_min": _tp_minutes(pos, 4),
            **_sd_telemetry(pos),
        }
    except Exception:
        return {
            "session_tag": "Unknown", "peak_roi_pct": 0.0, "worst_drawdown_pct": 0.0,
            "duration_minutes": 0.0, "clean_exit_reason": "UNKNOWN", "quality_tag": "unknown",
        }


def init(path):
    """path: a directory to hold the two CSVs (created if missing). Writes
    header rows only if the file doesn't already exist, so re-init on every
    app restart never truncates prior collected data."""
    global _data_dir, _features_file, _outcomes_file
    try:
        _data_dir = path
        os.makedirs(_data_dir, exist_ok=True)
        _features_file = os.path.join(_data_dir, "ai_trade_features.csv")
        _outcomes_file = os.path.join(_data_dir, "ai_trade_outcomes.csv")
        _ensure_header(_features_file, _FEATURE_FIELDS)
        _ensure_header(_outcomes_file, _OUTCOME_FIELDS)
    except Exception as e:
        print(f"[AIDataLogger] init failed (logging disabled): {e}")


def _ensure_header(file_path, fields):
    if not os.path.exists(file_path):
        with open(file_path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=fields).writeheader()
        return
    # Existing file from before new columns were added: rewrite it once with
    # the full header (old rows get blanks) so new rows never misalign.
    try:
        with open(file_path, "r", newline="") as f:
            rows = list(csv.DictReader(f))
            old_fields = list(rows and rows[0].keys() or [])
        if not rows:
            with open(file_path, "r", newline="") as f:
                old_fields = next(csv.reader(f), [])
        if old_fields != list(fields):
            tmp = file_path + ".tmp"
            with open(tmp, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            os.replace(tmp, file_path)
    except Exception as e:
        print(f"[AIDataLogger] header migration skipped: {e}")


def _append_row(file_path, fields, row):
    if not file_path:
        return
    try:
        with _lock:
            with open(file_path, "a", newline="") as f:
                csv.DictWriter(f, fieldnames=fields).writerow(row)
    except Exception as e:
        # Never let a logging failure touch the caller (paper_trader) -
        # just skip this row.
        print(f"[AIDataLogger] write failed: {e}")


def log_trade_opened(pos):
    """Call right after paper_trader opens a position - pos is the same dict
    stored in paper_trader._positions (has entry_price, signal_*, etc)."""
    if not _features_file:
        return
    try:
        ts = pos.get("opened_at_ts", time.time())
        dt = datetime.fromtimestamp(ts)
        row = {
            "trade_id": pos.get("id"),
            "opened_at_ts": ts,
            "opened_at": pos.get("opened_at"),
            "symbol": pos.get("symbol"),
            "action": pos.get("action"),
            "entry_price": pos.get("entry_price"),
            "invest_usdt": pos.get("invest_usdt"),
            "leverage": pos.get("leverage"),
            "signal_stop_loss": pos.get("signal_stop_loss"),
            "signal_tp1": pos.get("signal_tp1"),
            "signal_tp2": pos.get("signal_tp2"),
            "signal_tp3": pos.get("signal_tp3"),
            "signal_tp4": pos.get("signal_tp4"),
            "tp_mode": pos.get("tp_mode"),
            "tp_value": pos.get("tp_value"),
            "sl_value": pos.get("sl_value"),
            "hour_of_day": dt.hour,
            "day_of_week": dt.weekday(),
            "session_tag": session_tag(ts),
            "timeframe": pos.get("timeframe"),
            "entry_zone": pos.get("entry_zone"),
            "ema_slope_pct": pos.get("ema_slope_pct"),
            "volume_ratio": pos.get("volume_ratio"),
            "regime_cross_n": pos.get("regime_cross_n"),
            "atr_pct": pos.get("atr_pct"),
            "sd_width_pct": pos.get("sd_width_pct"),
            "ema_slope_prev_pct": pos.get("ema_slope_prev_pct"),
            "ema_slope10_pct": pos.get("ema_slope10_pct"),
            "ema_turn": pos.get("ema_turn"),
        }
        _append_row(_features_file, _FEATURE_FIELDS, row)
    except Exception as e:
        print(f"[AIDataLogger] log_trade_opened failed: {e}")


def log_trade_closed(pos, reason):
    """Call right after paper_trader closes a position - pos is the same
    dict, already updated with status/ltp/roi_pct/pnl_usdt/closed_at(_ts)."""
    if not _outcomes_file:
        return
    try:
        opened_ts = pos.get("opened_at_ts")
        closed_ts = pos.get("closed_at_ts", time.time())
        duration = (closed_ts - opened_ts) if opened_ts else None
        row = {
            "trade_id": pos.get("id"),
            "closed_at_ts": closed_ts,
            "closed_at": pos.get("closed_at"),
            "symbol": pos.get("symbol"),
            "action": pos.get("action"),
            "close_reason": reason,
            "exit_price": pos.get("ltp"),
            "pnl_usdt": pos.get("pnl_usdt"),
            "roi_pct": pos.get("roi_pct"),
            "duration_seconds": duration,
            "tp_hit_levels": ",".join(str(l) for l in pos.get("tp_hit_levels", [])),
        }
        row.update(build_close_telemetry(pos))
        row.update({
            "timeframe": pos.get("timeframe"),
            "entry_zone": pos.get("entry_zone"),
            "ema_slope_pct": pos.get("ema_slope_pct"),
            "volume_ratio": pos.get("volume_ratio"),
            "regime_cross_n": pos.get("regime_cross_n"),
            "atr_pct": pos.get("atr_pct"),
            "sd_width_pct": pos.get("sd_width_pct"),
            "ema_slope_prev_pct": pos.get("ema_slope_prev_pct"),
            "ema_slope10_pct": pos.get("ema_slope10_pct"),
            "ema_turn": pos.get("ema_turn"),
        })
        _append_row(_outcomes_file, _OUTCOME_FIELDS, row)
    except Exception as e:
        print(f"[AIDataLogger] log_trade_closed failed: {e}")
