"""Part 12 test: backend/v2_playbook_next.py (Indicator Playbook 2: what each TSI + Z state does next; exit-at-warning replay, read-only).
Offline, writes only into temp folders. Main question: can a thin, mixed or lucky state / replay be named a winner, is a SELL turned around, and are
gross ROI points kept apart from money? (They must not be mixed up.)
Run:  python3 test/test_v2_playbook_next.py"""
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
import v2_playbook as B
import v2_playbook_next as N

DAY0 = (int(time.time()) // 86400 - 20) * 86400
GOOD, BAD = (1.5, 10.0, 5.0), (-1.5, -10.0, 5.0)        # BUY picture: BOTH_WITH, then NEITHER (Z fell 3.0 and TSI under its signal = WARNING)


def tr(i, pnl=1.0, day=0, **kw):
    t = {"id": i, "symbol": "AAAUSDT", "bot": "b1", "action": "BUY", "timeframe": "5m", "invest_usdt": 100.0, "pnl_usdt": pnl, "roi_pct": pnl,
         "fee_applied": True, "opened_at_ts": DAY0 + day * 86400 + 36060 + i, "closed_at_ts": DAY0 + day * 86400 + 37000 + i}
    t.update(kw)
    return t


def path_of(t, bars=(GOOD, BAD), s=None, final=1.0, **kw):
    """Saved path line: indicator candles close at 300, 600, ...; ROI path 0 -> 2 (300 s) -> 3 (600 s) -> final (900 s)."""
    ind = [[300.0 * (k + 1)] + list(b) for k, b in enumerate(bars)]
    r = {"key": "%s@%d" % (t["id"], int(t["opened_at_ts"])), "action": t["action"], "ind": ind, "roi_final": final,
         "s": s or [[15.0, 0.0, 0.0, 0.0], [300.0, 2.0, 2.0, 2.0], [600.0, 3.0, 3.0, 3.0], [900.0, final, final, final]]}
    r.update(kw)
    return r


def many(start, n, **kw):
    return [tr(start + i, day=i % 15, **kw) for i in range(n)]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2n_")
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

    def box(self, trades, paths, name="paper_b1", **kw):
        self.write("closed_trades_archive.jsonl", trades)
        self.write(B.PATHS_FILE, paths)
        return N.build_report(self.data, **kw)["boxes"][name]


class Bars(Base):
    def test_roi_at_takes_the_last_sample_at_or_before(self):
        self.assertEqual((N.roi_at([10, 20], [1.0, 2.0], 5), N.roi_at([10, 20], [1.0, 2.0], 10), N.roi_at([10, 20], [1.0, 2.0], 19), N.roi_at([10, 20], [1.0, 2.0], 99)),
                         (None, 1.0, 1.0, 2.0))

    def test_each_candle_gets_its_state_now_and_next(self):
        red = N.reduce_bars(path_of(tr(1), final=1.0))
        (g, b) = red["bars"]
        self.assertEqual((g[3], g[4], g[5]), ("BOTH_WITH", 2.0, 3.0))          # next candle: 2 -> 3
        self.assertEqual((b[3], b[4], b[5]), ("NEITHER", 3.0, 1.0))            # last candle: "next" is the real exit
        self.assertEqual((red["warn_t"], red["warn_roi"], red["final"]), (600.0, 3.0, 1.0))

    def test_sell_is_turned_around(self):
        t = tr(1, action="SELL")
        mirror = tuple((-v if i < 3 else v) for i, v in enumerate(GOOD + (0,)))[:3]
        red = N.reduce_bars(path_of(t, bars=(mirror,)))
        self.assertEqual(red["bars"][0][3], "BOTH_WITH")
        self.assertEqual(N.reduce_bars(path_of(t, bars=(GOOD,)))["bars"][0][3], "NEITHER")

    def test_unusable_lines_give_none_and_early_candles_without_roi_are_skipped(self):
        t = tr(1)
        self.assertIsNone(N.reduce_bars(path_of(t, action="HOLD")))
        self.assertIsNone(N.reduce_bars(path_of(t, roi_final=None)))
        late = N.reduce_bars(path_of(t, s=[[500.0, 1.0, 1.0, 1.0], [900.0, 1.0, 1.0, 1.0]]))
        self.assertEqual(len(late["bars"]), 1)                                  # candle at 300 s has no ROI yet: skipped, never invented


class NextCandle(Base):
    def go(self, n_trades, final=1.0):
        t = many(1, n_trades)
        return self.box(t, [path_of(x, final=final) for x in t])

    def test_numbers_are_exact_for_a_known_path(self):
        s = self.go(30, final=1.0)["next_candle"]["agreement"]["states"]
        self.assertEqual((s["BOTH_WITH"]["avg_next_candle_roi"], s["BOTH_WITH"]["avg_to_exit_roi"], s["BOTH_WITH"]["up_next_candle_pct"]), (1.0, -1.0, 100.0))
        self.assertEqual((s["NEITHER"]["avg_next_candle_roi"], s["NEITHER"]["avg_to_exit_roi"], s["NEITHER"]["up_next_candle_pct"]), (-2.0, -2.0, 0.0))

    def test_29_trades_are_not_enough_data(self):
        s = self.go(29)["next_candle"]["agreement"]
        self.assertTrue(all(f["verdict"] == "NOT ENOUGH DATA" for f in s["states"].values()))
        self.assertEqual((s["states_tested"], s["consistent"]), (0, 0))
        self.assertIn("NOT ENOUGH DATA", s["luck_note"])

    def test_30_trades_with_same_sign_in_both_halves_are_consistent(self):
        s = self.go(30)["next_candle"]["agreement"]
        self.assertEqual(s["states"]["BOTH_WITH"]["verdict"], "CONSISTENT")
        self.assertEqual((s["states_tested"], s["consistent"]), (2, 2))

    def test_halves_that_disagree_are_mixed(self):
        t = [tr(1 + i, day=i // 2) for i in range(30)]                              # open time grows with i: first 15 = older half
        paths = [path_of(x, final=(1.0 if i < 15 else 6.0)) for i, x in enumerate(t)]     # older half: holding lost, newer half: holding won
        s = self.box(t, paths)["next_candle"]["agreement"]["states"]["BOTH_WITH"]
        self.assertEqual(s["verdict"], "MIXED")
        self.assertLess(s["first_half_to_exit_roi"], 0)
        self.assertGreater(s["second_half_to_exit_roi"], 0)

    def test_many_candles_of_few_trades_do_not_pass_the_guard(self):
        t = many(1, 10)
        bars = (GOOD,) * 8
        s = self.box(t, [path_of(x, bars=bars) for x in t])["next_candle"]["z_state"]
        self.assertEqual(s["states"]["Z_WITH_1_OR_MORE"]["candles"], 80)
        self.assertEqual((s["states"]["Z_WITH_1_OR_MORE"]["trades"], s["states"]["Z_WITH_1_OR_MORE"]["verdict"]), (10, "NOT ENOUGH DATA"))

    def test_all_four_splits_exist(self):
        self.assertEqual(sorted(self.go(30)["next_candle"]), sorted(N.DIMS))


class Replay(Base):
    def go(self, n, warn_roi, final, invest=100.0):
        t = many(1, n, invest_usdt=invest)
        s = lambda: [[15.0, 0.0, 0.0, 0.0], [300.0, 2.0, 2.0, 2.0], [600.0, warn_roi, warn_roi, warn_roi], [900.0, final, final, final]]
        return self.box(t, [path_of(x, s=s(), final=final) for x in t])["exit_at_warning_replay"]

    def test_leaving_at_the_warning_paid(self):
        r = self.go(30, 4.0, 1.0)
        self.assertEqual((r["trades"], r["net_usdt"]), (30, 90.0))             # 100 x (4 - 1) / 100 = 3 USDT per trade
        self.assertEqual(r["verdict"], "LEAVING AT THE WARNING PAID (lead)")
        self.assertIn("REPLAY", r["label_kind"])

    def test_leaving_at_the_warning_cost_money(self):
        r = self.go(30, 1.0, 4.0)
        self.assertEqual((r["net_usdt"], r["verdict"]), (-90.0, "LEAVING AT THE WARNING COST MONEY"))

    def test_thin_replay_is_not_enough_data(self):
        self.assertEqual(self.go(29, 4.0, 1.0)["verdict"], "NOT ENOUGH DATA")

    def test_one_lucky_trade_is_mixed(self):
        t = many(1, 30)
        paths = []
        for i, x in enumerate(t):
            big = i == 3
            w, f = (30.0, 1.0) if big else (0.9, 1.0)                           # 29 tiny losses by leaving early + one big win
            paths.append(path_of(x, s=[[15.0, 0.0, 0.0, 0.0], [300.0, 2.0, 2.0, 2.0], [600.0, w, w, w], [900.0, f, f, f]], final=f))
        self.assertEqual(self.box(t, paths)["exit_at_warning_replay"]["verdict"], "MIXED")

    def test_trade_without_invest_is_left_out_not_guessed(self):
        t = many(1, 30)
        del t[0]["invest_usdt"]
        r = self.box(t, [path_of(x, s=[[15.0, 0.0, 0.0, 0.0], [300.0, 2.0, 2.0, 2.0], [600.0, 4.0, 4.0, 4.0], [900.0, 1.0, 1.0, 1.0]], final=1.0) for x in t])
        self.assertEqual(r["exit_at_warning_replay"]["trades"], 29)

    def test_no_warning_no_replay_rows(self):
        t = many(1, 30)
        r = self.box(t, [path_of(x, bars=(GOOD, GOOD)) for x in t])["exit_at_warning_replay"]
        self.assertEqual((r["trades"], r["verdict"]), (0, "NOT ENOUGH DATA"))


class Boxes(Base):
    def test_trades_without_samples_pnl_or_time_are_counted_not_used(self):
        a, no_p, no_t, no_s = tr(1), tr(2, None), tr(3), tr(4)
        del no_t["opened_at_ts"], no_t["closed_at_ts"]
        b = self.box([a, no_p, no_t, no_s], [path_of(a)])
        self.assertEqual((b["trades_used"], b["stats"]["no_pnl"], b["stats"]["no_time"], b["stats"]["no_samples"]), (1, 1, 1, 1))

    def test_boxes_are_separate_live_is_not_analysed_and_no_grand_total(self):
        live = [tr(500 + i, 50.0, source="live") for i in range(40)]
        b1 = many(1, 30)
        self.write("closed_trades_archive.jsonl", b1 + live)
        self.write("closed_trades_archive_b2.jsonl", [dict(x, bot="b2") for x in many(2000, 30)])
        self.write(B.PATHS_FILE, [path_of(x) for x in b1 + many(2000, 30)])
        rep = N.build_report(self.data)
        self.assertEqual(sorted(rep["boxes"]), ["paper_b1", "paper_b2"])
        self.assertEqual((rep["boxes"]["paper_b1"]["trades_used"], rep["boxes"]["paper_b2"]["trades_used"]), (30, 30))
        for bad in ("total", "combined", "all_boxes"):
            self.assertNotIn('"%s' % bad, json.dumps(rep).lower())

    def test_duplicate_closed_trade_and_duplicate_path_line_count_once(self):
        a = tr(1)
        b = self.box([a, dict(a)], [path_of(a), path_of(a, final=9.0)])
        self.assertEqual(b["trades_used"], 1)
        self.assertEqual(b["next_candle"]["agreement"]["states"]["NEITHER"]["candles"], 1)

    def test_missing_paths_file_is_reported_not_a_crash(self):
        self.write("closed_trades_archive.jsonl", many(1, 3))
        rep = N.build_report(self.data)
        self.assertEqual((rep["paths_file"]["status"], rep["boxes"]["paper_b1"]["stats"]["no_samples"]), ("missing", 3))


class ReadOnly(Base):
    def snap(self):
        out = {}
        for n in sorted(os.listdir(self.data)):
            with open(os.path.join(self.data, n), "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()
        return out

    def test_data_untouched_and_exactly_one_file_written(self):
        t = many(1, 30)
        self.write("closed_trades_archive.jsonl", t)
        self.write(B.PATHS_FILE, [path_of(x) for x in t])
        before, names = self.snap(), sorted(os.listdir(self.data))
        out = os.path.join(self.dir, "out.json")
        self.assertEqual(N.main(["--data", self.data, "--out", out]), 0)
        self.assertEqual((before, names), (self.snap(), sorted(os.listdir(self.data))))
        with open(out) as f:
            self.assertTrue(json.load(f)["read_only"])

    def test_missing_data_folder_gives_an_error(self):
        self.assertIn("error", N.build_report(os.path.join(self.dir, "nope")))

    def test_a_secret_never_reaches_the_report_file(self):
        secret = "sk_live_abcdefghijklmnop1234567890"
        out = os.path.join(self.dir, "o.json")
        orig = N.build_report
        N.build_report = lambda *a, **k: {"tool": "x", "api_secret": secret, "note": "key " + secret}
        self.addCleanup(setattr, N, "build_report", orig)
        N.main(["--data", self.data, "--out", out])
        if os.path.exists(out):
            with open(out) as f:
                self.assertNotIn(secret, f.read())

    def test_source_has_no_network_trading_or_write_code(self):
        with open(os.path.join(ROOT, "backend", "v2_playbook_next.py")) as f:
            src = f.read()
        mods = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add((n.module or "").split(".")[0])
        for bad in ("socket", "requests", "urllib", "http", "sqlite3", "ccxt", "binance", "app", "strategy", "paper_trader", "live_recorder", "ai_ind_tracker"):
            self.assertNotIn(bad, mods)
        self.assertNotIn("open(", src)                                          # this module never opens a file itself (the reader is Part 11's, read-only)


if __name__ == "__main__":
    unittest.main()
