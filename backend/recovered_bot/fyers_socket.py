"""fyers_socket.py - live prices over the Fyers WebSocket (like the Binance side), REST only as fallback.

* TickFeed keeps the latest price of every subscribed symbol. Prices arrive by push, so they do
  NOT use the 50 requests/minute REST limit.
* If the socket is down, silent during market hours, or the daily token changed, the watchdog
  restarts it (with a growing pause). While it is down the provider simply uses REST.
* The Fyers library (pip install fyers-apiv3) is optional. Without it state = "unavailable" and
  everything keeps working on REST.
* The socket factory is injectable, so tests run offline with a fake socket.
"""
import logging
import threading
import time

log = logging.getLogger("fyers_socket")

MAX_SYMBOLS = 300
SILENT_LIMIT = 25.0          # seconds without any tick during market hours -> restart the socket
BACKOFF = (5, 15, 30, 60, 120)


class _SdkSocket:
    """Thin wrapper over fyers_apiv3 FyersDataSocket."""

    def __init__(self, ws):
        self.ws = ws

    def connect(self):
        self.ws.connect()

    def subscribe(self, symbols):
        self.ws.subscribe(symbols=list(symbols), data_type="SymbolUpdate")

    def close(self):
        try:
            self.ws.close_connection()
        except Exception:
            pass


def sdk_factory(access_token, on_open, on_message, on_error, on_close):
    from fyers_apiv3.FyersWebsocket import data_ws        # ImportError -> state "unavailable"
    ws = data_ws.FyersDataSocket(access_token=access_token, log_path="", litemode=False,
                                 write_to_file=False, reconnect=True, on_connect=on_open,
                                 on_close=on_close, on_error=on_error, on_message=on_message)
    return _SdkSocket(ws)


class TickFeed:
    def __init__(self, factory=None, on_tick=None):
        self.factory = factory or sdk_factory
        self.on_tick = on_tick
        self.lock = threading.RLock()
        self.ticks = {}                  # symbol -> (epoch, dict)
        self.wanted = []                 # symbols to keep subscribed (order kept)
        self._wanted_set = set()
        self.sock = None
        self.state = "off"               # off | connecting | connected | unavailable | error
        self.error = ""
        self.restarts = 0
        self.started_at = 0.0
        self.last_tick = 0.0
        self._next_restart = 0.0
        self._fails = 0                  # restarts since the last good tick (drives the pause)
        self._cred = None                # (app_id, token) the current socket was started with
        self._gen = 0                    # a new socket gets a new number; old sockets' callbacks are ignored

    # ---- start / stop -------------------------------------------------------
    def start(self, app_id, token):
        with self.lock:
            self._stop_locked()
            self._cred = (app_id, token)
            self._gen += 1
            gen = self._gen
            self.state, self.error = "connecting", ""
            self.started_at = time.time()
        threading.Thread(target=self._run, args=(gen, f"{app_id}:{token}"), daemon=True).start()

    def _run(self, gen, access_token):
        try:
            sock = self.factory(access_token, lambda: self._on_open(gen), lambda m: self._on_message(gen, m),
                                lambda m: self._on_error(gen, m), lambda m=None: self._on_close(gen, m))
        except ImportError:
            with self.lock:
                if gen == self._gen:
                    self.state = "unavailable"
                    self.error = "Fyers WebSocket library missing: pip install fyers-apiv3 (using REST meanwhile)"
            return
        except Exception as e:
            self._fail(gen, f"{type(e).__name__}: {e}")
            return
        with self.lock:
            if gen != self._gen:
                sock.close()
                return
            self.sock = sock
        try:
            sock.connect()
        except Exception as e:
            self._fail(gen, f"{type(e).__name__}: {e}")

    def _fail(self, gen, msg):
        with self.lock:
            if gen == self._gen:
                self.state, self.error = "error", str(msg)[:160]

    def stop(self):
        with self.lock:
            self._stop_locked()
            self.state, self._cred = "off", None

    def _stop_locked(self):
        self._gen += 1                   # ignore everything the old socket still sends
        s, self.sock = self.sock, None
        if s:
            threading.Thread(target=s.close, daemon=True).start()

    # ---- callbacks (run on the library's thread) ------------------------------
    def _on_open(self, gen):
        with self.lock:
            if gen != self._gen:
                return
            self.state = "connected"
            syms, sock = list(self.wanted), self.sock
        if sock and syms:
            for i in range(0, len(syms), 100):
                try:
                    sock.subscribe(syms[i:i + 100])
                except Exception as e:
                    self._fail(gen, f"subscribe: {e}")

    def _on_close(self, gen, msg=None):
        with self.lock:
            if gen == self._gen and self.state in ("connected", "connecting"):
                self.state = "error"
                self.error = "WebSocket closed"

    def _on_error(self, gen, msg):
        with self.lock:
            if gen == self._gen:
                self.error = str(msg)[:160]

    def _on_message(self, gen, msg):
        rows = msg if isinstance(msg, list) else [msg]
        now = time.time()
        for m in rows:
            if not isinstance(m, dict):
                continue
            sym, ltp = m.get("symbol"), m.get("ltp")
            if sym is None or ltp is None:
                if m.get("s") == "error" or (isinstance(m.get("code"), int) and m["code"] >= 400):
                    with self.lock:
                        if gen == self._gen:
                            self.error = str(m)[:160]
                continue
            try:
                ltp = float(ltp)
            except (TypeError, ValueError):
                continue
            q = {"lp": ltp, "prev_close": m.get("prev_close_price"), "ch": m.get("ch"), "chp": m.get("chp"),
                 "src": "ws"}
            with self.lock:
                if gen != self._gen:
                    return
                self.ticks[sym] = (now, q)
                self.last_tick = now
                self._fails = 0
                self.state, self.error = "connected", ""
            if self.on_tick:
                try:
                    self.on_tick(sym, ltp)
                except Exception:
                    log.exception("on_tick")

    # ---- use ------------------------------------------------------------------
    def subscribe(self, symbols):
        new = []
        with self.lock:
            for s in symbols:
                if s and s not in self._wanted_set and len(self.wanted) < MAX_SYMBOLS:
                    self._wanted_set.add(s)
                    self.wanted.append(s)
                    new.append(s)
            sock, ok = self.sock, self.state == "connected"
        if new and sock and ok:
            try:
                sock.subscribe(new)
            except Exception as e:
                self.error = f"subscribe: {e}"[:160]

    def get(self, symbol, max_age=6.0):
        """-> {lp, prev_close, ch, chp, src:'ws'} if a fresh pushed price exists, else None."""
        with self.lock:
            hit = self.ticks.get(symbol)
        if hit and time.time() - hit[0] <= max_age:
            return hit[1]
        return None

    def connected(self):
        return self.state == "connected"

    def healthy(self, max_age=10.0):
        return self.state == "connected" and self.last_tick > 0 and time.time() - self.last_tick <= max_age

    def check(self, market_open, token=None):
        """Watchdog - call every few seconds. Restarts a dead / silent socket or one with an old token."""
        with self.lock:
            cred, state, now = self._cred, self.state, time.time()
            if cred is None or state in ("off", "unavailable"):
                return
            if token and token != cred[1]:               # daily token renewed
                app_id = cred[0]
                restart = True
            else:
                silent = max(self.last_tick, self.started_at)
                restart = state == "error" or (market_open and now - silent > SILENT_LIMIT)
                app_id = cred[0]
            if not restart or now < self._next_restart:
                return
            pause = BACKOFF[min(self._fails, len(BACKOFF) - 1)]
            self._fails += 1
            self._next_restart = now + pause
            self.restarts += 1
            use = token or cred[1]
        log.warning("Fyers WebSocket restart #%s", self.restarts)
        self.start(app_id, use)

    def info(self):
        now = time.time()
        with self.lock:
            return {"state": self.state, "connected": self.state == "connected",
                    "age": round(now - self.last_tick, 1) if self.last_tick else None,
                    "symbols": len(self.wanted), "restarts": self.restarts, "error": self.error}
