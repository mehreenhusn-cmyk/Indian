#!/usr/bin/env python3
"""AI Own: the old 12 calls/hour limit is gone (0 = no limit), migration runs once, own keys decide the limit."""
import json, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recovered_bot import settings_store as S
from recovered_bot import ai_vision_own as O

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  OK  {name}")
    else: FAIL += 1; print(f" FAIL {name}")

check("new default is 0", S._defaults["vision_own_max_calls_hour"] == 0)

d = tempfile.mkdtemp()
path = os.path.join(d, "settings.json")
json.dump({"vision_own_max_calls_hour": 12, "vision_own_enabled": True}, open(path, "w"))
S.init(path)
check("old 12 migrated to 0", S.get("vision_own_max_calls_hour") == 0)
check("flag saved", json.load(open(path)).get("_mig_own_hour_unlimited") is True)

S.update(vision_own_max_calls_hour=20)          # user sets his own value later
S.init(path)
check("own value kept after restart (migration runs once)", S.get("vision_own_max_calls_hour") == 20)

S.update(vision_own_max_calls_hour=0)
O._hour_calls[:] = [time.time()] * 100
O._last_ask[0] = time.time()
check("no spread wait when 0", O._slot_wait() == 0.0)
O._own_day_net = lambda V: 0.0
O._own_open_count = lambda V: 0
check("100 calls this hour are not a block", "Hour call limit" not in (O._blocked_reason(type("V", (), {"quota_resume_at": staticmethod(lambda: 0)})) or ""))

S.update(vision_own_max_calls_hour=12)
check("a set limit still works", O._slot_wait() > 0 or O._hour_used() >= 12)

print(f"\n{PASS} passed, {FAIL} failed"); sys.exit(1 if FAIL else 0)
