"""Part 70 (V2-S0-GUARD): only an ALLOW-LIST of files may import the live trading modules. Static scan (AST) of every .py under backend/, no import, no network.
NOT RUN in the delivery (owner rule).  Run: python3 test/test_v2_isolation_guard.py
Live modules: binance_trader, ai_live_client, protection_manager (real exchange calls) and execution_router (picks paper or live).
If this test fails, a file that is NOT on the list now reaches live trading: look at it before allowing it, then add it to the list on purpose.
The list is today's real situation (30 Oct 2026), not a wish."""
import ast
import os
import unittest

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
LIVE = {"binance_trader", "ai_live_client", "protection_manager"}
ROUTER = {"execution_router"}
ALLOW_LIVE = {"api/settings.py", "recovered_bot/ai_live_executor.py", "recovered_bot/app.py", "recovered_bot/binance_trader.py", "recovered_bot/exchange.py",
              "recovered_bot/execution_router.py", "recovered_bot/live_recorder.py", "recovered_bot/live_snapshot.py", "recovered_bot/protection_manager.py",
              "recovered_bot/reconciliation.py"}
ALLOW_ROUTER = {"api/preview_close.py", "api/trade.py", "api_server.py", "recovered_bot/app.py", "recovered_bot/exchange.py", "recovered_bot/execution_router.py",
                "recovered_bot/protection_manager.py", "recovered_bot/reconciliation.py"}
NEVER_PREFIX = ("v2_", "brain_", "dual_", "smart_brain", "pa_layer", "vol_layer", "trade_archive")   # research / paper layers (top level of backend)


def py_files():
    for root, _, files in os.walk(BACKEND):
        if "__pycache__" in root:
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.relpath(os.path.join(root, f), BACKEND).replace(os.sep, "/")


def names_imported(rel):
    """Every module / name a file imports anywhere (also inside functions). Last dotted part only: 'from recovered_bot import binance_trader' counts."""
    with open(os.path.join(BACKEND, rel), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[-1] for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                out.add(n.module.split(".")[-1])
            out |= {a.name for a in n.names}
    return out


def scan(wanted):
    return {r for r in py_files() if names_imported(r) & wanted}


class GuardTest(unittest.TestCase):
    def test_only_the_allow_list_imports_the_live_modules(self):
        extra = scan(LIVE) - ALLOW_LIVE
        self.assertEqual(extra, set(), "NEW file(s) import a live trading module: %s" % sorted(extra))

    def test_only_the_allow_list_imports_the_execution_router(self):
        extra = scan(ROUTER) - ALLOW_ROUTER
        self.assertEqual(extra, set(), "NEW file(s) import the execution router: %s" % sorted(extra))

    def test_research_and_paper_layers_never_touch_live_code(self):
        bad = sorted(r for r in scan(LIVE | ROUTER) if "/" not in r and r.startswith(NEVER_PREFIX))
        self.assertEqual(bad, [], "a research / paper layer imports live code: %s" % bad)

    def test_v2_api_data_route_is_read_only_code(self):
        self.assertNotIn("api/v2_data.py", scan(LIVE | ROUTER))

    def test_the_allow_list_points_at_real_files(self):
        have = set(py_files())
        self.assertEqual((ALLOW_LIVE | ALLOW_ROUTER) - have, set(), "allow-list names a file that no longer exists: update the list on purpose")

    def test_the_scan_really_sees_a_known_live_importer(self):
        self.assertIn("recovered_bot/execution_router.py", scan(LIVE))


if __name__ == "__main__":
    unittest.main()
