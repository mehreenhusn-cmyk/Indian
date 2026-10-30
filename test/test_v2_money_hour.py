"""Part 8 test: backend/v2_money_hour.py (Money Map 1: result after fees by hour / session, read-only). Offline, writes only into temp folders.
Main question: can a thin or lucky hour ever be named a winner, and can boxes or fees be mixed up? (They must not.)
Run:  python3 test/test_v2_money_hour.py"""
import ast
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_money_hour as M

DAY0 = (int(time.time()) // 86400 - 20) * 86400          # 00:00 UTC, 20 days ago


def tr(i, hour, pnl, day=0, **kw):
    """New-style paper trade (fee inside pnl), opened at <hour>:01 UTC on day DAY0+day."""
    t = {"id": i, "symbol": "AAAUSDT", "bot": "b1", "invest_usdt": 100.0, "pnl_usdt": pnl, "roi_pct": pnl, "fee_applied": True, "fee_usdt": 1.0,
         "opened_at_ts": DAY0 + day * 86400 + hour * 3600 + 60, "closed_at_ts": DAY0 + day * 86400 + hour * 3600 + 900}
    t.update(kw)
    return t


def many(start, n, hour, pnl):
    return [tr(start + i, hour, pnl, day=i % 15) for i in range(n)]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2m_")
        self.data = os.path.join(self.dir, "data")
        os.makedirs(self.data)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self._sock = socket.socket
        socket.socket = self._no_net
        self.addCleanup(setattr, socket, "socket", self._sock)

    @staticmethod
    def _no_net(*a, **k):
        raise AssertionError("network used")

    def write(self, name, rows):
        with open(os.path.join(self.data, name), "w") as f:
            for r in rows:
                f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")

    def box(self, rows, name="b1", **kw):
        self.write("closed_trades_archive.jsonl" if name == "b1" else "closed_trades_archive_b2.jsonl", rows)
        return M.build_report(self.data, **kw)["boxes"]["paper_b1" if name == "b1" else "paper_b2"]


class FakeWinnerGuard(Base):
    def test_29_trades_is_not_enough_data_and_never_ranked(self):
        b = self.box(many(1, 29, 10, 5.0))
        self.assertEqual(b["by_hour_utc"]["10"]["verdict"], "NOT ENOUGH DATA")
        self.assertEqual(b["candidate_hours_utc"], [])
        self.assertIn("no winner is named", b["summary"])

    def test_30_steady_trades_become_a_candidate(self):
        b = self.box(many(1, 30, 10, 2.0))
        self.assertEqual(b["by_hour_utc"]["10"]["verdict"], "CANDIDATE")
        self.assertEqual(b["candidate_hours_utc"], ["10"])

    def test_one_lucky_trade_is_mixed_not_candidate(self):
        rows = many(1, 29, 10, -1.0) + [tr(99, 10, 200.0, day=3)]
        h = self.box(rows)["by_hour_utc"]["10"]
        self.assertGreater(h["net_usdt"], 0)
        self.assertLess(h["net_without_best_trade_usdt"], 0)
        self.assertEqual(h["verdict"], "MIXED")

    def test_profit_only_in_first_half_is_mixed(self):
        rows = [tr(i, 10, 5.0, day=0) for i in range(15)] + [tr(100 + i, 10, -1.0, day=10) for i in range(15)]
        h = self.box(rows)["by_hour_utc"]["10"]
        self.assertGreater(h["net_usdt"], 0)
        self.assertLess(h["second_half_net_usdt"], 0)
        self.assertEqual(h["verdict"], "MIXED")

    def test_losing_hour_is_negative_and_listed_as_worst(self):
        b = self.box(many(1, 30, 3, -2.0))
        self.assertEqual(b["by_hour_utc"]["03"]["verdict"], "NEGATIVE")
        self.assertEqual(b["worst_hours_utc"], ["03"])

    def test_thin_session_is_not_enough_data_too(self):
        b = self.box(many(1, 10, 2, 5.0))
        self.assertEqual(b["by_session_utc"]["ASIA"]["verdict"], "NOT ENOUGH DATA")


class Money(Base):
    def test_old_trade_without_fee_gets_the_fee_estimated(self):
        old = {"id": 1, "symbol": "OLD", "bot": "b1", "invest_usdt": 100.0, "pnl_usdt": 3.0, "roi_pct": 3.0, "opened_at_ts": DAY0 + 36060, "closed_at_ts": DAY0 + 37000}
        self.assertAlmostEqual(M.net_fee_correct(old, 1.0), 2.0)
        self.assertAlmostEqual(M.net_fee_correct(old, 0.5), 2.5)
        self.assertAlmostEqual(M.net_fee_correct(tr(2, 10, 3.0), 1.0), 3.0)          # fee already inside: nothing taken twice
        self.assertAlmostEqual(M.net_fee_correct({"source": "live", "invest_usdt": 100, "pnl_usdt": 4.0}, 1.0), 4.0)
        self.assertIsNone(M.net_fee_correct({"id": 3}, 1.0))

    def test_old_fee_changes_the_hour_result(self):
        rows = [{"id": i, "symbol": "OLD", "bot": "b1", "invest_usdt": 100.0, "pnl_usdt": 0.5, "roi_pct": 0.5, "opened_at_ts": DAY0 + (i % 15) * 86400 + 36060,
                 "closed_at_ts": DAY0 + (i % 15) * 86400 + 37000} for i in range(30)]
        h = self.box(rows, fee_roi=1.0)["by_hour_utc"]["10"]
        self.assertAlmostEqual(h["net_usdt"], -15.0, places=3)               # 30 x (0.5 - 1.0)
        self.assertEqual(h["verdict"], "NEGATIVE")

    def test_duplicate_trade_counts_once(self):
        t = tr(1, 10, 5.0)
        self.assertEqual(self.box([t, dict(t), dict(t)])["trades_used"], 1)

    def test_boxes_stay_separate_and_nothing_is_added_up(self):
        self.write("closed_trades_archive.jsonl", [tr(1, 10, 5.0), tr(2, 10, 5.0, source="live"), tr(3, 10, 5.0, source="live", estimated=True)])
        self.write("closed_trades_archive_b2.jsonl", [tr(4, 10, 5.0, bot="b2")])
        rep = M.build_report(self.data)
        self.assertEqual({k: v["trades_used"] for k, v in rep["boxes"].items()}, {"real_live": 1, "live_estimated": 1, "paper_b1": 1, "paper_b2": 1})
        txt = json.dumps(rep).lower()
        for bad in ("total", "combined", "all_boxes"):
            self.assertNotIn('"%s' % bad, txt)

    def test_real_live_with_6_trades_has_no_winner_anywhere(self):
        b = M.build_report(self.write("closed_trades_archive.jsonl", [tr(i, 10, 9.0, source="live") for i in range(6)]) or self.data)["boxes"]["real_live"]
        self.assertEqual(b["trades_used"], 6)
        self.assertTrue(all(v["verdict"] == "NOT ENOUGH DATA" for v in b["by_hour_utc"].values()))
        self.assertTrue(all(v["verdict"] == "NOT ENOUGH DATA" for v in b["by_session_utc"].values()))
        self.assertEqual(b["candidate_hours_utc"], [])


class Time(Base):
    def test_entry_time_is_used_not_close_time(self):
        t = tr(1, 10, 1.0)
        t["closed_at_ts"] = DAY0 + 15 * 3600                                  # closed 5 hours later
        b = self.box([t])
        self.assertEqual(b["by_hour_utc"]["10"]["trades"], 1)
        self.assertEqual(b["by_hour_utc"]["15"]["trades"], 0)
        self.assertEqual(b["stats"]["time_from_close"], 0)

    def test_missing_entry_time_falls_back_to_close_and_is_counted(self):
        t = tr(1, 12, 1.0)
        del t["opened_at_ts"]
        b = self.box([t])
        self.assertEqual(b["by_hour_utc"]["12"]["trades"], 1)
        self.assertEqual(b["stats"]["time_from_close"], 1)

    def test_no_time_or_no_pnl_is_skipped_and_counted(self):
        a, c = tr(1, 10, 1.0), tr(2, 10, 1.0, pnl_usdt=None)
        del a["opened_at_ts"], a["closed_at_ts"]
        st = self.box([a, c, tr(3, 10, 1.0)])["stats"]
        self.assertEqual((st["used"], st["skipped_no_time"], st["skipped_no_pnl"]), (1, 1, 1))

    def test_session_borders_and_ist_label(self):
        self.assertEqual([M.session_of(h) for h in (0, 7, 8, 15, 16, 23)], ["ASIA", "ASIA", "EUROPE", "EUROPE", "US", "US"])
        self.assertEqual(M.ist_label(0), "05:30 IST")
        self.assertEqual(M.ist_label(19), "00:30 IST")
        self.assertEqual(M.ist_label(23), "04:30 IST")

    def test_session_adds_up_its_hours_only(self):
        b = self.box(many(1, 30, 9, 1.0) + many(100, 30, 20, -1.0))
        self.assertEqual(b["by_session_utc"]["EUROPE"]["trades"], 30)
        self.assertEqual(b["by_session_utc"]["US"]["trades"], 30)
        self.assertEqual(b["by_session_utc"]["ASIA"]["trades"], 0)


class ReadOnly(Base):
    def snap(self):
        out = {}
        for n in sorted(os.listdir(self.data)):
            with open(os.path.join(self.data, n), "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()
        return out

    def test_data_files_and_folder_are_untouched_and_one_file_is_written(self):
        self.write("closed_trades_archive.jsonl", many(1, 30, 10, 1.0))
        before, names = self.snap(), sorted(os.listdir(self.data))
        out = os.path.join(self.dir, "out.json")
        self.assertEqual(M.main(["--data", self.data, "--out", out]), 0)
        self.assertEqual(before, self.snap())
        self.assertEqual(names, sorted(os.listdir(self.data)))
        with open(out) as f:
            self.assertTrue(json.load(f)["read_only"])

    def test_missing_data_folder_gives_an_error_not_a_crash(self):
        self.assertIn("error", M.build_report(os.path.join(self.dir, "nope")))

    def test_a_secret_in_the_data_never_reaches_the_report_file(self):
        secret = "sk_live_abcdefghijklmnop1234567890"
        self.write("closed_trades_archive.jsonl", many(1, 3, 10, 1.0))
        out = os.path.join(self.dir, "o.json")
        orig = M.build_report
        M.build_report = lambda *a, **k: {"tool": "x", "api_secret": secret, "note": "key " + secret}
        self.addCleanup(setattr, M, "build_report", orig)
        M.main(["--data", self.data, "--out", out])
        if os.path.exists(out):
            with open(out) as f:
                self.assertNotIn(secret, f.read())

    def test_source_has_no_network_or_trading_imports_and_opens_nothing_for_writing(self):
        with open(os.path.join(ROOT, "backend", "v2_money_hour.py")) as f:
            src = f.read()
        mods = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add((n.module or "").split(".")[0])
        for bad in ("socket", "requests", "urllib", "http", "sqlite3", "ccxt", "binance", "app", "strategy", "paper_trader", "live_recorder"):
            self.assertNotIn(bad, mods)
        self.assertNotIn("open(", src.replace("def ", ""))                   # all reading goes through Part 5 / Part 1 safe readers


if __name__ == "__main__":
    unittest.main(verbosity=1)
