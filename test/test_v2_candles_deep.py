"""Part 17b test: backend/v2_candles_deep.py (deep hole filler). Offline: the exchange is a fake, data goes to temp folders.
Main questions: nothing happens while OFF, only slots that are really missing are asked (one request per coin + interval), only candles the exchange returns are saved,
a slot the exchange does not have becomes ONE gap row and is never asked again, a failed coin writes no gap, the budget holds, and the module is public-GET-only.
Run:  python3 test/test_v2_candles_deep.py"""
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
import v2_candles_deep as DP
import v2_defs as D
import v2_store as S

NOW = (1_800_000_000 // 3600) * 3600 + 100


class Exchange:
    """Fake klines: the last `limit` candles up to and INCLUDING the forming one. Candles older than `listed` or in `skip` do not exist."""
    def __init__(self):
        self.reqs, self.now, self.skip, self.fail, self.listed = [], NOW, set(), set(), 0

    def __call__(self, url):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        sym, iv, lim = q["symbol"][0], q["interval"][0], int(q["limit"][0])
        self.reqs.append((sym, iv, lim))
        if sym in self.fail:
            raise OSError("down")
        top = self.now // D.STEP[iv] * D.STEP[iv]
        ts = [top - i * D.STEP[iv] for i in range(lim - 1, -1, -1)]
        return [[t * 1000, "10", "11", "9", "10", "5", 0] for t in ts if t >= self.listed and (sym, iv, t) not in self.skip]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2kd_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._s = socket.socket
        socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))
        self.addCleanup(setattr, socket, "socket", self._s)
        self.con = S.open_store(self.dir)
        self.addCleanup(self.con.close)
        self.ex = Exchange()
        K.set_enabled(self.dir, True)
        S.add_snapshot(self.con, NOW - 300, "C00USDT", 1, 1, 1, rank_gain=1)

    def normal(self):
        return K.run_once(self.con, self.dir, NOW, self.ex, lambda s: None)

    def deep(self, **kw):
        return DP.run_once(self.con, self.dir, NOW, self.ex, lambda s: None, **kw)

    def n(self, table, where="1"):
        return self.con.execute("SELECT COUNT(*) FROM %s WHERE %s" % (table, where)).fetchone()[0]


class TestDeep(Base):
    def test_off_does_nothing(self):
        K.set_enabled(self.dir, False)
        self.assertEqual(self.deep(), {"state": "OFF"})
        self.assertEqual((self.ex.reqs, self.n("candles")), ([], 0))

    def test_new_coin_with_500_candles_is_filled_back_to_the_window(self):
        self.normal()
        self.ex.reqs.clear()
        r = self.deep()
        self.assertEqual((r["state"], r["requests"], r["gaps"], r["failed"]), ("OK", 2, 0, 0))
        self.assertEqual(self.n("candles", "interval='5m'"), DP.WINDOW + DP.SKIP_NEWEST)
        self.assertTrue(all(q[2] <= K.MAX_LIMIT for q in self.ex.reqs))
        self.assertEqual(self.n("gap_log"), 0)

    def test_nothing_missing_means_no_request(self):
        self.normal()
        self.deep()
        self.ex.reqs.clear()
        self.assertEqual((self.deep()["requests"], self.ex.reqs), (0, []))

    def test_old_hole_in_the_middle_is_filled_with_real_candles_only(self):
        self.normal()
        self.deep()
        top = DP.window_top(NOW, "5m")
        hole = [top - 300 * i for i in (100, 101, 102)]
        self.con.execute("DELETE FROM candles WHERE interval='5m' AND open_ts IN (?,?,?)", hole)
        self.ex.reqs.clear()
        r = self.deep()
        self.assertEqual((r["saved"], r["gaps"], len(self.ex.reqs)), (3, 0, 1))
        self.assertEqual(self.ex.reqs[0][2], ((NOW // 300 * 300 - 300) - hole[-1]) // 300 + 2)

    def test_slots_the_exchange_does_not_have_become_one_gap_and_are_not_asked_again(self):
        self.normal()
        top = DP.window_top(NOW, "5m")
        self.ex.skip = {("C00USDT", "5m", top - 300 * i) for i in (700, 701, 702)}
        r = self.deep()
        self.assertEqual(r["gaps"], 1)
        self.assertEqual(self.con.execute("SELECT from_ts, to_ts, reason FROM gap_log WHERE interval='5m'").fetchall(), [(top - 300 * 702, top - 300 * 700, DP.REASON)])
        self.assertEqual(self.n("candles", "interval='5m'"), DP.WINDOW + DP.SKIP_NEWEST - 3)
        self.ex.reqs.clear()
        self.assertEqual((self.deep()["requests"], self.ex.reqs), (0, []))

    def test_before_listing_is_one_gap_row_not_invented_candles(self):
        self.normal()
        top = DP.window_top(NOW, "5m")
        self.ex.listed = top - 300 * 599                            # the coin has only 600 candles of history in the window
        self.deep()
        g = self.con.execute("SELECT from_ts, to_ts FROM gap_log WHERE interval='5m'").fetchall()
        self.assertEqual(g, [(top - 300 * (DP.WINDOW - 1), top - 300 * 600)])
        self.assertEqual(self.n("candles", "interval='5m' AND open_ts < %d" % (top - 300 * 599)), 0)

    def test_old_too_old_gap_does_not_block_the_refill(self):
        self.normal()
        top = DP.window_top(NOW, "5m")
        S.add_gap(self.con, "candle", "C00USDT", "5m", top - 900 * 300, top - 600 * 300, "too old to refill (over 999 candles)", NOW)
        self.deep()
        self.assertEqual(self.n("candles", "interval='5m'"), DP.WINDOW + DP.SKIP_NEWEST)

    def test_failed_coin_writes_no_gap_and_is_retried(self):
        self.normal()
        self.ex.fail = {"C00USDT"}
        r = self.deep()
        self.assertEqual((r["state"], r["failed"], r["gaps"], self.n("gap_log")), ("PARTIAL", 2, 0, 0))
        self.ex.fail = set()
        self.assertEqual(self.deep()["state"], "OK")
        self.assertEqual(self.n("candles", "interval='5m'"), DP.WINDOW + DP.SKIP_NEWEST)

    def test_budget_stops_and_the_next_run_continues(self):
        self.normal()
        r = self.deep(budget=1)
        self.assertEqual((r["state"], r["requests"]), ("BUDGET_STOPPED", 1))
        r = self.deep(budget=1)                                     # 3m is complete now, so this run reaches 5m and finishes
        self.assertEqual((r["state"], r["requests"]), ("OK", 1))
        self.assertEqual(self.deep(budget=1)["requests"], 0)

    def test_failure_while_saving_rolls_back(self):
        self.normal()
        before = self.n("candles")
        orig = S.add_candle
        S.add_candle = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        self.addCleanup(setattr, S, "add_candle", orig)
        with self.assertRaises(RuntimeError):
            self.deep()
        self.assertEqual((self.n("candles"), self.n("gap_log"), self.con.in_transaction), (before, 0, False))

    def test_full_store_and_no_coins(self):
        orig = S.can_write
        S.can_write = lambda con, cap=S.CAP_BYTES: False
        self.addCleanup(setattr, S, "can_write", orig)
        self.assertEqual(self.deep()["state"], "FULL_PAUSED")
        S.can_write = orig
        self.con.execute("DELETE FROM ticker_snapshot")
        self.assertEqual(self.deep()["state"], "NO_SYMBOLS")
        self.assertEqual(self.ex.reqs, [])


class TestGuardsAndCli(Base):
    def test_source_is_public_get_only(self):
        with open(os.path.join(ROOT, "backend", "v2_candles_deep.py"), encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(mods, {"argparse", "os", "sys", "time", "v2_candles", "v2_defs", "v2_inventory", "v2_store"})
        body = src.split('"""', 2)[2].lower()
        for w in ("hmac", "hashlib", "signature", "x-mbx", "apikey", "api_key", "secret", "neworder", "recovered_bot", "binance_client", "owl.db", "post", "https://", "urllib"):
            self.assertNotIn(w, body, w)

    def test_plan_is_offline_and_cli_works(self):
        self.normal()
        self.assertEqual(len(DP.plan(self.con, NOW)), 2)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = DP.main(["--plan", "--data", self.dir])
        self.assertEqual(rc, 0)
        self.assertIn("holes", buf.getvalue())
        K.set_enabled(self.dir, False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            DP.main(["--once", "--data", self.dir])
        self.assertEqual(buf.getvalue(), "{'state': 'OFF'}\n")


if __name__ == "__main__":
    unittest.main(verbosity=1)
