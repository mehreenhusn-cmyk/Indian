"""
ai_learning.py - turns the Shadow Lab's raw signal rows into "what has the AI learned about my EMA50
strategy": WHAT WORKS / WHAT FAILS / WHAT IS STILL UNCERTAIN, each with sample counts, validation
counts and an EVIDENCE STATUS (never a fake "AI confidence 87%").

  DISCOVERED  seen on the older 60% of the data, not yet testable on the newer 40%
  VALIDATING  newer data exists but is still too small to decide
  CONFIRMED   held up on the newer 40% (same direction, big enough, not just luck)
  STABLE      CONFIRMED on every re-check for 48h+ (the pattern survived new data coming in)
  WEAKENING   was CONFIRMED / STABLE, newer data no longer backs it up
  REJECTED    looked real on old data, did NOT hold on new data

Four things come out of it:
  1. timeline   - how much the AI has seen / validated, how many patterns per status, last update
  2. patterns   - the Shadow Lab's combination scenarios (SD + Special Master TSI + higher timeframes +
                  Top-10 gainer/loser side) with their lifecycle kept between rebuilds
  3. tp         - TP1 -> TP4 funnel, what happens after TP1, and what the stalls / losses had in common
  4. timeframes - 3m vs 5m vs 15m, and what higher-timeframe agreement did

Safety (same rules as the other AI modules): READ-ONLY and descriptive. Nothing here opens, blocks,
filters or changes a trade, and strategy.py is untouched. All numbers are historical associations,
not trading rules.  Own daemon thread for the heavy part, every public function swallows its errors.
"""
import json
import math
import os
import threading
import time

STATUSES = ("DISCOVERED", "VALIDATING", "CONFIRMED", "STABLE", "WEAKENING", "REJECTED")
SPLIT = 0.6                 # old 60% finds, new 40% re-checks (same as ai_miner / the lab)
MIN_OLD = 20                # signals needed in the old part before an association is even listed
MIN_NEW = 20                # signals needed in the new part before it can be CONFIRMED / REJECTED
Z_FIND = 3.0                # stricter than 2: hundreds of facts are compared, some will look real by luck
Z_HOLD = 2.0
MIN_COINS = 3               # a CONFIRMED pattern must show up on at least this many different coins ...
MIN_DAYS = 3                # ... and on this many different days (one coin in one move is not independent evidence)
STABLE_AFTER_S = 48 * 3600
REBUILD_EVERY_S = 900
LIVE_RULE = "T4"
TF_ORDER = ("3m", "5m", "15m")
_SKIP_KINDS = ("direction",)

_lock = threading.RLock()
_dir = None
_life_file = None
_cache = {"data": None, "ts": 0.0, "rows": -1, "busy": False}
_life = {"loaded": False, "d": {}}


def init(path):
    global _dir, _life_file
    try:
        os.makedirs(path, exist_ok=True)
        _dir = path
        _life_file = os.path.join(path, "ai_lifecycle.json")
    except Exception:
        pass


# ------------------------------------------------------------------ small maths
def _z2(a1, n1, a2, n2):
    """two-proportion z (group 1 vs group 2); None when it cannot be computed."""
    if n1 < 5 or n2 < 5:
        return None
    p1, p2 = a1 / n1, a2 / n2
    p = (a1 + a2) / (n1 + n2)
    se = math.sqrt(max(p * (1 - p) * (1 / n1 + 1 / n2), 1e-12))
    return (p1 - p2) / se


def _pct(a, n):
    return (a / n * 100.0) if n else None


def _label(tok):
    return tok.split("=", 1)[1] if "=" in tok else tok


def _kind(tok):
    return tok.split("=", 1)[0]


# ------------------------------------------------------------------ associations (single facts)
def _assoc(rs, bad_fn, name, top=4):
    """Which single facts go with MORE `bad` outcomes (fails) or FEWER (works)?  rs = chronological
    lab rows.  Old 60% finds, new 40% re-checks.  Returns {"base": %, "fails": [...], "works": [...]}"""
    n = len(rs)
    if n < MIN_OLD + MIN_NEW:
        return {"n": n, "ready": False}
    cut = int(n * SPLIT)
    bad = [1 if bad_fn(r) else 0 for r in rs]
    tot_old, tot_new = sum(bad[:cut]), sum(bad[cut:])
    n_old, n_new = cut, n - cut
    stats = {}
    for i, r in enumerate(rs):
        for tok in r["tok"]:
            if _kind(tok) in _SKIP_KINDS:
                continue
            a = stats.setdefault(tok, [0, 0, 0, 0, set(), set()])   # n_old, bad_old, n_new, bad_new, coins, days
            a[4].add(r.get("s"))
            a[5].add(int(r["t"] // 86_400_000))
            if i < cut:
                a[0] += 1
                a[1] += bad[i]
            else:
                a[2] += 1
                a[3] += bad[i]
    items = []
    for tok, (no, bo, nn, bn, coins, days) in stats.items():
        if no < MIN_OLD or n_old - no < MIN_OLD:
            continue
        z = _z2(bo, no, tot_old - bo, n_old - no)
        if z is None or abs(z) < 2.5:
            continue
        rate_old = _pct(bo, no)
        rest_old = _pct(tot_old - bo, n_old - no)
        sign = 1 if z > 0 else -1                           # +1: more bad than the rest
        eff_old = (rate_old - rest_old) * sign              # always positive (size of the gap)
        status = "DISCOVERED"
        rate_new = rest_new = None
        if nn >= 10 and n_new - nn >= 10:
            rate_new = _pct(bn, nn)
            rest_new = _pct(tot_new - bn, n_new - nn)
            eff_new = (rate_new - rest_new) * sign
            z2 = _z2(bn, nn, tot_new - bn, n_new - nn)
            z2 = (z2 or 0.0) * sign
            if nn < MIN_NEW:
                status = "VALIDATING"
            elif z2 >= Z_HOLD and eff_new >= 0.5 * eff_old:
                ok = abs(z) >= Z_FIND and len(coins) >= MIN_COINS and len(days) >= MIN_DAYS
                status = "CONFIRMED" if ok else "VALIDATING"
            elif eff_new <= 0.25 * eff_old or z2 < 0:
                status = "REJECTED"
            else:
                status = "VALIDATING"
        elif abs(z) < Z_FIND:
            continue
        items.append({"label": _label(tok), "kind": _kind(tok), "n": no + nn,
                      "rate": _pct(bo + bn, no + nn), "n_old": no, "rate_old": rate_old,
                      "n_new": nn, "rate_new": rate_new, "status": status, "coins": len(coins), "days": len(days),
                      "side": "fails" if sign > 0 else "works", "_z": abs(z)})
    items.sort(key=lambda x: -x["_z"])
    out = {"n": n, "ready": True, "what": name, "base": _pct(tot_old + tot_new, n),
           "fails": [], "works": []}
    for it in items:
        side = it.pop("side")
        it.pop("_z", None)
        if it["status"] == "REJECTED" and len(out["fails"]) + len(out["works"]) >= top * 2:
            continue
        if len(out[side]) < top:
            out[side].append(it)
    return out


# ------------------------------------------------------------------ TP funnel
def _funnel(rs):
    n = len(rs)
    if not n:
        return None
    reach = []
    for k in (1, 2, 3, 4):
        key = f"T{k}"
        a = sum(1 for r in rs if (r["o"].get(key) or ["", ""])[1] == "TP")
        reach.append({"tp": k, "n": a, "pct": _pct(a, n)})
    t1 = [r for r in rs if (r["o"].get("T1") or ["", ""])[1] == "TP"]
    post = None
    if len(t1) >= 15:
        cont = sum(1 for r in t1 if (r["o"].get("T2") or ["", ""])[1] == "TP")
        back = sum(1 for r in t1 if (r["o"].get("T2") or ["", ""])[1] == "BE")
        post = {"n": len(t1), "continue_tp2": _pct(cont, len(t1)), "back_to_entry": _pct(back, len(t1)),
                "other": _pct(len(t1) - cont - back, len(t1))}
    stalls = []
    for k in (1, 2, 3):
        reached = [r for r in rs if (r["o"].get(f"T{k}") or ["", ""])[1] == "TP"]
        if len(reached) < MIN_OLD + MIN_NEW:
            continue
        a = _assoc(reached, lambda r, k=k: (r["o"].get(f"T{k + 1}") or ["", ""])[1] != "TP",
                   f"TP{k}->TP{k + 1} stall", top=3)
        if a.get("ready"):
            stalls.append({"from": k, "to": k + 1, "n": len(reached),
                           "stall_pct": a["base"], "causes": a["fails"], "helps": a["works"]})
    mm = [r["mm"] for r in rs if r.get("mm") and r["mm"][0] is not None]
    mfe = None
    if len(mm) >= 30:
        srt = sorted(x[0] for x in mm)
        sra = sorted(x[1] for x in mm)
        mfe = {"n": len(mm), "mfe_median": srt[len(srt) // 2], "mae_median": sra[len(sra) // 2],
               "mae_p80": sra[int(len(sra) * 0.8)]}
    return {"n": n, "reach": reach, "after_tp1": post, "stalls": stalls, "excursion": mfe}


# ------------------------------------------------------------------ higher-timeframe agreement / market side
def _group_table(rs, kind, lev, fee, win_fn):
    rows = {}
    for r in rs:
        for tok in r["tok"]:
            if _kind(tok) != kind:
                continue
            g = rows.setdefault(_label(tok), [])
            g.append(r)
    out = []
    for lab, g in rows.items():
        if len(g) < 15:
            continue
        w = sum(1 for r in g if win_fn(r))
        net = [(r["o"][LIVE_RULE][0] * lev - fee) for r in g if LIVE_RULE in r["o"]]
        out.append({"label": lab, "n": len(g), "win_pct": _pct(w, len(g)),
                    "avg_roi": (sum(net) / len(net)) if net else None})
    out.sort(key=lambda x: x["label"])
    return out


# ------------------------------------------------------------------ lifecycle (kept between rebuilds)
def _life_load():
    if _life["loaded"]:
        return
    _life["loaded"] = True
    try:
        if _life_file and os.path.exists(_life_file):
            with open(_life_file, "r") as f:
                d = json.load(f)
            if isinstance(d, dict):
                _life["d"] = d
    except Exception:
        _life["d"] = {}


def _life_save():
    try:
        if not _life_file:
            return
        tmp = _life_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_life["d"], f, separators=(",", ":"))
        os.replace(tmp, _life_file)
    except Exception:
        pass


def _advance(pid, verdict, now):
    """Move one pattern along its life. verdict: CONFIRMED / UNTESTED / FAILED / None (not found now)."""
    d = _life["d"]
    rec = d.get(pid)
    first_time = rec is None
    if rec is None:
        rec = d[pid] = {"first": now, "status": None, "conf_since": None, "last_conf": None, "hist": []}
    prev = rec["status"]
    if verdict == "CONFIRMED":
        if rec.get("conf_since") is None:
            rec["conf_since"] = now
        rec["last_conf"] = now
        st = "STABLE" if now - rec["conf_since"] >= STABLE_AFTER_S else "CONFIRMED"
    elif verdict == "FAILED":
        rec["conf_since"] = None
        st = "REJECTED"
    elif verdict == "UNTESTED":
        rec["conf_since"] = None
        st = "WEAKENING" if prev in ("CONFIRMED", "STABLE") else ("DISCOVERED" if first_time else "VALIDATING")
    else:                                                    # not found in this evaluation
        rec["conf_since"] = None
        if prev in ("CONFIRMED", "STABLE"):
            st = "WEAKENING"
        elif prev == "WEAKENING" and now - (rec.get("last_seen") or now) > 5 * 86400:
            st = "REJECTED"
        else:
            st = prev or "DISCOVERED"
    if verdict is not None:
        rec["last_seen"] = now
    if st != prev:
        rec["hist"] = (rec.get("hist") or [])[-11:] + [[int(now), st]]
    rec["status"] = st
    return rec


def _prune_life(now):
    d = _life["d"]
    for pid in list(d):
        rec = d[pid]
        age = now - (rec.get("last_seen") or rec.get("first") or now)
        if (rec.get("status") in ("DISCOVERED", "VALIDATING") and age > 3 * 86400) or \
                (rec.get("status") == "REJECTED" and age > 7 * 86400):
            d.pop(pid, None)


def _patterns(lab, now, recs=None):
    _life_load()
    seen = set()
    items = []
    lab_sets = {}
    for r in (recs or []):
        lab_sets.setdefault(r["tf"], []).append((r["s"], r["t"], frozenset(_label(t) for t in r["tok"])))

    def coverage(tf, label):
        parts = [x.strip() for x in str(label).split("  +  ")]
        hit = [(sy, t) for sy, t, ls in lab_sets.get(tf, ()) if all(x in ls for x in parts)]
        return len({h[0] for h in hit}), len({int(h[1] // 86_400_000) for h in hit})

    for tf, e in (lab.get("tfs") or {}).items():
        for bucket, kind_default in (("take", None), ("avoid", None), ("validating", None), ("rejected", None)):
            for it in (e.get(bucket) or []):
                pid = f"{tf}|{it.get('kind')}|{it.get('label')}"
                if pid in seen:
                    continue
                seen.add(pid)
                verdict = it.get("verdict")
                coins = days = None
                if verdict == "CONFIRMED" and lab_sets:
                    coins, days = coverage(tf, it.get("label"))
                    if coins < MIN_COINS or days < MIN_DAYS:
                        verdict = "UNTESTED"          # too thin to call it confirmed (one coin / one move)
                rec = _advance(pid, verdict, now)
                items.append({"id": pid, "tf": tf, "kind": it.get("kind"), "label": it.get("label"),
                              "coins": coins, "days": days, "net_positive": (it.get("avg") or 0) > 0,
                              "status": rec["status"], "first": rec.get("first"), "last_conf": rec.get("last_conf"),
                              "n": it.get("n"), "win_rate": it.get("win_rate"), "avg": it.get("avg"),
                              "n_old": it.get("n_old"), "avg_old": it.get("avg_old"),
                              "n_new": it.get("n_new"), "avg_new": it.get("avg_new")})
    for pid in list(_life["d"]):
        if pid not in seen:
            rec = _advance(pid, None, now)
            tf, kind, label = (pid.split("|", 2) + ["", ""])[:3]
            items.append({"id": pid, "tf": tf, "kind": kind, "label": label, "status": rec["status"],
                          "first": rec.get("first"), "last_conf": rec.get("last_conf"), "gone": True})
    _prune_life(now)
    _life_save()
    return items


# ------------------------------------------------------------------ build
def _compute():
    from . import ai_shadow_lab as L
    now = time.time()
    lab = L.build_lab()
    recs = L._compact_rows()
    lev = float(lab.get("leverage") or 1)
    fee = float(lab.get("fee_roi_pct") or 0)
    live = L.LIVE_RULE
    win_fn = lambda r: (r["o"].get(live) or [0])[0] * lev - fee > 0
    sl_fn = lambda r: (r["o"].get(live) or ["", ""])[1] == "SL"

    pats = _patterns(lab, now, recs)
    by_status = {s: 0 for s in STATUSES}
    for p in pats:
        by_status[p["status"]] = by_status.get(p["status"], 0) + 1

    tfs = {}
    for tf in TF_ORDER:
        rs = [r for r in recs if r["tf"] == tf and r["o"].get(live)]
        if not rs:
            continue
        rs.sort(key=lambda r: r["t"])
        cut = int(len(rs) * SPLIT)
        e = {"n": len(rs), "n_old": cut, "n_new": len(rs) - cut,
             "win_pct": _pct(sum(1 for r in rs if win_fn(r)), len(rs)),
             "funnel": _funnel(rs),
             "loss": _assoc(rs, sl_fn, "stop-loss hit"),
             "mtf": _group_table(rs, "mtf_agree", lev, fee, win_fn),
             "market": _group_table([r for r in rs if r.get("mk")], "market", lev, fee, win_fn)}
        lr = (lab.get("tfs", {}).get(tf, {}).get("rules", {}) or {}).get(live) or {}
        e["avg_roi"] = lr.get("avg")
        e["breakeven_wr"] = lr.get("breakeven_wr")
        tfs[tf] = e

    ts_all = [r["t"] for r in recs]
    live_rows = sum(1 for r in recs if r.get("mk"))
    validated = sum(((lab.get("tfs", {}).get(tf, {}) or {}).get("n_new") or 0) for tf in TF_ORDER)

    def pick(statuses, side=None):
        out = []
        for p in pats:
            if p["status"] not in statuses or p.get("gone"):
                continue
            out.append(p)
        return out

    works = [p for p in pick(("CONFIRMED", "STABLE")) if p.get("kind") == "TAKE"]
    fails = [p for p in pick(("CONFIRMED", "STABLE")) if p.get("kind") == "AVOID"]
    unsure = pick(("DISCOVERED", "VALIDATING", "WEAKENING"))
    rejected = [p for p in pats if p["status"] == "REJECTED"]

    caveats = ["Replay = real candles but no slippage; signals in the same market move are not independent.",
               "Replay coins = today's watchlist + coins from your closed trades (survivorship bias): "
               "only signals recorded LIVE carry the true Top-10 gainer/loser side.",
               "Everything here is a historical association, not a trading rule. The AI never opens, "
               "blocks or changes a trade."]
    if live_rows < 100:
        caveats.append("Top-10 gainer/loser effect: only %d live signals recorded so far (rank + side are "
                       "saved at signal time from now on)." % live_rows)
    return {
        "built": now,
        "timeline": {"signals": len(recs), "validated": validated, "live_signals": live_rows,
                     "first_signal_ms": min(ts_all) if ts_all else None,
                     "last_signal_ms": max(ts_all) if ts_all else None,
                     "patterns": by_status, "lab_phase": (lab.get("status") or {}).get("phase")},
        "answers": {"works": works[:8], "fails": fails[:8], "unsure": unsure[:8], "rejected": rejected[:8]},
        "patterns": pats,
        "tfs": tfs, "leverage": lev, "fee_roi_pct": fee, "caveats": caveats,
    }


def _rebuild():
    if _cache["busy"]:
        return
    _cache["busy"] = True
    try:
        data = _compute()
        n = (data.get("timeline") or {}).get("signals", 0)
        _cache.update(data=data, ts=time.time(), rows=n)
    except Exception as e:
        _cache["ts"] = time.time() - REBUILD_EVERY_S + 120
        _cache["err"] = f"{type(e).__name__}: {e}"
    finally:
        _cache["busy"] = False


def build(force=False):
    """Cached; the heavy rebuild runs on its own thread (never blocks a request, never raises)."""
    try:
        stale = time.time() - _cache["ts"] > REBUILD_EVERY_S
        if (force or stale or _cache["data"] is None) and not _cache["busy"]:
            threading.Thread(target=_rebuild, name="ai-learning", daemon=True).start()
        d = dict(_cache["data"] or {"timeline": {"signals": 0, "patterns": {}}, "tfs": {}, "answers": {},
                                    "patterns": [], "caveats": []})
        d["busy"] = _cache["busy"]
        d["error"] = _cache.get("err")
        return d
    except Exception:
        return {"timeline": {"signals": 0, "patterns": {}}, "tfs": {}, "answers": {}, "patterns": []}


def build_text():
    """Short plain text for the chat AI. '' while there is nothing to say."""
    try:
        d = _cache["data"]
        if not d or not (d.get("timeline") or {}).get("signals"):
            return ""
        t = d["timeline"]
        L = ["AI LEARNING STATUS (Shadow Lab evidence; historical associations only, never trading rules): "
             f"{t['signals']} signals seen, patterns by status {t['patterns']}."]
        for key, title in (("works", "WORKS"), ("fails", "FAILS"), ("unsure", "STILL UNCERTAIN")):
            for p in (d["answers"].get(key) or [])[:3]:
                L.append(f"- {title} [{p['status']}] {p['tf']}: {p['label']} -> {p.get('n')} signals, "
                         f"avg {p.get('avg', 0):+.2f}% ROI (newer data: {p.get('n_new')} signals)")
        return "\n".join(L)
    except Exception:
        return ""
