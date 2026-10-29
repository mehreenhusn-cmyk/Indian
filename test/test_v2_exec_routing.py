"""Part 4 test B: RECORDS how close_one / close_all / close_all_profit / close_all_loss are routed today (30 Oct 2026).
Rule being pinned: every action goes to PAPER xor LIVE - never both, never neither - and the master "trading paused" switch
never blocks a close. Also records ONE KNOWN GAP and fixes nothing: the preview shown before Close All Profit / Loss
(/api/preview_close_all) always prices PAPER positions, even when live trading is on. That is planned for Parts 19-20; when
it is fixed, the test named test_known_gap_* must be changed on purpose.
All exchange / paper calls are replaced by recorders: nothing real is touched. Offline. Run:  python3 test/test_v2_exec_routing.py"""
import ast
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from recovered_bot import execution_router as X      # noqa: E402
from recovered_bot import paper_trader as P          # noqa: E402

ACTIONS = ("close_one", "close_all", "close_all_profit", "close_all_loss")


class Recorder(object):
    """Stands in for paper_trader and for exchange. Every call is logged as (who, name)."""

    def __init__(self, who, log, live_positions=None):
        self.who, self.log, self.live_positions = who, log, live_positions or []

    def _rec(self, name, ret):
        self.log.append((self.who, name))
        return ret

    # paper_trader surface used by ExecutionRouter
    def close_position_manual(self, tid):
        return self._rec("close_position_manual", {"ok": True, "symbol": "PAPERUSDT", "forced": False})

    def close_all_with_detail(self, bot=None):
        return self._rec("close_all_with_detail", {"closed_count": 2, "failed_count": 0, "details": []})

    def close_all_profit(self, bot=None):
        return self._rec("close_all_profit", 3)

    def close_all_loss(self, bot=None):
        return self._rec("close_all_loss", 1)

    # exchange surface used by ExecutionRouter
    def get_open_positions(self):
        self.log.append((self.who, "get_open_positions"))
        return list(self.live_positions)

    def close_position_market(self, symbol, action):
        return self._rec("close_position_market:" + symbol, "order-" + symbol)


class Base(unittest.TestCase):
    LIVE = [{"symbol": "AAAUSDT", "action": "BUY", "pnl_usdt": 5.0},
            {"symbol": "BBBUSDT", "action": "SELL", "pnl_usdt": -2.0},
            {"symbol": "CCCUSDT", "action": "BUY", "pnl_usdt": 0.0}]

    def setUp(self):
        self.log = []
        self.flags = {"live_trading_enabled": False, "trading_enabled": True}
        self.saved = (X.settings_store, X.paper_trader, X.exchange)
        X.settings_store = type("S", (), {"get": staticmethod(lambda k, d=None: self.flags.get(k, d))})
        X.paper_trader = Recorder("paper", self.log)
        X.exchange = Recorder("live", self.log, self.LIVE)
        self.addCleanup(self.restore)

    def restore(self):
        X.settings_store, X.paper_trader, X.exchange = self.saved

    def who(self):
        return {w for w, _n in self.log}

    def call(self, name):
        if name == "close_one":
            return X.ExecutionRouter.close_one("7" if not self.flags["live_trading_enabled"] else "AAAUSDT")
        return getattr(X.ExecutionRouter, name)()


class PaperXorLive(Base):
    def test_paper_mode_touches_only_paper(self):
        for name in ACTIONS:
            self.log[:] = []
            r = self.call(name)
            self.assertEqual(self.who(), {"paper"}, name)
            self.assertEqual(r.get("mode"), "paper", name)

    def test_live_mode_touches_only_live(self):
        self.flags["live_trading_enabled"] = True
        for name in ACTIONS:
            self.log[:] = []
            r = self.call(name)
            self.assertEqual(self.who(), {"live"}, name)
            self.assertEqual(r.get("mode"), "live", name)

    def test_every_action_always_does_something(self):                       # "never neither"
        for live in (False, True):
            self.flags["live_trading_enabled"] = live
            for name in ACTIONS:
                self.log[:] = []
                self.call(name)
                self.assertTrue(self.log, (live, name))

    def test_live_profit_closes_pnl_zero_or_more_and_loss_closes_below_zero(self):
        self.flags["live_trading_enabled"] = True
        r = X.ExecutionRouter.close_all_profit()
        self.assertEqual(sorted(d["symbol"] for d in r["details"]), ["AAAUSDT", "CCCUSDT"])
        self.log[:] = []
        r = X.ExecutionRouter.close_all_loss()
        self.assertEqual([d["symbol"] for d in r["details"]], ["BBBUSDT"])
        self.assertEqual([n for _w, n in self.log if n.startswith("close_position_market")], ["close_position_market:BBBUSDT"])

    def test_live_close_all_closes_every_open_position(self):
        self.flags["live_trading_enabled"] = True
        r = X.ExecutionRouter.close_all()
        self.assertEqual((r["closed_count"], r["failed_count"]), (3, 0))

    def test_live_close_one_for_a_missing_position_is_a_clean_no_op(self):
        self.flags["live_trading_enabled"] = True
        r = X.ExecutionRouter.close_one("ZZZUSDT")
        self.assertFalse(r["ok"])
        self.assertEqual(r["mode"], "live")
        self.assertFalse([n for _w, n in self.log if n.startswith("close_position_market")])

    def test_paper_close_one_with_a_bad_id_never_reaches_the_exchange(self):
        r = X.ExecutionRouter.close_one("not-a-number")
        self.assertEqual((r["ok"], r["mode"]), (False, "paper"))
        self.assertEqual(self.log, [])

    def test_master_pause_never_blocks_a_close(self):
        self.flags["trading_enabled"] = False
        for live in (False, True):
            self.flags["live_trading_enabled"] = live
            for name in ACTIONS:
                self.log[:] = []
                self.call(name)
                self.assertTrue(self.log, (live, name))

    def test_mode_is_read_fresh_on_every_call(self):
        self.call("close_all_profit")
        self.flags["live_trading_enabled"] = True
        self.call("close_all_profit")
        self.assertEqual([w for w, n in self.log if n in ("close_all_profit", "close_position_market:AAAUSDT")], ["paper", "live"])


class SourceShape(unittest.TestCase):
    """Reads the source text only (no import side effects): each action must ask is_live() itself."""

    def test_each_action_checks_is_live(self):
        with open(os.path.join(ROOT, "backend", "recovered_bot", "execution_router.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        cls = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ExecutionRouter"][0]
        funcs = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
        for name in ACTIONS:
            calls = {c.func.id for c in ast.walk(funcs[name]) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
            self.assertIn("is_live", calls, name)
            self.assertNotIn("is_trading_enabled", calls, name)                  # closes are never gated by the pause switch


class PreviewSelection(unittest.TestCase):
    """Paper: what the preview lists is exactly what Close All Profit / Loss closes (same snapshot rule)."""

    ITEMS = [{"id": 1, "pnl_usdt": 4.0}, {"id": 2, "pnl_usdt": -1.5}, {"id": 3, "pnl_usdt": 0.0}, {"id": 4, "pnl_usdt": -0.01}]

    def setUp(self):
        self.saved = (P._fresh_snapshot, P._close_snapshot_items)
        P._fresh_snapshot = lambda bot=None: [dict(i) for i in self.ITEMS]
        self.closed = []
        P._close_snapshot_items = lambda items: self.closed.append([i["id"] for i in items]) or len(items)
        self.addCleanup(self.restore)

    def restore(self):
        P._fresh_snapshot, P._close_snapshot_items = self.saved

    def test_profit_preview_equals_profit_close(self):
        prev = P.preview_close_all("profit")
        P.close_all_profit()
        self.assertEqual([p["id"] for p in prev["positions"]], self.closed[-1])
        self.assertEqual(self.closed[-1], [1, 3])
        self.assertEqual((prev["count"], prev["total_pnl_usdt"]), (2, 4.0))

    def test_loss_preview_equals_loss_close(self):
        prev = P.preview_close_all("loss")
        P.close_all_loss()
        self.assertEqual([p["id"] for p in prev["positions"]], self.closed[-1])
        self.assertEqual(self.closed[-1], [2, 4])


class KnownGap(unittest.TestCase):
    def test_known_gap_preview_endpoint_is_paper_only(self):
        """RECORD ONLY. /api/preview_close_all calls paper_trader.preview_close_all and never asks the router or the exchange,
        so with live trading ON the confirm dialog would still show PAPER positions. Planned fix: Parts 19-20."""
        with open(os.path.join(ROOT, "backend", "api", "trade.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        fn = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "preview_close_all"][0]
        text = ast.unparse(fn)
        self.assertIn("paper_trader.preview_close_all", text)
        for word in ("is_live", "ExecutionRouter", "exchange"):
            self.assertNotIn(word, text, "the gap was fixed - update this test on purpose (Parts 19-20)")


if __name__ == "__main__":
    unittest.main(verbosity=1)
