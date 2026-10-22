#!/usr/bin/env python3
"""Ping feed tests (round 2): Binance /market URLs, miniTicker change %, history seed,
EMA warm-up gate, and the radar loop against a fake WebSocket (no network needed)."""
import asyncio, json, os, sys, tempfile, time, types

os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp(prefix="ping_feed_test_")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recovered_bot.ping_radar import PingRadar, parse_mini_ticker
from recovered_bot.ping_engine import PingEngine
from recovered_bot.ping_bot import PingBot
from recovered_bot import ping_collector as pc

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name}")


def mini_items(n=300):
    # realistic !miniTicker@arr item: only e,E,s,c,o,h,l,v,q (NO "P")
    out = []
    for i in range(n):
        o = 1.0
        c = 1.0 + (i - n // 2) / 1000.0
        out.append({"e": "24hrMiniTicker", "E": 1, "s": f"C{i:03d}USDT", "c": str(c), "o": str(o),
                    "h": str(max(o, c)), "l": str(min(o, c)), "v": "10", "q": "1000000"})
    return out


def kline_rows(n, now, price=100.0):
    rows = []
    for i in range(n):
        close_ms = int((now - (n - i) * 60 + 59) * 1000)
        p = price + i * 0.01
        rows.append([close_ms - 59999, str(p), str(p + 0.05), str(p - 0.05), str(p), "10", close_ms,
                     "1000", 10, "5", "500", "0"])
    # last row = candle still open (closes in the future)
    rows.append([int(now * 1000), "101", "101", "101", "101", "1", int((now + 50) * 1000), "10", 1, "1", "5", "0"])
    return rows


def main():
    # 1. parser
    check("parse: change from open/close", abs(parse_mini_ticker(mini_items()[299])[3] - 14.9) < 0.01)
    check("parse: non-USDT ignored", parse_mini_ticker({"s": "BTCUSD_PERP", "c": "1", "o": "1", "q": "1"}) is None)
    check("parse: bad numbers ignored", parse_mini_ticker({"s": "AAAUSDT", "c": "x", "o": "1", "q": "1"}) is None)

    # 2. watchlist = true top gainers / losers
    r = PingRadar()
    for t in mini_items():
        s, q, c, ch = parse_mini_ticker(t)
        r.on_ticker(s, q, c, change_pct=ch)
    g, l = r.top_bottom_by_change(10)
    check("gainers start with the biggest riser", g[0] == "C299USDT" and g[9] == "C290USDT")
    check("losers start with the biggest faller", l[0] == "C000USDT" and l[9] == "C009USDT")

    # 3. URLs use the /market route
    import ping_worker as pw
    check("radar urls are all /market", all("/market/" in u for u in pw.RADAR_URLS))
    check("kline url is /market/stream", pc.build_stream_url(["AAAUSDT", "BBBUSDT"]).startswith(
        "wss://fstream.binance.com/market/stream?streams=aaausdt@kline_1m/bbbusdt@kline_1m"))

    # 4. history seed
    eng = PingEngine()
    now = 1_700_000_000.0
    used = eng.seed_history("AAAUSDT", kline_rows(100, now), now=now)
    cs = eng.get("AAAUSDT")
    check("seed uses closed candles only", used == 100 and cs.n_closes == 100)
    check("seed sets EMA30 and EMA50", cs.ema30 is not None and cs.ema50 is not None and cs.ema30 > cs.ema50)
    check("seed registers no pings", eng.pop_events() == [] and not cs.ping_times_buy)
    check("seed fills the baseline", len(cs.net_hist) == 60)
    check("seed is skipped if live candles exist", eng.seed_history("AAAUSDT", kline_rows(100, now), now=now) == 0)

    # 5. EMA warm-up gate in the bot
    eng2 = PingEngine()
    box = {}
    bot = PingBot(eng2, lambda d: box.update(d=d), lambda: box.get("d") or {})
    base = now
    for i in range(25):
        eng2.on_closed_candle("BBBUSDT", 1000, 600, 100.0, int((base + i * 60) * 1000),
                              quote_vol_24h=1e9, high=100, low=99.9, open_=100)
    t1 = base + 25 * 60
    for i in range(5):
        px = 100.0 + 0.1 * (i + 1)
        eng2.on_closed_candle("BBBUSDT", 100000, 90000, px, int((t1 + i * 60) * 1000),
                              quote_vol_24h=1e9, high=px * 1.001, low=px * 0.995, open_=px)
    c2 = eng2.get("BBBUSDT")
    c2.ema30 = 99.0
    c2.ema50 = 98.0
    c2.n_closes = 10
    bot.tick(now=t1 + 5 * 60)
    vs = {t.variant for t in bot.open.values() if t.symbol == "BBBUSDT"}
    check("not warmed up: only variant C trades", vs == {"C"})
    c2.n_closes = 35
    bot.tick(now=t1 + 5 * 60 + 1)
    vs = {t.variant for t in bot.open.values() if t.symbol == "BBBUSDT"}
    check("30 candles: variant A allowed, B still blocked", "A" in vs and "B" not in vs)
    c2.n_closes = 60
    bot.tick(now=t1 + 5 * 60 + 2)
    vs = {t.variant for t in bot.open.values() if t.symbol == "BBBUSDT"}
    check("50+ candles: variant B allowed", "B" in vs)

    # 6. radar loop against a fake websocket
    asyncio.run(radar_loop_test(pw))

    # 7. collector: history first, then live closed candles -> a BUY ping
    asyncio.run(collector_test())


async def radar_loop_test(pw):
    urls_used = []
    payload = json.dumps(mini_items())

    class FakeWS:
        def __init__(self, silent):
            self.silent = silent
            self.sent = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def recv(self):
            if self.silent:               # old-style URL: socket opens, sends nothing
                await asyncio.sleep(3600)
            self.sent += 1
            if self.sent > 2:
                await asyncio.sleep(3600)
            return payload

    def fake_connect(url, **kw):
        urls_used.append(url)
        return FakeWS(silent=(len(urls_used) == 1))

    fake = types.ModuleType("websockets")
    fake.connect = fake_connect
    sys.modules["websockets"] = fake
    pw.NO_DATA_SEC = 0.3
    pw.RECONNECT_BASE_SEC = 0.05
    w = pw.Worker()
    task = asyncio.create_task(w.radar_loop())
    for _ in range(100):
        await asyncio.sleep(0.1)
        if w.collector.candidates:
            break
    w._stop = True
    task.cancel()
    try:
        await task
    except BaseException:
        pass
    check("silent first url -> switches to the next url", len(urls_used) >= 2)
    check("radar receives data and counts it", w.radar_msgs >= 1 and len(w.radar.all_symbols()) == 300)
    check("watchlist candidates appear (20 coins)", len(w.collector.candidates) == 20)
    top = sorted(w.collector.candidates)
    check("watchlist = 10 top gainers + 10 top losers",
          all(f"C{i:03d}USDT" in top for i in list(range(0, 10)) + list(range(290, 300))))


async def collector_test():
    now = time.time()
    seeded_calls = []

    def fake_fetch(sym, *a, **k):
        seeded_calls.append(sym)
        return kline_rows(100, now)

    def kmsg(ts_ms, closed=True):
        return json.dumps({"stream": "aaausdt@kline_1m", "data": {"e": "kline", "s": "AAAUSDT", "k": {
            "s": "AAAUSDT", "t": ts_ms - 59999, "T": ts_ms, "o": "100", "c": "101", "h": "101.5", "l": "99.9",
            "q": "200000", "Q": "190000", "x": closed}}})

    class FakeWS:
        def __init__(self):
            self.i = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def recv(self):
            self.i += 1
            if self.i == 1:
                return kmsg(int(now * 1000) - 120000, closed=False)   # open candle: ignored
            if self.i <= 4:
                return kmsg(int(now * 1000) - 120000 + (self.i - 1) * 60000)
            await asyncio.sleep(3600)

    urls = []

    def fake_connect(url, **kw):
        urls.append(url)
        return FakeWS()

    fake = types.ModuleType("websockets")
    fake.connect = fake_connect
    sys.modules["websockets"] = fake
    pc.fetch_klines = fake_fetch
    eng = PingEngine()
    rad = PingRadar()
    coll = pc.PingCollector(eng, rad)
    coll.update_candidates([], ["AAAUSDT"], [])
    task = asyncio.create_task(coll.run())
    for _ in range(60):
        await asyncio.sleep(0.1)
        if eng.get("AAAUSDT").n_closes >= 103:
            break
    coll.stop()
    task.cancel()
    try:
        await task
    except BaseException:
        pass
    cs = eng.get("AAAUSDT")
    check("collector: history fetched before the stream", seeded_calls == ["AAAUSDT"])
    check("collector: connects to /market/stream", bool(urls) and "/market/stream?streams=aaausdt@kline_1m" in urls[0])
    check("collector: live candles add to history (100 + 3)", cs.n_closes == 103)
    check("collector: big taker-buy candle -> BUY ping", len(cs.ping_times_buy) >= 1)
    check("collector: open (unclosed) candle ignored", cs.n_closes == 103)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
