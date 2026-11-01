"""owl_sniper_engine.py - OwlSniper Parts S1 + S2 of 7: the INDICATOR + REGIME core + the HONEST TEST (fees, train / test days, SD-length search) (backend, plain python, NO numpy / pandas / sklearn / optuna).
Standalone and read-only. It imports nothing from the bot, the Brain or Dual Bot, and no old file imports it. Nothing is traded, nothing is saved here.
Same maths as the two Pine scripts, so the numbers on the chart and in the engine agree:
  Special 13        (main chart)  SMA + population SD of close (length `len`, today 200), EMA30 / EMA50 cloud, +-1/2/3 SD price bands.
  Special Master new (lower deck)  Z = (close - SMA) / SD  (zLen, today 200), TSI = ta.tsi(close, 5, 25) * 100, signal = EMA(TSI, 14), histogram = TSI - signal.
SD is the POPULATION SD (divide by n), exactly like Pine ta.stdev, NOT the sample SD of pandas.
EXCLUDED on purpose: CHoCH and BOS (market structure). They are never computed, mapped or used here.
Regime (sideways guard): Volatility Index VI = SD / SMA (thickness of the SD band against its mean line). The market is SIDEWAYS when VI is below
regime_ratio x its own average of the last regime_win candles. Not enough data = UNKNOWN, and UNKNOWN is treated as blocked (the safe side).
Part S2 (this file): trade simulator with USDT fees + slippage, train / test split by whole UTC DAYS (older days = TRAIN, newer 30% = TEST, same as v2_replay HOLDOUT), SD-length search.
The search only ever looks at TRAIN days; only the one winner is then shown the TEST days once. "200 is wrong" is said ONLY when the winner also beats 200 on the TEST days, with enough trades and a t-stat >= 2. Else: NOT PROVEN and the settings stay as they are.
Part S3 adds the win-probability, the 85% floor and the Insight Report. Feed candles of ONE gap-free run per coin (Part S4 does that).
Candles in: list of dicts (scan_lab style: timestamp / open / high / low / close) OR tuples (open_ts, o, h, l, c, v) (v2_replay style). Oldest first."""
import math
import random

VERSION = "owl_sniper_engine 2 (Part S2)"
EXCLUDED = ("CHoCH", "BOS")                      # market structure is switched OFF for ever in this module

DEFAULTS = {
    "sd_len": 200,           # Special 13 `len` and Special Master `zLen` (today 200; Part S2 tests 20..200)
    "fast_ema": 30, "slow_ema": 50,              # EMA cloud of Special 13
    "z_mult": 2.0,           # stop line = SMA -+ z_mult x SD
    "tsi_long": 25, "tsi_short": 5, "tsi_signal": 14,   # Special Master new: longfLen 25, shortfLen 5, signalfLen 14
    "regime_win": 50,        # candles used for the average Volatility Index
    "regime_ratio": 1.0,     # SIDEWAYS when VI < regime_ratio x average VI (Part S2 tests this on the train days only)
    "z_lo": -2.2, "z_hi": 1.2,   # a LONG is allowed only when z_lo < Z < z_hi; a SHORT uses the mirror (-z_hi < Z < -z_lo)
}


# ---------------------------------------------------------------- indicators (plain python)
def sma(c, n):
    """Simple moving average. None until n values are there."""
    out, run = [None] * len(c), 0.0
    for i, x in enumerate(c):
        run += x
        if i >= n:
            run -= c[i - n]
        if i >= n - 1:
            out[i] = run / n
    return out


def ema_any(x, n):
    """EMA that also accepts leading None values (same seed as scan_lab.ema: the SMA of the first n real values). Gaps after the start are not allowed."""
    out = [None] * len(x)
    start = next((i for i, v in enumerate(x) if v is not None), None)
    if start is None or len(x) - start < n:
        return out
    k = 2.0 / (n + 1)
    v = sum(x[start:start + n]) / n
    out[start + n - 1] = v
    for i in range(start + n, len(x)):
        if x[i] is None:
            break
        v = x[i] * k + v * (1 - k)
        out[i] = v
    return out


def ema(c, n):
    return ema_any(c, n)


def pstdev(c, n):
    """Rolling POPULATION standard deviation (divide by n) = Pine ta.stdev. Shifted sums keep it exact for big prices."""
    out, ref = [None] * len(c), (c[0] if c else 0.0)
    p1, p2 = [0.0], [0.0]
    for x in c:
        d = x - ref
        p1.append(p1[-1] + d)
        p2.append(p2[-1] + d * d)
    for i in range(n - 1, len(c)):
        s1, s2 = p1[i + 1] - p1[i + 1 - n], p2[i + 1] - p2[i + 1 - n]
        m = s1 / n
        out[i] = math.sqrt(max(s2 / n - m * m, 0.0))
    return out


def sma_any(x, n):
    """SMA of a series that has leading None values (the first n real values are needed)."""
    first = next((i for i, v in enumerate(x) if v is not None), None)
    if first is None:
        return [None] * len(x)
    return [None] * first + sma(x[first:], n)


def tsi_series(c, short=5, long=25, signal=14):
    """Pine: tsi = ta.tsi(close, short, long) * 100 = 100 * EMA(EMA(diff, long), short) / EMA(EMA(|diff|, long), short); tsl = EMA(tsi, signal).
    Returns (tsi, tsl, hist) with hist = tsi - tsl. Values are -100 .. +100. None while there is not enough data."""
    n = len(c)
    diff = [None] + [c[i] - c[i - 1] for i in range(1, n)]
    adiff = [None] + [abs(c[i] - c[i - 1]) for i in range(1, n)]
    num = ema_any(ema_any(diff, long), short)
    den = ema_any(ema_any(adiff, long), short)
    tsi = [None] * n
    for i in range(n):
        if num[i] is not None and den[i] is not None:
            tsi[i] = 100.0 * num[i] / den[i] if den[i] > 0 else 0.0
    tsl = ema_any(tsi, signal)
    hist = [(tsi[i] - tsl[i]) if tsi[i] is not None and tsl[i] is not None else None for i in range(n)]
    return tsi, tsl, hist


# ---------------------------------------------------------------- candles in
def to_series(candles):
    """Candles -> {n, t, o, h, l, c}. Accepts dicts (timestamp / open / high / low / close) or tuples (ts, o, h, l, c, v). Bad rows raise ValueError."""
    S = {"t": [], "o": [], "h": [], "l": [], "c": []}
    for x in candles:
        if isinstance(x, dict):
            t, o, h, l, c = x.get("timestamp", x.get("ts", 0)), x["open"], x["high"], x["low"], x["close"]
        else:
            t, o, h, l, c = x[0], x[1], x[2], x[3], x[4]
        t, o, h, l, c = int(t), float(o), float(h), float(l), float(c)
        if c <= 0 or h < l:
            raise ValueError("bad candle at %s" % t)
        for key, val in (("t", t), ("o", o), ("h", h), ("l", l), ("c", c)):
            S[key].append(val)
    S["n"] = len(S["c"])
    return S


# ---------------------------------------------------------------- the engine core
def build_features(candles, cfg=None, tsi_pack=None):
    """All Special 13 + Special Master numbers for every candle. cfg = DEFAULTS with changes. Returns one dict of lists S (same length as the candles).
    Keys: ema_f, ema_s, gap_pct (cloud width in % of price), cloud (+1 fast above slow, -1 below), sma, sd, z, tsi, tsl, hist, vi, vi_avg, side_ok (regime), long_x, short_x."""
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
            S["z"][i] = (c[i] - m) / d if d > 0 else 0.0     # flat window (SD 0): Z = 0, never a division error
            S["vi"][i] = d / m if m > 0 else None
    S["tsi"], S["tsl"], S["hist"] = tsi_pack if tsi_pack else tsi_series(c, cf["tsi_short"], cf["tsi_long"], cf["tsi_signal"])   # tsi_pack = same TSI reused by the search (it does not depend on the lengths searched)
    S["vi_avg"] = sma_any(S["vi"], cf["regime_win"])
    S["side_ok"] = [None] * n                              # True = TRENDING, False = SIDEWAYS, None = UNKNOWN
    for i in range(n):
        if S["vi"][i] is not None and S["vi_avg"][i] is not None:
            S["side_ok"][i] = S["vi"][i] >= cf["regime_ratio"] * S["vi_avg"][i]
    S["long_x"], S["short_x"] = [False] * n, [False] * n   # Pine ta.crossover / ta.crossunder of EMA fast vs slow
    for i in range(1, n):
        f, s, pf, ps = S["ema_f"][i], S["ema_s"][i], S["ema_f"][i - 1], S["ema_s"][i - 1]
        if None in (f, s, pf, ps):
            continue
        S["long_x"][i] = f > s and pf <= ps
        S["short_x"][i] = f < s and pf >= ps
    return S


def first_valid(S):
    """First candle index where every number is there (the warm-up is over). n if never."""
    if "_fv" in S:
        return S["_fv"]
    keys = ("ema_f", "ema_s", "sma", "sd", "z", "tsi", "tsl", "hist", "vi", "vi_avg")
    S["_fv"] = next((i for i in range(S["n"]) if all(S[k][i] is not None for k in keys)), S["n"])
    return S["_fv"]


def regime_at(S, i):
    """'TRENDING' / 'SIDEWAYS' / 'UNKNOWN' at candle i."""
    v = S["side_ok"][i] if 0 <= i < S["n"] else None
    return "UNKNOWN" if v is None else ("TRENDING" if v else "SIDEWAYS")


def sd_price(S, i, k):
    """Price of the +k / -k SD band at candle i (k = 1, 2, 3 or -1, -2, -3), like the Special 13 lines. None when not ready."""
    m, d = S["sma"][i], S["sd"][i]
    return None if m is None or d is None else m + k * d


def stop_price(S, i, side, z_mult=None):
    """Stop line: LONG = SMA - z_mult x SD, SHORT = SMA + z_mult x SD (the prompt's rule). None when not ready.
    NOTE: this can be far from the entry; Part S2 measures the real distance in % and rejects a stop that is too wide for the capital."""
    m, d = S["sma"][i], S["sd"][i]
    if m is None or d is None:
        return None
    zm = S["cfg"]["z_mult"] if z_mult is None else z_mult
    return m - zm * d if side == "LONG" else m + zm * d


def raw_signal(S, i):
    """The plain EMA + TSI + Z confluence at candle i, BEFORE the regime guard and BEFORE any probability.
    Returns {"side": "LONG" | "SHORT" | None, "why": [plain lines], "z": ..., "hist": ..., "gap_pct": ..., "regime": ...}. Never raises on a young series."""
    out = {"side": None, "why": [], "regime": regime_at(S, i), "z": None, "hist": None, "gap_pct": None}
    if not 1 <= i < S["n"] or i < first_valid(S):
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
    out["why"].append("TSI histogram %.2f %s" % (h, "agrees (%s)" % ("rising" if side == "LONG" else "falling") if ok_h else "does NOT agree"))
    out["why"].append("Z-Score %.2f is %s the allowed zone" % (z, "inside" if ok_z else "OUTSIDE"))
    if ok_h and ok_z:
        out["side"] = side
    return out


# ================================================================ PART S2: honest test (fees, train / test days, SD-length search)
FEE_PCT, SLIP_PCT = 0.05, 0.02      # per side, % of price - the SAME numbers as v2_replay.py / v2_bt_rules.py (kept here so this file stays standalone)
TEST_FRAC = 0.3                      # newest 30% of the whole days = TEST
MIN_DAYS = 6                         # fewer whole days than this = no honest split = NOT_ENOUGH_DATA
MAX_HOLD = 30                        # candles; then the trade is closed at the close of the last one (TIME)
MAX_SL_PCT, MIN_SL_PCT = 2.0, 0.15   # a stop wider than 2% of price is refused (too big for a 10 USDT base); a stop tighter than 0.15% is only noise
MIN_TRAIN_TRADES, MIN_TEST_TRADES = 10, 15
T_NEEDED = 2.0                       # the mean net of the TEST trades must be 2 standard errors above 0, else it can be luck
MARGIN_FRAC = 0.02                   # the winner must beat 200 on TEST by at least 2% of the capital
SD_CURVE = (20, 40, 60, 80, 100, 120, 150, 200)


def cost_pct():
    """Round trip cost in % of price: fee + slippage, both sides."""
    return 2.0 * (FEE_PCT + SLIP_PCT)


def day_of(t):
    """UTC day number of a timestamp in seconds or in milliseconds."""
    t = int(t)
    return (t // 1000 if t > 10 ** 11 else t) // 86400


def split_by_days(S, test_frac=TEST_FRAC):
    """Cut a series at a whole-day border. -> {cut (first TEST candle index), train_days, test_days} or None when there are fewer than MIN_DAYS days."""
    days = sorted(set(day_of(t) for t in S["t"]))
    if len(days) < MIN_DAYS:
        return None
    k = min(len(days) - 1, max(1, int(round(len(days) * (1.0 - test_frac)))))
    cut = next(i for i, t in enumerate(S["t"]) if day_of(t) >= days[k])
    return {"cut": cut, "train_days": k, "test_days": len(days) - k}


def simulate_trade(S, i, side, sl, end, tp_pct, max_hold=MAX_HOLD):
    """ONE hypothetical trade: entry = close of candle i, TP = tp_pct away, stop = sl. Looks only at candles i+1 .. min(end-1, i+max_hold).
    If one candle touches both lines the STOP counts first (the bad case). -> {exit, why (TP / SL / TIME), gross_pct, net_pct} or None when no candle is left."""
    entry, long_ = S["c"][i], side == "LONG"
    tp = entry * (1.0 + tp_pct / 100.0) if long_ else entry * (1.0 - tp_pct / 100.0)
    last = min(end - 1, i + max_hold)
    if last <= i:
        return None
    px, why, j = S["c"][last], "TIME", last
    for k in range(i + 1, last + 1):
        hi, lo = S["h"][k], S["l"][k]
        if (lo <= sl) if long_ else (hi >= sl):
            px, why, j = sl, "SL", k
            break
        if (hi >= tp) if long_ else (lo <= tp):
            px, why, j = tp, "TP", k
            break
    gross = (px - entry) / entry * 100.0 * (1 if long_ else -1)
    return {"exit": j, "why": why, "gross_pct": gross, "net_pct": gross - cost_pct()}


def run_period(S, lo, hi, tp_pct=1.5, use_regime=True, capital=10.0):
    """Every signal of candles [lo, hi) worked out one after the other (one trade at a time). A trade never looks past hi, so TRAIN never sees TEST.
    -> {"trades": [...], "skipped": {sideways, sl_wide, sl_bad}}. Each trade keeps the numbers Part S3 learns from (feat)."""
    out, skip = [], {"sideways": 0, "sl_wide": 0, "sl_bad": 0}
    i = max(lo, first_valid(S), 1)
    while i < hi - 1:
        if not (S["long_x"][i] or S["short_x"][i]):
            i += 1
            continue
        sig = raw_signal(S, i)
        if sig["side"] is None:
            i += 1
            continue
        if use_regime and sig["regime"] != "TRENDING":
            skip["sideways"] += 1
            i += 1
            continue
        side, entry = sig["side"], S["c"][i]
        sl = stop_price(S, i, side)
        dist = ((entry - sl) if side == "LONG" else (sl - entry)) / entry * 100.0
        if dist <= 0:
            skip["sl_bad"] += 1
            i += 1
            continue
        if dist > MAX_SL_PCT or dist < MIN_SL_PCT:
            skip["sl_wide" if dist > MAX_SL_PCT else "sl_bad"] += 1
            i += 1
            continue
        r = simulate_trade(S, i, side, sl, hi, tp_pct)
        if r is None:
            break
        out.append({"i": i, "t": S["t"][i], "side": side, "entry": entry, "sl": sl, "sl_pct": dist, "exit_i": r["exit"], "exit_t": S["t"][r["exit"]],
                    "why": r["why"], "gross_pct": r["gross_pct"], "net_pct": r["net_pct"], "net_usdt": capital * r["net_pct"] / 100.0, "win": r["net_pct"] > 0,
                    "feat": {"z": sig["z"], "hist": sig["hist"], "gap_pct": sig["gap_pct"], "vi_ratio": S["vi"][i] / S["vi_avg"][i], "dir": 1 if side == "LONG" else -1}})
        i = r["exit"] + 1
    return {"trades": out, "skipped": skip}


def stats_of(trades, capital=10.0):
    """Plain numbers of a trade list (any coins mixed, ordered by exit time): count, win rate, net USDT, worst dip, worst losing streak, t-stat of the mean net %."""
    tr = sorted(trades, key=lambda x: x["exit_t"])
    n = len(tr)
    out = {"trades": n, "wins": sum(1 for x in tr if x["win"]), "net_usdt": round(sum(x["net_usdt"] for x in tr), 4), "win_rate": None, "worst_dip_usdt": 0.0, "worst_streak": 0, "t_stat": None}
    if not n:
        return out
    out["win_rate"] = out["wins"] / n
    eq = peak = dip = 0.0
    run = streak = 0
    for x in tr:
        eq += x["net_usdt"]
        peak = max(peak, eq)
        dip = max(dip, peak - eq)
        run = 0 if x["win"] else run + 1
        streak = max(streak, run)
    out["worst_dip_usdt"], out["worst_streak"] = round(dip, 4), streak
    if n >= 2:
        m = sum(x["net_pct"] for x in tr) / n
        var = sum((x["net_pct"] - m) ** 2 for x in tr) / (n - 1)
        out["t_stat"] = round(m / math.sqrt(var / n), 2) if var > 0 else None
    return out


def prep_sets(candle_sets):
    """candle lists (one per coin, one gap-free run each) -> prepared series with the TRAIN / TEST cut. Series that are too short or have too few days are left out (counted)."""
    sets, left = [], 0
    for k, cs in enumerate(candle_sets):
        try:
            S = to_series(cs)
        except (ValueError, KeyError, IndexError, TypeError):
            left += 1
            continue
        sp = split_by_days(S) if S["n"] else None
        if sp is None:
            left += 1
            continue
        sets.append({"k": k, "candles": cs, "cut": sp["cut"], "days": (sp["train_days"], sp["test_days"]),
                     "tsi": tsi_series(S["c"], DEFAULTS["tsi_short"], DEFAULTS["tsi_long"], DEFAULTS["tsi_signal"])})
    return sets, left


def trades_for(sets, cfg, tp_pct=1.5, use_regime=True, capital=10.0, test=True):
    """All coins, one setting -> (train_trades, test_trades) (test=False: the TEST days are not even looked at, used by the random search). Features are made on the whole series (they only look back), the trades are cut at the TRAIN / TEST border."""
    tr, te = [], []
    for ps in sets:
        S = build_features(ps["candles"], cfg, tsi_pack=ps["tsi"])
        tr += run_period(S, 0, ps["cut"], tp_pct, use_regime, capital)["trades"]
        if test:
            te += run_period(S, ps["cut"], S["n"], tp_pct, use_regime, capital)["trades"]
    return tr, te


def _score(st, capital):
    """TRAIN score: net USDT minus half the worst dip. Too few trades = unusable."""
    return -1e9 if st["trades"] < MIN_TRAIN_TRADES else st["net_usdt"] - 0.5 * st["worst_dip_usdt"]


def sample_cfg(rng):
    return {"sd_len": rng.randint(20, 200), "fast_ema": rng.randint(10, 40), "slow_ema": rng.randint(45, 75),
            "z_mult": round(rng.uniform(1.5, 2.5), 2), "regime_ratio": round(rng.uniform(0.8, 1.2), 2)}


def search_params(candle_sets, n_trials=60, seed=42, tp_pct=1.5, capital=10.0, base=None):
    """The honest search. Random trials look at TRAIN days only. The best TRAIN setting and the old one (200 / 30 / 50) are then both shown the TEST days once.
    -> dict with verdict BETTER_PROVEN / NOT_PROVEN / NOT_ENOUGH_DATA, both settings with train + test numbers, the SD-length curve and plain lines."""
    base_cfg = dict(DEFAULTS)
    base_cfg.update(base or {})
    sets, left = prep_sets(candle_sets)
    res = {"version": VERSION, "verdict": "NOT_ENOUGH_DATA", "coins_used": len(sets), "coins_left_out": left, "trials": 0, "tp_pct": tp_pct, "cost_pct": round(cost_pct(), 4),
           "split": None, "old": None, "best": None, "best_cfg": None, "curve": [], "guard": None, "lines": []}
    if not sets:
        res["lines"].append("Not enough whole days of candles (need at least %d days per coin). Settings stay as they are." % MIN_DAYS)
        return res
    res["split"] = {"train_days": min(s["days"][0] for s in sets), "test_days": min(s["days"][1] for s in sets)}

    def both(cfg, use_regime=True):
        a, b = trades_for(sets, cfg, tp_pct, use_regime, capital)
        return {"cfg": cfg, "train": stats_of(a, capital), "test": stats_of(b, capital)}, a, b

    old, _, _ = both(base_cfg)
    res["old"] = old
    rng = random.Random(seed)
    best_cfg, best_sc = None, -1e9
    for _ in range(int(n_trials)):
        cfg = dict(base_cfg, **sample_cfg(rng))
        if cfg["fast_ema"] >= cfg["slow_ema"]:
            continue
        a = trades_for(sets, cfg, tp_pct, True, capital, test=False)[0]
        sc = _score(stats_of(a, capital), capital)
        res["trials"] += 1
        if sc > best_sc:
            best_cfg, best_sc = cfg, sc
    for ln in SD_CURVE:                                       # the readable "is 200 right?" curve, only the SD length changes
        row, _, _ = both(dict(base_cfg, sd_len=ln))
        res["curve"].append({"sd_len": ln, "train_net": row["train"]["net_usdt"], "train_trades": row["train"]["trades"],
                             "test_net": row["test"]["net_usdt"], "test_trades": row["test"]["trades"]})
    if best_cfg is None:
        res["verdict"] = "NOT_PROVEN"
        res["lines"].append("No setting made %d or more trades on the TRAIN days. Settings stay as they are." % MIN_TRAIN_TRADES)
        return res
    best, _, _ = both(best_cfg)
    res["best"], res["best_cfg"] = best, best_cfg
    nog, _, _ = both(best_cfg, use_regime=False)              # what the sideways guard added or cost on the TEST days
    res["guard"] = {"test_net_with": best["test"]["net_usdt"], "test_trades_with": best["test"]["trades"], "test_net_without": nog["test"]["net_usdt"], "test_trades_without": nog["test"]["trades"]}
    bt, ot = best["test"], old["test"]
    proven = (bt["trades"] >= MIN_TEST_TRADES and bt["net_usdt"] > 0 and bt["net_usdt"] > ot["net_usdt"] + MARGIN_FRAC * capital and bt["t_stat"] is not None and bt["t_stat"] >= T_NEEDED)
    res["verdict"] = "BETTER_PROVEN" if proven else ("NOT_ENOUGH_DATA" if bt["trades"] < MIN_TEST_TRADES else "NOT_PROVEN")
    res["lines"] = calibration_lines(res)
    return res


def calibration_lines(res):
    """Plain lines for the Insight Report: what was tested, what won on TRAIN, what it did on TEST, and whether 200 is really wrong."""
    L = []
    sp, o, b = res.get("split"), res.get("old"), res.get("best")
    if not o:
        return list(res.get("lines") or [])
    L.append("Tested %d coins, %d random settings on %d TRAIN days; the winner was then shown %d unseen TEST days. Cost counted: %.2f%% per round trip (fee + slippage)." %
             (res["coins_used"], res["trials"], sp["train_days"], sp["test_days"], res["cost_pct"]))
    L.append("Old setting (SD %d, EMA %d/%d): TEST %d trades, net %+.2f USDT." % (o["cfg"]["sd_len"], o["cfg"]["fast_ema"], o["cfg"]["slow_ema"], o["test"]["trades"], o["test"]["net_usdt"]))
    if b:
        c = res["best_cfg"]
        L.append("TRAIN winner (SD %d, EMA %d/%d, stop %.2f SD, sideways ratio %.2f): TEST %d trades, net %+.2f USDT, worst dip %.2f USDT, t-stat %s." %
                 (c["sd_len"], c["fast_ema"], c["slow_ema"], c["z_mult"], c["regime_ratio"], b["test"]["trades"], b["test"]["net_usdt"], b["test"]["worst_dip_usdt"], b["test"]["t_stat"]))
    v = res["verdict"]
    if v == "BETTER_PROVEN":
        L.append("RESULT: the new setting beat the old one on unseen days with enough trades. It is now used%s." % ("; SD length 200 was NOT the best" if res["best_cfg"]["sd_len"] != 200 else ""))
    elif v == "NOT_ENOUGH_DATA":
        L.append("RESULT: too few TEST trades (need %d). Nothing is proven, settings stay as they are. More days of candles are needed." % MIN_TEST_TRADES)
    else:
        L.append("RESULT: NOT PROVEN. The winner did not clearly beat the old setting on unseen days (it can be luck). Settings stay as they are.")
    g = res.get("guard")
    if g:
        L.append("Sideways guard on TEST days: with guard %+.2f USDT (%d trades), without %+.2f USDT (%d trades)." % (g["test_net_with"], g["test_trades_with"], g["test_net_without"], g["test_trades_without"]))
    return L


class OwlSniperEngine:
    """Holds the settings. Part S1 = features + raw signal + regime. Part S2 adds calibrate() (SD-length search on train days, check on test days, USDT fees).
    Part S3 adds the win-probability, the 85% floor and evaluate_live() with the Insight Report. The engine is a WATCHER: it never opens or closes a trade."""

    def __init__(self, target_profit_pct=1.5, stop_loss_buffer_sd=2.0, capital_usdt=10.0, floor=0.85):
        self.tp_target = float(target_profit_pct) / 100.0
        self.capital = float(capital_usdt)
        self.floor = float(floor)
        self.optimal_config = dict(DEFAULTS, z_mult=float(stop_loss_buffer_sd))
        self.is_trained = False                 # becomes True in Part S3 (win-probability learned)
        self.calibrated = False
        self.calibration = None
        self.excluded = EXCLUDED

    def features(self, candles, cfg=None):
        """build_features with this engine's settings (or the cfg given, for the search)."""
        use = dict(self.optimal_config)
        use.update(cfg or {})
        return build_features(candles, use)

    def scan(self, candles):
        """Newest closed candle: raw signal + regime. -> dict. Part S3 puts the probability and the 85% floor on top of this."""
        S = self.features(candles)
        i = S["n"] - 1
        sig = raw_signal(S, i)
        return {"version": VERSION, "n": S["n"], "regime": sig["regime"], "side": sig["side"], "why": sig["why"], "z": sig["z"], "hist": sig["hist"],
                "sd_len": S["cfg"]["sd_len"], "blocked_by_regime": bool(sig["side"]) and sig["regime"] != "TRENDING"}

    def calibrate(self, candle_sets, n_trials=60, seed=42):
        """Part S2: the honest search (see search_params). The settings change ONLY when the verdict is BETTER_PROVEN; else they stay as they are.
        candle_sets = one gap-free candle list per coin. -> the result dict (its "lines" are plain text for the Insight Report)."""
        res = search_params(candle_sets, n_trials, seed, self.tp_target * 100.0, self.capital, base=self.optimal_config)
        if res["verdict"] == "BETTER_PROVEN":
            self.optimal_config.update(res["best_cfg"])
        self.calibration, self.calibrated = res, res["verdict"] != "NOT_ENOUGH_DATA"
        return res

    def collect_trades(self, candle_sets):
        """The trades of the CURRENT settings, split into TRAIN and TEST (Part S3 learns the win-probability from TRAIN and checks the 85% floor on TEST). -> (train, test)."""
        sets, _left = prep_sets(candle_sets)
        return trades_for(sets, self.optimal_config, self.tp_target * 100.0, True, self.capital)
