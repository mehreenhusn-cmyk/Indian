"""
ai_ml.py - the learning model for AI Insights (pure Python, no numpy/pandas).

A regularised logistic regression is trained on the closed trades to learn two
things: "does this setup end as a WIN" and "does it reach TP1". It is trained on
the OLDER 60% of trades and graded on the NEWER 40% it never saw. A label-shuffle
test says how good a result pure luck can give. Only if the model beats that is
it called LEARNED; otherwise it says NOT YET (honest - with a thin sample an ML
model is a blind guess).

NO per-trade score is shown to the user or the chat AI. The AI only sees:
  - did the model learn anything real (verdict + numbers on the newer trades)
  - which factors pushed toward winning / losing (top weights, in words)

Hand-off for the next AI (wiring): predict(trade_dict) -> {"win": p, "tp1": p}
or None. It is NOT called anywhere in the trading path. The fitted model is
saved to ai_model.json next to the closed-trade archive. Never raises.
"""
import json
import math
import os
import random
import threading
import time

from . import trade_store
from . import ai_miner

MIN_TRADES = 60
SPLIT = 0.6
L2 = 2.0
ITERS = 150
LR = 0.3
_CACHE_S = 300
_NUMERIC = ("ema_slope_pct", "volume_ratio", "atr_pct", "sd_width_pct", "regime_cross_n",
            "ema_slope10_pct")
_ORIENTED = ("ema_slope10_pct",)      # signed: + = EMA moving WITH the trade (BUY up / SELL down)
_CAT_KINDS = ("direction", "session", "ist_time", "weekday", "zone", "ema", "volume",
              "regime", "volatility", "sd_width", "sl_dist", "timeframe", "slope_turn")

_lock = threading.Lock()
_cache = {"key": None, "ts": 0.0, "data": None}
_model = {"spec": None, "w": {}}      # last fitted model for predict()


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _num_vec(t):
    out = []
    for k in _NUMERIC:
        v = t.get(k)
        if v in (None, ""):
            out.append(None)
        elif k == "ema_slope_pct":
            out.append(abs(_f(v)))
        elif k in _ORIENTED:
            out.append(_f(v) * (-1.0 if str(t.get("action") or "").upper() in ("SELL", "SHORT") else 1.0))
        else:
            out.append(_f(v))
    d = ai_miner._sl_dist(t)
    out.append(d)
    return out


def _build_spec(rows, feats):
    """vocabulary of categorical tokens (>=5% of trades) + numeric mean/std."""
    n = len(rows)
    cnt = {}
    for f in feats:
        for k in _CAT_KINDS:
            if k in f:
                tok = f"{k}={f[k]}"
                cnt[tok] = cnt.get(tok, 0) + 1
    vocab = sorted(t for t, c in cnt.items() if c >= max(5, 0.05 * n))
    cols = [[] for _ in range(len(_NUMERIC) + 1)]
    for t in rows:
        for i, v in enumerate(_num_vec(t)):
            if v is not None:
                cols[i].append(min(v, 50.0) if i else min(v, 50.0))
    stats = []
    for c in cols:
        if len(c) >= 5:
            m = sum(c) / len(c)
            s = math.sqrt(sum((x - m) ** 2 for x in c) / len(c)) or 1.0
            stats.append((m, s))
        else:
            stats.append((0.0, 1.0))
    names = list(vocab) + [f"num:{k}" for k in _NUMERIC] + ["num:sl_dist"]
    return {"vocab": vocab, "stats": stats, "names": names}


def _vector(t, f, spec):
    idx = {tok: i for i, tok in enumerate(spec["vocab"])}
    x = [0.0] * len(spec["names"])
    for k in _CAT_KINDS:
        if k in f:
            j = idx.get(f"{k}={f[k]}")
            if j is not None:
                x[j] = 1.0
    base = len(spec["vocab"])
    for i, v in enumerate(_num_vec(t)):
        m, s = spec["stats"][i]
        x[base + i] = 0.0 if v is None else (min(v, 50.0) - m) / s
    return x


def _fit(X, y):
    n, d = len(X), len(X[0])
    pos = sum(y)
    b = math.log((pos + 0.5) / (n - pos + 0.5))
    w = [0.0] * d
    for _ in range(ITERS):
        gb, gw = 0.0, [0.0] * d
        for xi, yi in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, xi) if xj)
            p = 1.0 / (1.0 + math.exp(-max(min(z, 30.0), -30.0)))
            e = p - yi
            gb += e
            for j, xj in enumerate(xi):
                if xj:
                    gw[j] += e * xj
        b -= LR * gb / n
        for j in range(d):
            w[j] -= LR * (gw[j] / n + L2 * w[j] / n)
    return b, w


def _prob(x, b, w):
    z = b + sum(wj * xj for wj, xj in zip(w, x) if xj)
    return 1.0 / (1.0 + math.exp(-max(min(z, 30.0), -30.0)))


def _auc(scores, y):
    pos = [s for s, v in zip(scores, y) if v]
    neg = [s for s, v in zip(scores, y) if not v]
    if not pos or not neg:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    rp = sum(r for r, v in zip(ranks, y) if v)
    return (rp - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg))


def _eval(name, X, y, rois, cut):
    """train on [:cut], grade on [cut:]."""
    yt, ye = y[:cut], y[cut:]
    if sum(yt) < 8 or sum(ye) < 4 or (len(ye) - sum(ye)) < 4:
        return {"name": name, "verdict": "NOT ENOUGH DATA", "pos_train": sum(yt), "pos_test": sum(ye)}
    b, w = _fit(X[:cut], yt)
    sc = [_prob(x, b, w) for x in X[cut:]]
    auc = _auc(sc, ye)
    rnd = random.Random(5)
    nulls = []
    for _ in range(200):
        sh = list(ye)
        rnd.shuffle(sh)
        a = _auc(sc, sh)
        if a is not None:
            nulls.append(a)
    nulls.sort()
    null95 = nulls[int(len(nulls) * 0.95) - 1] if nulls else 0.6
    order = sorted(range(len(sc)), key=lambda i: sc[i])
    third = max(1, len(order) // 3)
    lo = [rois[cut + i] for i in order[:third]]
    hi = [rois[cut + i] for i in order[-third:]]
    avg_all = sum(rois[cut:]) / len(rois[cut:])
    res = {"name": name, "n_train": cut, "n_test": len(ye), "pos_train": sum(yt), "pos_test": sum(ye),
           "auc": auc, "luck_auc95": null95,
           "top_third_roi": sum(hi) / len(hi), "bottom_third_roi": sum(lo) / len(lo), "avg_roi": avg_all}
    ok = auc is not None and auc > max(null95, 0.55) and res["top_third_roi"] > res["bottom_third_roi"]
    res["verdict"] = "LEARNED" if ok else "NOT YET"
    return res


def _mem_path():
    arch = getattr(trade_store, "_archive", None)
    return os.path.join(os.path.dirname(arch) or ".", "ai_model.json") if arch else None


def _compute():
    rows = [t for t in trade_store.get_all_closed(800)
            if (t.get("quality_tag") or "unknown") in ("clean", "unknown")]
    rows.sort(key=ai_miner._ts)
    n = len(rows)
    out = {"n": n, "ready": n >= MIN_TRADES, "min_trades": MIN_TRADES}
    if n < MIN_TRADES:
        return out
    feats = ai_miner._features(rows)
    spec = _build_spec(rows, feats)
    X = [_vector(t, f, spec) for t, f in zip(rows, feats)]
    rois = [_f(t.get("roi_pct")) for t in rows]
    y_win = [1 if _f(t.get("pnl_usdt")) > 0 else 0 for t in rows]
    y_tp1 = [1 if t.get("tp_hit_levels") else 0 for t in rows]
    cut = int(n * SPLIT)
    out["targets"] = [_eval("win", X, y_win, rois, cut), _eval("reach TP1", X, y_tp1, rois, cut)]
    out["n_features"] = len(spec["names"])
    # final fit on everything (for the wiring AI); factors reported only if something was learned
    fits = {}
    for key, y in (("win", y_win), ("tp1", y_tp1)):
        if sum(y) >= 8 and (n - sum(y)) >= 8:
            fits[key] = _fit(X, y)
    for tg, key in zip(out["targets"], ("win", "tp1")):
        if tg.get("verdict") == "LEARNED" and key in fits:
            b, w = fits[key]
            pairs = sorted(zip(spec["names"], w), key=lambda p: -abs(p[1]))[:6]
            tg["factors"] = [{"name": nm.replace("=", ": "), "dir": "helps" if wt > 0 else "hurts",
                              "weight": round(wt, 2)} for nm, wt in pairs if abs(wt) > 0.05]
    with _lock:
        _model["spec"] = spec
        _model["w"] = {k: {"b": b, "w": w} for k, (b, w) in fits.items()}
    p = _mem_path()
    try:
        if p and fits:
            with open(p + ".tmp", "w") as fh:
                json.dump({"trained_on": n, "ts": time.time(), "names": spec["names"],
                           "models": {k: {"b": b, "w": w} for k, (b, w) in fits.items()},
                           "targets": out["targets"]}, fh)
            os.replace(p + ".tmp", p)
    except Exception:
        pass
    return out


def build_ml(force=False):
    try:
        key = len(trade_store.get_all_closed(800))
        with _lock:
            c = _cache
            if not force and c["data"] is not None and c["key"] == key and time.time() - c["ts"] < _CACHE_S:
                return c["data"]
        data = _compute()
        with _lock:
            _cache.update({"key": key, "ts": time.time(), "data": data})
        return data
    except Exception:
        return {"n": 0, "ready": False, "min_trades": MIN_TRADES}


def predict(trade):
    """For the wiring AI. trade = dict with the same keys as a closed trade
    (action, session_tag, entry_zone, ema_slope_pct, volume_ratio, regime_cross_n,
    atr_pct, sd_width_pct, entry_price, signal_stop_loss, opened_at_ts, timeframe).
    Returns {"win": p, "tp1": p} or None if no model fitted yet. Not used by the bot."""
    try:
        build_ml()
        with _lock:
            spec, ms = _model["spec"], dict(_model["w"])
        if not spec or not ms:
            return None
        f = ai_miner._features([trade])[0]
        x = _vector(trade, f, spec)
        return {k: _prob(x, m["b"], m["w"]) for k, m in ms.items()}
    except Exception:
        return None


# ---------------------------------------------------------------- shadow log
# When a trade OPENS the current model's answer is saved quietly; when the trade
# CLOSES the real result is matched to it. After some weeks this says whether the
# model really predicts anything - without ever showing a per-trade number to the
# chat AI and without ever touching a trade. Screen + hand-off only.
SHADOW_MIN = 30           # matched trades before any verdict is given
_SHADOW_KEEP = 1500
_shadow = {"loaded": False, "d": {}}
_shadow_lock = threading.Lock()


def _shadow_path():
    p = _mem_path()
    return os.path.join(os.path.dirname(p), "ai_shadow.json") if p else None


def _shadow_key(t):
    try:
        from . import ai_path_logger
        return ai_path_logger.make_key(t.get("id", t.get("trade_id")), t.get("opened_at_ts"))
    except Exception:
        return f"{t.get('id')}@{int(_f(t.get('opened_at_ts')))}"


def _shadow_load():
    if _shadow["loaded"]:
        return
    _shadow["loaded"] = True
    try:
        p = _shadow_path()
        if p and os.path.exists(p):
            with open(p, "r") as fh:
                _shadow["d"] = json.load(fh) or {}
    except Exception:
        _shadow["d"] = {}


def _shadow_save():
    try:
        p = _shadow_path()
        if not p:
            return
        d = _shadow["d"]
        if len(d) > _SHADOW_KEEP:
            for k in sorted(d, key=lambda k: d[k].get("ts", 0))[:len(d) - _SHADOW_KEEP]:
                d.pop(k, None)
        with open(p + ".tmp", "w") as fh:
            json.dump(d, fh)
        os.replace(p + ".tmp", p)
    except Exception:
        pass


def _shadow_open_worker(trade):
    try:
        pr = predict(trade)          # uses the model fitted on trades closed BEFORE this one
        with _lock:
            data = _cache["data"] or {}
        verd = {tg.get("name"): tg.get("verdict") for tg in (data.get("targets") or [])}
        rec = {"ts": time.time(), "sym": trade.get("symbol"), "side": trade.get("action"),
               "win": None if not pr else round(pr.get("win", 0.0), 4),
               "tp1": None if not pr else round(pr.get("tp1", 0.0), 4),
               "v_win": verd.get("win"), "v_tp1": verd.get("reach TP1"), "done": False}
        with _shadow_lock:
            _shadow_load()
            _shadow["d"][_shadow_key(trade)] = rec
            _shadow_save()
    except Exception:
        pass


def shadow_open(trade):
    """Call when a trade opens. Runs in a background thread - never delays the trade."""
    try:
        threading.Thread(target=_shadow_open_worker, args=(dict(trade),), daemon=True,
                         name="ai-shadow-open").start()
    except Exception:
        pass


def shadow_close(pos):
    """Call when a trade closes: attach the real result to the saved guess. Never raises."""
    try:
        with _shadow_lock:
            _shadow_load()
            rec = _shadow["d"].get(_shadow_key(pos))
            if not rec or rec.get("done"):
                return
            rec.update(done=True, a_win=1 if _f(pos.get("pnl_usdt")) > 0 else 0,
                       a_tp1=1 if pos.get("tp_hit_levels") else 0,
                       roi=round(_f(pos.get("roi_pct")), 3),
                       tag=pos.get("quality_tag") or "unknown")
            _shadow_save()
    except Exception:
        pass


def _shadow_target(rows, pkey, akey):
    """rows: matched shadow records with a guess. -> verdict numbers for one target."""
    use = [r for r in rows if r.get(pkey) is not None and r.get(akey) is not None]
    out = {"n": len(use)}
    if len(use) < SHADOW_MIN:
        out["verdict"] = "COLLECTING"
        return out
    y = [r[akey] for r in use]
    sc = [r[pkey] for r in use]
    rois = [_f(r.get("roi")) for r in use]
    pos_n = sum(y)
    out.update({"base_rate": 100.0 * pos_n / len(y), "avg_roi": sum(rois) / len(rois)})
    if pos_n < 5 or len(y) - pos_n < 5:
        out["verdict"] = "NOT ENOUGH DATA"
        return out
    auc = _auc(sc, y)
    rnd = random.Random(11)
    nulls = []
    for _ in range(200):
        sh = list(y)
        rnd.shuffle(sh)
        a = _auc(sc, sh)
        if a is not None:
            nulls.append(a)
    nulls.sort()
    null95 = nulls[int(len(nulls) * 0.95) - 1] if nulls else 0.6
    order = sorted(range(len(sc)), key=lambda i: sc[i])
    third = max(1, len(order) // 3)
    lo, hi = order[:third], order[-third:]
    out.update({"auc": auc, "luck_auc95": null95,
                "top_rate": 100.0 * sum(y[i] for i in hi) / len(hi),
                "bottom_rate": 100.0 * sum(y[i] for i in lo) / len(lo),
                "top_roi": sum(rois[i] for i in hi) / len(hi),
                "bottom_roi": sum(rois[i] for i in lo) / len(lo)})
    ok = auc is not None and auc > max(null95, 0.55) and out["top_roi"] > out["bottom_roi"]
    out["verdict"] = "LEARNED" if ok else "NOT YET"
    return out


def shadow_stats():
    """For the screen only (owner view) - NOT given to the chat AI."""
    try:
        with _shadow_lock:
            _shadow_load()
            recs = list(_shadow["d"].values())
        done = [r for r in recs if r.get("done") and (r.get("tag") or "unknown") in ("clean", "unknown")]
        return {"saved": len(recs), "open": sum(1 for r in recs if not r.get("done")),
                "matched": len(done), "no_model": sum(1 for r in recs if r.get("win") is None),
                "need": SHADOW_MIN,
                "win": _shadow_target(done, "win", "a_win"),
                "tp1": _shadow_target(done, "tp1", "a_tp1")}
    except Exception:
        return {"saved": 0, "open": 0, "matched": 0, "no_model": 0, "need": SHADOW_MIN,
                "win": {"n": 0, "verdict": "COLLECTING"}, "tp1": {"n": 0, "verdict": "COLLECTING"}}


# ---------------------------------------------------------------- open-trade ML badge
# Advice only. A badge is shown on an OPEN trade only when the shadow log has PROVED the model
# (verdict LEARNED on >= SHADOW_MIN matched trades) AND this trade's quiet guess sits in the
# weakest third of past guesses. No number is ever sent out - only the word AVOID. The bot
# never stops, skips or changes a trade because of it, and chat AI never sees any of this.
_badge_cache = {"key": None, "ts": 0.0, "data": {}}
_BADGE_TTL = 20.0


def _badge_cut():
    """(cut, target) - guesses at or below `cut` are the weakest third - or None if the model
    is not proven yet. Uses the 'win' target only."""
    with _shadow_lock:
        _shadow_load()
        recs = list(_shadow["d"].values())
    done = [r for r in recs if r.get("done") and r.get("win") is not None
            and (r.get("tag") or "unknown") in ("clean", "unknown")]
    st = _shadow_target(done, "win", "a_win")
    if st.get("verdict") != "LEARNED" or len(done) < SHADOW_MIN:
        return None
    sc = sorted(r["win"] for r in done)
    return sc[max(0, len(sc) // 3 - 1)]


def open_badges(positions):
    """{trade id: {"verdict": "AVOID", "kind": "ml"}} for open positions the PROVED model rates in
    the weakest third. {} while the model is not proven. Cached ~20 s. Never raises."""
    try:
        pos = [p for p in (positions or []) if isinstance(p, dict) and p.get("id") is not None
               and p.get("entry_zone") is not None]
        if not pos:
            return {}
        ids = tuple(sorted(str(p["id"]) for p in pos))
        now = time.time()
        with _lock:
            c = _badge_cache
            if c["key"] == ids and now - c["ts"] < _BADGE_TTL:
                return c["data"]
        cut = _badge_cut()
        out = {}
        if cut is not None:
            for p in pos:
                pr = predict(dict(p))
                if pr and pr.get("win") is not None and pr["win"] <= cut:
                    out[str(p["id"])] = {"verdict": "AVOID", "kind": "ml"}
        with _lock:
            _badge_cache.update({"key": ids, "ts": now, "data": out})
        return out
    except Exception:
        return {}


def build_text():
    try:
        d = build_ml()
        if not d.get("n"):
            return ""
        if not d.get("ready"):
            return (f"ML MODEL: only {d['n']} learn-trades (needs {d['min_trades']}) - model not trained yet. "
                    f"Say so; never claim the AI 'learned' anything yet.")
        L = [f"ML MODEL (logistic regression, trained on the OLDER trades, graded on the NEWER ones it never saw; "
             f"{d['n_features']} factors). It is shadow-only: it does NOT touch trades and you must NOT quote any "
             f"per-trade probability or score."]
        for t in d["targets"]:
            if t.get("auc") is None:
                L.append(f"  Target '{t['name']}': {t['verdict']} (positives train {t.get('pos_train')}, test {t.get('pos_test')}).")
                continue
            L.append(f"  Target '{t['name']}': {t['verdict']} - on {t['n_test']} unseen trades separation (AUC) "
                     f"{t['auc']:.2f} vs {t['luck_auc95']:.2f} that luck reaches; its top-third picks averaged "
                     f"{t['top_third_roi']:+.1f}% ROI vs bottom-third {t['bottom_third_roi']:+.1f}% (all {t['avg_roi']:+.1f}%).")
            for fa in t.get("factors", []):
                L.append(f"     learned: {fa['name']} {fa['dir']}")
        if all(t.get("verdict") != "LEARNED" for t in d["targets"]):
            L.append("  Nothing real learned yet - with this much data a model is guessing. Tell the user more "
                     "clean closed trades are needed; do not present the model as intelligent yet.")
        return "\n".join(L)
    except Exception:
        return ""
