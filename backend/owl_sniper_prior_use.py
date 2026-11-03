"""owl_sniper_prior_use.py - OwlSniper PRIOR KNOWLEDGE -> CANDIDATES -> RE-TEST (Part 37 / FILE 45). READ ONLY, PAPER ONLY: it only reads (the list of FILE 44 + the saved candles through the SD band study of FILE 16), it writes nothing, opens nothing, no network, no order code.
The owner's rule (MASTER 4.8): old backtests and studies are PRIOR knowledge, never blind trust. A useful finding becomes a CANDIDATE; Sniper then re-tests it ITSELF on fresh candles with its own rule (the same outcome + verdict rule as every other Sniper study: entry = open of the next candle, +2R / -1R, 30 candles, stop first, independent cases only, at least 30 independent cases and both halves must agree). Only a candidate that Sniper itself CONFIRMS may be used (use_in_sniper). Even then the Risk Box, the LEARN / REAL gates and the 85% real floor decide every trade: this file opens no door.
STEP 1 - which findings become candidates (the first rule that fits; everything else is listed in `skipped` with its reason, nothing is dropped silently):
  - not entry_known (exit rules, managing an open trade, Brain states) -> NOT a candidate: it is an exit / management note (kept in `notes` for the exit and opportunity files). entry_known None (the source does not say) -> NOT a candidate.
  - verdict NOT_ENOUGH_DATA / NO_EDGE / LOSING / DIAGNOSIS_ONLY -> nothing to test (NO_EDGE is kept as negative knowledge, counted in `no_edge`).
  - verdict EDGE or HINT (or AVOID) AND Sniper has a test that matches the SAME event -> candidate. Today that is ONE family: the SD level study 'Price at -kSD / +kSD' (k = 1, 2, 3) = Sniper's SD band touch events (owl_sniper_sdbands.py). HINT / EDGE (the level held) -> LOWERk_HELD (lower band, natural LONG) or UPPERk_HELD (upper band, natural SHORT). AVOID (the level broke) -> LOWERk_BROKE / UPPERk_BROKE (the break is the trade; the HELD kind is the 'do not take' side and is shown too).
  - anything else (Z-SMA cross events, situations with an extra condition like '-2SD + expanding', 'enter only when confirmed') -> NO matching Sniper test yet: listed as skipped, honestly, not forced into a wrong test.
STEP 2 - the RE-TEST: the SD band study is run on the newest FRESH_DAYS (30) of saved candles (fresh_days=0 = all saved candles). Status per candidate, from Sniper's own verdict of the natural decision:
  CONFIRMED (STEADY: enough independent cases, both halves, most coins) -> use_in_sniper True / PARTIAL (SOMETIMES: not proven, never used) / REFUTED (NO_PAY: Sniper's own data says the old finding does not hold now) / WAITING (NOT_ENOUGH_DATA: shows n of 30, rare bands like 3 SD often stay here, that is the honest answer) / NO_DATA (no saved candles).
  72 checks are made inside that study: a STEADY by luck is possible, trust it more when it stays STEADY on a later run (FILE 20 watches that).
API: candidates(rows), retest(cands, sd), build(d, tf='5m', fresh_days=30, rows=None, now=None), report(res). CLI:
  python3 backend/owl_sniper_prior_use.py --data DIR [--tf 5m] [--fresh-days 30] [--json]"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "owl_sniper_prior_use 1 (Part 37)"
PAPER_ONLY = True
FRESH_DAYS = 30
MIN_N = 30                                   # independent cases (the same number as every Sniper study)
TESTABLE = ("EDGE", "HINT", "AVOID")
NOTHING = ("NOT_ENOUGH_DATA", "NO_EDGE", "LOSING", "DIAGNOSIS_ONLY")


def _level(what):
    """'Price at -2SD' -> ('LOWER', 2); '+3SD' -> ('UPPER', 3); anything else (also '-2SD + expanding') -> None."""
    t = str(what or "").replace("Price at ", "", 1).strip()
    if len(t) == 4 and t[0] in "+-" and t[1] in "123" and t[2:] == "SD":
        return ("LOWER" if t[0] == "-" else "UPPER"), int(t[1])
    return None


def _skip(r, why):
    return {"id": r.get("id"), "what": r.get("what"), "verdict": r.get("verdict"), "reason": why}


def candidates(rows):
    """Prior rows (FILE 44) -> {cands, skipped, notes, no_edge}. PURE."""
    cands, skipped, notes, no_edge = [], [], [], 0
    for r in rows or ():
        if not isinstance(r, dict):
            continue
        v = r.get("verdict")
        if r.get("entry_known") is False:
            if v in ("EDGE", "HINT", "AVOID"):
                notes.append({"id": r.get("id"), "what": r.get("what"), "verdict": v, "line": r.get("line")})
            skipped.append(_skip(r, "about the exit or about managing an open trade, not an entry (kept as a note)"))
            continue
        if r.get("entry_known") is None:
            skipped.append(_skip(r, "the source does not say if it is known at entry"))
            continue
        if v in NOTHING:
            no_edge += 1 if v == "NO_EDGE" else 0
            skipped.append(_skip(r, "verdict %s: nothing to test" % v))
            continue
        lv = _level(r.get("what")) if r.get("source") == "level" else None
        if v not in TESTABLE or lv is None:
            skipped.append(_skip(r, "no matching Sniper test yet (Sniper tests SD band touches only)"))
            continue
        side, k = lv
        held = v != "AVOID"
        kind = "%s%d_%s" % (side, k, "HELD" if held else "BROKE")
        cands.append({"id": r.get("id"), "what": r.get("what"), "prior_verdict": v, "prior_n": r.get("n"), "prior_line": r.get("line"), "study": "sdbands", "kind": kind,
                      "avoid_kind": None if held else "%s%d_HELD" % (side, k)})
    return {"cands": cands, "skipped": skipped, "notes": notes, "no_edge": no_edge}


def _state(sd, kind):
    try:
        return ((sd or {}).get("kinds") or {})[kind]["states"][0]
    except (KeyError, IndexError, TypeError):
        return None


def retest(cands, sd):
    """Candidates + the result of owl_sniper_sdbands.build() -> candidates with Sniper's own status. PURE."""
    import owl_sniper_sdbands as SD
    out = []
    ready = bool(sd and sd.get("ready"))
    for c in cands or ():
        d = dict(c, status="NO_DATA", n_independent=0, exp_r=None, lift=None, win_pct=None, natural=SD.natural(c["kind"]), use_in_sniper=False, paper_only=True)
        st = _state(sd, c["kind"]) if ready else None
        if st is None:
            d["plain"] = "%s: no saved candles to re-test on yet." % c["what"]
            out.append(d)
            continue
        r = st["long" if d["natural"] == "LONG" else "short"]
        d.update(n_independent=int(r.get("n_independent", 0)), exp_r=r.get("exp_r"), lift=r.get("lift"), win_pct=r.get("win_pct"))
        d["status"] = {"STEADY": "CONFIRMED", "SOMETIMES": "PARTIAL", "NO_PAY": "REFUTED"}.get(r.get("verdict"), "WAITING")
        d["use_in_sniper"] = d["status"] == "CONFIRMED"
        if d["status"] == "WAITING":
            d["plain"] = "%s: Sniper has %d of %d independent cases to re-test it. No verdict yet." % (c["what"], d["n_independent"], MIN_N)
        else:
            word = {"CONFIRMED": "CONFIRMED by Sniper's own data", "PARTIAL": "only SOMETIMES on Sniper's data (not proven, not used)", "REFUTED": "does NOT hold on Sniper's data now"}[d["status"]]
            d["plain"] = "%s (old finding %s, n=%s): %s -> %s, %d independent cases, expected %+.2fR (%+.2fR vs any candle)." % (c["what"], c["prior_verdict"], c.get("prior_n"), word, d["natural"], d["n_independent"], r.get("exp_r") or 0.0, r.get("lift") or 0.0)
        if c.get("avoid_kind"):
            ah = _state(sd, c["avoid_kind"])
            if ah:
                a = ah["long" if SD.natural(c["avoid_kind"]) == "LONG" else "short"]
                d["avoid_side_verdict"] = a.get("verdict")
        out.append(d)
    return out


def build(d, tf="5m", fresh_days=FRESH_DAYS, rows=None, now=None):
    """Read the prior list (FILE 44) unless `rows` are given, make the candidates, re-test them on fresh candles. Never raises."""
    now = int(time.time() if now is None else now)
    head = {"version": VERSION, "paper_only": True, "report_only": True, "interval": tf, "fresh_days": fresh_days or "all saved candles"}
    try:
        if rows is None:
            import owl_sniper_prior_src as PS
            pr = PS.collect(d, now)
            rows, head["prior_sources"] = pr["rows"], pr["sources"]
        pre = candidates(rows)
    except Exception as e:
        return dict(head, state="error", text="The prior findings could not be read: %s." % str(e)[:80], lines=[], cands=[])
    try:
        import owl_sniper_sdbands as SD
        sd = SD.build(d, tf, since_days=fresh_days or None, now=now) if pre["cands"] else {"ready": False}
    except Exception as e:
        sd = {"ready": False, "note": "%s: %s" % (type(e).__name__, str(e)[:60])}
    res = retest(pre["cands"], sd)
    cnt = {s: sum(1 for c in res if c["status"] == s) for s in ("CONFIRMED", "PARTIAL", "REFUTED", "WAITING", "NO_DATA")}
    return dict(head, state="OK", cands=res, counts=cnt, skipped=pre["skipped"], notes=pre["notes"], no_edge=pre["no_edge"], retest_note=(sd or {}).get("note"), lines=report_lines(res, pre, cnt))


def report_lines(res, pre, cnt):
    if not res:
        return ["No old finding can be re-tested by Sniper yet (%d findings read, %d skipped with a reason, %d noted as NO_EDGE)." % (len(pre["skipped"]) + len(pre["cands"]), len(pre["skipped"]), pre["no_edge"])]
    return ["%d old findings became candidates: %d CONFIRMED, %d only partly, %d REFUTED, %d waiting for data." % (len(res), cnt["CONFIRMED"], cnt["PARTIAL"], cnt["REFUTED"], cnt["WAITING"] + cnt["NO_DATA"])] + [c["plain"] for c in res]


def report(res):
    return "\n".join(res.get("lines") or [res.get("text") or ""])


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper prior findings -> candidates -> re-test (read only)")
    ap.add_argument("--data", required=True)
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--fresh-days", type=int, default=FRESH_DAYS)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = build(a.data, a.tf, a.fresh_days)
    print(json.dumps(res, indent=1) if a.json else report(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
