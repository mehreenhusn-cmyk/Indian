#!/usr/bin/env python3
"""Tests for paper Ping Bot: LONG/SHORT, EMA variants, chase, absorbed, SL ladder, TP4, signal exit, time stop."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recovered_bot.ping_engine import PingEngine
from recovered_bot.ping_bot import PingBot, ENTRY_PINGS_5M, TIME_STOP_MIN, MAX_CHASE_PCT

PASS = FAIL = 0

def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name}")

def ts_ms(s):
    return int(s * 1000)

def seed_pings(eng, sym, n, base, side="BUY", price=100.0, move_pct=0.5):
    """Seed small nets then n large pings. move_pct keeps trade out of absorbed/chase band."""
    for i in range(25):
        eng.on_closed_candle(sym, 1000, 600, price, ts_ms(base + i * 60),
                             quote_vol_24h=1e9, high=price, low=price * 0.999, open_=price)
    t1 = base + 25 * 60
    for i in range(n):
        # price walks ~move_pct over the pings so absorbed is false, chase is false
        step = price * (move_pct / 100.0) / max(n, 1)
        if side == "BUY":
            px = price + step * (i + 1)
            eng.on_closed_candle(sym, 100000, 90000, px, ts_ms(t1 + i * 60),
                                 quote_vol_24h=1e9, high=px * 1.001, low=px * 0.995, open_=px)
        else:
            px = price - step * (i + 1)
            eng.on_closed_candle(sym, 100000, 10000, px, ts_ms(t1 + i * 60),
                                 quote_vol_24h=1e9, high=px * 1.005, low=px * 0.999, open_=px)
    return t1 + n * 60

def mem_store():
    box = {}
    def write(d):
        box["d"] = d
    def read():
        return box.get("d") or {}
    return write, read, box

def main():
    global PASS, FAIL
    base = 1_700_000_000.0
    write, read, box = mem_store()
    eng = PingEngine()
    bot = PingBot(eng, write, read)

    # LONG entry variant C after enough BUY pings
    now = seed_pings(eng, "AAAUSDT", 5, base, "BUY", 100.0)
    bot.tick(now=now)
    open_c = [t for t in bot.open.values() if t.symbol == "AAAUSDT" and t.variant == "C" and t.side == "LONG"]
    check("LONG entry variant C", len(open_c) == 1)

    # EMA30 filter: seed with closes above EMA for A
    eng2 = PingEngine()
    bot2 = PingBot(eng2, *mem_store()[:2])
    now2 = seed_pings(eng2, "BBBUSDT", 5, base, "BUY", 50.0)
    # force ema
    cs = eng2.get("BBBUSDT")
    cs.ema30 = 49.0
    cs.ema50 = 48.0
    bot2.tick(now=now2)
    check("variant A LONG when close > EMA30", any(t.variant == "A" and t.side == "LONG" for t in bot2.open.values()))

    # SHORT experimental
    eng3 = PingEngine()
    bot3 = PingBot(eng3, *mem_store()[:2])
    now3 = seed_pings(eng3, "CCCUSDT", 5, base, "SELL", 80.0)
    cs = eng3.get("CCCUSDT")
    cs.ema30 = 81.0
    bot3.tick(now=now3)
    shorts = [t for t in bot3.open.values() if t.side == "SHORT"]
    check("SHORT entry exists", len(shorts) >= 1)
    check("SHORT tagged experimental", all(t.experimental for t in shorts))

    # chase guard
    eng4 = PingEngine()
    bot4 = PingBot(eng4, *mem_store()[:2])
    now4 = seed_pings(eng4, "DDDUSDT", 5, base, "BUY", 100.0)
    cs = eng4.get("DDDUSDT")
    cs.first_ping_price = 100.0
    cs.price = 100.0 * (1 + (MAX_CHASE_PCT + 0.5) / 100.0)
    bot4.tick(now=now4 + 1)
    check("chase skips entry", not any(t.symbol == "DDDUSDT" for t in bot4.open.values()))
    check("chase skip logged", any(s.get("reason") == "chased" for s in bot4.skips))

    # SL ladder + TP4
    eng5 = PingEngine()
    write5, read5, _ = mem_store()
    bot5 = PingBot(eng5, write5, read5)
    now5 = seed_pings(eng5, "EEEUSDT", 5, base, "BUY", 100.0)
    cs = eng5.get("EEEUSDT")
    cs.ema30 = 99.0
    bot5.tick(now=now5)
    key = ("EEEUSDT", "C", "LONG")
    check("open for TP test", key in bot5.open)
    tr = bot5.open[key]
    R = abs(tr.entry - tr.sl)
    # walk price to TP1
    cs.price = tr.entry + R * 1.01
    bot5._manage_open(now5 + 10)
    check("TP1 hit SL to entry", tr.tp_hits >= 1 and abs(tr.sl - tr.entry) < 1e-9)
    cs.price = tr.entry + R * 2.01
    bot5._manage_open(now5 + 20)
    check("TP2 hit SL to TP1", tr.tp_hits >= 2 and abs(tr.sl - tr.tp[0]) < 1e-9)
    cs.price = tr.entry + R * 3.01
    bot5._manage_open(now5 + 30)
    check("TP3 hit SL to TP2", tr.tp_hits >= 3 and abs(tr.sl - tr.tp[1]) < 1e-9)
    cs.price = tr.entry + R * 4.01
    bot5._manage_open(now5 + 40)
    check("TP4 full close", key not in bot5.open and any(d.get("exit_reason") == "tp4" for d in bot5.closed))

    # time stop
    eng6 = PingEngine()
    bot6 = PingBot(eng6, *mem_store()[:2])
    now6 = seed_pings(eng6, "FFFUSDT", 5, base, "BUY", 100.0)
    bot6.tick(now=now6)
    key6 = ("FFFUSDT", "C", "LONG")
    check("open for time stop", key6 in bot6.open)
    bot6._manage_open(now6 + TIME_STOP_MIN * 60 + 1)
    check("time stop closes", key6 not in bot6.open and any(d.get("exit_reason") == "time_stop" for d in bot6.closed))

    # signal exit
    eng7 = PingEngine()
    bot7 = PingBot(eng7, *mem_store()[:2])
    now7 = seed_pings(eng7, "GGGUSDT", 5, base, "BUY", 100.0)
    bot7.tick(now=now7)
    key7 = ("GGGUSDT", "C", "LONG")
    cs = eng7.get("GGGUSDT")
    cs.ema30 = 101.0
    cs.recent_net = -50000
    cs.price = 100.2
    bot7._manage_open(now7 + 10)
    check("signal exit", key7 not in bot7.open and any(d.get("exit_reason") == "signal" for d in bot7.closed))

    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)

if __name__ == "__main__":
    main()
