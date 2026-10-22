"""Tests for the review fixes: episode reset, radar re-flag, collector resubscribe.
Run: cd backend && python test_ping_fixes.py
"""
import asyncio
import sys
import time

from recovered_bot.ping_engine import PingEngine, EPISODE_GAP_SEC
from recovered_bot.ping_radar import PingRadar, RADAR_REFLAG_SEC
from recovered_bot.ping_collector import PingCollector
import recovered_bot.ping_collector as pc

fails = 0


def ok(name, cond):
    global fails
    print(("  OK  " if cond else "  FAIL ") + name)
    if not cond:
        fails += 1


# 1. first-ping price resets after a quiet gap (chase guard must not use a stale price)
e = PingEngine()
t0 = 1_700_000_000_000
for i in range(6):  # build a baseline of small candles
    e.on_closed_candle("AAAUSDT", 100000, 50000, 1.0, t0 + i * 60000)
e.on_closed_candle("AAAUSDT", 500000, 450000, 1.00, t0 + 7 * 60000)  # BUY ping at 1.00
cs = e.get("AAAUSDT")
ok("first ping price set", cs.first_ping_price == 1.00)
later = t0 + (7 * 60 + EPISODE_GAP_SEC + 120) * 1000
e.on_closed_candle("AAAUSDT", 500000, 450000, 1.30, later)  # next BUY ping, hours later
ok("first ping price resets after quiet gap", abs(cs.first_ping_price - 1.30) < 1e-9)

# side flip starts a new episode
e.on_closed_candle("AAAUSDT", 500000, 50000, 1.29, later + 60000)  # SELL ping
ok("side flip resets first ping side", cs.first_ping_side == "SELL")

# 2. radar can flag a coin again after the cool-off
r = PingRadar()
r.flagged["BBBUSDT"] = time.time() - RADAR_REFLAG_SEC - 5
base = 1_000_000.0
now = 1_800_000_000.0
r.on_ticker("BBBUSDT", base, 1.0)
for i in range(8):  # quiet history, 1 minute apart
    r.on_ticker("BBBUSDT", base + i * 1000, 1.0)
    r.maybe_evaluate(now=now + i * 60)
r.on_ticker("BBBUSDT", base + 8 * 1000 + 400000, 1.0)  # big minute
r.flagged["BBBUSDT"] = (now + 8 * 60) - RADAR_REFLAG_SEC - 5
newly = r.maybe_evaluate(now=now + 8 * 60)
ok("radar re-flags old coin after cool-off", "BBBUSDT" in newly)

# 3. collector reconnects when the wanted set changes
async def collector_test():
    pc.RESUB_CHECK_SEC = 0.05
    pc.RESUB_MIN_SEC = 0.1
    eng = PingEngine()
    rad = PingRadar()
    c = PingCollector(eng, rad)
    c.candidates = {"AAAUSDT": {"flag_ts": time.time(), "watchlist": True, "last_ping_ts": None}}
    seen = []

    async def fake_batch(symbols, on_health):
        seen.append(tuple(symbols))
        await asyncio.sleep(10)

    c._one_batch = fake_batch
    task = asyncio.create_task(c._run_batches([["AAAUSDT"]], None))
    await asyncio.sleep(0.3)
    c.candidates["CCCUSDT"] = {"flag_ts": time.time(), "watchlist": False, "last_ping_ts": None}
    await asyncio.wait_for(task, 2.0)  # must return by itself so run() can resubscribe
    return True


try:
    ok("collector returns when candidate set changes", asyncio.run(collector_test()))
except Exception as ex:
    ok(f"collector resubscribe ({ex})", False)

print(f"\n{'ALL PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
