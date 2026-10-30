"""Part 6 test: backend/v2_pnl_open.py (floating P&L + live fee facts, read-only). Offline, no network, temp folders only.
Run:  python3 test/test_v2_pnl_open.py"""
import ast
import json
import os
import shutil
import socket
import sqlite3
import stat
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_inv_safe as S
import v2_pnl_open as O

NOW = time.time()


def pos(i, action="BUY", entry=100.0, ltp=101.0, invest=100.0, lev=10, shown=None, **kw):
    """BUY 100 -> 101 at 10x = +10% gross; fee 1% of ROI -> net +9% -> +9 USDT on 100 margin."""
    p = {"id": i, "symbol": "S%dUSDT" % i, "action": action, "entry_price": entry, "ltp": ltp, "invest_usdt": invest,
         "leverage": lev, "fee_roi_pct": 1.0, "bot": "b1", "opened_at_ts": NOW - 7200}
    p.update(kw)
    ok = all(isinstance(p[k], (int, float)) and p[k] for k in ("entry_price", "ltp", "invest_usdt"))
    p["pnl_usdt"] = shown if shown is not None else (O.gross_roi(action, p["entry_price"], p["ltp"], lev) * p["invest_usdt"] / 100.0
                                                     - p["invest_usdt"] * 0.01 if ok else 0.0)
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2o_")
        self.data = os.path.join(self.dir, "data")
        os.makedirs(self.data)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._sock = socket.socket
        socket.socket = self._no_net
        self.addCleanup(setattr, socket, "socket", self._sock)
        self.con = None

    @staticmethod
    def _no_net(*a, **k):
        raise AssertionError("network used")

    def db(self, rows, wal=False, age=1.0):
        for ext in ("", "-wal", "-shm"):
            if os.path.exists(os.path.join(self.data, "owl.db" + ext)):
                os.remove(os.path.join(self.data, "owl.db" + ext))
        con = sqlite3.connect(os.path.join(self.data, "owl.db"))
        if wal:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated_at REAL NOT NULL)")
        for r in rows:
            con.execute("INSERT INTO positions VALUES (?,?,?)", (r["id"], r["data"] if "data" in r else json.dumps(r), r.get("_upd", NOW - age)))
        con.commit()
        self.con = con if wal else con.close()

    def boxes(self, **kw):
        return O.build_report(self.data, **kw)["boxes"]


class Numbers(Base):
    def test_same_formula_as_the_paper_trader(self):
        from recovered_bot import paper_trader as PT
        for action, ltp in (("BUY", 101.5), ("SELL", 98.2), ("BUY", 97.0)):
            self.assertAlmostEqual(O.gross_roi(action, 100.0, ltp, 10), PT._calc_roi({"entry_price": 100.0, "action": action, "leverage": 10}, ltp))

    def test_gross_fee_net_for_a_long_and_a_short(self):
        self.db([pos(1), pos(2, action="SELL", ltp=99.0)])
        b = self.boxes()["paper_b1"]
        self.assertEqual((b["positions"], b["margin_locked_usdt"]), (2, 200.0))
        self.assertAlmostEqual(b["floating_gross_usdt"], 20.0)
        self.assertAlmostEqual(b["fee_already_deducted_usdt"], 2.0)
        self.assertAlmostEqual(b["floating_net_usdt"], 18.0)
        self.assertEqual((b["winners"], b["losers"]), (2, 0))
        self.assertTrue(b["floating_is_current"])
        self.assertEqual(sum(v["count"] for v in b["checks"].values()), 0)

    def test_a_loser_and_the_setting_fee_used_only_when_the_row_has_none(self):
        row = pos(1, ltp=99.0)
        del row["fee_roi_pct"]
        self.db([row])
        self.assertAlmostEqual(self.boxes(fee_roi=1.0)["paper_b1"]["floating_net_usdt"], -11.0)
        self.assertAlmostEqual(self.boxes(fee_roi=2.0)["paper_b1"]["floating_net_usdt"], -12.0)
        self.assertEqual(self.boxes()["paper_b1"]["losers"], 1)

    def test_open_hours(self):
        self.db([pos(1, opened_at_ts=NOW - 3 * 3600)])
        self.assertAlmostEqual(self.boxes()["paper_b1"]["oldest_open_hours"], 3.0, places=1)


class Boxes(Base):
    def test_paper_bot2_and_live_copy_stay_apart(self):
        self.db([pos(1), pos(2, bot="b2"), pos(3, source="live", ltp=105.0)])
        b = self.boxes()
        self.assertEqual({k: v["positions"] for k, v in b.items()}, {"paper_b1": 1, "paper_b2": 1, "live_local_copy": 1})
        self.assertNotIn("total", O.build_report(self.data))
        self.assertTrue(all(v["is_real_money"] is False for v in b.values()))


class Checks(Base):
    def flags(self, rows, box="paper_b1", **kw):
        self.db(rows, **kw)
        return {k: v for k, v in self.boxes()[box]["checks"].items() if v["count"]}

    def test_stale_snapshot_means_the_number_is_old(self):
        f = self.flags([pos(1)], age=600)
        self.assertEqual(set(f), {"stale_snapshot"})
        self.assertFalse(self.boxes()["paper_b1"]["floating_is_current"])

    def test_card_pnl_that_differs_from_recomputed_is_flagged(self):
        self.assertEqual(set(self.flags([pos(1, shown=15.0)])), {"pnl_differs_from_recomputed"})
        self.assertEqual(set(self.flags([pos(1, shown=None)])), set())

    def test_missing_fields_are_flagged_not_guessed(self):
        f = self.flags([pos(1, ltp=None), pos(2, entry_price=0), pos(3, invest_usdt=None)])
        self.assertEqual(f["missing_price_entry_or_margin"]["count"], 3)
        b = self.boxes()["paper_b1"]
        self.assertEqual((b["positions"], b["floating_net_usdt"]), (3, 0.0))

    def test_same_symbol_and_side_twice(self):
        a, b = pos(1), pos(2)
        b["symbol"] = a["symbol"]
        self.assertEqual(set(self.flags([a, b])), {"same_symbol_side_open_twice"})

    def test_a_corrupt_row_is_counted_and_the_rest_still_works(self):
        self.db([pos(1), {"id": 2, "data": "{not json"}])
        r = O.build_report(self.data)
        self.assertEqual((r["source"]["unreadable_rows"], r["boxes"]["paper_b1"]["positions"]), (1, 1))


class Sources(Base):
    def test_wal_database_is_read_by_copy_and_never_changed(self):
        self.db([pos(1)], wal=True)
        before = S.source_fingerprints(os.path.join(self.data, "owl.db"))
        listing = sorted(os.listdir(self.data))
        r = O.build_report(self.data)
        self.assertIn("copied snapshot", r["source"]["owl.db"])
        self.assertEqual(r["boxes"]["paper_b1"]["positions"], 1)
        self.assertEqual(S.source_fingerprints(os.path.join(self.data, "owl.db")), before)
        self.assertEqual(sorted(os.listdir(self.data)), listing)
        self.con.close()

    def test_missing_database_and_missing_folder_do_not_crash(self):
        r = O.build_report(self.data)
        self.assertTrue(r["source"]["owl.db"].startswith(("not opened", "no readable")))
        self.assertEqual(r["boxes"]["paper_b1"]["positions"], 0)
        self.assertEqual(O.build_report(os.path.join(self.dir, "nope"))["error"], "data folder not found")

    def test_live_closed_checks_count_estimates_and_missing_fee_fields(self):
        with open(os.path.join(self.data, "closed_trades_archive.jsonl"), "w") as f:
            for i, kw in enumerate(({}, {"estimated": True}, {"fee_usdt": 0.4})):
                f.write(json.dumps(dict({"id": i, "source": "live", "pnl_usdt": 1.0, "closed_at_ts": NOW - i}, **kw)) + "\n")
            f.write(json.dumps({"id": 9, "pnl_usdt": 2.0, "closed_at_ts": NOW}) + "\n")      # paper: must not count
        with open(os.path.join(self.data, "live_open_context.json"), "w") as f:
            json.dump({"AAAUSDT": {}, "BBBUSDT": {}}, f)
        c = O.build_report(self.data)["live_closed_checks"]
        self.assertEqual((c["live_closed_trades"], c["estimated_not_real"], c["rows_with_a_fee_field"], c["live_open_context_entries"]), (3, 1, 1, 2))
        self.assertFalse(c["fee_cannot_be_checked_per_trade"])


class CodeFacts(unittest.TestCase):
    """The facts printed in the report are READ from the code today. If live_recorder.py changes, these fail and the facts
    (and README4) must be re-checked on purpose."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "backend", "recovered_bot", "live_recorder.py"), encoding="utf-8") as f:
            cls.src = f.read()

    def test_fee_assets_are_usdt_usdc_busd_only(self):
        self.assertIn('_FEE_ASSETS = ("USDT", "USDC", "BUSD")', self.src)
        self.assertNotIn("BNB", self.src.upper().split("_FEE_ASSETS")[1][:60])

    def test_live_pnl_is_realized_minus_commission(self):
        self.assertIn('gross = sum(_f(t.get("realizedPnl")) for t in trades)', self.src)
        self.assertIn("pnl = gross - fees", self.src)

    def test_funding_is_not_read_anywhere(self):
        self.assertNotIn("funding", self.src.lower())
        self.assertNotIn("income", self.src.lower())

    def test_unreadable_history_means_estimated(self):
        self.assertIn("estimated = True", self.src)
        self.assertIn("estimated=estimated", self.src)


class Output(Base):
    def test_cli_writes_a_private_clean_report_and_the_module_stays_offline(self):
        key = "AbCdEf" + "0123456789" * 4
        self.db([pos(1, symbol=key)])
        out = os.path.join(self.dir, "o.json")
        self.assertEqual(O.main(["--data", self.data, "--out", out]), 0)
        with open(out) as f:
            text = f.read()
        self.assertNotIn(key, text)
        self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o600)
        self.assertIn("code_facts", text)
        with open(os.path.join(ROOT, "backend", "v2_pnl_open.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                names.add((n.module or "").split(".")[0])
        self.assertEqual(names, {"argparse", "json", "os", "sys", "time", "v2_inv_redact", "v2_inv_safe", "v2_inventory", "v2_pnl"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
