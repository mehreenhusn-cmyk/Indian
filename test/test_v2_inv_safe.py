"""Part 1 test: backend/v2_inv_safe.py (safe read-only database opener). Offline, no network, no trading module.
Run:  python3 test/test_v2_inv_safe.py"""
import ast
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_inv_safe as S


def _listing(folder):
    return sorted(os.listdir(folder))


def make_db(path, wal=False, rows=3):
    con = sqlite3.connect(path)
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    for i in range(rows):
        con.execute("INSERT INTO t (v) VALUES (?)", ("row%d" % i,))
    con.commit()
    return con


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2t_")
        self.data = os.path.join(self.dir, "data")
        os.makedirs(self.data)
        self.db = os.path.join(self.data, "a.db")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._sock = socket.socket                      # no network allowed anywhere in this test
        socket.socket = self._no_net
        self.addCleanup(setattr, socket, "socket", self._sock)

    @staticmethod
    def _no_net(*a, **k):
        raise AssertionError("network used")


class Rollback(Base):
    def test_direct_open_reads_and_changes_nothing(self):
        make_db(self.db).close()
        before, files = S.source_fingerprints(self.db), _listing(self.data)
        with S.open_safe(self.db, [self.data]) as d:
            self.assertEqual(d.mode, "direct")
            self.assertFalse(d.snapshot)
            self.assertEqual(d.con.execute("SELECT count(*) FROM t").fetchone()[0], 3)
            self.assertEqual(d.con.execute("SELECT min(id), max(id) FROM t").fetchone(), (1, 3))
            cols = [r[1] for r in d.con.execute("PRAGMA table_info(t)")]
            self.assertEqual(cols, ["id", "v"])
        self.assertEqual(S.source_fingerprints(self.db), before)          # size, mtime, sha256 of db and side files
        self.assertEqual(_listing(self.data), files)                      # no new file next to the source

    def test_every_write_is_denied(self):
        make_db(self.db).close()
        other = os.path.join(self.data, "b.db")
        make_db(other).close()
        bad = ["INSERT INTO t (v) VALUES ('x')", "UPDATE t SET v='y'", "DELETE FROM t", "CREATE TABLE z (a)",
               "DROP TABLE t", "ALTER TABLE t ADD COLUMN q", "ATTACH DATABASE '%s' AS o" % other, "VACUUM",
               "PRAGMA journal_mode=WAL", "PRAGMA writable_schema=1", "PRAGMA user_version=5", "BEGIN", "CREATE INDEX ix ON t(v)",
               "CREATE TEMP TABLE tt (a)"]
        with S.open_safe(self.db, [self.data]) as d:
            for sql in bad:
                with self.assertRaises(sqlite3.Error, msg=sql):
                    d.con.execute(sql)
            with self.assertRaises((sqlite3.Error, AttributeError)):
                d.con.enable_load_extension(True)
                d.con.execute("SELECT load_extension('x')")
            self.assertEqual(d.con.execute("SELECT count(*) FROM t").fetchone()[0], 3)

    def test_hot_journal_goes_to_snapshot(self):
        make_db(self.db).close()
        with open(self.db + "-journal", "wb") as f:
            f.write(b"\x00" * 64)                                         # a non-empty journal = "maybe hot"
        before, files = S.source_fingerprints(self.db), _listing(self.data)
        with S.open_safe(self.db, [self.data]) as d:
            self.assertTrue(d.snapshot)
            self.assertIn("hot journal", d.label())
            self.assertEqual(d.con.execute("SELECT count(*) FROM t").fetchone()[0], 3)
        self.assertEqual(S.source_fingerprints(self.db), before)
        self.assertEqual(_listing(self.data), files)

    def test_empty_journal_is_not_hot(self):
        make_db(self.db).close()
        open(self.db + "-journal", "wb").close()
        with S.open_safe(self.db, [self.data]) as d:
            self.assertEqual(d.mode, "direct")


class Wal(Base):
    def test_wal_with_live_writer_uses_snapshot_and_source_is_untouched(self):
        writer = make_db(self.db, wal=True, rows=5)
        writer.execute("INSERT INTO t (v) VALUES ('late')")
        writer.commit()                                                   # lives only in the -wal file (autocheckpoint off)
        self.assertTrue(os.path.getsize(self.db + "-wal") > 0)
        before, files = S.source_fingerprints(self.db), _listing(self.data)
        d = S.open_safe(self.db, [self.data])
        try:
            self.assertEqual(S.read_header(self.db), "wal")
            self.assertTrue(d.snapshot)
            self.assertIn("WAL", d.label())
            self.assertEqual(d.con.execute("SELECT count(*) FROM t").fetchone()[0], 6)     # sees the row that is only in -wal
            with self.assertRaises(sqlite3.Error):
                d.con.execute("INSERT INTO t (v) VALUES ('x')")
            tmp = d._tmp
            self.assertTrue(os.path.isdir(tmp))
        finally:
            d.close()
        self.assertFalse(os.path.exists(tmp))                              # temp copy removed
        self.assertEqual(S.source_fingerprints(self.db), before)
        self.assertEqual(_listing(self.data), files)
        writer.execute("INSERT INTO t (v) VALUES ('after')")               # the live writer still works
        writer.commit()
        writer.close()

    def test_not_enough_disk_space_refuses(self):
        make_db(self.db, wal=True).close()
        real = shutil.disk_usage
        shutil.disk_usage = lambda p: shutil._ntuple_diskusage(100, 99, 1)
        try:
            with self.assertRaises(S.OpenFailed):
                S.open_safe(self.db, [self.data])
        finally:
            shutil.disk_usage = real


class Paths(Base):
    def test_symlink_escape_is_rejected(self):
        outside = os.path.join(self.dir, "outside")
        os.makedirs(outside)
        secret = os.path.join(outside, "s.db")
        make_db(secret).close()
        link = os.path.join(self.data, "link.db")
        os.symlink(secret, link)
        with self.assertRaises(S.UnsafePath):
            S.open_safe(link, [self.data])
        linkdir = os.path.join(self.data, "dirlink")
        os.symlink(outside, linkdir)
        with self.assertRaises(S.UnsafePath):
            S.open_safe(os.path.join(linkdir, "s.db"), [self.data])

    def test_dotdot_and_outside_paths_are_rejected(self):
        outside = os.path.join(self.dir, "o.db")
        make_db(outside).close()
        with self.assertRaises(S.UnsafePath):
            S.open_safe(os.path.join(self.data, "..", "o.db"), [self.data])
        with self.assertRaises(S.UnsafePath):
            S.open_safe(outside, [self.data])
        with self.assertRaises(S.UnsafePath):
            S.open_safe(self.db, [])
        with self.assertRaises(S.UnsafePath):
            S.open_safe("", [self.data])

    def test_symlink_inside_the_root_is_allowed(self):
        make_db(self.db).close()
        link = os.path.join(self.data, "alias.db")
        os.symlink(self.db, link)
        real, was_link = S.resolve_under(link, [self.data])
        self.assertEqual(real, os.path.realpath(self.db))
        self.assertTrue(was_link)
        with S.open_safe(link, [self.data]) as d:
            self.assertEqual(d.con.execute("SELECT count(*) FROM t").fetchone()[0], 3)

    def test_bad_files_are_refused_with_plain_messages(self):
        with self.assertRaises(S.OpenFailed):
            S.open_safe(os.path.join(self.data, "missing.db"), [self.data])
        junk = os.path.join(self.data, "junk.db")
        with open(junk, "wb") as f:
            f.write(b"password=hunter2 " * 20)
        with self.assertRaises(S.OpenFailed) as cm:
            S.open_safe(junk, [self.data])
        self.assertNotIn("hunter2", str(cm.exception))                     # no content of the file in the message
        empty = os.path.join(self.data, "empty.db")
        open(empty, "wb").close()
        with self.assertRaises(S.OpenFailed):
            S.open_safe(empty, [self.data])
        with self.assertRaises(S.OpenFailed):
            S.open_safe(self.data, [self.data])                             # a folder is not a database


class Isolation(unittest.TestCase):
    def test_module_has_no_network_or_trading_imports(self):
        with open(os.path.join(ROOT, "backend", "v2_inv_safe.py"), encoding="utf-8") as f:
            src = f.read()
        names = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                names.add((n.module or "").split(".")[0])
        banned = {"socket", "urllib", "requests", "http", "httpx", "aiohttp", "ssl", "recovered_bot", "api_server", "api",
                  "smart_brain", "dual_lab", "brain_own", "config", "main", "strategy", "paper_trader", "binance_trader"}
        self.assertEqual(names & banned, set())
        self.assertTrue(names <= {"hashlib", "os", "shutil", "sqlite3", "tempfile"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
