"""Part 10 test: backend/v2_leakage.py (Money Map 3: leakage map, read-only). Offline, writes only into temp folders.
Main question: are leaks measured honestly (hindsight never called real loss, break-even 'would have won' never guessed, nothing added up, boxes never mixed)?
Run:  python3 test/test_v2_leakage.py"""
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
import v2_leakage as K

DAY0 = (int(time.time()) // 86400 - 20) * 86400


def tr(i, gross, peak=None, status="CLOSED_TP4", **kw):
    """New-style paper trade: invest 100, fee 1 ROI% (1 USDT) inside net. net = gross - 1."""
    t = {"id": i, "symbol": "AAAUSDT", "bot": "b1", "invest_usdt": 100.0, "gross_roi_pct": gross, "fee_roi_pct": 1.0, "fee_usdt": 1.0, "fee_applied": True,
         "roi_pct": gross - 1.0, "pnl_usdt": gross - 1.0, "max_roi_pct": peak, "status": status, "regime_cross_n": 1,
         "opened_at_ts": DAY0 + 36060, "closed_at_ts": DAY0 + 37000 + i}
    t.update(kw)
    return t


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2k_")
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

    def box(self, rows, name="paper_b1", **kw):
        self.write("closed_trades_archive_b2.jsonl" if name == "paper_b2" else "closed_trades_archive.jsonl", rows)
        return K.build_report(self.data, **kw)["boxes"][name]

    def leaks(self, rows, **kw):
        return self.box(rows, **kw)["leaks"]


class Hindsight(Base):
    def test_gave_back_profit_is_peak_minus_close_in_usdt(self):
        L = self.leaks([tr(1, 4.0, peak=10.0), tr(2, 4.0, peak=3.0), tr(3, 6.0, peak=6.0)])["gave_back_profit"]
        self.assertEqual((L["trades"], L["usdt"], L["kind"]), (1, 6.0, "hindsight"))

    def test_peak_then_loss_needs_a_net_winner_at_the_peak(self):
        L = self.leaks([tr(1, 0.2, peak=5.0), tr(2, -3.0, peak=0.5), tr(3, 5.0, peak=9.0)])["peak_then_loss"]
        self.assertEqual((L["trades"], L["usdt"]), (1, 0.8))

    def test_hindsight_leaks_are_never_in_the_measured_ranking(self):
        rows = [tr(i, -5.0, peak=20.0, status="CLOSED_SL") for i in range(40)]
        c = self.box(rows)["context"]
        self.assertTrue(all(k not in c["biggest_measured_leaks_by_usdt"] for k in K.HINDSIGHT))
        self.assertNotIn("fee_cost", c["biggest_measured_leaks_by_usdt"])


class BreakEven(Base):
    def test_only_a_real_break_even_stop_is_counted(self):
        rows = [tr(1, 0.0, peak=6.0, status="CLOSED_SL", breakeven_auto_shifted=True),
                tr(2, 0.2, peak=6.0, status="CLOSED_SL", tp_hit_levels=[1, 2]),
                tr(3, 5.0, peak=9.0, status="CLOSED_SL", breakeven_auto_shifted=True),      # trailing stop above entry
                tr(4, 0.0, peak=6.0, status="CLOSED_SL"),                                     # stop at entry but TP1 never hit
                tr(5, -10.0, peak=1.0, status="CLOSED_SL", breakeven_auto_shifted=True),     # a normal loss
                tr(6, 0.0, peak=6.0, status="CLOSED_TP4", breakeven_auto_shifted=True)]      # not a stop
        L = self.leaks(rows)["breakeven_stop"]
        self.assertEqual((L["trades"], L["usdt"], L["fees_paid_usdt"]), (2, -1.8, 2.0))

    def test_would_have_won_is_never_guessed(self):
        L = self.leaks([tr(1, 0.0, peak=6.0, status="CLOSED_SL", breakeven_auto_shifted=True)])["breakeven_stop"]
        self.assertIn("NEEDS CANDLES", L["would_have_won"])
        self.assertNotIn("would_have_won_usdt", L)
        self.assertNotIsInstance(L["would_have_won"], (int, float))


class Sideways(Base):
    def test_only_choppy_losses_are_counted(self):
        rows = [tr(1, -4.0, regime_cross_n=3), tr(2, -4.0, regime_cross_n=2), tr(3, 6.0, regime_cross_n=4), tr(4, -2.0, regime_cross_n=5), tr(5, -9.0, regime_cross_n=None)]
        b = self.box(rows)
        L = b["leaks"]["sideways_loss"]
        self.assertEqual((L["trades"], L["usdt"], L["choppy_trades"], L["choppy_net_usdt"]), (2, -8.0, 3, -3.0))
        self.assertEqual(b["context"]["no_regime_row"], 1)


class Fees(Base):
    def test_fee_total_share_and_winners_flipped_by_fee(self):
        rows = [tr(1, 11.0), tr(2, 0.5), tr(3, -4.0)]                 # gross 11 / 0.5 / -4 ; net 10 / -0.5 / -5 ; fee 1 each
        L = self.leaks(rows)["fee_cost"]
        self.assertEqual((L["trades"], L["usdt"], L["winners_turned_loser_by_fee"]), (3, 3.0, 1))
        self.assertEqual(L["pct_of_gross_profit"], round(100 * 3.0 / 11.5, 1))

    def test_old_paper_trade_fee_is_estimated_and_follows_the_setting(self):
        old = {"id": 1, "symbol": "OLD", "bot": "b1", "invest_usdt": 100.0, "pnl_usdt": 3.0, "roi_pct": 3.0, "closed_at_ts": DAY0 + 40000}
        c = self.box([old], fee_roi=1.0)["context"]
        self.assertEqual((c["fees_usdt"], c["net_fee_correct_usdt"], c["gross_usdt_known"]), (1.0, 2.0, 3.0))
        self.assertEqual(self.box([old], fee_roi=0.5)["context"]["fees_usdt"], 0.5)

    def test_live_fee_is_unknown_and_left_out(self):
        live = {"id": 1, "symbol": "L", "source": "live", "invest_usdt": 100.0, "pnl_usdt": 4.0, "roi_pct": 4.0, "closed_at_ts": DAY0 + 40000}
        b = self.box([live], name="real_live")
        self.assertEqual((b["context"]["fee_unknown_trades"], b["leaks"]["fee_cost"]["trades"], b["context"]["fees_usdt"]), (1, 0, 0.0))


class Reversed(Base):
    def test_reversed_and_exit_reason_table(self):
        rows = [tr(1, -3.0, status="CLOSED_REVERSED"), tr(2, 5.0, status="CLOSED_REVERSED"), tr(3, 8.0, status="CLOSED_TP4"), tr(4, 1.0, status=None)]
        b = self.box(rows)
        self.assertEqual((b["leaks"]["reversed_exit"]["trades"], b["leaks"]["reversed_exit"]["usdt"]), (2, 0.0))
        self.assertEqual(b["context"]["by_exit_reason"], {"REVERSED": {"trades": 2, "net_usdt": 0.0}, "TP4": {"trades": 1, "net_usdt": 7.0}, "UNKNOWN": {"trades": 1, "net_usdt": 0.0}})


class Guards(Base):
    def test_29_is_not_enough_data_30_is_measured(self):
        self.assertEqual(self.leaks([tr(i, -3.0, status="CLOSED_REVERSED") for i in range(29)])["reversed_exit"]["verdict"], "NOT ENOUGH DATA")
        self.assertEqual(self.leaks([tr(i, -3.0, status="CLOSED_REVERSED") for i in range(30)])["reversed_exit"]["verdict"], "ENOUGH DATA")

    def test_ranking_lists_biggest_measured_leak_first_and_skips_thin_ones(self):
        rows = [tr(i, -9.0, status="CLOSED_REVERSED", regime_cross_n=1) for i in range(30)] + [tr(100 + i, -2.0, regime_cross_n=3) for i in range(30)] + [tr(200, -50.0, status="CLOSED_SL", breakeven_auto_shifted=True)]
        self.assertEqual(self.box(rows)["context"]["biggest_measured_leaks_by_usdt"], ["reversed_exit", "sideways_loss"])

    def test_nothing_is_added_up_and_boxes_stay_apart(self):
        self.write("closed_trades_archive.jsonl", [tr(1, 5.0), tr(2, 5.0, source="live"), tr(3, 5.0, source="live", estimated=True)])
        self.write("closed_trades_archive_b2.jsonl", [tr(4, 5.0, bot="b2")])
        rep = K.build_report(self.data)
        self.assertEqual({k: v["context"]["trades_used"] for k, v in rep["boxes"].items()}, {"real_live": 1, "live_estimated": 1, "paper_b1": 1, "paper_b2": 1})
        for bad in ("total", "combined", "all_boxes", "all_leaks"):
            self.assertNotIn('"%s' % bad, json.dumps(rep).lower())
        self.assertEqual({v["kind"] for v in rep["boxes"]["paper_b1"]["leaks"].values()}, {"hindsight", "measured"})

    def test_rows_without_peak_duplicates_and_no_pnl_are_counted_not_guessed(self):
        old = {"id": 7, "symbol": "OLD", "bot": "b1", "invest_usdt": 100.0, "pnl_usdt": 3.0, "roi_pct": 3.0, "closed_at_ts": DAY0 + 40000}
        a = tr(1, 4.0, peak=9.0)
        c = self.box([old, a, dict(a), tr(3, 1.0, pnl_usdt=None, roi_pct=None)])["context"]
        self.assertEqual((c["trades_used"], c["no_peak_row"], c["skipped_no_pnl"]), (2, 1, 1))


class ReadOnly(Base):
    def snap(self):
        out = {}
        for n in sorted(os.listdir(self.data)):
            with open(os.path.join(self.data, n), "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()
        return out

    def test_data_untouched_and_exactly_one_file_written(self):
        self.write("closed_trades_archive.jsonl", [tr(i, 3.0, peak=8.0) for i in range(5)])
        before, names, out = self.snap(), sorted(os.listdir(self.data)), os.path.join(self.dir, "out.json")
        self.assertEqual(K.main(["--data", self.data, "--out", out]), 0)
        self.assertEqual((before, names), (self.snap(), sorted(os.listdir(self.data))))
        with open(out) as f:
            self.assertTrue(json.load(f)["read_only"])

    def test_missing_folder_error_and_secret_never_written(self):
        self.assertIn("error", K.build_report(os.path.join(self.dir, "nope")))
        secret, out, orig = "sk_live_abcdefghijklmnop1234567890", os.path.join(self.dir, "o.json"), K.build_report
        K.build_report = lambda *a, **k: {"tool": "x", "api_secret": secret, "note": "key " + secret}
        self.addCleanup(setattr, K, "build_report", orig)
        K.main(["--data", self.data, "--out", out])
        if os.path.exists(out):
            with open(out) as f:
                self.assertNotIn(secret, f.read())

    def test_source_has_no_network_trading_or_write_code(self):
        with open(os.path.join(ROOT, "backend", "v2_leakage.py")) as f:
            src = f.read()
        mods = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add((n.module or "").split(".")[0])
        for bad in ("socket", "requests", "urllib", "http", "sqlite3", "ccxt", "binance", "app", "strategy", "paper_trader", "live_recorder"):
            self.assertNotIn(bad, mods)
        self.assertNotIn("open(", src)


if __name__ == "__main__":
    unittest.main(verbosity=1)
