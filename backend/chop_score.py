"""chop_score.py - Part C1 (README_CHOP): the QUALITY SCORE 0-100 of one signal for the both-indicator bot b3, plus the soft brake and the self-learning SUGGESTION maths.
Pure maths on closed candles. No network, no database, no trading code, nothing is saved unless save_weights() is called (only after the owner says ok).
Score = sum of weight x fraction (0..1) of 9 parts (README_CHOP section 4). The weights are STARTING GUESSES (NV = not validated), kept in ONE dict so the learning can change them.
Self-learning rule: the bot never changes its own weights. suggest_weights() only PROPOSES a change from judged decisions (TAKE results and what each SKIP would have made),
and only when the first 60% (train) and the last 40% (test) of the rows show the same direction. The owner says ok, then save_weights() writes the file.
Candle = (open_ts, o, h, l, c, v)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_scalp_ind as I

VERSION = "chop_score 1 (Part C1)"
WEIGHTS = {"clean": 15, "htf": 15, "z": 12, "tsi": 15, "squeeze": 10, "volume": 8, "room": 15, "not_stretched": 5, "btc": 5}   # sums to 100
MAX_ONE_WEIGHT = 40.0
FULL_CUT, HALF_CUT = 70.0, 50.0          # score >= FULL_CUT -> full size, >= HALF_CUT -> half size, below -> skip (NV, tuned by the replay in C2)
BRAKE_LOSSES, BRAKE_ADD = 3, 10.0        # 3 losses on ONE coin: only that coin needs +10 on both cuts (no pause, README P7)
SQUEEZE_LOOK, SQUEEZE_GAP, SQUEEZE_RANK = 100, 3, 0.30
VOL_NOW, VOL_BASE = 3, 20
BTC_MOVE_PCT = 0.5


def default_weights():
    return dict(WEIGHTS)


def _normalise(w):
    tot = float(sum(w.values()))
    return {k: round(v * 100.0 / tot, 2) for k, v in w.items()} if tot > 0 else default_weights()


def load_weights(path=None):
    """The weights from a json file if it is valid, else the starting weights. A bad or missing file never raises."""
    if not path or not os.path.isfile(path):
        return default_weights()
    try:
        with open(path, "r", encoding="utf-8") as f:
            w = json.load(f)
        if not isinstance(w, dict) or set(w) != set(WEIGHTS):
            return default_weights()
        if any((not isinstance(v, (int, float))) or isinstance(v, bool) or v < 0 or v > MAX_ONE_WEIGHT for v in w.values()):
            return default_weights()
        return _normalise({k: float(v) for k, v in w.items()})
    except (OSError, ValueError):
        return default_weights()


def save_weights(path, weights):
    """Write the weights file (atomic). Call ONLY after the owner has said ok to a suggestion."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_normalise(weights), f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def _want(side):
    return 1 if side == "BUY" else -1


def _state_frac(s):
    return 1.0 if s == "AGREE" else 0.0 if s == "AGAINST" else 0.5


def squeeze_frac(ind, i, side):
    """1 = the SD band was tight (lowest 30% of the last 100) 3 candles ago AND price now closes outside the 1 SD band in the signal direction; 0.5 = tight only; 0 = no squeeze or not enough candles."""
    sd, mean = ind["sd_std"], ind["sd_mean"]
    w = lambda j: None if sd[j] is None or not mean[j] else sd[j] / abs(mean[j])
    k = i - SQUEEZE_GAP
    if k - SQUEEZE_LOOK < 0 or w(k) is None:
        return 0.0
    past = [x for x in (w(j) for j in range(k - SQUEEZE_LOOK, k)) if x is not None]
    if len(past) < SQUEEZE_LOOK // 2:
        return 0.0
    rank = sum(1 for x in past if x <= w(k)) / float(len(past))
    if rank > SQUEEZE_RANK:
        return 0.0
    zone = I.band_zone(ind["close"][i], mean[i], sd[i])
    return 1.0 if zone is not None and zone * _want(side) >= 1 else 0.5


def volume_frac(candles, i):
    """1 = the last 3 candles trade 1.5x the volume of the 20 before; 0.5 = at least equal; 0 = lower or no volume data."""
    if i - VOL_NOW - VOL_BASE + 1 < 0:
        return 0.0
    now = [float(candles[j][5]) for j in range(i - VOL_NOW + 1, i + 1)]
    base = [float(candles[j][5]) for j in range(i - VOL_NOW - VOL_BASE + 1, i - VOL_NOW + 1)]
    b = sum(base) / len(base)
    if b <= 0:
        return 0.0
    r = (sum(now) / len(now)) / b
    return 1.0 if r >= 1.5 else 0.5 if r >= 1.0 else 0.0


def btc_frac(btc_move_pct, side):
    """BTC moving sharply the same way gives alts a bonus; sharply against = 0; unknown or small = 0.5."""
    if btc_move_pct is None:
        return 0.5
    m = btc_move_pct * _want(side)
    return 1.0 if m >= BTC_MOVE_PCT else 0.0 if m <= -BTC_MOVE_PCT else 0.5


def parts(candles, ind, i, side, chop, breakout, z_state, tsi_state, htf_agree, room, btc_move_pct=None):
    """The 9 fractions (0..1). chop = chop_filter.chop_state dict, room = chop_filter.room dict, htf_agree = True / False / None (None = not known)."""
    if chop["chop"]:
        clean = 0.5 if breakout else 0.0
    else:
        clean = 1.0 if chop["cross_n"] <= 1 else 0.6
    zone = I.band_zone(ind["close"][i], ind["sd_mean"][i], ind["sd_std"][i])
    zd = 0 if zone is None else zone * _want(side)
    return {"clean": clean,
            "htf": 0.5 if htf_agree is None else 1.0 if htf_agree else 0.0,
            "z": _state_frac(z_state), "tsi": _state_frac(tsi_state),
            "squeeze": squeeze_frac(ind, i, side), "volume": volume_frac(candles, i),
            "room": 1.0 if room["ok_fee"] and room["beats_stop"] else 0.5 if room["ok_fee"] else 0.0,
            "not_stretched": 1.0 if zd < 1 else 0.5 if zd == 1 else 0.0,
            "btc": btc_frac(btc_move_pct, side)}


def score(frac, weights=None):
    w = weights or WEIGHTS
    return round(sum(w[k] * frac.get(k, 0.0) for k in w), 1)


def size_for(sc, coin_losses=0, full_cut=None, half_cut=None):
    """-> (FULL, HALF or NONE; full_cut_used; half_cut_used). The soft brake raises both cuts for a coin with 3+ losses in a row. full_cut / half_cut replace the starting cuts (used by the C2 replay sweep)."""
    add = BRAKE_ADD if coin_losses >= BRAKE_LOSSES else 0.0
    fc, hc = (FULL_CUT if full_cut is None else full_cut) + add, (HALF_CUT if half_cut is None else half_cut) + add
    return ("FULL" if sc >= fc else "HALF" if sc >= hc else "NONE"), fc, hc


def _edge(rows, name):
    hi = [r["net_pct"] for r in rows if r["parts"].get(name, 0.5) >= 0.75]
    lo = [r["net_pct"] for r in rows if r["parts"].get(name, 0.5) <= 0.25]
    if len(hi) < 8 or len(lo) < 8:
        return None, len(hi), len(lo)
    return sum(hi) / len(hi) - sum(lo) / len(lo), len(hi), len(lo)


def suggest_weights(rows, weights=None, min_rows=60, step=0.15, min_edge_pct=0.05):
    """PROPOSE new weights. rows = judged decisions in TIME ORDER, each a dict with parts (name -> fraction) and net_pct (net result after fee) (a TAKE = its real result, a SKIP = what it would have made).
    A part is changed only if its edge (mean net of rows where it was strong minus rows where it was weak) has the SAME sign on the train part (first 60%) and the test part (last 40%) and is at least min_edge_pct.
    A change is at most 15% of the old weight. Nothing is saved. -> dict with enough, rows, changes, new_weights."""
    w = dict(weights or WEIGHTS)
    n = len(rows)
    out = {"enough": n >= min_rows, "rows": n, "changes": [], "new_weights": dict(w)}
    if n < min_rows:
        out["note"] = "need %d judged decisions, have %d" % (min_rows, n)
        return out
    cut = int(n * 0.6)
    train, test = rows[:cut], rows[cut:]
    new = dict(w)
    for name in w:
        e_tr, a, b = _edge(train, name)
        e_te, _c, _d = _edge(test, name)
        if e_tr is None or e_te is None or e_tr * e_te <= 0 or min(abs(e_tr), abs(e_te)) < min_edge_pct:
            continue
        new[name] = max(0.0, min(MAX_ONE_WEIGHT, w[name] * (1.0 + step if e_tr > 0 else 1.0 - step)))
        out["changes"].append({"part": name, "train_edge_pct": round(e_tr, 3), "test_edge_pct": round(e_te, 3), "old": round(w[name], 2), "new_raw": round(new[name], 2)})
    out["new_weights"] = _normalise(new)
    return out
