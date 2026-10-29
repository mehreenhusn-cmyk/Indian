"""v2_inv_safe.py - Part 1: SAFE READ-ONLY DATABASE OPENER (used later by the inventory tool, Part 3).

Question it answers: "can I look inside an Owl database without ever changing it, even while the app is writing to it?"
It opens a database for READING ONLY and never touches the source file, its -wal / -shm / -journal files, any setting or any trade.

How (plain Python sqlite3, no network, no trading module, no new library):
  1. The path goes through realpath and must stay under the allowed folders. A symlink that points outside is REJECTED.
  2. The 100-byte file header is read (bytes 18 and 19 = 2 means WAL mode). A rollback-journal database with no hot journal
     is opened straight from the source with "file:...?mode=ro" + PRAGMA query_only=ON + a write-deny authorizer.
  3. A WAL database, or one with a hot (non-empty) -journal file, is NEVER opened from the source: SQLite could create
     or rewrite side files there. The db and its -wal / -shm / -journal are copied to a temp folder (free space checked first)
     and the COPY is opened with the same locks. The report says "copied snapshot" (it can lag a live writer by moments).
  4. The authorizer allows only SELECT / READ / FUNCTION / RECURSIVE and a short list of read-only PRAGMAs. Every write,
     ATTACH, DETACH, extension load, VACUUM, transaction control or other PRAGMA is denied.

Run nothing here by hand: it is a library. Tests: python3 test/test_v2_inv_safe.py
"""
import hashlib
import os
import shutil
import sqlite3
import tempfile

HEADER = b"SQLite format 3\x00"
SIDE = ("-wal", "-shm", "-journal")
OK_PRAGMAS = {"table_info", "table_xinfo", "index_list", "index_info", "index_xinfo", "page_count", "page_size",
              "freelist_count", "schema_version", "user_version"}
OK_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


class UnsafePath(Exception):
    """The path is outside the allowed folders (or a symlink leads outside)."""


class OpenFailed(Exception):
    """The database could not be opened safely. The message is plain text and holds no data from the file."""


def _deny_writes(action, a, b, c, d):
    if action in OK_ACTIONS:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and str(a).lower() in OK_PRAGMAS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def resolve_under(path, roots):
    """Real path of `path`, only if it is inside one of `roots`. Returns (real_path, was_symlink)."""
    if not path or not roots:
        raise UnsafePath("no path or no allowed folder given")
    real = os.path.realpath(path)
    for r in roots:
        rr = os.path.realpath(r)
        try:
            if os.path.commonpath([real, rr]) == rr:
                return real, os.path.islink(path) or real != os.path.abspath(path)
        except ValueError:                                  # different drives
            continue
    raise UnsafePath("path is outside the allowed folders: " + os.path.basename(str(path)))


def read_header(path):
    """Return 'wal' or 'rollback'. Raises OpenFailed for a missing, empty or non-SQLite file."""
    try:
        with open(path, "rb") as f:
            h = f.read(100)
    except OSError:
        raise OpenFailed("file cannot be read")
    if len(h) < 100 or h[:16] != HEADER:
        raise OpenFailed("not a SQLite database")
    return "wal" if (h[18] == 2 or h[19] == 2) else "rollback"


def has_hot_journal(path):
    j = path + "-journal"
    try:
        return os.path.getsize(j) > 0
    except OSError:
        return False


def fingerprint(path):
    """(size, mtime_ns, sha256) of a file, or None when it does not exist. Tests use it to prove the source did not change."""
    try:
        st = os.stat(path)
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                h.update(blk)
        return (st.st_size, st.st_mtime_ns, h.hexdigest())
    except OSError:
        return None


def source_fingerprints(path):
    """Fingerprints of the db and its side files, keyed by suffix ('' for the db itself)."""
    return {s: fingerprint(path + s) for s in ("",) + SIDE}


class SafeDb(object):
    """An open read-only connection. Use as a context manager, or call close()."""

    def __init__(self, con, source, mode, reason, tmpdir):
        self.con, self.source, self.mode, self.reason, self._tmp = con, source, mode, reason, tmpdir

    @property
    def snapshot(self):
        return self.mode == "snapshot"

    def label(self):
        return "copied snapshot (%s)" % self.reason if self.snapshot else "direct read-only"

    def close(self):
        try:
            if self.con is not None:
                self.con.close()
        finally:
            self.con = None
            if self._tmp:
                shutil.rmtree(self._tmp, ignore_errors=True)
                self._tmp = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _lock(con):
    con.execute("PRAGMA query_only=ON")
    con.set_authorizer(_deny_writes)                        # installed AFTER the pragma above, so nothing is left open
    return con


def _snapshot(real, reason, tmp_base):
    names = [real + s for s in ("",) + SIDE if os.path.exists(real + s)]
    need = sum(os.path.getsize(n) for n in names)
    base = tmp_base or tempfile.gettempdir()
    if shutil.disk_usage(base).free < need * 1.2 + (1 << 20):
        raise OpenFailed("not enough free disk space for a snapshot")
    tmp = tempfile.mkdtemp(prefix="v2inv_", dir=base)
    try:
        dst = os.path.join(tmp, "snap.db")
        for n in names:
            shutil.copyfile(n, dst + n[len(real):])
        con = sqlite3.connect("file:%s?mode=rw" % dst, uri=True, timeout=5, isolation_level=None)
        _lock(con).execute("SELECT count(*) FROM sqlite_master").fetchone()
        return SafeDb(con, real, "snapshot", reason, tmp)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise OpenFailed("snapshot could not be opened")


def open_safe(path, roots, tmp_base=None):
    """Open `path` for reading only. `roots` = list of allowed folders. Returns SafeDb. Never writes next to the source."""
    real, _link = resolve_under(path, roots)
    if not os.path.isfile(real):
        raise OpenFailed("file does not exist")
    kind = read_header(real)
    if kind == "wal":
        return _snapshot(real, "WAL database", tmp_base)
    if has_hot_journal(real):
        return _snapshot(real, "hot journal", tmp_base)
    con = None
    try:
        con = sqlite3.connect("file:%s?mode=ro" % real, uri=True, timeout=5, isolation_level=None)
        _lock(con).execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error:
        if con is not None:
            con.close()
        raise OpenFailed("database could not be opened read-only")
    return SafeDb(con, real, "direct", "rollback journal", None)
