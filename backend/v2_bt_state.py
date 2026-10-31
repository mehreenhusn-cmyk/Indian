"""v2_bt_state.py - Part 84b: BRAIN TRADER 3 of 8 (backend, read-only maths). The TAGS of one closed candle: what the owner's TWO indicators say and what kind of market it is, in plain labels.
It does NOT work out any indicator itself: EMA50, SD bands, TSI 25/13/13, Z-score, Z-SMA come from v2_scalp_ind.compute() (Part 51). No third indicator (README5: only the two families).
Tags: sd_zone (8 zones, in SD units), SD width + expanding / contracting + SQUEEZE, EMA50 slope + distance, TSI state, Z state (zone, toward / away from zero, vs Z-SMA), price-Z divergence,
TSI + Z agreement, the bot's own EMA cross (signal), VOLUME tag (HIGH / NORMAL / LOW = a note only, never a rule; owner said yes 1 Nov), move over 12 candles, and ONE market_state:
  DATA_NOT_READY, PUMP, DUMP, BREAKOUT, BREAKDOWN, CONSOLIDATION, TRENDING_UP, TRENDING_DOWN, SIDEWAYS, TRANSITION.
Every limit below is a STARTING value (NV, not validated); Part 89 studies them on the owner's data. The labels are words, not advice: nothing here is a signal or an order.
HONESTY RULES: every tag at candle i uses candles 0..i only (verify_no_lookahead() proves it on a sample); a tag without enough candles is None and the state is DATA_NOT_READY, never a guess (needs about 399 candles of one gap-free run).
Candle = (open_ts, o, h, l, c, v). No network, no write, no trading import. Run (Termux, optional):  python3 backend/v2_bt_state.py [--symbol XYZUSDT] [--interval 5m]  -> the newest tags of that coin."""
import argparse
import bisect
import json
import math
import os
import sqlite3
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_scalp_ind as IND

VERSION = "v2_bt_state 1 (Part 84b)"
VOLUME_TAG = True
LIM = {"slope_bars": 5, "slope_flat": 0.15, "width_bars": 20, "width_up": 1.10, "width_down": 0.90, "squeeze_rank": 0.20, "squeeze_hist": 100, "squeeze_window": 200,
       "squeeze_memory": 20, "move_bars": 12, "pump_sd": 3.0, "div_bars": 12, "mom_bars": 3, "tsi_near_zero": 10.0, "vol_bars": 20, "vol_high": 1.5, "vol_low": 0.6}
ZONE_NAMES = {-3: "-3_-2", -2: "-2_-1", -1: "-1_0", 0: "0_+1", 1: "+1_+2", 2: "+2_+3"}
STATES = ("DATA_NOT_READY", "PUMP", "DUMP", "BREAKOUT", "BREAKDOWN", "CONSOLIDATION", "TRENDING_UP", "TRENDING_DOWN", "SIDEWAYS", "TRANSITION")


def _r(x, d=4):
    return None if x is None else round(float(x), d)


def sd_units(ind, i):
    m, s = ind["sd_mean"][i], ind["sd_std"][i]
    return None if m is None or not s else (ind["close"][i] - m) / s


def zone_name(u):
    """Eight zones: below -3, -3 to -2, -2 to -1, -1 to mean, mean to +1, +1 to +2, +2 to +3, above +3."""
    if u is None:
        return None
    if u < -3:
        return "BELOW_-3"
    if u >= 3:
        return "ABOVE_+3"
    return ZONE_NAMES[int(math.floor(u))]


def width_pct(ind, i):
    m, s = ind["sd_mean"][i], ind["sd_std"][i]
    return None if m is None or s is None or m == 0 else s / abs(m) * 100.0


def squeeze_series(widths):
    """True where the SD width is in the lowest 20% of its own last 200 values (needs 100 values first). Causal: a value at i sees only widths up to i."""
    out, win, srt = [None] * len(widths), [], []
    for i, x in enumerate(widths):
        if x is None:
            continue
        win.append(x)
        bisect.insort(srt, x)
        if len(win) > LIM["squeeze_window"]:
            srt.pop(bisect.bisect_left(srt, win.pop(0)))
        if len(win) >= LIM["squeeze_hist"]:
            out[i] = bisect.bisect_right(srt, x) / float(len(win)) <= LIM["squeeze_rank"]
    return out


def prepare(candles):
    """ONE gap-free run of closed candles -> a context. Work out once, then ask tags(ctx, i) for any candle."""
    ind = IND.compute(candles)
    w = [width_pct(ind, i) for i in range(len(candles))]
    return {"c": candles, "ind": ind, "w": w, "sq": squeeze_series(w)}


def _width_state(ctx, i):
    w, k = ctx["w"], LIM["width_bars"]
    prev = [x for x in w[max(0, i - k):i] if x is not None]
    if w[i] is None or len(prev) < k // 2 or sum(prev) == 0:
        return None
    ratio = w[i] / (sum(prev) / len(prev))
    return "EXPANDING" if ratio >= LIM["width_up"] else "CONTRACTING" if ratio <= LIM["width_down"] else "STEADY"


def _slope(ind, i):
    k = LIM["slope_bars"]
    e, s = ind["ema50"][i], ind["sd_std"][i]
    if i < k or e is None or ind["ema50"][i - k] is None or not s:
        return None
    return (e - ind["ema50"][i - k]) / s


def _tsi(ind, i):
    t, sg, k = ind["tsi"][i], ind["tsi_signal"][i], LIM["mom_bars"]
    if t is None or sg is None or i < k or ind["tsi"][i - k] is None:
        return None, None
    side = "ABOVE" if t > sg else "BELOW" if t < sg else "ON"
    zone = "OB" if t >= IND.TSI_OB else "OS" if t <= IND.TSI_OS else "MID"
    return side + "_" + ("RISING" if t > ind["tsi"][i - k] else "FALLING"), zone


def _z(ind, i):
    z, zs, k = ind["z"][i], ind["z_sma"][i], LIM["mom_bars"]
    if z is None or i < k or ind["z"][i - k] is None:
        return None, None, None
    zone = "EXTREME_HIGH" if z >= 2 else "HIGH" if z >= 1 else "NEUTRAL" if z > -1 else "LOW" if z > -2 else "EXTREME_LOW"
    way = "TOWARD_ZERO" if abs(z) < abs(ind["z"][i - k]) else "AWAY_FROM_ZERO"
    return zone, way, (None if zs is None else "ABOVE" if z > zs else "BELOW" if z < zs else "ON")


def _divergence(ind, i):
    """Price makes a new high of the last 12 candles but Z does not = BEARISH; new low but Z does not = BULLISH. A tag only: the owner knows it is sometimes just sideways."""
    k = LIM["div_bars"]
    if i < k:
        return None
    rng = range(i - k + 1, i + 1)
    c, z = [ind["close"][j] for j in rng], [ind["z"][j] for j in rng]
    if any(x is None for x in z):
        return None
    if c[-1] >= max(c) and z[-1] < max(z[:-1]):
        return "BEARISH"
    if c[-1] <= min(c) and z[-1] > min(z[:-1]):
        return "BULLISH"
    return "NONE"


def _volume(candles, i):
    k = LIM["vol_bars"]
    if not VOLUME_TAG or i < k:
        return None
    avg = sum(float(x[5]) for x in candles[i - k:i]) / k
    if avg <= 0:
        return None
    r = float(candles[i][5]) / avg
    return "HIGH" if r >= LIM["vol_high"] else "LOW" if r <= LIM["vol_low"] else "NORMAL"


def _market_state(t, ctx, i):
    need = ("sd_units", "slope_sd", "tsi_state", "z_zone", "z_vs_sma", "width_state", "squeeze")
    if any(t[k] is None for k in need) or ctx["ind"]["ema50"][i] is None:
        return "DATA_NOT_READY"
    u, mv = t["sd_units"], t["move_sd"]
    if mv is not None and abs(mv) >= LIM["pump_sd"]:
        return "PUMP" if mv > 0 else "DUMP"
    recent_sq = any(ctx["sq"][j] for j in range(max(0, i - LIM["squeeze_memory"]), i + 1))
    if recent_sq and t["width_state"] == "EXPANDING" and abs(u) >= 1.0:
        return "BREAKOUT" if u > 0 else "BREAKDOWN"
    flat = abs(t["slope_sd"]) < LIM["slope_flat"]
    if t["squeeze"] and flat:
        return "CONSOLIDATION"
    if not flat and t["slope_sd"] > 0 and t["price_vs_ema"] == "ABOVE" and u > 0:
        return "TRENDING_UP"
    if not flat and t["slope_sd"] < 0 and t["price_vs_ema"] == "BELOW" and u < 0:
        return "TRENDING_DOWN"
    return "SIDEWAYS" if flat and abs(u) < 1.0 else "TRANSITION"


def tags(ctx, i):
    """All tags of candle i from candles 0..i only. JSON-safe (rounded). market_state is ONE of STATES."""
    ind, c = ctx["ind"], ctx["c"]
    u, k = sd_units(ind, i), LIM["move_bars"]
    e, s = ind["ema50"][i], ind["sd_std"][i]
    slope = _slope(ind, i)
    tsi, tzone = _tsi(ind, i)
    zz, zway, zsma = _z(ind, i)
    bull = None if ind["tsi"][i] is None or ind["tsi_signal"][i] is None or ind["z"][i] is None or ind["z_sma"][i] is None else \
        (ind["tsi"][i] > ind["tsi_signal"][i], ind["z"][i] > ind["z_sma"][i])
    t = {"i": i, "open_ts": int(c[i][0]), "close": _r(ind["close"][i], 8), "sd_units": _r(u, 3), "sd_zone": zone_name(u), "sd_width_pct": _r(ctx["w"][i], 3),
         "width_state": _width_state(ctx, i), "squeeze": ctx["sq"][i],
         "price_vs_ema": None if e is None else "ABOVE" if ind["close"][i] > e else "BELOW" if ind["close"][i] < e else "ON",
         "ema_dist_sd": _r(None if e is None or not s else (ind["close"][i] - e) / s, 3), "slope_sd": _r(slope, 3),
         "ema_slope": None if slope is None else "FLAT" if abs(slope) < LIM["slope_flat"] else "UP" if slope > 0 else "DOWN",
         "tsi_state": tsi, "tsi_zone": tzone, "tsi_near_zero": None if ind["tsi"][i] is None else abs(ind["tsi"][i]) < LIM["tsi_near_zero"],
         "z_zone": zz, "z_way": zway, "z_vs_sma": zsma, "divergence": _divergence(ind, i),
         "agreement": None if bull is None else "AGREE_UP" if all(bull) else "AGREE_DOWN" if not any(bull) else "DISAGREE",
         "signal": IND.ema_cross(ind, i), "volume_tag": _volume(c, i),
         "move_sd": _r(None if i < k or not s else (ind["close"][i] - ind["close"][i - k]) / s, 3)}
    t["market_state"] = _market_state(t, ctx, i)
    t["ready"] = t["market_state"] != "DATA_NOT_READY"
    return t


def verify_no_lookahead(candles, picks=None):
    """Proof: the tags at candle i from candles 0..i must equal the tags from the whole run. -> list of (index, tag) that differ (empty = causal)."""
    full = prepare(candles)
    n = len(candles)
    picks = picks or sorted(set([x for x in (60, 150, 260, 410) if x < n] + [n - 1]))
    bad = []
    for i in picks:
        a, b = tags(full, i), tags(prepare(candles[:i + 1]), i)
        bad += [(i, k) for k in a if a[k] != b[k] and not (isinstance(a[k], float) and abs(a[k] - b[k]) < 1e-3)]
    return bad


def main(argv=None):
    import v2_defs as D
    import v2_setup_finder as SF
    import v2_store as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="5m", choices=("3m", "5m"))
    a = ap.parse_args(argv)
    path = S.store_path(a.data)
    if not os.path.isfile(path):
        print(json.dumps({"ready": False, "note": "the market store is not created yet"}))
        return 0
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    try:
        good, _bad = D.clean_candles(D.candles_from_store(con, a.symbol, a.interval, 0, 2 ** 31), a.interval)
    finally:
        con.close()
    runs = SF.runs(good, a.interval)
    if not runs:
        print(json.dumps({"ready": False, "note": "no saved candles for this coin"}))
        return 0
    run = runs[-1]
    print(json.dumps({"version": VERSION, "symbol": a.symbol, "interval": a.interval, "run_candles": len(run), "need_candles": IND.need_candles(),
                      "tags": tags(prepare(run), len(run) - 1)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
