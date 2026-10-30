"""Part 19 test: backend/api/preview_close.py (Positions 1 of 2: the SAFE CLOSE PREVIEW, backend half). Offline; nothing is mounted, closed or saved.
Main question: does the preview pick EXACTLY the positions the real button would close, in the same mode? So the key tests run the REAL ExecutionRouter / paper_trader selection code
(with the exchange and the price snapshot replaced by fakes, and the closing step replaced by a recorder) and compare the symbols / ids with the preview.
Also: live vs paper mode, flatten = live + every paper bot + live switched off, unpriced positions not hidden, unreadable data = ok False (never a made-up zero), nothing closed, only 1 GET route behind the token check.
Run:  python3 test/test_v2_preview.py"""
import ast
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from api import preview_close as V
from recovered_bot import execution_router as E
from recovered_bot import paper_trader as P

LIVE = [{"symbol": "AAAUSDT", "action": "BUY", "pnl_usdt": 2.5, "entry": 1, "secret_note": "x"}, {"symbol": "BBBUSDT", "action": "SELL", "pnl_usdt": -1.25},
        {"symbol": "CCCUSDT", "action": "BUY", "pnl_usdt": 0}, {"symbol": "DDDUSDT", "action": "BUY"}, {"symbol": "EEEUSDT", "action": "SELL", "pnl_usdt": None},
        {"symbol": "FFFUSDT", "action": "BUY", "pnl_usdt": "-0.5"}]
SNAP = [{"id": 1, "symbol": "P1USDT", "action": "BUY", "ltp": 2, "pnl_usdt": 1.0, "roi_pct": 5}, {"id": 2, "symbol": "P2USDT", "action": "SELL", "ltp": 3, "pnl_usdt": -2.0, "roi_pct": -9},
        {"id": 3, "symbol": "P3USDT", "action": "BUY", "ltp": 4, "pnl_usdt": 0, "roi_pct": 0}]


def view(snap=SNAP, total=None):
    return lambda bot: (list(snap), len(snap) if total is None else total)


def syms(rows):
    return [r["symbol"] for r in rows]


class Base(unittest.TestCase):
    def patch(self, obj, name, val):
        old = getattr(obj, name)
        setattr(obj, name, val)
        self.addCleanup(setattr, obj, name, old)


class TestSameSelectionAsTheRealClose(Base):
    def real_live(self, which):
        seen = []
        self.patch(E, "is_live", lambda: True)
        self.patch(E.exchange, "get_open_positions", lambda: list(LIVE))
        self.patch(E.ExecutionRouter, "_close_live_positions", staticmethod(lambda ps: seen.append(syms(ps)) or {"mode": "live", "closed_count": len(ps), "failed_count": 0, "details": []}))
        getattr(E.ExecutionRouter, which)()
        return seen[0]

    def test_live_profit_loss_and_all_match_the_real_live_close(self):
        for mode, real in (("profit", "close_all_profit"), ("loss", "close_all_loss"), ("all", "close_all")):
            got = V.preview(mode, "b1", True, lambda: list(LIVE), view())
            self.assertEqual(syms(got["parts"]["live"]["positions"]), self.real_live(real), mode)
            self.assertNotIn("paper", got["parts"], mode)

    def real_paper(self, which):
        seen = []
        self.patch(E, "is_live", lambda: False)
        self.patch(P, "_fresh_snapshot", lambda bot=None: list(SNAP))
        self.patch(P, "_close_snapshot_items", lambda items: seen.append([p["id"] for p in items]) or len(items))
        getattr(P, which)("b1")
        return seen[0]

    def test_paper_profit_and_loss_match_the_real_paper_close(self):
        for mode, real in (("profit", "close_all_profit"), ("loss", "close_all_loss")):
            got = V.preview(mode, "b1", False, lambda: [], view())
            self.assertEqual([r["id"] for r in got["parts"]["paper"]["positions"]], self.real_paper(real), mode)

    def test_paper_all_and_flatten_cover_every_position_the_real_close_walks(self):
        pos = {7: {"bot": "b1"}, 8: {"bot": "b2"}, 9: {}}
        closed = []
        self.patch(P, "_positions", pos)
        self.patch(P, "close_position_manual", lambda tid: closed.append(tid) or {"ok": True})
        P.close_all_with_detail("b1")
        real_bot, closed[:] = list(closed), []
        P.close_all_with_detail()
        real_all = list(closed)
        self.patch(P, "_fresh_snapshot", lambda bot=None: [{"id": 7, "symbol": "X", "pnl_usdt": 0}])        # only 1 of the walked positions has a price
        count = lambda bot: sum(1 for p in pos.values() if bot is None or (p.get("bot") or "b1") == bot)
        for_bot = V.preview("all", "b1", False, lambda: [], lambda bot: (P._fresh_snapshot(bot), count(bot)))
        every = V.preview("flatten", "b1", False, lambda: [], lambda bot: (P._fresh_snapshot(bot), count(bot)))
        self.assertEqual((real_bot, real_all), ([7, 9], [7, 8, 9]))
        self.assertEqual(for_bot["parts"]["paper"]["unpriced_count"], len(real_bot) - 1)
        self.assertEqual(every["parts"]["paper"]["unpriced_count"], len(real_all) - 1)       # flatten uses NO bot filter, like the real /api/flatten


class TestModeAndShape(Base):
    def test_live_on_reads_the_exchange_never_the_paper_snapshot(self):
        calls = []
        got = V.preview("profit", "b1", True, lambda: LIVE, lambda bot: calls.append(bot) or (SNAP, 3))
        self.assertEqual((got["mode"], calls, sorted(got["parts"])), ("live", [], ["live"]))
        self.assertEqual(syms(got["positions"]), ["AAAUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT"])        # 0 / None / missing pnl count as 0 = profit side, like the real close

    def test_paper_mode_never_reads_the_exchange(self):
        def boom():
            raise AssertionError("exchange read in paper mode")
        got = V.preview("loss", "b1", False, boom, view())
        self.assertEqual((got["mode"], got["count"], got["total_pnl_usdt"]), ("paper", 1, -2.0))

    def test_flatten_is_live_plus_every_paper_bot_and_switches_live_off(self):
        seen = []
        got = V.preview("flatten", "b1", True, lambda: LIVE[:2], lambda bot: seen.append(bot) or (SNAP, 3))
        self.assertEqual((seen, got["count"], got["will_turn_live_off"]), ([None], 5, True))
        self.assertEqual(sorted(got["parts"]), ["live", "paper"])
        self.assertEqual({r["source"] for r in got["positions"]}, {"live", "paper"})
        self.assertEqual(got["total_pnl_usdt"], round(2.5 - 1.25 + 1.0 - 2.0 + 0, 6))
        off = V.preview("flatten", "b1", False, lambda: LIVE, view())
        self.assertEqual((sorted(off["parts"]), off["will_turn_live_off"]), (["paper"], True))     # live off: no exchange read, paper only

    def test_only_known_fields_are_passed_on(self):
        row = V.preview("all", "b1", True, lambda: LIVE, view())["positions"][0]
        self.assertEqual((row["symbol"], row["source"], "secret_note" in row), ("AAAUSDT", "live", False))

    def test_totals_add_up_and_the_old_response_shape_is_kept(self):
        got = V.preview("profit", "b1", False, lambda: [], view())
        self.assertTrue(all(k in got for k in ("ok", "count", "total_pnl_usdt", "positions")))
        self.assertEqual((got["count"], got["total_pnl_usdt"]), (2, 1.0))

    def test_unpriced_positions_are_reported_not_hidden(self):
        got = V.preview("all", "b1", False, lambda: [], view(SNAP[:1], total=4))
        self.assertEqual((got["count"], got["parts"]["paper"]["unpriced_count"]), (1, 3))

    def test_empty_is_a_clean_zero(self):
        got = V.preview("all", "b1", True, lambda: [], view([]))
        self.assertEqual((got["ok"], got["count"], got["total_pnl_usdt"]), (True, 0, 0))


class TestHonestErrors(Base):
    def test_bad_mode(self):
        for m in ("", "PROFIT", "close", "profit; drop", None):
            self.assertEqual(V.preview(m, "b1", True, lambda: [], view()), {"ok": False, "error": "mode must be profit, loss, all or flatten"}, m)

    def test_unreadable_pnl_is_an_error_not_a_zero(self):
        got = V.preview("profit", "b1", True, lambda: [{"symbol": "X", "pnl_usdt": "abc"}], view())
        self.assertEqual((got["ok"], "P&L" in got["error"]), (False, True))

    def test_exchange_or_price_failure_gives_a_short_text_without_details(self):
        def boom():
            raise RuntimeError("HTTP 500 https://secret.example/key=abc")
        for got in (V.preview("all", "b1", True, boom, view()), V.preview("all", "b1", False, boom, lambda b: boom())):
            self.assertEqual(got, {"ok": False, "error": "could not read the positions right now"})


class TestRouterAndSource(Base):
    def test_one_get_route_behind_the_token_check_and_it_calls_the_real_sources(self):
        import asyncio
        routes = []

        class R:
            def get(s, path, **kw):
                return lambda f: (routes.append((path, kw, f)), f)[1]
        fa = types.ModuleType("fastapi")
        fa.APIRouter, fa.Depends = R, lambda f: ("dep", f)
        self.patch(sys.modules, "fastapi", fa) if "fastapi" in sys.modules else sys.modules.__setitem__("fastapi", fa)
        self.addCleanup(lambda: sys.modules.pop("fastapi", None) if sys.modules.get("fastapi") is fa else None)
        guard = lambda: None
        self.patch(E, "is_live", lambda: True)
        self.patch(E.exchange, "get_open_positions", lambda: list(LIVE))
        V.make_router(guard, lambda bot, d: "b1")
        self.assertEqual([(p, kw["dependencies"]) for p, kw, _ in routes], [("/api/v2/preview_close", [("dep", guard)])])
        got = asyncio.run(routes[0][2](mode="loss", bot=""))
        self.assertEqual(syms(got["positions"]), ["BBBUSDT", "FFFUSDT"])

    def test_the_real_paper_view_counts_only_the_asked_bot(self):
        import asyncio
        routes = []

        class R:
            def get(s, path, **kw):
                return lambda f: (routes.append(f), f)[1]
        fa = types.ModuleType("fastapi")
        fa.APIRouter, fa.Depends = R, lambda f: f
        sys.modules["fastapi"] = fa
        self.addCleanup(sys.modules.pop, "fastapi", None)
        self.patch(E, "is_live", lambda: False)
        self.patch(P, "_positions", {7: {"bot": "b1"}, 8: {"bot": "b2"}, 9: {}})
        self.patch(P, "_fresh_snapshot", lambda bot=None: [])
        V.make_router(lambda: None, lambda bot, d: "b1")
        self.assertEqual(asyncio.run(routes[0](mode="all", bot=""))["parts"]["paper"]["unpriced_count"], 2)      # b1 + the one with no bot (= b1), not b2
        self.assertEqual(asyncio.run(routes[0](mode="flatten", bot=""))["parts"]["paper"]["unpriced_count"], 3)

    def test_source_closes_nothing_and_has_no_network_or_write_code(self):
        with open(os.path.join(ROOT, "backend", "api", "preview_close.py"), encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        self.assertEqual([n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))], [])      # top level imports nothing at all
        body = src.split('"""', 2)[2].lower()
        for w in ("close_position", "close_all", "close_one", "set_target", "trail_sl", "settings_store", "update(", "requests", "urllib", "socket", "hmac", "signature", "neworder", "@r.post", "open("):
            self.assertNotIn(w, body, w)


if __name__ == "__main__":
    unittest.main(verbosity=1)
