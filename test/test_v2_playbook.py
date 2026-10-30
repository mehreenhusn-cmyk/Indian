"""Part 11 test: backend/v2_playbook.py (Indicator Playbook 1: TSI + Z state after entry vs result after fees, read-only).
Offline, writes only into temp folders. Main question: can a thin, no-data or lucky state be named a winner, is the direction of SELL turned
correctly, and is the hindsight table kept apart from money? (They must not be mixed up.)
Run:  python3 test/test_v2_playbook.py"""
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

DAY0 = (int(time.time()) // 86400 - 20) * 86400


def tr(i, pnl, day=0, **kw):
    """New-style paper trade (fee inside pnl), action BUY (closed rows keep BUY / SELL under "action")."""
    t = {"id": i, "symbol": "AAAUSDT", "bot": "b1", "action": "BUY", "timeframe": "5m", "invest_usdt": 100.0, "pnl_usdt": pnl, "roi_pct": pnl,
         "fee_applied": True, "opened_at_ts": DAY0 + day * 86400 + 36060, "closed_at_ts": DAY0 + day * 86400 + 37000}
    t.update(kw)
    return t


def path_of(t, z=1.5, tsi=10.0, tsl=5.0, extra=None, final=2.0, **kw):
    """Saved path line that belongs to trade t: first closed candle after entry has (z, tsi, tsl)."""
    ind = [[300.0, z, tsi, tsl]] + (extra or [])
    r = {"key": "%s@%d" % (t["id"], int(t["opened_at_ts"])), "action": t["action"], "ind": ind, "roi_final": final,
         "s": [[15.0, 0.5, 0.0, 1.0], [600.0, 3.0, 2.0, 4.0], [900.0, final, final, final]]}
    r.update(kw)
    return r


def many(start, n, pnl, **kw):
    return [tr(start + i, pnl, day=i % 15, **kw) for i in range(n)]


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

    def box(self, trades, paths, name="paper_b1", **kw):
        self.write("closed_trades_archive.jsonl", trades)
        self.write(B.PATHS_FILE, paths)
        return B.build_report(self.data, **kw)["boxes"][name]

    def split(self, trades, paths, dim, **kw):
        return self.box(trades, paths, **kw)["splits"][dim]


class States(Base):
    def red(self, action, z, tsi, tsl, extra=None):
        t = tr(1, 1.0, action=action)
        return B.reduce_path(path_of(t, z, tsi, tsl, extra))

    def test_buy_with_z_and_tsi_is_both_with(self):
        s = B.states(self.red("BUY", 1.4, 20.0, 10.0))
        self.assertEqual((s["z_state"], s["tsi_vs_signal"], s["tsi_zone"], s["agreement"]), ("Z_WITH_1_OR_MORE", "TSI_WITH_SIGNAL", "TSI_WITH_0_30", "BOTH_WITH"))

    def test_sell_direction_is_turned_around(self):
        s = B.states(self.red("SELL", -1.4, -20.0, -10.0))                  # same picture mirrored = same state
        self.assertEqual((s["z_state"], s["tsi_zone"], s["agreement"]), ("Z_WITH_1_OR_MORE", "TSI_WITH_0_30", "BOTH_WITH"))
        s2 = B.states(self.red("SELL", 1.4, 20.0, 10.0))                    # BUY-looking picture on a SELL = against
        self.assertEqual((s2["z_state"], s2["agreement"], s2["tsi_zone"]), ("Z_AGAINST", "NEITHER", "TSI_AGAINST_0_30"))

    def test_only_one_indicator_agrees(self):
        self.assertEqual(B.states(self.red("BUY", 0.4, -5.0, 5.0))["agreement"], "Z_ONLY")
        self.assertEqual(B.states(self.red("BUY", -0.4, 40.0, 5.0))["agreement"], "TSI_ONLY")
        self.assertEqual(B.states(self.red("BUY", -0.4, 40.0, 5.0))["tsi_zone"], "TSI_WITH_OVER_30")
        self.assertEqual(B.states(self.red("BUY", 0.0, -40.0, 5.0))["tsi_zone"], "TSI_AGAINST_OVER_30")

    def test_unusable_lines_give_none_never_a_guess(self):
        t = tr(1, 1.0)
        self.assertIsNone(B.reduce_path(path_of(t, action="HOLD")))
        self.assertIsNone(B.reduce_path(dict(path_of(t), ind=[])))
        self.assertIsNone(B.reduce_path(dict(path_of(t), ind=[[1, None, 2, 3], ["x", 1, 2, 3], [1, 2]])))

    def test_warning_needs_tsi_against_and_z_fall(self):
        up = [[600.0, 1.2, 20.0, 5.0]]                                       # Z lower by 0.3 only, TSI still with: no warning
        self.assertIsNone(self.red("BUY", 1.5, 10.0, 5.0, up)["warn_t"])
        both = [[600.0, 0.9, -3.0, 5.0]]                                     # Z fell 0.6 AND TSI under its signal
        self.assertEqual(self.red("BUY", 1.5, 10.0, 5.0, both)["warn_t"], 600.0)
        small_fall = [[600.0, 1.2, -3.0, 5.0]]                               # TSI against but Z fell only 0.3: no warning
        self.assertIsNone(self.red("BUY", 1.5, 10.0, 5.0, small_fall)["warn_t"])
        only_z = [[600.0, 0.5, 20.0, 5.0]]
        self.assertIsNone(self.red("BUY", 1.5, 10.0, 5.0, only_z)["warn_t"])


class FakeWinnerGuard(Base):
    def run_state(self, n_good, n_other, pnl_good=2.0, pnl_other=-1.0):
        good = many(1, n_good, pnl_good)
        other = many(1000, n_other, pnl_other)
        paths = [path_of(t, z=1.5, tsi=10.0, tsl=5.0) for t in good] + [path_of(t, z=-1.5, tsi=-10.0, tsl=5.0) for t in other]
        return self.split(good + other, paths, "agreement")

    def test_29_trades_are_thin_and_never_ranked(self):
        s = self.run_state(29, 30)
        self.assertNotIn("BOTH_WITH", s["slots"])
        self.assertEqual((s["slots_too_thin"], s["candidates"]), (1, 0))

    def test_30_steady_trades_become_a_candidate_and_the_rest_is_negative(self):
        s = self.run_state(30, 30)
        self.assertEqual(s["candidate_slots"], ["BOTH_WITH"])
        self.assertEqual(s["slots"]["NEITHER"]["verdict"], "NEGATIVE")

    def test_one_lucky_trade_is_mixed(self):
        good = many(1, 29, -1.0) + [tr(99, 300.0, day=3)]
        s = self.split(good, [path_of(t) for t in good], "agreement")
        self.assertEqual((s["slots"]["BOTH_WITH"]["verdict"], s["candidates"]), ("MIXED", 0))

    def test_no_data_trades_are_shown_but_never_ranked(self):
        trades = many(1, 40, 5.0)
        s = self.split(trades, [], "agreement")
        self.assertEqual((s["unknown_trades"], s["slots_tested"], s["candidates"], s["candidate_slots"]), (40, 0, 0, []))
        self.assertEqual(s["slots"][B.NO_DATA]["trades"], 40)


class Joining(Base):
    def test_trade_without_samples_is_counted_as_no_samples(self):
        trades = many(1, 35, 1.0)
        b = self.box(trades, [path_of(t) for t in trades[:30]])
        self.assertEqual((b["stats"]["with_samples"], b["stats"]["no_samples"]), (30, 5))

    def test_ids_restart_daily_so_the_open_time_is_part_of_the_key(self):
        a, c = tr(7, 1.0, day=1), tr(7, 1.0, day=2)
        b = self.box([a, c], [path_of(a)])
        self.assertEqual((b["stats"]["with_samples"], b["stats"]["no_samples"]), (1, 1))

    def test_first_duplicate_path_line_wins_and_garbage_lines_are_counted(self):
        t = tr(1, 1.0)
        good, dup = path_of(t, z=1.5), path_of(t, z=-1.5)
        self.write(B.PATHS_FILE, [good, dup, "not json", "[1,2]", ""])
        res, st = B.read_paths(os.path.join(self.data, B.PATHS_FILE), [self.data])
        self.assertEqual((len(res), st["usable"], st["unparsable"]), (1, 1, 2))
        self.assertGreater(res["1@%d" % int(t["opened_at_ts"])]["first"][1], 0)

    def test_missing_paths_file_is_reported_not_a_crash(self):
        self.write("closed_trades_archive.jsonl", many(1, 3, 1.0))
        rep = B.build_report(self.data)
        self.assertEqual(rep["paths_file"]["status"], "missing")
        self.assertEqual(rep["boxes"]["paper_b1"]["stats"]["no_samples"], 3)

    def test_trades_without_pnl_or_time_are_skipped_and_counted(self):
        a, no_p, no_t = tr(1, 1.0), tr(2, None), tr(3, 1.0)
        del no_t["opened_at_ts"], no_t["closed_at_ts"]
        b = self.box([a, no_p, no_t], [path_of(a)])
        self.assertEqual((b["trades_used"], b["stats"]["no_pnl"], b["stats"]["no_time"]), (1, 1, 1))


class MoneyRules(Base):
    def test_boxes_are_separate_and_live_is_not_analysed(self):
        live = [tr(500 + i, 50.0, source="live") for i in range(40)]
        self.write("closed_trades_archive.jsonl", many(1, 30, 1.0) + live)
        self.write("closed_trades_archive_b2.jsonl", many(2000, 30, -1.0, bot="b2"))
        self.write(B.PATHS_FILE, [])
        rep = B.build_report(self.data)
        self.assertEqual(sorted(rep["boxes"]), ["paper_b1", "paper_b2"])
        self.assertEqual((rep["boxes"]["paper_b1"]["trades_used"], rep["boxes"]["paper_b2"]["trades_used"]), (30, 30))
        for bad in ("total", "combined", "all_boxes"):
            self.assertNotIn('"%s' % bad, json.dumps(rep).lower())

    def test_old_trade_without_fee_gets_the_estimated_fee_taken_off(self):
        old = [{"id": i, "symbol": "OLDUSDT", "bot": "b1", "action": "BUY", "invest_usdt": 100.0, "pnl_usdt": 0.5, "roi_pct": 0.5, "timeframe": "5m",
                "opened_at_ts": DAY0 + (i % 15) * 86400 + 36060, "closed_at_ts": DAY0 + (i % 15) * 86400 + 37000} for i in range(30)]
        s = self.split(old, [path_of(t) for t in old], "agreement", fee_roi=1.0)
        self.assertAlmostEqual(s["slots"]["BOTH_WITH"]["net_usdt"], -15.0, places=3)
        self.assertEqual(s["slots"]["BOTH_WITH"]["verdict"], "NEGATIVE")

    def test_duplicate_closed_trade_is_counted_once(self):
        a = tr(1, 1.0)
        b = self.box([a, dict(a)], [path_of(a)])
        self.assertEqual(b["trades_used"], 1)


class WarningTable(Base):
    def warned(self, n, warn_roi, final):
        out = []
        for i in range(n):
            t = tr(i + 1, 1.0, day=i % 15)
            p = path_of(t, z=1.5, tsi=10.0, tsl=5.0, extra=[[600.0, 0.5, -3.0, 5.0]], final=final)
            p["s"] = [[15.0, 0.5, 0.0, 1.0], [600.0, warn_roi, warn_roi, warn_roi], [900.0, final, final, 6.0]]
            out.append((t, p))
        return [t for t, _ in out], [p for _, p in out]

    def test_thin_warning_table_is_not_enough_data(self):
        t, p = self.warned(29, 4.0, 1.0)
        self.assertEqual(self.box(t, p)["warning_hindsight"]["verdict"], "NOT ENOUGH DATA")

    def test_warning_table_is_hindsight_and_says_so(self):
        t, p = self.warned(30, 4.0, 1.0)
        w = self.box(t, p)["warning_hindsight"]
        self.assertEqual((w["verdict"], w["exit_at_warning_was_better"], w["real_exit_was_better"]), ("MEASURED", 30, 0))
        self.assertEqual((w["avg_roi_at_warning"], w["avg_roi_at_real_exit"]), (4.0, 1.0))
        self.assertIn("HINDSIGHT", w["label"])
        self.assertNotIn("net_usdt", w)                                      # never a money number

    def test_warning_split_counts_warned_and_not_warned(self):
        t, p = self.warned(30, 4.0, 1.0)
        s = self.split(t, p, "warning")
        self.assertEqual(s["slots"]["WARNED"]["trades"], 30)


class ReadOnly(Base):
    def snap(self):
        out = {}
        for n in sorted(os.listdir(self.data)):
            with open(os.path.join(self.data, n), "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()
        return out

    def test_data_untouched_and_exactly_one_file_written(self):
        trades = many(1, 30, 1.0)
        self.write("closed_trades_archive.jsonl", trades)
        self.write(B.PATHS_FILE, [path_of(t) for t in trades])
        before, names = self.snap(), sorted(os.listdir(self.data))
        out = os.path.join(self.dir, "out.json")
        self.assertEqual(B.main(["--data", self.data, "--out", out]), 0)
        self.assertEqual((before, names), (self.snap(), sorted(os.listdir(self.data))))
        with open(out) as f:
            self.assertTrue(json.load(f)["read_only"])

    def test_missing_data_folder_gives_an_error(self):
        self.assertIn("error", B.build_report(os.path.join(self.dir, "nope")))

    def test_a_secret_never_reaches_the_report_file(self):
        secret = "sk_live_abcdefghijklmnop1234567890"
        out = os.path.join(self.dir, "o.json")
        orig = B.build_report
        B.build_report = lambda *a, **k: {"tool": "x", "api_secret": secret, "note": "key " + secret}
        self.addCleanup(setattr, B, "build_report", orig)
        B.main(["--data", self.data, "--out", out])
        if os.path.exists(out):
            with open(out) as f:
                self.assertNotIn(secret, f.read())

    def test_source_has_no_network_trading_or_write_code(self):
        with open(os.path.join(ROOT, "backend", "v2_playbook.py")) as f:
            src = f.read()
        tree = ast.parse(src)
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add((n.module or "").split(".")[0])
            elif isinstance(n, ast.Call) and getattr(n.func, "id", "") == "open":
                self.assertEqual(n.args[1].value, "r")                      # every open() in this module is read-only
        for bad in ("socket", "requests", "urllib", "http", "sqlite3", "ccxt", "binance", "app", "strategy", "paper_trader", "live_recorder", "ai_ind_tracker"):
            self.assertNotIn(bad, mods)


if __name__ == "__main__":
    unittest.main()
