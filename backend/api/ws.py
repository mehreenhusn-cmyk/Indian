"""api/ws.py - the WebSocket (/ws) and the shared status broadcaster, moved out of api_server.py (NEXT-6j).

ConnectionManager + one shared status loop (status_broadcaster) + the /ws route. Same code, same send timeouts, same 0.25 s cadence,
same snapshot-on-connect. _display_status stays in api_server.py and is passed in (not copied).
api_server.py keeps the names manager, _dumps, _snapshot_msg, _status_broadcaster as thin links, so start-up and everything else is unchanged.
"""
import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from recovered_bot import settings_store, status, telemetry


MAX_SOCKETS = 3
SEND_TIMEOUT_SEC = 10.0  # a client that can't take one frame in 10s (40 ticks) is dropped, not waited on (was 4s: a short phone hiccup cut the socket)


class ConnectionManager:
    """Each connection gets its OWN asyncio.Lock, held around every send to
    that socket - both the shared broadcaster below AND that connection's
    own reader() (for ping/pong, resync) write through send_to(), so two
    tasks can never write to the same WebSocket at the same time (a raw
    concurrent send_text() from two tasks is not safe)."""

    def __init__(self):
        self.active_connections: dict[WebSocket, asyncio.Lock] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[websocket] = asyncio.Lock()
        # The app only ever needs ONE live socket. After a stall it can leave several half-dead ones behind;
        # keep the newest MAX_SOCKETS and close the older ones so they stop eating every 250 ms tick.
        while len(self.active_connections) > MAX_SOCKETS:
            old_ws = next(iter(self.active_connections))
            self.active_connections.pop(old_ws, None)
            try:
                await old_ws.close()
            except Exception:
                pass

    def disconnect(self, websocket: WebSocket):
        self.active_connections.pop(websocket, None)

    async def send_to(self, websocket: WebSocket, message: str):
        conn_lock = self.active_connections.get(websocket)
        if conn_lock is None:
            return
        async with conn_lock:
            await websocket.send_text(message)

    async def _send_guarded(self, websocket: WebSocket, message: str) -> bool:
        try:
            await asyncio.wait_for(self.send_to(websocket, message), timeout=SEND_TIMEOUT_SEC)
            return True
        except Exception:
            # Dead or too-slow client: drop it so it can never hold up the
            # price/PnL stream for everyone else. The app auto-reconnects and
            # immediately gets a FULL_STATE_SNAPSHOT, so nothing is lost.
            self.disconnect(websocket)
            try:
                await websocket.close()
            except Exception:
                pass
            return False

    async def broadcast(self, message: str):
        """Sends to all clients CONCURRENTLY (was one-by-one with no timeout,
        so one stalled socket delayed every other client's tick).
        Returns (clients_targeted, clients_dropped)."""
        conns = list(self.active_connections.keys())
        if not conns:
            return 0, 0
        if len(conns) == 1:
            results = [await self._send_guarded(conns[0], message)]
        else:
            results = await asyncio.gather(*(self._send_guarded(c, message) for c in conns))
        return len(conns), results.count(False)


manager = ConnectionManager()

# PRODUCTION HARDENING - CPU/bandwidth throttle for the 1s status broadcast.
# The old code ran a full writer() loop PER CONNECTED WEBSOCKET - so N
# connected devices/tabs meant N redundant _display_status() computations
# every second, and (whenever LIVE trading is on) N simultaneous blocking
# REST calls to the exchange every second, each one stalling the event
# loop for its round-trip. Now there is exactly ONE shared loop no matter
# how many clients are connected, the exchange call runs off the event
# loop thread (asyncio.to_thread), the work is skipped entirely when
# nobody is listening, and two payload fields that rarely change
# tick-to-tick (alerts, watchlist) are only re-sent when they actually
# changed - same trick the alerts_rev check already used, now extended to
# watchlist too. Update cadence itself is left at 1s on purpose (Part 4's
# live LTP/ticker feed must stay live-feeling) - the fix is doing that
# work once and non-blockingly, not doing it less often.
BROADCAST_INTERVAL_SEC = 0.25   # was 1.0 - matches the ~250ms kline/last-price feed so the app is not a second behind Binance
_last_broadcast_watchlist = None


async def status_broadcaster(_display_status):
    """The ONE shared status loop. _display_status is api_server's own function (passed in, not copied)."""
    global _last_broadcast_watchlist
    last_alerts_rev = None
    while True:
        # Live-trading mode makes a real exchange REST call every tick
        # (_display_status -> get_open_positions) - keep that at 1s so the
        # faster paper/price cadence never hammers the exchange rate limit.
        await asyncio.sleep(
            max(BROADCAST_INTERVAL_SEC, 1.0)
            if settings_store.get("live_trading_enabled", False)
            else BROADCAST_INTERVAL_SEC
        )
        if not manager.active_connections:
            continue  # nobody listening right now - skip all the work below
        _t0 = time.perf_counter()
        # Alerts (up to 250 detail dicts) rarely change - don't even COPY them
        # on ticks where the revision is unchanged (they used to be deep-copied
        # 4x/sec and then popped). Price / positions / PnL are untouched.
        _skip = ("alerts",) if status.alerts_rev() == last_alerts_rev else ()
        try:
            if settings_store.get("live_trading_enabled", False):
                # _display_status() hits exchange.get_open_positions() (a real
                # network call) in this branch - never run that directly on
                # the event loop that every websocket/HTTP request shares.
                data = await asyncio.to_thread(_display_status, _skip)
            else:
                data = _display_status(_skip)
        except Exception:
            continue
        if not _skip:
            last_alerts_rev = data.get("alerts_rev")
        wl = data.get("watchlist")
        if wl == _last_broadcast_watchlist:
            data.pop("watchlist", None)
        else:
            _last_broadcast_watchlist = wl
        _t1 = time.perf_counter()
        _msg = _dumps({"type": "update", "data": data})
        _dumps_ms = (time.perf_counter() - _t1) * 1000.0      # how long the JSON text takes to build (shows in the load report)
        _build_ms = (time.perf_counter() - _t0) * 1000.0
        _n, _dropped = await manager.broadcast(_msg)
        telemetry.record_broadcast((time.perf_counter() - _t0) * 1000.0, len(_msg), _n,
                                   build_ms=_build_ms, dropped=_dropped, dumps_ms=_dumps_ms)


def _dumps(obj):
    return json.dumps(obj, default=str)


def snapshot_msg(_display_status):
    """FULL_STATE_SNAPSHOT: the complete status dict (open positions with live
    PnL, alerts, movers, stats...). Sent on every (re)connect and on request,
    so the app replaces its state wholesale instead of trusting whatever it
    had before the connection dropped."""
    return _dumps({"type": "init", "kind": "FULL_STATE_SNAPSHOT", "data": _display_status()})


def make_router(_display_status):
    """The /ws route. It must be included LAST (it was the last route of api_server.py)."""
    r = APIRouter()

    def _snapshot_msg():
        return snapshot_msg(_display_status)

    @r.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)

        async def send(text):
            await manager.send_to(websocket, text)

        async def reader():
            # Client sends {"type":"ping"} every ~5s (latency + liveness) and may
            # send {"type":"resync"} to ask for a fresh full snapshot.
            while True:
                msg = await websocket.receive_text()
                try:
                    kind = json.loads(msg).get("type")
                except (json.JSONDecodeError, AttributeError):
                    continue
                if kind == "ping":
                    await send(_dumps({"type": "pong", "server_ts": time.time()}))
                elif kind == "resync":
                    await send(await asyncio.to_thread(_snapshot_msg))

        # Periodic "update" messages now come from the single shared
        # _status_broadcaster() task (started once at server startup) instead
        # of a per-connection writer() loop - see its docstring above for why.
        # This connection's own task just accepts the initial snapshot + reads
        # client pings/resyncs until it disconnects.
        try:
            await send(await asyncio.to_thread(_snapshot_msg))
            await reader()
        except Exception:
            pass
        finally:
            manager.disconnect(websocket)

    return r
