"""chop_filter.py - Part C1 (README_CHOP): the FILTER BRAIN of the both-indicator bot b3. It only decides ENTRY (TAKE / SKIP + size + short reason). TP and stop stay the current bot's.
Pure maths on closed candles from backend/v2_scalp_ind.py (EMA50, SD bands, Z, Z-SMA, TSI). No network, no database, no orders, nothing saved. Reads nothing from the repo except v2_scalp_ind.py and chop_score.py.
DECISION ORDER (README_CHOP section 3):
  1 chop gate (hard block; the breakout key may override it)   2 top trigger = EMA50 cross on a CLOSED candle   3 Z state + TSI state (a STATE check, the bottom never triggers alone)
  4 bigger timeframe side (caller passes it; a hard block only if p["htf_block"] is True)   5 not stretched past 2 SD + fee check   6 quality score -> FULL / HALF / NONE, soft brake per coin
LATE ENTRY (scenario 5): a trigger blocked by chop or by Z + TSI is a late_candidate. If within 3 candles Z + TSI agree, price is still on the trigger side of EMA50 and the chop gate is clear, decide(late_from=...) can TAKE it.
SKIP VALUE: skip_outcome() says what a skipped signal would have made (SIMPLE walk: stop = signal candle extreme, target = first SD band, one cost deduction). The full replay with the bot's TP1-4 is C2.
p may also carry full_cut / half_cut (the C2 replay sweeps them); P itself has neither, so the starting cuts of chop_score apply.
All numbers in P and COST_PCT are STARTING VALUES (NV = not validated); the replay (C2) tunes them with a train / test split.
Run (Termux, optional, read-only):  python3 backend/chop_filter.py [--data DIR] [--symbol BTCUSDT] [--interval 5m]  -> prints the decision for the newest closed candle.
Candle = (open_ts, o, h, l, c, v)."""
import argparse
import json
import os
import sqlite3
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_scalp_ind as I
import chop_score as S

VERSION = "chop_filter 1 (Part C1)"
COST_PCT = 0.14                      # round-trip cost in % of price (README_CHOP: the replay engine's figure)
P = {"cross_window": 20, "cross_chop_n": 3,        # 3+ EMA50 crosses in 20 candles = chop
     "flat_bars": 10, "flat_sd_k": 0.25,           # EMA50 moved less than 0.25 SD in 10 candles = flat
     "mid_bars": 8, "mid_sd_k": 0.5,               # last 8 closes all within 0.5 SD of the SD middle = stuck
     "fee_mult": 2.0,                              # target distance must be >= 2 x COST_PCT
     "late_bars": 3, "stretch_zone": 2, "htf_block": False, "horizon": 24}


def _want(side):
    return 1 if side == "BUY" else -1


def _sgn(x):
    return (x > 0) - (x < 0)


def cross_count(ind, i, window=None):
    """EMA50 crosses (the bot's own rule) in the last `window` closed candles, this one included. 1 = clean trend start."""
    w = window or P["cross_window"]
    return sum(1 for j in range(max(1, i - w + 1), i + 1) if I.ema_cross(ind, j) is not None)


def chop_state(ind, i, p=None):
    """The chop gate. chop = EMA50 flat OR 3+ crosses in 20 candles OR price stuck near the SD middle. Unit-free: flat and stuck are measured in standard deviations."""
    p = p or P
    e, sd, mean, c = ind["ema50"], ind["sd_std"], ind["sd_mean"], ind["close"]
    k, m = p["flat_bars"], p["mid_bars"]
    flat = bool(i >= k and e[i] is not None and e[i - k] is not None and sd[i] and abs(e[i] - e[i - k]) < p["flat_sd_k"] * sd[i])
    n = cross_count(ind, i, p["cross_window"])
    many = n >= p["cross_chop_n"]
    stuck = bool(i >= m - 1 and all(mean[j] is not None and sd[j] and abs(c[j] - mean[j]) < p["mid_sd_k"] * sd[j] for j in range(i - m + 1, i + 1)))
    why = (["EMA flat"] if flat else []) + (["%d EMA crosses in %d" % (n, p["cross_window"])] if many else []) + (["stuck at SD middle"] if stuck else [])
    return {"chop": flat or many or stuck, "flat": flat, "cross_n": n, "stuck": stuck, "reasons": why}


def z_state(ind, i, side):
    """Z close vs its Z-SMA (the black line): AGREE / NEUTRAL / AGAINST for this side."""
    z, zs = ind["z"][i], ind["z_sma"][i]
    if z is None or zs is None or z == zs:
        return "NEUTRAL"
    return "AGREE" if (z > zs) == (side == "BUY") else "AGAINST"


def tsi_state(ind, i, side):
    """TSI line vs signal line AND histogram direction (rising / falling): both with the side = AGREE, both against = AGAINST, mixed = NEUTRAL."""
    t, sg, h = ind["tsi"][i], ind["tsi_signal"][i], ind["hist"][i]
    hp = ind["hist"][i - 1] if i >= 1 else None
    if t is None or sg is None or h is None or hp is None:
        return "NEUTRAL"
    a, b = _sgn(t - sg) * _want(side), _sgn(h - hp) * _want(side)
    return "AGREE" if a > 0 and b > 0 else "AGAINST" if a < 0 and b < 0 else "NEUTRAL"


def breakout_key(ind, i, side):
    """The key that can open the chop gate: the close is OUTSIDE the 1 SD band in the signal direction AND Z and TSI both agree."""
    mean, sd, c = ind["sd_mean"][i], ind["sd_std"][i], ind["close"][i]
    if mean is None or not sd:
        return False
    out = c > mean + sd if side == "BUY" else c < mean - sd
    return bool(out and z_state(ind, i, side) == "AGREE" and tsi_state(ind, i, side) == "AGREE")


def stretched(ind, i, side, p=None):
    """Price is already 2 SD or more away from the SD middle in the signal direction = late chase."""
    p = p or P
    zone = I.band_zone(ind["close"][i], ind["sd_mean"][i], ind["sd_std"][i])
    return zone is not None and zone * _want(side) >= p["stretch_zone"]


def target_info(ind, i, side):
    """The first SD band (mean +/- 1, 2, 3 SD) that lies beyond the close in the signal direction -> {level, dist_pct}; None if price is past 3 SD or no band yet."""
    mean, sd, c = ind["sd_mean"][i], ind["sd_std"][i], ind["close"][i]
    if mean is None or not sd or c <= 0:
        return None
    w = _want(side)
    for k in (1, 2, 3):
        lvl = mean + w * k * sd
        if (lvl - c) * w > 0:
            return {"level": lvl, "dist_pct": (lvl - c) * w / c * 100.0}
    return None


def room(candles, ind, i, side, p=None):
    """Fee check + room: ok_fee = target distance >= fee_mult x COST_PCT; beats_stop = target distance is more than the stop distance (stop = signal candle extreme)."""
    p = p or P
    t = target_info(ind, i, side)
    c = float(candles[i][4])
    stop = float(candles[i][3]) if side == "BUY" else float(candles[i][2])
    stop_pct = (c - stop) * _want(side) / c * 100.0 if c > 0 else None
    d = None if t is None else t["dist_pct"]
    return {"dist_pct": None if d is None else round(d, 4), "need_pct": round(p["fee_mult"] * COST_PCT, 4), "stop_pct": None if stop_pct is None else round(stop_pct, 4),
            "ok_fee": d is not None and d >= p["fee_mult"] * COST_PCT, "beats_stop": d is not None and stop_pct is not None and d > stop_pct}


def _res(action, size, sc, scen, why, **kw):
    r = {"action": action, "size": size, "score": sc, "scenario": scen, "why": why, "late_candidate": False}
    r.update(kw)
    return r


def decide(candles, ind, i, htf_side=None, btc_move_pct=None, coin_losses=0, weights=None, p=None, late_from=None):
    """The entry decision for the CLOSED candle i. ind = v2_scalp_ind.compute(candles) of ONE gap-free run.
    htf_side = ABOVE or BELOW (close vs the bigger timeframe EMA50) or None. late_from = dict with i (index) and side of an earlier late_candidate.
    -> dict: action (TAKE / SKIP / NONE), size (FULL / HALF / NONE), score, scenario (README_CHOP section 5), why (short text), late_candidate, side, parts, states.
    NONE = no trigger on this candle (nothing to decide)."""
    p = p or P
    st = I.state(ind, i)
    if not st["ready"]:
        return _res("SKIP", "NONE", None, 0, "not enough candles yet", side=None)
    if late_from:
        side = late_from["side"]
        gap = i - late_from["i"]
        if gap < 1 or gap > p["late_bars"]:
            return _res("NONE", "NONE", None, 0, "late window over", side=side)
        ema = ind["ema50"][i]
        if (ind["close"][i] > ema) != (side == "BUY"):
            return _res("SKIP", "NONE", None, 5, "late: price left the trigger side of EMA50", side=side)
    else:
        side = I.ema_cross(ind, i)
        if side is None:
            return _res("NONE", "NONE", None, 0, "no EMA50 cross on this candle", side=None)
    chop, brk = chop_state(ind, i, p), breakout_key(ind, i, side)
    zs, ts = z_state(ind, i, side), tsi_state(ind, i, side)
    hs = None if htf_side is None else (htf_side == "ABOVE") == (side == "BUY")
    rm = room(candles, ind, i, side, p)
    fr = S.parts(candles, ind, i, side, chop, brk, zs, ts, hs, rm, btc_move_pct)
    sc = S.score(fr, weights)
    base = {"side": side, "parts": fr, "states": {"z": zs, "tsi": ts, "htf_agree": hs, "chop": chop, "breakout": brk, "room": rm}, "late": bool(late_from)}
    if chop["chop"] and (late_from or not brk):
        return _res("SKIP", "NONE", sc, 4, "chop: " + ", ".join(chop["reasons"]), late_candidate=not late_from, **base)
    if late_from and not (zs == "AGREE" and ts == "AGREE"):
        return _res("SKIP", "NONE", sc, 5, "late: Z and TSI do not both agree", **base)
    if zs == "AGAINST" and ts == "AGAINST":
        return _res("SKIP", "NONE", sc, 3, "Z and TSI both against", late_candidate=not late_from, **base)
    if hs is False and p["htf_block"]:
        return _res("SKIP", "NONE", sc, 0, "bigger timeframe against", **base)
    if stretched(ind, i, side, p):
        return _res("SKIP", "NONE", sc, 8, "late chase: already past %d SD" % p["stretch_zone"], **base)
    if not rm["ok_fee"]:
        return _res("SKIP", "NONE", sc, 0, "target %s%% is under %s%% (fee check)" % (rm["dist_pct"], rm["need_pct"]), **base)
    size, fc, hc = S.size_for(sc, coin_losses, p.get("full_cut"), p.get("half_cut"))
    if size == "FULL" and not (zs == "AGREE" and ts == "AGREE"):
        size = "HALF"          # scenario 2 and every mixed state: at most half size
    if size == "NONE":
        return _res("SKIP", "NONE", sc, 0, "score %s is under %s%s" % (sc, hc, " (brake)" if coin_losses >= S.BRAKE_LOSSES else ""), **base)
    scen = 5 if late_from else 4 if chop["chop"] else 1 if (zs == "AGREE" and ts == "AGREE") else 2 if (ts == "AGREE" and zs == "NEUTRAL") else 0
    return _res("TAKE", size, sc, scen, "score %s, Z %s, TSI %s%s" % (sc, zs, ts, ", breakout key" if chop["chop"] else ""), **base)


def skip_outcome(candles, ind, i, side, p=None):
    """What a SKIPPED signal at candle i would have made (SIMPLE walk, see the top). stop = signal candle extreme, target = first SD band, first touch wins, a candle touching both counts as the stop.
    After `horizon` candles without a touch it exits at that close. -> dict (net_pct after cost, exit, mfe_pct, candles, final, label RALLY_MISSED or LOSS_AVOIDED) or None if not computable yet.
    final = False means the horizon is not complete yet, so ask again later."""
    p = p or P
    w = _want(side)
    entry = float(candles[i][4])
    t = target_info(ind, i, side)
    stop = float(candles[i][3]) if side == "BUY" else float(candles[i][2])
    end = min(len(candles) - 1, i + p["horizon"])
    if t is None or entry <= 0 or (entry - stop) * w <= 0 or end <= i:
        return None
    exit_px, why, mfe = None, "TIME", 0.0
    for j in range(i + 1, end + 1):
        hi, lo = float(candles[j][2]), float(candles[j][3])
        mfe = max(mfe, ((hi - entry) if w > 0 else (entry - lo)) / entry * 100.0)
        if (lo <= stop) if w > 0 else (hi >= stop):
            exit_px, why = stop, "STOP"
            break
        if (hi >= t["level"]) if w > 0 else (lo <= t["level"]):
            exit_px, why = t["level"], "TARGET"
            break
    if exit_px is None:
        exit_px = float(candles[end][4])
    net = (exit_px - entry) * w / entry * 100.0 - COST_PCT
    return {"net_pct": round(net, 4), "exit": why, "mfe_pct": round(mfe, 4), "candles": end - i, "final": why != "TIME" or end - i >= p["horizon"],
            "label": "RALLY_MISSED" if net > 0 else "LOSS_AVOIDED"}


def main(argv=None):
    import v2_defs as D
    import v2_setup_finder as SF
    import v2_store as ST
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="5m")
    a = ap.parse_args(argv)
    path = ST.store_path(a.data)
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
    ind = I.compute(run)
    i = len(run) - 1
    print(json.dumps({"version": VERSION, "symbol": a.symbol, "interval": a.interval, "candles": len(run), "chop": chop_state(ind, i) if ind["ema50"][i] is not None else None,
                      "decision": decide(run, ind, i)}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
