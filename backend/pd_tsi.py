"""pd_tsi.py - candle data + indicator numbers + STRENGTH score for the Pump / Dump scanner (Round 1, 28 Nov 2026).
Read README_PUMPDUMP.md section 3 and 4 first. Inside the existing pd_runner thread only: no new thread, no Telegram, no order.
  * Candles come from GET /fapi/v1/klines (public, no key). A coin + time frame is fetched ONLY when its next candle has closed (cache),
    with a hard cap of calls per minute (pd_config kline_calls_min) and a back-off on 429 / 418.
  * NO new formula: sma / pstdev / zscore / tsi_series come from owl_sniper_engine_a.py (Pine-exact, the owner's chart: TSI long 25 / short 5 /
    signal 14, Z length 200, Z-SMA 200, EMA 30 / 50, SD bands on the 200 mean). Extra Z lengths 50 / 100 are for the study (Round 4).
  * Per coin per time frame: tsi, tsi_signal, hist, hist_change, tsi_up, tsi_above_zero, z50 / z100 / z200, zsm, ema30 / ema50 distance %, sd_pos
    (= Z200, price position inside the SD bands, in SD units), taker_buy_share (buyers' share of the last 3 closed candles).
  * strength() = 0-100, a plain weighted sum (weights in pd_config); the learned chance (pd_chance.py) tells how far to trust it."""
import time
from collections import deque

import pd_config as C
from owl_sniper_engine_a import ema, pstdev, sma, sma_any, tsi_series, zscore

URL = "https://fapi.binance.com/fapi/v1/klines"
TFS = ("5m", "15m", "1h", "2h", "4h", "1d")
TF_SEC = {"5m": 300, "15m": 900, "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400}
TSI_SHORT, TSI_LONG, TSI_SIGNAL = 5, 25, 14     # the owner's Special Master TSI (owl_sniper_engine_b DEFAULTS)
Z_LENS = (50, 100, 200)
ZSM_LEN = 200
MIN_CLOSES = 60


class RateLimited(Exception):
    def __init__(self, status, wait):
        super().__init__("binance %s" % status)
        self.status, self.wait = status, wait


def _last(x):
    return x[-1] if x and x[-1] is not None else None


def analyse(rows, tf, now):
    """Binance kline rows (oldest first) -> dict of numbers, or None when there are too few CLOSED candles. The forming candle is dropped."""
    rows = [r for r in rows if r[0] / 1000.0 + TF_SEC[tf] <= now + 1]
    if len(rows) < MIN_CLOSES:
        return None
    c = [float(r[4]) for r in rows]
    t, sg, hs = tsi_series(c, TSI_SHORT, TSI_LONG, TSI_SIGNAL)
    out = {"tf": tf, "n": len(c), "close": c[-1], "close_t": int(rows[-1][0] / 1000.0 + TF_SEC[tf]),
           "tsi": _last(t), "tsi_signal": _last(sg), "hist": _last(hs)}
    out["hist_change"] = (hs[-1] - hs[-2]) if len(hs) > 1 and hs[-1] is not None and hs[-2] is not None else None
    out["tsi_up"] = (t[-1] > t[-2]) if len(t) > 1 and t[-1] is not None and t[-2] is not None else None
    out["tsi_above_zero"] = (t[-1] > 0) if t[-1] is not None else None
    zs = {}
    for n in Z_LENS:
        zz = zscore(c, n)
        zs[n] = zz
        out["z%d" % n] = _last(zz)
    out["zsm"] = _last(sma_any(zs[200], ZSM_LEN))
    out["sd_pos"] = out["z200"]
    for n in (30, 50):
        e = _last(ema(c, n))
        out["ema%d_dist" % n] = ((c[-1] / e - 1.0) * 100.0) if e else None
    out["hi24"] = max(float(r[2]) for r in rows[-24:])    # Part A (29 Nov 2026): high / low of the last 24 closed candles (15m = 6 h, 1h = 24 h): Rank reads them to see a pump that is already over
    out["lo24"] = min(float(r[3]) for r in rows[-24:])
    qv = sum(float(r[7]) for r in rows[-3:])
    out["taker_buy_share"] = (sum(float(r[10]) for r in rows[-3:]) / qv) if qv > 0 else None
    return out


class Klines:
    def __init__(self, fetch=None):
        self.fetch = fetch or self._fetch
        self.cache = {}            # (symbol, tf) -> {"next": epoch of the next candle close, "data": dict or None, "t": fetch time}
        self.calls = deque()       # times of the calls of the last 60 s
        self.blocked_until = 0.0
        self.last_error = ""
        self.fetched = 0

    @staticmethod
    def _fetch(sym, tf, limit):
        import requests
        r = requests.get(URL, params={"symbol": sym, "interval": tf, "limit": limit}, timeout=10)
        if r.status_code in (418, 429):
            raise RateLimited(r.status_code, 600 if r.status_code == 418 else 120)
        r.raise_for_status()
        return r.json()

    def get(self, sym, tf):
        c = self.cache.get((sym, tf))
        return c["data"] if c else None

    def tf_data(self, sym):
        """All cached time frames of a coin: {tf: numbers}."""
        out = {}
        for tf in TFS:
            d = self.get(sym, tf)
            if d:
                out[tf] = d
        return out

    def due(self, sym, tf, now):
        c = self.cache.get((sym, tf))
        return c is None or now >= c["next"]

    def limited(self, now):
        """A short text for the app when Binance is limiting us (or our own cap is full), else ''."""
        if now < self.blocked_until:
            return "Binance ne thodi der rok diya (%d s)" % int(self.blocked_until - now)
        return ""

    def refresh(self, sym, tf, now):
        """'fresh' (no call needed) | 'ok' | 'cap' (per-minute cap full) | 'blocked' (Binance back-off) | 'error'."""
        if not self.due(sym, tf, now):
            return "fresh"
        if now < self.blocked_until:
            return "blocked"
        while self.calls and self.calls[0] < now - 60:
            self.calls.popleft()
        if len(self.calls) >= C.get("kline_calls_min"):
            return "cap"
        self.calls.append(now)
        try:
            rows = self.fetch(sym, tf, int(C.get("kline_limit")))
            data = analyse(rows, tf, now)
            nxt = rows[-1][0] / 1000.0 + TF_SEC[tf] + 3 if rows else now + 60
            if nxt <= now:
                nxt = now + 30
            self.cache[(sym, tf)] = {"next": nxt, "data": data, "t": now}
            self.fetched += 1
            self.last_error = ""
            return "ok"
        except RateLimited as e:
            self.blocked_until = now + e.wait
            self.last_error = str(e)
            return "blocked"
        except Exception as e:
            old = self.cache.get((sym, tf))
            self.cache[(sym, tf)] = {"next": now + 60, "data": old["data"] if old else None, "t": now}
            self.last_error = "%s: %s" % (type(e).__name__, str(e)[:80])
            return "error"

    def step(self, symbols, now, tfs=None):
        """Refresh what is due, symbols in priority order, short time frames first, at most kline_step_max calls per step. Returns the calls made."""
        made, cap = 0, int(C.get("kline_step_max"))
        for tf in (tfs or TFS):
            for sym in symbols:
                if made >= cap:
                    return made
                res = self.refresh(sym, tf, now)
                if res in ("ok", "error"):
                    made += 1
                elif res in ("cap", "blocked"):
                    return made
        if len(self.cache) > 600:                       # forget coins nobody asked for in the last hour
            for k in [k for k, v in self.cache.items() if v["t"] < now - 3600]:
                del self.cache[k]
        return made

    def clear(self):
        self.cache.clear()
        self.calls.clear()


def _clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def strength(sgn, vr, d15, rank_gain, tfd):
    """0-100 strength of a move. sgn = +1 pump / -1 dump, vr = volume ratio, rank_gain = places climbed in the Binance 24h list, tfd = Klines.tf_data(sym).
    Parts (weights in pd_config): volume, buyers / sellers share (taker), TSI turning or on the right side of zero, histogram direction, how many
    time frames agree (TSI turning AND histogram going the right way), rank climb. The distance from the EMA is NOT used (far from EMA is allowed).
    Missing candle data = those parts count 0 and `partial` is True (the card then says it is an estimate)."""
    tfs = list(tfd.values())
    shares = [d["taker_buy_share"] for tf, d in tfd.items() if tf in ("5m", "15m") and d.get("taker_buy_share") is not None]
    tk = 0.0
    if shares:
        s = sum(shares) / len(shares)
        tk = _clamp01(((s - 0.5) if sgn > 0 else (0.5 - s)) / 0.2)
    turn = hist_ok = agree = 0.0
    for d in tfs:
        tn = 1.0 if d.get("tsi_up") is not None and ((d["tsi_up"]) == (sgn > 0)) else 0.0
        zn = 1.0 if d.get("tsi") is not None and sgn * d["tsi"] > 0 else 0.0
        hk = 1.0 if d.get("hist_change") is not None and sgn * d["hist_change"] > 0 else 0.0
        turn += 0.5 * tn + 0.5 * zn
        hist_ok += hk
        agree += 1.0 if (tn and hk) else 0.0
    n = len(tfs)
    parts = {"vol": _clamp01(vr / 8.0), "taker": tk, "tsi": (turn / n) if n else 0.0, "hist": (hist_ok / n) if n else 0.0,
             "tf": agree / float(len(TFS)), "rank": _clamp01(rank_gain / 20.0)}
    w = {k: float(C.get("w_" + k)) for k in parts}
    score = sum(parts[k] * w[k] for k in parts)
    return {"score": int(round(max(0.0, min(100.0, score)))), "partial": n < len(TFS) or not shares, "tf_agree": int(agree), "tf_ready": n,
            "parts": {k: round(v, 2) for k, v in parts.items()}}
