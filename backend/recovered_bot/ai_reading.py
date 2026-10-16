"""
ai_reading.py - "Indicator Reading": what BOTH indicators said at the moment a signal came, and what
happened next. Plain counting on the Shadow Lab replay rows - nothing is predicted or invented.

  MAIN chart : SD zone, EMA turn, sideways/trending, SD shape/size, volume ...
  Z-score    : zone, rising/falling, divergence, its own average line ...
  TSI        : zone, above/below signal, 4-zone, reversal arrow, momentum ...
  BOTH       : do Z and TSI agree with the trade or not.

What it builds (per timeframe):
  1. indicators : for each fact (e.g. "TSI below signal") how many signals, win %, avg ROI, SL %, TP1 %,
                  and a verdict GOOD / AVOID / UNSURE / NORMAL against the average signal.
  2. habits     : facts that are AVOID *and* common ("tu ye mauke bahut lete ho") = possible wrong use.
  3. best/avoid : 2-fact combos (one fact from two different indicator groups) that were good / bad on the
                  OLDER 60% AND still on the NEWER 40%. Each carries the exit AI found best there
                  (TP1 pe poora band = scalp, ya TP4 tak hold) - AI tells when to scalp, nothing is forced.
  4. levels     : per SD zone: what Z and TSI usually said there, and the result (SD zone x Z/TSI agreement).

PAKKA = both halves agree and enough signals. SHAYAD = both halves agree but the sample is small.
Everything is the net ROI of the live rule (fee already inside). Replay on real candles, not live trading.
READ-ONLY: it never changes, blocks or closes a trade.
"""
import threading
import time

from . import ai_exit_study as X
from . import ai_rowcache as RC
from . import ai_shadow_lab as L

LIVE = X.LIVE
MIN_ALL = 100           # signals before any verdict is called reliable
MIN_N = 30              # a fact needs at least this many signals to be judged
MIN_NEW = 10            # ... of which at least this many in the newer 40%
GAP = 1.0               # ROI points a fact must be above/below the average signal (on BOTH halves)
PAKKA_N = 60
PAKKA_NEW = 20
HABIT_SHARE = 10.0      # % of all signals a bad fact must cover to count as a habit
MAX_PER_GROUP = 6
MAX_COMBO = 3
_CACHE_S = 90

_lock = threading.RLock()
_out_cache = {}

GROUPS = (
    ("main", "Main chart (EMA + SD band)",
     ("sd_zone", "ema_turn", "move", "regime", "sd_shape", "sd_size", "volume")),
    ("z", "Z-score (neeche wala indicator)",
     ("z_zone", "z_move", "z_div", "zma_vs_trade", "z_why", "z_recent")),
    ("tsi", "TSI (neeche wala indicator)",
     ("tsi_pos", "tsi_vs_sig", "tsi_4zone", "tsi_vs_trade", "warning", "momentum")),
    ("both", "Z aur TSI saath me",
     ("z_tsi",)),
)
_KIND_GROUP = {k: g for g, _, ks in GROUPS for k in ks}
_COMBO_GROUPS = ("main", "z", "tsi", "both")


def _cfg(name, default):
    try:
        return X._cfg(name, default)
    except Exception:
        return default


def _avg(vs):
    return sum(vs) / len(vs) if vs else 0.0


def _pct(k, n):
    return (k / n * 100.0) if n else 0.0


def _tokens(rows):
    """{ 'kind=label': set(row index) } for the kinds that belong to an indicator group."""
    idx = {}
    for i, r in enumerate(rows):
        for k, t in r["lab"].items():
            if k in _KIND_GROUP and isinstance(t, str):
                idx.setdefault((k, t), set()).add(i)
    return idx


def _stats(rows, ids, cut, all_avg, all_old, all_new):
    """Numbers of one fact / combo. ids = row indexes (oldest first rows)."""
    ids = sorted(ids)
    n = len(ids)
    vs = [rows[i]["v"][LIVE] for i in ids]
    old = [rows[i]["v"][LIVE] for i in ids if i < cut]
    new = [rows[i]["v"][LIVE] for i in ids if i >= cut]
    avg = _avg(vs)
    d_old = (_avg(old) - all_old) if old else None
    d_new = (_avg(new) - all_new) if new else None
    sl = sum(1 for i in ids if rows[i]["w"][LIVE] == "SL")
    tp1 = sum(1 for i in ids if rows[i]["w"]["T1"] == "TP")
    return {"n": n, "n_new": len(new), "avg": round(avg, 3), "diff": round(avg - all_avg, 3),
            "avg_old": round(_avg(old), 3) if old else None, "avg_new": round(_avg(new), 3) if new else None,
            "d_old": d_old, "d_new": d_new,
            "win_rate": round(_pct(sum(1 for v in vs if v > 0), n), 1),
            "sl": round(_pct(sl, n), 1), "tp1": round(_pct(tp1, n), 1)}


def _verdict(st):
    """GOOD / AVOID need the same direction on the OLDER and the NEWER part, with enough signals."""
    if st["n"] < MIN_N:
        return "FEW", None
    do, dn = st["d_old"], st["d_new"]
    if do is None or dn is None or st["n_new"] < MIN_NEW:
        return "UNSURE", None
    sure = st["n"] >= PAKKA_N and st["n_new"] >= PAKKA_NEW
    if do >= GAP and dn >= GAP:
        return "GOOD", ("PAKKA" if sure else "SHAYAD")
    if do <= -GAP and dn <= -GAP:
        return "AVOID", ("PAKKA" if sure else "SHAYAD")
    if abs(st["diff"]) >= GAP and (do * dn) < 0:
        return "UNSURE", None           # old and new half disagree: could be luck
    return "NORMAL", None


def _exit_plan(label, rows, ids):
    try:
        sc = X._scenario(label, [rows[i] for i in sorted(ids)])
        return {"best": sc["best"], "nice": X.NICE[sc["best"]], "verdict": sc["verdict"], "msg": sc["msg"],
                "live_avg": sc["avg"][LIVE], "best_avg": sc["avg"][sc["best"]]}
    except Exception:
        return None


def _public(st):
    return {k: v for k, v in st.items() if k not in ("d_old", "d_new")}


def build(tf=""):
    """The whole indicator-reading page for one timeframe. Never raises."""
    try:
        tf = tf if tf in L.SIGNAL_TFS else str(_cfg("timeframe", "3m"))
        if tf not in L.SIGNAL_TFS:
            tf = "3m"
        lev = float(_cfg("leverage", 1) or 1)
        fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
        key = (RC.version(), tf, lev, fee)
        with _lock:
            hit = _out_cache.get(tf)
            if hit and hit[0] == key and time.time() - hit[1] < _CACHE_S:
                return hit[2]
        rows = X.lab_rows(tf, lev, fee)
        n = len(rows)
        out = {"tf": tf, "signals": n, "status": "TOO_FEW" if n < MIN_ALL else "OK", "headline": "",
               "overall": {}, "indicators": [], "habits": [], "best": [], "avoid": [], "levels": {},
               "scalp_note": "Scalp karna hai ya hold - AI har condition ke saath 'exit' line me batata hai "
                             "(TP1 pe poora band = scalp). Bot ka exit koi nahi badla.",
               "caveats": ["Replay on real candles, live trading nahi: slippage nahi, order hamesha fill.",
                           "ROI = price move x leverage minus fee. Har trade ka margin barabar.",
                           "Bahut saari cheezein ek saath check hoti hain, isliye kuch result sirf luck se bhi aa sakte hain. "
                           "Isi liye GOOD/AVOID tabhi likha jata hai jab purane aur naye dono hisse me same nikle.",
                           "Ye sirf dekhna hai: koi rule live trading me nahi lagaya gaya."]}
        if n < 25:
            out["headline"] = f"Abhi sirf {n} signal. Reading ke liye kam se kam {MIN_ALL}+ chahiye."
            _store(tf, key, out)
            return out
        cut = int(n * 0.6)
        all_vs = [r["v"][LIVE] for r in rows]
        all_avg = _avg(all_vs)
        all_old, all_new = _avg(all_vs[:cut]), _avg(all_vs[cut:])
        out["overall"] = {"avg": round(all_avg, 3), "win_rate": round(_pct(sum(1 for v in all_vs if v > 0), n), 1),
                          "sl": round(_pct(sum(1 for r in rows if r["w"][LIVE] == "SL"), n), 1)}
        idx = _tokens(rows)
        facts = {}      # (kind, label) -> (stats, verdict, tier)
        for tok, ids in idx.items():
            if len(ids) < MIN_N // 2:
                continue
            st = _stats(rows, ids, cut, all_avg, all_old, all_new)
            v, tier = _verdict(st)
            facts[tok] = (st, v, tier)

        # 1) per indicator
        good = bad = 0
        for gk, title, kinds in GROUPS:
            items = []
            for (k, t), (st, v, tier) in facts.items():
                if k in kinds and v != "FEW":
                    items.append((abs(st["diff"]), k, t, st, v, tier))
            items.sort(key=lambda x: -x[0])
            lst = []
            for _, k, t, st, v, tier in items[:MAX_PER_GROUP]:
                row = {"kind": k, "label": t, "verdict": v, "tier": tier, "share": round(_pct(st["n"], n), 1)}
                row.update(_public(st))
                if v in ("GOOD", "AVOID"):
                    row["exit"] = _exit_plan(t, rows, idx[(k, t)])
                lst.append(row)
            for (k, t), (st, v, tier) in facts.items():
                if k in kinds:
                    good += v == "GOOD"
                    bad += v == "AVOID"
            out["indicators"].append({"key": gk, "title": title, "facts": lst})

        # 2) habits: bad AND common
        habits = []
        for (k, t), (st, v, tier) in facts.items():
            share = _pct(st["n"], n)
            if v == "AVOID" and share >= HABIT_SHARE:
                rest = (sum(all_vs) - st["avg"] * st["n"]) / max(1, n - st["n"])
                habits.append({"kind": k, "label": t, "tier": tier, "n": st["n"], "share": round(share, 1),
                               "avg": st["avg"], "rest_avg": round(rest, 3), "win_rate": st["win_rate"],
                               "msg": f"Signal ke time '{t}' tha - {st['n']} signal ({share:.0f}%) me, avg {st['avg']:+.1f}% "
                                      f"vs baaki {rest:+.1f}%. Yahan entry lena nuksaan wala dikha - skip ya wait behtar."})
        habits.sort(key=lambda h: h["avg"] - h["rest_avg"])
        out["habits"] = habits[:4]

        # 3) combos: one fact from each of two different indicator groups
        keys = [t for t, (st, v, tier) in facts.items() if st["n"] >= MIN_N // 2]
        goods, avoids = [], []
        for a in range(len(keys)):
            ga = _KIND_GROUP[keys[a][0]]
            for b in range(a + 1, len(keys)):
                if _KIND_GROUP[keys[b][0]] == ga or keys[a][0] == keys[b][0]:
                    continue
                ids = idx[keys[a]] & idx[keys[b]]
                if len(ids) < MIN_N:
                    continue
                st = _stats(rows, ids, cut, all_avg, all_old, all_new)
                v, tier = _verdict(st)
                if v not in ("GOOD", "AVOID"):
                    continue
                label = f"{keys[a][1]} + {keys[b][1]}"
                item = {"label": label, "verdict": v, "tier": tier, "share": round(_pct(st["n"], n), 1),
                        "exit": _exit_plan(label, rows, ids)}
                item.update(_public(st))
                strength = min(abs(st["d_old"]), abs(st["d_new"]))
                (goods if v == "GOOD" else avoids).append((strength, item))
        goods.sort(key=lambda x: -x[0])
        avoids.sort(key=lambda x: -x[0])
        out["best"] = _spread([i for _, i in goods])
        out["avoid"] = _spread([i for _, i in avoids])

        # 4) levels: SD zone -> what Z / TSI usually said there, and the result
        zones = {}
        for (k, t), ids in idx.items():
            if k == "sd_zone" and len(ids) >= MIN_N // 2:
                zones[t] = ids
        cols = sorted({t for (k, t) in idx if k == "z_tsi"})
        lv_rows = []
        for zt, ids in sorted(zones.items(), key=lambda kv: -len(kv[1])):
            cells = {}
            for ct in cols:
                both = ids & idx.get(("z_tsi", ct), set())
                if len(both) >= 8:
                    vs = [rows[i]["v"][LIVE] for i in both]
                    cells[ct] = {"n": len(both), "avg": round(_avg(vs), 2),
                                 "win_rate": round(_pct(sum(1 for v in vs if v > 0), len(both)), 1)}
            vs = [rows[i]["v"][LIVE] for i in ids]
            lv_rows.append({"zone": zt, "n": len(ids), "avg": round(_avg(vs), 2),
                            "win_rate": round(_pct(sum(1 for v in vs if v > 0), len(ids)), 1),
                            "z_usual": _dominant(idx, ids, "z_zone"), "tsi_usual": _dominant(idx, ids, "tsi_pos"),
                            "cells": cells})
        out["levels"] = {"cols": cols, "rows": lv_rows[:8]}

        if n < MIN_ALL:
            out["headline"] = f"Abhi {n} signal hain - reading shuruaati hai, {MIN_ALL}+ ke baad maano."
        elif good or bad:
            out["headline"] = (f"{good} cheez bot ke liye achhi aur {bad} nuksaan wali nikli (purane aur naye dono data me). "
                               f"{len(out['habits'])} aadat check karne layak.")
        else:
            out["headline"] = "Abhi koi indicator-reading dono hisso me pakka achhi ya buri nahi nikli."
        _store(tf, key, out)
        return out
    except Exception as e:
        return {"tf": tf, "signals": 0, "status": "ERROR", "headline": "", "indicators": [], "habits": [],
                "best": [], "avoid": [], "levels": {}, "overall": {}, "error": f"{type(e).__name__}: {e}"}


def _store(tf, key, out):
    with _lock:
        _out_cache[tf] = (key, time.time(), out)


def _dominant(idx, ids, kind):
    best, cnt = None, 0
    for (k, t), s in idx.items():
        if k == kind:
            c = len(ids & s)
            if c > cnt:
                best, cnt = t, c
    return {"label": best, "share": round(cnt / len(ids) * 100.0, 0)} if best and ids else None


def _spread(items):
    """Top combos, but do not show three near-identical ones (same two facts + one more): skip a combo
    whose signals are mostly the same as one already shown, judged by label overlap."""
    out = []
    for it in items:
        parts = set(it["label"].split(" + "))
        if any(len(parts & set(o["label"].split(" + "))) >= 2 and len(parts) <= len(o["label"].split(" + ")) for o in out):
            continue
        out.append(it)
        if len(out) >= MAX_COMBO:
            break
    return out
