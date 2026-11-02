"""owl_sniper_engine_c1.py - OwlSniper ENGINE PART C1 of 3: the HONEST SIMULATOR (fees, slippage, whole-day train / test split) (backend, plain python, NO numpy / pandas / sklearn).
Imports only owl_sniper_engine_a (maths) and owl_sniper_engine_b (features, regime, signal). Nothing is traded, nothing is saved here.
Rules that keep the test honest:
  * Every hypothetical trade pays fee + slippage on BOTH sides (FEE_PCT + SLIP_PCT per side, the same numbers as v2_replay).
  * If one candle touches both the stop and the target, the STOP counts first (the bad case, never the flattering one).
  * Candles are cut at a WHOLE UTC DAY border: the older 70% of the days = TRAIN, the newest 30% = TEST. A trade that starts in TRAIN never looks into TEST,
    and indicators only look BACK, so there is no data leakage.
  * A stop wider than MAX_SL_PCT of price is refused (too big for a 10 USDT base); a stop tighter than MIN_SL_PCT is only noise.
Part C2 imports this file for the SD-length search and the OwlSniperEngine class.
EXCLUDED on purpose: CHoCH and BOS (market structure)."""
import math

from owl_sniper_engine_a import tsi_series
from owl_sniper_engine_b import DEFAULTS, to_series, build_features, warmup_end, raw_signal, stop_price

VERSION = "owl_sniper_engine_c1 1 (Part C1)"

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
    -> {"trades": [...], "skipped": {sideways, sl_wide, sl_bad}}. Each trade keeps the numbers owl_sniper_prob.py learns from (feat)."""
    out, skip = [], {"sideways": 0, "sl_wide": 0, "sl_bad": 0}
    i = max(lo, warmup_end(S), 1)
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
