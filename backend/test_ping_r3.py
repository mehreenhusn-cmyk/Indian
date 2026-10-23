#!/usr/bin/env python3
"""Ping round 3 tests: Lead baseline, snapshot rows, fast state file, bot save throttle."""
import json, os, sys, tempfile, time

os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp(prefix="ping_r3_test_")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recovered_bot import ping_store as st
from recovered_bot.ping_radar import PingRadar
from recovered_bot.ping_engine import PingEngine
from recovered_bot.ping_tracker import PingTracker
from recovered_bot.ping_bot import PingBot

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name}")


def radar_with(order):
    r = PingRadar()
    for i, s in enumerate(order):
        r.on_ticker(s, 1_000_000, 1.0, change_pct=float(i))   # later in list = bigger rise
    return r


def main():
    # 1. Lead baseline: coins already in the top 10 at start are NOT "entries"
    syms = [f"C{i:02d}USDT" for i in range(40)]
    r = radar_with(syms)
    eng = PingEngine()
    store = {}
    tr = PingTracker(eng, r, lambda d: store.update(d), lambda: dict(store))
    tr.tick_lead(now=1_700_000_000.0)
    check("first tick records no entries", tr.lead_snapshot()["today_count"] == 0)
    # a new coin jumps to the top -> a real entry
    r.on_ticker("NEWUSDT", 1_000_000, 1.0, change_pct=99.0)
    tr.tick_lead(now=1_700_000_060.0)
    check("a coin that really enters the top 10 is counted", tr.lead_events and tr.lead_events[-1]["symbol"] == "NEWUSDT")
    n = len(tr.lead_events)
    tr.tick_lead(now=1_700_000_120.0)
    check("same coin is not counted twice", len(tr.lead_events) == n)

    # 2. restart the same day: tracker baselines again, no fake entries
    tr2 = PingTracker(eng, r, lambda d: store.update(d), lambda: dict(store))
    before = len(tr2.lead_events)
    tr2.tick_lead(now=1_700_000_180.0)
    check("restart does not add fake entries", len(tr2.lead_events) == before)

    # 3. state snapshot: fast write, no .bak, readable
    st.write_state({"ts": time.time(), "rows": [1]})
    st.write_state({"ts": time.time(), "rows": [1, 2]})
    check("state readable", st.read_state().get("rows") == [1, 2])
    check("state writes leave no .bak", not os.path.exists(st.state_path() + ".bak"))

    # 4. lead/trades keep the safe .bak, and ping-reset must remove both
    st.write_lead({"a": 1}); st.write_lead({"a": 2})
    check("lead keeps a .bak copy", os.path.exists(st.lead_path() + ".bak"))
    os.remove(st.lead_path())
    check("deleting only the main file would bring old data back from .bak", st.read_lead().get("a") == 1)
    os.remove(st.lead_path() + ".bak")
    check("after removing .bak too, lead is empty", st.read_lead() == {})

    # 5. bot save throttle: an idle bot does not rewrite its file every tick
    writes = []
    bot = PingBot(PingEngine(), lambda d: writes.append(d), lambda: {})
    t0 = 1_700_000_000.0
    for i in range(30):
        bot.tick(now=t0 + i * 5)          # 150 s, nothing happens
    check("idle bot writes about once a minute, not every tick", 1 <= len(writes) <= 4)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
