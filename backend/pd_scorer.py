"""pd_scorer.py - turns one coin's history into numbers (features), a 0-100 score and a stage candidate, for pumps (side +1) and dumps (side -1).
Pure functions, no network, no file. Time frames: 1 minute = trigger, 5 minutes = confirm, 15 / 30 minutes = is the move still alive.
Volume spike = turnover per minute of the last 1 / 5 minutes divided by the coin's own average per minute of the hour before (floor: 20% of its
24h average per minute, so a dead coin cannot give a huge ratio from a tiny base)."""
import bisect
import math

import pd_config as C


def _pct(a, b):
    return (a / b - 1.0) * 100.0 if b else 0.0


def features(h, now, qv24, poll_sec):
    """-> dict of numbers or None when there is not enough history. Keys: p r1 r5 r15 r30 vr1 vr5 flat rng brk_up brk_dn warm."""
    if h is None or len(h.t) < 4:
        return None
    tol = max(2.5 * poll_sec, 45.0)

    def at(sec):
        i = bisect.bisect_right(h.t, now - sec) - 1
        if i < 0 or (now - sec) - h.t[i] > tol:
            return -1
        return i

    i1, i5, i15, i30 = at(60), at(300), at(900), at(1800)
    if i5 < 0:
        return None
    p = h.p[-1]
    f = {"p": p,
         "r1": _pct(p, h.p[i1]) if i1 >= 0 else 0.0,
         "r5": _pct(p, h.p[i5]),
         "r15": _pct(p, h.p[i15]) if i15 >= 0 else 0.0,
         "r30": _pct(p, h.p[i30]) if i30 >= 0 else 0.0}
    ib = at(3900)
    if ib < 0:
        ib = 0
    span = h.t[i5] - h.t[ib]
    f["warm"] = span >= C.get("warm_min") * 60 - 60
    if span < 120:
        f.update(vr1=0.0, vr5=0.0, flat=False, rng=0.0, brk_up=False, brk_dn=False, warm=False)
        return f
    base = max(0.0, h.q[i5] - h.q[ib]) / (span / 60.0)
    base = max(base, qv24 / 1440.0 * 0.2, 1.0)
    v5 = max(0.0, h.q[-1] - h.q[i5]) / max((now - h.t[i5]) / 60.0, 0.5)
    v1 = max(0.0, h.q[-1] - h.q[i1]) / max((now - h.t[i1]) / 60.0, 0.25) if i1 >= 0 else v5
    f["vr5"], f["vr1"] = v5 / base, v1 / base
    seg = h.p[ib:i5 + 1]
    hi, lo = max(seg), min(seg)
    f["rng"] = _pct(hi, lo)
    f["flat"] = f["rng"] < 4.0
    f["brk_up"], f["brk_dn"] = p > hi, p < lo
    return f


def vr(f):
    """ONE volume number: the 5 min ratio, or 70% of the 1 min ratio when that is bigger (a fresh spike)."""
    return max(f["vr5"], 0.7 * f["vr1"])


def score(side, f, adj=0.0):
    """0-100. side = +1 pump, -1 dump. adj = the tuner's penalty / bonus for this coin."""
    d5, d1 = side * f["r5"], side * f["r1"]
    vol = min(40.0, vr(f) * 4.0)
    speed = min(30.0, max(d5, 0.0) * 10.0 + max(d1, 0.0) * 5.0)
    brk = 15.0 if (f["brk_up"] if side > 0 else f["brk_dn"]) else 0.0
    flat = 15.0 if f["flat"] else (5.0 if f["rng"] < 7.0 else 0.0)
    return max(0.0, min(100.0, vol + speed + brk + flat + adj))


def classify(side, f, sc):
    """Stage of a coin that is not tracked yet: 'START', 'WATCH' or None."""
    if not f.get("warm"):
        return None
    d5, d1, v = side * f["r5"], side * f["r1"], vr(f)
    if (d5 >= C.get("start_r5") or d1 >= C.get("start_r1")) and v >= C.get("start_vol") and sc >= C.get("start_score"):
        return "START"
    if d5 >= C.get("watch_r5") and v >= C.get("watch_vol") and sc >= C.get("watch_score"):
        return "WATCH"
    return None
