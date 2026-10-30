"""Part 15 test: backend/v2_defs.py (Collectors 2 of 5: versioned definitions). Offline, pure maths, writes nothing except one temp store for the read-only helper.
Main questions: is a number ever invented when data is thin / bad / has a gap, are ranks deterministic, is the harsher drawdown reading kept,
are incomplete hours ever used for the baseline, and does the module stay free of network / order code and never write?
Run:  python3 test/test_v2_defs.py"""
import ast
import math
import os
import shutil
import socket
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import v2_defs as D
import v2_store as S

T0 = 1_800_000_400 - 1_800_000_400 % 3600        # a UTC hour start
DAY = 86400


def cs(prices, t0=T0, step=300):
    """prices = list of (o, h, l, c, v) -> candle rows on a clean grid."""
    return [(t0 + i * step,) + tuple(p) for i, p in enumerate(prices)]


class NoNet(unittest.TestCase):
    def setUp(self):
        self._s = socket.socket
        socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))
        self.addCleanup(setattr, socket, "socket", self._s)


class TestClean(NoNet):
    def test_good_rows_sorted_and_deduped_first_stays(self):
        rows = [(T0 + 300, 2, 3, 1, 2, 5), (T0, 1, 2, 1, 1, 4), (T0, 9, 9, 9, 9, 9)]
        good, bad = D.clean_candles(rows, "5m")
        self.assertEqual([g[0] for g in good], [T0, T0 + 300])
        self.assertEqual(good[0][1], 1.0)
        self.assertEqual(bad, 1)

    def test_bad_rows_counted(self):
        rows = [(T0, 1, 2, 1, 1, 4), (T0 + 300, 0, 1, 0, 1, 1), (T0 + 600, 1, 2, 1, 1, -1), (T0 + 900, 1, 1, 2, 1, 1), (T0 + 1200, float("nan"), 1, 1, 1, 1),
                (T0 + 1500, True, 1, 1, 1, 1), ("x",), None, (T0 + 1800, 1, 2, 1, 5, 1)]
        good, bad = D.clean_candles(rows, "5m")
        self.assertEqual(len(good), 1)
        self.assertEqual(bad, 8)

    def test_gap_detected(self):
        good, _ = D.clean_candles(cs([(1, 2, 1, 1, 1)] * 3), "5m")
        self.assertFalse(D.has_gap(good, "5m"))
        self.assertTrue(D.has_gap(good[:1] + good[2:], "5m"))
        self.assertTrue(D.has_gap(good, "3m"))             # 5m grid is a gap on the 3m grid


class TestRank(NoNet):
    ITEMS = [("A", 100, 110), ("B", 100, 90), ("C", 100, 100), ("D", 50, 60), ("E", 10, 9), ("F", 10, 12), ("G", 1, 1.01)]

    def test_change_pct(self):
        self.assertEqual(D.day_open_change_pct(100, 110)["value"], 10.0)
        self.assertEqual(D.day_open_change_pct(100, 90)["value"], -10.0)

    def test_change_unavailable(self):
        for a, b in ((0, 1), (-1, 1), (1, 0), (None, 1), (1, float("inf")), (True, 1)):
            self.assertEqual(D.day_open_change_pct(a, b)["status"], "UNAVAILABLE")

    def test_gainers_order_and_ranks(self):
        r = D.day_open_rank(self.ITEMS, "GAINER", top=3)
        self.assertEqual([x["symbol"] for x in r["ranks"]], ["D", "F", "A"])      # D and F are both +20: tie goes A-Z, then A +10
        self.assertEqual([x["rank"] for x in r["ranks"]], [1, 2, 3])
        self.assertEqual(r["status"], "OK")

    def test_tie_goes_by_symbol(self):
        r = D.day_open_rank([("Z", 10, 11), ("M", 10, 11), ("A", 10, 11)], "GAINER", top=3)
        self.assertEqual([x["symbol"] for x in r["ranks"]], ["A", "M", "Z"])

    def test_losers_lowest_first(self):
        r = D.day_open_rank(self.ITEMS, "LOSER", top=2)
        self.assertEqual([x["symbol"] for x in r["ranks"]], ["B", "E"])

    def test_same_input_same_output_any_order(self):
        a = D.day_open_rank(self.ITEMS, "GAINER")
        b = D.day_open_rank(list(reversed(self.ITEMS)), "GAINER")
        self.assertEqual(a, b)

    def test_partial_is_not_padded(self):
        r = D.day_open_rank(self.ITEMS[:2], "GAINER", top=5)
        self.assertEqual(r["status"], "PARTIAL")
        self.assertEqual(len(r["ranks"]), 2)

    def test_bad_and_duplicate_symbols_skipped(self):
        r = D.day_open_rank([("A", 10, 11), ("A", 10, 99), ("", 10, 11), ("B", 0, 5), (1, 10, 11), ("C",), None], "GAINER", top=5)
        self.assertEqual([x["symbol"] for x in r["ranks"]], ["A"])
        self.assertEqual(r["skipped"], 6)
        self.assertEqual(r["ranks"][0]["change_pct"], 10.0)      # first A stays

    def test_nothing_valid_unavailable(self):
        r = D.day_open_rank([("B", 0, 5)], "LOSER")
        self.assertEqual((r["status"], r["ranks"]), ("UNAVAILABLE", []))

    def test_wrong_kind_raises(self):
        with self.assertRaises(ValueError):
            D.day_open_rank([], "WINNER")


class TestPeak(NoNet):
    LONG = cs([(10, 11, 9.5, 10.5, 1), (10.5, 12, 10, 11, 1), (11, 13, 10.8, 12, 1), (12, 12.5, 11, 11.5, 1), (11.5, 13, 11, 12, 1)])

    def test_long_first_peak_wins_on_tie(self):
        r = D.time_to_peak(self.LONG, "5m", T0)
        self.assertEqual(r["status"], "OK")
        self.assertEqual(r["value"], 10.0)                  # candle index 2 = 10 minutes, the later 13 does not replace it
        self.assertEqual(r["peak_candle_index"], 2)
        self.assertEqual(r["peak_pct"], 30.0)
        self.assertFalse(r["no_gain"])

    def test_short_uses_lowest_low(self):
        rows = cs([(10, 10.2, 9.8, 9.9, 1), (9.9, 10, 9, 9.5, 1), (9.5, 9.7, 9.4, 9.6, 1)])
        r = D.time_to_peak(rows, "5m", T0, "SHORT")
        self.assertEqual((r["value"], r["peak_candle_index"]), (5.0, 1))
        self.assertEqual(r["peak_pct"], 10.0)

    def test_never_went_up_flagged_no_gain(self):
        rows = cs([(10, 10, 9, 9.5, 1), (9.5, 9.6, 8, 8.5, 1), (8.5, 8.6, 7, 7.5, 1)])
        r = D.time_to_peak(rows, "5m", T0)
        self.assertTrue(r["no_gain"])
        self.assertEqual(r["value"], 0.0)

    def test_entry_inside_candle_counts_from_entry_time(self):
        r = D.time_to_peak(self.LONG, "5m", T0 + 100)
        self.assertEqual(r["value"], round((T0 + 600 - (T0 + 100)) / 60.0, 2))

    def test_window_limits_the_look(self):
        r = D.time_to_peak(self.LONG, "5m", T0, window=3)
        self.assertEqual(r["candles_used"], 3)

    def test_too_few_missing_entry_gap_bad_row(self):
        self.assertEqual(D.time_to_peak(self.LONG[:2], "5m", T0)["status"], "UNAVAILABLE")
        self.assertEqual(D.time_to_peak(self.LONG[1:], "5m", T0)["status"], "UNAVAILABLE")     # entry candle missing
        self.assertEqual(D.time_to_peak(self.LONG[:1] + self.LONG[2:], "5m", T0)["status"], "UNAVAILABLE")
        self.assertEqual(D.time_to_peak(self.LONG + [(T0 + 1500, 0, 1, 1, 1, 1)], "5m", T0)["status"], "UNAVAILABLE")
        self.assertEqual(D.time_to_peak(self.LONG, "1h", T0)["status"], "UNAVAILABLE")
        self.assertEqual(D.time_to_peak([], "5m", T0)["status"], "UNAVAILABLE")

    def test_wrong_side_raises(self):
        with self.assertRaises(ValueError):
            D.time_to_peak(self.LONG, "5m", T0, "UP")


class TestDrawdown(NoNet):
    def test_long_fall_from_best(self):
        rows = cs([(10, 12, 10, 11, 1), (11, 11.5, 9, 9.5, 1), (9.5, 10, 9, 9.8, 1)])
        self.assertEqual(D.max_drawdown(rows, "5m")["value"], 25.0)        # 12 -> 9

    def test_harsher_reading_inside_one_candle(self):
        rows = cs([(10, 20, 10, 15, 1), (15, 16, 15, 16, 1), (16, 17, 16, 17, 1)])
        self.assertEqual(D.max_drawdown(rows, "5m")["value"], 50.0)        # the same candle: 20 first, then 10

    def test_short_rise_from_best(self):
        rows = cs([(10, 10, 8, 9, 1), (9, 9.5, 8.5, 9, 1), (9, 9.6, 9, 9.4, 1)])
        self.assertEqual(D.max_drawdown(rows, "5m", "SHORT")["value"], 25.0)   # candle 1: low 8 first, then high 10 (harsher reading)

    def test_straight_up_is_zero(self):
        rows = cs([(10, 10, 10, 10, 1), (11, 11, 11, 11, 1), (12, 12, 12, 12, 1)])
        self.assertEqual(D.max_drawdown(rows, "5m")["value"], 0.0)

    def test_unavailable_when_thin_or_gap(self):
        rows = cs([(10, 12, 10, 11, 1)] * 3)
        self.assertEqual(D.max_drawdown(rows[:2], "5m")["status"], "UNAVAILABLE")
        self.assertEqual(D.max_drawdown(rows[:1] + rows[2:], "5m")["status"], "UNAVAILABLE")


class TestVolume(NoNet):
    def test_decay_ratio(self):
        rows = cs([(1, 1, 1, 1, 10), (1, 1, 1, 1, 100), (1, 1, 1, 1, 50), (1, 1, 1, 1, 20), (1, 1, 1, 1, 5), (1, 1, 1, 1, 999)][:5])
        r = D.volume_decay(rows, "5m")
        self.assertEqual(r["value"], round((50 + 20 + 5) / 3 / 100, 4))
        self.assertEqual(r["after_used"], 3)

    def test_peak_last_unavailable(self):
        rows = cs([(1, 1, 1, 1, 1), (1, 1, 1, 1, 2), (1, 1, 1, 1, 3)])
        self.assertEqual(D.volume_decay(rows, "5m")["status"], "UNAVAILABLE")

    def test_zero_volume_unavailable(self):
        rows = cs([(1, 1, 1, 1, 0)] * 4)
        self.assertEqual(D.volume_decay(rows, "5m")["status"], "UNAVAILABLE")


class TestBaseline(NoNet):
    def hours(self, days, vol=lambda d: 100 + d, interval="5m"):
        step = D.STEP[interval]
        rows = []
        for d in days:
            for i in range(3600 // step):
                rows.append((T0 - d * DAY + i * step, 1, 1, 1, 1, vol(d) / (3600 // step)))
        return rows

    def test_complete_hours_only(self):
        rows = self.hours([1, 2]) + self.hours([3])[:-1]
        hv = D.hourly_volumes(rows, "5m")
        self.assertEqual(sorted(hv), [T0 - 2 * DAY, T0 - DAY])         # day 3 lost one candle: not used

    def test_median_of_same_hour(self):
        hv = D.hourly_volumes(self.hours([1, 2, 3, 4, 5]), "5m")
        r = D.same_hour_baseline(hv, T0 + 1234)
        self.assertEqual((r["status"], r["days_used"]), ("OK", 5))
        self.assertAlmostEqual(r["value"], 103.0)

    def test_three_candle_grid_works(self):
        hv = D.hourly_volumes(self.hours([1, 2, 3], interval="3m"), "3m")
        self.assertEqual(D.same_hour_baseline(hv, T0)["status"], "OK")

    def test_too_few_days_unavailable(self):
        hv = D.hourly_volumes(self.hours([1, 2]), "5m")
        r = D.same_hour_baseline(hv, T0)
        self.assertEqual((r["status"], r["value"]), ("UNAVAILABLE", None))

    def test_older_than_7_days_and_today_not_used(self):
        hv = D.hourly_volumes(self.hours([0, 8, 9, 10, 1, 2]), "5m")
        r = D.same_hour_baseline(hv, T0)
        self.assertEqual(r["status"], "UNAVAILABLE")
        self.assertIn("only 2 of the last 7", r["reason"])

    def test_bad_values_ignored(self):
        r = D.same_hour_baseline({T0 - DAY: float("nan"), T0 - 2 * DAY: -5, T0 - 3 * DAY: 1, T0 - 4 * DAY: 2, T0 - 5 * DAY: 3}, T0)
        self.assertEqual((r["days_used"], r["value"]), (3, 2))


class TestStoreReader(NoNet):
    def test_reads_only_one_symbol_interval_range_and_writes_nothing(self):
        d = tempfile.mkdtemp(prefix="v2d_")
        self.addCleanup(shutil.rmtree, d, True)
        con = S.open_store(d)
        self.addCleanup(con.close)
        for i in range(4):
            S.add_candle(con, "AAA", "5m", T0 + i * 300, 1, 2, 1, 1, 5)
        S.add_candle(con, "BBB", "5m", T0, 1, 2, 1, 1, 5)
        S.add_candle(con, "AAA", "3m", T0, 1, 2, 1, 1, 5)
        before = con.total_changes
        rows = D.candles_from_store(con, "AAA", "5m", T0 + 300, T0 + 900)
        self.assertEqual([r[0] for r in rows], [T0 + 300, T0 + 600, T0 + 900])
        self.assertEqual(con.total_changes, before)
        self.assertEqual(D.max_drawdown(rows, "5m")["status"], "OK")


class TestGuards(NoNet):
    def test_no_network_order_or_write_code(self):
        with open(os.path.join(ROOT, "backend", "v2_defs.py"), encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(mods, {"math", "statistics", "sys"})
        low = src.lower()
        for word in ("insert ", "update ", "delete ", "drop ", "commit", "urllib", "requests", "hmac", "signature", "order("):
            self.assertNotIn(word, low.split('"""', 2)[2], word)

    def test_version_and_meanings_listed(self):
        self.assertEqual(D.DEFS_VERSION, 1)
        for w in ("day_open_rank", "time_to_peak", "max_drawdown", "volume_decay", "same_hour_baseline"):
            self.assertIn(w, D.__doc__)

    def test_no_nan_leaks_out(self):
        rows = cs([(10, 12, 10, 11, 1)] * 5)
        for r in (D.time_to_peak(rows, "5m", T0), D.max_drawdown(rows, "5m"), D.volume_decay(rows, "5m")):
            v = r["value"]
            self.assertTrue(v is None or math.isfinite(v))


if __name__ == "__main__":
    unittest.main(verbosity=1)
