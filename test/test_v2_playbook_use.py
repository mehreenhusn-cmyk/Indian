"""Part 13 test: backend/v2_playbook_use.py (Indicator Playbook 3: when to use / when NOT to use; ONE command, ONE file, read-only).
Offline, writes only into temp folders. Main questions: can a thin / mixed / lucky slot become a lead? does a FAILED report ever look like "nothing found"
(the bug the first draft had: it answered an empty "+0.00")? does one run really replace the six old files?
Run:  python3 test/test_v2_playbook_use.py"""
import ast
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "test"))
import v2_inv_redact as R
import v2_money_hour as M
import v2_playbook as B
import v2_playbook_use as U
from test_v2_playbook_next import many, path_of, tr

SECTIONS = ("part8_hour", "part9_split", "part10_leakage", "part11_playbook", "part12_next", "check_all")


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2u_")
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

    def report(self, trades, paths=None, **kw):
        self.write("closed_trades_archive.jsonl", trades)
        self.write(B.PATHS_FILE, paths if paths is not None else [path_of(x) for x in trades])
        return U.build_report(self.data, **kw)

    def box(self, trades, paths=None, name="paper_b1", **kw):
        return self.report(trades, paths, **kw)["boxes"][name]

    def patch(self, mod, name, fn):
        orig = getattr(mod, name)
        setattr(mod, name, fn)
        self.addCleanup(setattr, mod, name, orig)


def names(rows):
    return {(r["part"], r["split"], r["slot"]) for r in rows}


class Leads(Base):
    def test_30_steady_winners_are_a_use_lead_and_nothing_to_avoid(self):
        b = self.box(many(1, 30, pnl=1.0))
        self.assertIn((8, "hour_utc", "10"), names(b["market"]["use_leads"]))
        self.assertEqual(b["market"]["avoid"], [])
        self.assertTrue(b["complete"])
        self.assertGreaterEqual(b["candidates"], 1)

    def test_29_trades_name_nothing(self):
        b = self.box(many(1, 29, pnl=1.0))
        self.assertEqual((b["market"]["use_leads"], b["market"]["avoid"], b["indicators"]["use_leads"], b["slots_tested"]), ([], [], [], 0))
        self.assertTrue(b["headline"].startswith("NOT ENOUGH DATA"))

    def test_30_steady_losers_are_avoid_and_never_a_lead(self):
        b = self.box(many(1, 30, pnl=-1.0))
        self.assertIn((8, "hour_utc", "10"), names(b["market"]["avoid"]))
        self.assertEqual(b["market"]["use_leads"], [])
        self.assertIn((11, "agreement", "BOTH_WITH"), names(b["indicators"]["avoid"]))

    def test_good_total_but_one_lucky_trade_is_not_a_lead(self):
        t = many(1, 30, pnl=-0.1)
        t[7]["pnl_usdt"] = t[7]["roi_pct"] = 50.0
        b = self.box(t)
        self.assertEqual(b["market"]["use_leads"], [])
        self.assertGreaterEqual(b["mixed"], 1)

    def test_halves_that_disagree_are_mixed_not_lead_not_avoid(self):
        t = [tr(1 + i, pnl=(5.0 if i < 15 else -1.0), day=i // 2) for i in range(30)]       # open time grows with i: older half wins, newer half loses, total > 0
        b = self.box(t, [path_of(x) for x in t])
        self.assertEqual((b["market"]["use_leads"], b["market"]["avoid"]), ([], []))
        self.assertGreaterEqual(b["mixed"], 1)

    def test_verdict_words_are_copied_from_the_earlier_parts(self):
        b = self.box(many(1, 30, pnl=1.0))
        for r in b["market"]["use_leads"] + b["indicators"]["use_leads"]:
            self.assertEqual(r["verdict"], "CANDIDATE")
            self.assertGreaterEqual(r["trades"], M.MIN_SLOT)
        for r in b["market"]["avoid"] + b["indicators"]["avoid"]:
            self.assertEqual(r["verdict"], "NEGATIVE")

    def test_trades_without_indicator_samples_are_never_a_lead(self):
        t = many(1, 40, pnl=1.0)
        b = self.box(t, [])
        self.assertEqual(b["indicators"]["use_leads"], [])
        self.assertTrue(all(r["slot"] != "UNKNOWN" for r in b["market"]["use_leads"] + b["market"]["avoid"]))

    def test_lists_are_capped(self):
        rows = [{"part": 9, "split": "coin", "slot": "C%d" % i, "verdict": "CANDIDATE", "trades": 40, "net_usdt": float(i)} for i in range(20)]
        got = U.pick(rows, "CANDIDATE", True)
        self.assertEqual((len(got), got[0]["net_usdt"]), (U.TOP, 19.0))
        self.assertEqual(U.pick(rows, "NEGATIVE", False), [])

    def test_worst_avoid_slot_comes_first(self):
        rows = [{"part": 9, "split": "coin", "slot": "C%d" % i, "verdict": "NEGATIVE", "trades": 40, "net_usdt": v} for i, v in enumerate((-5.0, -1.0, -10.0))]
        self.assertEqual([r["net_usdt"] for r in U.pick(rows, "NEGATIVE", False)], [-10.0, -5.0, -1.0])

    def test_the_worst_coin_is_listed_before_the_mild_one(self):
        t = [tr(1 + i, pnl=-1.0, symbol="AAAUSDT", day=i % 15) for i in range(30)] + [tr(101 + i, pnl=-3.0, symbol="BBBUSDT", day=i % 15) for i in range(30)]
        b = self.box(t, [path_of(x) for x in t])
        coins = [r["slot"] for r in b["market"]["avoid"] if r["split"] == "coin"]
        self.assertEqual(coins, ["BBBUSDT", "AAAUSDT"])

    def test_boxes_are_not_added_together(self):
        rep = self.report(many(1, 30, pnl=1.0))
        self.assertTrue(rep["boxes"]["paper_b1"]["slots_tested"] > 0)
        self.assertEqual(rep["boxes"]["paper_b2"]["slots_tested"], 0)
        self.assertEqual(sorted(rep["boxes"]), ["paper_b1", "paper_b2"])             # real live boxes are not analysed here


class LuckNote(Base):
    def rows(self, cand, tested):
        return [{"verdict": "CANDIDATE" if i < cand else "MIXED"} for i in range(tested)]

    def test_one_lead_in_forty_is_about_luck(self):
        self.assertIn("luck", U.luck_note(self.rows(1, 40)))

    def test_many_leads_are_still_only_leads(self):
        n = U.luck_note(self.rows(10, 40))
        self.assertIn("not proof", n)
        self.assertNotIn("about what luck", n)

    def test_nothing_tested_says_not_enough_data(self):
        self.assertTrue(U.luck_note([{"verdict": "NOT ENOUGH DATA"}]).startswith("NOT ENOUGH DATA"))


class StateLeads(Base):
    def test_leaving_beat_holding_in_both_halves(self):
        t = many(1, 30)
        b = self.box(t, [path_of(x, final=1.0) for x in t])
        leave = {(x["split"], x["state"]) for x in b["indicators"]["leave_leads"]}
        self.assertIn(("agreement", "NEITHER"), leave)
        self.assertEqual(b["indicators"]["hold_leads"], [])
        self.assertEqual(b["indicators"]["leave_leads"][0]["unit"], "gross ROI points, not money")

    def test_holding_beat_leaving(self):
        t = many(1, 30)
        b = self.box(t, [path_of(x, final=6.0) for x in t])
        self.assertIn(("agreement", "BOTH_WITH"), {(x["split"], x["state"]) for x in b["indicators"]["hold_leads"]})

    def test_halves_that_disagree_give_no_state_lead(self):
        t = [tr(1 + i, day=i // 2) for i in range(30)]                                   # older half: leaving won, newer half: holding won
        b = self.box(t, [path_of(x, final=(1.0 if i < 15 else 6.0)) for i, x in enumerate(t)])
        found = {(x["split"], x["state"]) for x in b["indicators"]["hold_leads"] + b["indicators"]["leave_leads"]}
        self.assertNotIn(("agreement", "BOTH_WITH"), found)
        self.assertNotIn(("agreement", "NEITHER"), found)

    def test_thin_states_give_no_state_lead(self):
        t = many(1, 29)
        b = self.box(t, [path_of(x) for x in t])
        self.assertEqual((b["indicators"]["hold_leads"], b["indicators"]["leave_leads"]), ([], []))

    def test_replay_verdict_is_passed_through(self):
        t = many(1, 30)
        b = self.box(t, [path_of(x, final=1.0) for x in t])
        self.assertEqual(b["indicators"]["exit_at_warning"]["trades"], 30)
        self.assertNotEqual(b["indicators"]["exit_at_warning"]["verdict"], "NOT AVAILABLE")


class FailClosed(Base):
    """The bug of the first draft: one failed report gave a quiet empty answer. It must say INCOMPLETE and name the report."""
    MODS = (("part8_hour", U.M), ("part9_split", U.S), ("part10_leakage", U.L), ("part11_playbook", U.B), ("part12_next", U.N))

    def test_any_single_report_that_crashes_makes_the_box_incomplete(self):
        t = many(1, 30, pnl=1.0)
        for name, mod in self.MODS:
            with self.subTest(report=name):
                orig = mod.build_report
                mod.build_report = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
                try:
                    rep = self.report(t)
                finally:
                    mod.build_report = orig
                b = rep["boxes"]["paper_b1"]
                self.assertEqual((rep["reports_failed"], b["complete"]), ([name], False))
                self.assertTrue(b["headline"].startswith("INCOMPLETE"))
                self.assertIn(name, b["headline"])
                self.assertIn("RuntimeError", rep["details"][name]["error"])

    def test_an_error_answer_counts_as_failed_too(self):
        self.patch(U.N, "build_report", lambda *a, **k: {"error": "data folder not found"})
        b = self.box(many(1, 30, pnl=1.0))
        self.assertFalse(b["complete"])
        self.assertEqual(b["indicators"]["exit_at_warning"]["verdict"], "NOT AVAILABLE")

    def test_the_working_reports_still_give_their_lists(self):
        self.patch(U.N, "build_report", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
        b = self.box(many(1, 30, pnl=1.0))
        self.assertIn((8, "hour_utc", "10"), names(b["market"]["use_leads"]))
        self.assertTrue(b["headline"].startswith("INCOMPLETE"))

    def test_incomplete_never_shows_a_money_number_as_nothing_found(self):
        self.patch(U.L, "build_report", lambda *a, **k: (_ for _ in ()).throw(KeyError("k")))
        b = self.box(many(1, 30, pnl=1.0))
        self.assertIsNone(b["box_net_after_fee_usdt"])                              # unknown stays None, never +0.00
        self.assertNotIn("+0.00", json.dumps(b))

    def test_a_failed_check_all_does_not_stop_the_playbook(self):
        self.patch(U.C, "build_report", lambda *a, **k: (_ for _ in ()).throw(OSError("db")))
        rep = self.report(many(1, 30, pnl=1.0))
        self.assertTrue(rep["check_all_failed"] and rep["boxes"]["paper_b1"]["complete"])


class OneFile(Base):
    def go(self, **kw):
        t = many(1, 30, pnl=1.0)
        self.write("closed_trades_archive.jsonl", t)
        self.write(B.PATHS_FILE, [path_of(x) for x in t])
        out = os.path.join(self.dir, "out.json")
        return U.main(["--data", self.data, "--out", out] + kw.get("extra", [])), out

    def test_one_run_one_file_with_all_six_reports_inside(self):
        code, out = self.go()
        self.assertEqual(code, 0)
        with open(out) as f:
            rep = json.load(f)
        self.assertEqual(sorted(rep["details"]), sorted(SECTIONS))
        self.assertEqual(rep["reports_failed"], [])
        self.assertTrue(rep["read_only"])
        self.assertEqual(sorted(x for x in os.listdir(self.dir) if x.endswith(".json")), ["out.json"])

    def test_fee_argument_reaches_every_report(self):
        seen = []
        for _n, mod in FailClosed.MODS:
            orig = mod.build_report
            mod.build_report = (lambda o: lambda d, fee=1.0: seen.append(fee) or o(d, fee))(orig)
            self.addCleanup(setattr, mod, "build_report", orig)
        self.go(extra=["--fee-roi", "2.5"])
        self.assertEqual(seen, [2.5] * 5)

    def test_an_unreadable_value_in_check_all_still_lets_the_playbook_through(self):
        t = many(1, 30)
        self.write("closed_trades_archive.jsonl", t)
        self.write(B.PATHS_FILE, [path_of(x) for x in t])
        self.patch(U.C, "build_report", lambda *a, **k: {"weird": {1, 2}})
        out = os.path.join(self.dir, "o.json")
        self.assertEqual(U.main(["--data", self.data, "--out", out]), 0)
        with open(out) as f:
            text = f.read()
        self.assertIn("left_out", text)
        self.assertIn("paper_b1", text)

    def test_an_unreadable_value_in_a_playbook_report_refuses_and_writes_nothing(self):
        self.patch(U.N, "build_report", lambda *a, **k: {"tool": "x", "weird": {1, 2}})
        out = os.path.join(self.dir, "o.json")
        t = many(1, 30)
        self.write("closed_trades_archive.jsonl", t)
        self.assertEqual(U.main(["--data", self.data, "--out", out]), 2)
        self.assertFalse(os.path.exists(out))

    def test_a_named_secret_is_blanked_in_the_file(self):
        t = many(1, 30)
        self.write("closed_trades_archive.jsonl", t)
        self.write(B.PATHS_FILE, [path_of(x) for x in t])
        self.patch(U.C, "build_report", lambda *a, **k: {"api_secret": "sk_live_abcdefghijklmnop1234567890"})
        out = os.path.join(self.dir, "o.json")
        self.assertEqual(U.main(["--data", self.data, "--out", out]), 0)
        with open(out) as f:
            self.assertNotIn("sk_live_", f.read())

    def test_missing_data_folder_stops_with_no_file(self):
        out = os.path.join(self.dir, "o.json")
        self.assertEqual(U.main(["--data", os.path.join(self.dir, "nope"), "--out", out]), 1)
        self.assertFalse(os.path.exists(out))
        self.assertIn("error", U.build_report(os.path.join(self.dir, "nope")))


class ReadOnly(Base):
    def snap(self):
        out = {}
        for n in sorted(os.listdir(self.data)):
            with open(os.path.join(self.data, n), "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()
        return out

    def test_data_untouched_and_label_says_not_a_rule(self):
        t = many(1, 30)
        self.write("closed_trades_archive.jsonl", t)
        self.write(B.PATHS_FILE, [path_of(x) for x in t])
        before, names_before = self.snap(), sorted(os.listdir(self.data))
        rep = U.build_report(self.data)
        self.assertEqual((before, names_before), (self.snap(), sorted(os.listdir(self.data))))
        self.assertIn("Not a trading rule", rep["boxes"]["paper_b1"]["label"])

    def test_source_has_no_network_trading_or_write_code(self):
        with open(os.path.join(ROOT, "backend", "v2_playbook_use.py")) as f:
            src = f.read()
        mods = set()
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add((n.module or "").split(".")[0])
        for bad in ("socket", "requests", "urllib", "http", "sqlite3", "ccxt", "binance", "app", "strategy", "paper_trader", "live_recorder", "ai_ind_tracker", "subprocess"):
            self.assertNotIn(bad, mods)
        self.assertNotIn("open(", src)
        self.assertNotIn("os.system", src)


if __name__ == "__main__":
    unittest.main()
