"""top10_7d.py - the coins that were in Binance's TOP 10 GAINERS or TOP 10 LOSERS on each of the last 7 completed days (owner, 26 Nov 2026).
History comes from Binance DAILY candles (one request per coin), so ALL 7 days are there from the first run: no waiting for data to collect.
Day = 00:00 UTC to 00:00 UTC (= 5:30 AM IST to 5:30 AM IST), change = that day's close vs open. A coin with a daily turnover under MIN_QV is skipped
(dead coins fill the lists otherwise). A coin is never a gainer and a loser on the same day.
The list is built ONCE per UTC day and saved in <data>/top10_7d.json (about 1 minute for ~400 coins, one request at a time, small pauses). It is built when
the app asks and the file is missing / from yesterday: a worker thread that ends by itself, NO permanent background job. Never raises.
view() adds the LIVE numbers: one coin per row (its newest day in a list), price now, change since that day's close, change over the 7-day window, 24h change."""
import json
import os
import threading
import time

DAY_MS = 86400000
KEEP = 7
PER_SIDE = 10
MIN_QV = 5000000.0       # daily turnover (USDT) a coin needs on a day to count that day
PRE_QV = 1000000.0       # 24h turnover now: coins below it are not even asked for candles (saves about half of the requests)
BASE = "https://fapi.binance.com"
FILE = "top10_7d.json"
_S = {"thread": None, "err": "", "done": 0, "total": 0, "started": 0.0}
_LOCK = threading.Lock()
_NOW = {"t": 0.0, "v": None}


def _get(path, params=None):
    import requests
    r = requests.get(BASE + path, params=params, timeout=12)
    r.raise_for_status()
    return r.json()


def day_name(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000.0))


def _load(base):
    try:
        with open(os.path.join(base, FILE), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def _save(base, obj):
    os.makedirs(base, exist_ok=True)
    p = os.path.join(base, FILE)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(p + ".tmp", p)


def build(base, fetch=None, now_s=None, pause=0.05):
    """Reads the candles and writes the file. Returns the dict. Raises on a network error (the caller keeps it in _S['err'])."""
    fetch = fetch or _get
    now_s = time.time() if now_s is None else now_s
    today_ms = int(now_s * 1000) // DAY_MS * DAY_MS
    tick = fetch("/fapi/v1/ticker/24hr")
    syms = []
    for d in tick:
        s = str(d.get("symbol", ""))
        try:
            if s.endswith("USDT") and "_" not in s and float(d.get("quoteVolume", 0)) >= PRE_QV:
                syms.append(s)
        except Exception:
            pass
    _S.update(done=0, total=len(syms))
    per_day = {}            # day -> [(sym, pct, close, qv)]
    first_open = {}         # sym -> open of the oldest of the 7 days
    for i, s in enumerate(syms):
        try:
            kl = fetch("/fapi/v1/klines", {"symbol": s, "interval": "1d", "limit": KEEP + 2})
        except Exception:
            kl = []
        done = [k for k in kl if int(k[0]) < today_ms][-KEEP:]       # completed days only
        for k in done:
            try:
                o, c, qv = float(k[1]), float(k[4]), float(k[7])
            except Exception:
                continue
            if o > 0 and qv >= MIN_QV:
                per_day.setdefault(day_name(int(k[0])), []).append((s, (c / o - 1.0) * 100.0, c))
        if done:
            try:
                first_open[s] = float(done[0][1])
            except Exception:
                pass
        _S["done"] = i + 1
        if pause:
            time.sleep(pause)
    days = {}
    keep_syms = set()
    for day, rows in per_day.items():
        rows.sort(key=lambda r: r[1], reverse=True)
        g = [r for r in rows if r[1] > 0][:PER_SIDE]
        l = [r for r in reversed(rows) if r[1] < 0][:PER_SIDE]
        days[day] = {"gainers": [[r[0], round(r[1], 2), r[2]] for r in g], "losers": [[r[0], round(r[1], 2), r[2]] for r in l]}
        keep_syms.update(r[0] for r in g + l)
    out = {"built_for": day_name(today_ms), "built_at": int(now_s), "days": days, "o7": {s: first_open[s] for s in keep_syms if s in first_open}}
    _save(base, out)
    return out


def _worker(base):
    try:
        _S["err"] = ""
        build(base)
    except Exception as e:
        _S["err"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    finally:
        _S["thread"] = None


def _start(base):
    with _LOCK:
        t = _S["thread"]
        if t is not None and t.is_alive():
            return False
        _S["started"] = time.time()
        t = threading.Thread(target=_worker, args=(base,), daemon=True, name="top10_7d_build")
        _S["thread"] = t
        t.start()
        return True


def _live(fetch=None, now=None):
    """symbol -> (price, 24h change %). One call, cached 30 s."""
    now = time.time() if now is None else now
    if _NOW["v"] is not None and now - _NOW["t"] < 30:
        return _NOW["v"]
    v = {}
    for d in (fetch or _get)("/fapi/v1/ticker/24hr"):
        try:
            v[d["symbol"]] = (float(d["lastPrice"]), float(d.get("priceChangePercent", 0.0)))
        except Exception:
            pass
    _NOW.update(t=now, v=v)
    return v


def rows_from(data, live):
    """One row per coin = its NEWEST day in a top-10 list, with how often it came back and its numbers now."""
    seen = {}
    for day in sorted(data.get("days", {}), reverse=True):
        for side, key in (("G", "gainers"), ("L", "losers")):
            for sym, pct, close in data["days"][day].get(key, []):
                if sym in seen:
                    seen[sym]["times"] += 1
                    continue
                seen[sym] = {"symbol": sym, "side": side, "day": day, "day_pct": pct, "close": close, "times": 1}
    o7 = data.get("o7", {})
    out = []
    for sym, r in seen.items():
        lv = live.get(sym)
        if lv and lv[0] > 0:
            r["now"] = lv[0]
            r["chg24"] = round(lv[1], 2)
            r["since_pct"] = round((lv[0] / r["close"] - 1.0) * 100.0, 2) if r["close"] > 0 else None
            r["week_pct"] = round((lv[0] / o7[sym] - 1.0) * 100.0, 2) if o7.get(sym, 0) > 0 else None
        out.append(r)
    out.sort(key=lambda r: (r["day"], abs(r["day_pct"])), reverse=True)
    return out


def view(base, fetch=None, now_s=None):
    now_s = time.time() if now_s is None else now_s
    today = day_name(int(now_s * 1000) // DAY_MS * DAY_MS)
    data = _load(base)
    fresh = bool(data) and data.get("built_for") == today
    building = False
    if not fresh:
        _start(base)
        t = _S["thread"]
        building = t is not None and t.is_alive()
    res = {"state": "ok", "built_for": data.get("built_for") if data else None, "building": building, "progress": [_S["done"], _S["total"]],
           "error": _S["err"], "days": sorted(data.get("days", {}), reverse=True) if data else [], "rows": []}
    if data:
        try:
            res["rows"] = rows_from(data, _live(fetch, now_s))
        except Exception as e:
            res["error"] = "live prices: %s" % type(e).__name__
            res["rows"] = rows_from(data, {})
    elif not building and _S["err"]:
        res["state"] = "error"
    return res
