"""Part 17 test: backend/v2_candles.py (Collectors 4 of 5: closed 3m / 5m candles, max 40 coins, gap refill). Offline: the exchange is a fake, data goes to temp folders.
Main questions: nothing happens while OFF, only CLOSED candles are saved, a request is made only for what is missing, holes become gap records (never bridged or invented),
the request budget and the 40-coin cap hold, a failed coin does not stop the others, and the module is public-GET-only. Run:  python3 test/test_v2_candles.py"""
import ast
import io
import os
import shutil
import socket
import sys
import tempfile
import unittest
import urllib.parse
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_candles as K
import v2_defs as D
import v2_store as S

NOW = (1_800_000_000 // 3600) * 3600 + 100          # inside a forming 3m and 5m candle


class Exchange:
    """Fake klines: the last `limit` candles of the grid up to and INCLUDING the forming one, like the real thing."""
    def __init__(self):
        self.reqs, self.now, self.skip, self.fail = [], NOW, set(), set()

    def __call__(self, url):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        sym, iv, lim = q["symbol"][0], q["interval"][0], int(q["limit"][0])
        self.reqs.append((sym, iv, lim))
        if sym in self.fail:
            raise OSError("down")
        step = D.STEP[iv]
        top = self.now // step * step
        return [[(top - i * step) * 1000, "10", "11", "9", "10", "5", 0] for i in range(lim - 1, -1, -1) if (sym, iv, top - i * step) not in self.skip]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2k_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._s = socket.socket
        socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))
        self.addCleanup(setattr, socket, "socket", self._s)
        self.con = S.open_store(self.dir)
        self.addCleanup(self.con.close)
        self.ex = Exchange()
        K.set_enabled(self.dir, True)

    def seed(self, n=3):
        for i in range(n):
            S.add_snapshot(self.con, NOW - 300, "C%02dUSDT" % i, 1, 1, 1, rank_gain=i + 1)

    def go(self, now=NOW, **kw):
        self.ex.now = now
        return K.run_once(self.con, self.dir, now, self.ex, lambda s: None, **kw)

    def n(self, table, where="1"):
        return self.con.execute("SELECT COUNT(*) FROM %s WHERE %s" % (table, where)).fetchone()[0]


class TestGuards(Base):
    def test_off_by_default_does_nothing(self):
        K.set_enabled(self.dir, False)
        self.seed()
        self.assertEqual(self.go(), {"state": "OFF"})
        self.assertEqual((self.ex.reqs, self.n("candles"), self.n("collector_health")), ([], 0, 0))

    def test_only_one_address_and_three_words(self):
        ok = K.kline_url("BTCUSDT", "5m", 10)
        for bad in (ok.replace("klines", "order"), ok + "&signature=x", ok.replace("symbol", "pair"), K.kline_url("btcusdt", "5m", 10), K.kline_url("BTCUSDT", "1h", 10),
                    K.kline_url("BTCUSDT", "5m", 1001), K.kline_url("BTCUSDT", "5m", 0), ok.replace("https://fapi.binance.com", "https://evil.example"), ok + "&limit=5"):
            with self.assertRaises(K.FetchFailed, msg=bad):
                K.http_get(bad)

    def test_source_has_no_key_signature_or_order_code(self):
        with open(os.path.join(ROOT, "backend", "v2_candles.py"), encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(mods, {"argparse", "json", "os", "sys", "time", "urllib", "v2_defs", "v2_inventory", "v2_store"})
        body = src.split('"""', 2)[2].lower()
        for w in ("hmac", "hashlib", "signature", "x-mbx", "apikey", "api_key", "secret", "neworder", "recovered_bot", "binance_client", "owl.db", "post"):
            self.assertNotIn(w, body, w)
        self.assertEqual(body.count("https://"), 1)

    def test_switch_link_and_garbage(self):
        os.remove(K.flag_path(self.dir))
        os.symlink(os.path.join(self.dir, "x"), K.flag_path(self.dir))
        with self.assertRaises(S.StoreRefused):
            K.set_enabled(self.dir, True)


class TestParseAndPick(Base):
    def test_forming_dropped_bad_counted_grid_enforced(self):
        top = NOW // 300 * 300
        rows = [[(top - 300) * 1000, "10", "11", "9", "10", "5"], [top * 1000, "10", "11", "9", "10", "5"], [(top - 600) * 1000 + 1000, "10", "11", "9", "10", "5"],
                [(top - 900) * 1000, "0", "1", "0", "1", "1"], ["x"], None, [(top - 1200) * 1000, "10", "9", "9", "10", "5"]]
        good, bad = K.parse_klines(rows, "5m", NOW)
        self.assertEqual([c[0] for c in good], [top - 300])
        self.assertEqual(bad, 5)
        self.assertEqual(K.parse_klines("junk", "5m", NOW), ([], 0))

    def test_cohort_first_then_snapshot_dedup_and_cap(self):
        S.add_cohort(self.con, "2026-10-29", "GAINER", 1, "AAAUSDT", 1, NOW, "PROXY")
        S.add_cohort(self.con, "2026-10-29", "LOSER", 1, "BBBUSDT", 1, NOW, "PROXY")
        S.add_snapshot(self.con, NOW - 300, "BBBUSDT", 1, 1, 1, rank_gain=1)
        S.add_snapshot(self.con, NOW - 300, "CCCUSDT", 1, 1, 1, rank_loss=1)
        S.add_snapshot(self.con, NOW - 300, "DDDUSDT", 1, 1, 1, rank_gain=2)
        self.assertEqual(K.pick_symbols(self.con, NOW), ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"])
        self.assertEqual(K.pick_symbols(self.con, NOW, cap=3), ["AAAUSDT", "BBBUSDT", "CCCUSDT"])
        self.assertEqual(K.pick_symbols(self.con, NOW + 2 * 86400), ["AAAUSDT", "BBBUSDT"])      # stale snapshot not used

    def test_forty_coin_cap(self):
        self.seed(60)
        self.assertEqual(len(K.pick_symbols(self.con, NOW)), 40)
        self.assertEqual(self.go()["coins"], 40)


class TestRefill(Base):
    def setUp(self):
        super().setUp()
        self.seed(1)

    def test_first_run_saves_500_closed_per_interval_and_never_the_forming(self):
        r = self.go()
        self.assertEqual((r["state"], r["saved"], r["requests"], r["gaps"]), ("OK", 1000, 2, 0))
        for iv, st in (("3m", 180), ("5m", 300)):
            self.assertEqual(self.con.execute("SELECT MAX(open_ts) FROM candles WHERE interval=?", (iv,)).fetchone()[0], NOW // st * st - st)
        self.assertEqual(self.ex.reqs, [("C00USDT", "3m", 501), ("C00USDT", "5m", 501)])

    def test_nothing_missing_means_no_request_and_no_new_rows(self):
        self.go()
        self.ex.reqs.clear()
        self.assertEqual((self.go(NOW + 60)["requests"], self.ex.reqs, self.n("candles")), (0, [], 1000))

    def test_next_candle_is_one_new_row_and_a_small_request(self):
        self.go()
        self.ex.reqs.clear()
        r = self.go(NOW + 300)
        self.assertEqual(r["saved"], 3)                     # 5m: 1 new, 3m: 2 new (300 s is 1.67 candles)
        self.assertTrue(all(q[2] <= 4 for q in self.ex.reqs))
        self.assertEqual(self.n("gap_log"), 0)

    def test_stop_of_ten_candles_is_refilled_without_gap(self):
        self.go()
        r = self.go(NOW + 3000)
        self.assertEqual((r["gaps"], self.n("candles", "interval='5m'")), (0, 510))

    def test_stop_longer_than_999_candles_saves_999_and_records_the_old_part(self):
        self.go()
        late = NOW + 300 * 1100                                 # 3.8 days later: a fresh snapshot keeps the coin on the list
        S.add_snapshot(self.con, late - 300, "C00USDT", 1, 1, 1, rank_gain=1)
        self.go(late)
        g = self.con.execute("SELECT from_ts, to_ts, reason FROM gap_log WHERE interval='5m'").fetchall()
        self.assertEqual(len(g), 1)
        self.assertIn("too old to refill", g[0][2])
        self.assertEqual(self.n("candles", "interval='5m'"), 500 + 999)
        self.ex.reqs.clear()
        self.assertEqual(self.go(NOW + 300 * 1100 + 10)["requests"], 0)

    def test_hole_in_the_middle_is_recorded_exactly(self):
        top = NOW // 300 * 300 - 300
        self.ex.skip = {("C00USDT", "5m", top - 600), ("C00USDT", "5m", top - 900)}
        self.go()
        self.assertEqual(self.con.execute("SELECT from_ts, to_ts FROM gap_log WHERE interval='5m'").fetchall(), [(top - 900, top - 600)])
        self.assertEqual(self.n("candles", "interval='5m'"), 498)

    def test_missing_newest_candle_is_recorded_and_not_asked_again(self):
        top = NOW // 300 * 300 - 300
        self.ex.skip = {("C00USDT", "5m", top)}
        self.go()
        self.assertEqual(self.n("gap_log", "from_ts=%d AND to_ts=%d" % (top, top)), 1)
        self.ex.reqs.clear()
        self.go(NOW + 10)
        self.assertEqual([q for q in self.ex.reqs if q[1] == "5m"], [])

    def test_failed_coin_is_skipped_retried_and_writes_no_gap(self):
        self.seed(3)
        self.ex.fail = {"C01USDT"}
        r = self.go()
        self.assertEqual((r["state"], r["failed"], r["gaps"]), ("PARTIAL", 2, 0))
        self.assertEqual(self.n("candles", "symbol='C01USDT'"), 0)
        self.assertEqual(self.n("candles", "symbol='C00USDT'"), 1000)
        self.assertEqual(self.ex.reqs.count(("C01USDT", "3m", 501)), 2)          # 2 tries, both counted
        self.ex.fail = set()
        self.assertEqual(self.go(NOW + 5)["state"], "OK")
        self.assertEqual(self.n("candles", "symbol='C01USDT'"), 1000)

    def test_budget_stops_and_the_next_run_continues(self):
        self.seed(10)
        r = self.go(budget=7)
        self.assertEqual((r["state"], r["requests"]), ("BUDGET_STOPPED", 7))
        done = self.n("candles")
        self.assertEqual(self.go(budget=7)["state"], "BUDGET_STOPPED")
        self.assertGreater(self.n("candles"), done)
        while self.go(budget=7)["state"] != "OK":
            pass
        self.assertEqual(self.n("candles"), 10 * 1000)

    def test_full_store_pauses_without_network(self):
        orig = S.can_write
        S.can_write = lambda con, cap=S.CAP_BYTES: False
        self.addCleanup(setattr, S, "can_write", orig)
        self.assertEqual(self.go()["state"], "FULL_PAUSED")
        self.assertEqual((self.ex.reqs, self.n("candles")), ([], 0))

    def test_failure_while_saving_rolls_that_coin_back(self):
        orig = S.add_candle
        S.add_candle = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        self.addCleanup(setattr, S, "add_candle", orig)
        with self.assertRaises(RuntimeError):
            self.go()
        self.assertEqual((self.n("candles"), self.n("gap_log"), self.con.in_transaction), (0, 0, False))

    def test_store_filling_up_mid_run_saves_nothing_and_the_next_run_catches_up(self):
        orig, calls = S.can_write, []
        S.can_write = lambda con, cap=S.CAP_BYTES: not calls.append(1) and len(calls) == 1
        self.go()
        S.can_write = orig
        self.assertEqual((self.n("candles"), self.n("gap_log")), (0, 0))
        self.assertEqual(self.go(NOW + 5)["saved"], 1000)

    def test_no_coins_yet(self):
        self.con.execute("DELETE FROM ticker_snapshot")
        self.assertEqual(self.go()["state"], "NO_SYMBOLS")
        self.assertEqual(self.ex.reqs, [])


class TestLoopAndCli(Base):
    def test_loop_survives_a_bad_run(self):
        seen, waits, buf = [], [], io.StringIO()

        def once(con, d):
            seen.append(1)
            if len(seen) == 1:
                raise RuntimeError("bad")
            return {"state": "OK"}
        with redirect_stdout(buf):
            K.loop(self.dir, once, waits.append, lambda: NOW, max_runs=3)
        self.assertEqual((len(seen), waits), (3, [60] * 3))
        self.assertIn("run error: RuntimeError", buf.getvalue())

    def test_cli(self):
        def cli(*a):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = K.main(list(a) + ["--data", self.dir])
            return rc, buf.getvalue()
        self.assertIn("OFF", cli("--off")[1])
        self.assertEqual(cli("--once"), (0, "{'state': 'OFF'}\n"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
