"""Part 7: India price push route exists, splash gate guard, tiny bar gaps (source checks, no server needed)."""
import os, re, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def rd(p):
    return open(os.path.join(ROOT, p), encoding="utf-8").read()

class Part7(unittest.TestCase):
    def test_ws_route(self):
        s = rd("backend/india_api.py")
        self.assertIn('@r.websocket("/ws_ticks")', s)
        self.assertIn("API_TOKEN", s)
        compile(s, "india_api.py", "exec")
    def test_app_uses_push_with_fallback(self):
        s = rd("frontend/lib/services/india_ticks.dart")
        self.assertIn("/api/india/ws_ticks", s)
        self.assertIn("_pushing", s)          # REST poll is skipped only while pushes arrive
        self.assertIn("_wsDown", s)           # reconnect
    def test_splash(self):
        s = rd("frontend/lib/widgets/owl_welcome_overlay.dart")
        self.assertIn("storeIsPersistent", s)
        self.assertIn("Trading System", s)
        self.assertIn("gate = const Duration(hours: 12)", s)
        self.assertIn("gap = 0.6", rd("frontend/lib/widgets/owl_load_sequence.dart"))

if __name__ == "__main__":
    unittest.main()
