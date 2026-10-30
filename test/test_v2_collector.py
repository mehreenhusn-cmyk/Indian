"""Part 16 test: backend/v2_collector.py (Collectors 3 of 5: 5-minute ticker collector, OFF by default). Offline: the network function is always a fake, data goes to temp folders.
Main questions: does it do NOTHING while switched off, can a restart or double start duplicate rows, are missed slots recorded as gaps (never invented), is the midnight cohort
written only at 00:00 UTC and labelled AUTHENTIC / PROXY honestly, is a failed run rolled back, and is the module public-GET-only with no key, signature or order code?
Run:  python3 test/test_v2_collector.py"""
import ast
import io
import os
import shutil
import socket
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_collector as C
import v2_store as S

MID = (1_800_000_000 // 86400) * 86400            # a 00:00 UTC slot
NOON = MID + 12 * 3600


def tick(sym, op, last, vol=1000.0, ct=None):
    return {"symbol": sym, "openPrice": str(op), "lastPrice": str(last), "quoteVolume": str(vol), "closeTime": int((ct if ct is not None else NOON) * 1000)}


def universe(n=50, ct=None):
    """symbol i moves (i - n/2) percent: S49 is the best gainer, S00 the worst loser."""
    return [tick("S%02dUSDT" % i, 100, 100 + (i - n // 2), ct=ct) for i in range(n)]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2c_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._s = socket.socket
        socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))
        self.addCleanup(setattr, socket, "socket", self._s)
        self.con = S.open_store(self.dir)
        self.addCleanup(self.con.close)
        self.calls, self.data = 0, universe()

    def get(self, url):
        self.calls += 1
        return self.data

    def on(self):
        C.set_enabled(self.dir, True)

    def go(self, now, get=None):
        return C.run_once(self.con, self.dir, now, get or self.get, sleep=lambda s: None)

    def count(self, t, where="1"):
        return self.con.execute("SELECT COUNT(*) FROM %s WHERE %s" % (t, where)).fetchone()[0]


class TestSwitch(Base):
    def test_default_off(self):
        self.assertFalse(C.is_enabled(self.dir))
        self.assertEqual(self.go(NOON), {"state": "OFF"})
        self.assertEqual((self.calls, self.count("ticker_snapshot"), self.count("collector_health")), (0, 0, 0))
        self.assertIsNone(C._meta_get(self.con, "collector_last_run_ts"))

    def test_on_off_and_garbage(self):
        self.on()
        self.assertTrue(C.is_enabled(self.dir))
        C.set_enabled(self.dir, False)
        self.assertFalse(C.is_enabled(self.dir))
        for txt in ("maybe", "", "2", "onn"):
            with open(C.flag_path(self.dir), "w") as f:
                f.write(txt)
            self.assertFalse(C.is_enabled(self.dir), txt)

    def test_switch_file_link_refused(self):
        real = os.path.join(self.dir, "real.txt")
        with open(real, "w") as f:
            f.write("1")
        os.symlink(real, C.flag_path(self.dir))
        self.assertFalse(C.is_enabled(self.dir))
        with self.assertRaises(S.StoreRefused):
            C.set_enabled(self.dir, True)

    def test_switch_off_again_stops_the_next_run(self):
        self.on()
        self.go(NOON)
        C.set_enabled(self.dir, False)
        self.assertEqual((self.go(NOON + 300)["state"], self.calls), ("OFF", 1))


class TestFetch(Base):
    def test_retry_then_success_waits_1_then_2(self):
        seq, waits = [RuntimeError("x"), [], self.data], []

        def g(url):
            r = seq.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        self.assertEqual(C.fetch_tickers(g, waits.append), self.data)
        self.assertEqual(waits, [1, 2])

    def test_all_tries_fail(self):
        with self.assertRaises(C.FetchFailed):
            C.fetch_tickers(lambda u: (_ for _ in ()).throw(OSError("down")), lambda s: None)

    def test_only_the_one_address_is_allowed(self):
        with self.assertRaises(C.FetchFailed):
            C.http_get("https://fapi.binance.com/fapi/v1/order")
        with self.assertRaises(C.FetchFailed):
            C.http_get(C.HOST_URL + "?signature=abc")

    def test_parse_keeps_clean_usdt_only(self):
        raw = [tick("AAAUSDT", 1, 2), tick("BTCBUSD", 1, 2), tick("lowerUSDT", 1, 2), tick("ZEROUSDT", 0, 2), tick("NANUSDT", "nan", 2), tick("AAAUSDT", 5, 6),
               {"symbol": "NOKEYUSDT"}, "text", None, tick("NEGUSDT", 1, 2, vol=-1), tick("A-BUSDT", 1, 2)]
        out, skipped = C.parse_tickers(raw)
        self.assertEqual(list(out), ["AAAUSDT"])
        self.assertEqual(out["AAAUSDT"]["last"], 2.0)          # first copy stays
        self.assertEqual(skipped, 10)
        self.assertEqual(C.parse_tickers("junk"), ({}, 0))


class TestRun(Base):
    def setUp(self):
        super().setUp()
        self.on()

    def test_saves_top_20_each_side_with_ranks(self):
        r = self.go(NOON + 17)
        self.assertEqual((r["state"], r["saved"]), ("OK", 40))
        run_ts = NOON
        row = self.con.execute("SELECT rank_gain, rank_loss, change_pct FROM ticker_snapshot WHERE run_ts=? AND symbol='S49USDT'", (run_ts,)).fetchone()
        self.assertEqual(row, (1, None, 24.0))
        row = self.con.execute("SELECT rank_gain, rank_loss FROM ticker_snapshot WHERE run_ts=? AND symbol='S00USDT'", (run_ts,)).fetchone()
        self.assertEqual(row, (None, 1))
        self.assertEqual(self.count("ticker_snapshot", "rank_gain IS NULL AND rank_loss IS NULL"), 0)
        self.assertEqual(C._meta_get(self.con, "collector_last_run_ts"), run_ts)
        self.data = universe(6)                                   # small universe: a symbol in both lists is saved once
        self.assertEqual(self.go(NOON + 300)["saved"], 6)

    def test_same_slot_twice_and_older_slot_do_nothing(self):
        self.go(NOON)
        self.assertEqual(self.go(NOON + 100)["state"], "SKIP_DUPLICATE")
        self.assertEqual(self.go(NOON - 600)["state"], "SKIP_DUPLICATE")
        self.assertEqual((self.calls, self.count("ticker_snapshot")), (1, 40))

    def test_next_slot_adds_rows_no_gap(self):
        self.go(NOON)
        self.assertEqual(self.go(NOON + 300)["state"], "OK")
        self.assertEqual((self.count("ticker_snapshot"), self.count("gap_log")), (80, 0))

    def test_missed_slots_become_one_gap_record(self):
        self.go(NOON)
        self.go(NOON + 300 * 4)
        g = self.con.execute("SELECT kind, symbol, interval, from_ts, to_ts, reason FROM gap_log").fetchall()
        self.assertEqual(g, [("ticker", "*", "5m", NOON + 300, NOON + 900, "collector was not running")])

    def test_fetch_failure_logs_gap_health_and_moves_on(self):
        self.go(NOON)
        bad = lambda u: (_ for _ in ()).throw(OSError("down"))
        r = self.go(NOON + 300, bad)
        self.assertEqual(r["state"], "FETCH_FAILED")
        self.assertEqual(self.count("gap_log", "from_ts=%d AND to_ts=%d" % (NOON + 300, NOON + 300)), 1)
        self.assertEqual(self.count("ticker_snapshot"), 40)
        self.assertEqual(self.go(NOON + 600)["state"], "OK")
        self.assertEqual(self.count("gap_log"), 1)               # no second record for the same hole
        self.assertEqual(self.con.execute("SELECT status FROM collector_health WHERE status='FETCH_FAILED'").fetchone()[0], "FETCH_FAILED")

    def test_answer_without_valid_ticker(self):
        self.data = [tick("ZEROUSDT", 0, 0)]
        self.assertEqual(self.go(NOON)["state"], "NO_VALID_DATA")
        self.assertEqual((self.count("ticker_snapshot"), self.count("gap_log")), (0, 1))

    def test_full_store_pauses_and_says_so(self):
        orig = S.can_write
        S.can_write = lambda con, cap=S.CAP_BYTES: False
        self.addCleanup(setattr, S, "can_write", orig)
        self.assertEqual(self.go(NOON)["state"], "FULL_PAUSED")
        self.assertEqual((self.calls, self.count("ticker_snapshot")), (0, 0))
        self.assertEqual(self.con.execute("SELECT status FROM collector_health").fetchone()[0], "FULL_PAUSED")


class TestCohort(Base):
    def setUp(self):
        super().setUp()
        self.on()
        self.data = universe(50, ct=MID)

    def test_midnight_authentic_previous_day_ten_rows(self):
        r = self.go(MID + 20)
        self.assertEqual(r["cohort"], "AUTHENTIC")
        self.assertEqual(self.count("cohort_official"), 10)
        self.assertEqual(self.count("cohort_official", "day='%s' AND source='AUTHENTIC'" % C._day(MID - 1)), 10)
        top = self.con.execute("SELECT symbol, open_price, snap_ts FROM cohort_official WHERE kind='GAINER' AND rank=1").fetchone()
        self.assertEqual(top, ("S49USDT", 124.0, MID))
        self.assertEqual(self.con.execute("SELECT symbol FROM cohort_official WHERE kind='LOSER' AND rank=1").fetchone()[0], "S00USDT")

    def test_late_fetch_is_proxy(self):
        self.assertEqual(self.go(MID + 200)["cohort"], "PROXY")
        self.assertEqual(self.count("cohort_official", "source='PROXY'"), 10)

    def test_stale_close_time_is_proxy(self):
        self.data = universe(50, ct=MID - 3600)
        self.assertEqual(self.go(MID + 10)["cohort"], "PROXY")

    def test_not_midnight_writes_no_cohort_even_after_a_late_start(self):
        for now in (MID + 300, MID + 3600, NOON):
            self.assertEqual(self.go(now)["cohort"], "NONE")
        self.assertEqual(self.count("cohort_official"), 0)

    def test_fewer_than_five_on_a_side_is_partial_and_proxy(self):
        self.data = universe(4, ct=MID)
        self.assertEqual(self.go(MID + 5)["cohort"], "PARTIAL")
        self.assertEqual(self.count("cohort_official", "source='AUTHENTIC'"), 0)

    def test_first_cohort_of_a_day_is_never_overwritten(self):
        self.go(MID + 200)                                       # PROXY saved first
        S.add_cohort(self.con, C._day(MID - 1), "GAINER", 1, "OTHERUSDT", 1, MID + 5, "AUTHENTIC")
        self.assertEqual(self.con.execute("SELECT symbol, source FROM cohort_official WHERE kind='GAINER' AND rank=1").fetchone(), ("S49USDT", "PROXY"))

    def test_failure_inside_the_run_rolls_everything_back(self):
        orig = S.add_cohort
        S.add_cohort = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        self.addCleanup(setattr, S, "add_cohort", orig)
        with self.assertRaises(RuntimeError):
            self.go(MID + 5)
        self.assertEqual((self.count("ticker_snapshot"), self.count("cohort_official")), (0, 0))
        self.assertIsNone(C._meta_get(self.con, "collector_last_run_ts"))


class TestLoopAndCli(Base):
    def test_loop_survives_a_bad_run_and_waits_for_the_next_slot(self):
        seen, waits = [], []

        def once(con, d):
            seen.append(1)
            if len(seen) == 1:
                raise RuntimeError("bad")
            return {"state": "OK"}
        buf = io.StringIO()
        with redirect_stdout(buf):
            C.loop(self.dir, once, waits.append, lambda: NOON + 100, max_runs=3)
        self.assertEqual(len(seen), 3)
        self.assertEqual(waits, [202.0] * 3)
        self.assertIn("run error: RuntimeError", buf.getvalue())

    def test_cli_on_off_status_once(self):
        def cli(*a):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = C.main(list(a) + ["--data", self.dir])
            return rc, buf.getvalue()
        self.assertIn("OFF", cli("--status")[1])
        self.assertIn("ON", cli("--on")[1])
        self.assertTrue(C.is_enabled(self.dir))
        self.assertIn("OFF", cli("--off")[1])
        rc, out = cli("--once")
        self.assertEqual((rc, "OFF" in out), (0, True))
        self.assertEqual(C.main(["--once", "--data", "/no/such/folder"]), 1)


class TestGuards(Base):
    def test_public_get_only_no_key_no_signature_no_order_code(self):
        with open(os.path.join(ROOT, "backend", "v2_collector.py"), encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(mods, {"argparse", "json", "math", "os", "sys", "time", "urllib", "v2_defs", "v2_inventory", "v2_store"})
        body = src.split('"""', 2)[2].lower()
        for word in ("hmac", "hashlib", "signature", "x-mbx", "apikey", "api_key", "secret", "neworder", "method=\"post\"", "recovered_bot", "binance_client", "owl.db"):
            self.assertNotIn(word, body, word)
        self.assertEqual(body.count("https://"), 1)

if __name__ == "__main__":
    unittest.main(verbosity=1)
