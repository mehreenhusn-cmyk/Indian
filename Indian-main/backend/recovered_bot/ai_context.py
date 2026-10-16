"""
ai_context.py - the bigger picture for the AI: where does the coin stand on 1h / 4h / 1d? (BTC is NOT used: the daily top gainers / losers do not follow it)

Why it exists: an EMA50 signal on the 3m chart is much weaker when the bigger timeframes run the other way
(a SHORT signal while the daily chart is rising). The AI should SEE that and learn from it, not be told a rule.

How it stays cheap and safe (Binance rate limit hit this app before):
  - reads are CACHE ONLY (tag / trend never touch the network, so opening a trade is never delayed)
  - refresh() downloads at most MAX_FETCH candle sets per call, only for coins with an open AI trade,
    and only when the cached copy is older than its TTL (1h chart: 5 min, 4h: 15 min, 1d: 1 hour)
  - it runs inside the coach's own thread, never on the web server's event loop
  - any failure keeps the old cached value; every public function swallows its own errors

Trend of one timeframe (from the SAME indicators the bot uses: EMA50 slope, price vs EMA50, SD band width):
  UP / DOWN   EMA50 slope clearly one way and price on that side of it
  SIDE        EMA50 flat, or the SD band is squeezed (no direction)
  TURN_UP / TURN_DOWN   price crossed to the other side of EMA50 while its slope still points the old way
READ-ONLY: nothing here opens, closes or blocks a trade.
"""
import threading
import time

TFS = ((60, "1h", 300), (240, "4h", 900), (1440, "1d", 3600))      # (minutes, name, cache seconds)
LOOKBACK = 260                # SD band (Z_LEN 200) needs ~225 candles before it has a value
MAX_FETCH = 3                 # candle downloads per refresh() call
MAX_COINS = 12                # coins with a cached bigger-TF picture at the same time
SLOPE_BARS = 10
SLOPE_MIN = 0.15              # same EMA50 slope threshold the exit table uses (ai_exit_learn.state)
SQUEEZE = 0.80                # SD band width now / 20 candles ago below this = squeezed

_lock = threading.RLock()
_cache = {}                   # (sym, tf name) -> {"t": fetched at, "trend": label, "z": float, "slope": float}
_fail = {}                    # (sym, tf name) -> last failed attempt (do not hammer a broken symbol)


def _trend_of(S):
    """Label for the newest CLOSED candle of S (a dict from ai_ind_features.build). None if not computable."""
    try:
        n = S["n"] - 2                                   # the last candle may still be forming
        if n < 30:
            return None
        c, e, sd, w = S["c"][n], S["e50"][n], S["std"][n], S["width"][n]
        e_old, w_old, z = S["e50"][n - SLOPE_BARS], S["width"][n - 20], S["z"][n]
        if None in (c, e, sd, e_old, w, w_old) or not sd:
            return None
        slope = (e - e_old) / sd
        squeezed = bool(w_old) and (w / w_old) < SQUEEZE
        if abs(slope) < SLOPE_MIN or squeezed:
            lab = "SIDE"
        elif slope > 0:
            lab = "UP" if c >= e else "TURN_DOWN"
        else:
            lab = "DOWN" if c <= e else "TURN_UP"
        return {"trend": lab, "slope": round(slope, 2), "z": None if z is None else round(z, 2)}
    except Exception:
        return None


def _fetch(sym, mins):
    from . import exchange
    return exchange.get_klines(sym, tf=mins, limit=LOOKBACK, fast=True)


def refresh(syms=(), force=False):
    """Download what is stale (the given coins only). Call from a background thread only."""
    try:
        from . import ai_ind_features as F
        now = time.time()
        want = [s for s in syms if s]
        budget = MAX_FETCH
        for sym in want:
            for mins, name, ttl in TFS:
                if budget <= 0:
                    return
                key = (sym, name)
                with _lock:
                    got = _cache.get(key)
                    bad = _fail.get(key, 0.0)
                if got and not force and now - got["t"] < ttl:
                    continue
                if now - bad < 120:
                    continue
                budget -= 1
                try:
                    cs = _fetch(sym, mins)
                    res = _trend_of(F.build(cs)) if cs else None
                except Exception:
                    res = None
                with _lock:
                    if res:
                        res["t"] = time.time()
                        _cache[key] = res
                        _fail.pop(key, None)
                    else:
                        _fail[key] = time.time()
                    if len(_cache) > MAX_COINS * len(TFS) + len(TFS):       # forget the oldest coins
                        for k in sorted(_cache, key=lambda x: _cache[x]["t"])[: len(_cache) - MAX_COINS * len(TFS)]:
                            _cache.pop(k, None)
    except Exception as e:
        print(f"[AIContext] refresh: {e}")


def trend(sym, name):
    """Cached trend label of one timeframe, or None (not downloaded yet)."""
    with _lock:
        v = _cache.get((sym, name))
    return v["trend"] if v else None


def _rel(label, d):
    """Trend label relative to a trade direction d (+1 long / -1 short): WITH / AGAINST / SIDE."""
    if label in (None, "SIDE"):
        return "SIDE" if label else None
    up = label in ("UP", "TURN_UP")
    return "WITH" if (up and d > 0) or (not up and d < 0) else "AGAINST"


def tag(sym, side):
    """How a trade (BUY/SELL) sits against the bigger picture.
    -> {'align': WITH|AGAINST|MIXED|SIDE|UNKNOWN, 'tfs': {'1h': 'WITH', ...}}"""
    try:
        d = 1 if side == "BUY" else -1
        tfs = {name: _rel(trend(sym, name), d) for _m, name, _t in TFS}
        known = [v for v in tfs.values() if v]
        out = {"tfs": tfs}
        if not known:
            out["align"] = "UNKNOWN"
        else:
            w, a = known.count("WITH"), known.count("AGAINST")
            out["align"] = "WITH" if w >= 2 and a == 0 else ("AGAINST" if a >= 2 and w == 0 else (
                "SIDE" if known.count("SIDE") == len(known) else "MIXED"))
        return out
    except Exception:
        return {"align": "UNKNOWN", "tfs": {}}


NICE = {"UP": "going up", "DOWN": "going down", "SIDE": "sideways", "TURN_UP": "turning up",
        "TURN_DOWN": "turning down", None: "loading"}


def coin_view(sym):
    """Bigger-TF picture of one coin for the screen."""
    try:
        return {name: NICE.get(trend(sym, name), "loading") for _m, name, _t in TFS}
    except Exception:
        return {}
