"""Part 9: AI Own plain summary + welcome screen remembers in a file with a build id."""
import os, sys, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

class FakeV:
    import threading
    _lock = threading.RLock()
    _state = {"trades": [], "dec": [], "scan": []}
    def quota_resume_at(self): return 0
    def _day0_ts(self): return 0

class Part9(unittest.TestCase):
    def test_summary_states(self):
        from recovered_bot import ai_vision_own as O
        V = FakeV()
        s = O.own_summary(V, [], [])
        self.assertIn(s["state"], ("off", "waiting", "paused"))
        O.enabled = lambda: True
        O._blocked_reason = lambda V: ""
        scan = [{"result": "skipped", "why": "TSI weak"}, {"result": "skipped", "why": "TSI weak"}, {"result": "none", "why": "no setup"}]
        s = O.own_summary(V, scan, [])
        self.assertEqual(s["state"], "looking")
        self.assertEqual((s["checked"], s["asked_ai"], s["taken"], s["skipped"]), (3, 2, 0, 2))
        self.assertEqual(s["top_reasons"][0], {"why": "TSI weak", "n": 2})
        s = O.own_summary(V, scan + [{"result": "taken"}], [{"status": "open"}])
        self.assertEqual(s["state"], "trading")
        O._blocked_reason = lambda V: "daily own loss cap reached"
        self.assertEqual(O.own_summary(V, scan, [])["state"], "paused")

    def test_files(self):
        w = open(os.path.join(ROOT, "frontend/lib/widgets/owl_welcome_overlay.dart"), encoding="utf-8").read()
        for need in ("owl_welcome_stamp.txt", "buildId", "getApplicationSupportDirectory", "build != OwlWelcomeOverlay.buildId"):
            self.assertIn(need, w)
        self.assertNotIn("storeIsPersistent &&", w)               # the splash no longer depends on the settings plugin
        v = open(os.path.join(ROOT, "frontend/lib/screens/vision_tab_screen.dart"), encoding="utf-8").read()
        self.assertIn("_ownSummaryCard(p)", v)

if __name__ == "__main__":
    unittest.main()
