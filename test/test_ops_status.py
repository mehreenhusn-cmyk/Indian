"""ops_status: /api/ops numbers + app-settings backup. Run: python3 test/test_ops_status.py"""
import os, sys, tempfile
home = tempfile.mkdtemp(); os.environ["HOME"] = home
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
open(os.path.join(home, ".owl_last_zip"), "w").write("/d/Download/Indian-main-x.zip 10 1760000000\n")
open(os.path.join(home, "owl_backend.log"), "w").write("[%s 00:00:01] starting backend\n[x] Traceback (most recent call last):\n[x] backend exited with code 1 after 3s\n" % __import__("time").strftime("%Y-%m-%d"))
from recovered_bot import ops_status as o
d = tempfile.mkdtemp(); s = o.snapshot(d)
assert s["zip"]["name"] == "Indian-main-x.zip" and s["restarts_today"] == 1 and s["problems"], s
assert o.prefs_merge(d, {"theme_mode": "light", "evil": "x", "voice_enabled": True}) == {"theme_mode": "light", "voice_enabled": True}
assert o.prefs_get(d)["theme_mode"] == "light"
print("PASS test_ops_status")
