"""recovered_bot/db.py

Native Python sqlite3, crash-safe replacement for two things app.py used
to keep in fragile form:

  1. `sent_signals` - a plain in-RAM set. Lost on every restart, so a
     scanner replay right after a crash/restart could re-open a duplicate
     trade for a signal that was already acted on seconds before the
     process died.
  2. `signal_log.py` - a whole-file JSON dump/load. Every record() call
     rewrote the ENTIRE signal history to disk; a process kill mid-write
     (low battery, VPS OOM-kill, `systemctl restart`) can leave a
     half-written file that fails json.load() on the next boot and
     silently loses the whole history, not just the newest entry.

Two tables, both crash-safe via sqlite's own WAL journal (a killed
process leaves the last COMMITted row intact - it can't produce a
half-written row the way a whole-file JSON rewrite can):

  - `signals`     one row per accepted signal, same fields signal_log.py
                   used to store - powers the Signals screen
                   (GET /api/signals). Capped at MAX_SIGNAL_HISTORY rows,
                   oldest dropped first, exactly like signal_log.py's
                   in-RAM cap did.
  - `idempotency`  dedup guard only: one row per signal_key
                   ("{symbol}_{signal.signal_time}") ever accepted.
                   Survives a restart, unlike the old RAM set - a
                   post-crash replay of the same closed candle is
                   recognized and skipped instead of re-opening a trade.

Also owns the `positions` table (added this round): paper_trader.py's
open positions, which used to live in a whole-file positions.json
rewritten via json.dump() on EVERY monitor-loop tick (once a second,
every open position, unconditionally) - a real disk-I/O spike on a
small VPS as the open-position count grows, and a Kivy-app-style
crash-unsafe whole-file rewrite (see the signal_log.py rationale
above - a killed process mid-write could lose ALL open positions, not
just the newest change).

  - `positions`      one row per OPEN position, id = paper_trader's own
                       trade_id, `data` = that position's full dict as
                       JSON. save_positions() below is a per-row
                       INSERT...ON CONFLICT DO UPDATE (only the changed
                       rows' pages touch disk, under WAL) plus a DELETE
                       for any id no longer open - NOT a rewrite of
                       every row's content into a fresh file each call.
  - `position_meta`  single key/value row (`next_id`) - the position-id
                       counter, previously also inside positions.json.

A pre-existing positions.json (installs from before this round) is
imported once via migrate_positions_json_if_needed() so no trade open
at upgrade time is lost, then the old file is renamed *.migrated so
this never re-imports it.

One shared sqlite3 connection (check_same_thread=False) guarded by a
single module-level lock - simplest correct thing for a single process
with a handful of writer threads (poll loop, top-up scan - now removed -
and the paper-trade monitor thread never wrote here anyway). WAL mode
lets readers (the FastAPI /api/signals handler, running in a different
thread via asyncio.to_thread if ever needed) proceed without blocking a
concurrent writer.
"""
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

_lock = threading.Lock()
_conn = None

MAX_SIGNAL_HISTORY = 3000         # was 300 (~2 days) - keep ~a month so Yesterday / older days stay visible
IDEMPOTENCY_MAX_AGE_SEC = 24 * 3600   # a signal_key encodes its own candle-close time - never legitimately repeats
IDEMPOTENCY_MAX_ROWS = 2000
IST_OFFSET = timedelta(hours=5, minutes=30)

# backend/recovered_bot/db.py -> parent.parent is backend/ - matches
# api_server.py's own DATA_DIR (os.path.join(os.path.dirname(__file__), "data")).
_DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_DEFAULT_PATH = os.path.join(_DEFAULT_DIR, "owl.db")


def init(path=None):
    """Call once at startup (api_server.py's on_startup, alongside
    settings_store.init()/trade_store.init()/etc). Safe to call more than
    once - a second call is a no-op if a connection is already open.
    path defaults to backend/data/owl.db, same directory every other
    *_store module already uses."""
    global _conn
    with _lock:
        if _conn is not None:
            return
        target = path or _DEFAULT_PATH
        os.makedirs(os.path.dirname(target), exist_ok=True)
        _conn = sqlite3.connect(target, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _create_tables_locked()


def _create_tables_locked():
    """Caller must already hold _lock (or be inside init(), before any
    other thread can reach _conn)."""
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_key TEXT NOT NULL,
            signal_no INTEGER,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            entry_price REAL,
            stop_loss REAL,
            tp1 REAL, tp2 REAL, tp3 REAL, tp4 REAL,
            signal_time TEXT,
            ist_time_str TEXT,
            date_str TEXT,
            recorded_at REAL,
            opened INTEGER NOT NULL DEFAULT 0,
            skip_reason TEXT
        )
    """)
    # Signals remember the timeframe / leverage / mode they were created
    # under, so old cards never relabel when settings change later.
    # Older databases get the columns added; their old rows stay NULL
    # (the app then shows no label instead of a wrong one).
    _have = {r[1] for r in _conn.execute("PRAGMA table_info(signals)").fetchall()}
    for _col, _typ in (("timeframe", "TEXT"), ("leverage", "INTEGER"), ("mode", "TEXT"), ("bot", "TEXT")):
        if _col not in _have:
            _conn.execute(f"ALTER TABLE signals ADD COLUMN {_col} {_typ}")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_id ON signals(id)")
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS idempotency (
            signal_key TEXT PRIMARY KEY,
            first_seen_ts REAL NOT NULL
        )
    """)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS position_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    _conn.commit()


def _ensure_init():
    """Self-locating safety net (same pattern the old idempotency.py used)
    so a forgotten init() wiring call never crashes the scan loop - it
    just falls back to the default backend/data/owl.db path."""
    if _conn is None:
        init()


# ------------------------------------------------------------ idempotency --

def is_duplicate(signal_key):
    """True if this exact signal_key (symbol + candle-close signal_time)
    has already been marked processed - in THIS run or any previous one,
    since it's on disk now instead of a RAM set. Replaces
    `sig_key in sent_signals`."""
    _ensure_init()
    with _lock:
        row = _conn.execute(
            "SELECT 1 FROM idempotency WHERE signal_key = ?", (signal_key,)
        ).fetchone()
    return row is not None


def mark_processed(signal_key):
    """Records signal_key as handled, so a duplicate delivery (restart
    replay, overlapping poll cycle, reconnect catch-up) is recognized
    next time - including across a restart, which the old RAM set could
    never do. Idempotent: marking the same key twice is a harmless no-op.
    Replaces `sent_signals.add(sig_key)`.
    NOTE: kept for backward compat, but has a TOCTOU race when paired with
    a separate is_duplicate() check (two threads can both see False before
    either calls this). New call sites should use claim_signal() instead,
    which does the check-and-mark as one atomic step."""
    _ensure_init()
    with _lock:
        _conn.execute(
            "INSERT OR IGNORE INTO idempotency (signal_key, first_seen_ts) VALUES (?, ?)",
            (signal_key, time.time()),
        )
        _prune_idempotency_locked()
        _conn.commit()


def claim_signal(signal_key):
    """DUPLICATE-TRADE RACE FIX: atomically claims signal_key in one step -
    returns True only for the caller that actually wins the insert (i.e.
    the first to process this exact symbol+candle-close signal), False for
    every other caller (another thread in the same poll cycle, an
    overlapping watchlist scan, a restart replay).

    Replaces the old two-step `if db.is_duplicate(key): return` then
    `db.mark_processed(key)` pattern, which had a real TOCTOU window: two
    threads racing through poll_klines() on the same symbol could both
    read is_duplicate() == False before either one reached mark_processed(),
    and both would then proceed to open a trade for the same signal.

    idempotency.signal_key is already the table's PRIMARY KEY, so a single
    `INSERT OR IGNORE` is atomic under the module lock and sqlite's own
    row-uniqueness enforcement - cursor.rowcount is 1 only for the caller
    whose INSERT actually happened (won the race), 0 for every caller that
    lost it (the row already existed)."""
    _ensure_init()
    with _lock:
        cur = _conn.execute(
            "INSERT OR IGNORE INTO idempotency (signal_key, first_seen_ts) VALUES (?, ?)",
            (signal_key, time.time()),
        )
        won = cur.rowcount == 1
        _prune_idempotency_locked()
        _conn.commit()
    return won


def _prune_idempotency_locked():
    """Caller must already hold _lock. Age-based prune first (safe by
    construction - see IDEMPOTENCY_MAX_AGE_SEC), then a hard row-count cap
    (oldest-first) as a pure housekeeping ceiling."""
    cutoff = time.time() - IDEMPOTENCY_MAX_AGE_SEC
    _conn.execute("DELETE FROM idempotency WHERE first_seen_ts < ?", (cutoff,))
    row = _conn.execute("SELECT COUNT(*) FROM idempotency").fetchone()
    count = row[0] if row else 0
    if count > IDEMPOTENCY_MAX_ROWS:
        _conn.execute(
            """
            DELETE FROM idempotency WHERE signal_key IN (
                SELECT signal_key FROM idempotency ORDER BY first_seen_ts ASC LIMIT ?
            )
            """,
            (count - IDEMPOTENCY_MAX_ROWS,),
        )


# ---------------------------------------------------------------- signals --

def record_signal(signal, symbol, opened, skip_reason=None, bot="b1"):
    """Drop-in replacement for signal_log.record() - same call site, same
    signature, same semantics (called once per generated signal, right
    after Telegram send), just backed by a sqlite INSERT instead of a
    whole-file JSON rewrite."""
    _ensure_init()
    try:
        utc_dt = datetime.strptime(signal.signal_time, "%Y-%m-%d %H:%M:%S")
    except Exception:
        utc_dt = datetime.now(timezone.utc)
    ist_dt = utc_dt + IST_OFFSET
    signal_key = f"{symbol}_{signal.signal_time}"
    # Snapshot the settings in force RIGHT NOW (creation time).
    try:
        from . import settings_store
        _live = bool(settings_store.get("live_trading_enabled", False))
        _tf = settings_store.get("timeframe", None)
        _lev = settings_store.get("live_leverage" if _live else "leverage", None)
        _lev = int(_lev) if _lev is not None else None
        _mode = "LIVE" if _live else "PAPER"
    except Exception:
        _tf, _lev, _mode = None, None, None
    with _lock:
        _conn.execute(
            """
            INSERT INTO signals (
                signal_key, signal_no, symbol, action, entry_price, stop_loss,
                tp1, tp2, tp3, tp4, signal_time, ist_time_str, date_str,
                recorded_at, opened, skip_reason, timeframe, leverage, mode, bot
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_key, getattr(signal, "signal_no", None), symbol, signal.action,
                signal.entry_price, signal.stop_loss,
                signal.tp1, signal.tp2, signal.tp3, signal.tp4,
                signal.signal_time, ist_dt.strftime("%d %b, %I:%M %p"), (ist_dt - timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d"),
                time.time(), 1 if opened else 0, skip_reason, _tf, _lev, _mode,
                "b2" if str(bot or "b1").lower() == "b2" else "b1",
            ),
        )
        # Same cap signal_log.py enforced (most-recent MAX_SIGNAL_HISTORY kept) -
        # keeps the table (and the /api/signals payload) from growing forever.
        _conn.execute(
            """
            DELETE FROM signals WHERE id NOT IN (
                SELECT id FROM signals ORDER BY id DESC LIMIT ?
            )
            """,
            (MAX_SIGNAL_HISTORY,),
        )
        _conn.commit()


def count_signals_today(mode=None, since_ts=0.0):
    """Signals recorded since since_ts (the trading-day start); mode='LIVE' / 'PAPER' limits it to that mode."""
    _ensure_init()
    try:
        with _lock:
            if mode:
                r = _conn.execute(
                    "SELECT COUNT(*) FROM signals WHERE recorded_at >= ? AND UPPER(COALESCE(mode,'')) = ? "
                    "AND (bot IS NULL OR bot != 'b2')", (float(since_ts), str(mode).upper())).fetchone()
            else:
                r = _conn.execute(
                    "SELECT COUNT(*) FROM signals WHERE recorded_at >= ? AND (bot IS NULL OR bot != 'b2')",
                    (float(since_ts),)).fetchone()
        return int(r[0] or 0)
    except Exception:
        return 0


def get_recent_signals(limit=100, bot="b1", mode=None):
    """Most-recent-first list of dicts - same shape signal_log.get_recent()
    returned, so GET /api/signals needs no response-shape change, only its
    import/call site swapped."""
    _ensure_init()
    with _lock:
        rows = _conn.execute(
            """
            SELECT signal_no, symbol, action, entry_price, stop_loss,
                   tp1, tp2, tp3, tp4, signal_time, ist_time_str, date_str,
                   recorded_at, opened, skip_reason, timeframe, leverage, mode
            FROM signals WHERE {where} ORDER BY id DESC LIMIT ?
            """.format(where=("bot = 'b2'" if str(bot or "b1").lower() == "b2" else "(bot IS NULL OR bot != 'b2')")
                       + (" AND UPPER(COALESCE(mode,'')) = '%s'" % ("LIVE" if str(mode).upper() == "LIVE" else "PAPER") if mode else "")),
            (limit,),
        ).fetchall()
    return [
        {
            "signal_no": r[0], "symbol": r[1], "action": r[2],
            "entry_price": r[3], "stop_loss": r[4],
            "tp1": r[5], "tp2": r[6], "tp3": r[7], "tp4": r[8],
            "signal_time": r[9], "ist_time_str": r[10], "date_str": r[11],
            "recorded_at": r[12], "opened": bool(r[13]), "skip_reason": r[14],
            "timeframe": r[15], "leverage": r[16], "mode": r[17],
        }
        for r in rows
    ]


# --------------------------------------------------------------- positions --

def load_positions():
    """Returns (positions_dict, next_id) - positions_dict keyed by int
    trade_id, same shape paper_trader.py's in-RAM `_positions` always was.
    Called once at startup (paper_trader.init()) to restore whatever was
    open before the process was last killed/restarted."""
    _ensure_init()
    with _lock:
        rows = _conn.execute("SELECT id, data FROM positions").fetchall()
        meta_row = _conn.execute(
            "SELECT value FROM position_meta WHERE key = 'next_id'"
        ).fetchone()
    positions = {}
    for pid, data in rows:
        try:
            positions[int(pid)] = json.loads(data)
        except Exception:
            # A single corrupt row (shouldn't happen under WAL, but never
            # let one bad row take down startup) is just dropped - unlike
            # the old whole-file JSON, every OTHER position is unaffected.
            continue
    try:
        next_id = int(meta_row[0]) if meta_row else 1
    except (TypeError, ValueError):
        next_id = 1
    if positions:
        next_id = max(next_id, max(positions.keys()) + 1)
    return positions, max(1, next_id)


def save_positions(positions, next_id):
    """Sync the `positions` table to exactly match `positions` (dict of
    trade_id -> position dict, paper_trader.py's `_positions`): upserts
    every id present, deletes any row for an id no longer in it. This is
    the replacement for paper_trader.py's old _save() - called on the
    same cadence (every monitor-loop tick, ~1/s, plus every open/close/
    SL-move) but each call only touches the rows that actually changed,
    under one transaction, instead of serializing the whole dict to a
    fresh JSON string and rewriting an entire file from byte 0 every
    time. Safe to call with an empty dict (clears the table - see
    paper_trader.reset())."""
    _ensure_init()
    now = time.time()
    with _lock:
        try:
            existing = {r[0] for r in _conn.execute("SELECT id FROM positions").fetchall()}
            keep = set()
            for pid, pos in positions.items():
                pid = int(pid)
                keep.add(pid)
                _conn.execute(
                    """
                    INSERT INTO positions (id, data, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
                    """,
                    (pid, json.dumps(pos, default=str), now),
                )
            stale = existing - keep
            for pid in stale:
                _conn.execute("DELETE FROM positions WHERE id = ?", (pid,))
            _conn.execute(
                """
                INSERT INTO position_meta (key, value) VALUES ('next_id', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(int(next_id)),),
            )
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise


def migrate_positions_json_if_needed(json_path):
    """One-time upgrade path: pre-SQLite installs kept open positions in a
    whole-file positions.json (see module docstring). If the `positions`
    table is still empty AND that old file exists, import it once so no
    trade that was open at upgrade time is lost, then rename the old file
    to `<path>.migrated` so this never runs again (and the raw JSON stays
    around as a recovery backup instead of being deleted).
    Safe/idempotent to call every startup - a no-op once migrated."""
    _ensure_init()
    with _lock:
        row = _conn.execute("SELECT COUNT(*) FROM positions").fetchone()
        already_has_rows = bool(row and row[0])
    if already_has_rows or not json_path or not os.path.exists(json_path):
        return False
    try:
        with open(json_path, "r") as f:
            saved = json.load(f)
        positions = {int(k): v for k, v in (saved.get("positions") or {}).items()}
        next_id = int(saved.get("next_id", 1) or 1)
    except Exception:
        # Corrupt/unreadable old file - nothing to migrate, but also
        # nothing worth crashing startup over.
        return False
    if positions:
        save_positions(positions, next_id)
    try:
        os.rename(json_path, json_path + ".migrated")
    except Exception:
        pass
    return True
