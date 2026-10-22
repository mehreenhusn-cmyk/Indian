#!/usr/bin/env python3
"""Plain-script tests for ping_engine (no network).

Covers: BUY ping, SELL ping, below threshold, absorbed, rolling counts,
UTC hour reset, own-baseline threshold.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recovered_bot.ping_engine import (
    PingEngine, PING_MIN_USDT, PING_Z, ABSORB_MOVE_PCT, ABSORB_PINGS,
    YELLOW_MIN, RED_MIN,
)

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name}")


def ts_ms(epoch_sec):
    return int(epoch_sec * 1000)


def main():
    global PASS, FAIL
    eng = PingEngine()
    base = 1_700_000_000.0

    r = eng.on_closed_candle("AAAUSDT", 10000, 6000, 100.0, ts_ms(base), quote_vol_24h=1e9)
    check("below threshold returns None", r is None)

    r = eng.on_closed_candle("AAAUSDT", 100000, 90000, 101.0, ts_ms(base + 60), quote_vol_24h=1e9)
    check("BUY ping fires", r is not None and r["side"] == "BUY")
    check("BUY net positive", r is not None and r["net"] > 0)

    r = eng.on_closed_candle("BBBUSDT", 100000, 10000, 50.0, ts_ms(base + 60), quote_vol_24h=1e9)
    check("SELL ping fires", r is not None and r["side"] == "SELL")
    check("SELL net negative", r is not None and r["net"] < 0)

    # Seed many tiny nets so median stays low; then fire 5 large BUY pings.
    eng2 = PingEngine()
    t0 = base
    for i in range(30):
        eng2.on_closed_candle("CCCUSDT", 1000, 600, 10.0, ts_ms(t0 + i * 60), quote_vol_24h=1e9)
    t1 = t0 + 30 * 60
    for i in range(4):
        eng2.on_closed_candle("CCCUSDT", 100000, 90000, 10.0 + i * 0.01, ts_ms(t1 + i * 60), quote_vol_24h=1e9)
    row = eng2.row_for("CCCUSDT", now=t1 + 4 * 60, side="BUY")
    check("pings_5m == 4", row and row["pings_5m"] == 4)
    check("pings_15m == 4", row and row["pings_15m"] == 4)
    check("color yellow at 4", row and row["color"] == "yellow")

    eng2.on_closed_candle("CCCUSDT", 100000, 90000, 10.05, ts_ms(t1 + 5 * 60), quote_vol_24h=1e9)
    row = eng2.row_for("CCCUSDT", now=t1 + 5 * 60, side="BUY")
    check("color red at 5", row and row["color"] == "red")
    check("pings_15m == 5", row and row["pings_15m"] == 5)

    eng3 = PingEngine()
    h0 = (int(base // 3600) + 1) * 3600
    eng3.on_closed_candle("DDDUSDT", 100000, 90000, 20.0, ts_ms(h0 - 30), quote_vol_24h=1e9)
    eng3.on_closed_candle("DDDUSDT", 100000, 90000, 20.1, ts_ms(h0 - 10), quote_vol_24h=1e9)
    row = eng3.row_for("DDDUSDT", now=h0 - 5, side="BUY")
    check("pings_hour before boundary == 2", row and row["pings_hour"] == 2)
    eng3.on_closed_candle("DDDUSDT", 100000, 90000, 20.2, ts_ms(h0 + 10), quote_vol_24h=1e9)
    row = eng3.row_for("DDDUSDT", now=h0 + 15, side="BUY")
    check("pings_hour after boundary == 1", row and row["pings_hour"] == 1)

    eng4 = PingEngine()
    t = base
    for i in range(20):
        eng4.on_closed_candle("EEEUSDT", 10000, 7500, 30.0, ts_ms(t + i * 60), quote_vol_24h=1e9)
    r = eng4.on_closed_candle("EEEUSDT", 30000, 22500, 30.0, ts_ms(t + 21 * 60), quote_vol_24h=1e9)
    check("own-baseline: 15k net below T=20k", r is None)
    r = eng4.on_closed_candle("EEEUSDT", 50000, 37500, 30.1, ts_ms(t + 22 * 60), quote_vol_24h=1e9)
    check("own-baseline: 25k net fires BUY", r is not None and r["side"] == "BUY")

    eng5 = PingEngine()
    t = base
    price = 100.0
    for i in range(3):
        px = price + i * 0.01
        eng5.on_closed_candle("FFFUSDT", 100000, 90000, px, ts_ms(t + i * 60), quote_vol_24h=1e9)
    row = eng5.row_for("FFFUSDT", now=t + 3 * 60, side="BUY")
    check("absorbed true when flat", row and row["absorbed"] is True)

    eng6 = PingEngine()
    for i in range(3):
        px = 100.0 * (1 + 0.01 * i)
        eng6.on_closed_candle("GGGUSDT", 100000, 90000, px, ts_ms(t + i * 60), quote_vol_24h=1e9)
    row = eng6.row_for("GGGUSDT", now=t + 3 * 60, side="BUY")
    check("absorbed false when price moved", row and row["absorbed"] is False)

    cs = eng2.coins["CCCUSDT"]
    check("ema30 set", cs.ema30 is not None)
    check("ema50 set", cs.ema50 is not None)

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
