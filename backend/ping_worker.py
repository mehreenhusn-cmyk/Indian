#!/usr/bin/env python3
"""Ping data engine worker - own process.

Binance WS -> radar + collector + engine -> ping_state.json every ~2 s.
Started by the owner as a second Termux command. Does not touch the live bot.
"""
import asyncio
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recovered_bot.ping_store import (
    write_state, append_event, state_path,
    write_trades, read_trades, write_lead, read_lead,
)
from recovered_bot.ping_radar import PingRadar, parse_mini_ticker
from recovered_bot.ping_collector import PingCollector, log, NO_DATA_SEC
from recovered_bot.ping_engine import PingEngine
from recovered_bot.ping_bot import PingBot
from recovered_bot.ping_tracker import PingTracker
from recovered_bot.ping_signal_bridge import SignalBridge, POLL_SEC

# ---- constants (starting guesses) ----
BUILD_TAG = "2026-10-23-ping-r2"
SNAPSHOT_SEC = 2.0
# Old /ws and /stream URLs were retired by Binance on 2026-04-23: they open but send nothing.
# miniTicker lives under /market. Try the raw path first, then the combined-stream form.
RADAR_URLS = (
    "wss://fstream.binance.com/market/ws/!miniTicker@arr",
    "wss://fstream.binance.com/market/stream?streams=!miniTicker@arr",
)
HEARTBEAT_SEC = 60.0
RECONNECT_BASE_SEC = 1.0
RECONNECT_MAX_SEC = 60.0


class Worker:
    def __init__(self):
        self.radar = PingRadar()
        self.engine = PingEngine()
        self.collector = PingCollector(self.engine, self.radar)
        self.bot = PingBot(self.engine, write_trades, read_trades)
        self.tracker = PingTracker(self.engine, self.radar, write_lead, read_lead)
        # Read-only link to the live bot's signals (owl.db) and closed trades.
        self.bridge = SignalBridge(self.tracker, os.path.dirname(os.path.dirname(state_path())))
        self.ws_state = "INIT"
        self.radar_msgs = 0
        self.radar_url_idx = 0
        self.last_msg_ts = 0.0
        self.started_ts = time.time()
        self._stop = False

    def health(self):
        age = None
        if self.last_msg_ts:
            age = time.time() - self.last_msg_ts
        if self.collector.last_msg_ts and (not self.last_msg_ts or self.collector.last_msg_ts > self.last_msg_ts):
            age = time.time() - self.collector.last_msg_ts
        return {
            "alive": True,
            "build_tag": BUILD_TAG,
            "ws_state": self.collector.ws_state if self.collector.ws_state != "INIT" else self.ws_state,
            "last_msg_age_sec": round(age, 2) if age is not None else None,
            "candidate_count": len(self.collector.candidates),
            "radar_msgs": self.radar_msgs,
            "radar_coins": len(self.radar.all_symbols()),
            "kline_msgs": self.collector.msgs,
            "uptime_sec": round(time.time() - self.started_ts, 1),
            "signal_link": self.bridge.status,
            "state_path": state_path(),
        }

    def write_snapshot(self):
        now = time.time()
        rows = self.engine.all_rows(now=now, only_with_pings=True)
        for sym, meta in self.collector.candidates.items():
            if meta.get("watchlist") and not any(r["symbol"] == sym for r in rows):
                cs = self.engine.get(sym)
                cs.in_watchlist = True
                px = self.radar.price(sym)
                if px:
                    cs.price = px
                cs.quote_vol_24h = self.radar.quote_vol_24h(sym)
                row = self.engine.row_for(sym, now=now, side="BUY")
                if row:
                    rows.append(row)
        snap = {
            "ts": now,
            "stale": False,
            "health": self.health(),
            "rows": rows,
            "candidates": sorted(self.collector.candidates.keys()),
            "bot": self.bot.snapshot(),
            "score": self.tracker.score_snapshot(),
            "lead": self.tracker.lead_snapshot(),
        }
        write_state(snap)
        for ev in self.engine.pop_events():
            append_event(ev)

    async def radar_loop(self):
        import websockets
        backoff = RECONNECT_BASE_SEC
        while not self._stop:
            url = RADAR_URLS[self.radar_url_idx % len(RADAR_URLS)]
            try:
                self.ws_state = "CONNECTING"
                async with websockets.connect(
                    url, ping_interval=20, ping_timeout=20, max_size=2**23
                ) as ws:
                    self.ws_state = "LIVE"
                    log(f"radar connected: {url}")
                    first = True
                    while not self._stop:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=NO_DATA_SEC)
                        except asyncio.TimeoutError:
                            raise RuntimeError(f"radar socket open but no data for {NO_DATA_SEC:.0f}s")
                        self.last_msg_ts = time.time()
                        self.radar_msgs += 1
                        try:
                            arr = json.loads(raw)
                        except Exception:
                            continue
                        if isinstance(arr, dict):      # combined-stream wrapper
                            arr = arr.get("data")
                        if not isinstance(arr, list):
                            continue
                        backoff = RECONNECT_BASE_SEC
                        if first:
                            first = False
                            log(f"radar first data: {len(arr)} coins")
                        for t in arr:
                            parsed = parse_mini_ticker(t)
                            if parsed is None:
                                continue
                            sym, qv, px, chg = parsed
                            self.radar.on_ticker(sym, qv, px, change_pct=chg)
                        newly = self.radar.maybe_evaluate()
                        gainers, losers = self.radar.top_bottom_by_change(10)
                        self.collector.update_candidates(newly, gainers, losers)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.ws_state = f"RECONNECTING:{e}"
                log(f"radar problem: {e} (retry in {backoff:.0f}s, next url)")
                self.radar_url_idx += 1
                await asyncio.sleep(backoff)
                backoff = min(RECONNECT_MAX_SEC, backoff * 2)

    async def heartbeat_loop(self):
        while not self._stop:
            await asyncio.sleep(HEARTBEAT_SEC)
            h = self.health()
            log(f"alive | radar msgs={self.radar_msgs} coins={len(self.radar.all_symbols())} "
                f"| candidates={h['candidate_count']} kline msgs={self.collector.msgs} "
                f"| state={h['ws_state']}")

    async def bot_loop(self):
        while not self._stop:
            try:
                self.bot.tick()
                self.tracker.tick_lead()
                await asyncio.to_thread(self.bridge.poll)
                await asyncio.to_thread(self.bridge.match_results)
            except Exception as e:
                print(f"[ping_worker] bot/tracker error: {e}")
            await asyncio.sleep(5.0)

    async def snapshot_loop(self):
        while not self._stop:
            try:
                self.write_snapshot()
            except Exception as e:
                print(f"[ping_worker] snapshot error: {e}")
            await asyncio.sleep(SNAPSHOT_SEC)

    async def run(self):
        print(f"[ping_worker] start build={BUILD_TAG} state={state_path()}")
        try:
            self.write_snapshot()
        except Exception as e:
            print(f"[ping_worker] initial snapshot: {e}")
        radar_t = asyncio.create_task(self.radar_loop())
        snap_t = asyncio.create_task(self.snapshot_loop())
        coll_t = asyncio.create_task(self.collector.run(on_health=None))
        bot_t = asyncio.create_task(self.bot_loop())
        hb_t = asyncio.create_task(self.heartbeat_loop())
        try:
            await asyncio.gather(radar_t, snap_t, coll_t, bot_t, hb_t)
        except asyncio.CancelledError:
            pass
        finally:
            self._stop = True
            self.collector.stop()
            for t in (radar_t, snap_t, coll_t, bot_t, hb_t):
                t.cancel()
            print("[ping_worker] stopped")


def main():
    # Same DNS fallback the main backend uses (some ISPs block Binance DNS).
    try:
        from recovered_bot.dns_fallback import ensure_dns_fallback
        ensure_dns_fallback()
    except Exception as e:
        print(f"[ping_worker] dns fallback not active: {e}")
    w = Worker()
    try:
        asyncio.run(w.run())
    except KeyboardInterrupt:
        print("[ping_worker] keyboard interrupt")
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
