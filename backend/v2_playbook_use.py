"""v2_playbook_use.py - Part 13: INDICATOR PLAYBOOK 3 of 3 (read-only). "When did the bot / the TSI + Z-score pay after fees, and when NOT?"
ONE command, ONE file: this module runs the reports of Parts 8, 9, 10, 11, 12 (and the Part 7 check) itself, in this one run, then reads their answers.
The owner never has to run 5 commands or send 5 files again. Nothing is traded, nothing is changed, no data file is written to.

Per paper box (paper_b1, paper_b2; boxes are never added together; real live boxes have no indicator samples and too few trades):
  market.use_leads / market.avoid      hour, session, setup, timeframe, side, coin ... slots (Parts 8-9). USE LEAD = the Part 8 guard said CANDIDATE
                                       (>= 30 trades, net after fee > 0, both halves > 0, > 0 without the best trade). AVOID = >= 30 trades and net <= 0.
  indicators.use_leads / avoid         TSI + Z-score states after entry (Part 11), same guard and same two words.
  indicators.hold_leads / leave_leads  states where holding (or leaving) beat the other one in BOTH halves (Part 12; gross ROI points, not money).
  indicators.exit_at_warning           the Part 12 replay verdict (USDT, no slippage).        leaks   the measured leaks of Part 10 (not added up).
THIS MODULE DOES NOT JUDGE AGAIN. It copies the verdict words of the earlier Parts, so a thin slot (< 30 trades) can never become a lead. Several slots are
compared at once, so a luck note is printed. A USE LEAD is something to test later (Parts 39-46), NEVER a trading rule. Nothing here switches anything on.
FAIL-CLOSED: if one of the earlier reports fails, the box says INCOMPLETE and names it; an empty list is never shown as "nothing found".
Run (Termux):  python3 backend/v2_playbook_use.py [--data DIR] [--out FILE] [--fee-roi 1.0]   -> Download/owl_playbook_use.json (send this ONE file)
Tests: python3 test/test_v2_playbook_use.py"""
import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_check_all as C
import v2_inv_redact as R
import v2_inventory as I
import v2_leakage as L
import v2_money_hour as M
import v2_money_split as S
import v2_playbook as B
import v2_playbook_next as N
import v2_pnl as P

VERSION = "v2_playbook_use 1 (Part 13)"
TOP = 8                                                   # longest list shown per kind
REPORTS = (("part8_hour", M), ("part9_split", S), ("part10_leakage", L), ("part11_playbook", B), ("part12_next", N))
GUARDED = ("CANDIDATE", "MIXED", "NEGATIVE")              # verdicts that passed the 30-trade minimum


def run(fn, *a):
    """One report. Any crash or error answer becomes a marked failure, never an empty result."""
    try:
        r = fn(*a)
    except Exception as e:                                # noqa: BLE001 - one report must not stop the others
        return {"section_failed": True, "error": "%s: %s" % (type(e).__name__, str(e)[:150])}
    if not isinstance(r, dict):
        return {"section_failed": True, "error": "no report"}
    if r.get("error"):
        return {"section_failed": True, "error": str(r["error"])[:150]}
    return r


def row(part, split, slot, f):
    return {"part": part, "split": split, "slot": str(slot), "verdict": f.get("verdict"), "trades": f.get("trades"), "net_usdt": f.get("net_usdt"),
            "win_rate_pct": f.get("win_rate_pct")}


def box_of(rep, box):
    return {} if not rep or rep.get("section_failed") else (rep.get("boxes") or {}).get(box) or {}


def market_rows(reps, box):
    rows = []
    b = box_of(reps["part8_hour"], box)
    for split, key in (("hour_utc", "by_hour_utc"), ("session_utc", "by_session_utc")):
        rows += [row(8, split, k, f) for k, f in (b.get(key) or {}).items()]
    for dim, sp in (box_of(reps["part9_split"], box).get("splits") or {}).items():
        rows += [row(9, dim, k, f) for k, f in (sp.get("slots") or {}).items() if k != S.UNKNOWN]
    return rows


def indicator_rows(reps, box):
    rows = []
    for dim, sp in (box_of(reps["part11_playbook"], box).get("splits") or {}).items():
        rows += [row(11, dim, k, f) for k, f in (sp.get("slots") or {}).items() if k != B.NO_DATA]
    return rows


def pick(rows, verdict, best_first):
    got = [r for r in rows if r["verdict"] == verdict and r["net_usdt"] is not None]
    return sorted(got, key=lambda r: -r["net_usdt"] if best_first else r["net_usdt"])[:TOP]


def state_leads(reps, box):
    """Part 12 states that are CONSISTENT in both halves: holding beat leaving (hold) or leaving beat holding (leave). Gross ROI points."""
    hold, leave = [], []
    for dim, d in (box_of(reps["part12_next"], box).get("next_candle") or {}).items():
        for name, f in (d.get("states") or {}).items():
            if f.get("verdict") != "CONSISTENT" or not f.get("avg_to_exit_roi"):
                continue
            x = {"split": dim, "state": name, "trades": f["trades"], "avg_next_candle_roi": f["avg_next_candle_roi"], "avg_to_exit_roi": f["avg_to_exit_roi"],
                 "unit": "gross ROI points, not money"}
            (hold if f["avg_to_exit_roi"] > 0 else leave).append(x)
    key = lambda x: -abs(x["avg_to_exit_roi"])            # noqa: E731
    return sorted(hold, key=key)[:TOP], sorted(leave, key=key)[:TOP]


def luck_note(rows):
    tested = [r for r in rows if r["verdict"] in GUARDED]
    cand = sum(r["verdict"] == "CANDIDATE" for r in tested)
    if not tested:
        return "NOT ENOUGH DATA: no slot has %d trades." % M.MIN_SLOT
    if cand and cand <= math.ceil(0.05 * len(tested)):
        return "%d of %d tested slots are leads: about what luck alone gives. Weak lead." % (cand, len(tested))
    return "%d of %d tested slots passed the guard; they are compared together, so read them as leads, not proof." % (cand, len(tested))


def box_use(box, reps, failed):
    mk, ind = market_rows(reps, box), indicator_rows(reps, box)
    hold, leave = state_leads(reps, box)
    allr = mk + ind
    cnt = {v: sum(r["verdict"] == v for r in allr) for v in GUARDED}
    replay = box_of(reps["part12_next"], box).get("exit_at_warning_replay") or {}
    leaks = box_of(reps["part10_leakage"], box).get("context") or {}
    out = {"complete": not failed, "reports_failed": failed, "slots_tested": sum(cnt.values()), "candidates": cnt["CANDIDATE"], "mixed": cnt["MIXED"], "negative": cnt["NEGATIVE"],
           "luck_note": luck_note(allr),
           "market": {"use_leads": pick(mk, "CANDIDATE", True), "avoid": pick(mk, "NEGATIVE", False)},
           "indicators": {"use_leads": pick(ind, "CANDIDATE", True), "avoid": pick(ind, "NEGATIVE", False), "hold_leads": hold, "leave_leads": leave,
                          "exit_at_warning": {"verdict": replay.get("verdict", "NOT AVAILABLE"), "trades": replay.get("trades"), "net_usdt": replay.get("net_usdt")}},
           "leaks": {"biggest_measured_leaks_by_usdt": leaks.get("biggest_measured_leaks_by_usdt"), "summary": leaks.get("summary")},
           "box_net_after_fee_usdt": leaks.get("net_fee_correct_usdt"),
           "label": "LEADS ONLY: test later (Parts 39-46). Not a trading rule, nothing was switched on."}
    if failed:
        out["headline"] = "INCOMPLETE: %s failed. Do not read the lists below as final." % ", ".join(failed)
    elif not out["slots_tested"]:
        out["headline"] = "NOT ENOUGH DATA: no slot or state has %d trades yet. Nothing is named." % M.MIN_SLOT
    else:
        out["headline"] = "%d lead(s), %d to avoid, %d mixed out of %d tested. %s" % (cnt["CANDIDATE"], cnt["NEGATIVE"], cnt["MIXED"], out["slots_tested"], out["luck_note"])
    return out


def build_report(data_dir, fee_roi=1.0):
    if not os.path.isdir(os.path.realpath(data_dir)):
        return {"tool": VERSION, "read_only": True, "error": "data folder not found"}
    reps = {name: run(mod.build_report, data_dir, fee_roi) for name, mod in REPORTS}
    failed = sorted(n for n, r in reps.items() if r.get("section_failed"))
    check = run(C.build_report, data_dir, fee_roi)
    boxes = {b: box_use(b, reps, failed) for b in B.PAPER_BOXES}
    return {"tool": VERSION, "read_only": True, "made_utc": P.fmt_ts(time.time()), "fee_roi_pct_used_for_old_trades": fee_roi, "min_trades_per_slot": M.MIN_SLOT,
            "reports_failed": failed, "check_all_failed": bool(check.get("section_failed")), "boxes": boxes,
            "owner_summary": ["%s: %s" % (b, x["headline"]) for b, x in boxes.items()],
            "notes": ["Boxes are never added together. Real live boxes are not analysed here (no indicator samples, too few trades).",
                      "The verdict words are copied from Parts 8-12; this Part never loosens the 30-trade guard.",
                      "details holds the full reports of Parts 7-12, so this ONE file replaces the six older files."],
            "details": dict(reps, check_all=check)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl Indicator Playbook 3: when to use / when not to use (one command, one file, read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--fee-roi", type=float, default=1.0, help="fee %% of ROI for OLD paper trades without a fee (default 1.0)")
    a = ap.parse_args(argv)
    out = a.out or os.path.join(os.path.dirname(I.default_out()), "owl_playbook_use.json")
    rep = build_report(I.find_data_dir(a.data), a.fee_roi)
    if rep.get("error"):
        print("STOP:", rep["error"], "- run with --data FOLDER")
        return 1
    try:
        R.write_report(rep, out)
    except R.RedactionFailed:
        rep["details"]["check_all"] = {"left_out": "a secret-looking field was found; run v2_check_all.py alone"}   # the playbook itself must still be sent
        try:
            R.write_report(rep, out)
        except R.RedactionFailed as e:
            print("REFUSED: secret-looking fields, NO file written:", ", ".join(map(str, e.paths[:20])))
            return 2
    print("Playbook 3 written:", out)
    for line in rep["owner_summary"]:
        print(" -", line)
    if rep["reports_failed"]:
        print("WARNING: these reports failed:", ", ".join(rep["reports_failed"]), "- the file says INCOMPLETE")
    print("Nothing was changed. Send this ONE file to Claude. No other command is needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
