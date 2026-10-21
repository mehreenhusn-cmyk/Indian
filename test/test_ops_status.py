"""ops_status: current-run problems + app-settings backup. Run: python3 test/test_ops_status.py"""
import os
import sys
import tempfile
import time

home = tempfile.mkdtemp()
os.environ["HOME"] = home
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

day = time.strftime("%Y-%m-%d")
log = os.path.join(home, "owl_backend.log")
# older run + current run
open(log, "w").write(
    f"[{day} 00:00:01] starting backend\n"
    f"[{day} 00:00:02] Error OLD should not show\n"
    f"[{day} 01:00:00] starting backend\n"
    f"[{day} 01:00:01] [STALL] OUR CODE BUSY event loop was frozen 2.0s\n"
    f"[{day} 01:00:05] Traceback (most recent call last):\n"
    f"[{day} 01:00:06] backend exited with code 1 after 3s\n"
)
open(os.path.join(home, ".owl_last_zip"), "w").write("/d/Download/Indian-main-x.zip 10 1760000000\n")

from recovered_bot import ops_status as o

d = tempfile.mkdtemp()
s = o.snapshot(d)
assert s["zip"]["name"] == "Indian-main-x.zip", s
assert s["restarts_today"] == 2, s
assert s.get("problems_scope") == "current_run", s
# OLD error must not appear
probs = " ".join(s.get("problems") or [])
assert "OLD should not show" not in probs, probs
assert "STALL" in probs or "Traceback" in probs, probs
assert s.get("run_started"), s

assert o.prefs_merge(d, {"theme_mode": "light", "evil": "x", "voice_enabled": True}) == {
    "theme_mode": "light",
    "voice_enabled": True,
}
assert o.prefs_get(d)["theme_mode"] == "light"
assert s.get("build", "").startswith("2026-10-21")
print("PASS test_ops_status")
