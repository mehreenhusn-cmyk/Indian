"""Part 23 test (written, NOT RUN when delivered - owner rule: no useless test runs).
Static checks of frontend/lib/models/diag_status.dart + a Python mirror of the level rules.
Dart is not compiled in the sandbox; the owner's APK build is the compile proof.
Run:  python3 test/test_v2_diag_status.py"""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "frontend", "lib", "models", "diag_status.dart"), encoding="utf-8").read()


def ws_level(connected, age):                    # mirror of DiagStatus._ws
    if connected is None:
        return "unknown"
    if not connected:
        return "bad"
    if age is None:
        return "warn"
    return "bad" if age > 6 else "warn" if age > 3 else "ok"


def market_level(s):                             # mirror of DiagStatus._market
    return {"LIVE": "ok", "REST": "warn", "CONNECTING": "warn", "RECONNECTING": "warn",
            "STALE": "bad", "DISCONNECTED": "bad"}.get(s, "unknown")


def overall(levels):                             # mirror of DiagStatus.overall
    if "bad" in levels:
        return "bad"
    if "warn" in levels:
        return "warn"
    return "unknown" if "unknown" in levels else "ok"


class Diag(unittest.TestCase):
    def test_six_keys_in_order(self):
        self.assertIn("static const List<String> keys = [", SRC)
        pos = [SRC.index("'%s'," % k) for k in ("backend", "ws", "market_data", "scanner", "strategy", "execution")]
        self.assertEqual(pos, sorted(pos))

    def test_ws_rules(self):
        self.assertEqual(ws_level(None, None), "unknown")
        self.assertEqual(ws_level(False, 0.5), "bad")
        self.assertEqual(ws_level(True, None), "warn")
        self.assertEqual([ws_level(True, a) for a in (1, 3.5, 7)], ["ok", "warn", "bad"])

    def test_market_rules(self):
        self.assertEqual(market_level("LIVE"), "ok")
        self.assertEqual(market_level("STALE"), "bad")
        self.assertEqual(market_level("whatever"), "unknown")
        self.assertEqual(market_level(None), "unknown")

    def test_unknown_is_never_ok(self):
        self.assertEqual(overall(["ok", "unknown", "ok"]), "unknown")
        self.assertEqual(overall(["ok", "warn", "unknown"]), "warn")
        self.assertEqual(overall(["warn", "bad", "ok"]), "bad")

    def test_pure_model_no_imports_no_network(self):
        self.assertNotIn("import ", SRC)
        for bad in ("http", "WebSocket(", "dart:io", "flutter"):
            self.assertNotIn(bad, SRC.replace("'WebSocket'", ""))


if __name__ == "__main__":
    unittest.main()
