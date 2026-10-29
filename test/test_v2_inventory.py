"""Part 3 test: backend/v2_inventory.py (read-only data inventory). Offline, no network, no trading module.
Run:  python3 test/test_v2_inventory.py"""
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
import v2_inventory as I

NOW_MS = int(time.time() * 1000)


def make_trades(path, n, wal=False, mode_col=True, ts=None):
    con = sqlite3.connect(path)
    if wal:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT, timeframe TEXT, open_time INTEGER%s)"
                % (", mode TEXT" if mode_col else ""))
    for i in range(n):
        t = NOW_MS - (n - i) * 60000 if ts is None else ts
        if mode_col:
            con.execute("INSERT INTO trades (symbol, timeframe, open_time, mode) VALUES (?,?,?,?)",
                        ("BTC%d" % (i % 4), "5m" if i % 2 else "15m", t, "paper" if i % 3 else "live"))
        else:
            con.execute("INSERT INTO trades (symbol, timeframe, open_time) VALUES (?,?,?)", ("BTC", "5m", t))
    con.commit()
    return con


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2i_")
        self.data = os.path.join(self.dir, "data")
        os.makedirs(self.data)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._sock = socket.socket
        socket.socket = self._no_net
        self.addCleanup(setattr, socket, "socket", self._sock)

    @staticmethod
    def _no_net(*a, **k):
        raise AssertionError("network used")

    def file(self, name):
        return os.path.join(self.data, name)


class Labels(unittest.TestCase):
    def test_label_rules(self):
        self.assertEqual(I.label(0, True), "Not collected")
        self.assertEqual(I.label(500, False), "Data incomplete")
        self.assertEqual(I.label(29, True), "Insufficient data")
        self.assertEqual(I.label(30, True), "Exploratory")
        self.assertEqual(I.label(299, True), "Exploratory")
        self.assertEqual(I.label(300, True), "Watch")

    def test_iso_handles_seconds_millis_and_text(self):
        self.assertEqual(I.iso(1700000000)[0], "2023-11-14 22:13:20 UTC")
        self.assertEqual(I.iso(1700000000000)[0], "2023-11-14 22:13:20 UTC")
        self.assertEqual(I.iso("2026-10-30 04:21")[1], "text")
        self.assertEqual(I.iso(12)[1], "number")


class Databases(Base):
    def test_table_numbers_and_labels(self):
        make_trades(self.file("a.db"), 400).close()
        make_trades(self.file("small.db"), 5).close()
        sqlite3.connect(self.file("empty.db")).execute("CREATE TABLE t (id INTEGER)").connection.commit()
        rep = I.build_report(self.data)
        a = rep["files"]["a.db"]["tables"][0]
        self.assertEqual((a["rows"], a["label"], a["safe_for_research"]), (400, "Watch", True))
        self.assertEqual(a["symbols_distinct"], 4)
        self.assertEqual(set(a["timeframes"]), {"5m", "15m"})
        self.assertEqual(a["time"]["zone"], "UTC (epoch numbers)")
        self.assertEqual(a["paper_live_column"]["column"], "mode")
        self.assertEqual(rep["files"]["small.db"]["tables"][0]["label"], "Insufficient data")
        self.assertEqual(rep["files"]["empty.db"]["tables"][0]["label"], "Not collected")
        self.assertEqual(rep["summary"]["files_seen"], 3)

    def test_without_mode_column_paper_live_is_nv(self):
        make_trades(self.file("b.db"), 40, mode_col=False).close()
        t = I.build_report(self.data)["files"]["b.db"]["tables"][0]
        self.assertTrue(t["paper_live_mix"].startswith("NV"))
        self.assertNotIn("paper_live_column", t)

    def test_duplicates_and_future_times_are_flagged(self):
        con = make_trades(self.file("d.db"), 50, mode_col=False, ts=NOW_MS - 1000)      # same symbol + same time 50 times
        con.close()
        t = I.build_report(self.data)["files"]["d.db"]["tables"][0]
        self.assertEqual(t["duplicate_rows"], 49)
        make_trades(self.file("f.db"), 40, mode_col=False, ts=NOW_MS + 10 * 86400000).close()
        f = I.build_report(self.data)["files"]["f.db"]["tables"][0]
        self.assertIn("timestamps in the future", f["problems"])
        self.assertEqual((f["label"], f["safe_for_research"]), ("Exploratory", False))

    def test_no_time_column_is_data_incomplete(self):
        con = sqlite3.connect(self.file("n.db"))
        con.execute("CREATE TABLE x (a INTEGER, b TEXT)")
        con.executemany("INSERT INTO x VALUES (?,?)", [(i, "v") for i in range(100)])
        con.commit()
        con.close()
        t = I.build_report(self.data)["files"]["n.db"]["tables"][0]
        self.assertEqual(t["label"], "Data incomplete")
        self.assertIn("no time column found", t["problems"])

    def test_sources_are_never_changed_and_no_side_files_appear(self):
        make_trades(self.file("r.db"), 60).close()
        w = make_trades(self.file("w.db"), 60, wal=True)                                 # WAL db kept open = live writer
        before = {n: S.source_fingerprints(self.file(n)) for n in ("r.db", "w.db")}
        listing = sorted(os.listdir(self.data))
        rep = I.build_report(self.data)
        self.assertEqual({n: S.source_fingerprints(self.file(n)) for n in ("r.db", "w.db")}, before)
        self.assertEqual(sorted(os.listdir(self.data)), listing)                          # no new -wal / -shm / temp files
        self.assertIn("copied snapshot", rep["files"]["w.db"]["open_mode"])
        self.assertEqual(rep["files"]["r.db"]["open_mode"], "direct read-only")
        w.close()

    def test_corrupt_db_is_reported_not_crashed(self):
        with open(self.file("bad.db"), "wb") as f:
            f.write(b"not a database" * 300)
        make_trades(self.file("ok.db"), 40).close()
        rep = I.build_report(self.data)
        self.assertEqual(rep["files"]["bad.db"]["status"], "not opened")
        self.assertEqual(rep["files"]["bad.db"]["label"], "Data incomplete")
        self.assertEqual(rep["files"]["ok.db"]["tables"][0]["rows"], 40)


class TextFiles(Base):
    def test_json_gives_key_names_only(self):
        with open(self.file("settings.json"), "w") as f:
            json.dump({"leverage": 10, "api": {"note": "x"}, "list": [{"a": 1}]}, f)
        r = I.build_report(self.data)["files"]["settings.json"]
        self.assertEqual(r["key_paths"], ["api", "api.note", "leverage", "list", "list[].a"])
        self.assertNotIn("values", r)

    def test_jsonl_and_csv_counts(self):
        with open(self.file("e.jsonl"), "w") as f:
            f.write('{"s":"BTC","t":1}\n' * 40)
        with open(self.file("c.csv"), "w") as f:
            f.write("symbol,time,price\n" + "BTC,1,2\n" * 350)
        rep = I.build_report(self.data)["files"]
        self.assertEqual((rep["e.jsonl"]["lines"], rep["e.jsonl"]["label"]), (40, "Exploratory"))
        self.assertEqual((rep["c.csv"]["lines"], rep["c.csv"]["label"]), (351, "Watch"))
        self.assertEqual(rep["c.csv"]["header_columns"], ["symbol", "time", "price"])


class Safety(Base):
    def test_symlink_pointing_outside_is_not_read(self):
        outside = os.path.join(self.dir, "outside.db")
        make_trades(outside, 40).close()
        os.symlink(outside, self.file("link.db"))
        r = I.build_report(self.data)["files"]["link.db"]
        self.assertEqual(r["status"], "not opened")
        self.assertNotIn("tables", r)

    def test_report_never_holds_a_secret_and_refuses_when_one_slips_in(self):
        key = "AbCdEf" + "0123456789" * 4                                               # built at run time, not stored
        with open(self.file("x.json"), "w") as f:
            json.dump({"binance_" + key: 1, "ok": 2}, f)
        out = os.path.join(self.dir, "rep.json")
        self.assertEqual(I.main(["--data", self.data, "--out", out]), 0)
        with open(out) as fh:
            text = fh.read()
        self.assertNotIn(key, text)
        self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o600)
        self.assertIn("read_only", text)
        out2 = os.path.join(self.dir, "rep2.json")
        orig = I.build_report
        I.build_report = lambda d: {"summary": {}, "files": {"leak": object()}}      # a value the scrubber cannot clean -> refuse
        try:
            self.assertEqual(I.main(["--data", self.data, "--out", out2]), 2)
        finally:
            I.build_report = orig
        self.assertFalse(os.path.exists(out2))

    def test_missing_data_folder_is_a_clear_report(self):
        rep = I.build_report(os.path.join(self.dir, "nope"))
        self.assertEqual(rep["summary"]["error"], "data folder not found")

    def test_module_has_no_network_or_trading_imports(self):
        with open(os.path.join(ROOT, "backend", "v2_inventory.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                names.add((n.module or "").split(".")[0])
        self.assertEqual(names, {"argparse", "datetime", "json", "os", "sys", "time", "v2_inv_redact", "v2_inv_safe"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
