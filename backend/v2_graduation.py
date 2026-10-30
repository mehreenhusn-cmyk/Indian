"""v2_graduation.py - Part 69: GRADUATION GATE (read-only report). "Has the PAPER bot earned a tiny live test?" - a pass / fail list, never a switch.

Two arms are judged, each on its own, ROI points NET of fee (what the archives store), finished paper trades only:
  current_bot  every finished Dual Bot trade (dual_archive.db, status closed)
  brain_own    the Brain's own finished pretend trades (brain_archive.db, table own)
The what-if arm of Part 66 (brain_protect) is NEVER evidence here: it is hypothetical.
7 checks per arm (state pass / fail / wait; wait = still collecting, never a pass):
  trades 200+ | span 28+ days | active days 14+ | net positive (total and average per trade above 0) | recovery (total / max drawdown at least 1.5)
  luck test SUPPORTED (Part 66 test: 100+ trades, both halves agree, small luck chance) | last 14 days not negative (at least 10 trades)
Verdict: any fail = NOT READY; no fail but a wait = NOT ENOUGH DATA; all pass = GATE PASSED (paper).
GATE PASSED does NOT switch anything and is NOT a promise of future profit: a tiny live test still needs the owner's separate OK and a daily loss cap.
The limits below are the gate's own starting values (NV, not validated); the owner may change them. Unit is ROI points, not USDT (USDT = ROI x invest).
Reads only (mode=ro). No network, no trading module, no write except the ONE report file.
Run (Termux):  python3 backend/v2_graduation.py [--data DIR] [--out FILE]   -> Download/owl_graduation.json
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_stats as BS
import v2_brain_ab as A

VERSION = "v2_graduation 1 (Part 69)"
DAY_MS = 86400000
LIMITS = {"min_trades": 200, "min_span_days": 28, "min_active_days": 14, "recovery_factor": 1.5, "recent_days": 14, "recent_min_trades": 10}
LABELS = {"trades": "Finished trades", "span": "Days from first to last trade", "active": "Days with trades", "net": "Net result above zero",
          "recovery": "Profit covers the worst drawdown", "luck": "Luck test", "recent": "Last 14 days not negative"}


def _chk(key, state, value, need):
    return {"key": key, "label": LABELS[key], "state": state, "value": value, "need": need}


def evaluate(rows, now=None, limits=None):
    """PURE. rows = [(t_ms, net)] -> the 7 checks + verdict of ONE arm. Same rows -> same answer. now = seconds (tests)."""
    lim = dict(LIMITS, **(limits or {}))
    now = time.time() if now is None else float(now)
    rows = sorted((int(t), float(x)) for t, x in rows)
    n = len(rows)
    st = A.arm_stats(rows)
    thin = n < BS.MIN_N                                           # under 30 trades nothing can be called good or bad
    span = round((rows[-1][0] - rows[0][0]) / DAY_MS, 1) if n else 0.0
    cks = [_chk("trades", "pass" if n >= lim["min_trades"] else "wait", n, ">= %d" % lim["min_trades"]),
           _chk("span", "pass" if span >= lim["min_span_days"] else "wait", span, ">= %d" % lim["min_span_days"]),
           _chk("active", "pass" if st["days"] >= lim["min_active_days"] else "wait", st["days"], ">= %d" % lim["min_active_days"])]
    if thin:
        cks.append(_chk("net", "wait", st["total"], "total and average above 0"))
        cks.append(_chk("recovery", "wait", None, ">= %s" % lim["recovery_factor"]))
    else:
        cks.append(_chk("net", "pass" if st["total"] > 0 and (st["expectancy"] or 0) > 0 else "fail", st["total"], "total and average above 0"))
        dd, tot = st["max_drawdown"], st["total"]
        rf = None if dd <= 0 else round(tot / dd, 2)
        ok = tot > 0 and (dd <= 0 or tot / dd >= lim["recovery_factor"])
        cks.append(_chk("recovery", "pass" if ok else "fail", rf if rf is not None else ("no drawdown" if tot > 0 else None), ">= %s" % lim["recovery_factor"]))
    pv = A.paired(rows)
    cks.append(_chk("luck", "pass" if pv["verdict"] == "SUPPORTED" and (pv["mean_diff"] or 0) > 0 else "wait", pv["verdict"], "SUPPORTED"))
    cut = (now - lim["recent_days"] * 86400) * 1000.0
    rec = [x for t, x in rows if t >= cut]
    if len(rec) < lim["recent_min_trades"]:
        cks.append(_chk("recent", "wait", {"trades": len(rec)}, "%d+ trades, total not below 0" % lim["recent_min_trades"]))
    else:
        cks.append(_chk("recent", "pass" if sum(rec) >= 0 else "fail", {"trades": len(rec), "total": round(sum(rec), 2)}, "total not below 0"))
    states = [c["state"] for c in cks]
    verdict = "NOT READY" if "fail" in states else ("NOT ENOUGH DATA" if "wait" in states else "GATE PASSED (paper)")
    return {"verdict": verdict, "passed": states.count("pass"), "failed": states.count("fail"), "waiting": states.count("wait"),
            "checks": cks, "numbers": st}


def build_report(base=None, now=None, limits=None):
    dual, own, _prot, notes = A.load(base)
    arms = {"current_bot": evaluate(list(dual.values()), now, limits), "brain_own": evaluate(own, now, limits)}
    return {"version": VERSION, "generated_ts": int(time.time() if now is None else now), "unit": "ROI points net of fee", "paper_only": True,
            "limits": dict(LIMITS, **(limits or {})), "arms": arms,
            "notes": notes + ["the two arms are judged separately and never added together",
                              "brain_protect (Part 66) is hypothetical and is not used here",
                              "GATE PASSED changes nothing and promises nothing; a tiny live test needs the owner's separate OK and a daily loss cap",
                              "the limits are starting values, not validated"]}


def main(argv=None):
    import v2_inv_redact as R
    import v2_inventory as I
    ap = argparse.ArgumentParser(description="Owl Graduation gate (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    out = a.out or os.path.join(os.path.dirname(I.default_out()), "owl_graduation.json")
    rep = build_report(I.find_data_dir(a.data))
    try:
        R.write_report(rep, out)
    except R.RedactionFailed as e:
        print("REFUSED: secret-looking fields, NO file written:", ", ".join(map(str, e.paths[:20])))
        return 2
    print("Graduation gate written:", out)
    for k, v in rep["arms"].items():
        print("  %-12s %-22s pass %d | fail %d | wait %d | trades %d" % (k, v["verdict"], v["passed"], v["failed"], v["waiting"], v["numbers"]["trades"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
