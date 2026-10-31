"""v2_ledger_fill.py - Part 73: LEDGER AUTO-FILL. The Knowledge Ledger (Parts 39-42) is empty until findings are written. This tool reads the ONE file of the
Indian Playbook (owl_playbook_use.json, Part 13) and writes one Ledger finding per USE LEAD and per AVOID slot, so the Ledger screen shows real, traceable rows.

It only COPIES what Parts 8-13 already judged; it never judges again and never loosens their 30-trade guard:
  - USE LEAD (verdict CANDIDATE) and AVOID (verdict NEGATIVE) slots of the market and indicator splits, per paper box (paper_b1, paper_b2: never added together).
  - Status is NEVER above "Exploratory" (a lead is something to test later); a slot under 30 trades would be "Insufficient data" (the report never lists one).
  - sample_size = trades of the slot, denominator = trades of the box with that split known (every result shows both). net_result = net after fee (USDT).
  - A box whose reports failed (INCOMPLETE) is skipped and named; an empty list is never written as "nothing found".
  - Hold / leave states (gross ROI points, another unit) are NOT copied here.
Idempotent: the same finding name is never added twice; if the numbers changed a NEW VERSION is added (the old version stays); if nothing changed, nothing is written.
It writes only to the Ledger file v2_ledger.db in the data folder. No trade, setting or other file is touched; no network; no trading module.

Run (Termux):  python3 backend/v2_ledger_fill.py [--data DIR] [--from FILE] [--dry-run]
  --from FILE  default: owl_playbook_use.json in the Download folder (make it first with: python3 backend/v2_playbook_use.py)
  --dry-run    print what would be written, write nothing"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_inventory as I
import v2_ledger as L

VERSION = "v2_ledger_fill 1 (Part 73)"
MIN_TRADES = 30
KINDS = (("use_leads", "LEAD (use)"), ("avoid", "AVOID"))
COMPARE = ("status", "sample_size", "denominator", "net_result", "note")


def _slots(details, part, split, box):
    """-> {slot: facts} of one split of one box, from the full reports kept inside the Playbook file."""
    if part == 8:
        b = (((details.get("part8_hour") or {}).get("boxes") or {}).get(box)) or {}
        return b.get({"hour_utc": "by_hour_utc", "session_utc": "by_session_utc"}.get(split, ""), {}) or {}
    key = {9: "part9_split", 11: "part11_playbook"}.get(part)
    b = (((details.get(key) or {}).get("boxes") or {}).get(box)) or {}
    return (((b.get("splits") or {}).get(split) or {}).get("slots")) or {}


def _denominator(details, part, split, box):
    return sum(int(f.get("trades") or 0) for k, f in _slots(details, part, split, box).items() if k not in ("UNKNOWN", "NO DATA", "no data"))


def _finding(rep, box, group, kind_key, kind_word, r):
    n = int(r.get("trades") or 0)
    den = _denominator(rep.get("details") or {}, r.get("part"), r.get("split"), box)
    wr = r.get("win_rate_pct")
    not_won = (n - int(round(n * float(wr) / 100.0))) if wr is not None else None
    fee = rep.get("fee_roi_pct_used_for_old_trades")
    status = "Exploratory" if n >= MIN_TRADES else "Insufficient data"
    name = "%s | %s %s = %s | %s" % (box, group, r.get("split"), r.get("slot"), kind_word)
    return name, {
        "name": name, "status": status,
        "definition": "Paper box %s, split %s (%s), slot %s: net result after fee of the trades in that slot. Copied from the Playbook (Part %s); the guard is >= 30 trades, "
                      "net after fee above 0, both halves above 0, above 0 without the best trade (for an AVOID slot: net at or below 0)." % (box, r.get("split"), group, r.get("slot"), r.get("part")),
        "sample_size": n, "denominator": max(den, n), "denominator_label": "paper trades of %s with the %s split known" % (box, r.get("split")),
        "net_result": r.get("net_usdt"), "cost_assumptions": "net after fee; old paper trades without a fee use %s%% of ROI" % fee if fee is not None else "net after fee",
        "confidence": "LEAD only. %s" % ((rep["boxes"][box].get("luck_note")) or ""),
        "limitations": "Paper box, not live money. Many slots are compared at once, so luck is possible. Not a trading rule. Nothing was switched on.",
        "counterexamples": "Trades that did not win: %s of %s" % (not_won if not_won is not None else "unknown", n),
        "next_test": "Check again on newer paper trades after the next Playbook run. Move above Exploratory only through the Ledger rules and the owner.",
        "owner_approval": "none", "production_status": "Research only. No live use.",
        "note": "auto-filled from owl_playbook_use.json made %s" % rep.get("made_utc"),
    }


def collect(rep):
    """-> (list of (name, fields), list of skipped-box texts). Reads the Playbook report only."""
    out, skipped = [], []
    for box, b in (rep.get("boxes") or {}).items():
        if not b.get("complete"):
            skipped.append("%s skipped: INCOMPLETE (%s). Nothing was written for it." % (box, ", ".join(b.get("reports_failed") or ["unknown"])))
            continue
        for group, sect in (("market", b.get("market") or {}), ("indicators", b.get("indicators") or {})):
            for key, word in KINDS:
                for r in sect.get(key) or []:
                    out.append(_finding(rep, box, group, key, word, r))
    return out, skipped


def fill(data_dir, rep, dry=False):
    items, skipped = collect(rep)
    try:
        have = {r["name"]: r for r in L.latest(data_dir, True)}
    except FileNotFoundError:
        have = {}
    added = versions = same = 0
    for name, f in items:
        old = have.get(name)
        if old is not None and all(old.get(k) == f.get(k) for k in COMPARE):
            same += 1
            continue
        if dry:
            added, versions = (added + 1, versions) if old is None else (added, versions + 1)
            continue
        res = L.add_version(data_dir, f, None if old is None else old["finding_id"])
        if not res.get("ok"):
            skipped.append("%s: %s" % (name, res.get("error")))
        elif old is None:
            added += 1
        else:
            versions += 1
    return {"tool": VERSION, "dry_run": dry, "found": len(items), "new_findings": added, "new_versions": versions, "unchanged": same, "skipped": skipped}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl Ledger auto-fill from the Playbook report")
    ap.add_argument("--data")
    ap.add_argument("--from", dest="src")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    data_dir = I.find_data_dir(a.data)
    src = a.src or os.path.join(os.path.dirname(I.default_out()), "owl_playbook_use.json")
    if not os.path.isfile(src):
        print("STOP: %s not found. Make it first: python3 backend/v2_playbook_use.py" % src)
        return 1
    try:
        with open(src, "r", encoding="utf-8") as fh:
            rep = json.load(fh)
    except (OSError, ValueError):
        print("STOP: %s cannot be read as a Playbook report." % src)
        return 1
    if not str(rep.get("tool", "")).startswith("v2_playbook_use") or not isinstance(rep.get("boxes"), dict):
        print("STOP: that file is not an owl_playbook_use.json report.")
        return 1
    res = fill(data_dir, rep, a.dry_run)
    print("%s: %d slot(s) found | new findings %d | new versions %d | unchanged %d%s" % (
        "DRY RUN" if res["dry_run"] else "DONE", res["found"], res["new_findings"], res["new_versions"], res["unchanged"], " (nothing written)" if res["dry_run"] else ""))
    for s in res["skipped"]:
        print("-", s)
    if not res["found"] and not res["skipped"]:
        print("No lead and no avoid slot yet (not enough data). Nothing was written: empty is not the same as nothing found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
