"""
ai_ind_features.py - the "Special Master" (TSI + Z-score) and SD-band maths in plain Python,
so the AI can LABEL every EMA50-cross signal with what both indicators were showing.

Pure functions only: no network, no files, no trading code, no pandas/numpy (the app's
build rules). Nothing here is used by any trading decision - it only describes.

What is computed (same formulas as the Pine script "Special Master new"):
  Z-score  z = (close - SMA200) / STDEV200      (population stdev, like Pine and like
                                                 strategy.py's SD levels; the Pine plot
                                                 shows z * 10, here z is in sigma units)
  TSI      100 * EMA(EMA(change, long), short) / EMA(EMA(|change|, long), short)
           signal = EMA(TSI, signal_len); histogram ("Bj candle") = TSI - signal
           defaults = the "Slow" speed of the script: long 25, short 13, signal 13
  Reversal warning arrow (script section 2C):
           DOWN = histogram > 0 and shrinking after a peak AND z falling from > +1
           UP   = histogram < 0 and shrinking after a trough AND z rising from < -1
  SD shape: SD width % = stdev / mean * 100 (strategy.sd_width_pct), compared with 50 candles
           ago and with its own recent median -> expanding / shrinking / ballooned / tight.

Why Z can FALL while price RISES (and the reverse): Z = (close - mean200) / std200 is NOT price, it is the
distance from the 200-candle average measured in standard deviations. Over a window of k candles the change of Z
splits EXACTLY into three parts (see _z_split):
  price part  = (close_now - close_then) / std_now          price moved
  mean part   = -(mean_now - mean_then) / std_now           the 200-average moved (if it rose faster than price, Z falls)
  sd part     = (close_then - mean_then) * (1/std_now - 1/std_then)   the SD changed (after a spike std balloons, Z shrinks)
price + mean + sd == Z_now - Z_then. Labels z_why / z_why10 name the part that explains a price-vs-Z disagreement.

Small honest note: Pine seeds its EMA slightly differently in the first bars; with 400+
candles of history the difference is far below the 3rd decimal, but the numbers can differ
from TradingView in the last digit.
"""
import math
from bisect import bisect_right

TSI_SHORT = 13          # "Slow" speed in the Pine script
TSI_LONG = 25
TSI_SIGNAL = 13
Z_LEN = 200
EMA_LEN = 50
Z_WARN = 1.0            # script input "Z-Score Extreme Threshold"
OB = 30.0               # script default Ob / Os value (+30 / -30)
ZMA_LEN = 200           # the black line in the Z pane = 200-candle average of Z (app default 'Z-score SMA 2')
DIV_WIN = 10            # divergence: last 10 candles vs the 10 before them
ZE_FAST = 30            # Special Master v6: EMA of the Z close, fast / slow (the cloud sits between them)
ZE_SLOW = 50
MIN_BARS = 400          # candles needed before every feature (incl. SD width history) is valid


def ema(vals, n, seed="first"):
    """EMA over a list that may start with None. seed='first' = Pine ta.ema style
    (first value starts it), seed='sma' = strategy.py style (SMA of the first n)."""
    out = [None] * len(vals)
    start = 0
    while start < len(vals) and vals[start] is None:
        start += 1
    if start >= len(vals):
        return out
    k = 2.0 / (n + 1)
    if seed == "sma":
        if len(vals) - start < n:
            return out
        prev = sum(vals[start:start + n]) / n
        out[start + n - 1] = prev
        first = start + n
    else:
        prev = vals[start]
        out[start] = prev
        first = start + 1
    for i in range(first, len(vals)):
        prev = vals[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def build(candles, tsi_short=TSI_SHORT, tsi_long=TSI_LONG, tsi_sig=TSI_SIGNAL,
          z_len=Z_LEN, ema_len=EMA_LEN):
    """candles: CLOSED candles oldest-first, dicts with timestamp/open/high/low/close.
    -> dict of equal-length lists (None where not computable yet)."""
    n = len(candles)
    t = [int(c["timestamp"]) for c in candles]
    c = [float(x["close"]) for x in candles]
    h = [float(x["high"]) for x in candles]
    l = [float(x["low"]) for x in candles]

    # --- rolling mean / population stdev via prefix sums on centred values
    ref = c[0] if n else 0.0
    p1 = [0.0] * (n + 1)
    p2 = [0.0] * (n + 1)
    for i in range(n):
        d = c[i] - ref
        p1[i + 1] = p1[i] + d
        p2[i + 1] = p2[i] + d * d
    sma = [None] * n
    std = [None] * n
    z = [None] * n
    width = [None] * n
    for i in range(z_len - 1, n):
        s1 = p1[i + 1] - p1[i + 1 - z_len]
        s2 = p2[i + 1] - p2[i + 1 - z_len]
        m = s1 / z_len
        var = max(s2 / z_len - m * m, 0.0)
        sd = math.sqrt(var)
        mean = m + ref
        sma[i] = mean
        std[i] = sd
        if sd > 0:
            z[i] = (c[i] - mean) / sd
        if mean > 0:
            width[i] = sd / mean * 100.0

    # --- average of Z over ZMA_LEN candles (the black line in the Z pane)
    zsma = [None] * n
    zs_run, zs_cnt = 0.0, 0
    for i in range(n):
        if z[i] is None:
            continue
        zs_run += z[i]
        zs_cnt += 1
        if zs_cnt > ZMA_LEN:
            zs_run -= z[i - ZMA_LEN]
            zs_cnt -= 1
        if zs_cnt == ZMA_LEN:
            zsma[i] = zs_run / ZMA_LEN

    # --- Special Master v6: EMA 30 / EMA 50 of the Z close (forward-filled where a flat price gave no Z),
    #     cloud = fast vs slow, black BUY/SELL candle = the Z close crossing the SLOW EMA (Pine crossover / crossunder)
    zff, zlast = [], None
    for v in z:
        zlast = v if v is not None else zlast
        zff.append(zlast)
    zef, zes = ema(zff, ZE_FAST), ema(zff, ZE_SLOW)
    zxu, zxd = [False] * n, [False] * n
    for i in range(1, n):
        if None in (zff[i], zff[i - 1], zes[i], zes[i - 1]):
            continue
        if zff[i - 1] <= zes[i - 1] and zff[i] > zes[i]:
            zxu[i] = True
        elif zff[i - 1] >= zes[i - 1] and zff[i] < zes[i]:
            zxd[i] = True

    # --- EMA50 exactly as the bot computes it (SMA seeded)
    e50 = ema(c, ema_len, seed="sma")

    # --- TSI (Pine ta.tsi: long smoothing first, then short)
    pc = [None] + [c[i] - c[i - 1] for i in range(1, n)]
    apc = [None] + [abs(c[i] - c[i - 1]) for i in range(1, n)]
    num = ema(ema(pc, tsi_long), tsi_short)
    den = ema(ema(apc, tsi_long), tsi_short)
    tsi = [None] * n
    for i in range(n):
        if num[i] is not None and den[i] is not None and den[i] != 0:
            tsi[i] = 100.0 * num[i] / den[i]
    tsl = ema(tsi, tsi_sig)
    diff = [None if (tsi[i] is None or tsl[i] is None) else tsi[i] - tsl[i] for i in range(n)]

    # --- reversal warning arrows (script section 2C), per bar
    wdn = [0] * n
    wup = [0] * n
    for i in range(2, n):
        d0, d1, d2 = diff[i], diff[i - 1], diff[i - 2]
        z0, z1 = z[i], z[i - 1]
        if None in (d0, d1, d2, z0, z1):
            continue
        weak_bull = d0 > 0 and d0 < d1 and d1 >= d2
        weak_bear = d0 < 0 and d0 > d1 and d1 <= d2
        if weak_bull and z0 < z1 and z1 > Z_WARN:
            wdn[i] = 1
        if weak_bear and z0 > z1 and z1 < -Z_WARN:
            wup[i] = 1

    # --- EMA50 crosses (for "opposite cross" exits and candidate detection)
    xup = [False] * n
    xdn = [False] * n
    for i in range(1, n):
        if e50[i] is None or e50[i - 1] is None:
            continue
        xup[i] = c[i - 1] <= e50[i - 1] and c[i] > e50[i]
        xdn[i] = c[i - 1] >= e50[i - 1] and c[i] < e50[i]

    return {"n": n, "t": t, "o": [float(x["open"]) for x in candles], "h": h, "l": l, "c": c,
            "sma": sma, "std": std, "z": z, "zsma": zsma, "width": width, "e50": e50,
            "tsi": tsi, "tsl": tsl, "diff": diff, "wdn": wdn, "wup": wup,
            "xup": xup, "xdn": xdn, "zef": zef, "zes": zes, "zxu": zxu, "zxd": zxd}


def _r(v, nd=3):
    return None if v is None else round(float(v), nd)


def _median(vals):
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2.0


def _z_split(S, i, k):
    """(price part, mean part, sd part) of Z[i] - Z[i-k] - they add up to it exactly. None if not computable."""
    c, sma, std = S["c"], S["sma"], S["std"]
    j = i - k
    if j < 0 or None in (sma[i], std[i], sma[j], std[j]) or not std[i] or not std[j]:
        return None
    a0 = c[j] - sma[j]
    pp = (c[i] - c[j]) / std[i]
    pm = -(sma[i] - sma[j]) / std[i]
    ps = a0 * (1.0 / std[i] - 1.0 / std[j])
    return pp, pm, ps


def own_features(S, i):
    """Raw numbers describing both indicators + SD shape at candle i (own timeframe).
    None if there is not enough history (needs i >= MIN_BARS - 1)."""
    if i < MIN_BARS - 1 or i >= S["n"]:
        return None
    z, tsi, tsl, diff, width = S["z"], S["tsi"], S["tsl"], S["diff"], S["width"]
    std, c = S["std"], S["c"]
    if None in (z[i], tsi[i], tsl[i], diff[i], width[i], std[i]):
        return None
    zs20 = [z[j] for j in range(i - 19, i + 1) if z[j] is not None]
    wlast = [width[j] for j in range(i - 199, i + 1)]
    wmed = _median(wlast)
    w50 = width[i - 50]
    # bars since TSI crossed its signal line
    since = 99
    for j in range(i, max(i - 99, 1), -1):
        a, b = diff[j], diff[j - 1]
        if a is None or b is None:
            break
        if (a > 0) != (b > 0):
            since = i - j
            break
    sd_i = std[i] if std[i] else None
    run20 = (c[i] - c[i - 20]) / sd_i if sd_i else None
    run50 = (c[i] - c[i - 50]) / sd_i if sd_i else None
    return {
        "z": _r(z[i]), "zd3": _r(z[i] - z[i - 3]) if z[i - 3] is not None else None,
        "zmax20": _r(max(abs(x) for x in zs20)) if zs20 else None,
        "tsi": _r(tsi[i], 2), "tsl": _r(tsl[i], 2), "dif": _r(diff[i], 2),
        "dd1": _r(abs(diff[i]) - abs(diff[i - 1]), 2) if diff[i - 1] is not None else None,
        "wd": 1 if any(S["wdn"][i - 2:i + 1]) else 0,
        "wu": 1 if any(S["wup"][i - 2:i + 1]) else 0,
        "tx": since,
        "wn": _r(width[i], 4), "wr50": _r(width[i] / w50, 3) if w50 else None,
        "wrel": _r(width[i] / wmed, 3) if wmed else None,
        "run20": _r(run20, 2), "run50": _r(run50, 2),
        **_z_why_numbers(S, i),
        **_extra_numbers(S, i),
        **_zema_numbers(S, i),
    }


def _extra_numbers(S, i):
    """Phase-1 extras (all optional - a missing number simply gives no label):
    zgap  = Z minus its 200-candle average (black line in the Z pane)
    zmad  = how that average moved over 5 candles
    dvg   = divergence between price and Z: +1 bullish (price lower low, Z higher low),
            -1 bearish (price higher high, Z lower high), 0 none. Last 10 candles vs the 10 before.
    rng30 = high-low range of the last 30 candles, in SD units (small = sideways)
    es10  = EMA50 change over 10 candles, in SD units (near 0 = EMA flat)
    ed    = (close - EMA50) / SD: how far price is from the EMA50 (only on signals recorded after this was added)"""
    out = {}
    try:
        z, zsma, c, h, l, e50, std = S["z"], S["zsma"], S["c"], S["h"], S["l"], S["e50"], S["std"]
        if z[i] is not None and zsma[i] is not None:
            out["zgap"] = _r(z[i] - zsma[i])
            if zsma[i - 5] is not None:
                out["zmad"] = _r(zsma[i] - zsma[i - 5], 4)
        a0, a1, b0, b1 = i - DIV_WIN + 1, i + 1, i - 2 * DIV_WIN + 1, i - DIV_WIN + 1
        zn, zp = z[a0:a1], z[b0:b1]
        if None not in zn and None not in zp and len(zn) == len(zp) == DIV_WIN:
            dv = 0
            if max(c[a0:a1]) > max(c[b0:b1]) and max(zn) < max(zp) - 0.1:
                dv = -1
            elif min(c[a0:a1]) < min(c[b0:b1]) and min(zn) > min(zp) + 0.1:
                dv = 1
            out["dvg"] = dv
        sd = std[i]
        if sd:
            out["rng30"] = _r((max(h[i - 29:i + 1]) - min(l[i - 29:i + 1])) / sd, 2)
            if e50[i] is not None and e50[i - 10] is not None:
                out["es10"] = _r((e50[i] - e50[i - 10]) / sd, 3)
            if e50[i] is not None:
                out["ed"] = _r((c[i] - e50[i]) / sd, 3)      # price minus EMA50, in SD units (new signals only)
    except Exception:
        pass
    return out


def _zema_numbers(S, i):
    """Special Master v6 numbers (raw, no rule): zef/zes = Z-EMA 30 / 50, zcl = cloud width (fast minus slow, + = green cloud),
    zcs / zcf = Z close minus slow / fast EMA, zbx = candles since the Z close last crossed the slow EMA
    (+n after a BUY cross, -n after a SELL cross, 0 = this candle is a black candle, 99 = none in the last 99), zbn = 1 / -1 on this candle."""
    out = {}
    try:
        zf, zs, z = S.get("zef"), S.get("zes"), S["z"]
        if zf is None or zf[i] is None or zs[i] is None:
            return out
        out["zef"], out["zes"] = _r(zf[i]), _r(zs[i])
        out["zcl"] = _r(zf[i] - zs[i])
        if z[i] is not None:
            out["zcs"], out["zcf"] = _r(z[i] - zs[i]), _r(z[i] - zf[i])
        out["zbx"], out["zbn"] = 99, 0
        for j in range(i, max(i - 99, 0), -1):
            if S["zxu"][j] or S["zxd"][j]:
                sgn = 1 if S["zxu"][j] else -1
                out["zbx"] = sgn * (i - j)
                out["zbn"] = sgn if j == i else 0
                break
    except Exception:
        pass
    return out


def _z_why_numbers(S, i):
    """zp/zm/zs = price / mean / sd part of the Z change over 3 candles; zp10/zm10/zs10 = over 10 candles."""
    out = {}
    for k, suffix in ((3, "3"), (10, "10")):
        sp = _z_split(S, i, k)
        if sp:
            out["zp" + suffix], out["zm" + suffix], out["zs" + suffix] = _r(sp[0]), _r(sp[1]), _r(sp[2])
    return out


def _z_why_label(zp, zm, zs):
    """One self-describing label: does Z follow price, or disagree - and why."""
    if zp is None or zm is None or zs is None:
        return None
    dz = zp + zm + zs
    eps = 0.15
    if abs(dz) < eps and abs(zp) < eps:
        return "Z flat, price flat"
    if zp > 0.05 and dz < -eps:
        return ("price up / Z down: average catching up" if zm <= zs
                else "price up / Z down: SD expanding")
    if zp < -0.05 and dz > eps:
        return ("price down / Z up: average catching down" if zm >= zs
                else "price down / Z up: SD expanding")
    return "Z follows price"


def ctx_features(S, i):
    """Compact higher-timeframe context at candle i of that timeframe's series."""
    if S is None or i is None or i < 120 or i >= S["n"]:
        return None
    e, c, tsi, tsl, z = S["e50"], S["c"], S["tsi"], S["tsl"], S["z"]
    if e[i] is None or e[i - 3] is None or tsi[i] is None or tsl[i] is None:
        return None
    return {"p": 1 if c[i] > e[i] else -1,
            "s": _r((e[i] - e[i - 3]) / e[i - 3] * 100.0, 4) if e[i - 3] else 0.0,
            "d": 1 if tsi[i] > tsl[i] else -1,
            "z": _r(z[i]) if z[i] is not None else None}


def ctx_index(S, t_close_ms, tf_ms):
    """Index of the last candle of S that was already CLOSED at t_close_ms (or None)."""
    if S is None:
        return None
    closes = S.get("_close_ms")
    if closes is None:
        closes = S["_close_ms"] = [x + tf_ms - 1 for x in S["t"]]
    j = bisect_right(closes, t_close_ms) - 1
    return j if j >= 0 else None


# ---------------------------------------------------------------- labels
def labels(action, ind, ctx, sig=None):
    """{kind: self-describing label} - the 'facts' the miner combines. Direction-aware:
    higher-timeframe facts say WITH / AGAINST the trade, not up / down."""
    f = {}
    if not ind:
        return f
    long_ = str(action).upper() in ("BUY", "LONG")
    dirn = 1 if long_ else -1
    z = ind.get("z")
    if z is not None:
        f["z_zone"] = ("Z below -2s" if z < -2 else "Z -2..-1s" if z < -1 else
                       "Z -1..+1s" if z <= 1 else "Z +1..+2s" if z <= 2 else "Z above +2s")
    zd = ind.get("zd3")
    if zd is not None:
        f["z_move"] = "Z rising" if zd > 0.15 else "Z falling" if zd < -0.15 else "Z flat"
    why3 = _z_why_label(ind.get("zp3"), ind.get("zm3"), ind.get("zs3"))
    if why3:
        f["z_why"] = why3
    why10 = _z_why_label(ind.get("zp10"), ind.get("zm10"), ind.get("zs10"))
    if why10:
        f["z_why10"] = why10
    zm = ind.get("zmax20")
    if zm is not None:
        f["z_recent"] = "Z was stretched 2s+ lately" if zm >= 2 else "Z not stretched lately"
    tsi, tsl = ind.get("tsi"), ind.get("tsl")
    if tsi is not None:
        f["tsi_pos"] = ("TSI over +30" if tsi > OB else "TSI 0..+30" if tsi >= 0 else
                        "TSI -30..0" if tsi >= -OB else "TSI under -30")
    if tsi is not None and tsl is not None:
        f["tsi_vs_sig"] = "TSI above signal" if tsi > tsl else "TSI below signal"
        f["tsi_4zone"] = ("sig+ and TSI under it" if (tsl > 0 and tsi < tsl) else
                          "sig+ and TSI over it" if tsl > 0 else
                          "sig- and TSI under it" if tsi < tsl else "sig- and TSI over it")
    dd = ind.get("dd1")
    if dd is not None:
        f["momentum"] = "momentum growing" if dd > 0 else "momentum fading"
    if ind.get("wd") or ind.get("wu"):
        f["warning"] = "reversal arrow DOWN" if ind.get("wd") else "reversal arrow UP"
    else:
        f["warning"] = "no reversal arrow"
    wr50 = ind.get("wr50")
    if wr50 is not None:
        f["sd_shape"] = "SD expanding" if wr50 > 1.2 else "SD shrinking" if wr50 < 0.85 else "SD steady"
    wrel = ind.get("wrel")
    if wrel is not None:
        f["sd_size"] = "SD ballooned" if wrel > 1.5 else "SD tight" if wrel < 0.7 else "SD normal"
    zg = ind.get("zgap")
    if zg is not None:
        f["zma_vs_trade"] = "Z avg-line WITH trade" if zg * dirn > 0 else "Z avg-line AGAINST trade"
    dvg = ind.get("dvg")
    if dvg is not None:
        f["z_div"] = ("no Z divergence" if dvg == 0 else
                      "Z divergence WITH trade" if dvg * dirn > 0 else "Z divergence AGAINST trade")
    rng, es = ind.get("rng30"), ind.get("es10")
    if rng is not None and es is not None:
        f["move"] = ("sideways (small range, flat EMA)" if (rng < 1.0 and abs(es) < 0.15) else
                     "trending WITH trade" if (abs(es) >= 0.4 and es * dirn > 0) else
                     "trending AGAINST trade" if abs(es) >= 0.4 else "slow / mixed move")
    if z is not None and tsi is not None and tsl is not None:
        zw, tw = z * dirn > 0, (tsi - tsl) * dirn > 0
        f["z_tsi"] = ("Z and TSI both WITH trade" if (zw and tw) else
                      "Z and TSI both AGAINST trade" if (not zw and not tw) else
                      "Z WITH but TSI AGAINST" if zw else "Z AGAINST but TSI WITH")
    if tsi is not None and tsl is not None:
        tz, sz = tsi * dirn > 0, tsl * dirn > 0          # the zero line of the TSI pane
        f["tsi_zero"] = ("TSI and signal both on trade side of 0" if (tz and sz) else
                         "TSI and signal both on wrong side of 0" if (not tz and not sz) else
                         "TSI and signal on different sides of 0")
    zcl, zcs, zbx = ind.get("zcl"), ind.get("zcs"), ind.get("zbx")
    if zcl is not None:                                   # Special Master v6: Z-EMA 30/50 cloud and the black BUY/SELL candle
        f["z_cloud"] = "Z cloud WITH trade" if zcl * dirn > 0 else "Z cloud AGAINST trade"
    if zcs is not None:
        f["z_vs_ema"] = "Z close WITH trade side of its slow EMA" if zcs * dirn > 0 else "Z close on the wrong side of its slow EMA"
    if zbx is not None:
        if zbx == 99:
            f["z_black"] = "no Z black candle lately"
        else:
            sgn = ind.get("zbn") or (1 if zbx > 0 else -1)
            if zbx == 0:
                sgn = ind.get("zbn") or 1
            near = "now" if zbx == 0 else ("1-3 candles ago" if abs(zbx) <= 3 else "4-10 candles ago" if abs(zbx) <= 10 else "long ago")
            f["z_black"] = f"Z black candle {'WITH' if sgn * dirn > 0 else 'AGAINST'} trade, {near}"
    ed = ind.get("ed")
    if ed is not None:
        f["ema_dist"] = ("price near EMA50" if abs(ed) < 0.3 else
                         "price far from EMA50 (WITH trade)" if (ed * dirn >= 1.0) else
                         "price far from EMA50 (AGAINST trade)" if (ed * dirn <= -1.0) else
                         "price a bit away from EMA50")
    r20 = ind.get("run20")
    if r20 is not None:
        f["phase"] = "after a pump" if r20 >= 2 else "after a dump" if r20 <= -2 else "no big run"
    f["tsi_vs_trade"] = ("TSI with trade" if ((tsi or 0) - (tsl or 0)) * dirn > 0 else "TSI against trade") \
        if (tsi is not None and tsl is not None) else None
    if f["tsi_vs_trade"] is None:
        del f["tsi_vs_trade"]
    for tf, cx in (ctx or {}).items():
        if not cx:
            continue
        name = tf
        f[f"htf_{tf}"] = (f"{name} trend WITH trade" if cx["p"] * dirn > 0 else f"{name} trend AGAINST trade")
        s = cx.get("s") or 0.0
        if abs(s) < 0.005:
            f[f"htfs_{tf}"] = f"{name} EMA flat"
        else:
            f[f"htfs_{tf}"] = f"{name} EMA slope WITH" if s * dirn > 0 else f"{name} EMA slope AGAINST"
        f[f"htft_{tf}"] = f"{name} TSI WITH" if cx["d"] * dirn > 0 else f"{name} TSI AGAINST"
    # multi-timeframe AGREEMENT as its own fact (separate from each single timeframe above)
    votes = [cx["p"] * dirn for cx in (ctx or {}).values() if cx]
    if len(votes) >= 2:
        w = sum(1 for v in votes if v > 0)
        f["mtf_agree"] = ("higher TFs all WITH trade" if w == len(votes) else
                          "higher TFs all AGAINST trade" if w == 0 else "higher TFs mixed")
    if sig:
        if sig.get("zone"):
            f["sd_zone"] = str(sig["zone"])
        if sig.get("turn"):
            f["ema_turn"] = str(sig["turn"])
        cn = sig.get("cross_n")
        if cn is not None:
            f["regime"] = "clean (1 cross)" if cn <= 1 else "choppy (3+ crosses)" if cn >= 3 else "mixed (2 crosses)"
        vr = sig.get("vol")
        if vr is not None:
            f["volume"] = "volume surge" if vr >= 1.5 else "normal volume"
    return f
