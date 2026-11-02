"""owl_sniper_engine_b.py - OwlSniper ENGINE PART B of 3: candles in, features, regime guard, raw signal (backend, plain python, NO numpy / pandas / sklearn).
Imports ONLY owl_sniper_engine_a (the maths) and `math`. Nothing is traded, nothing is saved here.
What it does, in plain words:
  to_series      candles (dicts or tuples, oldest first) -> clean lists t / o / h / l / c. Bad rows raise ValueError (never guessed).
  build_features every indicator number for every candle: EMA cloud, SMA, SD, Z, TSI, Volatility Index (VI), regime flag, EMA crosses.
  regime_at      'TRENDING' / 'SIDEWAYS' / 'UNKNOWN'. VI = SD / SMA. SIDEWAYS when VI < regime_ratio x its own average of the last regime_win candles.
                 UNKNOWN (not enough data) is treated as BLOCKED by every caller: the safe side.
  raw_signal     EMA cross + TSI histogram + Z zone confluence at one candle, BEFORE the regime guard and BEFORE any probability.
  stop_price     stop line = SMA -+ z_mult x SD (right outside the outer SD band).
EXCLUDED on purpose: CHoCH and BOS (market structure). They are never computed, mapped or used here.
Flat window (SD = 0): Z is 0.0 here (no trade zone, never a division error). Part A's zscore() returns None for the same case; this file chooses 0.0 on purpose.
Part C imports this file for the simulator, the day split, the search and the OwlSniperEngine class."""
from owl_sniper_engine_a import sma, sma_any, ema, pstdev, tsi_series, _ok

VERSION = "owl_sniper_engine_b 1 (Part B)"
EXCLUDED = ("CHoCH", "BOS")

DEFAULTS = {
    "sd_len": 200,           # Special 13 `len` and Special Master `zLen` (Part C tests 20..200 on TRAIN days only)
    "fast_ema": 30, "slow_ema": 50,              # EMA cloud of Special 13
    "z_mult": 2.0,           # stop line = SMA -+ z_mult x SD
    "tsi_long": 25, "tsi_short": 5, "tsi_signal": 14,   # Special Master: longfLen 25, shortfLen 5, signalfLen 14
    "regime_win": 50,        # candles used for the average Volatility Index
    "regime_ratio": 1.0,     # SIDEWAYS when VI < regime_ratio x average VI
    "z_lo": -2.2, "z_hi": 1.2,   # LONG allowed only when z_lo < Z < z_hi; SHORT uses the mirror (-z_hi < Z < -z_lo)
}
KEYS_NEEDED = ("ema_f", "ema_s", "sma", "sd", "z", "tsi", "tsl", "hist", "vi", "vi_avg")


# ---------------------------------------------------------------- candles in
def to_series(candles):
    """Candles -> {n, t, o, h, l, c}. Accepts dicts (timestamp or ts / open / high / low / close) or tuples (ts, o, h, l, c, v). Oldest first.
    A bad row (price <= 0, high < low, not a number, missing key) raises ValueError with the row's timestamp."""
    S = {"t": [], "o": [], "h": [], "l": [], "c": []}
    for x in candles:
        try:
            if isinstance(x, dict):
                t, o, h, l, c = x.get("timestamp", x.get("ts", 0)), x["open"], x["high"], x["low"], x["close"]
            else:
                t, o, h, l, c = x[0], x[1], x[2], x[3], x[4]
            t, o, h, l, c = int(t), float(o), float(h), float(l), float(c)
        except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError("bad candle row: %r" % (x,))
        if not all(_ok(v) for v in (o, h, l, c)) or c <= 0 or o <= 0 or h < l:
            raise ValueError("bad candle at %s" % t)
        for key, val in (("t", t), ("o", o), ("h", h), ("l", l), ("c", c)):
            S[key].append(val)
    S["n"] = len(S["c"])
    return S


# ---------------------------------------------------------------- features
def build_features(candles, cfg=None, tsi_pack=None):
    """All Special 13 + Special Master numbers for every candle. cfg = DEFAULTS with changes. Returns one dict of lists S (same length as the candles).
    Keys: ema_f, ema_s, gap_pct (cloud width in % of price), cloud (+1 fast above slow, -1 below), sma, sd, z, tsi, tsl, hist, vi, vi_avg,
    side_ok (True TRENDING / False SIDEWAYS / None UNKNOWN), long_x, short_x (Pine ta.crossover / ta.crossunder of EMA fast vs slow).
    tsi_pack = a (tsi, tsl, hist) tuple reused by the Part C search (TSI does not depend on the SD length that is searched)."""
    cf = dict(DEFAULTS)
    cf.update(cfg or {})
    S = to_series(candles)
    c, n = S["c"], S["n"]
    S["cfg"] = cf
    S["ema_f"], S["ema_s"] = ema(c, cf["fast_ema"]), ema(c, cf["slow_ema"])
    S["sma"], S["sd"] = sma(c, cf["sd_len"]), pstdev(c, cf["sd_len"])
    S["gap_pct"], S["cloud"], S["z"], S["vi"] = [None] * n, [None] * n, [None] * n, [None] * n
    for i in range(n):
        f, s, m, d = S["ema_f"][i], S["ema_s"][i], S["sma"][i], S["sd"][i]
        if f is not None and s is not None:
            S["gap_pct"][i] = abs(f - s) / c[i] * 100.0
            S["cloud"][i] = 1 if f > s else -1
        if m is not None and d is not None:
            S["z"][i] = (c[i] - m) / d if d > 0 else 0.0
            S["vi"][i] = d / m if m > 0 else None
    S["tsi"], S["tsl"], S["hist"] = tsi_pack if tsi_pack else tsi_series(c, cf["tsi_short"], cf["tsi_long"], cf["tsi_signal"])
    S["vi_avg"] = sma_any(S["vi"], cf["regime_win"])
    S["side_ok"] = [None] * n
    for i in range(n):
        if S["vi"][i] is not None and S["vi_avg"][i] is not None:
            S["side_ok"][i] = S["vi"][i] >= cf["regime_ratio"] * S["vi_avg"][i]
    S["long_x"], S["short_x"] = [False] * n, [False] * n
    for i in range(1, n):
        f, s, pf, ps = S["ema_f"][i], S["ema_s"][i], S["ema_f"][i - 1], S["ema_s"][i - 1]
        if None in (f, s, pf, ps):
            continue
        S["long_x"][i] = f > s and pf <= ps
        S["short_x"][i] = f < s and pf >= ps
    return S


def warmup_end(S):
    """First candle index where every number is there (the warm-up is over). n if never."""
    if "_fv" in S:
        return S["_fv"]
    S["_fv"] = next((i for i in range(S["n"]) if all(S[k][i] is not None for k in KEYS_NEEDED)), S["n"])
    return S["_fv"]


# ---------------------------------------------------------------- regime and bands
def regime_at(S, i):
    """'TRENDING' / 'SIDEWAYS' / 'UNKNOWN' at candle i. UNKNOWN is BLOCKED by every caller."""
    v = S["side_ok"][i] if 0 <= i < S["n"] else None
    return "UNKNOWN" if v is None else ("TRENDING" if v else "SIDEWAYS")


def regime_counts(S, lo=0, hi=None):
    """How many candles of each regime in [lo, hi). Handy for the 'market is X% sideways' line."""
    out = {"TRENDING": 0, "SIDEWAYS": 0, "UNKNOWN": 0}
    for i in range(max(0, lo), S["n"] if hi is None else min(hi, S["n"])):
        out[regime_at(S, i)] += 1
    return out


def sd_price(S, i, k):
    """Price of the +k / -k SD band at candle i (k = 1, 2, 3 or -1, -2, -3), like the Special 13 lines. None when not ready."""
    m, d = S["sma"][i], S["sd"][i]
    return None if m is None or d is None else m + k * d


def stop_price(S, i, side, z_mult=None):
    """Stop line: LONG = SMA - z_mult x SD, SHORT = SMA + z_mult x SD. None when not ready.
    It can be far from the entry; Part C measures the real distance in % and refuses a stop that is too wide for the capital."""
    m, d = S["sma"][i], S["sd"][i]
    if m is None or d is None:
        return None
    zm = S["cfg"]["z_mult"] if z_mult is None else z_mult
    return m - zm * d if side == "LONG" else m + zm * d


# ---------------------------------------------------------------- raw signal
def raw_signal(S, i):
    """EMA + TSI + Z confluence at candle i, BEFORE the regime guard and BEFORE any probability.
    Returns {"side": "LONG" | "SHORT" | None, "why": [plain lines], "z", "hist", "gap_pct", "regime"}. Never raises on a young series."""
    out = {"side": None, "why": [], "regime": regime_at(S, i), "z": None, "hist": None, "gap_pct": None}
    if not 1 <= i < S["n"] or i < warmup_end(S):
        out["why"].append("not enough candles yet (warm-up)")
        return out
    cf, z, h = S["cfg"], S["z"][i], S["hist"][i]
    out.update(z=z, hist=h, gap_pct=S["gap_pct"][i])
    if S["long_x"][i]:
        side = "LONG"
        out["why"].append("EMA%d crossed ABOVE EMA%d" % (cf["fast_ema"], cf["slow_ema"]))
        ok_h, ok_z = h > 0, cf["z_lo"] < z < cf["z_hi"]
    elif S["short_x"][i]:
        side = "SHORT"
        out["why"].append("EMA%d crossed BELOW EMA%d" % (cf["fast_ema"], cf["slow_ema"]))
        ok_h, ok_z = h < 0, -cf["z_hi"] < z < -cf["z_lo"]
    else:
        out["why"].append("no EMA cross on this candle")
        return out
    out["why"].append("TSI histogram %.2f %s" % (h, ("agrees (%s)" % ("rising" if side == "LONG" else "falling")) if ok_h else "does NOT agree"))
    out["why"].append("Z-Score %.2f is %s the allowed zone" % (z, "inside" if ok_z else "OUTSIDE"))
    if ok_h and ok_z:
        out["side"] = side
    return out


def latest_snapshot(candles, cfg=None):
    """One call for the live screen: features of a candle list -> the numbers of the NEWEST candle (or None if the warm-up is not over).
    {i, t, close, sd_len, z, hist, vi, vi_avg, regime, signal} - 'signal' is raw_signal() of the newest candle."""
    S = build_features(candles, cfg)
    i = S["n"] - 1
    if i < 1 or i < warmup_end(S):
        return None
    return {"i": i, "t": S["t"][i], "close": S["c"][i], "sd_len": S["cfg"]["sd_len"], "z": S["z"][i], "hist": S["hist"][i],
            "vi": S["vi"][i], "vi_avg": S["vi_avg"][i], "regime": regime_at(S, i), "signal": raw_signal(S, i)}
