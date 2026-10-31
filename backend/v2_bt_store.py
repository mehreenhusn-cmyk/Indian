"""v2_bt_store.py - Part 84a: BRAIN TRADER 1 of 8 (backend). The OWN database file v2_brain_trader.db (never the market store, never a bot / trading database).
What it holds: the Brain Trader VERSIONS (BT-01, BT-02...), every DECISION (OPEN_LONG / OPEN_SHORT / WAIT / SKIP / NO_OPINION), every PAPER trade open and close, all net of fee and slippage.
Rules (README5): the ledger is append-only (SQLite triggers block UPDATE and DELETE); a changed rule = a new version, old rows are never rewritten.
Three SOURCES are kept apart and never added together: REPLAY (past candles), PAPER (live market, pretend money), SHADOW (live market, no orders). LIVE is LOCKED: it is refused here.
NO LOOK-AHEAD: a decision at candle close T may only use data up to T (data_upto_ts <= close_ts), else it is refused.
A signal can be saved only once per version / source / coin / timeframe / candle / side (a second try returns False: the duplicate-signal guard).
No network, no order code, no trading import. Run (Termux, optional):  python3 backend/v2_bt_store.py [--data DIR]  -> prints the status (counts only).
Later Parts add the explorer (85), screens (86-87), review (88) on top of these tables."""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_store as S

VERSION = "v2_bt_store 1 (Part 84a)"
DB_NAME = "v2_brain_trader.db"
SCHEMA_VERSION = 1
SOURCES = ("REPLAY", "PAPER", "SHADOW")                 # LIVE is not here on purpose: locked until the Graduation gate and the owner's own OK
SAMPLES = ("TRAIN", "HOLDOUT", "NEW")                   # NEW = data after the rule was frozen
DECISIONS = ("OPEN_LONG", "OPEN_SHORT", "WAIT", "SKIP", "NO_OPINION")      # WAIT = not now: the snapshot holds wait_for (the condition) and max_wait_candles
SIDES = ("LONG", "SHORT")
EXIT_REASONS = ("TARGET", "STOP", "TIME", "CLOSE_RULE", "KILL_SWITCH")
REQUIRED_DEF = ("indicators", "entry", "stop", "target", "max_hold", "fee_pct", "slippage_pct", "size_usdt")
_AO = "CREATE TRIGGER IF NOT EXISTS %s_no_%s BEFORE %s ON %s BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END"
TABLES = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS bt_version (version TEXT PRIMARY KEY, definition TEXT NOT NULL, created_ts INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS bt_decision (version TEXT NOT NULL, source TEXT NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL, close_ts INTEGER NOT NULL, side TEXT NOT NULL, "
    "decision TEXT NOT NULL, sample TEXT NOT NULL, state TEXT, reason TEXT, snapshot TEXT, data_upto_ts INTEGER NOT NULL, created_ts INTEGER NOT NULL, "
    "PRIMARY KEY (version, source, symbol, interval, close_ts, side))",
    "CREATE TABLE IF NOT EXISTS bt_trade_open (trade_id TEXT PRIMARY KEY, version TEXT NOT NULL, source TEXT NOT NULL, symbol TEXT NOT NULL, interval TEXT NOT NULL, side TEXT NOT NULL, "
    "open_ts INTEGER NOT NULL, entry REAL NOT NULL, sl REAL NOT NULL, tp REAL NOT NULL, size_usdt REAL NOT NULL, sample TEXT NOT NULL, created_ts INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS bt_trade_close (trade_id TEXT PRIMARY KEY, close_ts INTEGER NOT NULL, exit_price REAL NOT NULL, exit_reason TEXT NOT NULL, gross_pct REAL NOT NULL, "
    "fee_pct REAL NOT NULL, slip_pct REAL NOT NULL, net_pct REAL NOT NULL, net_usdt REAL NOT NULL, mfe_pct REAL, mae_pct REAL, hold_candles INTEGER NOT NULL, created_ts INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS guard_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, ts INTEGER NOT NULL)",          # the ONLY mutable table: switches and limits
    "CREATE TABLE IF NOT EXISTS guard_log (ts INTEGER NOT NULL, event TEXT NOT NULL, detail TEXT)",
)
TRIGGERS = tuple(_AO % (t, op.lower(), op, t) for t in ("bt_version", "bt_decision", "bt_trade_open", "bt_trade_close", "guard_log") for op in ("UPDATE", "DELETE"))


def db_path(data_dir):
    return S.store_path(data_dir, DB_NAME)


def connect(data_dir):
    """Opens (and, only here, creates) the Brain Trader file. Never touches v2_market.db or any trading database."""
    con = sqlite3.connect(db_path(data_dir), timeout=10)
    for q in TABLES + TRIGGERS:
        con.execute(q)
    con.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    con.commit()
    return con


def open_ro(data_dir):
    """Read-only connection or None when the file does not exist (a read never creates it)."""
    path = db_path(data_dir)
    if not os.path.isfile(path):
        return None
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    con.execute("PRAGMA query_only=ON")
    return con


def _need(cond, text):
    if not cond:
        raise ValueError(text)


def register_version(con, version, definition, now=None):
    """Saves a version once (BT-01...). A missing part = ValueError. The same name again keeps the FIRST text: a rule change needs a NEW version name."""
    _need(isinstance(version, str) and version.startswith("BT-"), "version must look like BT-01")
    missing = [k for k in REQUIRED_DEF if definition.get(k) in (None, "", [], {})]
    _need(not missing, "definition is not complete, missing: " + ", ".join(missing))
    con.execute("INSERT OR IGNORE INTO bt_version VALUES (?,?,?)", (version, json.dumps(definition, sort_keys=True), int(time.time() if now is None else now)))
    con.commit()


def latest_version(con):
    r = con.execute("SELECT version FROM bt_version ORDER BY created_ts DESC, version DESC LIMIT 1").fetchone()
    return r[0] if r else None


def _known(con, version):
    return con.execute("SELECT 1 FROM bt_version WHERE version=?", (version,)).fetchone() is not None


def add_decision(con, rec, now=None):
    """One decision at one closed candle. -> True when new, False when that signal was already saved (duplicate guard). Look-ahead, LIVE or an unknown version = ValueError."""
    _need(rec.get("source") in SOURCES, "source must be REPLAY, PAPER or SHADOW (LIVE is locked)")
    _need(rec.get("decision") in DECISIONS and rec.get("side") in SIDES and rec.get("sample") in SAMPLES, "bad decision, side or sample")
    _need(_known(con, rec.get("version")), "no saved definition for this version")
    _need(int(rec["data_upto_ts"]) <= int(rec["close_ts"]), "look-ahead refused: the data goes past the candle close")
    cur = con.execute("INSERT OR IGNORE INTO bt_decision VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (rec["version"], rec["source"], rec["symbol"], rec["interval"], int(rec["close_ts"]), rec["side"], rec["decision"], rec["sample"], rec.get("state"),
                       rec.get("reason"), json.dumps(rec.get("snapshot") or {}, sort_keys=True), int(rec["data_upto_ts"]), int(time.time() if now is None else now)))
    con.commit()
    return cur.rowcount == 1


def trade_id(version, source, symbol, interval, side, open_ts):
    return "|".join((version, source, symbol, interval, side, str(int(open_ts))))


def open_trade(con, rec, now=None):
    """A paper trade opens. SL and TP must sit on the right side of the entry. -> the trade id, or None when that trade already exists."""
    _need(rec.get("source") in SOURCES and rec.get("side") in SIDES and rec.get("sample") in SAMPLES, "bad source, side or sample (LIVE is locked)")
    _need(_known(con, rec.get("version")), "no saved definition for this version")
    e, sl, tp = float(rec["entry"]), float(rec["sl"]), float(rec["tp"])
    ok = (sl < e < tp) if rec["side"] == "LONG" else (tp < e < sl)
    _need(ok and float(rec["size_usdt"]) > 0, "SL / TP are on the wrong side of the entry, or size is not above 0")
    tid = trade_id(rec["version"], rec["source"], rec["symbol"], rec["interval"], rec["side"], rec["open_ts"])
    cur = con.execute("INSERT OR IGNORE INTO bt_trade_open VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (tid, rec["version"], rec["source"], rec["symbol"], rec["interval"], rec["side"], int(rec["open_ts"]), e, sl, tp, float(rec["size_usdt"]), rec["sample"],
                       int(time.time() if now is None else now)))
    con.commit()
    return tid if cur.rowcount == 1 else None


def close_trade(con, tid, rec, now=None):
    """A paper trade closes ONCE. Net = gross - fee - slippage (all in percent of the entry); net_usdt = net_pct x size. -> True when new."""
    row = con.execute("SELECT open_ts, size_usdt FROM bt_trade_open WHERE trade_id=?", (tid,)).fetchone()
    _need(row is not None, "this trade was never opened")
    _need(rec.get("exit_reason") in EXIT_REASONS and int(rec["close_ts"]) >= row[0], "bad exit reason, or the close is before the open")
    net = float(rec["gross_pct"]) - float(rec["fee_pct"]) - float(rec["slip_pct"])
    cur = con.execute("INSERT OR IGNORE INTO bt_trade_close VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (tid, int(rec["close_ts"]), float(rec["exit_price"]), rec["exit_reason"], float(rec["gross_pct"]), float(rec["fee_pct"]), float(rec["slip_pct"]), net,
                       net / 100.0 * row[1], rec.get("mfe_pct"), rec.get("mae_pct"), int(rec["hold_candles"]), int(time.time() if now is None else now)))
    con.commit()
    return cur.rowcount == 1


def open_trades(con, source):
    return con.execute("SELECT o.trade_id, o.symbol, o.interval, o.side, o.open_ts FROM bt_trade_open o LEFT JOIN bt_trade_close c ON c.trade_id=o.trade_id "
                       "WHERE o.source=? AND c.trade_id IS NULL ORDER BY o.open_ts", (source,)).fetchall()


def closed_rows(con, source, since_ts=0):
    """[(close_ts, net_usdt)] of ONE source, oldest first. Sources are never mixed."""
    return con.execute("SELECT c.close_ts, c.net_usdt FROM bt_trade_close c JOIN bt_trade_open o ON o.trade_id=c.trade_id WHERE o.source=? AND c.close_ts>=? ORDER BY c.close_ts, c.trade_id",
                       (source, int(since_ts))).fetchall()


def status(data_dir):
    """What a route will show: versions and counts per source. Counts only; sources are never added together."""
    con = open_ro(data_dir)
    if con is None:
        return {"ready": False, "framework": VERSION, "note": "no Brain Trader file yet: nothing has been saved", "live": "LOCKED"}
    try:
        per = {}
        for s in SOURCES:
            d = con.execute("SELECT COUNT(*) FROM bt_decision WHERE source=?", (s,)).fetchone()[0]
            o = con.execute("SELECT COUNT(*) FROM bt_trade_open WHERE source=?", (s,)).fetchone()[0]
            c = con.execute("SELECT COUNT(*) FROM bt_trade_close c JOIN bt_trade_open t ON t.trade_id=c.trade_id WHERE t.source=?", (s,)).fetchone()[0]
            per[s] = {"decisions": d, "opened": o, "closed": c}
        return {"ready": True, "framework": VERSION, "live": "LOCKED", "latest_version": latest_version(con), "per_source": per,
                "note": "paper / replay / shadow are kept apart; nothing here is real money"}
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
