"""ai_health report. Run: python3 test/test_ai_health.py"""
import os
import sys
import tempfile

home = tempfile.mkdtemp()
os.environ["HOME"] = home
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from recovered_bot import ai_health

r = ai_health.build_report()
assert isinstance(r, dict)
assert "summary" in r and "suggestions" in r and "freezes" in r
assert isinstance(r["suggestions"], list) and len(r["suggestions"]) >= 1
text = ai_health.plain_text()
assert "APP HEALTH" in text
assert "Suggestions" in text
print("PASS test_ai_health")
print("--- sample ---")
print(text[:600])
