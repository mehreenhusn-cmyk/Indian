"""Part 8: whole-app report builder never crashes (each section is isolated), Telegram login reminder fires once a day, Settings has the button."""
import os, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

class Part8(unittest.TestCase):
    def test_report_builds(self):
        from recovered_bot import ai_report
        t = ai_report.build_app_text()
        for head in ("ABOUT THE APP", "KNOWN PROBLEMS", "SETTINGS"):
            self.assertIn(head, t)
        low = t.lower()
        for secret in ("bot_token", "api_secret", "refresh_token ="):
            self.assertNotIn(secret, low)

    def test_login_reminder_once_a_day(self):
        from datetime import datetime, timezone, timedelta
        from recovered_bot import india_telegram as T
        class W:  # fake broker with 1 day left
            def auth_info(self): return {"refresh_days_left": 1}
        class RT: live = W(); login_ok = None; settings = {}
        o = T.IndiaTelegram.__new__(T.IndiaTelegram)
        o.rt, o.state, o.sent = RT(), {"count": 0, "sent": []}, []
        o._creds = lambda: ("tok", "chat")
        o._save_state = lambda: None
        o._post = lambda text, token, chat, kind: (o.sent.append(text) or (True, "sent"))
        now = datetime(2026, 10, 22, 9, 0, tzinfo=T.IST)
        self.assertTrue(o.remind_login(now))
        self.assertFalse(o.remind_login(now))                       # same day: no second message
        self.assertTrue(o.remind_login(now + timedelta(days=1)))    # next day: again
        self.assertEqual(len(o.sent), 2)
        RT.live = type("W2", (), {"auth_info": lambda s: {"refresh_days_left": 9}})()
        self.assertFalse(o.remind_login(now + timedelta(days=2)))   # plenty of days left: silent

    def test_settings_button(self):
        s = open(os.path.join(ROOT, "frontend/lib/screens/settings_screen.dart"), encoding="utf-8").read()
        self.assertIn("const ReportDownloadCard()", s)
        self.assertIn("/api/report/app_save", open(os.path.join(ROOT, "frontend/lib/widgets/report_download_card.dart"), encoding="utf-8").read())

if __name__ == "__main__":
    unittest.main()
