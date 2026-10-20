"""
ai_miner.py - lets AI Insights DISCOVER patterns on its own (no scoring).

What it does (all plain counting, no API key, never raises):
  1. Turns every closed trade into labelled facts (direction, session, IST time
     block, weekday, SD zone, EMA slope, volume, regime, volatility, SD width,
     SL distance, timeframe, coin, IST hour).
  2. Tries every single fact and every COMBO of 2-3 facts ("Asian + +2SD zone +
     volume surge") and measures the average ROI of those trades vs all others.
  3. OLD vs NEW test: patterns are found on the older ~60% of trades and then
     re-checked on the newer ~40%. Only a pattern that keeps working on the
     newer trades is called CONFIRMED. One that flips is called FAILED.
  4. Noise check: the same search is run on shuffled results. If shuffled data
     also "finds" patterns, real patterns are probably luck and the AI says so.
  5. Pattern memory (ai_patterns.json): remembers how many checks in a row a
     pattern has stayed CONFIRMED -> STABLE. This is the "learning" over time.
  6. Postmortem: why trades lose (reversal after TP1 / quick stop / sideways
     chop), where each loss type concentrates, and which trail / max-loss rule
     would have helped on the old trades AND on the new ones.

It only READS closed trades and only ADVISES. It never changes trading.
Output: build_miner() -> dict (card + API), build_text() -> str (AI prompt).
"""
import json
import math
import os
import random
import threading
import time
from itertools import combinations

from . import trade_store

IST_OFFSET_S = 5.5 * 3600
MIN_TOTAL = 30          # below this many trades nothing is called a pattern
SPLIT = 0.6             # oldest 60% = discovery, newest 40% = re-check
MIN_TRAIN = 8           # trades a pattern needs in the old part
MIN_TEST = 5            # ... and in the new part, to be re-checked at all
T_MIN = 2.6             # how clear the difference must be in the old part
T_NEW = 1.0             # ... and how clear it must still be on the newer part
HOLD_FRAC = 0.4         # new-part edge must be >= 40% of old-part edge
MAX_ORDER = 3
FAST_SL_MIN = 15.0
VOL_SURGE = 1.5
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_LEARN_TAGS = ("clean", "unknown")
_CACHE_S = 300

_lock = threading.Lock()
_cache = {"key": None, "ts": 0.0, "data": None}


# ----------------------------------------------------------------- helpers
def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _has(v):
    return v is not None and v != ""


def _ts(t):
    ts = _f(t.get("opened_at_ts"), 0.0)
    if ts <= 0:
        ts = _f(t.get("closed_at_ts"), 0.0) - _f(t.get("duration_seconds"), 0.0)
    return ts


def _median(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2.0


def _sl_dist(t):
    try:
        e, sl = float(t.get("entry_price")), float(t.get("signal_stop_loss"))
        return abs(e - sl) / e * 100.0 if e > 0 and sl > 0 else None
    except (TypeError, ValueError):
        return None


def _regime(t):
    if not _has(t.get("regime_cross_n")):
        return None
    n = int(_f(t.get("regime_cross_n")))
    return "clean" if n <= 1 else ("mixed" if n == 2 else "choppy")


def _loss_type(t, thr):
    """Why a losing trade lost. None for winners."""
    if _f(t.get("pnl_usdt")) > 0:
        return None
    if t.get("tp_hit_levels"):
        return "reversal after TP1"
    dur = t.get("duration_minutes")
    if _has(dur) and _f(dur) <= FAST_SL_MIN:
        return "quick stop"
    if _f(t.get("peak_roi_pct")) >= thr:
        return "went green, no TP1"
    return "sideways then stop"


def _roi_dist(t, key):
    """Distance entry -> signal level in ROI % (price % x leverage)."""
    try:
        e, v, lev = float(t.get("entry_price")), float(t.get(key)), float(t.get("leverage") or 1)
        return abs(v - e) / e * 100.0 * lev if e > 0 and v > 0 else None
    except (TypeError, ValueError):
        return None


def _fee_labels(t):
    """How big the exchange fee is next to this trade's risk (SL) and first reward (TP1).
    A fee that eats half the SL distance, or most of TP1, makes a trade lose by design."""
    out = {}
    fee = _f(t.get("fee_roi_pct"))
    if fee <= 0:
        return out
    sl = _roi_dist(t, "signal_stop_loss")
    if sl:
        r = fee / sl
        out["fee_vs_sl"] = "fee<20% of SL" if r < 0.2 else ("fee 20-40% of SL" if r < 0.4 else "fee 40%+ of SL")
    tp1 = _roi_dist(t, "signal_tp1")
    if tp1:
        x = tp1 / fee
        out["tp1_vs_fee"] = "TP1<2x fee" if x < 2 else ("TP1 2-4x fee" if x < 4 else "TP1 4x+ fee")
    return out


def _is_sell(t):
    return str(t.get("action") or "").upper() in ("SELL", "SHORT")


def _slope_turn(t):
    """Entry EMA-slope shape RELATIVE to the trade: is the EMA already moving with the
    trade, just turning towards it, or against it? None for trades saved before the
    ema_turn tag existed."""
    ev = t.get("ema_turn")
    if not ev or ev == "unknown":
        return None
    if ev == "flat":
        return "EMA flat"
    up = "up" in ev
    with_trade = (not up) if _is_sell(t) else up
    word = "turning" if ev.startswith("turning") else "steady"
    return f"EMA {word} {'WITH' if with_trade else 'AGAINST'} trade"


def _features(trades):
    """-> list of {kind: label} per trade (same order)."""
    slopes = [abs(_f(t.get("ema_slope_pct"))) for t in trades if _has(t.get("ema_slope_pct"))]
    atrs = [_f(t.get("atr_pct")) for t in trades if _has(t.get("atr_pct"))]
    wids = [_f(t.get("sd_width_pct")) for t in trades if _has(t.get("sd_width_pct"))]
    m_sl = _median(slopes) if len(slopes) >= 10 else None
    m_atr = _median(atrs) if len(atrs) >= 10 else None
    m_wid = _median(wids) if len(wids) >= 10 else None
    out = []
    for t in trades:
        f = {}
        if t.get("action"):
            f["direction"] = str(t["action"])
        if t.get("session_tag") and t["session_tag"] != "Unknown":
            f["session"] = str(t["session_tag"])
        ts = _ts(t)
        if ts > 0:
            loc = ts + IST_OFFSET_S
            h = int((loc % 86400) // 3600)
            f["ist_time"] = f"IST {h // 4 * 4:02d}-{h // 4 * 4 + 4:02d}"
            f["weekday"] = _DAYS[(int(loc // 86400) + 3) % 7]
            f["ist_hour"] = f"IST {h:02d}h"          # single-fact only
        if _has(t.get("entry_zone")):
            f["zone"] = str(t["entry_zone"])
        if m_sl is not None and _has(t.get("ema_slope_pct")):
            f["ema"] = "steep EMA" if abs(_f(t["ema_slope_pct"])) >= m_sl else "flat EMA"
        if _has(t.get("volume_ratio")):
            f["volume"] = "volume surge" if _f(t["volume_ratio"]) >= VOL_SURGE else "normal volume"
        st = _slope_turn(t)
        if st:
            f["slope_turn"] = st
        r = _regime(t)
        if r:
            f["regime"] = r
        if m_atr is not None and _has(t.get("atr_pct")):
            f["volatility"] = "violent" if _f(t["atr_pct"]) >= m_atr else "calm"
        if m_wid is not None and _has(t.get("sd_width_pct")):
            f["sd_width"] = "wide SD" if _f(t["sd_width_pct"]) >= m_wid else "narrow SD"
        d = _sl_dist(t)
        if d is not None:
            f["sl_dist"] = "SL<1%" if d < 1 else ("SL 1-2%" if d < 2 else ("SL 2-4%" if d < 4 else "SL 4%+"))
        f.update(_fee_labels(t))
        lab = t.get("lab_labels")           # SD / Z-score / TSI / higher-timeframe facts from ai_shadow_lab
        if isinstance(lab, dict):
            for k in _LAB_KINDS:
                if lab.get(k):
                    f[k] = str(lab[k])
        if t.get("timeframe"):
            f["timeframe"] = str(t["timeframe"])
        if t.get("symbol"):
            f["coin"] = str(t["symbol"])               # single-fact only
        out.append(f)
    return out


# Only a few lab facts are mixed into the trade miner (more would make the combination search too heavy
# for the phone); the Shadow Lab mines the full set on its own signals.
_LAB_KINDS = ("z_zone", "tsi_vs_trade", "warning", "sd_shape", "phase", "htf_15m", "htf_1h")
_SINGLE_ONLY = ("coin", "ist_hour")


def _tokens(f):
    """(combinable tokens, single-only tokens)."""
    comb = sorted(f"{k}={v}" for k, v in f.items() if k not in _SINGLE_ONLY)
    single = sorted(f"{k}={v}" for k, v in f.items() if k in _SINGLE_ONLY)
    return comb, single


# ------------------------------------------------------------------ mining
def _welch(n1, s1, q1, n2, s2, q2):
    """difference of means (inside minus outside) + t-statistic with POOLED
    variance. Pooled, not Welch: a small group where every trade lost the same
    -5% has near-zero variance of its own, which would make Welch's t explode
    for pure-luck groups."""
    if n1 < 2 or n2 < 2:
        return None, None
    m1, m2 = s1 / n1, s2 / n2
    v1 = max((q1 - n1 * m1 * m1) / (n1 - 1), 0.0)
    v2 = max((q2 - n2 * m2 * m2) / (n2 - 1), 0.0)
    sp2 = ((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2)
    se = math.sqrt(sp2 * (1.0 / n1 + 1.0 / n2))
    if se < 1e-9:
        return m1 - m2, None
    return m1 - m2, (m1 - m2) / se


def _mine(toks, vals, cut, max_order=MAX_ORDER, t_min=T_MIN):
    """toks: [(comb, single)] per trade, chronological. vals: outcome per trade.
    cut: rows < cut are the OLD part. -> {combo(tuple): stats dict}."""
    agg = {}
    for i, (comb, single) in enumerate(toks):
        v = vals[i]
        q = v * v
        old = i < cut
        keys = [(s,) for s in single]
        for k in range(1, max_order + 1):
            keys.extend(combinations(comb, k))
        for key in keys:
            a = agg.get(key)
            if a is None:
                a = agg[key] = [0, 0.0, 0.0, 0, 0.0, 0.0]
            if old:
                a[0] += 1
                a[1] += v
                a[2] += q
            else:
                a[3] += 1
                a[4] += v
                a[5] += q
    n = len(vals)
    tn1 = cut
    ts1 = sum(vals[:cut])
    tq1 = sum(x * x for x in vals[:cut])
    tn2 = n - cut
    ts2 = sum(vals[cut:])
    tq2 = sum(x * x for x in vals[cut:])
    res = {}
    for key, (n1, s1, q1, n2, s2, q2) in agg.items():
        if n1 < MIN_TRAIN or tn1 - n1 < MIN_TRAIN:
            continue
        edge, t = _welch(n1, s1, q1, tn1 - n1, ts1 - s1, tq1 - q1)
        if edge is None or t is None or abs(t) < t_min:
            continue
        sign = 1 if edge > 0 else -1
        verdict, edge_te = "UNTESTED", None
        if n2 >= MIN_TEST and tn2 - n2 >= MIN_TEST:
            edge_te, t2 = _welch(n2, s2, q2, tn2 - n2, ts2 - s2, tq2 - q2)
            if edge_te is not None:
                holds = (edge_te * sign > 0 and abs(edge_te) >= HOLD_FRAC * abs(edge)
                         and t2 is not None and abs(t2) >= T_NEW)
                verdict = "CONFIRMED" if holds else "FAILED"
        res[key] = {
            "sign": sign, "edge": edge, "t": t, "verdict": verdict, "edge_te": edge_te,
            "n_tr": n1, "avg_tr": s1 / n1, "n_te": n2, "avg_te": (s2 / n2) if n2 else None,
            "n": n1 + n2, "avg": (s1 + s2) / (n1 + n2),
        }
    return res


def _prune(res):
    """Drop a combo unless it beats every smaller part of itself (same direction)."""
    keep = {}
    for key, r in res.items():
        if len(key) > 1:
            redundant = False
            for k in range(1, len(key)):
                for parent in combinations(key, k):
                    p = res.get(parent)
                    if p is not None and p["sign"] == r["sign"] and \
                            (r["avg"] - p["avg"]) * r["sign"] <= 0:
                        redundant = True
                        break
                if redundant:
                    break
            if redundant:
                continue
        keep[key] = r
    return keep


def _label(key):
    return "  +  ".join(x.split("=", 1)[1] for x in key)


# ---------------------------------------------------- pattern memory (learning)
def _mem_path():
    try:
        arch = getattr(trade_store, "_archive", None)
        if arch:
            return os.path.join(os.path.dirname(arch) or ".", "ai_patterns.json")
    except Exception:
        pass
    return None


def _mem_load():
    p = _mem_path()
    try:
        if p and os.path.exists(p):
            with open(p, "r") as fh:
                d = json.load(fh)
            if isinstance(d, dict):
                return d
    except Exception:
        pass
    return {}


def _mem_save(d):
    p = _mem_path()
    try:
        if p:
            tmp = p + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(d, fh)
            os.replace(tmp, p)
    except Exception:
        pass


def _update_memory(items, n_now):
    """streak = consecutive checks (each with new trades) a pattern stayed CONFIRMED.
    Only confirmed patterns are stored, so the file stays small."""
    mem = _mem_load()
    verdicts = {it["key"]: it["verdict"] for it in items}
    for it in items:
        k, m = it["key"], mem.get(it["key"])
        if it["verdict"] == "CONFIRMED":
            if m is None:
                m = mem[k] = {"first_n": n_now, "streak": 0, "last_n": 0}
            if n_now != m.get("last_n"):
                m["streak"] = m.get("streak", 0) + 1
                m["last_n"] = n_now
        elif m is not None:
            m.update({"streak": 0, "first_n": n_now, "last_n": n_now})
        m = mem.get(k)
        it["streak"] = m["streak"] if m else 0
        it["stable"] = bool(m) and m["streak"] >= 3 and (n_now - m.get("first_n", n_now)) >= 10
    for k in list(mem):
        if k not in verdicts and n_now - mem[k].get("last_n", 0) > 300:
            del mem[k]
    _mem_save(mem)


def _pct(vals, q):
    v = sorted(vals)
    return v[min(int(len(v) * q), len(v) - 1)] if v else None


def _hold_wait(rows):
    """How long to wait for each TP, and what happens if you keep waiting after TP1.
    All from the trades' own timestamps (minutes from entry)."""
    ladder = []
    for lvl in (1, 2, 3, 4):
        ts = [_f(t.get(f"tp{lvl}_min")) for t in rows if _has(t.get(f"tp{lvl}_min"))]
        if len(ts) >= 5:
            ladder.append({"level": lvl, "n": len(ts), "p50": _pct(ts, 0.5), "p80": _pct(ts, 0.8)})
    t1 = [t for t in rows if t.get("tp_hit_levels") and _has(t.get("tp1_min")) and _has(t.get("duration_minutes"))]
    waits = []
    if len(t1) >= 10:
        for x in (10, 20, 30, 60):
            alive = [t for t in t1 if _f(t["duration_minutes"]) > _f(t["tp1_min"]) + x]
            if len(alive) < 5:
                continue
            up = sum(1 for t in alive if len(t.get("tp_hit_levels") or []) >= 2)
            rev = sum(1 for t in alive if (t.get("clean_exit_reason") or "") in ("SL", "TSL"))
            waits.append({"wait": x, "n": len(alive), "tp2_plus": up, "reversed": rev,
                          "avg_roi": sum(_f(t.get("roi_pct")) for t in alive) / len(alive)})
    # how long BIG winners (TP3+) took vs how long reversals took, split by regime
    big = [t for t in rows if len(t.get("tp_hit_levels") or []) >= 3 and _has(t.get("duration_minutes"))]
    byreg = {}
    for t in big:
        r = _regime(t)
        if r:
            byreg.setdefault(r, []).append(_f(t["duration_minutes"]))
    reg = [{"regime": k, "n": len(v), "p50": _pct(v, 0.5), "p80": _pct(v, 0.8)}
           for k, v in sorted(byreg.items()) if len(v) >= 4]
    if not ladder and not waits:
        return None
    return {"ladder": ladder, "waits": waits, "big_by_regime": reg, "n_tp1": len(t1)}


# --------------------------------------------------------------- postmortem
def _present(key, rows, feats):
    """rows matching the combo -> (n, wins, pnl, avg_roi)."""
    want = {tuple(x.split("=", 1)) for x in key}
    sel = [r for r, f in zip(rows, feats) if all(f.get(k) == v for k, v in want)]
    n = len(sel)
    if not n:
        return 0, 0, 0.0, 0.0
    return (n, sum(1 for t in sel if _f(t.get("pnl_usdt")) > 0),
            sum(_f(t.get("pnl_usdt")) for t in sel),
            sum(_f(t.get("roi_pct")) for t in sel) / n)


def _exit_rules(rows, cut):
    """What-if exit rules from each trade's best (MFE) and worst (MAE) ROI.
    Approximation: the order of peak and dip inside a trade is unknown."""
    use = [t for t in rows if _has(t.get("peak_roi_pct")) and _has(t.get("worst_drawdown_pct"))]
    if len(use) < 20:
        return None
    # keep chronological cut aligned to this subset
    ids = {id(t) for t in rows[:cut]}
    old = [t for t in use if id(t) in ids]
    new = [t for t in use if id(t) not in ids]
    if len(old) < 10 or len(new) < 5:
        return None

    def trail_gain(ts, act, tr):
        g = 0.0
        for t in ts:
            roi = _f(t.get("roi_pct"))
            peak = max(_f(t.get("peak_roi_pct")), roi)
            if peak >= act and peak - roi > tr:
                g += (peak - tr) - roi
        return g

    def cap_gain(ts, c):
        g = 0.0
        for t in ts:
            roi = _f(t.get("roi_pct"))
            if _f(t.get("worst_drawdown_pct")) <= -c and roi > -c:
                g += (-c) - roi
        return g

    out = {"n_old": len(old), "n_new": len(new),
           "base_old": sum(_f(t.get("roi_pct")) for t in old),
           "base_new": sum(_f(t.get("roi_pct")) for t in new)}
    best = None
    for act in (5, 10, 15, 20, 30):
        for tr in (3, 5, 8, 12):
            g = trail_gain(old, act, tr)
            if best is None or g > best[0]:
                best = (g, act, tr)
    if best and best[0] > 0:
        out["trail"] = {"act": best[1], "trail": best[2], "gain_old": best[0],
                        "gain_new": trail_gain(new, best[1], best[2])}
    bestc = None
    for c in (3, 5, 8, 12, 20):
        g = cap_gain(old, c)
        if bestc is None or g > bestc[0]:
            bestc = (g, c)
    if bestc:
        out["cap"] = {"cap": bestc[1], "gain_old": bestc[0], "gain_new": cap_gain(new, bestc[1])}
    wins = sorted(abs(_f(t.get("worst_drawdown_pct"))) for t in use if _f(t.get("pnl_usdt")) > 0)
    if len(wins) >= 8:
        out["winner_dip"] = {"n": len(wins), "p50": wins[len(wins) // 2],
                             "p80": wins[int(len(wins) * 0.8)], "p95": wins[min(int(len(wins) * 0.95), len(wins) - 1)]}
    return out




# ------------------------------------------------ SD size and shape during a trade
SD_MIN = 20            # trades with >= 2 saved SD bars before any SD result is shown
EXPAND, SHRINK = 1.2, 0.85   # width now / width at entry


def _sd_info(r):
    """(w0, ratio_end, drift_pct, early_ratio, early_t_min) or None. Uses the SD bars
    saved while the trade was open (ai_sd_tracker)."""
    sd = r.get("sd") or []
    if len(sd) < 2:
        return None
    w0 = _f((r.get("sd0") or {}).get("w")) or _f(sd[0][1])
    if w0 <= 0:
        return None
    last = sd[-1]
    ratio_end = _f(last[1]) / w0
    m0, m1 = _f(sd[0][2]), _f(last[2])
    drift = ((m1 - m0) / m0 * 100.0) if m0 > 0 else 0.0
    if r.get("action") == "SELL":
        drift = -drift
    early = next((s for s in sd if _f(s[0]) >= 600), None)       # first bar >= 10 min after entry
    er = (_f(early[1]) / w0, _f(early[0]) / 60.0) if early else (None, None)
    return w0, ratio_end, drift, er[0], er[1]


def _grp(name, recs, overall, idx_cut):
    """Outcome numbers for one group of (rec, order index)."""
    if not recs:
        return None
    nets = [_rnet(r) for r, _ in recs]
    t1 = sum(1 for r, _ in recs if _first_hit(r, (r.get("levels") or {}).get("tp1")) is not None)
    t2 = sum(1 for r, _ in recs if _first_hit(r, (r.get("levels") or {}).get("tp2")) is not None)
    o = [_rnet(r) for r, i in recs if i < idx_cut]
    nw = [_rnet(r) for r, i in recs if i >= idx_cut]
    avg = sum(nets) / len(nets)
    g = {"name": name, "n": len(recs), "avg": avg, "win": 100.0 * sum(1 for x in nets if x > 0) / len(nets),
         "tp1": 100.0 * t1 / len(recs), "tp2": 100.0 * t2 / len(recs),
         "old": (sum(o) / len(o)) if o else None, "new": (sum(nw) / len(nw)) if nw else None, "n_new": len(nw)}
    g["steady"] = (g["old"] is not None and g["new"] is not None and len(nw) >= 5 and len(o) >= 5
                   and ((g["old"] - overall) * (g["new"] - overall) > 0))
    return g


def _sd_study(use, cut):
    """SD width/shape while the trade was open vs how the trade ended (after fee).
    Groups: width at entry (small/mid/big), width change by the end (expanded / flat /
    shrunk), centre line drifting WITH or AGAINST the trade, and the early warning
    'width already >= 1.2x entry after 10 min'."""
    rows = [(r, i) for i, r in enumerate(use)]
    info = [(r, i, _sd_info(r)) for r, i in rows]
    info = [(r, i, x) for r, i, x in info if x]
    out = {"ready": False, "n_sd": len(info), "need": SD_MIN}
    if len(info) < SD_MIN:
        return out
    overall = sum(_rnet(r) for r, _, _ in info) / len(info)
    out.update({"ready": True, "overall_avg": overall})
    w0s = sorted(x[0] for _, _, x in info)
    a, b = w0s[len(w0s) // 3], w0s[2 * len(w0s) // 3]
    out["w0_cuts"] = [a, b]
    groups = {"size": [], "shape": [], "centre": [], "early": []}
    for nm, sel in (("small SD at entry", lambda x: x[0] < a), ("mid SD at entry", lambda x: a <= x[0] < b),
                    ("big SD at entry", lambda x: x[0] >= b)):
        groups["size"].append(_grp(nm, [(r, i) for r, i, x in info if sel(x)], overall, cut))
    for nm, sel in (("SD expanded (>=1.2x entry)", lambda x: x[1] >= EXPAND),
                    ("SD about same", lambda x: SHRINK < x[1] < EXPAND),
                    ("SD shrank (<=0.85x entry)", lambda x: x[1] <= SHRINK)):
        groups["shape"].append(_grp(nm, [(r, i) for r, i, x in info if sel(x)], overall, cut))
    groups["centre"].append(_grp("centre moved WITH trade", [(r, i) for r, i, x in info if x[2] > 0], overall, cut))
    groups["centre"].append(_grp("centre moved AGAINST trade", [(r, i) for r, i, x in info if x[2] <= 0], overall, cut))
    e = [(r, i, x) for r, i, x in info if x[3] is not None]
    groups["early"].append(_grp("after 10 min SD already >=1.2x", [(r, i) for r, i, x in e if x[3] >= EXPAND], overall, cut))
    groups["early"].append(_grp("after 10 min SD not expanded", [(r, i) for r, i, x in e if x[3] < EXPAND], overall, cut))
    out["groups"] = {k: [g for g in v if g] for k, v in groups.items()}
    return out


# ------------------------------------------ EMA slope during a trade (needs ai_slope_tracker data)
SLOPE_MIN = 20         # trades with >= 2 saved slope bars before any slope result is shown
FLIP_EPS = 0.005       # % - slope smaller than this counts as flat, not a flip


def _slope_info(r):
    """(s0, s_end, flipped, early_flip, early_t_min) or None. Slopes are ORIENTED:
    + = EMA moving WITH the trade (BUY up / SELL down). flipped = slope started WITH the
    trade and was clearly AGAINST it at some bar before the trade closed (fake-signal sign)."""
    sl = r.get("slope") or []
    if len(sl) < 2 or r.get("slope0") is None:
        return None
    k = -1.0 if _is_sell(r) else 1.0
    s0 = _f(r.get("slope0")) * k
    ser = [(_f(x[0]), _f(x[1]) * k) for x in sl]
    flipped = any(v < -FLIP_EPS for _, v in ser) and s0 > FLIP_EPS
    early = next(((t, v) for t, v in ser if t >= 600), None)       # first bar >= 10 min after entry
    return s0, ser[-1][1], flipped, (early[1] < -FLIP_EPS if early and s0 > FLIP_EPS else None), \
        (early[0] / 60.0 if early else None)


def _slope_study(use, cut):
    """How the EMA slope behaved AFTER entry vs how the trade ended (after fee).
    Groups: slope at entry (with / against / flat), slope by the end (kept or grew /
    faded / flipped against), 'flipped against before the trade closed' (fake-signal
    sign) and the early warning 'slope already against after 10 min'."""
    info = [(r, i, _slope_info(r)) for i, r in enumerate(use)]
    info = [(r, i, x) for r, i, x in info if x]
    out = {"ready": False, "n_slope": len(info), "need": SLOPE_MIN}
    if len(info) < SLOPE_MIN:
        return out
    overall = sum(_rnet(r) for r, _, _ in info) / len(info)
    out.update({"ready": True, "overall_avg": overall})
    groups = {"entry": [], "end": [], "flip": [], "early": []}

    def add(gname, name, sel, rows=None):
        groups[gname].append(_grp(name, [(r, i) for r, i, x in (rows or info) if sel(x)], overall, cut))

    add("entry", "slope WITH trade at entry", lambda x: x[0] > FLIP_EPS)
    add("entry", "slope AGAINST trade at entry", lambda x: x[0] < -FLIP_EPS)
    add("entry", "slope flat at entry", lambda x: abs(x[0]) <= FLIP_EPS)
    add("end", "slope stayed/grew with trade", lambda x: x[1] > FLIP_EPS)
    add("end", "slope faded to flat", lambda x: abs(x[1]) <= FLIP_EPS)
    add("end", "slope ended AGAINST trade", lambda x: x[1] < -FLIP_EPS)
    add("flip", "slope flipped against BEFORE close", lambda x: x[2])
    add("flip", "slope never flipped", lambda x: not x[2] and x[0] > FLIP_EPS)
    e = [(r, i, x) for r, i, x in info if x[3] is not None]
    add("early", "after 10 min slope already AGAINST", lambda x: x[3], e)
    add("early", "after 10 min slope still with trade", lambda x: not x[3], e)
    out["groups"] = {k: [g for g in v if g] for k, v in groups.items()}
    sl_trades = [(r, x) for r, i, x in info if _rnet(r) < 0 and _f(r.get("roi_final")) < 0]
    if sl_trades:
        fl = sum(1 for _, x in sl_trades if x[2])
        out["fake"] = {"losers": len(sl_trades), "flipped": fl}
    return out


# ------------------------------------------------- real price-path replay
PATH_MIN = 20          # finished trades with a saved path before any replay result is shown
PATH_MIN_NEW = 8       # ... and in the newer part, to call a rule HELD


def _rfee(r):
    return _f(r.get("fee"))


def _rnet(r):
    """Final ROI of a saved path AFTER the exchange fee."""
    return _f(r.get("roi_final")) - _rfee(r)


def _sim(rec, be=True, tgt=4, trail=None, cap=None, tstop=None, lock=0.0):
    """Replay ONE trade's saved path under a rule set -> (exit ROI %, minutes).
    Rules (all in ROI %, same units as the app):
      be     SL moves to entry once TP1 was touched (what the bot does today)
      lock   ROI points above entry that SL moves to after TP1 (0 = entry; fee = "entry + fee")
      (all results are GROSS price ROI; the exchange fee is subtracted by the caller)
      tgt    full exit at this TP level (1-4); falls back to the highest saved TP
      trail  (act, gap): once peak >= act, stop follows peak - gap
      cap    max loss: stop never lower than -cap
      tstop  exit at market if TP1 not touched within this many minutes
    Inside one 15 s sample the order of the low and the high is unknown, so the
    STOP is always checked first (pessimistic) - a rule can only look better
    than it is when it really would have worked."""
    lv = rec.get("levels") or {}
    sl = lv.get("sl")
    if sl is None:
        return None
    tp1 = lv.get("tp1")
    tpt = lv.get(f"tp{tgt}")
    if tpt is None:
        for n in (4, 3, 2, 1):
            if lv.get(f"tp{n}") is not None:
                tpt = lv[f"tp{n}"]
                break
    peak = 0.0
    tp1_hit = False
    for t, roi, lo, hi in rec.get("s") or []:
        mins = t / 60.0
        stop = sl
        if cap is not None:
            stop = max(stop, -cap)
        if be and tp1_hit:
            stop = max(stop, lock)
        if trail is not None and peak >= trail[0]:
            stop = max(stop, peak - trail[1])
        if lo <= stop:
            return stop, mins
        if tstop is not None and not tp1_hit and mins >= tstop:
            return roi, mins
        if hi > peak:
            peak = hi
        if tpt is not None and hi >= tpt:
            return tpt, mins
        if tp1 is not None and hi >= tp1:
            tp1_hit = True
    last = (rec.get("s") or [[0, rec.get("roi_final", 0.0)]])[-1]
    return _f(rec.get("roi_final")), last[0] / 60.0


def _first_hit(rec, level):
    """Minutes until the path first reached `level` ROI, else None."""
    if level is None:
        return None
    for t, roi, lo, hi in rec.get("s") or []:
        if hi >= level:
            return t / 60.0
    return None


def _path_study(rows):
    """Uses the saved real ROI path of each trade (ai_path_logger). Only trades
    that have a clean path (no long price gaps) take part. Rules are searched on
    the OLDER 60% of those trades and re-checked on the NEWER 40%."""
    try:
        from . import ai_path_logger
    except Exception:
        return None
    paths = ai_path_logger.load_paths()
    out = {"n_paths": len(paths), "need": PATH_MIN, "ready": False}
    if not paths:
        return out
    use = []
    for t in rows:
        r = paths.get(ai_path_logger.make_key(t.get("id"), t.get("opened_at_ts")))
        if not r or not r.get("s") or (r.get("levels") or {}).get("sl") is None:
            continue
        dur = max(1.0, _f(r["s"][-1][0]))
        if _f(r.get("gaps")) > 0.1 * dur:
            continue
        use.append(r)
    out["n_used"] = len(use)
    out["sd_study"] = _sd_study(use, int(len(use) * SPLIT))
    out["slope_study"] = _slope_study(use, int(len(use) * SPLIT))
    if len(use) < PATH_MIN:
        return out
    cut = int(len(use) * SPLIT)
    old, new = use[:cut], use[cut:]
    out.update({"ready": True, "n_old": len(old), "n_new": len(new)})

    def total(ts, **kw):
        s_ = 0.0
        for r in ts:
            x = _sim(r, **kw)
            if x:
                s_ += x[0] - _rfee(r)
        return s_

    base = {}
    err = [abs(_sim(r)[0] - _rfee(r) - _rnet(r)) for r in use if _sim(r)]
    out["replay_err"] = sum(err) / len(err) if err else None
    b_old, b_new = total(old), total(new)
    out["base_old"], out["base_new"] = b_old, b_new

    grids = {
        "target": [("TP1", dict(tgt=1)), ("TP2", dict(tgt=2)), ("TP3", dict(tgt=3))],
        "no breakeven shift": [("off", dict(be=False))],
        "breakeven + fee": [("SL to entry+fee after TP1", dict(lock=max(_median([_rfee(r) for r in use]) or 0.0, 0.0)))],
        "trail": [(f"after +{a}% ROI, gap {g}%", dict(trail=(a, g)))
                  for a in (5, 10, 15, 20, 30) for g in (3, 5, 8, 12)],
        "max loss": [(f"{c}% ROI", dict(cap=c)) for c in (3, 5, 8, 12, 20)],
        "time stop": [(f"no TP1 in {m} min", dict(tstop=m)) for m in (15, 30, 60, 120)],
    }
    rules, picked = [], {}
    for name, opts in grids.items():
        best = None
        for lab, kw in opts:
            g = total(old, **kw) - b_old
            if best is None or g > best[0]:
                best = (g, lab, kw)
        g_old, lab, kw = best
        g_new = total(new, **kw) - b_new
        held = g_old > 0 and g_new > 0 and len(new) >= PATH_MIN_NEW
        rules.append({"name": name, "param": lab, "gain_old": g_old, "gain_new": g_new,
                      "held": held, "helps_old": g_old > 0})
        if held:
            picked.update(kw)
    out["rules"] = rules
    if len(picked) >= 2:
        out["combo"] = {"gain_old": total(old, **picked) - b_old,
                        "gain_new": total(new, **picked) - b_new,
                        "rules": [r["name"] + " = " + r["param"] for r in rules if r["held"]]}

    # when does TP1 / TP2.. really come (from the path, not just the TP stamps)
    tm = {}
    for n in (1, 2, 3, 4):
        v = [m for m in (_first_hit(r, (r.get("levels") or {}).get(f"tp{n}")) for r in use) if m is not None]
        if len(v) >= 5:
            tm[n] = {"n": len(v), "p50": _pct(v, 0.5), "p80": _pct(v, 0.8)}
    out["tp_time"] = tm

    # no TP1 yet after X minutes -> what happened next
    wait = []
    for x in (15, 30, 60, 120):
        still = []
        for r in use:
            m1 = _first_hit(r, (r.get("levels") or {}).get("tp1"))
            dur = _f(r["s"][-1][0]) / 60.0
            if dur > x and (m1 is None or m1 > x):
                still.append((m1 is not None, _rnet(r)))
        if len(still) >= 5:
            wait.append({"after": x, "n": len(still), "later_tp1": sum(1 for a, _ in still if a),
                         "avg_roi": sum(b for _, b in still) / len(still),
                         "won": sum(1 for _, b in still if b > 0)})
    out["no_tp1_wait"] = wait

    # REAL order: how deep did winners dip BEFORE their first TP1 touch
    dips = []
    for r in use:
        if _rnet(r) <= 0:
            continue
        lv1 = (r.get("levels") or {}).get("tp1")
        if lv1 is None:
            continue
        lo_before = 0.0
        for t, roi, lo, hi in r["s"]:
            lo_before = min(lo_before, lo)
            if hi >= lv1:
                break
        dips.append(abs(lo_before))
    if len(dips) >= 8:
        dips.sort()
        out["winner_dip_first"] = {"n": len(dips), "p50": _pct(dips, 0.5),
                                   "p80": _pct(dips, 0.8), "p95": _pct(dips, 0.95)}
    return out



# ------------------------------------------------------ fee + "if you had skipped"
def _fee_view(rows):
    """Real picture after exchange fees: gross P&L (price only) vs net (after fee)."""
    fees = [_f(t.get("fee_usdt")) for t in rows]
    if not any(fees):
        return None
    net = sum(_f(t.get("pnl_usdt")) for t in rows)
    tot = sum(fees)
    wins_net = sum(1 for t in rows if _f(t.get("pnl_usdt")) > 0)
    wins_gross = sum(1 for t in rows if _f(t.get("pnl_usdt")) + _f(t.get("fee_usdt")) > 0)
    return {"n": len(rows), "n_est": sum(1 for t in rows if t.get("fee_est")),
            "fee_roi": _median([_f(t.get("fee_roi_pct")) for t in rows if _has(t.get("fee_roi_pct"))]),
            "fee_usdt": tot, "net": net, "gross": net + tot,
            "wins_net": wins_net, "wins_gross": wins_gross}


def _skip_stats(sel):
    wins = [t for t in sel if _f(t.get("pnl_usdt")) > 0]
    loss = [t for t in sel if _f(t.get("pnl_usdt")) <= 0]
    mh = sum(_f(t.get("invest_usdt")) * _f(t.get("duration_minutes")) / 60.0 for t in sel)
    return {"n": len(sel), "pnl": sum(_f(t.get("pnl_usdt")) for t in sel),
            "wins": len(wins), "win_pnl": sum(_f(t.get("pnl_usdt")) for t in wins),
            "loss_pnl": sum(_f(t.get("pnl_usdt")) for t in loss),
            "fee": sum(_f(t.get("fee_usdt")) for t in sel), "margin_hours": mh}


def _skip_report(rows, feats, items, cut):
    """If the bot had skipped every trade matching a CONFIRMED AVOID pattern:
    how many trades, how much net P&L, how many winners would be lost. Plain
    counting on real closed trades, split old vs new. Advice only."""
    avoid = [i for i in items if i["verdict"] == "CONFIRMED" and i["kind"] == "AVOID"]
    out = {"patterns": len(avoid), "total_n": len(rows),
           "total_pnl": sum(_f(t.get("pnl_usdt")) for t in rows)}
    if not avoid:
        out["curve"] = _learn_curve(rows, [False] * len(rows), cut)
        return out
    wants = [{tuple(x.split("=", 1)) for x in i["key"].split("|")} for i in avoid]
    hit = [any(all(f.get(k) == v for k, v in w) for w in wants) for f in feats]
    sel = [t for t, h in zip(rows, hit) if h]
    out["all"] = _skip_stats(sel)
    out["old"] = _skip_stats([t for j, (t, h) in enumerate(zip(rows, hit)) if h and j < cut])
    out["new"] = _skip_stats([t for j, (t, h) in enumerate(zip(rows, hit)) if h and j >= cut])
    out["labels"] = [i["label"] for i in avoid[:4]]
    out["curve"] = _learn_curve(rows, hit, cut)
    return out


def _learn_curve(rows, hit, cut, max_pts=120):
    """Running total P&L (USDT), trade by trade in time order: what the bot really made vs
    what it would have made had it skipped the trades that match a CONFIRMED AVOID pattern.
    Both lines are shown NET (fee already taken off) and GROSS (price move only, fee added
    back) so the fee is visible. `cut` marks where the NEWER 40% (not used to find the
    patterns) starts - that part is the honest test. Plain counting, no prediction."""
    a_net = a_gro = s_net = s_gro = 0.0
    pts = []
    for t, h in zip(rows, hit):
        net = _f(t.get("pnl_usdt"))
        gro = net + _f(t.get("fee_usdt"))
        a_net += net
        a_gro += gro
        if not h:
            s_net += net
            s_gro += gro
        pts.append([round(a_net, 3), round(s_net, 3), round(a_gro, 3), round(s_gro, 3)])
    if len(pts) > max_pts:
        step = len(pts) / float(max_pts)
        idx = sorted({min(len(pts) - 1, int(i * step)) for i in range(max_pts)} | {len(pts) - 1})
        cut = sum(1 for i in idx if i < cut)
        pts = [pts[i] for i in idx]
    return {"cols": ["actual_net", "skip_net", "actual_gross", "skip_gross"], "pts": pts, "cut": cut,
            "fee_total": round(sum(_f(t.get("fee_usdt")) for t in rows), 3)}


# --------------------------------------------------------------------- main
def _null_threshold(toks, vals, cut, max_order, runs):
    """Max-T permutation test (the standard fix for 'tried hundreds of combos, some
    look good by luck'): shuffle the OLD-part results `runs` times, record the
    biggest |t| any combo reaches by pure luck, and demand real patterns beat the
    2nd-biggest of those. Returns the |t| threshold (never below T_MIN)."""
    rnd = random.Random(11)
    old_toks = toks[:cut]
    best = []
    for _ in range(runs):
        v = list(vals[:cut])
        rnd.shuffle(v)
        agg = {}
        for (comb, single), x in zip(old_toks, v):
            keys = [(s_,) for s_ in single]
            for k in range(1, max_order + 1):
                keys.extend(combinations(comb, k))
            for key in keys:
                a = agg.get(key)
                if a is None:
                    a = agg[key] = [0, 0.0, 0.0]
                a[0] += 1
                a[1] += x
                a[2] += x * x
        tn, ts_, tq = cut, sum(v), sum(x * x for x in v)
        mx = 0.0
        for n1, s1, q1 in agg.values():
            if n1 < MIN_TRAIN or tn - n1 < MIN_TRAIN:
                continue
            _e, t = _welch(n1, s1, q1, tn - n1, ts_ - s1, tq - q1)
            if t is not None and abs(t) > mx:
                mx = abs(t)
        best.append(mx)
    best.sort(reverse=True)
    return max(T_MIN, best[1] if len(best) > 1 else best[0] if best else T_MIN)


def _shuffled_confirmed(toks, vals, cut, t_min):
    rnd = random.Random(7)
    counts = []
    for _ in range(2):
        v = list(vals)
        rnd.shuffle(v)
        r = _mine(toks, v, cut, t_min=t_min)
        counts.append(sum(1 for x in r.values() if x["verdict"] == "CONFIRMED"))
    return sum(counts) / len(counts)


def _compute():
    rows = [t for t in trade_store.get_all_closed(800)
            if (t.get("quality_tag") or "unknown") in _LEARN_TAGS]
    rows.sort(key=_ts)
    try:
        from . import ai_shadow_lab
        rows = ai_shadow_lab.attach_trades(rows)
    except Exception:
        pass
    n = len(rows)
    out = {"n": n, "ready": n >= MIN_TOTAL, "min_total": MIN_TOTAL, "fee_view": _fee_view(rows)}
    if n < MIN_TOTAL:
        return out
    cut = int(n * SPLIT)
    feats = _features(rows)
    toks = [_tokens(f) for f in feats]
    roi = [_f(t.get("roi_pct")) for t in rows]
    out.update({"n_old": cut, "n_new": n - cut,
                "avg_roi": sum(roi) / n,
                "pnl": sum(_f(t.get("pnl_usdt")) for t in rows)})

    t_eff = _null_threshold(toks, roi, cut, MAX_ORDER, 12)
    out["t_needed"] = t_eff
    res = _prune(_mine(toks, roi, cut, t_min=t_eff))
    out["noise_confirmed"] = _shuffled_confirmed(toks, roi, cut, t_eff)
    items = []
    for key, r in res.items():
        cnt, wins, pnl, avg = _present(key, rows, feats)
        items.append({"key": "|".join(key), "label": _label(key), "order": len(key),
                      "kind": "TAKE" if r["sign"] > 0 else "AVOID", "verdict": r["verdict"],
                      "n": cnt, "wins": wins, "win_rate": wins / cnt * 100.0 if cnt else 0.0,
                      "avg_roi": avg, "pnl": pnl, "edge": r["edge"],
                      "n_old": r["n_tr"], "avg_old": r["avg_tr"],
                      "n_new": r["n_te"], "avg_new": r["avg_te"]})
    out["tested"] = len(res)
    _update_memory(items, n)
    rank = lambda x: (-(abs(x["edge"]) * math.sqrt(x["n"])))
    conf = sorted([i for i in items if i["verdict"] == "CONFIRMED"], key=rank)
    out["confirmed_n"] = len(conf)
    out["confirmed"] = conf[:10]
    out["take"] = [i for i in conf if i["kind"] == "TAKE"][:5]
    out["avoid"] = [i for i in conf if i["kind"] == "AVOID"][:5]
    out["untested"] = sorted([i for i in items if i["verdict"] == "UNTESTED"], key=rank)[:5]
    failed = [i for i in items if i["verdict"] == "FAILED"]
    out["failed_n"] = len(failed)
    out["failed"] = sorted(failed, key=rank)[:4]

    # ---- postmortem: why trades lose, and where each loss type concentrates
    thr = max(abs(sum(_f(t.get("roi_pct")) for t in rows if _f(t.get("pnl_usdt")) > 0) /
                  max(1, sum(1 for t in rows if _f(t.get("pnl_usdt")) > 0))) / 2.0, 0.5)
    types = [_loss_type(t, thr) for t in rows]
    losers = [(t, ty) for t, ty in zip(rows, types) if ty]
    anat = []
    for name in ("reversal after TP1", "quick stop", "sideways then stop", "went green, no TP1"):
        sel = [t for t, ty in losers if ty == name]
        if not sel:
            continue
        flag = [1.0 if ty == name else 0.0 for ty in types]
        t_loss = _null_threshold(toks, flag, cut, 2, 8)
        hot = _prune(_mine(toks, flag, cut, max_order=2, t_min=t_loss))
        spots = sorted([(k, r) for k, r in hot.items() if r["sign"] > 0 and r["verdict"] == "CONFIRMED"],
                       key=lambda kr: -(kr[1]["edge"] * math.sqrt(kr[1]["n"])))[:3]
        anat.append({
            "type": name, "n": len(sel), "share": len(sel) / n * 100.0,
            "pnl": sum(_f(t.get("pnl_usdt")) for t in sel),
            "avg_min": _median([_f(t.get("duration_minutes")) for t in sel if _has(t.get("duration_minutes"))]),
            "spots": [{"label": _label(k), "rate_in": r["avg"] * 100.0,
                       "n": r["n"]} for k, r in spots],
        })
    out["loss_anatomy"] = {"losers": len(losers), "thr": thr, "types": anat}
    out["exit_rules"] = _exit_rules(rows, cut)
    out["hold"] = _hold_wait(rows)
    out["skip_report"] = _skip_report(rows, feats, items, cut)
    out["path_study"] = _path_study(rows)
    return out


def build_miner(force=False):
    """Cached (5 min or until the closed-trade count changes). Never raises."""
    try:
        try:
            # Rebuild after every 25 new closed trades (was: after EVERY closed trade). The bot closes ~270 trades a day,
            # so the old key made this heavy job run again and again and blocked the other AI screens.
            key = (len(trade_store.get_all_closed(800)) // 25,)
        except Exception:
            key = None
        with _lock:
            c = _cache
            if (not force and c["data"] is not None and c["key"] == key
                    and time.time() - c["ts"] < _CACHE_S):
                return c["data"]
        data = _compute()
        with _lock:
            _cache.update({"key": key, "ts": time.time(), "data": data})
        return data
    except Exception:
        return {"n": 0, "ready": False, "min_total": MIN_TOTAL}


# ------------------------------------------------------ open-trade AI badge
_flag_cache = {"key": None, "ts": 0.0, "data": {}}
_FLAG_TTL = 20.0


def open_flags(positions):
    """{trade id: {"verdict": "AVOID", "labels": [...]}} for every OPEN paper
    position whose entry facts match a CONFIRMED AVOID pattern (the same
    patterns as the skip report). ADVICE ONLY: the app shows a small badge,
    nothing here ever blocks, closes or changes a trade. Cached ~20 s so the
    1-second status loop stays cheap. Never raises - any problem = no badge."""
    try:
        pos = [p for p in (positions or []) if isinstance(p, dict) and p.get("id") is not None
               and p.get("entry_zone") is not None]
        if not pos:
            return {}
        ids = tuple(sorted(str(p["id"]) for p in pos))
        now = time.time()
        with _lock:
            c = _flag_cache
            if c["key"] == ids and now - c["ts"] < _FLAG_TTL:
                return c["data"]          # cheap path for the 1 s status loop
        data = build_miner()
        avoid = [i for i in (data.get("confirmed") or []) if i.get("kind") == "AVOID"]
        if not data.get("ready") or not avoid:
            with _lock:
                _flag_cache.update({"key": ids, "ts": now, "data": {}})
            return {}
        rows = [t for t in trade_store.get_all_closed(800)
                if (t.get("quality_tag") or "unknown") in _LEARN_TAGS]
        rows.sort(key=_ts)
        try:
            from . import ai_data_logger
        except Exception:
            ai_data_logger = None
        extra = []
        for p in pos:
            d = dict(p)
            if ai_data_logger and not d.get("session_tag"):
                d["session_tag"] = ai_data_logger.session_tag(d.get("opened_at_ts"))
            extra.append(d)
        # medians (EMA slope / ATR / SD width) are taken over the closed trades too,
        # so an open trade is labelled exactly like a closed one would be.
        feats = _features(rows + extra)[len(rows):]
        wants = [(i["label"], {tuple(x.split("=", 1)) for x in i["key"].split("|")}) for i in avoid]
        out = {}
        for p, f in zip(pos, feats):
            hit = [lab for lab, w in wants if all(f.get(k) == v for k, v in w)]
            if hit:
                out[str(p["id"])] = {"verdict": "AVOID", "labels": hit[:2]}
        with _lock:
            _flag_cache.update({"key": ids, "ts": now, "data": out})
        return out
    except Exception:
        return {}


# --------------------------------------------------------------- AI prompt
def _pline(p):
    new = (f", new part {p['n_new']} trades avg {p['avg_new']:+.1f}%" if p.get("avg_new") is not None
           else ", not yet re-checked on newer trades")
    st = " STABLE" if p.get("stable") else (f" (confirmed {p.get('streak', 0)} checks in a row)" if p.get("streak") else "")
    return (f"  [{p['kind']}] {p['label']}: {p['n']} trades, win {p['win_rate']:.0f}%, avg ROI {p['avg_roi']:+.1f}%, "
            f"P&L {p['pnl']:+.2f} USDT | old part {p['n_old']} trades avg {p['avg_old']:+.1f}%{new} -> {p['verdict']}{st}")


def build_text():
    """Prompt block for ai_assistant (via ai_stats.build_summary). '' if nothing."""
    try:
        d = build_miner()
        if not d.get("n"):
            return ""
        if not d.get("ready"):
            return (f"PATTERN MINER: only {d['n']} learn-trades (needs {d['min_total']}) - no self-discovered "
                    f"patterns yet. Say the data is too thin; do not invent any pattern.")
        L = [f"PATTERN MINER (code searched {d['tested']} fact-combinations on {d['n']} trades; found on the OLDER "
             f"{d['n_old']} trades and re-checked on the NEWER {d['n_new']}. NO scores - only measured results. "
             f"avg ROI over all = {d['avg_roi']:+.1f}% per trade. A pattern had to beat what pure luck produced "
             f"on shuffled results (|t| >= {d.get('t_needed', 0):.1f})):"]
        conf_n = d.get("confirmed_n", 0)
        noise = d.get("noise_confirmed", 0.0)
        L.append(f"  NOISE CHECK: on shuffled (fake) results the same search 'confirms' ~{noise:.1f} patterns by luck; "
                 f"on the real data it confirmed {conf_n}. "
                 + ("Real confirmed count is NOT clearly above luck - call every pattern a weak hint."
                    if conf_n <= noise + 1 else "Real count is above luck - still a hint, not a promise."))
        if d.get("take"):
            L.append(" CONFIRMED TAKE-type patterns (held on newer trades):")
            L += [_pline(p) for p in d["take"]]
        if d.get("avoid"):
            L.append(" CONFIRMED AVOID-type patterns (kept losing on newer trades):")
            L += [_pline(p) for p in d["avoid"]]
        if not d.get("take") and not d.get("avoid"):
            L.append(" No pattern has been confirmed on newer trades yet - say so plainly.")
        if d.get("untested"):
            L.append(" CANDIDATES (found on old trades, newer trades too few to check yet - weakest evidence):")
            L += [_pline(p) for p in d["untested"][:3]]
        if d.get("failed_n"):
            L.append(f" FAILED the newer-trade test: {d['failed_n']} patterns looked good/bad on old trades but "
                     f"flipped or vanished on new ones (e.g. " +
                     "; ".join(f"{p['label']}" for p in d.get("failed", [])[:2]) +
                     ") - proof that some 'patterns' are luck; never present these as rules.")
        la = d.get("loss_anatomy") or {}
        if la.get("types"):
            L.append(f" LOSS POSTMORTEM ({la['losers']} losing trades; 'went green' = best profit >= {la['thr']:.1f}% ROI):")
            for ty in la["types"]:
                med = f", median {ty['avg_min']:.0f} min" if ty.get("avg_min") is not None else ""
                L.append(f"  {ty['type']}: {ty['n']} trades ({ty['share']:.0f}% of all), P&L {ty['pnl']:+.2f} USDT{med}")
                for s in ty["spots"]:
                    L.append(f"     concentrates in (held old+new): {s['label']} ({s['n']} trades)")
        ho = d.get("hold")
        if ho:
            L.append(" HOLD / WAIT LESSONS (minutes from entry, from the trades' own TP timestamps):")
            for g in ho["ladder"]:
                L.append(f"  TP{g['level']}: {g['n']} trades reached it, usually by ~{g['p50']:.0f} min, "
                         f"8 in 10 by ~{g['p80']:.0f} min")
            if ho["waits"]:
                L.append(f"  If you kept holding AFTER TP1 ({ho['n_tp1']} TP1-touchers; only trades still open at that wait):")
                for w in ho["waits"]:
                    L.append(f"    still open {w['wait']} min after TP1: {w['n']} trades -> {w['tp2_plus']} later hit TP2+, "
                             f"{w['reversed']} ended by SL/TSL, avg final ROI {w['avg_roi']:+.1f}%")
            for r in ho["big_by_regime"]:
                L.append(f"  TP3+ winners in a {r['regime']} market took ~{r['p50']:.0f} min (8 in 10 within ~{r['p80']:.0f} min), n={r['n']}")
        er = d.get("exit_rules")
        if er:
            L.append(f" EXIT WHAT-IF (from each trade's best/worst ROI; APPROXIMATE - order of peak/dip unknown; "
                     f"old {er['n_old']} trades vs new {er['n_new']}; values in ROI-points summed):")
            if er.get("trail"):
                t = er["trail"]
                ok = "HELD on new trades" if t["gain_new"] > 0 else "did NOT help on new trades"
                L.append(f"  Trail: once profit >= {t['act']}% ROI, exit if it falls {t['trail']}% from peak -> old "
                         f"{t['gain_old']:+.0f}, new {t['gain_new']:+.0f} ({ok})")
            else:
                L.append("  No trailing rule would have helped on the old trades.")
            if er.get("cap"):
                c = er["cap"]
                L.append(f"  Max-loss cap {c['cap']}% ROI -> old {c['gain_old']:+.0f}, new {c['gain_new']:+.0f} "
                         + ("(cap would have helped)" if c["gain_old"] > 0 and c["gain_new"] > 0
                            else "(tighter stops cut winners that dipped first - current SL is fine)"))
            if er.get("winner_dip"):
                w = er["winner_dip"]
                L.append(f"  Winners dipped (worst) median {w['p50']:.1f}%, 80% of them <= {w['p80']:.1f}%, "
                         f"95% <= {w['p95']:.1f}% ROI before winning -> a stop tighter than this kills winners.")
        fv = d.get("fee_view")
        if fv:
            L.append(f" FEES: every trade pays ~{fv['fee_roi']:.1f}% ROI exchange fee (older paper trades: estimated, {fv['n_est']} of {fv['n']}). "
                     f"Over these {fv['n']} trades P&L before fee {fv['gross']:+.2f} USDT, fee {fv['fee_usdt']:.2f} USDT, "
                     f"AFTER fee {fv['net']:+.2f} USDT; winners {fv['wins_gross']} before fee -> {fv['wins_net']} after fee. "
                     f"Always quote the AFTER-fee numbers; the strategy is only profitable if AFTER-fee P&L is positive.")
        sr = d.get("skip_report")
        if sr:
            if not sr.get("patterns"):
                L.append(" SKIP REPORT: no AVOID pattern is confirmed yet - nothing can be recommended to skip.")
            else:
                a, o, nw = sr["all"], sr["old"], sr["new"]
                L.append(f" SKIP REPORT (had every trade matching a CONFIRMED AVOID pattern [{'; '.join(sr['labels'])}] been skipped; "
                         f"plain counting on real trades, AFTER fee): {a['n']} of {sr['total_n']} trades, their net P&L {a['pnl']:+.2f} USDT "
                         f"(skipping would change total by {-a['pnl']:+.2f}), {a['wins']} winners worth {a['win_pnl']:+.2f} would be lost, "
                         f"fees saved {a['fee']:.2f}, margin tied up {a['margin_hours']:.1f} USDT-hours. "
                         f"Old part: {o['n']} trades {o['pnl']:+.2f}; NEW part: {nw['n']} trades {nw['pnl']:+.2f}. "
                         f"Only call it reliable if the NEW part is also negative.")
        ps = d.get("path_study")
        if ps:
            if not ps.get("ready"):
                L.append(f" REAL PRICE-PATH REPLAY: {ps.get('n_paths', 0)} trade paths saved, {ps.get('n_used', 0)} usable "
                         f"(needs {ps.get('need', PATH_MIN)}) - path recording started recently; say replay answers are "
                         f"not available yet, do not guess trail/hold numbers from it.")
            else:
                err = ps.get("replay_err")
                L.append(f" REAL PRICE-PATH REPLAY (each trade's saved ROI path re-run under other exit rules; "
                         f"{ps['n_used']} trades, rules searched on old {ps['n_old']}, re-checked on new {ps['n_new']}; "
                         f"inside one 15 s sample the stop is assumed to hit first = pessimistic; ROI-points summed; "
                         f"baseline = today's rules (SL to entry after TP1, target TP4)"
                         + (f"; replay of today's rules is off by avg {err:.1f} ROI-points per trade vs the real result"
                            if err is not None else "") + "):")
                for r in ps.get("rules", []):
                    tag = "HELD on new trades" if r["held"] else ("helped old only - NOT proven" if r["helps_old"] else "no gain")
                    L.append(f"  {r['name']} ({r['param']}): old {r['gain_old']:+.0f}, new {r['gain_new']:+.0f} -> {tag}")
                if ps.get("combo"):
                    c = ps["combo"]
                    L.append(f"  Combined held rules ({'; '.join(c['rules'])}): old {c['gain_old']:+.0f}, new {c['gain_new']:+.0f}")
                for n, g in sorted((ps.get("tp_time") or {}).items()):
                    L.append(f"  TP{n} first touched at median ~{g['p50']:.0f} min, 8 in 10 by ~{g['p80']:.0f} min (n={g['n']})")
                for w in ps.get("no_tp1_wait", []):
                    L.append(f"  Still no TP1 after {w['after']} min ({w['n']} trades): {w['later_tp1']} touched TP1 later, "
                             f"{w['won']} ended in profit, avg final ROI {w['avg_roi']:+.1f}%")
                wd = ps.get("winner_dip_first")
                if wd:
                    L.append(f"  Winners dipped BEFORE their first TP1 (real order): median {wd['p50']:.1f}%, 80% <= {wd['p80']:.1f}%, "
                             f"95% <= {wd['p95']:.1f}% ROI (n={wd['n']}) - a stop tighter than this would have killed them.")
        sds = ps.get("sd_study") if ps else None
        if sds:
            if not sds.get("ready"):
                L.append(f" SD SIZE/SHAPE DURING TRADES: only {sds.get('n_sd', 0)} trades have saved SD bars (needs {sds.get('need', SD_MIN)}) - "
                         f"no SD-shape answer yet, do not guess.")
            else:
                L.append(f" SD SIZE/SHAPE DURING TRADES (SD bands are re-computed every bar; width = 1 SD as % of price; results AFTER fee, "
                         f"average net ROI of all these trades {sds['overall_avg']:+.2f}%; 'steady' = same side of the average on old and new trades):")
                for gname, gl in sds["groups"].items():
                    for g in gl:
                        o = f"{g['old']:+.2f}" if g["old"] is not None else "n/a"
                        nw = f"{g['new']:+.2f}" if g["new"] is not None else "n/a"
                        L.append(f"  [{gname}] {g['name']}: n={g['n']}, avg {g['avg']:+.2f}%, win {g['win']:.0f}%, "
                                 f"TP1 {g['tp1']:.0f}%, TP2 {g['tp2']:.0f}% | old {o}, new {nw} ({'steady' if g['steady'] else 'NOT proven'})")
        sls = ps.get("slope_study") if ps else None
        if sls:
            if not sls.get("ready"):
                L.append(f" EMA SLOPE DURING TRADES: only {sls.get('n_slope', 0)} trades have saved slope bars (needs {sls.get('need', SLOPE_MIN)}) - "
                         f"no slope-while-open answer yet, do not guess.")
            else:
                L.append(f" EMA SLOPE DURING TRADES (slope = EMA50 change over 3 candles, WITH trade = BUY rising / SELL falling; "
                         f"checked once per closed candle while the trade was open; results AFTER fee, average net ROI of these "
                         f"trades {sls['overall_avg']:+.2f}%; 'steady' = same side of the average on old and new trades). "
                         f"A trade that opened with the slope WITH it but later flipped AGAINST it is a possible FAKE SIGNAL:")
                for gname, gl in sls["groups"].items():
                    for g in gl:
                        o = f"{g['old']:+.2f}" if g["old"] is not None else "n/a"
                        nw = f"{g['new']:+.2f}" if g["new"] is not None else "n/a"
                        L.append(f"  [slope {gname}] {g['name']}: n={g['n']}, avg {g['avg']:+.2f}%, win {g['win']:.0f}%, "
                                 f"TP1 {g['tp1']:.0f}%, TP2 {g['tp2']:.0f}% | old {o}, new {nw} ({'steady' if g['steady'] else 'NOT proven'})")
                fk = sls.get("fake")
                if fk:
                    L.append(f"  Of {fk['losers']} losing trades with slope data, {fk['flipped']} had the slope flip against them before the close.")
        L.append("  RULES FOR YOU: quote only these numbers; never give a score or 'confidence %'; a pattern is a "
                 "fact about the PAST. Say CONFIRMED / UNTESTED / FAILED / STABLE exactly as shown; the bot still "
                 "takes every signal - you only advise.")
        return "\n".join(L)
    except Exception:
        return ""
