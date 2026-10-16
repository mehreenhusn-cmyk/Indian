"""Score-lock test: AI files must never read ai_book / the health score (see ai_guard.py).
Run:  python3 test/test_ai_isolation.py     (also runs in CI before the APK build)"""
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = os.path.join(ROOT, "backend", "recovered_bot")
spec = importlib.util.spec_from_file_location("ai_guard", os.path.join(BOT, "ai_guard.py"))
ai_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai_guard)


class AiIsolation(unittest.TestCase):
    def test_real_ai_files_are_clean(self):
        self.assertEqual(ai_guard.check(BOT), [])

    def test_guard_catches_import(self):
        self.assertTrue(ai_guard.check_source("from . import ai_book\n"))
        self.assertTrue(ai_guard.check_source("from .ai_book import summary\n"))
        self.assertTrue(ai_guard.check_source("import recovered_bot.ai_book\n"))

    def test_guard_catches_health_read(self):
        self.assertTrue(ai_guard.check_source("x = d['health']\n"))
        self.assertTrue(ai_guard.check_source("x = d.get('health')\n"))
        self.assertTrue(ai_guard.check_source("x = ai_book._health(1)\n"))

    def test_guard_catches_ml_numbers_in_chat_files(self):
        self.assertTrue(ai_guard.check_source("ai_ml.shadow_stats()\n", chat=True))
        self.assertTrue(ai_guard.check_source("ai_ml.predict(t)\n", chat=True))
        self.assertEqual(ai_guard.check_source("ai_ml.build_text()\n", chat=True), [])

    def test_words_in_text_are_fine(self):
        self.assertEqual(ai_guard.check_source('"""the health score is screen only"""\n'), [])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)
