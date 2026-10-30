"""Part 5 test: backend/v2_pnl.py (read-only realized P&L check). Offline, no network, writes only into temp folders.
Main question: can real money, paper money and old no-fee trades ever get mixed into one number? (They must not.)
Run:  python3 test/test_v2_pnl_contamination.py"""
import ast
import json
import os
import shutil
import socket
import stat
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_inv_safe as S
import v2_pnl as P

NOW = time.time()


def trade(i, pnl, **kw):
    """A new-style paper trade: invest 100, fee 1 USDT already inside pnl (fee_applied)."""
    t = {"id": i, "symbol": "AAAUSDT", "bot": "b1", "invest_usdt": 100.0, "pnl_usdt": pnl, "roi_pct": pnl,
         "gross_roi_pct": (pnl or 0.0) + 1.0, "fee_roi_pct": 1.0, "fee_usdt": 1.0, "fee_applied": True,
         "closed_at_ts": NOW - 1000 - (i if isinstance(i, int) else 0)}
    t.update(kw)
    return t


def old_trade(i, pnl, **kw):
    t = {"id": i, "symbol": "OLDUSDT", "bot": "b1", "invest_usdt": 100.0, "pnl_usdt": pnl, "roi_pct": pnl, "closed_at_ts": NOW - 5000 - i}
    t.update(kw)
    return t


def live_trade(i, pnl, **kw):
    t = {"id": i, "symbol": "LIVEUSDT", "source": "live", "invest_usdt": 100.0, "pnl_usdt": pnl, "roi_pct": pnl, "closed_at_ts": NOW - 300 - i}
    t.update(kw)
    return t


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2p_")
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

    def report(self, **kw):
        return P.build_report(self.data, **kw)


class Boxes(Base):
    def test_live_paper_and_bot2_never_share_a_box_or_a_total(self):
        self.write("closed_trades_archive.jsonl", [trade(1, 5.0), trade(2, -2.0), live_trade(3, 10.0), live_trade(4, 4.0, estimated=True)])
        self.write("closed_trades_archive_b2.jsonl", [trade(5, 7.0, bot="b2")])
        b = self.report()["boxes"]
        self.assertEqual({k: (v["trades"], v["net_recorded_usdt"]) for k, v in b.items()},
                         {"real_live": (1, 10.0), "live_estimated": (1, 4.0), "paper_b1": (2, 3.0), "paper_b2": (1, 7.0)})
        self.assertNotIn("total", self.report())
        self.assertNotIn("grand_total", self.report())

    def test_wins_and_losses(self):
        self.write("closed_trades_archive.jsonl", [trade(1, 5.0), trade(2, -2.0), trade(3, 0.0)])
        b = self.report()["boxes"]["paper_b1"]
        self.assertEqual((b["wins"], b["losses"], b["trades"]), (1, 1, 3))

    def test_estimated_live_trade_is_not_real_money(self):
        self.write("closed_trades_archive.jsonl", [live_trade(1, 9.0, estimated=True)])
        b = self.report()["boxes"]
        self.assertEqual((b["real_live"]["trades"], b["live_estimated"]["trades"]), (0, 1))


class Fees(Base):
    def test_applied_fee_gives_gross_and_keeps_net(self):
        self.write("closed_trades_archive.jsonl", [trade(1, 5.0)])
        b = self.report()["boxes"]["paper_b1"]
        self.assertEqual((b["net_recorded_usdt"], b["net_fee_correct_usdt"], b["gross_usdt_known"], b["fee_applied_usdt"]), (5.0, 5.0, 6.0, 1.0))
        self.assertEqual(b["by_fee_basis"], {"applied": 1})
        self.assertFalse(b["needs_fee_estimate"])

    def test_old_trade_without_fee_gets_an_estimated_fee_and_is_marked(self):
        self.write("closed_trades_archive.jsonl", [old_trade(1, 5.0)])
        b = self.report()["boxes"]["paper_b1"]
        self.assertEqual((b["net_recorded_usdt"], b["net_fee_correct_usdt"], b["fee_estimated_usdt"], b["fee_applied_usdt"]), (5.0, 4.0, 1.0, 0.0))
        self.assertTrue(b["needs_fee_estimate"])
        self.assertEqual(self.report(fee_roi=0.5)["boxes"]["paper_b1"]["net_fee_correct_usdt"], 4.5)

    def test_the_fee_setting_never_changes_trades_that_already_carry_a_fee(self):
        self.write("closed_trades_archive.jsonl", [trade(1, 5.0), live_trade(2, 8.0)])
        a, c = self.report(fee_roi=0.0)["boxes"], self.report(fee_roi=3.0)["boxes"]
        self.assertEqual(a["paper_b1"]["net_fee_correct_usdt"], c["paper_b1"]["net_fee_correct_usdt"])
        self.assertEqual(c["real_live"]["net_fee_correct_usdt"], 8.0)

    def test_live_trade_fee_is_reported_as_not_verified(self):
        self.write("closed_trades_archive.jsonl", [live_trade(1, 8.0)])
        b = self.report()["boxes"]["real_live"]
        self.assertEqual(b["by_fee_basis"], {"live": 1})
        self.assertEqual(b["gross_usdt_known"], 0.0)                              # gross is unknown, never invented


class Checks(Base):
    def flags(self, rows, box="paper_b1", fname="closed_trades_archive.jsonl"):
        self.write(fname, rows)
        return {k: v for k, v in self.report()["boxes"][box]["checks"].items() if v["count"]}

    def test_duplicate_is_flagged_and_counted_once(self):
        self.write("closed_trades_archive.jsonl", [trade(1, 5.0), trade(1, 5.0)])
        b = self.report()["boxes"]["paper_b1"]
        self.assertEqual((b["trades"], b["net_recorded_usdt"], b["checks"]["duplicate_trade"]["count"]), (1, 5.0, 1))

    def test_missing_and_future_times_and_missing_pnl(self):
        f = self.flags([trade(1, 5.0, closed_at_ts=None), trade(2, 5.0, closed_at_ts=NOW + 10 * 86400), trade(3, None)])
        self.assertEqual(set(f), {"missing_close_time", "future_close_time", "missing_pnl"})
        self.assertEqual(f["missing_pnl"]["examples"], ["3"])

    def test_pnl_that_does_not_match_roi_times_invest(self):
        self.assertEqual(set(self.flags([trade(1, 5.0, roi_pct=9.0, gross_roi_pct=10.0)])), {"pnl_not_roi_times_invest"})
        self.assertEqual(self.flags([trade(1, 5.0)]), {})

    def test_gross_minus_fee_must_equal_net(self):
        self.assertEqual(set(self.flags([trade(1, 5.0, gross_roi_pct=9.0)])), {"gross_minus_fee_not_net"})

    def test_live_trade_with_a_paper_style_fee_is_flagged(self):
        f = self.flags([live_trade(1, 5.0, fee_applied=True)], box="real_live")
        self.assertEqual(set(f), {"live_trade_with_paper_fee"})

    def test_a_bot2_row_in_the_main_archive_and_the_reverse_are_flagged(self):
        self.assertEqual(set(self.flags([trade(1, 5.0, bot="b2")])), {"wrong_box"})
        f = self.flags([trade(2, 5.0, bot="b1")], box="paper_b2", fname="closed_trades_archive_b2.jsonl")
        self.assertEqual(set(f), {"wrong_box"})

    def test_a_box_with_any_flag_is_not_trusted_for_research(self):
        self.write("closed_trades_archive.jsonl", [trade(i, 1.0) for i in range(1, 320)])
        b = self.report()["boxes"]["paper_b1"]
        self.assertEqual((b["label"], b["trusted_for_research"]), ("Watch", True))
        self.write("closed_trades_archive.jsonl", [trade(i, 1.0) for i in range(1, 320)] + [trade(999, 1.0, roi_pct=50.0, gross_roi_pct=51.0)])
        self.assertFalse(self.report()["boxes"]["paper_b1"]["trusted_for_research"])


class Sources(Base):
    def test_cache_rows_missing_from_the_archive_are_counted_not_added(self):
        self.write("closed_trades_archive.jsonl", [trade(1, 5.0)])
        with open(os.path.join(self.data, "trades.json"), "w") as f:
            json.dump({"closed_trades": [trade(1, 5.0), trade(2, 6.0)], "b2": {"closed_trades": [trade(9, 1.0, bot="b2")]}}, f)
        r = self.report()
        self.assertEqual((r["cache_check"]["b1_only_in_cache"], r["cache_check"]["b2_only_in_cache"]), (1, 1))
        self.assertEqual(r["boxes"]["paper_b1"]["net_recorded_usdt"], 5.0)

    def test_bad_lines_missing_files_and_empty_boxes_do_not_crash(self):
        self.write("closed_trades_archive.jsonl", ["not json", "[1,2]", json.dumps(trade(1, 5.0)), ""])
        r = self.report()
        self.assertEqual(r["sources"]["closed_trades_archive.jsonl"], {"lines": 3, "unparsable": 2})
        self.assertEqual(r["sources"]["closed_trades_archive_b2.jsonl"]["status"], "missing")
        self.assertEqual(r["boxes"]["paper_b2"]["label"], "Not collected")
        self.assertEqual(P.build_report(os.path.join(self.dir, "nope"))["error"], "data folder not found")

    def test_symlink_to_a_file_outside_the_data_folder_is_not_read(self):
        outside = os.path.join(self.dir, "outside.jsonl")
        with open(outside, "w") as f:
            f.write(json.dumps(trade(1, 5.0)) + "\n")
        os.symlink(outside, os.path.join(self.data, "closed_trades_archive.jsonl"))
        r = self.report()
        self.assertTrue(r["sources"]["closed_trades_archive.jsonl"]["status"].startswith("not opened"))
        self.assertEqual(r["boxes"]["paper_b1"]["trades"], 0)

    def test_files_are_never_changed(self):
        self.write("closed_trades_archive.jsonl", [trade(1, 5.0)])
        names = ("closed_trades_archive.jsonl",)
        before = {n: S.source_fingerprints(os.path.join(self.data, n)) for n in names}
        listing = sorted(os.listdir(self.data))
        self.report()
        P.main(["--data", self.data, "--out", os.path.join(self.dir, "o.json")])
        self.assertEqual({n: S.source_fingerprints(os.path.join(self.data, n)) for n in names}, before)
        self.assertEqual(sorted(os.listdir(self.data)), listing)


class Output(Base):
    def test_cli_writes_a_private_clean_report(self):
        key = "AbCdEf" + "0123456789" * 4                                           # built at run time
        self.write("closed_trades_archive.jsonl", [trade(key, 5.0, roi_pct=40.0, gross_roi_pct=41.0)])  # flagged -> its id is printed as an example
        out = os.path.join(self.dir, "o.json")
        self.assertEqual(P.main(["--data", self.data, "--out", out]), 0)
        with open(out) as f:
            text = f.read()
        self.assertNotIn(key, text)
        self.assertEqual(stat.S_IMODE(os.stat(out).st_mode), 0o600)
        self.assertIn('"read_only": true', text)

    def test_module_has_no_network_or_trading_imports(self):
        with open(os.path.join(ROOT, "backend", "v2_pnl.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        names = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                names.add((n.module or "").split(".")[0])
        self.assertEqual(names, {"argparse", "datetime", "json", "os", "sys", "time", "v2_inv_redact", "v2_inv_safe", "v2_inventory"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
