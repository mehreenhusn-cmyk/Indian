"""
ai_rules.py - the AI writes RULES from what it learned and tells you what they would have done.

  SKIP rule  : "ye scenario skip karo"           (from the Playbook's CHHODO scenarios)
  BOOK rule  : "is scenario mein TPk par book"   (from the Playbook's hold/book plan, only when
                the plan was better on the older trades)
For every rule and for ALL rules together (each trade counted once, no double counting):
  "agar ye lagte to P&L X ki jagah Y hota" - split into the OLDER trades and the NEWER trades.
SCOREBOARD: the first time a rule is seen it is stamped (ai_rules_state.json). Trades that close
AFTER that stamp are the real test: did the rule keep working on trades it never saw?

ADVICE ONLY. Nothing here is wired into trading: no rule is applied, nothing is blocked or closed.
Everything is hindsight counting on closed trades (an estimate, not a promise); BOOK effects are
estimates from which TP levels each trade touched. Fee labels are left out of the names.
Rules are machine-readable (build_rules()["rules"]) so a later, approved step can use them.
"""
import json
import os
import threading
import time

from . import trade_store
from . import ai_miner
from . import ai_playbook

MIN_TRACK = 10          # matched NEW trades a rule needs before the scoreboard judges it
_CACHE_S = 300
_lock = threading.Lock()
_cache = {"key": None, "ts": 0.0, "data": None}
_state = {"loaded": False, "d": {}}
_LEARN_TAGS = ("clean", "unknown")


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _state_path():
    arch = getattr(trade_store, "_archive", None)
    return os.path.join(os.path.dirname(arch) or ".", "ai_rules_state.json") if arch else None


def _state_load():
    if _state["loaded"]:
        return
    _state["loaded"] = True
    try:
        p = _state_path()
        if p and os.path.exists(p):
            with open(p, "r") as fh:
                _state["d"] = json.load(fh) or {}
    except Exception:
        _state["d"] = {}


def _state_save():
    try:
        p = _state_path()
        if not p:
            return
        with open(p + ".tmp", "w") as fh:
            json.dump(_state["d"], fh)
        os.replace(p + ".tmp", p)
    except Exception:
        pass


def _since(rid, now):
    """Stamp (once) when the AI first proposed this rule; later trades are its real test."""
    _state_load()
    d = _state["d"]
    if rid not in d:
        d[rid] = {"since": now}
        _state_save()
    return _f(d[rid].get("since"), now)


def _matches(f, key):
    return all(f.get(a) == b for a, b in (x.split("=", 1) for x in key.split("|")))


def _margin(t, med):
    roi, pnl = _f(t.get("roi_pct")), _f(t.get("pnl_usdt"))
    return abs(pnl / roi * 100.0) if abs(roi) >= 0.5 else med


def _book_delta(t, k, med):
    """Estimated USDT change if this trade had been closed fully at TPk (touch-based estimate)."""
    if not isinstance(t.get("tp_hit_levels"), list):
        return 0.0
    diff = ai_playbook._target_roi(t, k) - _f(t.get("roi_pct"))
    return diff * _margin(t, med) / 100.0


def _split(vals, idxs, cut):
    old = sum(v for v, i in zip(vals, idxs) if i < cut)
    new = sum(v for v, i in zip(vals, idxs) if i >= cut)
    return old, new


def _compute():
    rows = [t for t in trade_store.get_all_closed(800) if (t.get("quality_tag") or "unknown") in _LEARN_TAGS]
    rows.sort(key=ai_miner._ts)
    n = len(rows)
    out = {"n": n, "ready": n >= ai_miner.MIN_TOTAL, "min_total": ai_miner.MIN_TOTAL}
    if n < ai_miner.MIN_TOTAL:
        return out
    pb = ai_playbook.build_playbook()
    if not pb.get("ready"):
        return out
    cut = int(n * ai_miner.SPLIT)
    feats = ai_miner._features(rows)
    margins = sorted(_f(abs(_f(t.get("pnl_usdt")) / _f(t.get("roi_pct")) * 100.0))
                     for t in rows if abs(_f(t.get("roi_pct"))) >= 0.5)
    med = margins[len(margins) // 2] if margins else 0.0
    now = time.time()
    base = sum(_f(t.get("pnl_usdt")) for t in rows)

    rules = []
    for s in pb.get("scenarios") or []:
        pl = s.get("plan") or {}
        if s["action"] == "CHHODO":
            rules.append({"type": "SKIP", "key": s["key"], "name": s["name"], "tier": s["tier"], "target": None})
        elif s["action"] == "LO" and pl.get("best") in (1, 2, 3) and pl.get("gain_old", 0) > 0:
            rules.append({"type": "BOOK", "key": s["key"], "name": s["name"], "tier": s["tier"], "target": pl["best"]})

    # ---- each rule on its own
    for r in rules:
        idx = [i for i, f in enumerate(feats) if _matches(f, r["key"])]
        if r["type"] == "SKIP":
            vals = [-_f(rows[i].get("pnl_usdt")) for i in idx]
        else:
            vals = [_book_delta(rows[i], r["target"], med) for i in idx]
        o, nw = _split(vals, idx, cut)
        r.update({"id": f"{r['type']}|{r['key']}", "n": len(idx), "effect": round(sum(vals), 2),
                  "effect_old": round(o, 2), "effect_new": round(nw, 2),
                  "n_old": sum(1 for i in idx if i < cut), "n_new": sum(1 for i in idx if i >= cut)})
        # scoreboard: only trades that closed AFTER the rule was first proposed
        since = _since(r["id"], now)
        tr = [i for i in idx if _f(rows[i].get("closed_at_ts")) > since]
        tv = ([-_f(rows[i].get("pnl_usdt")) for i in tr] if r["type"] == "SKIP"
              else [_book_delta(rows[i], r["target"], med) for i in tr])
        eff = sum(tv)
        if len(tr) < MIN_TRACK:
            verdict = "COLLECTING"
        else:
            verdict = "CHAL RAHA" if eff > 0 else "NAHI CHALA"
        r["score"] = {"since": since, "n": len(tr), "effect": round(eff, 2), "verdict": verdict, "need": MIN_TRACK}
        r["text"] = (f"Skip karo: {r['name']}" if r["type"] == "SKIP"
                     else f"{r['name']}: TP{r['target']} par poora band karo")

    # ---- all rules together, each trade counted ONCE
    def combine(use):
        skip_keys = [r["key"] for r in use if r["type"] == "SKIP"]
        book = [(r["key"], r["target"]) for r in use if r["type"] == "BOOK"]
        sk_idx, bk_idx, sk_v, bk_v = [], [], [], []
        for i, f in enumerate(feats):
            if any(_matches(f, k) for k in skip_keys):
                sk_idx.append(i)
                sk_v.append(-_f(rows[i].get("pnl_usdt")))
                continue
            for k, tgt in book:
                if _matches(f, k):
                    d = _book_delta(rows[i], tgt, med)
                    if d:
                        bk_idx.append(i)
                        bk_v.append(d)
                    break
        so, sn = _split(sk_v, sk_idx, cut)
        bo, bn = _split(bk_v, bk_idx, cut)
        tot = sum(sk_v) + sum(bk_v)
        return {"rules": len(use), "skip_n": len(sk_idx), "book_n": len(bk_idx),
                "skip_effect": round(sum(sk_v), 2), "book_effect": round(sum(bk_v), 2),
                "total": round(tot, 2), "would_be": round(base + tot, 2),
                "total_old": round(so + bo, 2), "total_new": round(sn + bn, 2)}

    pakka = [r for r in rules if r["tier"] == "PAKKA"]
    out.update({"base": round(base, 2), "rules": rules, "all": combine(rules), "pakka": combine(pakka),
                "n_old": cut, "n_new": n - cut,
                "note": "Hindsight hai, guarantee nahi: rule lagte to ye hota. Jeete hue trade bhi skip ho jaate hain. "
                        "ISHAARA rules mein luck ho sakta hai. BOOK ka asar andaza hai. Abhi koi rule bot par lagu nahi, sirf salah."})
    return out


def build_rules(force=False):
    """Cached (5 min or until the closed-trade count changes). Never raises."""
    try:
        try:
            last = trade_store.get_recent_closed(1)
            key = (len(trade_store.get_all_closed(800)), last[0].get("closed_at_ts") if last else None)
        except Exception:
            key = None
        with _lock:
            c = _cache
            if not force and c["data"] is not None and c["key"] == key and time.time() - c["ts"] < _CACHE_S:
                return c["data"]
        data = _compute()
        with _lock:
            _cache.update({"key": key, "ts": time.time(), "data": data})
        return data
    except Exception:
        return {"n": 0, "ready": False, "min_total": ai_miner.MIN_TOTAL}


def rules_lines(rs):
    """Same rules as plain text for the chat AI prompt (numbers come ONLY from code)."""
    if not rs or not rs.get("ready") or not rs.get("rules"):
        return []
    a, p = rs["all"], rs["pakka"]
    L = [f"AI RULES (sirf salah, bot par lagu nahi; hindsight): {a['rules']} rules saath lagte to pichhle {rs['n']} trades mein "
         f"P&L {rs['base']:+.2f} ki jagah {a['would_be']:+.2f} hota ({a['total']:+.2f}: skip {a['skip_effect']:+.2f}, "
         f"TP par book {a['book_effect']:+.2f}); purane trades par {a['total_old']:+.2f}, naye par {a['total_new']:+.2f}. "
         f"Sirf PAKKA rules se: {p['total']:+.2f}."]
    for r in rs["rules"]:
        sc = r["score"]
        L.append(f"  [{r['tier']}] {r['text']}: asar {r['effect']:+.2f} USDT (purane {r['effect_old']:+.2f}, naye {r['effect_new']:+.2f}); "
                 f"scoreboard: {sc['verdict']} ({sc['n']} naye trade, {sc['effect']:+.2f})")
    L.append("  NOTE: har rule ke liye user ko batao kahan leak hai, skip ya TP par book, aur improve kaise; "
             "ISHAARA ko pakka mat bolo; numbers jodo mat jab tak 'saath' wala number na ho.")
    return L
