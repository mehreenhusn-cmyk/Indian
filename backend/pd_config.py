"""pd_config.py - settings + data folder of the PUMP / DUMP scanner (PD), 26 Nov 2026. Read README5 "PUMP DUMP SCANNER" first.

The scanner reads Binance USDT-M futures (public data, no key), finds coins that start to pump or dump, and shows them ONLY in the app
(no Telegram, no order, it never touches the trading bot). Its own files live in <data folder>/pumpdump/ :
  events/<day>.jsonl   every stage change (WATCH, START, RUNNING, WEAK, END), one file per IST day
  outcomes/<day>.jsonl  what each START really did after 15 / 30 / 60 min (real or fake)
  missed/<day>.jsonl   coins that moved 5%+ in 30 min without any alert (for the tuner)
  tuner.json           slow self-learning: coin penalties / bonuses, threshold changes (with the reason), switches
  reports/<day>.json   the small daily report
  enabled.json         the on / off switch of the scanner (the app has a switch for it)
Numbers below are the DEFAULTS. The tuner may override only the keys in TUNABLE, in small steps inside the bounds."""
import os
import threading
import time

VERSION = "pd 2 (28 Nov 2026, Round 1)"

DEFAULTS = {
    "poll_sec": 20,          # one Binance 24h-ticker call (all coins) every 20 s
    "min_qv24": 5000000.0,   # skip dead coins: 24h turnover under 5M USDT
    "hist_min": 95,          # minutes of price / volume history kept per coin
    "warm_min": 12,          # minutes of history needed before any alert (volume baseline)
    "watch_r5": 0.5, "watch_vol": 2.0, "watch_score": 30,
    "start_r5": 1.0, "start_r1": 0.7, "start_vol": 5.0, "start_score": 65,   # Round C (26 Nov 2026): 55 -> 65, the first day gave 41 pump + 31 dump STARTs, only 30% / 24% real
    "run_gain": 3.0,         # % since START -> PUMP RUNNING / DUMP RUNNING, one update per further step of the same size
    "run_vol": 1.5,
    "weak_vol": 1.0, "weak_pullback": 1.2,
    "cool_start_min": 60, "cool_watch_min": 30,   # Round C: one START per coin per 60 min (was 30)
    "watch_ttl_min": 20, "end_after_weak_min": 10, "start_fail_min": 45,
    "max_active_side": 5,    # at most 5 coins at a time on the pump side and 5 on the dump side
    "real_move": 2.0,        # an alert is REAL when the coin moved 2%+ the right way within 60 min
    "missed_move": 5.0,      # a move of 5%+ in 30 min with no alert = missed
    "min_outcomes": 100,     # the tuner changes thresholds only after this many checked alerts (last 14 days)
    "keep_days": 60,
    "tz_min": 330,           # day = IST calendar day
    # ---- Round 1 (28 Nov 2026): Naye Movers + Chal rahe + TSI strength + chance. One setting per line, never a # comment in the middle of a line.
    "rank_sample_sec": 30,
    "rank_hist_min": 35,
    "top_n": 10,
    "mv_rank_gain": 8,
    "mv_vol": 2.5,
    "mv_move_lo": 1.0,
    "mv_move_hi": 6.0,
    "mv_r5_min": 0.2,
    "mv_max_side": 8,
    "run_max_side": 10,
    "run_keep_min": 180,
    "tire_vol": 0.7,
    "tire_share": 0.48,
    "noise_r5": 0.5,
    "kline_limit": 499,
    "kline_calls_min": 40,
    "kline_step_max": 12,
    "w_vol": 25, "w_taker": 20, "w_tsi": 20, "w_hist": 10, "w_tf": 15, "w_rank": 10,
    "chance_prior": 0.30,
    "chance_k": 20,
}
# the only keys the tuner may change: (min, max, step)
TUNABLE = {"start_vol": (3.0, 8.0, 0.5), "watch_vol": (1.5, 4.0, 0.5)}

_lock = threading.RLock()
_S = {"root": None, "overrides": {}}


def init(data_dir):
    with _lock:
        _S["root"] = os.path.join(data_dir, "pumpdump")
        os.makedirs(_S["root"], exist_ok=True)
    try:
        import pd_store
        t = pd_store.read_json("tuner.json", {})
        ov = t.get("overrides") or {}
        with _lock:
            _S["overrides"] = {k: float(v) for k, v in ov.items() if k in TUNABLE}
    except Exception:
        pass
    return _S["root"]


def root():
    return _S["root"]


def path(*parts):
    return os.path.join(_S["root"], *parts)


def get(key):
    with _lock:
        if key in _S["overrides"]:
            return _S["overrides"][key]
    return DEFAULTS[key]


def set_override(key, val):
    if key not in TUNABLE:
        return False
    lo, hi, _ = TUNABLE[key]
    with _lock:
        _S["overrides"][key] = max(lo, min(hi, float(val)))
    return True


def overrides():
    with _lock:
        return dict(_S["overrides"])


def day_of(ts):
    """IST calendar day (YYYY-MM-DD) of an epoch time."""
    return time.strftime("%Y-%m-%d", time.gmtime(ts + get("tz_min") * 60))


def clock_of(ts):
    """IST HH:MM:SS of an epoch time."""
    return time.strftime("%H:%M:%S", time.gmtime(ts + get("tz_min") * 60))
