"""Part 7 test: backend/v2_check_all.py (one command, one file, read-only). Offline, no network, temp folders only.
Run:  python3 test/test_v2_check_all.py"""
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
import v2_check_all as C
import v2_inv_safe as S
import v2_pnl_open as O

NOW = time.time()


def closed(i, pnl=1.0, **kw):
    t = {"id": i, "bot": "b1", "invest_usdt": 100.0, "pnl_usdt": pnl, "roi_pct": pnl, "closed_at_ts": NOW - 100 - (i if isinstance(i, int) else 0)}
    t.update(kw)
    return t


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2c_")
        self.data = os.path.join(self.dir, "data")
        os.makedirs(self.data)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._sock = socket.socket
        socket.socket = self._no_net
        self.addCleanup(setattr, socket, "socket", self._sock)

    @staticmethod
    def _no_net(*a, **k):
        raise AssertionError("network used")

    def archive(self, rows, name="closed_trades_archive.jsonl"):
        with open(os.path.join(self.data, name), "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)

    def side_db(self, name, n, mode_values=("paper",)):
        con = sqlite3.connect(os.path.join(self.data, name))
        con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, open_time INTEGER, mode TEXT)")
        for i in range(n):
            con.execute("INSERT INTO trades (symbol, open_time, mode) VALUES (?,?,?)",
                        ("AAA", int(NOW * 1000) - i * 60000, mode_values[i % len(mode_values)]))
        con.commit()
        con.close()

    def positions_db(self, rows):
        con = sqlite3.connect(os.path.join(self.data, "owl.db"))
        con.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated_at REAL NOT NULL)")
        for i, p in enumerate(rows, 1):
            con.execute("INSERT INTO positions VALUES (?,?,?)", (i, json.dumps(p), NOW - 1))
        con.commit()
        con.close()


class Worlds(Base):
    def test_every_world_is_separate_and_nothing_is_added_together(self):
        self.archive([closed(i) for i in range(1, 321)] + [closed(900, 5.0, source="live"), closed(901, 2.0, source="live", estimated=True)])
        self.archive([closed(5, 7.0, bot="b2")], "closed_trades_archive_b2.jsonl")
        self.side_db("dual_archive.db", 50)
        r = C.build_report(self.data)
        w = r["worlds"]
        self.assertEqual(set(w), set(C.WORLDS))
        self.assertEqual([w[k]["closed"]["trades"] for k in ("real_live", "live_estimated", "paper_main", "paper_bot2", "dual_bot", "brain")],
                         [1, 1, 320, 1, 50, 0])
        for bad in ("total", "grand_total", "all_worlds", "combined"):
            self.assertNotIn(bad, json.dumps(r["worlds"]).lower())
        self.assertEqual(r["sections_failed"], [])

    def test_verdicts(self):
        self.archive([closed(i, 1.0, fee_applied=True, fee_usdt=0.0, fee_roi_pct=0.0, gross_roi_pct=1.0) for i in range(1, 321)])
        w = C.build_report(self.data)["worlds"]
        self.assertEqual(w["paper_main"]["closed"]["verdict"], "TRUSTED")
        self.assertEqual(w["brain"]["closed"]["verdict"], "NOT COLLECTED")
        self.assertEqual(w["real_live"]["closed"]["verdict"], "NOT COLLECTED")

    def test_old_trades_without_fee_and_few_trades_mean_use_with_care(self):
        self.archive([closed(i) for i in range(1, 6)])
        c = C.build_report(self.data)["worlds"]["paper_main"]["closed"]
        self.assertEqual(c["verdict"], "USE WITH CARE")
        self.assertTrue(any("fee is estimated" in x for x in c["reasons"]))
        self.assertTrue(any("5 trades" in x for x in c["reasons"]))

    def test_live_worlds_always_carry_the_fee_and_estimate_warnings(self):
        self.archive([closed(1, 5.0, source="live"), closed(2, 2.0, source="live", estimated=True)])
        w = C.build_report(self.data)["worlds"]
        self.assertTrue(any("funding" in x for x in w["real_live"]["closed"]["reasons"]))
        self.assertTrue(any("estimated from the last price" in x for x in w["live_estimated"]["closed"]["reasons"]))

    def test_a_flagged_check_is_a_reason(self):
        self.archive([closed(1), closed(1)])
        c = C.build_report(self.data)["worlds"]["paper_main"]["closed"]
        self.assertTrue(any(x.startswith("duplicate_trade") for x in c["reasons"]))


class SideWorlds(Base):
    def test_a_live_value_in_dual_bot_or_brain_is_flagged(self):
        self.side_db("dual_archive.db", 40, ("paper", "paper", "live"))
        self.side_db("brain_archive.db", 40, ("paper",))
        w = C.build_report(self.data)["worlds"]
        self.assertTrue(any("must be paper only" in x for x in w["dual_bot"]["closed"]["reasons"]))
        self.assertFalse(any("must be paper only" in x for x in w["brain"]["closed"]["reasons"]))
        self.assertEqual(w["brain"]["closed"]["trades"], 40)

    def test_open_positions_stay_in_their_own_world_and_are_never_real_money(self):
        pos = {"symbol": "AAAUSDT", "action": "BUY", "entry_price": 100.0, "ltp": 101.0, "invest_usdt": 100.0, "leverage": 10,
               "fee_roi_pct": 1.0, "pnl_usdt": 9.0, "bot": "b1", "opened_at_ts": NOW - 60}
        self.positions_db([pos, dict(pos, symbol="BBBUSDT", bot="b2"), dict(pos, symbol="CCCUSDT", source="live")])
        r = C.build_report(self.data)
        o = {k: v["open"] for k, v in r["worlds"].items() if v["open"]}
        self.assertEqual({k: v["positions"] for k, v in o.items()}, {"paper_main": 1, "paper_bot2": 1, "real_live": 1})
        self.assertTrue(all(v["is_real_money"] is False for v in o.values()))
        self.assertTrue(any("open: 1 positions" in line for line in r["owner_summary"]))


class Robust(Base):
    def test_one_failing_section_is_reported_and_the_report_still_comes(self):
        orig = O.build_report
        O.build_report = lambda *a, **k: 1 / 0
        try:
            r = C.build_report(self.data)
        finally:
            O.build_report = orig
        self.assertEqual(r["sections_failed"], ["open_pnl"])
        self.assertEqual(r["details"]["open_pnl"]["reason"][:17], "ZeroDivisionError")
        self.assertIn("inventory", r["details"])
        self.assertEqual(r["owner_summary"], ["a section failed: see sections_failed"])

    def test_missing_folder_stops_with_a_clear_message(self):
        self.assertEqual(C.build_report(os.path.join(self.dir, "nope"))["error"], "data folder not found")
        self.assertEqual(C.main(["--data", os.path.join(self.dir, "nope"), "--out", os.path.join(self.dir, "o.json")]), 1)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "o.json")))

    def test_empty_data_folder_is_all_not_collected(self):
        w = C.build_report(self.data)["worlds"]
        self.assertTrue(all(v["closed"]["verdict"] == "NOT COLLECTED" for v in w.values() if v["closed"]))


class Output(Base):
    def test_one_private_clean_file_and_the_data_is_untouched(self):
        key = "AbCdEf" + "0123456789" * 4
        self.archive([closed(i) for i in range(1, 50)] + [closed(key, 1.0, roi_pct=40.0)])
        self.side_db("dual_archive.db", 5)
        names = ("closed_trades_archive.jsonl", "dual_archive.db")
        before = {n: S.source_fingerprints(os.path.join(self.data, n)) for n in names}
        listing = sorted(os.listdir(self.data))
        outdir = os.path.join(self.dir, "out")
        os.makedirs(outdir)
        out = os.path.join(outdir, "owl_check_all.json")
        self.assertEqual(C.main(["--data", self.data, "--out", out]), 0)
        self.assertEqual(os.listdir(outdir), ["owl_check_all.json"])
        with open(out) as f:
            text = f.read()
        self.assertNotIn(key, text)
        self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o600)
        for k in ("worlds", "owner_summary", "details", "code_facts"):
            self.assertIn(k, text)
        self.assertEqual({n: S.source_fingerprints(os.path.join(self.data, n)) for n in names}, before)
        self.assertEqual(sorted(os.listdir(self.data)), listing)

    def test_module_has_no_network_or_trading_imports(self):
        with open(os.path.join(ROOT, "backend", "v2_check_all.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                names.add((n.module or "").split(".")[0])
        self.assertEqual(names, {"argparse", "os", "sys", "time", "v2_inv_redact", "v2_inventory", "v2_pnl", "v2_pnl_open"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
