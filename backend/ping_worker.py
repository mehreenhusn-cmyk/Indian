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
from recovered_bot.ping_radar import PingRadar
from recovered_bot.ping_collector import PingCollector
from recovered_bot.ping_engine import PingEngine
from recovered_bot.ping_bot import PingBot
from recovered_bot.ping_tracker import PingTracker
from recovered_bot.ping_signal_bridge import SignalBridge, POLL_SEC

# ---- constants (starting guesses) ----
BUILD_TAG = "2026-10-22-ping-p1"
SNAPSHOT_SEC = 2.0
RADAR_WS = "wss://fstream.binance.com/ws/!miniTicker@arr"
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
            try:
                self.ws_state = "CONNECTING"
                async with websockets.connect(
                    RADAR_WS, ping_interval=20, ping_timeout=20, max_size=2**23
                ) as ws:
                    self.ws_state = "LIVE"
                    backoff = RECONNECT_BASE_SEC
                    async for raw in ws:
                        if self._stop:
                            break
                        self.last_msg_ts = time.time()
                        try:
                            arr = json.loads(raw)
                        except Exception:
                            continue
                        if not isinstance(arr, list):
                            continue
                        for t in arr:
                            sym = (t.get("s") or "").upper()
                            if not sym.endswith("USDT"):
                                continue
                            self.radar.on_ticker(
                                sym, t.get("q", 0), t.get("c", 0), change_pct=t.get("P"),
                            )
                        newly = self.radar.maybe_evaluate()
                        gainers, losers = self.radar.top_bottom_by_change(10)
                        self.collector.update_candidates(newly, gainers, losers)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.ws_state = f"RECONNECTING:{e}"
                await asyncio.sleep(backoff)
                backoff = min(RECONNECT_MAX_SEC, backoff * 2)

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
        try:
            await asyncio.gather(radar_t, snap_t, coll_t, bot_t)
        except asyncio.CancelledError:
            pass
        finally:
            self._stop = True
            self.collector.stop()
            for t in (radar_t, snap_t, coll_t, bot_t):
                t.cancel()
            print("[ping_worker] stopped")


def main():
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
