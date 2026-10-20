"""
ai_playbook.py - ONE plain-language playbook per scenario:
  "kab profit deta hai / kab nuksaan" + "isme hold karo ya profit book karo" + "kaise improve karo".

How it is built (plain counting, no prediction, nothing is invented):
  1. Scenarios come from ai_miner: the labelled facts of every closed trade (time block,
     session, SD zone, EMA, volume, choppy/clean, SL distance ...) and their COMBOS of 2-3.
  2. PAKKA  = found on the OLDER 60% of trades AND still true on the NEWER 40% (miner CONFIRMED).
     ISHAARA = looks real on the older part but the newer part is too small / not confirmed yet,
               or it passed only a lower bar - it can be luck. Shown clearly as a hint.
  3. For each scenario the exit plan is replayed from each trade's own TP hits:
     "agar TP1 / TP2 / TP3 / TP4 par poora band karte to avg ROI kya hota" vs what really happened.
     Best plan is picked on the OLD part and re-checked on the NEW part (HELD = still better).
     ANDAZA: it uses which TP levels the trade touched, not the full price path, so it is an
     estimate (the path-replay study in Insights is the exact one for newer trades).
It only READS closed trades and only ADVISES - it never changes, blocks or closes a trade.
Fee-related labels are left out; every ROI is the real (net) result.
Hand-off for later wiring: build_playbook()["rules"] = machine-readable list (key, kind, tier,
best_target) that an ML/bot step can read - NOT wired into trading anywhere.
"""
import threading
import time

from . import trade_store
from . import ai_miner

MIN_PLAN = 8            # trades with TP info a scenario needs before an exit plan is shown
LOW_T = 1.6             # lower bar for the ISHAARA tier (the miner's own bar is noise-calibrated)
SHOW_EACH = 4           # scenarios shown per side (profit / loss)
_CACHE_S = 300
_lock = threading.Lock()
_cache = {"key": None, "ts": 0.0, "data": None}
_LEARN_TAGS = ("clean", "unknown")


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


# ------------------------------------------------------------------ naming
_DAYPART = ((0, "Raat"), (4, "Subah-saweray"), (8, "Subah"), (12, "Dopahar"), (16, "Shaam"), (20, "Raat"))


def _tok_name(tok):
    k, _, v = tok.partition("=")
    if k == "ist_time":                       # "IST 20-24"
        try:
            a = int(v.split()[1].split("-")[0])
        except Exception:
            return v
        part = [n for h, n in _DAYPART if h <= a][-1]
        return f"{part} {a}-{a + 4}h IST"
    if k == "ist_hour":
        return v.replace("IST ", "") + " IST"
    if k == "session":
        return f"{v} session"
    if k == "zone":
        return f"zone {v}"
    if k == "ema":
        return "tez EMA slope" if "steep" in v else "dheela EMA slope"
    if k == "volume":
        return "volume surge" if "surge" in v else "normal volume"
    if k == "regime":
        return "choppy bazaar" if "choppy" in v else ("saaf trend" if "clean" in v else "mixed bazaar")
    if k == "volatility":
        return "tez volatility" if v == "violent" else "shant bazaar"
    if k == "sd_width":
        return "chaudi SD band" if "wide" in v else "patli SD band"
    if k == "sl_dist":
        return "paas ka SL (<1%)" if v == "SL<1%" else v.replace("SL ", "SL ")
    if k == "slope_turn":
        return f"slope {v}"
    return v


def _name(key):
    return " + ".join(_tok_name(t) for t in key.split("|"))


_IMPROVE = {
    "sl_dist": "SL ka distance rule badlo (SL thoda door) ya aise signal skip karo",
    "zone": "Is SD zone mein entry ka rule badlo ya skip karo",
    "ema": "EMA slope ka filter lagao",
    "volume": "Volume ka filter lagao",
    "regime": "Sideways/choppy bazaar mein trade skip karo",
    "volatility": "Volatility ka filter lagao",
    "sd_width": "SD band ki chaudai ka filter lagao",
    "ist_time": "Is time block mein trade skip karke dekho",
    "ist_hour": "Is ghante mein trade skip karke dekho",
    "session": "Is session mein trade skip karke dekho",
    "weekday": "Is din trade skip karke dekho",
    "direction": "Is side ke trade skip karke dekho",
    "timeframe": "Is timeframe ke trade skip karke dekho",
    "slope_turn": "Slope palat'ne par trade ka rule badlo",
}


def _kinds(key):
    return [t.partition("=")[0] for t in key.split("|")]


# ------------------------------------------------------------- exit plans
def _lvl(t, k):
    d = ai_miner._roi_dist(t, f"signal_tp{k}")
    return None if d is None else d - _f(t.get("fee_roi_pct"))


def _target_roi(t, k):
    """Net ROI of this trade if it had been closed fully at TPk (estimate)."""
    hits = t.get("tp_hit_levels") or []
    actual = _f(t.get("roi_pct"))
    if k in hits:
        v = _lvl(t, k)
        return v if v is not None else actual
    return actual


def _avg(v):
    return sum(v) / len(v) if v else None


def _plan(sel, idx, cut):
    use = [t for t in sel if isinstance(t.get("tp_hit_levels"), list) and _lvl(t, 1) is not None]
    if len(use) < MIN_PLAN:
        return None
    old = [t for t in use if idx[id(t)] < cut]
    new = [t for t in use if idx[id(t)] >= cut]
    tp = {}
    for k in (1, 2, 3, 4):
        tp[k] = {"all": _avg([_target_roi(t, k) for t in use]),
                 "old": _avg([_target_roi(t, k) for t in old]),
                 "new": _avg([_target_roi(t, k) for t in new])}
    act = {"all": _avg([_f(t.get("roi_pct")) for t in use]),
           "old": _avg([_f(t.get("roi_pct")) for t in old]),
           "new": _avg([_f(t.get("roi_pct")) for t in new])}
    best, gain_old, gain_new, held = 4, 0.0, None, False
    if len(old) >= 5:
        cand = max((1, 2, 3, 4), key=lambda k: (tp[k]["old"], k))
        g = tp[cand]["old"] - act["old"]
        if g > 0.3 and cand != 4:
            best, gain_old = cand, g
            if len(new) >= 4 and tp[cand]["new"] is not None:
                gain_new = tp[cand]["new"] - act["new"]
                held = gain_new > 0
    hit1 = [t for t in use if 1 in (t.get("tp_hit_levels") or [])]
    conv2 = (sum(1 for t in hit1 if 2 in (t.get("tp_hit_levels") or [])) / len(hit1) * 100.0) if len(hit1) >= 5 else None
    t1m = [_f(t.get("tp1_min")) for t in hit1 if t.get("tp1_min") not in (None, "")]
    return {"n": len(use), "n_old": len(old), "n_new": len(new), "actual": act, "tp": tp,
            "best": best, "gain_old": gain_old, "gain_new": gain_new, "held": held,
            "conv2": conv2, "tp1_min": ai_miner._median(t1m) if len(t1m) >= 5 else None,
            "n_hit1": len(hit1)}


def _plan_text(pl):
    """Plain Hinglish lines (hold / book advice) from a plan dict."""
    if not pl:
        return ["Abhi hold/book ka hisaab nahi: TP wale trades kam hain."]
    out = []
    a = pl["actual"]["all"]
    if pl["best"] == 4:
        out.append(f"TP4 tak hold abhi theek hai: koi nazdeek ka TP behtar nahi nikla (avg {a:+.1f}% ROI).")
    else:
        k = pl["best"]
        base = f"TP{k} par poora band karna: avg ROI {pl['actual']['old']:+.1f}% se {pl['tp'][k]['old']:+.1f}% (purane trades)"
        if pl["gain_new"] is not None:
            base += (f"; naye trades par {pl['actual']['new']:+.1f}% se {pl['tp'][k]['new']:+.1f}%"
                     + (" - HELD (naye par bhi behtar)" if pl["held"] else " - naye par behtar nahi nikla"))
        else:
            base += "; naye trades abhi kam hain, to sirf ishaara"
        out.append(base + ".")
    if pl.get("conv2") is not None:
        out.append(f"TP1 chhune wale {pl['n_hit1']} trades mein se {pl['conv2']:.0f}% TP2 tak gaye"
                   + (f" (TP1 median ~{pl['tp1_min']:.0f} min mein)." if pl.get("tp1_min") is not None else "."))
    return out


# ----------------------------------------------------------------- builder
def _compute():
    rows = [t for t in trade_store.get_all_closed(800) if (t.get("quality_tag") or "unknown") in _LEARN_TAGS]
    rows.sort(key=ai_miner._ts)
    n = len(rows)
    out = {"n": n, "ready": n >= ai_miner.MIN_TOTAL, "min_total": ai_miner.MIN_TOTAL}
    if n < ai_miner.MIN_TOTAL:
        return out
    cut = int(n * ai_miner.SPLIT)
    feats = ai_miner._features(rows)
    toks = [ai_miner._tokens(f) for f in feats]
    roi = [_f(t.get("roi_pct")) for t in rows]
    idx = {id(t): i for i, t in enumerate(rows)}
    keep = lambda key: not any(("fee" in x) for x in key)

    mined = ai_miner.build_miner()
    pakka = {i["key"]: i for i in (mined.get("confirmed") or []) if "fee" not in i["key"]}
    res = ai_miner._prune(ai_miner._mine(toks, roi, cut, t_min=LOW_T))
    cand = []
    for key, r in res.items():
        if not keep(key):
            continue
        k = "|".join(key)
        if r["verdict"] == "FAILED":
            continue
        # TAKE/AVOID from the miner only means "better/worse than the other trades". A playbook
        # entry must also be true in money: LO only if it really made money, CHHODO only if it lost.
        sel = [t for t, f in zip(rows, feats) if all(f.get(a) == b for a, b in (x.split("=", 1) for x in key))]
        if not sel:
            continue
        wins = sum(1 for t in sel if _f(t.get("pnl_usdt")) > 0)
        spnl = sum(_f(t.get("pnl_usdt")) for t in sel)
        if (r["sign"] > 0 and spnl <= 0) or (r["sign"] < 0 and spnl >= 0):
            continue
        cand.append({"key": k, "kind": "TAKE" if r["sign"] > 0 else "AVOID",
                     "tier": "PAKKA" if k in pakka else "ISHAARA",
                     "verdict": r["verdict"], "n": len(sel), "wins": wins,
                     "win_rate": wins / len(sel) * 100.0, "pnl": sum(_f(t.get("pnl_usdt")) for t in sel),
                     "avg_old": r["avg_tr"], "avg_new": r["avg_te"],
                     "n_old": r["n_tr"], "n_new": r["n_te"], "_sel": sel, "_edge": r["edge"]})
    rank = lambda x: (x["tier"] != "PAKKA", -(abs(x["_edge"]) * (x["n"] ** 0.5)))
    items = []
    for side in ("TAKE", "AVOID"):
        items += sorted([c for c in cand if c["kind"] == side], key=rank)[:SHOW_EACH]

    scen = []
    for c in items:
        pl = _plan(c.pop("_sel"), idx, cut)
        c.pop("_edge", None)
        kinds = _kinds(c["key"])
        c["name"] = _name(c["key"])
        c["plan"] = pl
        c["plan_text"] = _plan_text(pl)
        if c["kind"] == "TAKE":
            c["action"] = "LO"
            c["improve"] = "Ye scenario profit deta hai: aise signal lo. Hold/book neeche ke hisaab se."
        else:
            c["action"] = "CHHODO"
            c["improve"] = _IMPROVE.get(next((k for k in kinds if k in _IMPROVE), ""), "Is scenario ko skip karke dekho")
            if c["plan_text"]:
                c["plan_text"] = ["Agar phir bhi lete ho to: " + c["plan_text"][0]] + c["plan_text"][1:]
        c["avg_old"] = None if c["avg_old"] is None else round(c["avg_old"], 2)
        c["avg_new"] = None if c["avg_new"] is None else round(c["avg_new"], 2)
        c["pnl"] = round(c["pnl"], 2)
        c["win_rate"] = round(c["win_rate"])
        scen.append(c)

    overall = _plan(rows, idx, cut)
    out.update({"scenarios": scen, "n_pakka": sum(1 for s in scen if s["tier"] == "PAKKA"),
                "overall_plan": overall, "overall_text": _plan_text(overall),
                "rules": [{"key": s["key"], "kind": s["kind"], "tier": s["tier"],
                           "best_target": (s["plan"] or {}).get("best")} for s in scen],
                "note": "Hindsight hai, guarantee nahi. ISHAARA = luck ho sakta hai. Hold/book ka hisaab andaza hai "
                        "(TP touch par based). Bot ab bhi har signal leta hai."})
    return out


def build_playbook(force=False):
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


def playbook_lines(pb):
    """Same playbook as plain text for the chat AI prompt (numbers come ONLY from code)."""
    if not pb or not pb.get("ready"):
        return []
    L = ["PLAYBOOK (code se: scenario -> kab profit/nuksaan -> hold ya profit book). PAKKA = purane trades par mila "
         "AUR naye par bhi chala; ISHAARA = abhi pakka nahi, luck ho sakta hai. Har scenario ke baare mein user ko "
         "simple Hindi mein batao: LO ya CHHODO, hold ya book, aur kaise improve karna hai. Sirf ye numbers use karo:"]
    for s in pb.get("scenarios") or []:
        L.append(f"  [{s['tier']}] {s['action']}: {s['name']} - {s['n']} trades, {s['wins']} jeete ({s['win_rate']}%), "
                 f"P&L {s['pnl']:+.2f} USDT | improve: {s['improve']}")
        for ln in s.get("plan_text") or []:
            L.append(f"      hold/book: {ln}")
    for ln in pb.get("overall_text") or []:
        L.append(f"  SABHI TRADES hold/book: {ln}")
    L.append("  NOTE: hindsight + andaza; bot abhi kuch skip/close nahi karta; ISHAARA ko rule mat banao.")
    return L
