"""v2_scalp_store.py - Part 50: SCALP LAB 1 of 8 (backend). The OWN database file v2_scalp.db of the Scalp Lab (never the market store, never a trading database).
Each CATEGORY has its own definition + version and its own ledger of finished replay records. Categories share the raw candles (read-only, in v2_market.db) but NEVER records, P&L or ids:
the record key holds the category, so the same signal in two categories is two separate lines of two separate ledgers and nothing is added across them.
A definition must name entry, invalidation, stop, exit, max_hold, fees, slippage and window BEFORE any record can be written (README4 9.7: define first, test later).
Records are HYPOTHETICAL replay results (see v2_replay.py): only FINISHED ones are stored (TARGET / STOP / TIME); PENDING and UNAVAILABLE are counted at replay time and never saved as 0.
The ledger is append-only (SQLite triggers block UPDATE and DELETE); a changed rule = a new definition version, old records are never rewritten.
No network, no order code, no trading import. Run (Termux, optional):  python3 backend/v2_scalp_store.py [--data DIR]  -> prints the status. Route: GET /api/v2/scalp_lab (api/v2_data.py)."""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_store as S

VERSION = "v2_scalp_store 1 (Part 50)"
DB_NAME = "v2_scalp.db"
SCHEMA_VERSION = 1
REQUIRED_DEF = ("entry", "invalidation", "stop", "exit", "max_hold", "fees", "slippage", "window")
CATEGORIES = ("EMA_RETEST", "PUMP_DUMP", "SD_BAND", "TSI_MOMENTUM", "Z_BEHAVIOUR", "COMBINED", "QUICK_EXIT", "BRAIN_EXPLORER", "RESULTS")   # the 9 of README4 9.7
FINISHED = ("TARGET", "STOP", "TIME")
SAMPLES = ("TRAIN", "HOLDOUT")
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS category_def (category TEXT NOT NULL, version INTEGER NOT NULL, definition TEXT NOT NULL, created_ts INTEGER NOT NULL, PRIMARY KEY (category, version))",
    "CREATE TABLE IF NOT EXISTS record (category TEXT NOT NULL, version INTEGER NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL, side TEXT NOT NULL, signal_ts INTEGER NOT NULL, "
    "sample TEXT NOT NULL, entry REAL NOT NULL, exit_price REAL NOT NULL, status TEXT NOT NULL, hold_candles INTEGER NOT NULL, gross_pct REAL NOT NULL, net_pct REAL NOT NULL, "
    "PRIMARY KEY (category, version, symbol, interval, side, signal_ts))",
    "CREATE TRIGGER IF NOT EXISTS record_no_update BEFORE UPDATE ON record BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS record_no_delete BEFORE DELETE ON record BEGIN SELECT RAISE(ABORT, 'ledger is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS def_no_update BEFORE UPDATE ON category_def BEGIN SELECT RAISE(ABORT, 'definitions are never rewritten'); END",
)


def db_path(data_dir):
    return S.store_path(data_dir, DB_NAME)


def connect(data_dir):
    """Opens (and, only here, creates) the Scalp Lab file. Never touches v2_market.db."""
    con = sqlite3.connect(db_path(data_dir), timeout=10)
    for q in SCHEMA:
        con.execute(q)
    con.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    con.commit()
    return con


def open_ro(data_dir):
    """Read-only connection or None when the file does not exist (never created by a read)."""
    path = db_path(data_dir)
    if not os.path.isfile(path):
        return None
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    con.execute("PRAGMA query_only=ON")
    return con


def register_category(con, category, version, definition, now=None):
    """Saves a definition once. Missing parts or an unknown category = ValueError. The same version again keeps the FIRST saved text (a rule change needs a new version)."""
    if category not in CATEGORIES:
        raise ValueError("unknown category: %s" % category)
    if not isinstance(version, int) or version < 1:
        raise ValueError("version must be a whole number from 1")
    missing = [k for k in REQUIRED_DEF if not definition.get(k)]
    if missing:
        raise ValueError("definition is not complete, missing: " + ", ".join(missing))
    con.execute("INSERT OR IGNORE INTO category_def (category, version, definition, created_ts) VALUES (?,?,?,?)",
                (category, version, json.dumps(definition, sort_keys=True), int(time.time() if now is None else now)))
    con.commit()


def add_record(con, category, version, rec):
    """One finished replay record. Needs a saved definition. Not finished (PENDING / UNAVAILABLE) = refused. -> True when new, False when the key already existed."""
    if rec.get("status") not in FINISHED or rec.get("sample") not in SAMPLES:
        raise ValueError("only finished records with a TRAIN / HOLDOUT sample are saved")
    if con.execute("SELECT 1 FROM category_def WHERE category=? AND version=?", (category, version)).fetchone() is None:
        raise ValueError("no saved definition for this category and version")
    cur = con.execute("INSERT OR IGNORE INTO record VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (category, version, rec["symbol"], rec["interval"], rec["side"], int(rec["signal_ts"]), rec["sample"], float(rec["entry"]), float(rec["exit_price"]),
                       rec["status"], int(rec["hold_candles"]), float(rec["gross_pct"]), float(rec["net_pct"])))
    con.commit()
    return cur.rowcount == 1


def read_records(con, category, version, sample=None):
    q = "SELECT status, net_pct, gross_pct, hold_candles, sample FROM record WHERE category=? AND version=?"
    a = [category, version]
    if sample:
        q += " AND sample=?"
        a.append(sample)
    return con.execute(q + " ORDER BY signal_ts", a).fetchall()


def status(data_dir):
    """What the route shows: the categories, their versions and record counts (counts only, each category apart, never added together)."""
    con = open_ro(data_dir)
    if con is None:
        return {"ready": False, "framework": VERSION, "note": "no Scalp Lab file yet: nothing has been replayed", "categories_planned": list(CATEGORIES)}
    try:
        rows = con.execute("SELECT d.category, d.version, d.created_ts, (SELECT COUNT(*) FROM record r WHERE r.category=d.category AND r.version=d.version) FROM category_def d ORDER BY d.category, d.version").fetchall()
        return {"ready": True, "framework": VERSION, "categories_planned": list(CATEGORIES),
                "categories": [{"category": r[0], "version": r[1], "saved_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(r[2])), "records": r[3]} for r in rows],
                "note": "hypothetical replay only; each category has its own ledger; counts are never added across categories"}
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    a = ap.parse_args(argv)
    print(json.dumps(status(a.data), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
