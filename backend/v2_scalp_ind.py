"""v2_scalp_ind.py - Part 51: SCALP LAB 2 of 8 (backend, read-only maths). The numbers of the owner's TWO indicators, worked out from saved closed candles, for the Scalp Lab categories.
ONLY these (README4 section 4 / 7: no RSI, MACD, ADX, VWAP or any third indicator):
  1. MAIN CHART: EMA50 (Pine style, SMA-seeded, same as the bot's _compute_ema) and the SD bands = rolling mean +/- 1 / 2 / 3 population standard deviations of the last 200 closes.
  2. SPECIAL MASTER PANE: TSI slow 25 / 13 / 13 (long smoothing first, like Pine ta.tsi, OB / OS at +30 / -30), Z-score of the close over 200 candles, Z-SMA 200 (the black line), histogram = TSI - signal.
STARTING VALUES (NV = not validated): the exact Pine source of both indicators is not in the repo, so parity with the TradingView picture is NOT proven; the lengths sit in the constants below.
HONESTY RULES: (1) every number at candle i uses only candles 0..i (causal; verify_no_lookahead() proves it on a sample); (2) a number that does not have enough candles yet is None and state() says ready = False,
never 0 and never a guess; (3) the input must be ONE gap-free run of closed candles (v2_setup_finder.runs cuts at every gap); (4) nothing is saved, no network, no trading code (import guard in v2_replay.py).
Candle = (open_ts, o, h, l, c, v). Run (Termux, optional):  python3 backend/v2_scalp_ind.py [--data DIR] [--symbol BTCUSDT] [--interval 5m]  -> prints the newest state of that coin from the saved candles (read-only)."""
import argparse
import json
import math
import os
import sqlite3
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "v2_scalp_ind 1 (Part 51)"
EMA_LEN = 50
SD_LOOKBACK = 200
SD_MIN_N = 20                    # the SD band is drawn from 20 candles on (like the app's india_indicators), a short window is flagged by sd_n
Z_LEN = 200
ZSMA_LEN = 200
TSI_LONG, TSI_SHORT, TSI_SIGNAL = 25, 13, 13
TSI_OB, TSI_OS = 30.0, -30.0
INDICATORS_USED = ("ema50", "sd_band", "tsi", "z", "z_sma")


def need_candles():
    """How many candles a run needs before EVERY number of state() exists (the Z-SMA is the slowest)."""
    return Z_LEN + ZSMA_LEN - 1


def ema(values, n):
    """Pine-style EMA, seeded with the average of the first n valid values; None before that. None inside the series is skipped, like the app's Special Master."""
    out, k, prev, cnt, s = [None] * len(values), 2.0 / (n + 1), None, 0, 0.0
    for i, x in enumerate(values):
        if x is None:
            continue
        if prev is None:
            s += x
            cnt += 1
            if cnt >= n:
                prev = s / n
                out[i] = prev
        else:
            prev = x * k + prev * (1.0 - k)
            out[i] = prev
    return out


def roll_mean_sd(values, n, min_n=None):
    """Rolling mean and POPULATION standard deviation (like Pine ta.sma / ta.stdev) over the last n values. With min_n a shorter early window is used from min_n values on.
    A window that holds a None gives None. Sums are taken around the first value so a high price does not eat the precision."""
    m = len(values)
    mean, sd = [None] * m, [None] * m
    base = next((v for v in values if v is not None), 0.0)
    s = q = 0.0
    nn = 0
    for i, v in enumerate(values):
        if v is None:
            s = q = 0.0
            nn = 0
            continue
        x = v - base
        s += x
        q += x * x
        nn += 1
        if nn > n:
            o = values[i - n] - base
            s -= o
            q -= o * o
            nn -= 1
        need = n if min_n is None else min_n
        if nn >= need:
            mu = s / nn
            mean[i] = mu + base
            sd[i] = math.sqrt(max(q / nn - mu * mu, 0.0))
    return mean, sd


def sma(values, n):
    return roll_mean_sd(values, n)[0]


def compute(candles):
    """All series of ONE gap-free run of closed candles, each aligned 1:1 with the candles (None = not enough candles yet)."""
    c = [float(x[4]) for x in candles]
    n = len(c)
    e50 = ema(c, EMA_LEN)
    mean, sd = roll_mean_sd(c, SD_LOOKBACK, SD_MIN_N)
    zm, zs = roll_mean_sd(c, Z_LEN)
    z = [None if zm[i] is None or not zs[i] else (c[i] - zm[i]) / zs[i] for i in range(n)]
    zsma = sma(z, ZSMA_LEN)
    pc = [None] + [c[i] - c[i - 1] for i in range(1, n)]
    ap = [None if x is None else abs(x) for x in pc]
    num = ema(ema(pc, TSI_LONG), TSI_SHORT)
    den = ema(ema(ap, TSI_LONG), TSI_SHORT)
    tsi = [None if a is None or b is None or b == 0 else 100.0 * a / b for a, b in zip(num, den)]
    sig = ema(tsi, TSI_SIGNAL)
    hist = [None if a is None or b is None else a - b for a, b in zip(tsi, sig)]
    return {"close": c, "ema50": e50, "sd_mean": mean, "sd_std": sd, "z": z, "z_sma": zsma, "tsi": tsi, "tsi_signal": sig, "hist": hist}


def band_zone(close, mean, std):
    """Where the close stands in the SD bands, in whole standard deviations from the mean, cut at -3 and +3 (e.g. +1 = between the 1st and 2nd band above the mean). None if no band yet."""
    if mean is None or not std:
        return None
    return int(max(-3, min(3, math.trunc((close - mean) / std))))


def state(ind, i):
    """The reading of candle i from numbers up to candle i only. ready = every number exists. Words, not scores: no signal, no advice."""
    g = lambda k: ind[k][i]
    close, e, z, zs, t, sg = ind["close"][i], g("ema50"), g("z"), g("z_sma"), g("tsi"), g("tsi_signal")
    st = {"i": i, "close": close, "ema50": e, "z": z, "z_sma": zs, "tsi": t, "tsi_signal": sg, "hist": g("hist"),
          "price_vs_ema": None if e is None else ("ABOVE" if close > e else "BELOW" if close < e else "ON"),
          "band_zone": band_zone(close, g("sd_mean"), g("sd_std")),
          "z_vs_sma": None if z is None or zs is None else ("ABOVE" if z > zs else "BELOW" if z < zs else "ON"),
          "tsi_vs_signal": None if t is None or sg is None else ("ABOVE" if t > sg else "BELOW" if t < sg else "ON"),
          "tsi_zone": None if t is None else ("OB" if t >= TSI_OB else "OS" if t <= TSI_OS else "MID")}
    st["ready"] = all(st[k] is not None for k in ("ema50", "band_zone", "z", "z_sma", "tsi", "tsi_signal"))
    return st


def ema_cross(ind, i):
    """The bot's own rule on a CLOSED candle: the close crosses EMA50. -> "BUY", "SELL" or None (None also when EMA50 does not exist yet)."""
    if i < 1:
        return None
    a, b, c0, c1 = ind["ema50"][i - 1], ind["ema50"][i], ind["close"][i - 1], ind["close"][i]
    if a is None or b is None:
        return None
    if c0 <= a and c1 > b:
        return "BUY"
    if c0 >= a and c1 < b:
        return "SELL"
    return None


def verify_no_lookahead(candles, picks=None):
    """Proof that no number looks ahead: the value at candle i worked out from candles 0..i must equal the value from the whole run. -> list of (index, series) that differ (empty = causal)."""
    full = compute(candles)
    n = len(candles)
    picks = picks or sorted(set([k for k in (60, 150, 260, 410) if k < n] + [n - 1]))
    bad = []
    for i in picks:
        part = compute(candles[:i + 1])
        for k in ("ema50", "sd_mean", "sd_std", "z", "z_sma", "tsi", "tsi_signal", "hist"):
            a, b = full[k][i], part[k][i]
            if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-9 * max(1.0, abs(a))):
                bad.append((i, k))
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
    ind = compute(run)
    print(json.dumps({"version": VERSION, "symbol": a.symbol, "interval": a.interval, "run_candles": len(run), "need_candles": need_candles(), "state": state(ind, len(run) - 1)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
