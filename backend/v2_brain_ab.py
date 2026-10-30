"""v2_brain_ab.py - Part 66: BRAIN A/B PAPER COMPARISON (read-only report). Paper only, nothing here controls a trade.

Question: "Would the Brain have done better than the current bot, net of fee?"  Three arms, ROI points NET of fee (what the archives store):
  A current_bot    every FINISHED Dual Bot trade (dual_archive.db trades, status closed) = the baseline, unchanged.
  B brain_own      the Brain's OWN finished pretend trades (brain_archive.db table own). Real paper results, but a different set of trades.
  C brain_protect  what-if on the SAME trades as A: where the frozen shadow rule r1 (table shadow_rec) first said PROTECT_LOOKS_BETTER, the trade is
                   replaced by the ROI at that call (the number stored with the call, net); every other trade keeps its real result. HYPOTHETICAL.
  Brain-filtered   NOT AVAILABLE: no per-trade skip decision of the Brain is stored (only skipped-vs-taken totals, brain_skip). Said plainly, never guessed.
Per arm: trades, total, expectancy (mean), win rate, max drawdown (running total, oldest first), best / worst UTC day, days up / down and, if asked,
days that reached a daily target / loss. C vs A is judged on the same trades only (paired): NOT ENOUGH DATA under 30, NO CLEAR PATTERN unless both
halves agree and the luck test is small, EARLY HINT, SUPPORTED needs 100. A, B and C are never added together.
Reads only (mode=ro, query_only). No network, no trading module, no write except the ONE report file.
Run (Termux):  python3 backend/v2_brain_ab.py [--data DIR] [--out FILE] [--daily-target 20] [--daily-loss 20]   -> Download/owl_brain_ab.json
"""
import argparse
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_stats as BS
import trade_archive as TA

VERSION = "v2_brain_ab 1 (Part 66)"
DAY_MS = 86400000
RUNS = 2000


def _num(x):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else None
    except (TypeError, ValueError):
        return None


def arm_stats(rows, target=None, loss=None):
    """PURE. rows = [(t_ms, net)] -> numbers of one arm. Empty = zeros and verdict-free (n = 0)."""
    rows = sorted((int(t), float(x)) for t, x in rows)
    n = len(rows)
    out = {"trades": n, "total": 0.0, "expectancy": None, "win_rate_pct": None, "max_drawdown": 0.0,
           "best_day": None, "worst_day": None, "days": 0, "days_up": 0, "days_down": 0}
    if target is not None:
        out["days_at_target"] = 0
    if loss is not None:
        out["days_at_loss"] = 0
    if not n:
        return out
    run = peak = dd = 0.0
    days = {}
    for t, x in rows:
        run += x
        peak = max(peak, run)
        dd = max(dd, peak - run)
        days[t // DAY_MS] = days.get(t // DAY_MS, 0.0) + x
    out.update(total=round(run, 2), expectancy=round(run / n, 3), win_rate_pct=round(100.0 * sum(1 for _, x in rows if x > 0) / n, 1),
               max_drawdown=round(dd, 2), days=len(days), days_up=sum(1 for v in days.values() if v > 0),
               days_down=sum(1 for v in days.values() if v < 0), best_day=round(max(days.values()), 2), worst_day=round(min(days.values()), 2))
    if target is not None:
        out["days_at_target"] = sum(1 for v in days.values() if v >= target)
    if loss is not None:
        out["days_at_loss"] = sum(1 for v in days.values() if v <= -abs(loss))
    return out


def paired(diffs):
    """PURE. diffs = [(t_ms, protect - real)] on the SAME trades. Sign-flip luck test (fixed seed), halves must agree. Never a made-up percentage."""
    d = sorted((int(t), float(x)) for t, x in diffs)
    n = len(d)
    out = {"n": n, "mean_diff": None, "halves": [], "p": None, "verdict": "NOT ENOUGH DATA"}
    if not n:
        return out
    xs = [x for _, x in d]
    mean = sum(xs) / n
    out["mean_diff"] = round(mean, 3)
    if n < BS.MIN_N:
        return out
    h = n // 2
    halves = [sum(xs[:h]) / h, sum(xs[h:]) / (n - h)]
    rnd = random.Random(11)
    hit = sum(1 for _ in range(RUNS) if abs(sum(x if rnd.random() < 0.5 else -x for x in xs) / n) >= abs(mean) - 1e-12)
    p = (hit + 1.0) / (RUNS + 1.0)
    agree = halves[0] * halves[1] > 0 and halves[0] * mean > 0
    if not agree or p > 0.20:
        v = "NO CLEAR PATTERN"
    elif n >= BS.FULL_N and p <= 0.05:
        v = "SUPPORTED"
    else:
        v = "EARLY HINT"
    out.update(halves=[round(x, 3) for x in halves], p=round(p, 3), verdict=v)
    return out


def load(base=None):
    """Read-only. -> (dual closed {id: (t, net)}, brain own [(t, net)], first protect call {id: roi}, notes). Missing file / table = empty + a note."""
    notes, dual, own, prot = [], {}, [], {}
    con = TA.open_dual_ro(base)
    if con is None:
        notes.append("dual_archive.db not found")
    else:
        try:
            for i, t, net in con.execute("SELECT id, t, net FROM trades WHERE status = 'closed' AND net IS NOT NULL"):
                if _num(net) is not None and _num(t) is not None:
                    dual[str(i)] = (int(t), float(net))
        except Exception as ex:
            notes.append("dual trades unreadable: %s" % type(ex).__name__)
        finally:
            con.close()
    con = TA.open_brain_ro(base)
    if con is None:
        notes.append("brain_archive.db not found")
    else:
        try:
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "own" in names:
                own = [(int(t), float(n)) for t, n in con.execute("SELECT t, net FROM own WHERE net IS NOT NULL") if _num(t) is not None and _num(n) is not None]
            else:
                notes.append("table own missing")
            if "shadow_rec" in names:
                for i, roi in con.execute("SELECT id, roi FROM shadow_rec WHERE rec = 'PROTECT_LOOKS_BETTER' ORDER BY t ASC"):
                    if str(i) not in prot and _num(roi) is not None:
                        prot[str(i)] = float(roi)
            else:
                notes.append("table shadow_rec missing")
        except Exception as ex:
            notes.append("brain archive unreadable: %s" % type(ex).__name__)
        finally:
            con.close()
    return dual, own, prot, notes


def build_report(base=None, target=None, loss=None):
    dual, own, prot, notes = load(base)
    a_rows = list(dual.values())
    c_rows, diffs = [], []
    for i, (t, net) in dual.items():
        if i in prot:
            c_rows.append((t, prot[i]))
            diffs.append((t, prot[i] - net))
        else:
            c_rows.append((t, net))
    cmp_c = paired(diffs)
    return {"version": VERSION, "generated_ts": int(time.time()), "unit": "ROI points net of fee", "paper_only": True,
            "arms": {"current_bot": arm_stats(a_rows, target, loss), "brain_own": arm_stats(own, target, loss),
                     "brain_protect_whatif": arm_stats(c_rows, target, loss)},
            "protect_vs_current": dict(cmp_c, protect_calls=len(diffs)),
            "brain_filtered": {"status": "NOT AVAILABLE", "why": "no per-trade Brain skip decision is stored; only skipped-vs-taken totals exist (brain_skip)"},
            "notes": notes + ["brain_own is a different set of trades, not the same trades as current_bot",
                              "brain_protect_whatif is hypothetical: it replaces the result with the stored ROI at the first PROTECT call",
                              "the three arms are never added together; nothing was changed"]}


def main(argv=None):
    import v2_inv_redact as R
    import v2_inventory as I
    ap = argparse.ArgumentParser(description="Owl Brain A/B paper comparison (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--daily-target", type=float)
    ap.add_argument("--daily-loss", type=float)
    a = ap.parse_args(argv)
    out = a.out or os.path.join(os.path.dirname(I.default_out()), "owl_brain_ab.json")
    rep = build_report(I.find_data_dir(a.data), a.daily_target, a.daily_loss)
    try:
        R.write_report(rep, out)
    except R.RedactionFailed as e:
        print("REFUSED: secret-looking fields, NO file written:", ", ".join(map(str, e.paths[:20])))
        return 2
    print("Brain A/B written:", out)
    for k, v in rep["arms"].items():
        print("  %-22s trades %-5d total %+.2f  max drawdown %.2f" % (k, v["trades"], v["total"], v["max_drawdown"]))
    print("  protect vs current:", rep["protect_vs_current"]["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
