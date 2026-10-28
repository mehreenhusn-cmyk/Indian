"""brain_pattern.py - Batch 4c-2 PART 1: MISTAKE RISK from look-alikes (measurement only, nothing stored yet, nothing shown yet, nothing decided).

Question: "when a Brain call looks like earlier calls of the same state, did THOSE calls turn out to be mistakes more often than usual, and
did that tell us anything about whether THIS call was a mistake?"   Mistake = the same outcome facts as the B4b ledger (brain_stats.KINDS):
STRONG or STABLE but the trade lost; WEAKENING or REVERSED but the trade ended in profit and holding beat leaving.
It never opens, closes, changes or rejects a trade, calls no API, reads no price feed, writes nothing.

No new machinery: brain_look.analyze() does everything (same 8 numbers, past-only scaling, pool of earlier FINISHED trades only, one trade = one
piece of evidence, same slices, market-move-safe luck test, same verdict rule, MIN 30 calls). The only difference is WHAT is measured: brain_look
is told (flag=) to measure 100 x "was this call a mistake" instead of what holding added. So, for every call:
  usual   = the past-only mistake rate of finished trades at the same stage (same candle count + ROI band, same outcome rule) = the baseline
  excess  = 100 if mistake else 0, minus that usual rate  (percentage points)
  pred    = the look-alikes' average excess (pulled toward 0 when few): + = "look-alikes erred more than usual" (risky), - = reliable
  score   = sign(pred) x this call's own excess, averaged: positive = the look-alikes pointed the right way, by this many percentage points per call.
Positive evidence = calls the look-alikes called reliable really erred less than usual; negative evidence = calls they called risky really erred more.
Nothing is a rule and nothing is advice: a verdict only says whether the look-alike guess about mistakes was better than luck.

PART 2 (storage + gaps + view key, still observation only):
  look_call  one FROZEN row per scored call and channel ('roi' = B4c-1 measure, 'mistake' = this file), table look_call of brain_archive.db,
             INSERT OR IGNORE on (id, state, channel, version): a repeated run adds nothing, a row is never changed. A guess only ever used
             EARLIER finished trades, so it never needs to be rewritten. raw obs / journey / call_out / mistake / learn_stats are never written.
  gaps       per state: how far (in standard deviations of ALL finished first calls of that state) the mean of each of the 8 numbers was apart
             between mistake calls and correct calls. DESCRIPTION ONLY, not evidence and not a rule. Shown only for states whose mistake-risk
             verdict is a hint, only the 3 biggest gaps, only with MIN_HALF mistakes AND MIN_HALF correct calls that have the number.
  summary    the small block of the Brain view key learn.look (refresh at most every REFRESH_S, only when journeys changed, never raises).
Run by hand: cd backend && python3 brain_pattern.py
"""
import json
import time

import brain_look as BL
import brain_stats as BS
import trade_archive as TA

PATTERN_VERSION = "m1"
TOP_GAPS = 3
MAX_ROWS = 40                          # most slice results shown in the view
_C = {"t": 0.0, "key": None, "res": None, "err": "", "base": None}


def flag(c, state):
    """100 if this call would be a mistake under `state`'s ledger rule, else 0. Evaluated for EVERY call, so the baseline is the usual rate of
    the same outcome (the same rule as the B4b ledger), not a mix of different rules."""
    return 100.0 if BS.KINDS[state][2](c) else 0.0


def _text(r, label):
    if r["verdict"] == "NOT ENOUGH DATA":
        return "%s: %d of %d judged calls had enough look-alikes. NOT ENOUGH DATA (need %d)." % (label, r["n"], r["judged"], BS.MIN_N)
    base = "%s (%d calls): look-alikes called %d risky (they erred %+.0f points vs usual) and %d reliable (%+.0f points vs usual)." % (
        label, r["n"], r["risky_n"], r["risky_ex"] or 0, r["safe_n"], r["safe_ex"] or 0)
    if r["verdict"] == "NO CLEAR PATTERN":
        return base + (" Too bunched in time to test luck." if r["p"] is None else " No clear pattern: it could be luck, or older and newer calls disagree.")
    return base + " %s. Not advice." % r["verdict"].capitalize()


def analyze(calls):
    """PURE. brain_look's analysis of the mistake outcome. -> the brain_look result plus channel 'mistake', pattern_version and, in every result,
    risky_n / risky_ex (calls the look-alikes called risky: how many, mean excess mistake points) and safe_n / safe_ex."""
    res = BL.analyze(calls, flag=flag)
    for g in res["slices"]:
        for s, r in g["states"].items():
            r["risky_n"], r["risky_ex"], r["safe_n"], r["safe_ex"] = r.pop("hold_n"), r.pop("hold_ex"), r.pop("exit_n"), r.pop("exit_ex")
            r["kind"], r["label"] = BS.KINDS[s][0], BS.KINDS[s][1]
            r["text"] = ("" if g["slice"] == "all" else g["slice"] + " - ") + _text(r, r["label"] + ", look-alikes")
    res.update(channel="mistake", pattern_version=PATTERN_VERSION)
    return res


def gaps(calls, state, cutoff=None):
    """PURE. Mistake calls vs correct calls of `state` (first call of each finished trade, same rule as flag): per number the gap
    (mean over mistakes - mean over correct) / standard deviation of all those calls. cutoff = only trades whose exit candle closed by then
    (tests use it to show later trades cannot change an older picture). -> top TOP_GAPS by size [{feat, gap, mistakes, correct}]. Description only."""
    obs = [c for c in BS._first_per(calls, lambda c: c["st"]) if c["st"] == state and c.get("x") is not None and (cutoff is None or c["xc"] <= cutoff)]
    out = []
    for i, f in enumerate(BL.FEATS):
        bad = [c["x"][i] for c in obs if c["x"][i] is not None and flag(c, state) > 0]
        ok = [c["x"][i] for c in obs if c["x"][i] is not None and flag(c, state) == 0]
        al = bad + ok
        if len(bad) < BS.MIN_HALF or len(ok) < BS.MIN_HALF:
            continue
        m = sum(al) / len(al)
        sd = (sum((a - m) ** 2 for a in al) / len(al)) ** 0.5
        if sd > 1e-9:
            out.append({"feat": f, "gap": BS._r((BS._mean(bad) - BS._mean(ok)) / sd, 2), "mistakes": len(bad), "correct": len(ok)})
    return sorted(out, key=lambda r: -abs(r["gap"]))[:TOP_GAPS]


def rows_of(roi_res, mis_res, now):
    """PURE. The scored calls of both channels as look_call tuples (TA.LCOLS order)."""
    ch = ((roi_res, "roi", BL.LOOK_VERSION), (mis_res, "mistake", BL.LOOK_VERSION + "." + PATTERN_VERSION))
    return [(t["id"], t["st"], c, v, t["t"], BS._r(t["pred"], 4), t["m"], BS._r(t["actual"], 3), now) for res, c, v in ch for t in res["targets"]]


def refresh(base=None, force=False):
    """Recompute both channels when the journeys changed (at most every BS.REFRESH_S), freeze new look_call rows (insert-only). Reads only the two
    archives read-only, writes only look_call. Never raises. -> {roi, mistake, gaps, ...} or None (see _C["err"])."""
    now = time.time()
    try:
        same = _C["res"] is not None and _C["base"] == base
        if not force and same and now - _C["t"] < BS.REFRESH_S:
            return _C["res"]
        c = TA.learn_counts(BS.LEARN_VERSION, base)
        key = (c["journeys"], c["outcomes"])
        if not force and same and key == _C["key"]:
            _C["t"] = now
            return _C["res"]
        calls, info = BL.load(base)
        roi, mis = BL.analyze(calls), analyze(calls)
        rows = rows_of(roi, mis, now)
        if rows:
            TA.save_look_calls(rows, base)
        hint = {s: gaps(calls, s) for s, r in mis["slices"][0]["states"].items() if r["verdict"] in BL.HINTS}
        res = {"roi": roi, "mistake": mis, "gaps": hint, "left_out": info["left_out"], "no_feats": info["no_feats"], "rows": len(rows)}
        _C.update(t=now, key=key, res=res, err="", base=base)
        return res
    except Exception as ex:
        _C.update(t=now, err="%s: %s" % (type(ex).__name__, str(ex)[:100]), base=base, res=None)
        return None


def summary(base=None):
    """The small block of the Brain view (key learn.look). Never raises. status 'collecting' until some result has MIN_N calls, then 'measuring'."""
    res = refresh(base)
    if res is None:
        return {"status": "error", "err": _C["err"], "text": "Look-alike learning could not be measured. NOT ENOUGH DATA.", "provisional": True}
    show = ("state", "name", "n", "score", "hit", "halves", "p_adj", "verdict", "text")
    mshow = show + ("kind", "risky_n", "risky_ex", "safe_n", "safe_ex")

    def pack(r, keys, sl):
        return dict({k: r.get(k) for k in keys}, slice=sl)
    out = {"look_version": BL.LOOK_VERSION, "pattern_version": PATTERN_VERSION, "trades": res["roi"]["trades"], "min_n": BS.MIN_N, "provisional": True,
           "err": _C["err"], "gaps": res["gaps"], "gaps_note": "Description only, not a rule. Shown only where the mistake guess is a hint."}
    for name, keys in (("roi", show), ("mistake", mshow)):
        sl = res[name]["slices"]
        out[name] = {"overall": [pack(r, keys, "all") for r in sl[0]["states"].values()],
                     "slices": [pack(r, keys, g["slice"]) for g in sl[1:] for r in g["states"].values() if r["n"] >= BS.MIN_N][:MAX_ROWS]}
    seen = any(r["n"] >= BS.MIN_N for k in ("roi", "mistake") for r in res[k]["slices"][0]["states"].values())
    out["status"] = "measuring" if seen else "collecting"
    out["text"] = ("Look-alike learning: measuring. Observation only, nothing here controls a trade." if seen
                   else "Look-alike learning: NOT ENOUGH DATA yet (a result needs %d scored calls)." % BS.MIN_N)
    return out


def run(base=None):
    """Hand run / tests: load + analyze, no writes. Never raises. -> analysis dict (with `err` when something went wrong)."""
    try:
        calls, info = BL.load(base)
        out = analyze(calls)
        out.update(left_out=info["left_out"], no_feats=info["no_feats"], err="")
        out["states"] = out["slices"][0]["states"]
        return out
    except Exception as ex:
        return {"channel": "mistake", "pattern_version": PATTERN_VERSION, "states": {}, "slices": [], "targets": [], "coverage": {}, "trades": 0,
                "provisional": True, "err": "%s: %s" % (type(ex).__name__, str(ex)[:100])}


if __name__ == "__main__":
    o = run()
    print(json.dumps({k: v for k, v in o.items() if k not in ("states", "slices", "targets", "config")}, indent=1))
    for s in BS.STATES:
        if s in o.get("states", {}):
            print(o["states"][s]["text"])
    for g in o.get("slices", [])[1:]:
        for r in g["states"].values():
            if r["n"] >= BS.MIN_N:
                print(r["text"])
