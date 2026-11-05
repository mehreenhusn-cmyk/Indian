"""v2_candles_ws.py - Part 17e (Step C): LIVE CANDLES from the Binance futures websocket, REST only for the holes.
One websocket connection listens to the 3m and 5m kline streams of the same coins the REST collector uses (v2_candles.pick_symbols, at most 40 coins = 80 streams).
Only a CLOSED candle (kline flag x = true) is saved, with the same checks and the same table as the REST collector (v2_store.add_candle, v2_defs.clean_candles).
NO HOLE RULE: a live candle is saved ONLY when the candle before it is already known (saved, or covered by a recorded gap). Otherwise it is skipped and counted; the REST collector
(v2_candles.loop, every 60 s, forward refill) then fetches everything from the newest known candle up to now, so the missing part and this candle both arrive by REST. So a lost
connection can never leave an unrecorded hole behind a live candle. A coin with no candle at all is left to REST (it fetches the first 500).
Same switch as the REST collector (v2_candles_enabled, healed by v2_candles.self_heal). Public market data only, no key, no order path, writes only v2_market.db and v2_candles_ws.json.
Reconnects with a growing wait (5 s up to 5 min), tries the second address when the first fails, refreshes the coin list every 30 min. Needs the python package `websockets`
(already in requirements); without it this thread only writes a note and REST keeps working alone. Runs as ONE thread inside the V2 runner worker (v2_runner.py).
Status file v2_candles_ws.json (the Data Health page shows it): connected, last message age, saved, skipped, reconnects, last error.
"""
import asyncio
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v2_candles as K
import v2_defs as D
import v2_store as S

VERSION = "v2_candles_ws 1 (Part 17e)"
STATUS_FILE = "v2_candles_ws.json"
URLS = ("wss://fstream.binance.com/market/stream?streams=", "wss://fstream.binance.com/stream?streams=")
REFRESH_S, NO_DATA_S, FLUSH_S, FIRST_DELAY_S = 1800, 120, 30, 60
BACKOFF = (5, 10, 30, 60, 120, 300)
_ST = {"version": VERSION, "connected": False, "url": None, "coins": 0, "saved": 0, "duplicate": 0, "skipped_no_prev": 0, "refused": 0, "reconnects": 0,
       "last_msg_ts": None, "last_error": "", "note": "", "flushed": 0.0}


def stream_names(symbols):
    return ["%s@kline_%s" % (s.lower(), iv) for s in symbols for iv in K.INTERVALS]


def parse_kline(msg):
    """PURE. One websocket message -> (symbol, interval, (open_ts, o, h, l, c, v)) for a CLOSED, valid candle on the grid, else None."""
    try:
        d = msg.get("data", msg) if isinstance(msg, dict) else None
        if not d or d.get("e") != "kline":
            return None
        k = d["k"]
        iv, sym = k["i"], k["s"]
        if not k.get("x") or iv not in K.INTERVALS or not K._symbol_ok(sym):
            return None
        ts = int(k["t"]) // 1000
        if ts % D.STEP[iv]:
            return None
        good, _bad = D.clean_candles([(ts, float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"]))], iv)
        return (sym, iv, good[0]) if good else None
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return None


def prev_known(con, sym, iv, ts):
    """True when the candle before ts is saved, or inside a recorded candle gap."""
    p = ts - D.STEP[iv]
    if con.execute("SELECT 1 FROM candles WHERE symbol=? AND interval=? AND open_ts=?", (sym, iv, p)).fetchone():
        return True
    return bool(con.execute("SELECT 1 FROM gap_log WHERE kind='candle' AND symbol=? AND interval=? AND from_ts<=? AND to_ts>=?", (sym, iv, p, p)).fetchone())


def save_live(con, sym, iv, c):
    """-> 'saved' / 'duplicate' / 'no_prev' / 'refused'. Never raises."""
    try:
        if not prev_known(con, sym, iv, c[0]):
            return "no_prev"
        return "saved" if S.add_candle(con, sym, iv, *c) else "duplicate"
    except Exception:
        return "refused"


def read_status(data_dir):
    p = os.path.join(os.path.realpath(data_dir), STATUS_FILE)
    try:
        if os.path.islink(p):
            return {}
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _flush(data_dir, force=False):
    if not force and time.time() - _ST["flushed"] < FLUSH_S:
        return
    _ST["flushed"] = time.time()
    p = os.path.join(os.path.realpath(data_dir), STATUS_FILE)
    try:
        if os.path.islink(p):
            return
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(dict(_ST, written_ts=int(time.time())), f)
        os.replace(p + ".tmp", p)
    except OSError:
        pass


async def _session(d, con, idx):
    import websockets
    syms = K.pick_symbols(con, int(time.time()))
    if not syms:
        _ST["note"] = "no coins yet (the ticker collector has not saved a list)"
        _flush(d, True)
        await asyncio.sleep(60)
        return
    url = URLS[idx % len(URLS)] + "/".join(stream_names(syms))
    started = time.time()
    _ST.update(url=URLS[idx % len(URLS)], coins=len(syms), note="connecting")
    async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2 ** 22) as ws:
        _ST.update(connected=True, note="live", last_error="")
        _flush(d, True)
        while time.time() - started < REFRESH_S and K.is_enabled(d):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=NO_DATA_S)
            except asyncio.TimeoutError:
                raise RuntimeError("socket open but no data for %d s" % NO_DATA_S)
            _ST["last_msg_ts"] = int(time.time())
            try:
                got = parse_kline(json.loads(raw))
            except ValueError:
                got = None
            if got:
                r = save_live(con, got[0], got[1], got[2])
                key = {"saved": "saved", "duplicate": "duplicate", "no_prev": "skipped_no_prev", "refused": "refused"}[r]
                _ST[key] += 1
            _flush(d)


def loop(data_dir):
    """Own thread inside the runner worker. Never raises, never ends."""
    d = os.path.realpath(data_dir)
    time.sleep(FIRST_DELAY_S)                 # REST does the first fill
    try:
        import websockets  # noqa: F401
    except ImportError:
        _ST["note"] = "python package websockets is missing: live candles off, REST keeps working"
        _flush(d, True)
        while True:
            time.sleep(3600)
    fails, idx = 0, 0
    while True:
        try:
            if not K.is_enabled(d):
                _ST.update(connected=False, note="candle switch is OFF")
                _flush(d, True)
                time.sleep(60)
                continue
            con = S.open_store(d)
            try:
                asyncio.run(_session(d, con, idx))
            finally:
                con.close()
            fails = 0
            _ST["connected"] = False
        except Exception as e:                    # any failure: wait, try the other address, never stop
            fails += 1
            idx += 1
            _ST.update(connected=False, reconnects=_ST["reconnects"] + 1, last_error="%s: %s" % (type(e).__name__, str(e)[:100]), note="waiting to reconnect")
            _flush(d, True)
            time.sleep(BACKOFF[min(fails - 1, len(BACKOFF) - 1)])
