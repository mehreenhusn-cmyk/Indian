"""Part U2 (Z1b-1): the 7-day coin list for the Dual Bot. NAMES ONLY - no candle replay, no backtest.

Day = 00:00 UTC to 00:00 UTC (= 5:30 AM IST to 5:30 AM IST). For each completed day we keep the top 5 gainers + top 5 losers
by that day's change (1d candle: close vs open). Day lists are saved for ever in universe_days.json (never deleted).
universe_ctl.json {"cap": 30} = how many extra (7-day) coins may be added; change it without a zip.

This file does NOT touch the bot yet: Z1b-2 adds the one hook line in dual_lab.py. Everything here never raises.
Files (in the owl_data folder): universe_days.json, universe_ctl.json.
"""
import json
import os
import threading
import time

DAY_MS = 86400000
KEEP_DAYS = 7           # the last 7 COMPLETED days are used for the coin list
PER_SIDE = 5            # top 5 gainers + top 5 losers per day
DEFAULT_CAP = 30        # extra coins on top of today's list
_LOCK = threading.Lock()
_S = {"thread": None, "err": "", "last": 0.0, "extra": set()}


def _dir(base=None):
    if not base:
        base = os.environ.get("OWL_DATA_DIR")
    if not base:
        try:
            with open(os.path.expanduser("~/.owl_data_dir"), "r", encoding="utf-8") as f:
                base = f.read().strip()
        except Exception:
            base = ""
    base = base or os.path.expanduser("~/owl_data")
    os.makedirs(base, exist_ok=True)
    return base


def _load(name, default, base=None):
    try:
        with open(os.path.join(_dir(base), name), "r", encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, type(default)) else default
    except Exception:
        return default


def _save(name, obj, base=None):
    path = os.path.join(_dir(base), name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def day_start_ms(now_s):
    """00:00 UTC of the day that contains now_s (seconds)."""
    return int(now_s * 1000) // DAY_MS * DAY_MS


def day_name(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000.0))


def cap_now(base=None):
    try:
        c = int(_load("universe_ctl.json", {}, base).get("cap", DEFAULT_CAP))
        return max(0, min(c, 200))
    except Exception:
        return DEFAULT_CAP


def top_lists(changes, n=PER_SIDE):
    """changes = {symbol: percent}. Returns (gainers best first, losers worst first). A coin is never in both lists."""
    srt = sorted(changes.items(), key=lambda kv: kv[1])
    g = [s for s, _ in reversed(srt[-n:])]
    l = [s for s, _ in srt[:n] if s not in g]
    return g, l


def build_days(klines, today_ms, have=None):
    """klines = {symbol: [[open_ms, open, high, low, close, ...], ...]} (1d candles).
    Returns {"YYYY-MM-DD": {"g": [...], "l": [...]}} for completed days of the last KEEP_DAYS that are not in `have` yet."""
    have = have or {}
    per_day = {}
    for sym, kl in klines.items():
        for k in kl or []:
            try:
                o_ms, o, c = int(k[0]), float(k[1]), float(k[4])
            except Exception:
                continue
            if o <= 0 or o_ms >= today_ms or o_ms < today_ms - KEEP_DAYS * DAY_MS:
                continue                      # today's candle is still forming; older than 7 days is not needed
            per_day.setdefault(o_ms, {})[sym] = (c - o) / o * 100.0
    out = {}
    for o_ms, ch in per_day.items():
        name = day_name(o_ms)
        if name in have or len(ch) < 2 * PER_SIDE:
            continue
        g, l = top_lists(ch)
        out[name] = {"g": g, "l": l}
    return out


def extra_coins(days, today_coins, cap, today_ms):
    """7-day coins: newest day first, gainers then losers, no duplicates, not in today's list, no BTC. Max `cap`."""
    skip = set(today_coins or []) | {"BTCUSDT"}
    names = [day_name(today_ms - i * DAY_MS) for i in range(1, KEEP_DAYS + 1)]
    out = []
    for nm in names:
        d = days.get(nm) or {}
        for s in list(d.get("g") or []) + list(d.get("l") or []):
            if s not in skip and s not in out:
                out.append(s)
    return out[:max(0, cap)]


def _binance(path, params=None):
    from recovered_bot import binance_client
    return binance_client._get(path, params)


def refresh(fetch=None, now_s=None, base=None, pause=0.05, log=lambda m: None):
    """Reads Binance 1d candles (one request per coin) and adds any missing completed day to universe_days.json. Old days stay."""
    fetch = fetch or _binance
    now_s = time.time() if now_s is None else now_s
    today_ms = day_start_ms(now_s)
    days = _load("universe_days.json", {}, base)
    need = [day_name(today_ms - i * DAY_MS) for i in range(1, KEEP_DAYS + 1)]
    if all(n in days for n in need):
        return days
    tick = fetch("/fapi/v1/ticker/24hr")
    syms = [d["symbol"] for d in tick if str(d.get("symbol", "")).endswith("USDT") and "_" not in d["symbol"]]
    kl = {}
    for i, s in enumerate(syms):
        try:
            kl[s] = fetch("/fapi/v1/klines", {"symbol": s, "interval": "1d", "limit": KEEP_DAYS + 2})
        except Exception:
            continue                          # one coin failing must not stop the rest
        if pause:
            time.sleep(pause)
    log("universe: %d coins read" % len(kl))
    new = build_days(kl, today_ms, days)
    if new:
        days.update(new)
        _save("universe_days.json", days, base)
    return days


def _bg():
    try:
        refresh()
        _S["err"] = ""
    except Exception as e:
        _S["err"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    _S["last"] = time.time()


def coins_for_dual(today_coins, base=None, now_s=None):
    """The Dual Bot coin list = today's list + 7-day extras. Starts the background name-read when days are missing
    (about 1-2 minutes, the bot keeps running with today's list meanwhile). Never raises; any problem = today's list only."""
    today_coins = list(today_coins or [])
    try:
        now_s = time.time() if now_s is None else now_s
        today_ms = day_start_ms(now_s)
        days = _load("universe_days.json", {}, base)
        need = [day_name(today_ms - i * DAY_MS) for i in range(1, KEEP_DAYS + 1)]
        with _LOCK:
            t = _S["thread"]
            if not all(n in days for n in need) and (t is None or not t.is_alive()) and now_s - _S["last"] > 1800:
                _S["thread"] = threading.Thread(target=_bg, daemon=True, name="universe_7d")
                _S["thread"].start()
        extra = [s for s in extra_coins(days, today_coins, cap_now(base), today_ms) if s not in today_coins]
        _S["extra"] = set(extra)
        _log_day(today_coins, extra, base, now_s)
        return today_coins + extra
    except Exception as e:
        _S["err"] = "%s: %s" % (type(e).__name__, str(e)[:100])
        return today_coins


def with_extras(today_coins, base=None, now_s=None):
    """Read-only twin of coins_for_dual: today's list + 7-day names from the saved file. Starts no download (the Brain worker uses this).
    Never raises."""
    today_coins = list(today_coins or [])
    try:
        now_s = time.time() if now_s is None else now_s
        today_ms = day_start_ms(now_s)
        days = _load("universe_days.json", {}, base)
        extra = [s for s in extra_coins(days, today_coins, cap_now(base), today_ms) if s not in today_coins]
        return today_coins + extra
    except Exception:
        return today_coins


def _log_day(today, extra, base=None, now_s=None):
    """Remembers for ever which coins were on the Dual list on each UTC day (today's top 20 / 7-day-only names), in universe_log.json.
    The desk uses it to tell a trade's source (today / d7) without changing any trade row. Never raises."""
    try:
        day = day_name(day_start_ms(time.time() if now_s is None else now_s))
        log = _load("universe_log.json", {}, base)
        e = log.setdefault(day, {"today": [], "extra": []})
        changed = False
        for k, lst in (("today", today), ("extra", extra)):
            for s in lst or []:
                if s not in e[k]:
                    e[k].append(s)
                    changed = True
        if changed:
            _save("universe_log.json", log, base)
    except Exception as ex:
        _S["err"] = "%s: %s" % (type(ex).__name__, str(ex)[:100])


def tag_of(sym, t_ms, log):
    """Source of a trade, read-only: today (in that day's top list or BTC) / d7 (only a 7-day name that day) / other (before the log started)."""
    e = (log or {}).get(day_name(int(t_ms)))
    if sym == "BTCUSDT" or (e and sym in e.get("today", [])):
        return "today"
    return "d7" if e and sym in e.get("extra", []) else "other"


def is_extra(sym):
    """True when the coin is on the list ONLY because of the 7-day names (not in today's list). The Dual Bot then skips the history replay."""
    return sym in _S["extra"]


def load_log(base=None):
    return _load("universe_log.json", {}, base)


def status(base=None, now_s=None):
    """Small summary for the app / API (Z1b-2): which days are saved, cap, last error."""
    try:
        days = _load("universe_days.json", {}, base)
        keep = sorted(days)[-KEEP_DAYS:]
        return {"days": keep, "lists": {k: days[k] for k in keep}, "saved_days": len(days), "cap": cap_now(base), "err": _S["err"]}
    except Exception as e:
        return {"days": [], "saved_days": 0, "cap": DEFAULT_CAP, "err": str(e)[:100]}
