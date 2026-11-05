"""owl_sniper_eva.py - OwlSniper EXPECTED vs ACTUAL (Part 13 / FILE 24). REPORT ONLY: it never pauses, switches or changes anything. No network, no order code.
The question: "Before the trade the Risk Box said X. After the trade closed, what really happened?" If the real results stay below what was expected, the edge may be fading.
How it works (plain words):
  1. At ENTRY the Risk Box answer (owl_sniper_riskbox) is FROZEN into the small file v2_sniper_eva.json (record_expected): expected R, low end, win %, usual time, deepest dip (90th percentile). First write wins: an expectation is never changed after the trade is known.
     Only a Risk Box with state OK is saved. NOT_ENOUGH_DATA / NO_SIGNAL = no expectation = no comparison (never a made-up number).
  2. After the CLOSE the actual result is measured from the saved candles by the SAME rule as the learn bridge (owl_sniper_bridge_label: R after fees, time to result, worst move, best move). label_actuals() does that for bridge-shaped records.
  3. compare_one() = one trade: actual R minus expected R, inside the expected low end or not, time ratio (actual / usual), dip deeper than expected or not.
  4. cohort() = the newest LAST compared trades of ONE lane. Below MIN_N (30) compared trades: NOT_ENOUGH_DATA and NO number. From 30: mean expected R, mean actual R, the gap with its 2-standard-error range, win % expected vs actual,
     median time ratio, share of trades with a deeper dip than the 90% line (about 10% is normal). Verdict: BELOW_EXPECTED (the whole gap range is under 0 = warning), ON_TRACK (the range holds 0), ABOVE_EXPECTED (the whole range is over 0).
  Lanes (REAL / LEARN / ...) are judged apart, never added together.
Report only: a warning is shown, nothing is paused automatically (owner approval needed for any automatic reaction; not built).
WIRED in Part 17a: owl_sniper_eva_hook.freeze_async() is called where a Sniper paper trade opens (owl_sniper_paper.py); api/sniper_eva.py turns the closed Sniper paper trades into actuals (R = paper P&L / 1R in USDT) and serves report() as GET /api/v2/sniper_eva. The dip (MAE) is not measured for paper trades, so that line stays empty.
API: record_expected(d, uid, box, lane="REAL", now=None), load_expected(d), actual_from_label(label), label_actuals(d, records, now=None), compare_one(exp, act), cohort(rows), report(d, actuals, now=None). CLI:
  python3 backend/owl_sniper_eva.py --data DIR [--actuals FILE.json]   (FILE = list of actuals {uid, r_net, secs, mae_r, mfe_r, result}; without it only the waiting expectations are counted)"""
import argparse
import json
import math
import os
import sys
import tempfile
import time

VERSION = "owl_sniper_eva 1 (Part 13)"
FILE = "v2_sniper_eva.json"
MIN_N = 30             # compared trades before any verdict
LAST = 100             # the newest compared trades of a lane that count
KEEP = 500             # expectations kept in the file (newest)
Z = 2.0                # standard errors for the gap range


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if n == 0 else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0)


def _dur(sec):
    """Owner rule: more than 60 minutes = hours + minutes, never '220 min'."""
    if sec is None:
        return "-"
    if sec < 90:
        return "%d s" % round(sec)
    m = round(sec / 60.0)
    return "%d min" % m if m <= 60 else ("%d h" % (m // 60) if m % 60 == 0 else "%d h %d min" % (m // 60, m % 60))


def _path(d):
    return os.path.join(os.path.realpath(d), FILE)


def load_expected(d):
    """-> {uid: expectation}. A missing or damaged file gives {} (nothing is guessed)."""
    try:
        with open(_path(d), "r", encoding="utf-8") as f:
            x = json.load(f)
        e = x.get("expected") if isinstance(x, dict) else None
        return e if isinstance(e, dict) else {}
    except (OSError, ValueError):
        return {}


def expectation(box, uid, lane="REAL", now=None):
    """Risk Box answer -> frozen expectation, or None unless the box is OK with real numbers."""
    if not isinstance(box, dict) or box.get("state") != "OK" or not uid:
        return None
    keys = ("exp_r", "exp_r_low", "win_pct", "median_secs", "p75_secs", "mae_p90_r")
    vals = {k: _num(box.get(k)) for k in keys}
    if vals["exp_r"] is None or vals["exp_r_low"] is None or vals["win_pct"] is None:
        return None
    now = time.time() if now is None else now
    return dict(vals, uid=str(uid), lane=str(lane), symbol=box.get("symbol"), tf=box.get("tf"), side=box.get("side"), regime=box.get("regime"), n=_num(box.get("n")), ts=now)


def record_expected(d, uid, box, lane="REAL", now=None):
    """Freeze the expectation of ONE trade (first write wins). -> True if saved. Writes only its own file, by temp file + replace; never raises."""
    e = expectation(box, uid, lane, now)
    if e is None:
        return False
    try:
        cur = load_expected(d)
        if e["uid"] in cur:
            return False
        cur[e["uid"]] = e
        if len(cur) > KEEP:
            for k, _v in sorted(cur.items(), key=lambda kv: kv[1].get("ts") or 0)[:len(cur) - KEEP]:
                cur.pop(k, None)
        fd, tmp = tempfile.mkstemp(dir=os.path.realpath(d), prefix=FILE + ".")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": VERSION, "expected": cur}, f)
        os.replace(tmp, _path(d))
        return True
    except OSError:
        return False


def actual_from_label(lab):
    """A bridge label (owl_sniper_bridge_label) -> the actual result of one trade."""
    return {"uid": lab.get("uid"), "r_net": _num(lab.get("r_net")), "secs": _num(lab.get("secs_to_result")), "mae_r": _num(lab.get("mae_r")), "mfe_r": _num(lab.get("mfe_r")), "result": lab.get("result"), "entry_ts": _num(lab.get("entry_ts"))}


def label_actuals(d, records, now=None):
    """Bridge-shaped closed trades (source "sniper") -> actuals, measured from the saved candles by the learn-bridge rule. -> (actuals, skipped {reason: n}). Never raises."""
    try:
        import owl_sniper_bridge_label as BLB
        res = BLB.label_all(d, records, now=now)
        return [actual_from_label(x) for x in res["labels"]], res["skipped"]
    except Exception:
        return [], {"label_error": len(records or [])}


def compare_one(exp, act):
    """ONE trade: expectation + actual -> a compared row, or None when the actual has no R."""
    r = _num((act or {}).get("r_net"))
    if r is None or not exp:
        return None
    sec, med, mae, p90 = _num(act.get("secs")), _num(exp.get("median_secs")), _num(act.get("mae_r")), _num(exp.get("mae_p90_r"))
    return {"uid": exp["uid"], "lane": exp.get("lane", "REAL"), "ts": _num(act.get("entry_ts")) or _num(exp.get("ts")) or 0.0,
            "exp_r": exp["exp_r"], "exp_r_low": exp["exp_r_low"], "act_r": r, "gap_r": round(r - exp["exp_r"], 4), "below_low": r < exp["exp_r_low"],
            "exp_win": exp["win_pct"], "win": r > 0, "t_ratio": round(sec / med, 3) if sec and med else None,
            "deeper_dip": (mae > p90) if mae is not None and p90 is not None else None}


def cohort(rows):
    """Compared rows of ONE lane -> summary. Below MIN_N: NOT_ENOUGH_DATA and no number."""
    rows = sorted(rows, key=lambda x: x["ts"])[-LAST:]
    n = len(rows)
    if n < MIN_N:
        t = "NOT ENOUGH DATA: %d of %d compared trades. No verdict, no number." % (n, MIN_N)
        return {"state": "NOT_ENOUGH_DATA", "n": n, "min_n": MIN_N, "text": t, "lines": [t]}
    gaps = [x["gap_r"] for x in rows]
    m = sum(gaps) / n
    se = math.sqrt(sum((g - m) ** 2 for g in gaps) / (n - 1) / n)
    lo, hi = m - Z * se, m + Z * se
    verdict = "BELOW_EXPECTED" if hi < 0 else ("ABOVE_EXPECTED" if lo > 0 else "ON_TRACK")
    dips = [x["deeper_dip"] for x in rows if x["deeper_dip"] is not None]
    out = {"state": verdict, "n": n, "min_n": MIN_N, "exp_r": round(sum(x["exp_r"] for x in rows) / n, 3), "act_r": round(sum(x["act_r"] for x in rows) / n, 3),
           "gap_r": round(m, 3), "gap_low": round(lo, 3), "gap_high": round(hi, 3), "exp_win_pct": round(sum(x["exp_win"] for x in rows) / n, 1),
           "act_win_pct": round(100.0 * sum(1 for x in rows if x["win"]) / n, 1), "below_low_pct": round(100.0 * sum(1 for x in rows if x["below_low"]) / n, 1),
           "median_t_ratio": None, "deeper_dip_pct": round(100.0 * sum(dips) / len(dips), 1) if dips else None}
    tr = _median([x["t_ratio"] for x in rows if x["t_ratio"] is not None])
    out["median_t_ratio"] = round(tr, 2) if tr is not None else None
    word = {"BELOW_EXPECTED": "WARNING: real results are below what the Risk Box expected. The edge may be fading. Nothing was paused.", "ABOVE_EXPECTED": "Real results are better than expected.", "ON_TRACK": "Real results match what was expected (within the normal range)."}[verdict]
    out["lines"] = [word, "Last %d compared trades: expected %+.2f R, actual %+.2f R, gap %+.2f R (range %+.2f to %+.2f)." % (n, out["exp_r"], out["act_r"], out["gap_r"], lo, hi),
                    "Win %% expected %.0f%%, actual %.0f%%. Time: %s of the usual." % (out["exp_win_pct"], out["act_win_pct"], "%.1fx" % tr if tr is not None else "not measured")]
    if out["deeper_dip_pct"] is not None:
        out["lines"].append("%.0f%% of trades dipped deeper than the 90%% line (about 10%% is normal)." % out["deeper_dip_pct"])
    out["text"] = word
    return out


def report(d, actuals, now=None):
    """Expectations + actuals -> report per lane. Never raises, never writes."""
    exp = load_expected(d)
    by_uid = {a.get("uid"): a for a in actuals or [] if isinstance(a, dict)}
    lanes, matched = {}, 0
    for uid, e in exp.items():
        row = compare_one(e, by_uid.get(uid))
        if row:
            matched += 1
            lanes.setdefault(row["lane"], []).append(row)
    waiting = len(exp) - matched
    res = {lane: cohort(rows) for lane, rows in sorted(lanes.items())}
    text = "No expectation saved yet: the Risk Box has not been frozen at any entry." if not exp else "%d expectations saved, %d compared with a closed result, %d waiting." % (len(exp), matched, waiting)
    return {"version": VERSION, "state": "OK" if res else "NOT_ENOUGH_DATA", "n_expected": len(exp), "n_compared": matched, "n_waiting": waiting, "lanes": res,
            "text": text, "lines": [text] + [x for v in res.values() for x in v["lines"][:1]], "paper_only": True, "report_only": True}


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper expected vs actual (report only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--actuals", default=None)
    a = ap.parse_args(argv)
    acts = []
    if a.actuals:
        with open(a.actuals, "r", encoding="utf-8") as f:
            acts = json.load(f)
    print(json.dumps(report(a.data, acts), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
