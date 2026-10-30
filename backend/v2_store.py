"""v2_store.py - Part 14: COLLECTORS 1 of 5 - the storage base (its OWN database file v2_market.db). Nothing collects yet; this only builds the safe place to put data.
Rules (owner + README4): separate file, never the trading databases; 300 MB hard cap measured as USED pages (freed pages do not count); when 100% is reached
writing PAUSES (nothing is thrown away to make room silently beyond the purge rules); purge runs in ONE transaction (all or nothing); cohort_official and gap_log are
NEVER purged; a past cohort is NEVER overwritten (INSERT OR IGNORE, the first saved row stays); every insert is idempotent, so a restart cannot duplicate rows.
Tables: ticker_snapshot (every 5 min top gainers / losers), cohort_official (daily 00:00 UTC top 5 + 5, kind = GAINER / LOSER, source AUTHENTIC or PROXY),
candles (3m / 5m closed candles), gap_log (missing intervals are RECORDED, never invented), collector_health (status lines), meta (schema, provisional flag).
The schema is PROVISIONAL until the owner's inventory is reviewed (meta.schema_provisional = 1); a change = a new schema_version, old rows are never rewritten.
This module has no network, no signing and no order code (guard test). Run (Termux, optional):  python3 backend/v2_store.py [--data DIR]  -> creates/checks v2_market.db, prints usage.
Tests: python3 test/test_v2_store.py"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_inventory as I

VERSION = "v2_store 1 (Part 14)"
DB_NAME = "v2_market.db"
SCHEMA_VERSION = 1
CAP_BYTES = 300 * 1024 * 1024
WARN_PCT, PAUSE_PCT, PURGE_TO_PCT = 80.0, 100.0, 80.0
KEEP_DAYS = {"ticker_snapshot": 14, "candles_3m": 14, "candles_5m": 30}
PROTECTED = ("cohort_official", "gap_log")                 # never deleted by any purge
PURGEABLE = ("ticker_snapshot", "candles")
NEVER_USE = ("owl.db", "dual_archive.db", "brain_archive.db", "paper_trades.db")     # trading / archive databases are never this store
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS ticker_snapshot (run_ts INTEGER NOT NULL, symbol TEXT NOT NULL, price REAL, change_pct REAL, volume_usdt REAL, rank_gain INTEGER, rank_loss INTEGER, PRIMARY KEY (run_ts, symbol))",
    "CREATE TABLE IF NOT EXISTS cohort_official (day TEXT NOT NULL, kind TEXT NOT NULL, rank INTEGER NOT NULL, symbol TEXT NOT NULL, open_price REAL, snap_ts INTEGER, source TEXT NOT NULL, PRIMARY KEY (day, kind, rank))",
    "CREATE TABLE IF NOT EXISTS candles (symbol TEXT NOT NULL, interval TEXT NOT NULL, open_ts INTEGER NOT NULL, o REAL, h REAL, l REAL, c REAL, v REAL, PRIMARY KEY (symbol, interval, open_ts))",
    "CREATE TABLE IF NOT EXISTS gap_log (kind TEXT NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL, from_ts INTEGER NOT NULL, to_ts INTEGER NOT NULL, reason TEXT, logged_ts INTEGER, PRIMARY KEY (kind, symbol, interval, from_ts, to_ts))",
    "CREATE TABLE IF NOT EXISTS collector_health (ts INTEGER NOT NULL, status TEXT NOT NULL, note TEXT)",
)


class StoreRefused(Exception):
    """The path is not a safe place for the market store."""


def store_path(data_dir, name=DB_NAME):
    root = os.path.realpath(data_dir)
    if not os.path.isdir(root):
        raise StoreRefused("data folder not found")
    if name in NEVER_USE or os.path.basename(name) != name or not name.startswith("v2_"):
        raise StoreRefused("not a V2 store name: %s" % name)
    path = os.path.join(root, name)
    if os.path.islink(path) or os.path.realpath(path) != path:
        raise StoreRefused("the store file must not be a link")
    return path


def open_store(data_dir, name=DB_NAME):
    con = sqlite3.connect(store_path(data_dir, name), timeout=10, isolation_level=None)
    con.execute("PRAGMA busy_timeout=10000")
    con.execute("PRAGMA journal_mode=WAL")
    for sql in SCHEMA:
        con.execute(sql)
    con.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    con.execute("INSERT OR IGNORE INTO meta VALUES ('schema_provisional', '1')")
    return con


def used_bytes(con):
    """USED pages only: pages freed by a purge are reusable and do not count against the cap."""
    pages, free, size = (con.execute("PRAGMA %s" % p).fetchone()[0] for p in ("page_count", "freelist_count", "page_size"))
    return (pages - free) * size


def usage(con, cap=CAP_BYTES):
    used = used_bytes(con)
    pct = 100.0 * used / cap
    return {"used_bytes": used, "cap_bytes": cap, "used_pct": round(pct, 2), "state": "FULL_PAUSED" if pct >= PAUSE_PCT else ("WARN" if pct >= WARN_PCT else "OK"),
            "rows": {t: con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in ("ticker_snapshot", "cohort_official", "candles", "gap_log")}}


def can_write(con, cap=CAP_BYTES):
    return usage(con, cap)["state"] != "FULL_PAUSED"


def _insert(con, sql, args, cap):
    """One idempotent insert. False = ignored (already there) OR paused because the cap is reached; the caller reads usage() to tell which."""
    if not can_write(con, cap):
        return False
    return con.execute(sql, args).rowcount == 1


def add_snapshot(con, run_ts, symbol, price, change_pct, volume_usdt, rank_gain=None, rank_loss=None, cap=CAP_BYTES):
    return _insert(con, "INSERT OR IGNORE INTO ticker_snapshot VALUES (?,?,?,?,?,?,?)", (int(run_ts), symbol, price, change_pct, volume_usdt, rank_gain, rank_loss), cap)


def add_cohort(con, day, kind, rank, symbol, open_price, snap_ts, source, cap=CAP_BYTES):
    """Official cohort row. The FIRST saved row of (day, kind, rank) stays for ever; a second call never changes it."""
    if kind not in ("GAINER", "LOSER") or source not in ("AUTHENTIC", "PROXY"):
        raise ValueError("kind must be GAINER / LOSER and source AUTHENTIC / PROXY")
    return _insert(con, "INSERT OR IGNORE INTO cohort_official VALUES (?,?,?,?,?,?,?)", (day, kind, int(rank), symbol, open_price, snap_ts, source), cap)


def add_candle(con, symbol, interval, open_ts, o, h, l, c, v, cap=CAP_BYTES):
    if interval not in ("3m", "5m"):
        raise ValueError("interval must be 3m or 5m")
    return _insert(con, "INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?,?,?)", (symbol, interval, int(open_ts), o, h, l, c, v), cap)


def add_gap(con, kind, symbol, interval, from_ts, to_ts, reason, logged_ts):
    """A gap is written even when the store is full (it is tiny and it is the truth about missing data)."""
    return con.execute("INSERT OR IGNORE INTO gap_log VALUES (?,?,?,?,?,?,?)", (kind, symbol, interval, int(from_ts), int(to_ts), reason, int(logged_ts))).rowcount == 1


def add_health(con, ts, status, note=""):
    con.execute("INSERT INTO collector_health VALUES (?,?,?)", (int(ts), status, str(note)[:200]))
    con.execute("DELETE FROM collector_health WHERE rowid NOT IN (SELECT rowid FROM collector_health ORDER BY ts DESC, rowid DESC LIMIT 500)")


def purge(con, now_ts, cap=CAP_BYTES):
    """Retention purge in ONE transaction (all or nothing). Then, if the store is still above PURGE_TO_PCT, the OLDEST purgeable rows go first, in batches,
    until it is back under it. cohort_official and gap_log are never touched. Returns counts per table."""
    day = 86400
    out = {"ticker_snapshot": 0, "candles": 0}
    con.execute("BEGIN IMMEDIATE")
    try:
        out["ticker_snapshot"] += con.execute("DELETE FROM ticker_snapshot WHERE run_ts < ?", (now_ts - KEEP_DAYS["ticker_snapshot"] * day,)).rowcount
        for iv, key in (("3m", "candles_3m"), ("5m", "candles_5m")):
            out["candles"] += con.execute("DELETE FROM candles WHERE interval = ? AND open_ts < ?", (iv, now_ts - KEEP_DAYS[key] * day)).rowcount
        guard = 0
        while 100.0 * used_bytes(con) / cap > PURGE_TO_PCT and guard < 1000:
            guard += 1
            n = con.execute("DELETE FROM ticker_snapshot WHERE rowid IN (SELECT rowid FROM ticker_snapshot ORDER BY run_ts LIMIT 500)").rowcount
            out["ticker_snapshot"] += n
            if not n:
                m = con.execute("DELETE FROM candles WHERE rowid IN (SELECT rowid FROM candles ORDER BY open_ts LIMIT 500)").rowcount
                out["candles"] += m
                if not m:
                    break
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl market store: create / check v2_market.db (no collecting)")
    ap.add_argument("--data")
    a = ap.parse_args(argv)
    try:
        con = open_store(I.find_data_dir(a.data))
    except (StoreRefused, sqlite3.Error) as e:
        print("STOP:", e)
        return 1
    u = usage(con)
    print("Market store ready: %s | used %.2f%% of %d MB | %s | rows %s" % (DB_NAME, u["used_pct"], CAP_BYTES // 1048576, u["state"], u["rows"]))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
