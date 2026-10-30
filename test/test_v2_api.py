"""Part 18 test: backend/api/v2_data.py (Collectors 5 of 5: READ-ONLY routes over v2_market.db). Offline; fastapi is replaced by a tiny stub (it is not installed here), the store is a temp file.
Main questions: is everything OFF by default, can any route write or create the store, are the inputs checked and the answers capped, does a database problem leak a path or SQL,
are there exactly 5 GET routes all behind the token check, and is the module free of network / write / order code?
Run:  python3 test/test_v2_api.py"""
import ast
import hashlib
import os
import shutil
import socket
import sqlite3
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_candles as K
import v2_collector as C
import v2_store as S
from api import v2_data as A

NOW = 1_800_000_000


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2a_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._s = socket.socket
        socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))
        self.addCleanup(setattr, socket, "socket", self._s)

    def enable(self):
        with open(os.path.join(self.dir, A.FLAG_NAME), "w") as f:
            f.write("1")

    def seed(self):
        con = S.open_store(self.dir)
        for i in range(5):
            S.add_snapshot(con, NOW - 300, "G%dUSDT" % i, 10 + i, 5 - i, 1000, rank_gain=i + 1)
            S.add_snapshot(con, NOW - 300, "L%dUSDT" % i, 10 + i, -5 + i, 1000, rank_loss=i + 1)
        S.add_snapshot(con, NOW - 900, "OLDUSDT", 1, 1, 1, rank_gain=1)
        S.add_cohort(con, "2026-10-28", "GAINER", 1, "OLDUSDT", 1, NOW, "PROXY")
        S.add_cohort(con, "2026-10-29", "GAINER", 1, "G4USDT", 14, NOW, "AUTHENTIC")
        S.add_cohort(con, "2026-10-29", "LOSER", 1, "L0USDT", 10, NOW, "AUTHENTIC")
        for i in range(30):
            S.add_candle(con, "G4USDT", "5m", NOW - 300 * (30 - i), 1, 2, 1, 1.5, i)
        S.add_candle(con, "G4USDT", "3m", NOW, 1, 2, 1, 1, 1)
        S.add_gap(con, "candle", "G4USDT", "5m", NOW - 300 * 20, NOW - 300 * 18, "exchange returned no candle", NOW)
        S.add_gap(con, "candle", "G4USDT", "5m", NOW - 300 * 100, NOW - 300 * 90, "too old to refill (over 98 candles)", NOW)
        S.add_gap(con, "ticker", "*", "5m", NOW - 600, NOW - 600, "fetch failed: x", NOW)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('collector_last_run_ts', ?)", (str(NOW - 120),))
        for i in range(7):
            S.add_health(con, NOW - 100 + i, "OK", "run %d" % i)
        con.close()

    def get(self, name, now=NOW, **params):
        return A.dispatch(name, params, self.dir, now)

    def digest(self):
        p = os.path.join(self.dir, S.DB_NAME)
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest(), sorted(os.listdir(self.dir))


class TestOffAndMissing(Base):
    def test_everything_off_by_default_and_nothing_created(self):
        for n in A.ROUTES:
            st, body = self.get(n)
            self.assertEqual((st, body["enabled"]), (404, False), n)
        self.assertEqual(os.listdir(self.dir), [])

    def test_on_but_no_store_says_not_ready_and_does_not_create_it(self):
        self.enable()
        for n in A.ROUTES:
            self.assertEqual(self.get(n), (200, {"ready": False, "note": "the market store is not created yet"}), n)
        self.assertEqual(os.listdir(self.dir), [A.FLAG_NAME])

    def test_unknown_route_and_flag_garbage_or_link(self):
        self.assertEqual(self.get("order")[0], 404)
        with open(os.path.join(self.dir, "real.txt"), "w") as f:
            f.write("1")
        os.symlink(os.path.join(self.dir, "real.txt"), os.path.join(self.dir, A.FLAG_NAME))
        self.assertFalse(A.api_enabled(self.dir))


class TestViews(Base):
    def setUp(self):
        super().setUp()
        self.enable()
        self.seed()

    def test_status(self):
        C.set_enabled(self.dir, True)
        st, b = self.get("status")
        self.assertEqual(st, 200)
        self.assertEqual((b["switches"], b["last_ticker_run_ts"], b["last_ticker_run_age_sec"]), ({"ticker": True, "candles": False}, NOW - 120, 120))
        self.assertEqual((b["store"]["state"], b["store"]["rows"]["candles"], b["schema_provisional"]), ("OK", 31, True))
        self.assertEqual(len(b["health"]), 5)
        self.assertEqual(b["health"][0]["note"], "run 6")                 # newest first, capped at 5

    def test_snapshot_newest_run_in_rank_order_and_limit(self):
        st, b = self.get("snapshot")
        self.assertEqual((b["run_ts"], len(b["rows"])), (NOW - 300, 10))
        self.assertEqual([r["symbol"] for r in b["rows"][:4]], ["G0USDT", "L0USDT", "G1USDT", "L1USDT"])
        self.assertNotIn("OLDUSDT", [r["symbol"] for r in b["rows"]])
        self.assertEqual(len(self.get("snapshot", limit="3")[1]["rows"]), 3)

    def test_cohort_newest_day_default_explicit_day_and_bad_day(self):
        b = self.get("cohort")[1]
        self.assertEqual((b["day"], [r["symbol"] for r in b["rows"]]), ("2026-10-29", ["G4USDT", "L0USDT"]))
        self.assertEqual(self.get("cohort", day="2026-10-28")[1]["rows"][0]["source"], "PROXY")
        self.assertEqual(self.get("cohort", day="2020-01-01")[1]["rows"], [])
        for bad in ("29-10-2026", "2026-10-29; DROP TABLE x", "x"):
            self.assertEqual(self.get("cohort", day=bad)[0], 400, bad)

    def test_candles_newest_n_ascending_with_only_overlapping_gaps(self):
        b = self.get("candles", symbol="G4USDT", interval="5m", limit="12")[1]
        ts = [r["open_ts"] for r in b["rows"]]
        self.assertEqual((len(ts), ts == sorted(ts), ts[-1]), (12, True, NOW - 300))
        self.assertEqual(b["gaps"], [])                                    # the gap 18-20 candles back is older than these 12
        b = self.get("candles", symbol="G4USDT", limit="30")[1]
        self.assertEqual([g["reason"] for g in b["gaps"]], ["exchange returned no candle"])   # the 90-100 gap is too old to touch the range
        self.assertEqual(self.get("candles", symbol="G4USDT", interval="3m")[1]["rows"][0]["open_ts"], NOW)

    def test_candles_bad_input(self):
        for kw in ({}, {"symbol": "btcusdt"}, {"symbol": "A-BUSDT"}, {"symbol": "G4USDT", "interval": "1h"}, {"symbol": "G4USDT", "limit": "0"},
                   {"symbol": "G4USDT", "limit": "501"}, {"symbol": "G4USDT", "limit": "-1"}, {"symbol": "G4USDT", "limit": "1; DROP"}, {"symbol": "G4USDT'--"}):
            self.assertEqual(self.get("candles", **kw)[0], 400, kw)
        self.assertEqual(self.get("candles", symbol="G4USDT", limit="500")[0], 200)

    def test_gaps_newest_first_and_capped(self):
        b = self.get("gaps")[1]
        self.assertEqual((len(b["rows"]), b["rows"][0]["kind"]), (3, "ticker"))
        self.assertEqual(len(self.get("gaps", limit="2")[1]["rows"]), 2)
        self.assertEqual(self.get("gaps", limit="201")[0], 400)


class TestReadOnlyAndErrors(Base):
    def setUp(self):
        super().setUp()
        self.enable()
        self.seed()

    def test_no_route_changes_the_database_or_the_folder(self):
        before = self.digest()
        for n, kw in (("status", {}), ("snapshot", {}), ("cohort", {}), ("candles", {"symbol": "G4USDT"}), ("gaps", {})):
            self.assertEqual(self.get(n, **kw)[0], 200)
        self.assertEqual(self.digest()[0], before[0])
        self.assertEqual([f for f in self.digest()[1] if not f.endswith(("-wal", "-shm"))], [f for f in before[1] if not f.endswith(("-wal", "-shm"))])

    def test_the_connection_cannot_write(self):
        con = A.open_ro(self.dir)
        self.addCleanup(con.close)
        for sql in ("INSERT INTO gap_log VALUES ('x','x','5m',1,2,'x',3)", "DELETE FROM candles", "DROP TABLE meta", "UPDATE meta SET value='0'"):
            with self.assertRaises(sqlite3.Error, msg=sql):
                con.execute(sql)

    def test_database_problem_gives_a_short_fixed_text_without_path_or_sql(self):
        orig = A.open_ro
        A.open_ro = lambda d: (_ for _ in ()).throw(sqlite3.OperationalError("unable to open /data/secret/v2_market.db SELECT x"))
        self.addCleanup(setattr, A, "open_ro", orig)
        st, b = self.get("gaps")
        self.assertEqual((st, b), (503, {"error": "the market store is busy or unreadable"}))

    def test_linked_store_file_is_refused(self):
        os.replace(os.path.join(self.dir, S.DB_NAME), os.path.join(self.dir, "real.db"))
        os.symlink(os.path.join(self.dir, "real.db"), os.path.join(self.dir, S.DB_NAME))
        self.assertEqual(self.get("gaps"), (503, {"error": "the market store path is not safe"}))


class TestRouter(Base):
    def stub(self):
        class R:
            def __init__(s):
                s.routes = []

            def get(s, path, **kw):
                return lambda f: (s.routes.append((path, kw, f)), f)[1]
        fa, resp = types.ModuleType("fastapi"), types.ModuleType("fastapi.responses")
        fa.APIRouter, fa.Depends = R, lambda f: ("dep", f)
        resp.JSONResponse = lambda body, status_code=200: (status_code, body)
        for k, v in (("fastapi", fa), ("fastapi.responses", resp)):
            self.addCleanup(sys.modules.pop, k, None) if k not in sys.modules else None
            sys.modules[k] = v
        fa.responses = resp

    def test_five_get_routes_each_behind_the_token_check(self):
        self.stub()
        guard = lambda: None
        r = A.make_router(guard, self.dir)
        self.assertEqual([p for p, _, _ in r.routes], ["/api/v2/" + n for n in A.ROUTES])
        for _, kw, _ in r.routes:
            self.assertEqual(kw["dependencies"], [("dep", guard)])
        self.assertFalse([m for m in dir(r) if m in ("post", "put", "delete", "patch")])

    def test_a_route_answers_through_dispatch(self):
        import asyncio
        self.stub()
        socket.socket = self._s                                  # asyncio needs its own local socket pair (no network is used)
        r = A.make_router(lambda: None, self.dir)
        views = {p: f for p, _, f in r.routes}
        self.assertEqual(asyncio.run(views["/api/v2/status"]())[0], 404)             # off by default
        self.enable()
        self.seed()
        self.assertEqual(asyncio.run(views["/api/v2/candles"](symbol="bad"))[0], 400)


class TestSource(Base):
    def test_no_network_write_or_order_code(self):
        with open(os.path.join(ROOT, "backend", "api", "v2_data.py"), encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        top = {a.name.split(".")[0] for n in tree.body if isinstance(n, ast.Import) for a in n.names} | {(n.module or "").split(".")[0] for n in tree.body if isinstance(n, ast.ImportFrom)}
        self.assertEqual(top, {"os", "re", "sqlite3", "sys", "time", "urllib", "v2_candles", "v2_collector", "v2_store"})
        body = src.split('"""', 2)[2].lower()
        for w in ("urllib.request", "socket", "requests", "insert ", "update ", "delete ", "drop ", "commit", "hmac", "signature", "x-mbx", "neworder", "owl.db", "recovered_bot", "@r.post", "r.put"):
            self.assertNotIn(w, body, w)


if __name__ == "__main__":
    unittest.main(verbosity=1)
