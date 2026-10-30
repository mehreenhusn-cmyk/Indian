"""Part 14 test: backend/v2_store.py (Collectors 1 of 5: the separate market store v2_market.db, 300 MB cap, safe purge).
Offline, writes only into temp folders. Main questions: can the store ever be a trading database, can a past cohort be overwritten, can a restart duplicate rows,
does the cap really pause writing, does a failed purge leave half-deleted data, and are cohort_official / gap_log ever purged?
Run:  python3 test/test_v2_store.py"""
import ast
import hashlib
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_store as S

NOW = 1_800_000_000
DAY = 86400


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2s_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._sock = socket.socket
        socket.socket = self._no_net
        self.addCleanup(setattr, socket, "socket", self._sock)
        self.con = S.open_store(self.dir)
        self.addCleanup(self.con.close)

    @staticmethod
    def _no_net(*a, **k):
        raise AssertionError("network used")

    def count(self, table):
        return self.con.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]

    def fill(self, n, start=0, step=300):
        for i in range(n):
            S.add_snapshot(self.con, NOW - (start + i) * step, "S%d" % (i % 40), 1.0, 2.0, 3.0, 1, None)


class Safety(Base):
    def test_schema_and_provisional_flag(self):
        names = {r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"meta", "ticker_snapshot", "cohort_official", "candles", "gap_log", "collector_health"} <= names)
        meta = dict(self.con.execute("SELECT key, value FROM meta").fetchall())
        self.assertEqual((meta["schema_version"], meta["schema_provisional"]), ("1", "1"))

    def test_trading_and_foreign_names_are_refused(self):
        for bad in ("owl.db", "dual_archive.db", "brain_archive.db", "paper_trades.db", "market.db", "../v2_x.db", "sub/v2_x.db"):
            with self.assertRaises(S.StoreRefused, msg=bad):
                S.store_path(self.dir, bad)

    def test_missing_folder_and_link_are_refused(self):
        with self.assertRaises(S.StoreRefused):
            S.store_path(os.path.join(self.dir, "nope"))
        other = tempfile.mkdtemp(prefix="v2s_l_")
        self.addCleanup(shutil.rmtree, other, True)
        os.symlink(os.path.join(other, "x.db"), os.path.join(other, "v2_link.db"))
        with self.assertRaises(S.StoreRefused):
            S.store_path(other, "v2_link.db")

    def test_other_files_in_the_folder_are_never_touched(self):
        with open(os.path.join(self.dir, "owl.db"), "wb") as f:
            f.write(b"trading data")
        before = hashlib.sha256(b"trading data").hexdigest()
        self.fill(20)
        S.purge(self.con, NOW)
        with open(os.path.join(self.dir, "owl.db"), "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), before)

    def test_main_creates_only_the_market_store(self):
        d = tempfile.mkdtemp(prefix="v2s_m_")
        self.addCleanup(shutil.rmtree, d, True)
        self.assertEqual(S.main(["--data", d]), 0)
        self.assertTrue(all(n.startswith("v2_market.db") for n in os.listdir(d)))
        self.assertEqual(S.main(["--data", os.path.join(d, "nope")]), 1)


class Inserts(Base):
    def test_restart_does_not_duplicate_rows(self):
        self.fill(10)
        self.assertEqual(self.count("ticker_snapshot"), 10)
        self.con.close()
        self.con = S.open_store(self.dir)
        self.addCleanup(self.con.close)
        self.fill(10)
        self.assertEqual(self.count("ticker_snapshot"), 10)

    def test_a_saved_cohort_is_never_overwritten(self):
        self.assertTrue(S.add_cohort(self.con, "2026-10-30", "GAINER", 1, "AAAUSDT", 1.0, NOW, "AUTHENTIC"))
        self.assertFalse(S.add_cohort(self.con, "2026-10-30", "GAINER", 1, "BBBUSDT", 9.0, NOW + 5, "PROXY"))
        self.assertEqual(self.con.execute("SELECT symbol, open_price, source FROM cohort_official").fetchall(), [("AAAUSDT", 1.0, "AUTHENTIC")])

    def test_bad_values_are_refused(self):
        with self.assertRaises(ValueError):
            S.add_cohort(self.con, "d", "WINNER", 1, "A", 1.0, NOW, "AUTHENTIC")
        with self.assertRaises(ValueError):
            S.add_cohort(self.con, "d", "GAINER", 1, "A", 1.0, NOW, "GUESS")
        with self.assertRaises(ValueError):
            S.add_candle(self.con, "A", "1h", NOW, 1, 1, 1, 1, 1)

    def test_candle_and_gap_are_idempotent(self):
        self.assertTrue(S.add_candle(self.con, "A", "5m", NOW, 1, 2, 0.5, 1.5, 10))
        self.assertFalse(S.add_candle(self.con, "A", "5m", NOW, 9, 9, 9, 9, 9))
        self.assertEqual(self.con.execute("SELECT c FROM candles").fetchone()[0], 1.5)
        self.assertTrue(S.add_gap(self.con, "CANDLE", "A", "5m", NOW, NOW + 600, "api down", NOW + 700))
        self.assertFalse(S.add_gap(self.con, "CANDLE", "A", "5m", NOW, NOW + 600, "again", NOW + 800))
        self.assertEqual(self.count("gap_log"), 1)

    def test_health_keeps_only_the_latest_500(self):
        for i in range(520):
            S.add_health(self.con, NOW + i, "OK", "x")
        self.assertEqual(self.count("collector_health"), 500)
        self.assertEqual(self.con.execute("SELECT MIN(ts) FROM collector_health").fetchone()[0], NOW + 20)


class Cap(Base):
    def test_usage_states(self):
        used = S.used_bytes(self.con)
        self.assertEqual(S.usage(self.con, cap=used * 10)["state"], "OK")
        self.assertEqual(S.usage(self.con, cap=int(used / 0.9))["state"], "WARN")
        self.assertEqual(S.usage(self.con, cap=used)["state"], "FULL_PAUSED")

    def test_full_store_pauses_writing_but_still_records_gaps(self):
        cap = S.used_bytes(self.con) + 40000
        i = 0
        while S.can_write(self.con, cap) and i < 5000:
            S.add_snapshot(self.con, NOW - i, "S%d" % i, 1.0, 1.0, 1.0, cap=cap)
            i += 1
        self.assertFalse(S.can_write(self.con, cap))
        n = self.count("ticker_snapshot")
        self.assertFalse(S.add_snapshot(self.con, NOW + 10, "NEW", 1.0, 1.0, 1.0, cap=cap))
        self.assertFalse(S.add_cohort(self.con, "2026-10-30", "GAINER", 1, "A", 1.0, NOW, "AUTHENTIC", cap=cap))
        self.assertEqual(self.count("ticker_snapshot"), n)
        self.assertTrue(S.add_gap(self.con, "TICKER", "*", "5m", NOW, NOW + 300, "store full", NOW + 301))

    def test_freed_pages_do_not_count_as_used(self):
        self.fill(2000)
        full = S.used_bytes(self.con)
        self.con.execute("DELETE FROM ticker_snapshot")
        self.assertLess(S.used_bytes(self.con), full)


class Purge(Base):
    def seed(self):
        S.add_snapshot(self.con, NOW - 20 * DAY, "OLD", 1.0, 1.0, 1.0)
        S.add_snapshot(self.con, NOW - 1 * DAY, "NEW", 1.0, 1.0, 1.0)
        S.add_candle(self.con, "A", "3m", NOW - 20 * DAY, 1, 1, 1, 1, 1)       # 3m: kept 14 days -> goes
        S.add_candle(self.con, "A", "5m", NOW - 20 * DAY, 1, 1, 1, 1, 1)       # 5m: kept 30 days -> stays
        S.add_candle(self.con, "A", "5m", NOW - 40 * DAY, 1, 1, 1, 1, 1)       # goes
        S.add_cohort(self.con, "2026-08-01", "LOSER", 1, "OLDCOIN", 1.0, NOW - 90 * DAY, "AUTHENTIC")
        S.add_gap(self.con, "TICKER", "*", "5m", NOW - 90 * DAY, NOW - 89 * DAY, "old gap", NOW - 89 * DAY)

    def test_retention_days_are_per_table(self):
        self.seed()
        out = S.purge(self.con, NOW)
        self.assertEqual(out, {"ticker_snapshot": 1, "candles": 2})
        self.assertEqual(self.con.execute("SELECT symbol FROM ticker_snapshot").fetchall(), [("NEW",)])
        self.assertEqual(self.con.execute("SELECT interval, open_ts FROM candles").fetchall(), [("5m", NOW - 20 * DAY)])

    def test_cohort_official_and_gap_log_are_never_purged(self):
        self.seed()
        S.purge(self.con, NOW)
        S.purge(self.con, NOW + 400 * DAY)
        self.assertEqual((self.count("cohort_official"), self.count("gap_log")), (1, 1))

    def test_a_failed_purge_leaves_nothing_half_deleted(self):
        self.seed()
        self.con.execute("CREATE TRIGGER stop_candle_delete BEFORE DELETE ON candles BEGIN SELECT RAISE(ABORT, 'no'); END")
        with self.assertRaises(sqlite3.DatabaseError):
            S.purge(self.con, NOW)
        self.assertEqual((self.count("ticker_snapshot"), self.count("candles")), (2, 3))      # the ticker delete was rolled back too
        self.assertFalse(self.con.in_transaction)

    def test_over_the_purge_line_the_oldest_rows_go_first_and_protected_rows_stay(self):
        self.seed()
        self.fill(3000, start=100)
        cap = int(S.used_bytes(self.con) / 0.95)                                 # 95% used: above the 80% purge line
        before = self.count("ticker_snapshot")
        out = S.purge(self.con, NOW, cap=cap)
        self.assertGreater(out["ticker_snapshot"], 1)
        self.assertLess(self.count("ticker_snapshot"), before)
        self.assertLessEqual(100.0 * S.used_bytes(self.con) / cap, 80.0 + 5)
        newest = self.con.execute("SELECT MAX(run_ts) FROM ticker_snapshot").fetchone()[0]
        self.assertEqual(newest, NOW - 100 * 300)                                  # the newest rows are the ones kept
        self.assertEqual((self.count("cohort_official"), self.count("gap_log")), (1, 1))


class Source(Base):
    def test_no_network_signing_or_order_code(self):
        with open(os.path.join(ROOT, "backend", "v2_store.py")) as f:
            src = f.read()
        mods = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add((n.module or "").split(".")[0])
        for bad in ("socket", "requests", "urllib", "http", "hmac", "ccxt", "binance", "app", "strategy", "paper_trader", "live_recorder", "execution_router", "binance_trader"):
            self.assertNotIn(bad, mods)


if __name__ == "__main__":
    unittest.main()
