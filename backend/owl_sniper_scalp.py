"""owl_sniper_scalp.py - OwlSniper SCALP / SHORT SWING / SWING classifier + FAST SCALP priority (Part 31 / FILE 26). REPORT ONLY: read only, nothing is opened, paused or written, no network, no order code.
The question: "How long do trades like this really take, and would a small quick profit have been better than waiting?" The labels come from the MEASURED time of similar finished trades, never from a guess.
How it works (plain words):
  1. LABEL from the time to the result of similar past trades (median + 75th percentile, from the Risk Box or from the bridge labels). Volatility is already inside those times, because similar trades are matched on regime and on the volatility ratio.
       SCALP       = median <= 45 min AND 75th percentile <= 120 min.
       SHORT_SWING = not a scalp, median <= 4 h.
       SWING       = slower than that.   UNKNOWN = no measured time.
     The limits are starting values, the owner may tune them. Honest limit: every bridge trade is cut at 30 candles (the engine's time limit), so a 5m setup can never show more than 150 min. If the 75th percentile sits at that cap the line says "a quarter ran to the time limit; the real hold time may be longer".
  2. FAST SCALP PRIORITY: for a setup that is PROVEN to pay (the low end of its expected R is above 0) the score is expected R per hour = exp R / median hours. Setups that are not proven get NO score (never a made-up rank). In small-capital mode a SWING is not ranked (a slow swing ties up a small account); SCALP gets the "SCALP MODE" badge.
  3. SCALP CHECK ("Scalp Possible: YES (0.6R in < 45 min)"): on similar finished trades, how many reached +0.6R at their best point within 45 min, and what would the result have been if the trade had been closed at +0.6R (minus the real cost of that trade), against what really happened? Trades that did NOT reach it keep their real result. Paired gain with a 2-standard-error range:
       YES = the scalp rule pays even at the low end of its range; NO = it loses even at the high end; NOT_PROVEN otherwise. Below 30 trades: NOT_ENOUGH_DATA, no number.
     Conservative on purpose: the best point must come within 45 min (a trade that touched +0.6R early but peaked later is NOT counted), a candle that also touched the stop never counts, and the exit is assumed at the +0.6R price (no extra slippage beyond the trade's own cost).
Not here: the win chance (Risk Box, FILE 21), edge decay (FILE 20), sizing (FILE 25), "stay or rotate" with a small profit in hand (FILE 27).
API: classify(median_secs, p75_secs, tf=None), for_box(box, tf=None, small_capital=False), rank(items, small_capital=False), scalp_check(examples), family_report(examples), build(d, limit=0, since_days=None). CLI:
  python3 backend/owl_sniper_scalp.py --data DIR [--limit 2000] [--since-days N]   -> JSON (no secrets)."""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "owl_sniper_scalp 1 (Part 31)"
MIN_N = 30                                    # finished trades before any label or verdict
SCALP_MED_MIN, SCALP_P75_MIN, SHORT_MED_MIN = 45.0, 120.0, 240.0
TARGET_R, TARGET_MIN = 0.6, 45.0              # the scalp rule: take +0.6 R if it comes within 45 min
HOLD = 30                                     # candles; the engine's time limit (same as the labels)
Z = 2.0


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _dur(sec):
    """Owner rule: more than 60 minutes = hours + minutes, never '220 min'."""
    if sec is None:
        return "-"
    if sec < 90:
        return "%d s" % round(sec)
    m = round(sec / 60.0)
    return "%d min" % m if m <= 60 else ("%d h" % (m // 60) if m % 60 == 0 else "%d h %d min" % (m // 60, m % 60))


def _q(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _step(tf):
    try:
        import owl_sniper_tf as TF
        return float(TF.step(tf))
    except Exception:
        return None


def classify(median_secs, p75_secs, tf=None):
    """Measured times -> SCALP / SHORT_SWING / SWING (or UNKNOWN) + one plain line."""
    m, p = _num(median_secs), _num(p75_secs)
    if m is None or p is None or m <= 0:
        return {"label": "UNKNOWN", "capped": False, "line": "SCALP / SWING: unknown (no measured time)."}
    label = "SCALP" if (m / 60.0 <= SCALP_MED_MIN and p / 60.0 <= SCALP_P75_MIN) else ("SHORT_SWING" if m / 60.0 <= SHORT_MED_MIN else "SWING")
    st = _step(tf) if tf else None
    capped = bool(st and p >= HOLD * st * 0.99)
    line = "%s: half of similar trades ended within %s, three quarters within %s." % (label.replace("_", " "), _dur(m), _dur(p))
    if capped:
        line += " A quarter ran to the %d-candle time limit; the real hold time may be longer." % HOLD
    return {"label": label, "median_secs": m, "p75_secs": p, "capped": capped, "line": line}


def for_box(box, tf=None, small_capital=False):
    """A Risk Box answer (state OK only) -> label, badge and the fast-scalp score. Not OK = NOT_ENOUGH_DATA and no label."""
    if not isinstance(box, dict) or box.get("state") != "OK":
        return {"state": "NOT_ENOUGH_DATA", "label": "UNKNOWN", "r_per_hour": None, "badge": None, "small_capital_fit": None, "line": "SCALP / SWING: NOT ENOUGH DATA (the Risk Box has no measured time yet)."}
    c = classify(box.get("median_secs"), box.get("p75_secs"), tf or box.get("tf"))
    er, lo, med = _num(box.get("exp_r")), _num(box.get("exp_r_low")), _num(box.get("median_secs"))
    rph = round(er / (med / 3600.0), 3) if (er is not None and lo is not None and lo > 0 and med and med > 0) else None
    fit = None if not small_capital else c["label"] != "SWING"
    lines = [c["line"], ("Fast scalp score: %+.2f R per hour (expected %+.2f R, median %s)." % (rph, er, _dur(med))) if rph is not None else "Fast scalp score: none (the setup is not proven to pay, so no rank)."]
    if fit is False:
        lines.append("Small-capital mode: a slow swing ties up a small account; faster setups come first.")
    return {"state": "OK", "label": c["label"], "capped": c["capped"], "r_per_hour": rph, "badge": "SCALP MODE" if (small_capital and c["label"] == "SCALP") else None, "small_capital_fit": fit, "line": c["line"], "lines": lines}


def rank(items, small_capital=False):
    """items = [{id, box, tf?}] -> proven setups ordered by expected R per hour (fast scalps first by their own speed). Unproven or unfit ones are listed apart with the reason, never ranked."""
    ranked, skipped = [], []
    for it in items or []:
        r = for_box(it.get("box"), it.get("tf"), small_capital)
        row = {"id": it.get("id"), "label": r["label"], "r_per_hour": r["r_per_hour"], "badge": r["badge"], "line": r["line"]}
        why = "no measured time" if r["state"] != "OK" else ("a slow swing, not for small capital" if r["small_capital_fit"] is False else ("not proven to pay" if r["r_per_hour"] is None else None))
        (skipped.append(dict(row, why=why)) if why else ranked.append(row))
    ranked.sort(key=lambda x: -x["r_per_hour"])
    for i, x in enumerate(ranked, 1):
        x["rank"] = i
    return {"version": VERSION, "ranked": ranked, "skipped": skipped, "small_capital": bool(small_capital), "paper_only": True,
            "text": "%d ranked, %d not ranked (not proven, no time or too slow)." % (len(ranked), len(skipped))}


def scalp_check(examples, target_r=TARGET_R, mins=TARGET_MIN):
    """Similar finished trades (bridge examples with labels) -> would closing at +target_r within `mins` have paid better than the real result?"""
    pairs, skipped = [], 0
    for e in examples or []:
        lab, st = e.get("label") or {}, _step(e.get("tf"))
        net, gross, mfe, k = _num(lab.get("r_net")), _num(lab.get("r_gross")), _num(lab.get("mfe_r")), _num(lab.get("bars_to_mfe"))
        if None in (net, gross, mfe, k) or not st:
            skipped += 1
            continue
        hit = mfe >= target_r and k * st <= mins * 60.0
        pairs.append((hit, (target_r - (gross - net)) if hit else net, net))      # gross - net = this trade's own cost in R
    n = len(pairs)
    if n < MIN_N:
        t = "NOT ENOUGH DATA: %d of %d finished trades with a measured best point. No verdict, no number." % (n, MIN_N)
        return {"state": "NOT_ENOUGH_DATA", "n": n, "min_n": MIN_N, "skipped": skipped, "scalp_possible": "UNKNOWN", "text": t, "lines": [t]}
    sc, pl = [p[1] for p in pairs], [p[2] for p in pairs]
    gaps = [a - b for a, b in zip(sc, pl)]
    se = lambda xs: math.sqrt(sum((x - sum(xs) / n) ** 2 for x in xs) / (n - 1) / n)
    ms, mp, mg = sum(sc) / n, sum(pl) / n, sum(gaps) / n
    s_se, g_se = se(sc), se(gaps)
    possible = "YES" if ms - Z * s_se > 0 else ("NO" if ms + Z * s_se < 0 else "NOT_PROVEN")
    verdict = "SCALP_BETTER" if mg - Z * g_se > 0 else ("HOLD_BETTER" if mg + Z * g_se < 0 else "NO_DIFFERENCE")
    reached = sum(1 for p in pairs if p[0])
    head = "Scalp Possible: %s (%+.1fR within %d min)." % (possible.replace("_", " "), target_r, mins)
    lines = [head, "At least %.0f%% of %d similar trades reached +%.1f R within %d min. Closing there: %+.2f R each (range %+.2f to %+.2f); what really happened: %+.2f R." % (100.0 * reached / n, n, target_r, mins, ms, ms - Z * s_se, ms + Z * s_se, mp),
             {"SCALP_BETTER": "The quick scalp beat waiting (gain %+.2f R, range %+.2f to %+.2f).", "HOLD_BETTER": "Waiting beat the quick scalp (gain %+.2f R, range %+.2f to %+.2f).", "NO_DIFFERENCE": "Scalp or wait: no clear difference (gain %+.2f R, range %+.2f to %+.2f)."}[verdict] % (mg, mg - Z * g_se, mg + Z * g_se)]
    return {"state": verdict, "n": n, "min_n": MIN_N, "skipped": skipped, "scalp_possible": possible, "reach_pct_at_least": round(100.0 * reached / n, 1), "scalp_r": round(ms, 3), "scalp_r_low": round(ms - Z * s_se, 3), "scalp_r_high": round(ms + Z * s_se, 3),
            "plain_r": round(mp, 3), "gain_r": round(mg, 3), "gain_low": round(mg - Z * g_se, 3), "gain_high": round(mg + Z * g_se, 3), "text": head, "lines": lines}


def family_report(examples):
    """Deduped bridge examples -> label + scalp check per interval x side (and with the regime). Lanes are NOT split here: the pool is the one the Risk Box reads."""
    groups = {}
    for e in examples or []:
        lab = e.get("label") or {}
        if not e.get("tf") or e.get("side") not in ("LONG", "SHORT") or _num(lab.get("secs_to_result")) is None:
            continue
        for key in ("%s|%s" % (e["tf"], e["side"]), "%s|%s|%s" % (e["tf"], e["side"], e.get("regime") or "?")):
            groups.setdefault(key, []).append(e)
    fams = {}
    for key, ex in sorted(groups.items()):
        n = len(ex)
        if n < MIN_N:
            fams[key] = {"state": "NOT_ENOUGH_DATA", "n": n, "label": "UNKNOWN", "line": "NOT ENOUGH DATA: %d of %d finished trades." % (n, MIN_N)}
            continue
        secs = [float(x["label"]["secs_to_result"]) for x in ex]
        c = classify(_q(secs, 0.5), _q(secs, 0.75), key.split("|")[0])
        fams[key] = {"state": "OK", "n": n, "label": c["label"], "median_secs": round(c["median_secs"]), "p75_secs": round(c["p75_secs"]), "capped": c["capped"], "line": c["line"], "scalp": scalp_check(ex)}
    judged = [k for k, v in fams.items() if v["state"] == "OK"]
    text = "%d setups with a measured label (30+ trades each), %d without enough data." % (len(judged), len(fams) - len(judged)) if fams else "No finished trade with a time yet: no label (never a made-up number)."
    return {"version": VERSION, "state": "OK" if fams else "NOT_ENOUGH_DATA", "families": fams, "text": text, "lines": [text] + ["%s: %s" % (k, fams[k]["line"]) for k in judged[:4]], "paper_only": True, "report_only": True}


def build(d, limit=0, since_days=None, now=None):
    """Saved files -> bridge examples -> dedupe -> family report. Read only. Never raises."""
    t0 = time.time()
    try:
        import owl_sniper_bridge_learn as BL
        ex, _x = BL.load_examples(d, limit=limit, since_days=since_days, now=now)
        ex, dropped = BL.dedupe(ex)
        rep = family_report(ex)
        rep["dropped_duplicates"] = dropped
    except Exception as e:  # a broken file must never break the caller
        rep = {"version": VERSION, "state": "ERROR", "text": "Could not read the trades: %s" % type(e).__name__, "lines": ["Could not read the trades: %s" % type(e).__name__], "families": {}, "paper_only": True, "report_only": True}
    rep["seconds"] = round(time.time() - t0, 2)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper scalp / swing classifier (report only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or ".")
    ap.add_argument("--limit", type=int, default=0, help="only the newest N records (keeps the phone light)")
    ap.add_argument("--since-days", type=float, default=None)
    a = ap.parse_args(argv)
    print(json.dumps(build(a.data, a.limit, a.since_days), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
