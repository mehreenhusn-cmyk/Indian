"""
ai_evidence.py - the Vision AI's evidence engine (read-only, plain counting, nothing predicted).

1. extra_tags(f, side): measured tags for every judged signal - SD zone, SD shape, Z vs price, TSI zero + histogram,
   entry location in the recent range, market regime. Pure arithmetic on the indicator numbers, side-relative.
2. snapshot(V): Bot alone vs Bot + AI vs AI Own after fees, and which tag COMBINATIONS really win or lose.
   A pattern is only shown as confirmed when it is found on the OLDER 60% of trades and still holds on the NEWER 40%.
3. The "paper gate": what would have happened to the NEWER 40% if the AI had blocked the confirmed losing patterns.
It never changes, blocks or closes a trade.
"""
import threading
import time

MIN_OLD = 8          # trades a pattern needs on the older 60%
MIN_NEW = 4          # and on the newer 40%
SHOW = 6
_lock = threading.Lock()
_cache = {"ts": 0.0, "data": None}


def _f(v, d=0.0):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


def _at(a, i):
    try:
        v = a[i]
        return None if v is None else float(v)
    except Exception:
        return None


# ------------------------------------------------------------------ measured tags
def extra_tags(f, side, candles=None):
    """f = ai_ind_features.build(candles) arrays at the last closed candle. -> {tag: word}. Missing = unknown."""
    try:
        i = f["n"] - 1
        if i < 60:
            return {}
        buy = str(side).upper() == "BUY"
        dr = 1.0 if buy else -1.0
        c, sma, std, z, zs, tsi, tsl, diff, e50 = (f["c"], f["sma"], f["std"], f["z"], f["zsma"], f["tsi"], f["tsl"], f["diff"], f["e50"])
        out = {}
        ci, mi, si = _at(c, i), _at(sma, i), _at(std, i)
        if ci is not None and mi is not None and si:
            d = dr * (ci - mi) / si
            out["sd_zone"] = "SD<-1" if d < -1 else "SD-1..0" if d < 0 else "SD0..1" if d < 1 else "SD1..2" if d < 2 else "SD>2"
        s10 = _at(std, i - 10)
        ratio = (si / s10) if (si and s10) else None
        if ratio is not None:
            out["sd_shape"] = "expanding" if ratio > 1.1 else "shrinking" if ratio < 0.9 else "flat"
        c5, z0, z5 = _at(c, i - 5), _at(z, i), _at(z, i - 5)
        if None not in (ci, c5, z0, z5):
            pw, zw = dr * (ci - c5) > 0, dr * (z0 - z5) > 0
            out["z_vs_price"] = ("price_with_z_with" if zw else "price_with_z_against") if pw else ("price_against_z_with" if zw else "price_against_z_against")
        t0, l0 = _at(tsi, i), _at(tsl, i)
        if t0 is not None:
            out["tsi_zero"] = "with" if dr * t0 > 0 else "against"
        d0, d1, d2 = _at(diff, i), _at(diff, i - 1), _at(diff, i - 2)
        if None not in (d0, d1, d2):
            grow = abs(d0) > abs(d1) > abs(d2)
            shrink = abs(d0) < abs(d1) < abs(d2)
            out["tsi_hist"] = ("with_" if dr * d0 > 0 else "against_") + ("growing" if grow else "shrinking" if shrink else "flat")
        hs, ls = f.get("h") or [], f.get("l") or []
        if len(hs) > i and len(ls) > i and ci is not None:
            hh, ll = max(hs[i - 19:i + 1]), min(ls[i - 19:i + 1])
            if hh > ll:
                pos = (ci - ll) / (hh - ll)
                pos = pos if buy else 1 - pos
                out["entry_loc"] = "near_extreme" if pos >= 0.8 else "far_from_extreme" if pos <= 0.2 else "mid_range"
        cross, prev = 0, None
        for j in range(i - 19, i + 1):
            e, cj = _at(e50, j), _at(c, j)
            if e is None or cj is None:
                continue
            sgn = cj > e
            if prev is not None and sgn != prev:
                cross += 1
            prev = sgn
        zone, hist = out.get("sd_zone"), out.get("tsi_hist", "")
        if cross >= 3:
            reg = "CHOPPY"
        elif zone == "SD>2" and hist.endswith("shrinking"):
            reg = "EXHAUSTION"
        elif ratio is not None and ratio > 1.25:
            reg = "EXPANSION"
        else:
            e5 = _at(e50, i - 5)
            ei = _at(e50, i)
            reg = "TRENDING" if (ei is not None and e5 is not None and dr * (ei - e5) > 0) else "MIXED"
        out["regime"] = reg
        try:                                                  # volume vs the last 20 candles, and the 200-candle trend (a cheap higher-timeframe view)
            if candles and len(candles) > 22:
                vs = [_f(x.get("volume")) for x in candles[-21:]]
                base = sum(vs[:-1]) / 20.0
                if base > 0:
                    r = vs[-1] / base
                    out["volume"] = "high" if r > 1.5 else "low" if r < 0.7 else "normal"
            cs = f["c"][-200:]
            if len(cs) >= 150 and ci is not None:
                m200 = sum(cs) / len(cs)
                out["trend200"] = "with" if dr * (ci - m200) > 0 else "against"
        except Exception:
            pass
        return out
    except Exception:
        return {}


# ------------------------------------------------------------------ outcomes
def _tokens(dec):
    tk = []
    for k, v in (dec.get("tags2") or {}).items():
        tk.append(f"{k}={v}")
    for k, v in (dec.get("feat") or {}).items():
        if isinstance(v, bool):
            tk.append(f"{k}={'yes' if v else 'no'}")
    return tk


def _stats(vals):
    n = len(vals)
    if not n:
        return {"n": 0, "win_rate": None, "avg": None, "net": 0.0}
    w = sum(1 for v in vals if v > 0)
    return {"n": n, "win_rate": round(100.0 * w / n), "avg": round(sum(vals) / n, 3), "net": round(sum(vals), 2)}


def _rows(V):
    with V._lock:
        decs = [dict(d) for d in V._state.get("dec", [])]
        trades = [dict(t) for t in V._state.get("trades", [])]
    try:
        bm = V._bot_outcomes().get("closed", {})
    except Exception:
        bm = {}
    tr_by_dec = {t.get("dec_id"): t for t in trades}
    bot, own = [], []
    for d in decs:
        tk = _tokens(d)
        t0 = _f(d.get("sig_time") or d.get("decided_at"))
        if (d.get("source") or "bot") == "own":
            t = tr_by_dec.get(d.get("id"))
            if t and t.get("status") == "closed" and tk:
                own.append({"t": t0, "pnl": _f(t.get("pnl")), "tk": tk})
            continue
        no = d.get("signal_no")
        if no in bm:
            t = tr_by_dec.get(d.get("id"))
            bot.append({"t": t0, "pnl": _f(bm[no]), "tk": tk, "status": d.get("status"),
                        "ai_pnl": _f(t.get("pnl")) if (t and t.get("status") == "closed") else None})
    return bot, own, trades


def _mine(rows):
    """Confirmed GOOD / BAD tag combinations: same direction on the older 60% and the newer 40%."""
    rows = sorted([r for r in rows if r["tk"]], key=lambda r: r["t"])
    n = len(rows)
    if n < MIN_OLD + MIN_NEW:
        return {"n": n, "good": [], "bad": [], "blocked_new": _stats([]), "note": f"{n} trades with tags so far. Needs {MIN_OLD + MIN_NEW}+ before any pattern can be checked."}
    cut = int(n * 0.6)
    old, new = rows[:cut], rows[cut:]
    count = {}
    for r in rows:
        for k in set(r["tk"]):
            count[k] = count.get(k, 0) + 1
    toks = [k for k, c in count.items() if c >= MIN_OLD]
    cands = [(k,) for k in toks]
    toks = sorted(toks)[:40]
    for a in range(len(toks)):
        for b in range(a + 1, len(toks)):
            if toks[a].split("=")[0] != toks[b].split("=")[0]:
                cands.append((toks[a], toks[b]))

    def pick(rs, c):
        return [r["pnl"] for r in rs if all(k in r["tk"] for k in c)]
    good, bad = [], []
    for c in cands:
        po, pn = pick(old, c), pick(new, c)
        if len(po) < MIN_OLD or len(pn) < MIN_NEW:
            continue
        ao, an = sum(po) / len(po), sum(pn) / len(pn)
        item = {"pattern": " + ".join(c), "n_old": len(po), "n_new": len(pn), "avg_old": round(ao, 3), "avg_new": round(an, 3),
                "win_rate": _stats(po + pn)["win_rate"], "key": c}
        if ao > 0 and an > 0:
            good.append(item)
        elif ao < 0 and an < 0:
            bad.append(item)
    good.sort(key=lambda x: -(x["n_old"] + x["n_new"]))
    bad.sort(key=lambda x: -(x["n_old"] + x["n_new"]))
    bad = bad[:SHOW]
    blocked = [r["pnl"] for r in new if any(all(k in r["tk"] for k in b["key"]) for b in bad)]
    for x in good + bad:
        x.pop("key", None)
    return {"n": n, "good": good[:SHOW], "bad": bad, "blocked_new": _stats(blocked), "new_n": len(new),
            "note": "Patterns are found on the older 60% and checked on the newer 40%. Still a hint until there are 100+ trades."}


# ------------------------------------------------------------------ public
def snapshot(V, force=False):
    now = time.time()
    with _lock:
        if not force and _cache["data"] and now - _cache["ts"] < 60:
            return _cache["data"]
    bot, own, trades = _rows(V)
    taken = [r for r in bot if r.get("status") == "taken"]
    skipped = [r for r in bot if r.get("status") in ("skipped", "expired")]
    own_closed = [_f(t.get("pnl")) for t in trades if (t.get("source") or "bot") == "own" and t.get("status") == "closed"]
    table = [
        {"name": "Bot alone (every signal)", **_stats([r["pnl"] for r in bot])},
        {"name": "Bot + AI (signals the AI took)", **_stats([r["pnl"] for r in taken])},
        {"name": "Signals the AI blocked (bot result)", **_stats([r["pnl"] for r in skipped])},
        {"name": "AI on its taken signals (own exits)", **_stats([r["ai_pnl"] for r in taken if r.get("ai_pnl") is not None])},
        {"name": "AI Own (own scan)", **_stats(own_closed)},
    ]
    data = {"ok": True, "ts": now, "table": table, "bot_patterns": _mine(bot), "own_patterns": _mine(own),
            "note": "All results are after fees. Paper only. Nothing here changes a trade."}
    with _lock:
        _cache.update(ts=now, data=data)
    return data
