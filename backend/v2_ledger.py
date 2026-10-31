"""v2_ledger.py - Part 39: KNOWLEDGE LEDGER 1 of 4 (storage only, nothing connected).

One finding = one stable ID (F-0001...). Every change is a NEW version row; an old version is NEVER overwritten or deleted
(SQLite triggers refuse UPDATE and DELETE). Failed ideas and counterexamples stay. Own file v2_ledger.db in the data folder.
No network, no trading module, no live code, reads no other database, touches no setting. Nothing calls it yet (the trace chain
is Part 40, the route Part 41, the screen Part 42).

Status words (README 9.8, exactly these): Not collected | Data incomplete | Insufficient data | Exploratory | Watch |
Promising (unvalidated) | Validated in limited conditions | Rejected | Approved for controlled/paper test.
Research approval is NOT permission to change a live rule. Every result carries its sample size AND its denominator
(a win rate without a denominator is refused). Statuses from Promising upwards need sample_size > 0 and denominator > 0.

Run (Termux):  python3 backend/v2_ledger.py list | history F-0001 | changes | review | add FILE.json   [--data DIR]
  changes = what changed since the last review (versions added after it, with a field-by-field diff); review = mark "reviewed now"."""
import argparse
import json
import os
import sqlite3
import sys
import time
from urllib.request import pathname2url

VERSION = "v2_ledger 1 (Part 39)"
DB_NAME = "v2_ledger.db"
STATUSES = ("Not collected", "Data incomplete", "Insufficient data", "Exploratory", "Watch", "Promising (unvalidated)",
            "Validated in limited conditions", "Rejected", "Approved for controlled/paper test")
NEEDS_SAMPLE = STATUSES[5:6] + STATUSES[6:7] + STATUSES[8:9]
TEXT = ("name", "definition", "period_start", "period_end", "symbols", "timeframes", "denominator_label", "cost_assumptions",
        "confidence", "limitations", "counterexamples", "next_test", "owner_approval", "production_status", "note")
NUM = ("sample_size", "denominator")
FLOAT = ("gross_result", "net_result", "max_drawdown")
FIELDS = ("name", "definition", "status", "period_start", "period_end", "symbols", "timeframes", "sample_size", "denominator",
          "denominator_label", "gross_result", "net_result", "max_drawdown", "cost_assumptions", "confidence", "limitations",
          "counterexamples", "next_test", "owner_approval", "production_status", "note")

SCHEMA = """
CREATE TABLE IF NOT EXISTS finding_version (
  row_id INTEGER PRIMARY KEY AUTOINCREMENT, finding_id TEXT NOT NULL, version INTEGER NOT NULL, created_utc REAL NOT NULL,
  name TEXT NOT NULL, definition TEXT, status TEXT NOT NULL, period_start TEXT, period_end TEXT, symbols TEXT, timeframes TEXT,
  sample_size INTEGER NOT NULL, denominator INTEGER NOT NULL, denominator_label TEXT, gross_result REAL, net_result REAL,
  max_drawdown REAL, cost_assumptions TEXT, confidence TEXT, limitations TEXT, counterexamples TEXT, next_test TEXT,
  owner_approval TEXT, production_status TEXT, note TEXT, UNIQUE(finding_id, version));
CREATE TABLE IF NOT EXISTS review_mark (row_id INTEGER PRIMARY KEY AUTOINCREMENT, reviewed_utc REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS no_update_fv BEFORE UPDATE ON finding_version BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_fv BEFORE DELETE ON finding_version BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS no_update_rm BEFORE UPDATE ON review_mark BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_rm BEFORE DELETE ON review_mark BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END;
"""


def find_data_dir(arg=None):
    if arg:
        return arg
    try:
        import v2_inventory as I          # same folder rule as the other V2 tools, when it is there
        return I.find_data_dir(None)
    except Exception:
        return os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data")


def connect(data_dir, ro=False):
    """ro=True (Part 41, the read-only route): open the EXISTING file read-only, create nothing, no schema script."""
    if ro:
        path = os.path.join(data_dir, DB_NAME)
        if not os.path.isfile(path):
            raise FileNotFoundError(DB_NAME)
        con = sqlite3.connect("file:%s?mode=ro" % pathname2url(os.path.abspath(path)), uri=True)
        con.row_factory = sqlite3.Row
        return con
    os.makedirs(data_dir, exist_ok=True)
    con = sqlite3.connect(os.path.join(data_dir, DB_NAME))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def clean(fields):
    """-> (dict of the known fields, error text or None). Unknown keys are refused, never ignored."""
    unknown = sorted(set(fields) - set(FIELDS))
    if unknown:
        return None, "unknown field(s): " + ", ".join(unknown)
    out = {k: fields.get(k) for k in FIELDS}
    if not str(out["name"] or "").strip():
        return None, "name is required"
    if out["status"] not in STATUSES:
        return None, "status must be one of: " + " | ".join(STATUSES)
    for k in NUM:
        v = out[k]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            return None, "%s is required and must be a whole number >= 0 (every result shows its denominator)" % k
    for k in FLOAT:
        if out[k] is not None:
            try:
                out[k] = float(out[k])
            except (TypeError, ValueError):
                return None, "%s must be a number" % k
    for k in TEXT:
        if out[k] is not None:
            out[k] = str(out[k])
    if out["status"] in NEEDS_SAMPLE and (out["sample_size"] <= 0 or out["denominator"] <= 0):
        return None, "status '%s' needs sample_size > 0 and denominator > 0 (otherwise use Insufficient data)" % out["status"]
    return out, None


def add_version(data_dir, fields, finding_id=None):
    """New finding (finding_id None) or a NEW VERSION of an existing one. -> dict(ok, finding_id, version) or dict(ok False, error)."""
    f, err = clean(fields)
    if err:
        return {"ok": False, "error": err}
    con = connect(data_dir)
    try:
        if finding_id is None:
            n = con.execute("SELECT COUNT(DISTINCT finding_id) FROM finding_version").fetchone()[0]
            finding_id, ver = "F-%04d" % (n + 1), 1
        else:
            r = con.execute("SELECT MAX(version) FROM finding_version WHERE finding_id=?", (finding_id,)).fetchone()[0]
            if r is None:
                return {"ok": False, "error": "unknown finding_id " + str(finding_id)}
            ver = r + 1
        cols = ("finding_id", "version", "created_utc") + FIELDS
        con.execute("INSERT INTO finding_version (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))),
                    (finding_id, ver, time.time()) + tuple(f[k] for k in FIELDS))
        con.commit()
        return {"ok": True, "finding_id": finding_id, "version": ver}
    finally:
        con.close()


def _rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def history(data_dir, finding_id, ro=False):
    """All versions of one finding, oldest first. Failed / rejected versions are kept and shown."""
    con = connect(data_dir, ro)
    try:
        return _rows(con, "SELECT * FROM finding_version WHERE finding_id=? ORDER BY version", (finding_id,))
    finally:
        con.close()


def latest(data_dir, ro=False):
    """Newest version of every finding (list, by finding id). Each row shows sample_size AND denominator."""
    con = connect(data_dir, ro)
    try:
        return _rows(con, "SELECT f.* FROM finding_version f JOIN (SELECT finding_id, MAX(version) v FROM finding_version "
                          "GROUP BY finding_id) m ON f.finding_id=m.finding_id AND f.version=m.v ORDER BY f.finding_id")
    finally:
        con.close()


def diff(old, new):
    """Field-by-field change between two version rows (old may be None for a first version). -> {field: [old, new]}."""
    return {k: [None if old is None else old.get(k), new.get(k)] for k in FIELDS if old is None or old.get(k) != new.get(k)}


def mark_review(data_dir):
    con = connect(data_dir)
    try:
        t = time.time()
        con.execute("INSERT INTO review_mark (reviewed_utc) VALUES (?)", (t,))
        con.commit()
        return t
    finally:
        con.close()


def changes_since_review(data_dir, ro=False):
    """What changed since the last review mark (or since the start when there is none): every version added after it, with its diff."""
    con = connect(data_dir, ro)
    try:
        r = con.execute("SELECT MAX(reviewed_utc) FROM review_mark").fetchone()[0]
        since = r or 0.0
        out = []
        for row in _rows(con, "SELECT * FROM finding_version WHERE created_utc>? ORDER BY finding_id, version", (since,)):
            prev = con.execute("SELECT * FROM finding_version WHERE finding_id=? AND version=?",
                               (row["finding_id"], row["version"] - 1)).fetchone()
            out.append({"finding_id": row["finding_id"], "version": row["version"], "new_finding": prev is None,
                        "changed": diff(dict(prev) if prev else None, row)})
        return {"tool": VERSION, "since_utc": r, "since": "last review" if r else "the beginning (no review mark yet)", "changes": out}
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("list", "history", "changes", "review", "add"))
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--data")
    ap.add_argument("--finding", help="add: the finding id to add a NEW VERSION to (omit for a new finding)")
    a = ap.parse_args(argv)
    d = find_data_dir(a.data)
    if a.cmd == "list":
        res = {"tool": VERSION, "findings": latest(d)}
    elif a.cmd == "history":
        res = {"tool": VERSION, "versions": history(d, a.arg)} if a.arg else {"error": "give a finding id"}
    elif a.cmd == "changes":
        res = changes_since_review(d)
    elif a.cmd == "review":
        res = {"tool": VERSION, "reviewed_utc": mark_review(d)}
    else:
        try:
            with open(a.arg, encoding="utf-8") as fh:
                res = add_version(d, json.load(fh), a.finding)
        except (OSError, TypeError, ValueError) as e:
            res = {"ok": False, "error": "cannot read the json file: %s" % e}
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    sys.exit(main())
