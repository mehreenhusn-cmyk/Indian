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
Run by hand: cd backend && python3 brain_pattern.py      (not connected; storage and the view key are Part 2)
"""
import json

import brain_look as BL
import brain_stats as BS

PATTERN_VERSION = "m1"


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
