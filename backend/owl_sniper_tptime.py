"""owl_sniper_tptime.py - OwlSniper TP/SL TIME LEARNER (Plan F). PAPER ONLY, READ ONLY, pure functions, no file written, no network, no order code.
Question: how LONG does a Sniper trade usually take to reach its profit line (TP), its stop (SL), or the time limit?
Input = the Sniper's own closed trades (owl_sniper_lessons.read_own rows). A trade counts only if its exit reason says TP, SL or time, and its open and close times are known.
30+ RULE: numbers are shown only for a group (market state + side) with 30+ counted trades. Below that the answer is just the progress (e.g. 18 / 30), never a guess.
expect() gives one open trade its learned times: its own group if ready, else ALL setups if ready, else None.
Honest limit: the exit-reason text is read by words (TP / take profit, SL / stop, time / hold); a trade with another text is not counted.
API: build(rows), expect(tl, regime, side)"""
MIN_N = 30
VERSION = "owl_sniper_tptime 1 (Plan F)"


def _num(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _kind(t):
    s = str(t.get("clean_exit_reason") or t.get("exit_reason") or "").lower()
    if "time" in s or "hold" in s or "expire" in s:
        return "TIME"
    if "tp" in s or "take" in s or "profit" in s or "target" in s:
        return "TP"
    if "sl" in s or "stop" in s:
        return "SL"
    return None


def _held(t):
    t0, t1 = _num(t.get("opened_at_ts")), _num(t.get("closed_at_ts"))
    return int(t1 - t0) if t0 and t1 and t1 > t0 else None


def _pct(vals, q):
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * len(v)))] if v else None


def _one(items):
    """items = [(kind, held)] -> numbers only when 30+ counted trades."""
    n = len(items)
    out = {"n": n, "need": MIN_N, "ready": n >= MIN_N}
    if n < MIN_N:
        return out
    for k in ("TP", "SL"):
        h = [x for kk, x in items if kk == k]
        out[k.lower()] = {"n": len(h), "median_sec": _pct(h, 0.5), "p75_sec": _pct(h, 0.75)} if h else {"n": 0}
    out["time_n"] = sum(1 for kk, _x in items if kk == "TIME")
    return out


def build(rows):
    by = {}
    allr = []
    for t in rows or []:
        k, h = _kind(t), _held(t)
        if k is None or h is None:
            continue
        allr.append((k, h))
        key = "%s|%s" % (str(t.get("sniper_regime") or "?").upper(), "LONG" if str(t.get("action") or "").upper() == "BUY" else "SHORT")
        by.setdefault(key, []).append((k, h))
    return {"version": VERSION, "min_n": MIN_N, "all": _one(allr), "groups": {k: _one(v) for k, v in by.items()}}


def expect(tl, regime, side):
    """-> {scope, n, tp_sec, sl_sec} for an open trade, or {n, need} while still learning (n of the best available group), or None."""
    try:
        g = (tl.get("groups") or {}).get("%s|%s" % (str(regime or "?").upper(), str(side or "").upper())) or {}
        a = tl.get("all") or {}
        for scope, x in (("this setup", g), ("all setups", a)):
            if x.get("ready"):
                return {"scope": scope, "n": x["n"], "tp_sec": (x.get("tp") or {}).get("median_sec"), "sl_sec": (x.get("sl") or {}).get("median_sec")}
        return {"scope": "learning", "n": a.get("n", 0), "need": MIN_N}
    except Exception:
        return None
