"""Candidate set management + kline_1m combined-stream subscriptions.

Keeps at most CAND_MAX candidates = radar-flagged coins + watchlist
(top-10 gainers + top-10 losers derived from miniTicker).
Subscribes in batches to <symbol>@kline_1m and calls engine on closed candles.
"""
import asyncio
import json
import time

# ---- constants (starting guesses) ----
CAND_MAX = 40
CAND_QUIET_MIN = 15
KLINE_BATCH = 20
RESUB_CHECK_SEC = 5.0     # how often to compare wanted vs subscribed coins
RESUB_MIN_SEC = 30.0      # never reconnect more often than this
WS_BASE = "wss://fstream.binance.com"
RECONNECT_BASE_SEC = 1.0
RECONNECT_MAX_SEC = 60.0


class PingCollector:
    def __init__(self, engine, radar):
        self.engine = engine
        self.radar = radar
        self.candidates = {}
        self._tasks = []
        self._stop = False
        self.ws_state = "INIT"
        self.last_msg_ts = 0.0
        self._subs = set()

    def update_candidates(self, newly_flagged, gainers, losers, now=None):
        now = now if now is not None else time.time()
        watch = set(gainers or []) | set(losers or [])

        for sym in newly_flagged:
            if sym not in self.candidates:
                self.candidates[sym] = {
                    "flag_ts": now,
                    "watchlist": sym in watch,
                    "last_ping_ts": None,
                }
            else:
                self.candidates[sym]["flag_ts"] = now

        for sym in watch:
            if sym not in self.candidates:
                self.candidates[sym] = {
                    "flag_ts": now,
                    "watchlist": True,
                    "last_ping_ts": None,
                }
            else:
                self.candidates[sym]["watchlist"] = True

        for sym, meta in self.candidates.items():
            meta["watchlist"] = sym in watch
            cs = self.engine.coins.get(sym)
            if cs is not None:
                cs.in_watchlist = meta["watchlist"]
                if cs.last_ping_ts:
                    meta["last_ping_ts"] = cs.last_ping_ts

        drop = []
        for sym, meta in list(self.candidates.items()):
            if meta["watchlist"]:
                continue
            last = meta.get("last_ping_ts")
            if last is None:
                if now - meta["flag_ts"] >= CAND_QUIET_MIN * 60:
                    drop.append(sym)
            elif now - last >= CAND_QUIET_MIN * 60:
                drop.append(sym)
        for sym in drop:
            self.candidates.pop(sym, None)

        if len(self.candidates) > CAND_MAX:
            items = sorted(
                self.candidates.items(),
                key=lambda kv: (0 if kv[1]["watchlist"] else 1, -(kv[1]["flag_ts"])),
            )
            self.candidates = dict(items[:CAND_MAX])

        return set(self.candidates.keys())

    def desired_symbols(self):
        return set(self.candidates.keys())

    async def run(self, on_health=None):
        self._stop = False
        backoff = RECONNECT_BASE_SEC
        while not self._stop:
            desired = self.desired_symbols()
            if not desired:
                self.ws_state = "IDLE"
                await asyncio.sleep(2.0)
                continue
            batches = _chunk(sorted(desired), KLINE_BATCH)
            try:
                self.ws_state = "CONNECTING"
                await self._run_batches(batches, on_health)
                backoff = RECONNECT_BASE_SEC
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.ws_state = f"RECONNECTING:{e}"
                if on_health:
                    on_health()
                await asyncio.sleep(backoff)
                backoff = min(RECONNECT_MAX_SEC, backoff * 2)

    async def _run_batches(self, batches, on_health):
        subscribed = set()
        for b in batches:
            subscribed |= set(b)
        started = time.time()
        tasks = [asyncio.create_task(self._one_batch(batch, on_health)) for batch in batches]
        self._tasks = tasks
        try:
            # Stop as soon as the wanted coin set changes (new flagged coin, top-10
            # reshuffle) so run() reconnects with the new set. Without this, new
            # candidates were never subscribed.
            while not self._stop:
                await asyncio.sleep(RESUB_CHECK_SEC)
                if any(t.done() for t in tasks):
                    for t in tasks:
                        if t.done() and t.exception():
                            raise t.exception()
                    break
                if time.time() - started >= RESUB_MIN_SEC and self.desired_symbols() != subscribed:
                    break
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._tasks = []

    async def _one_batch(self, symbols, on_health):
        import websockets
        streams = "/".join(f"{s.lower()}@kline_1m" for s in symbols)
        url = f"{WS_BASE}/stream?streams={streams}"
        async with websockets.connect(url, ping_interval=20, ping_timeout=20, max_size=2**22) as ws:
            self.ws_state = "LIVE"
            self._subs |= set(symbols)
            async for raw in ws:
                if self._stop:
                    break
                self.last_msg_ts = time.time()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                data = msg.get("data") or msg
                k = data.get("k") if isinstance(data, dict) else None
                if not k or not k.get("x"):
                    continue
                sym = (k.get("s") or data.get("s") or "").upper()
                if not sym:
                    continue
                total_q = k.get("q", 0)
                taker_Q = k.get("Q", 0)
                close = k.get("c", 0)
                high = k.get("h", close)
                low = k.get("l", close)
                open_ = k.get("o", close)
                ts_ms = k.get("T") or k.get("t") or 0
                qv24 = self.radar.quote_vol_24h(sym)
                in_wl = bool(self.candidates.get(sym, {}).get("watchlist"))
                event = self.engine.on_closed_candle(
                    sym, total_q, taker_Q, close, ts_ms,
                    quote_vol_24h=qv24, in_watchlist=in_wl,
                    high=high, low=low, open_=open_,
                )
                if event and sym in self.candidates:
                    self.candidates[sym]["last_ping_ts"] = event["ts"]
                if on_health:
                    on_health()

    def stop(self):
        self._stop = True
        for t in self._tasks:
            t.cancel()


def _chunk(lst, n):
    return [lst[i:i + n] for i in range(0, len(lst), n)] or [[]]
