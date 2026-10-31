"""v2_summaries.py - Part 35: DATA EXPLORER 1 of 4 (backend, read-only). Four plain lists: WHAT HAPPENED / WHAT WAS TESTED / WHAT WAS LEARNED / WHAT IS UNKNOWN,
every number with its count and its coverage. It uses the data that is ALREADY on the phone, as it is; nothing is downloaded, nothing is written, nothing is changed.

Sources (all read-only, all existing Parts):
  Part 3  v2_inventory.build_report  -> which files exist, how many rows / lines, label (amount + timestamp quality, NOT profit)
  Part 5  v2_pnl.build_report        -> trades per box (real_live, live_estimated, paper_b1, paper_b2) - the 4 boxes are NEVER added together
  Part 39 v2_ledger (opened read-only) -> findings by status, each with sample_size AND denominator
No trade, order, setting or ledger row is touched; no network; no trading module is imported. The answer goes through the Part 5 redaction.
A win rate is NEVER given: only counts (trades, wins, losses) with the number of trades they come from.
The inventory read is slow on a phone, so the answer is kept for 120 seconds (cache) and a part that fails is shown as UNKNOWN, never as an empty success.

Run (Termux):  python3 backend/v2_summaries.py [--data DIR]      -> prints the answer as JSON
Route: GET /api/v2/summary (Part 36, in api/v2_data.py; off until the file v2_api_enabled exists)."""
import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "v2_summaries 1 (Part 35)"
CACHE_SEC = 120
MAX_FILES = 60
MAX_FINDINGS = 20
_CACHE = {}


def _now_text():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _rows_of(info):
    """Rows (database: sum of table rows) or lines (text file) of one inventory entry; None when unknown."""
    if info.get("tables"):
        vals = [t.get("rows") for t in info["tables"] if isinstance(t.get("rows"), int)]
        return sum(vals) if vals else None
    return info.get("lines") if isinstance(info.get("lines"), int) else None


def _data_files(data_dir, unknown):
    import v2_inventory as I
    try:
        inv = I.build_report(data_dir)
    except Exception:
        unknown.append("The data inventory could not be read, so the list of files is missing (not empty).")
        return {"state": "UNKNOWN", "files": [], "by_label": {}}
    summ = inv.get("summary", {})
    if summ.get("error"):
        unknown.append("The data folder was not found, so no file could be counted.")
        return {"state": "UNKNOWN", "files": [], "by_label": {}}
    files = []
    for rel, info in sorted(inv.get("files", {}).items()):
        files.append({"file": rel, "kind": info.get("kind"), "label": info.get("label"), "rows": _rows_of(info),
                      "bytes": info.get("bytes"), "modified_utc": info.get("modified_utc"), "status": info.get("status")})
        lab = info.get("label")
        if lab in ("Not collected", "Data incomplete", "Insufficient data"):
            why = info.get("reason") or {"Not collected": "no rows yet", "Data incomplete": "no usable time column or bad timestamps",
                                         "Insufficient data": "fewer than 30 rows"}[lab]
            unknown.append("%s: %s (%s). It cannot support a conclusion yet." % (rel, lab, why))
    cut = len(files) > MAX_FILES
    return {"state": "OK", "files_seen": summ.get("files_seen", len(files)), "files_over_limit": summ.get("files_over_limit", 0),
            "by_label": summ.get("by_label", {}), "files": files[:MAX_FILES], "cut": cut,
            "meaning": "labels describe the amount of data and the timestamp quality only; they say nothing about profit"}


def _trade_boxes(data_dir, unknown):
    import v2_pnl as P
    try:
        rep = P.build_report(data_dir)
    except Exception:
        unknown.append("The trade archive could not be read, so trade counts are missing (not zero).")
        return {"state": "UNKNOWN", "boxes": {}}
    if rep.get("error"):
        unknown.append("The data folder was not found, so trades could not be counted.")
        return {"state": "UNKNOWN", "boxes": {}}
    out = {}
    for name, b in rep.get("boxes", {}).items():
        issues = sum(v.get("count", 0) for v in b.get("checks", {}).values())
        out[name] = {"trades": b.get("trades", 0), "wins": b.get("wins", 0), "losses": b.get("losses", 0),
                     "first_close_utc": b.get("first_close_utc"), "last_close_utc": b.get("last_close_utc"),
                     "label": b.get("label"), "trusted_for_research": bool(b.get("trusted_for_research")), "data_issues": issues}
        if not b.get("trades"):
            unknown.append("Box %s has no closed trades in the archive: nothing can be said about it." % name)
        elif issues:
            unknown.append("Box %s has %d data issue(s) found by the Part 5 checks (duplicates, missing pnl or time ...)." % (name, issues))
    return {"state": "OK", "boxes": out, "never_added_together": True,
            "meaning": "counts only; wins and losses are out of the trades shown; no win rate is given"}


def _ledger(data_dir, unknown):
    import v2_ledger as L
    try:
        rows = L.latest(data_dir, True)
    except FileNotFoundError:
        unknown.append("The Knowledge Ledger is empty: no finding has been written yet (empty is not the same as nothing found).")
        return {"state": "EMPTY", "findings": 0, "by_status": {}, "list": []}
    except Exception:
        unknown.append("The Knowledge Ledger could not be read, so what was learned is missing (not empty).")
        return {"state": "UNKNOWN", "findings": 0, "by_status": {}, "list": []}
    by = {}
    for r in rows:
        by[r["status"]] = by.get(r["status"], 0) + 1
        if r["status"] in ("Insufficient data", "Data incomplete", "Not collected"):
            unknown.append("%s %s: status %s (sample %s of %s)." % (r["finding_id"], r["name"], r["status"], r["sample_size"], r["denominator"]))
    lst = [{"finding_id": r["finding_id"], "version": r["version"], "name": r["name"], "status": r["status"],
            "sample_size": r["sample_size"], "denominator": r["denominator"], "denominator_label": r.get("denominator_label")}
           for r in rows[:MAX_FINDINGS]]
    return {"state": "OK" if rows else "EMPTY", "findings": len(rows), "by_status": by, "list": lst, "cut": len(rows) > MAX_FINDINGS,
            "meaning": "not ranked by win rate; every finding shows its sample size and its denominator"}


def build(data_dir, now=None, use_cache=True):
    """-> the summary dict. Never raises; each part that fails says UNKNOWN."""
    t = time.time() if now is None else now
    key = os.path.realpath(data_dir)
    hit = _CACHE.get(key)
    if use_cache and hit and t - hit[0] < CACHE_SEC:
        return hit[1]
    unknown = []
    files = _data_files(data_dir, unknown)
    boxes = _trade_boxes(data_dir, unknown)
    led = _ledger(data_dir, unknown)
    happened = {"data_files": files, "trades": boxes}
    tested = {"ledger_findings_by_status": led["by_status"], "findings": led["findings"],
              "note": "Only what is written in the Knowledge Ledger counts as tested. A report file that was run but not entered in the Ledger is not listed here."}
    learned = {"ledger": led}
    unknown.append("Not checked here: AI Vision outcomes and the Dual Bot / Brain databases beyond their file row counts (Parts 36-38 and later).")
    out = {"tool": VERSION, "made_utc": _now_text(), "read_only": True,
           "what_happened": happened, "what_was_tested": tested, "what_was_learned": learned, "what_is_unknown": unknown[:200],
           "coverage": {"files_seen": files.get("files_seen"), "boxes_read": len(boxes.get("boxes", {})), "ledger_findings": led["findings"]},
           "notes": ["The 4 trade boxes are never added together.", "No win rate is given; only counts with the number they come from.",
                     "A part that could not be read says UNKNOWN; it is never shown as zero."]}
    _CACHE[key] = (t, out)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl data summary (read-only)")
    ap.add_argument("--data", help="data folder")
    a = ap.parse_args(argv)
    import v2_inventory as I
    import v2_inv_redact as R
    print(R.safe_report(build(I.find_data_dir(a.data), use_cache=False)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
