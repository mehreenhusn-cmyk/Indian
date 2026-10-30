"""v2_check_all.py - Part 7: ONE COMMAND, ONE FILE (read-only). Runs the inventory (Part 3), the closed-trade P&L check (Part 5) and the
open-position P&L check (Part 6) in one go and writes ONE owner summary: owl_check_all.json. Send that single file to Claude.

It separates the money into WORLDS that are never added together:
  real_live | live_estimated | paper_main | paper_bot2 | dual_bot | brain      (+ the open-position boxes of Part 6)
and gives each world a plain verdict: TRUSTED / USE WITH CARE (with the reasons) / NOT COLLECTED.
Dual Bot and Brain are paper only: if their tables show a live value in a mode column, that is flagged.
Nothing is written next to the data, no network, no trading module. A failing section is reported as failed; the rest still runs.
Run (Termux):  python3 backend/v2_check_all.py [--data DIR] [--out FILE] [--fee-roi 1.0]   -> Download/owl_check_all.json
Tests: python3 test/test_v2_check_all.py"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_inv_redact as R
import v2_inventory as I
import v2_pnl as P
import v2_pnl_open as O

VERSION = "v2_check_all 1 (Part 7)"
SIDE_DBS = {"dual_archive.db": "dual_bot", "brain_archive.db": "brain"}      # paper-only worlds that live in their own database
CLOSED = {"real_live": "real_live", "live_estimated": "live_estimated", "paper_b1": "paper_main", "paper_b2": "paper_bot2"}
OPEN = {"live_local_copy": "real_live", "paper_b1": "paper_main", "paper_b2": "paper_bot2"}
WORLDS = ("real_live", "live_estimated", "paper_main", "paper_bot2", "dual_bot", "brain")


def safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:                                   # one broken section must never hide the others
        return {"section_failed": True, "reason": "%s: %s" % (type(e).__name__, str(e)[:120])}


def side_world(inv, world, dbname):
    """Summary of Dual Bot / Brain from the inventory: tables, rows, label, and any LIVE value in a mode column."""
    w = {"found": False, "tables": 0, "rows": 0, "label": "Not collected", "live_values_found": [], "problems": []}
    for rel, f in (inv.get("files") or {}).items():
        if os.path.basename(rel) != dbname:
            continue
        w["found"] = True
        if f.get("status"):
            w["problems"].append("database not opened: " + str(f.get("reason", f["status"]))[:80])
        for t in f.get("tables") or []:
            w["tables"] += 1
            w["rows"] += t.get("rows") or 0
            w["problems"] += ["%s: %s" % (t["table"], p) for p in t.get("problems") or []]
            col = t.get("paper_live_column")
            if col and any("live" in str(v).lower() for v in col["values"]):
                w["live_values_found"].append("%s.%s" % (t["table"], col["column"]))
        w["label"] = f.get("label", w["label"])
    if w["live_values_found"]:
        w["problems"].append("a mode column holds a live value, but %s must be paper only" % world)
    return w


def verdict(trades, label, problems, notes):
    if not trades:
        return {"verdict": "NOT COLLECTED", "reasons": ["no closed trades recorded"]}
    reasons = list(problems) + list(notes)
    if label not in ("Exploratory", "Watch"):
        reasons.append("only %d trades (%s)" % (trades, label))
    return {"verdict": "USE WITH CARE" if reasons else "TRUSTED", "reasons": reasons}


def separate(inv, pnl, opn):
    worlds = {w: {"closed": None, "open": None} for w in WORLDS}
    for b, w in CLOSED.items():
        box = (pnl.get("boxes") or {}).get(b)
        if not box:
            continue
        probs = ["%s: %d" % (k, v["count"]) for k, v in box["checks"].items() if v["count"]]
        notes = []
        if box.get("needs_fee_estimate"):
            notes.append("old trades have no fee inside: fee is estimated")
        if w == "real_live":
            notes.append("fee and funding per trade not verified (see code_facts)")
        if w == "live_estimated":
            notes.append("estimated from the last price, not real Binance data")
        worlds[w]["closed"] = {"trades": box["trades"], "net_fee_correct_usdt": box["net_fee_correct_usdt"],
                               "label": box["label"], **verdict(box["trades"], box["label"], probs, notes)}
    for b, w in OPEN.items():
        box = (opn.get("boxes") or {}).get(b)
        if not box:
            continue
        probs = ["%s: %d" % (k, v["count"]) for k, v in box["checks"].items() if v["count"]]
        worlds[w]["open"] = {"positions": box["positions"], "floating_net_usdt": box["floating_net_usdt"],
                             "is_real_money": False, "current": box["floating_is_current"], "problems": probs}
    for w, db in ((v, k) for k, v in SIDE_DBS.items()):
        s = side_world(inv, w, db)
        worlds[w]["closed"] = {"trades": s["rows"], "label": s["label"], "database_found": s["found"],
                               **verdict(s["rows"], s["label"], s["problems"], [])}
    return worlds


def summary_lines(worlds, pnl, opn):
    out = []
    for w in WORLDS:
        c = worlds[w]["closed"]
        if not c:
            continue
        net = "" if "net_fee_correct_usdt" not in c else ", net after fee %+.2f USDT" % c["net_fee_correct_usdt"]
        out.append("%s: %d trades%s - %s%s" % (w, c["trades"], net, c["verdict"], (" (" + "; ".join(c["reasons"][:3]) + ")") if c["reasons"] else ""))
    for w in WORLDS:
        o = worlds[w]["open"]
        if o and o["positions"]:
            out.append("%s open: %d positions, floating %+.2f USDT (%s, never real money offline)" % (
                w, o["positions"], o["floating_net_usdt"], "current" if o["current"] else "OLD snapshot"))
    out.append("Live profit: funding fee is not included and a fee paid in BNB is not subtracted - check Binance fee settings.")
    out.append("The worlds are never added together.")
    return out


def build_report(data_dir, fee_roi=1.0):
    if not os.path.isdir(data_dir):
        return {"tool": VERSION, "read_only": True, "error": "data folder not found"}
    inv = safe(I.build_report, data_dir)
    pnl = safe(P.build_report, data_dir, fee_roi)
    opn = safe(O.build_report, data_dir, fee_roi)
    failed = [n for n, r in (("inventory", inv), ("closed_pnl", pnl), ("open_pnl", opn)) if r.get("section_failed")]
    worlds = separate(inv, pnl, opn) if not failed else {}
    return {"tool": VERSION, "read_only": True, "made_utc": P.fmt_ts(time.time()), "sections_failed": failed, "worlds": worlds,
            "owner_summary": summary_lines(worlds, pnl, opn) if worlds else ["a section failed: see sections_failed"],
            "details": {"inventory": inv, "closed_pnl": pnl, "open_pnl": opn}}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl: one command, one file (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--fee-roi", type=float, default=1.0)
    a = ap.parse_args(argv)
    out = a.out or os.path.join(os.path.dirname(I.default_out()), "owl_check_all.json")
    rep = build_report(I.find_data_dir(a.data), a.fee_roi)
    if rep.get("error"):
        print("STOP:", rep["error"], "- run with --data FOLDER")
        return 1
    try:
        R.write_report(rep, out)
    except R.RedactionFailed as e:
        print("REFUSED: secret-looking fields, NO file written:", ", ".join(map(str, e.paths[:20])))
        return 2
    print("Check written:", out)
    for line in rep["owner_summary"]:
        print(" -", line)
    print("Nothing was changed. Send this ONE file to Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
