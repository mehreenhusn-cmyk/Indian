"""Part 9 test: backend/v2_money_split.py (Money Map 2: result after fees by setup / market state / timeframe / coin, read-only).
Offline, writes only into temp folders. Main question: can a thin, unknown or lucky slot be named a winner, or boxes / fees be mixed up? (They must not.)
Run:  python3 test/test_v2_money_split.py"""
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
import v2_money_split as S

DAY0 = (int(time.time()) // 86400 - 20) * 86400


def tr(i, pnl, day=0, **kw):
    """New-style paper trade (fee inside pnl) opened 10:01 UTC on day DAY0+day."""
    t = {"id": i, "symbol": "AAAUSDT", "bot": "b1", "side": "BUY", "timeframe": "5m", "invest_usdt": 100.0, "pnl_usdt": pnl, "roi_pct": pnl,
         "fee_applied": True, "fee_usdt": 1.0, "opened_at_ts": DAY0 + day * 86400 + 36060, "closed_at_ts": DAY0 + day * 86400 + 37000}
    t.update(kw)
    return t


def many(start, n, pnl, **kw):
    return [tr(start + i, pnl, day=i % 15, **kw) for i in range(n)]


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="v2s_")
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
        return S.build_report(self.data, **kw)["boxes"]["paper_b1" if name == "b1" else "paper_b2"]

    def split(self, rows, dim, **kw):
        return self.box(rows, **kw)["splits"][dim]


class FakeWinnerGuard(Base):
    def test_thin_slot_is_counted_but_never_ranked(self):
        s = self.split(many(1, 29, 5.0, symbol="THINUSDT"), "coin")
        self.assertEqual((s["slots_tested"], s["slots_too_thin"], s["candidates"]), (0, 1, 0))
        self.assertNotIn("THINUSDT", s["slots"])
        self.assertEqual(s["candidate_slots"], [])
        self.assertIn("NOT ENOUGH DATA", s["luck_note"])

    def test_30_steady_trades_become_a_candidate(self):
        s = self.split(many(1, 30, 2.0, symbol="GOODUSDT"), "coin")
        self.assertEqual(s["candidate_slots"], ["GOODUSDT"])
        self.assertEqual(s["slots"]["GOODUSDT"]["verdict"], "CANDIDATE")

    def test_one_lucky_trade_is_mixed(self):
        s = self.split(many(1, 29, -1.0, symbol="LUCKUSDT") + [tr(99, 300.0, day=3, symbol="LUCKUSDT")], "coin")
        self.assertEqual(s["slots"]["LUCKUSDT"]["verdict"], "MIXED")
        self.assertEqual(s["candidates"], 0)

    def test_unknown_bucket_is_shown_but_never_ranked(self):
        s = self.split(many(1, 40, 5.0, entry_zone=None), "entry_zone")
        self.assertEqual(s["unknown_trades"], 40)
        self.assertEqual((s["slots_tested"], s["candidates"], s["candidate_slots"]), (0, 0, []))
        self.assertEqual(s["slots"][S.UNKNOWN]["verdict"], "CANDIDATE")         # honest facts are kept ...
        self.assertNotIn(S.UNKNOWN, s["candidate_slots"])                      # ... but it is never a named winner

    def test_luck_note_with_one_candidate_among_many_tested(self):
        rows = many(1, 30, 2.0, symbol="WINUSDT")
        for k in range(30):
            rows += many(1000 + k * 100, 30, -1.0, symbol="C%02dUSDT" % k)
        s = self.split(rows, "coin")
        self.assertEqual((s["slots_tested"], s["candidates"]), (31, 1))
        self.assertIn("about what luck", s["luck_note"])
        self.assertEqual(len(s["worst_slots"]), S.LIST_MAX)

    def test_many_candidates_get_the_normal_note_and_none_get_no_winner(self):
        rows = many(1, 30, 2.0, symbol="AUSDT") + many(100, 30, 2.0, symbol="BUSDT") + many(200, 30, 2.0, symbol="CUSDT")
        self.assertIn("lead to test", self.split(rows, "coin")["luck_note"])
        self.assertIn("no winner is named", self.split(many(1, 30, -2.0), "coin")["luck_note"])


class Splits(Base):
    def test_coin_timeframe_and_side_are_split_apart(self):
        rows = many(1, 30, 1.0, symbol="aaausdt", timeframe="3m", side="BUY") + many(100, 30, -1.0, symbol="BBBUSDT", timeframe="15m", side="SELL")
        b = self.box(rows)["splits"]
        self.assertEqual(sorted(b["coin"]["slots"]), ["AAAUSDT", "BBBUSDT"])
        self.assertEqual(sorted(b["timeframe"]["slots"]), ["15M", "3M"])
        self.assertEqual(b["side"]["slots"]["BUY"]["net_usdt"], 30.0)
        self.assertEqual(b["side"]["slots"]["SELL"]["net_usdt"], -30.0)
        self.assertEqual(sorted(b["timeframe+side"]["slots"]), ["15M+SELL", "3M+BUY"])

    def test_pair_with_a_missing_part_is_unknown(self):
        s = self.split(many(1, 30, 1.0, timeframe=None), "timeframe+side")
        self.assertEqual(list(s["slots"]), [S.UNKNOWN])

    def test_thirds_are_cut_from_the_box_own_values_and_missing_is_unknown(self):
        rows = [tr(i, 1.0, day=i % 15, atr_pct=float(i)) for i in range(1, 91)] + [tr(500, 1.0, atr_pct=None)]
        b = self.box(rows)
        c = b["third_cut_points"]["atr_pct"]
        self.assertEqual(c, [31.0, 61.0])
        s = b["splits"]["atr_pct"]
        self.assertEqual({k: v["trades"] for k, v in s["slots"].items()}, {"LOW": 30, "MID": 30, "HIGH": 30, S.UNKNOWN: 1})
        self.assertEqual(S.third_of(None, c), S.UNKNOWN)
        self.assertEqual((S.third_of(30, c), S.third_of(31, c), S.third_of(61, c)), ("LOW", "MID", "HIGH"))

    def test_cuts_need_at_least_three_values(self):
        self.assertEqual(S.cuts([1.0, 2.0]), (None, None))
        self.assertEqual(S.third_of(5.0, (None, None)), S.UNKNOWN)

    def test_slots_are_fee_correct(self):
        old = [{"id": i, "symbol": "OLDUSDT", "bot": "b1", "invest_usdt": 100.0, "pnl_usdt": 0.5, "roi_pct": 0.5, "timeframe": "5m",
                "opened_at_ts": DAY0 + (i % 15) * 86400 + 36060, "closed_at_ts": DAY0 + (i % 15) * 86400 + 37000} for i in range(30)]
        s = self.split(old, "coin", fee_roi=1.0)["slots"]["OLDUSDT"]
        self.assertAlmostEqual(s["net_usdt"], -15.0, places=3)
        self.assertEqual(s["verdict"], "NEGATIVE")

    def test_duplicates_and_trades_without_time_or_pnl(self):
        a = tr(1, 1.0)
        no_t, no_p = tr(2, 1.0), tr(3, None)
        del no_t["opened_at_ts"], no_t["closed_at_ts"]
        b = self.box([a, dict(a), no_t, no_p])
        self.assertEqual((b["trades_used"], b["stats"]["skipped_no_time"], b["stats"]["skipped_no_pnl"]), (1, 1, 1))


class Boxes(Base):
    def test_boxes_stay_separate_and_nothing_is_added_up(self):
        self.write("closed_trades_archive.jsonl", [tr(1, 5.0), tr(2, 5.0, source="live"), tr(3, 5.0, source="live", estimated=True)])
        self.write("closed_trades_archive_b2.jsonl", [tr(4, 5.0, bot="b2")])
        rep = S.build_report(self.data)
        self.assertEqual({k: v["trades_used"] for k, v in rep["boxes"].items()}, {"real_live": 1, "live_estimated": 1, "paper_b1": 1, "paper_b2": 1})
        for bad in ("total", "combined", "all_boxes"):
            self.assertNotIn('"%s' % bad, json.dumps(rep).lower())

    def test_real_live_with_6_trades_ranks_nothing(self):
        self.write("closed_trades_archive.jsonl", [tr(i, 9.0, source="live") for i in range(6)])
        b = S.build_report(self.data)["boxes"]["real_live"]
        self.assertTrue(all(s["slots_tested"] == 0 and s["candidates"] == 0 for s in b["splits"].values()))


class ReadOnly(Base):
    def snap(self):
        out = {}
        for n in sorted(os.listdir(self.data)):
            with open(os.path.join(self.data, n), "rb") as f:
                out[n] = hashlib.sha256(f.read()).hexdigest()
        return out

    def test_data_untouched_and_exactly_one_file_written(self):
        self.write("closed_trades_archive.jsonl", many(1, 30, 1.0))
        before, names = self.snap(), sorted(os.listdir(self.data))
        out = os.path.join(self.dir, "out.json")
        self.assertEqual(S.main(["--data", self.data, "--out", out]), 0)
        self.assertEqual((before, names), (self.snap(), sorted(os.listdir(self.data))))
        with open(out) as f:
            self.assertTrue(json.load(f)["read_only"])

    def test_missing_data_folder_gives_an_error(self):
        self.assertIn("error", S.build_report(os.path.join(self.dir, "nope")))

    def test_a_secret_never_reaches_the_report_file(self):
        secret = "sk_live_abcdefghijklmnop1234567890"
        out = os.path.join(self.dir, "o.json")
        orig = S.build_report
        S.build_report = lambda *a, **k: {"tool": "x", "api_secret": secret, "note": "key " + secret}
        self.addCleanup(setattr, S, "build_report", orig)
        S.main(["--data", self.data, "--out", out])
        if os.path.exists(out):
            with open(out) as f:
                self.assertNotIn(secret, f.read())

    def test_source_has_no_network_trading_or_write_code(self):
        with open(os.path.join(ROOT, "backend", "v2_money_split.py")) as f:
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


class SideFix(Base):
    """Part 11 fix: a closed trade row keeps BUY / SELL under "action", not "side" (paper_trader.py)."""

    def rows_action(self, n, act, pnl, start):
        out = many(start, n, pnl, action=act)
        for r in out:
            del r["side"]
        return out

    def test_action_is_used_when_side_is_missing(self):
        rows = self.rows_action(30, "BUY", 1.0, 1) + self.rows_action(30, "SELL", -1.0, 100)
        b = self.box(rows)["splits"]
        self.assertEqual(b["side"]["slots"]["BUY"]["net_usdt"], 30.0)
        self.assertEqual(b["side"]["slots"]["SELL"]["net_usdt"], -30.0)
        self.assertEqual(sorted(b["timeframe+side"]["slots"]), ["5M+BUY", "5M+SELL"])
        self.assertEqual(b["side"]["unknown_trades"], 0)

    def test_side_wins_over_action_and_empty_side_falls_back(self):
        self.assertEqual(S.text_value({"side": "sell", "action": "BUY"}, "side"), "SELL")
        self.assertEqual(S.text_value({"side": "  ", "action": "buy"}, "side"), "BUY")
        self.assertEqual(S.text_value({"action": "BUY"}, "timeframe"), S.UNKNOWN)       # the fallback is for side only

    def test_no_side_and_no_action_stays_unknown_never_ranked(self):
        rows = many(1, 40, 5.0)
        for r in rows:
            del r["side"]
        s = self.box(rows)["splits"]["side"]
        self.assertEqual((s["unknown_trades"], s["candidates"], s["candidate_slots"]), (40, 0, []))


if __name__ == "__main__":
    unittest.main(verbosity=1)
