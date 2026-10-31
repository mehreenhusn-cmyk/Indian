"""v2_ledger_trace.py - Part 40: KNOWLEDGE LEDGER 2 of 4 = the TRACE CHAIN (storage + read, nothing connected).

Chain (README 9.8): finding version (= the evaluation version, Part 39) -> record IDs -> candle / indicator snapshots -> fees and
assumptions -> outcome -> counterexamples. This file stores the LINKS in the same v2_ledger.db (new table trace_item) and answers
"show me the chain of finding F-0001 version 2, and what is missing in it". It stores only IDs and numbers the owner / a later
Part gives it. It never reads another database, never computes a result itself, never invents a missing link: a missing link is
reported as a GAP. Append-only like Part 39 (SQLite triggers refuse UPDATE and DELETE; a wrong link is corrected by a NEW version
of the finding, never by editing). No network, no trading / live module, no setting touched. Nothing calls it yet (route = Part 41).

Item kinds: record (one trade / observation / cohort row by its ID) | candle (candle snapshot of a record) | indicator (indicator
snapshot of a record) | outcome (the result of the whole finding version, one line of text + numbers).
source (data domain, NEVER added together): live | paper | observation | market | cohort_official | cohort_proxy | scalp | brain | diagnostics.
A record carries gross, fee, net (decimal text) and fee_basis; a counterexample is a record with counterexample=1 and stays in the
chain and in the counts (failed cases are kept).
Run (Termux):  python3 backend/v2_ledger_trace.py add FILE.json | show F-0001 [--version N]   [--data DIR]
FILE.json = {"finding_id": "F-0001", "version": 2, "items": [{"kind": "record", "ref_id": "T123", "source": "paper", ...}]}"""
import argparse
import json
import os
import sqlite3
import sys
import time
from decimal import Decimal, InvalidOperation

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v2_ledger as L

VERSION = "v2_ledger_trace 1 (Part 40)"
KINDS = ("record", "candle", "indicator", "outcome")
SOURCES = ("live", "paper", "observation", "market", "cohort_official", "cohort_proxy", "scalp", "brain", "diagnostics")
ITEM_KEYS = ("kind", "ref_id", "source", "record_ref", "symbol", "timeframe", "event_utc", "gross", "fee", "net", "fee_basis",
             "counterexample", "note")
MONEY = ("gross", "fee", "net")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trace_item (
  row_id INTEGER PRIMARY KEY AUTOINCREMENT, finding_id TEXT NOT NULL, version INTEGER NOT NULL, created_utc REAL NOT NULL,
  kind TEXT NOT NULL, ref_id TEXT NOT NULL, source TEXT NOT NULL, record_ref TEXT, symbol TEXT, timeframe TEXT, event_utc TEXT,
  gross TEXT, fee TEXT, net TEXT, fee_basis TEXT, counterexample INTEGER NOT NULL DEFAULT 0, note TEXT,
  UNIQUE(finding_id, version, kind, ref_id, source));
CREATE TRIGGER IF NOT EXISTS no_update_ti BEFORE UPDATE ON trace_item BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_ti BEFORE DELETE ON trace_item BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
"""


def connect(data_dir):
    con = L.connect(data_dir)
    con.executescript(SCHEMA)
    return con


def D(x):
    try:
        v = Decimal(str(x))
        return v if v.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def clean_item(it):
    """-> (dict, error). Unknown keys refused; money must be a decimal number; a candle / indicator must name its record_ref."""
    if not isinstance(it, dict):
        return None, "an item must be an object"
    bad = sorted(set(it) - set(ITEM_KEYS))
    if bad:
        return None, "unknown key(s): " + ", ".join(bad)
    o = {k: it.get(k) for k in ITEM_KEYS}
    if o["kind"] not in KINDS:
        return None, "kind must be one of: " + " | ".join(KINDS)
    if o["source"] not in SOURCES:
        return None, "source must be one of: " + " | ".join(SOURCES)
    if not str(o["ref_id"] or "").strip():
        return None, "ref_id is required (an outcome may use a short label)"
    if o["kind"] in ("candle", "indicator") and not str(o["record_ref"] or "").strip():
        return None, "a %s snapshot must name its record_ref" % o["kind"]
    for k in MONEY:
        if o[k] is not None:
            d = D(o[k])
            if d is None:
                return None, "%s must be a number" % k
            o[k] = str(d)
    ce = o["counterexample"]
    if ce not in (None, 0, 1, True, False):
        return None, "counterexample must be 0 or 1"
    if ce and o["kind"] != "record":
        return None, "only a record can be a counterexample"
    o["counterexample"] = 1 if ce else 0
    for k in ("ref_id", "record_ref", "symbol", "timeframe", "event_utc", "fee_basis", "note"):
        if o[k] is not None:
            o[k] = str(o[k])
    return o, None


def add_items(data_dir, finding_id, version, items):
    """All-or-nothing: if one item is wrong, NOTHING is stored. -> dict(ok, added) or dict(ok False, error)."""
    if not isinstance(items, list) or not items:
        return {"ok": False, "error": "items must be a non-empty list"}
    rows = []
    for n, it in enumerate(items, 1):
        o, err = clean_item(it)
        if err:
            return {"ok": False, "error": "item %d: %s" % (n, err)}
        rows.append(o)
    con = connect(data_dir)
    try:
        if con.execute("SELECT 1 FROM finding_version WHERE finding_id=? AND version=?", (finding_id, version)).fetchone() is None:
            return {"ok": False, "error": "no such finding version %s v%s" % (finding_id, version)}
        cols = ("finding_id", "version", "created_utc") + ITEM_KEYS
        t = time.time()
        try:
            for o in rows:
                con.execute("INSERT INTO trace_item (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))),
                            (finding_id, version, t) + tuple(o[k] for k in ITEM_KEYS))
            con.commit()
        except sqlite3.IntegrityError:
            con.rollback()
            return {"ok": False, "error": "the same item (kind + ref_id + source) is already in this version; nothing stored"}
        return {"ok": True, "added": len(rows)}
    finally:
        con.close()


def trace(data_dir, finding_id, version=None):
    """The chain of one finding version (default: the newest) + GAPS. Money is summed per source, never across sources."""
    con = connect(data_dir)
    try:
        if version is None:
            version = con.execute("SELECT MAX(version) FROM finding_version WHERE finding_id=?", (finding_id,)).fetchone()[0]
        fv = con.execute("SELECT * FROM finding_version WHERE finding_id=? AND version=?", (finding_id, version)).fetchone()
        if fv is None:
            return {"tool": VERSION, "error": "no such finding version"}
        items = [dict(r) for r in con.execute("SELECT * FROM trace_item WHERE finding_id=? AND version=? ORDER BY row_id",
                                              (finding_id, version))]
    finally:
        con.close()
    recs = [i for i in items if i["kind"] == "record"]
    snaps = {k: {i["record_ref"] for i in items if i["kind"] == k} for k in ("candle", "indicator")}
    per = {}
    for r in recs:
        s = per.setdefault(r["source"], {"records": 0, "counterexamples": 0, "gross": Decimal(0), "fee": Decimal(0),
                                         "net": Decimal(0), "fee_missing": 0})
        s["records"] += 1
        s["counterexamples"] += r["counterexample"]
        for k in MONEY:
            d = D(r[k])
            if d is not None:
                s[k] += d
        if r["fee"] is None:
            s["fee_missing"] += 1
    for s in per.values():
        for k in MONEY:
            s[k] = str(s[k])
    gaps = []
    if fv["sample_size"] and not recs:
        gaps.append("sample_size is %d but NO record IDs are stored" % fv["sample_size"])
    elif recs and len(recs) != fv["sample_size"]:
        gaps.append("sample_size is %d but %d record IDs are stored" % (fv["sample_size"], len(recs)))
    for r in recs:
        miss = [k for k in ("candle", "indicator") if r["ref_id"] not in snaps[k]]
        if miss:
            gaps.append("record %s (%s): no %s snapshot linked" % (r["ref_id"], r["source"], " / no ".join(miss)))
        if r["fee"] is None:
            gaps.append("record %s (%s): fee missing" % (r["ref_id"], r["source"]))
    if recs and not any(i["kind"] == "outcome" for i in items):
        gaps.append("no outcome line stored")
    if recs and not (fv["cost_assumptions"] or "").strip():
        gaps.append("cost assumptions are empty in the finding version")
    n_ce = sum(r["counterexample"] for r in recs)
    return {"tool": VERSION, "read_only_view": True, "finding": {k: fv[k] for k in ("finding_id", "version", "name", "status",
            "sample_size", "denominator", "denominator_label", "cost_assumptions")},
            "records": len(recs), "counterexamples": n_ce,
            "counterexample_share": "%d of %d" % (n_ce, len(recs)) if recs else "0 of 0",
            "per_source": per, "items": items, "gaps": gaps, "complete": bool(recs) and not gaps,
            "note": "sums are per source and never added together; a gap is shown, never filled in"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("add", "show"))
    ap.add_argument("arg")
    ap.add_argument("--version", type=int)
    ap.add_argument("--data")
    a = ap.parse_args(argv)
    d = L.find_data_dir(a.data)
    if a.cmd == "show":
        res = trace(d, a.arg, a.version)
    else:
        try:
            with open(a.arg, encoding="utf-8") as fh:
                j = json.load(fh)
            res = add_items(d, j["finding_id"], j["version"], j["items"])
        except (OSError, KeyError, TypeError, ValueError) as e:
            res = {"ok": False, "error": "cannot read the json file: %s" % e}
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    sys.exit(main())
