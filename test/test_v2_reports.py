"""Part 61 tests for backend/v2_reports.py (fees + tax report). NOT RUN in the delivery (owner rule). Run by hand: python3 test/test_v2_reports.py"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import v2_reports as V

NOW = 1790000000.0


def make(rows, cfg=None):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "closed_trades_archive.jsonl"), "w") as f:
        f.write("\n".join(json.dumps(r) for r in rows))
    if cfg is not None:
        with open(os.path.join(d, V.CONFIG_FILE), "w") as f:
            json.dump(cfg, f)
    return d


GOOD = {"version": "t1", "jurisdiction_label": "test", "tax_rate_pct": 30, "financial_year_start_month": 4}


class T(unittest.TestCase):
    def test_boxes_never_added(self):
        r = V.build_report(make([{"id": 1, "closed_at_ts": NOW - 100, "pnl_usdt": 5, "source": "live", "fee_usdt": 1},
                                 {"id": 2, "closed_at_ts": NOW - 100, "pnl_usdt": -3}]), now=NOW)
        self.assertEqual(r["boxes"]["real_live"]["totals"]["net_realized_usdt"], 5.0)
        self.assertEqual(r["boxes"]["paper_b1"]["totals"]["trades"], 1)

    def test_old_paper_fee_estimated_and_gross(self):
        r = V.build_report(make([{"id": 1, "closed_at_ts": NOW - 100, "pnl_usdt": 5, "invest_usdt": 100}]), fee_roi=1.0, now=NOW)
        t = r["boxes"]["paper_b1"]["totals"]
        self.assertEqual((t["gross_usdt"], t["fees_usdt"], t["net_realized_usdt"], t["fee_estimated_rows"]), (5.0, 1.0, 4.0, 1))

    def test_applied_fee_not_subtracted_twice(self):
        r = V.build_report(make([{"id": 1, "closed_at_ts": NOW - 100, "pnl_usdt": -9, "fee_applied": True, "fee_usdt": 1}]), now=NOW)
        t = r["boxes"]["paper_b1"]["totals"]
        self.assertEqual((t["gross_usdt"], t["net_realized_usdt"]), (-8.0, -9.0))

    def test_duplicate_counted_once(self):
        row = {"id": 1, "closed_at_ts": NOW - 100, "pnl_usdt": 2}
        self.assertEqual(V.build_report(make([row, row]), now=NOW)["boxes"]["paper_b1"]["totals"]["trades"], 1)

    def test_funding_shown_never_subtracted(self):
        r = V.build_report(make([{"id": 1, "closed_at_ts": NOW - 100, "pnl_usdt": 10, "source": "live", "funding_usdt": -2}]), now=NOW)
        t = r["boxes"]["real_live"]["totals"]
        self.assertEqual(t["net_realized_usdt"], 10.0)
        self.assertEqual(t["funding_usdt_shown_only"], -2.0)

    def test_no_config_no_tax(self):
        r = V.build_report(make([{"id": 1, "closed_at_ts": NOW - 100, "pnl_usdt": 10, "source": "live"}]), now=NOW)
        self.assertEqual(r["tax"]["state"], "TAX NOT CALCULATED")

    def test_bad_config_refused(self):
        for bad in ({**GOOD, "tax_rate_pct": 130}, {**GOOD, "tax_rate_pct": True}, {**GOOD, "financial_year_start_month": 13}, {"version": "x"}):
            r = V.build_report(make([{"id": 1, "closed_at_ts": NOW - 100, "pnl_usdt": 10, "source": "live"}], bad), now=NOW)
            self.assertEqual(r["tax"]["state"], "TAX NOT CALCULATED")

    def test_tax_only_real_live_and_loss_is_zero(self):
        rows = [{"id": 1, "closed_at_ts": NOW - 100, "pnl_usdt": -10, "source": "live"}, {"id": 2, "closed_at_ts": NOW - 100, "pnl_usdt": 500}]
        r = V.build_report(make(rows, GOOD), now=NOW)
        self.assertEqual(r["tax"]["state"], "ESTIMATE")
        self.assertEqual(list(r["tax"]["years"].values())[0]["tax_estimate_usdt"], 0.0)
        self.assertEqual(r["boxes"]["paper_b1"]["tax"], V.NOT_TAXABLE)

    def test_estimated_live_marks_year_incomplete(self):
        rows = [{"id": 1, "closed_at_ts": NOW - 100, "pnl_usdt": 10, "source": "live"},
                {"id": 2, "closed_at_ts": NOW - 100, "pnl_usdt": 4, "source": "live", "estimated": True}]
        y = list(V.build_report(make(rows, GOOD), now=NOW)["tax"]["years"].values())[0]
        self.assertTrue(y["data"].startswith("incomplete"))

    def test_financial_year_key_and_future_time(self):
        self.assertTrue(V.fy_key(1775000000, 4).startswith("FY2026") or V.fy_key(1775000000, 4).startswith("FY2025"))
        r = V.build_report(make([{"id": 1, "closed_at_ts": NOW + 10 * 86400, "pnl_usdt": 1}]), now=NOW)
        self.assertEqual(r["boxes"]["paper_b1"]["trades_without_usable_close_time"], 1)

    def test_source_has_no_network_or_trading_import(self):
        src = open(os.path.join(os.path.dirname(V.__file__), "v2_reports.py"), encoding="utf-8").read()
        for bad in ("import requests", "urllib", "socket", "binance_trader", "execution_router", "ai_live_client", "protection_manager"):
            self.assertNotIn(bad, src)


if __name__ == "__main__":
    unittest.main()
