"""Part 6: AI Own checks are spread over the hour, the limit message says when it resumes, the JSON dump is timed, compression is guarded."""
import os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from recovered_bot import ai_vision_own as OWN, telemetry


def test_spacing():
    OWN._num = lambda k, d: 12 if k == "vision_own_max_calls_hour" else d
    OWN._last_ask[0] = 0.0
    assert OWN._slot_wait() == 0.0, "first check is never delayed"
    now = 10_000.0
    OWN._last_ask[0] = now - 60
    w = OWN._slot_wait(now)
    assert 235 < w < 245, w                                   # 12/hour = one every 300 s, 60 s already passed
    OWN._last_ask[0] = now - 301
    assert OWN._slot_wait(now) == 0.0
    OWN._num = lambda k, d: 0 if k == "vision_own_max_calls_hour" else d
    OWN._last_ask[0] = now
    assert OWN._slot_wait(now) == 0.0, "0 = no limit, no spacing"


def test_resume_time():
    OWN._hour_calls[:] = [1000.0, 1100.0]
    assert abs(OWN._hour_resume_in(1000.0 + 3000.0) - 600.0) < 1.0     # oldest call frees its slot 3600 s after it was made
    OWN._hour_calls[:] = []
    assert OWN._hour_resume_in() == 0.0


def test_dump_timing_and_start_guard():
    telemetry.record_broadcast(5.0, 1000, 1, build_ms=2.0, dropped=0, dumps_ms=3.5)
    assert telemetry._bc["dumps_ms"] > 0 and telemetry._bc["dumps_max"] >= 3.5
    start = open(os.path.join(ROOT, "backend", "start.py")).read()
    assert "ws_per_message_deflate" in start and "inspect.signature(uvicorn.Config.__init__)" in start and "**_EXTRA" in start
    api = open(os.path.join(ROOT, "backend", "api_server.py")).read()
    assert "dumps_ms=_dumps_ms" in api
    lab = open(os.path.join(ROOT, "frontend", "lib", "widgets", "vision_lab_view.dart")).read()
    assert "AI said: $aiSaid" in lab


if __name__ == "__main__":
    test_spacing(); test_resume_time(); test_dump_timing_and_start_guard()
    print("ALL test_part6 passed")
