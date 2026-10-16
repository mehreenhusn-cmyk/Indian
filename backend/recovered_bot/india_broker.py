"""india_broker.py - broker plumbing for India paper mode (no broker-specific code).

* CredStore   - saves the API key / secret on the server (file mode 600), never returns
                them in full (the app only sees a masked version).
* epoch_to_ist - safe timestamp parsing (Unix seconds / ms, or 1980-based seconds).
* LiveProvider - base class for a real broker feed. A broker only fills in the four
                _fetch_* methods; caching, closed-candle filtering and error
                handling live here.
* register / make_provider - broker registry (Tradebulls registers itself in Part 2).
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone

try:
    from .india_data import DataProvider, IST
except ImportError:  # flat-import fallback (tests / scripts)
    from india_data import DataProvider, IST

EPOCH_1980 = 315532800        # seconds between 1970-01-01 and 1980-01-01 (ODIN-style feeds)


def epoch_to_ist(ts, mode="auto", ref=None):
    """Convert a broker timestamp to an IST datetime.
    mode: "unix" | "1980" | "auto". "auto" picks whichever reading lands closest to
    `ref` (default: now) - this is what fixes the Unix-vs-1980 mix-up."""
    ts = float(ts)
    if ts > 1e11:                      # milliseconds
        ts /= 1000.0
    ref = ref or datetime.now(IST)

    def conv(off):
        return datetime.fromtimestamp(ts + off, tz=timezone.utc).astimezone(IST)
    if mode == "unix":
        return conv(0)
    if mode == "1980":
        return conv(EPOCH_1980)
    a, b = conv(0), conv(EPOCH_1980)
    return a if abs((a - ref).total_seconds()) <= abs((b - ref).total_seconds()) else b


def mask(v):
    v = str(v or "")
    return "" if not v else (v[:2] + "*" * 6 + v[-2:] if len(v) > 6 else "*" * len(v))


class CredStore:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "india_broker.json")
        self.lock = threading.Lock()

    def _load(self):
        try:
            with open(self.path) as f:
                return json.load(f)
        except Exception:
            return {}

    def get(self, broker):
        with self.lock:
            return dict(self._load().get(broker, {}))

    def save(self, broker, creds):
        with self.lock:
            d = self._load()
            d[broker] = {k: str(v) for k, v in creds.items() if v not in (None, "")}
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(d, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)

    def clear(self, broker):
        with self.lock:
            d = self._load()
            d.pop(broker, None)
            with open(self.path, "w") as f:
                json.dump(d, f)
            os.chmod(self.path, 0o600)

    def masked(self, broker):
        return {k: mask(v) for k, v in self.get(broker).items()}


class BrokerError(Exception):
    """Readable error text for the app (login failed, no data, ...)."""


class RateLimited(BrokerError):
    """The broker said 'too many requests' (or our own budget is used up).
    Callers keep showing the last good data instead of an error."""


class LiveProvider(DataProvider):
    """Real-broker provider. Subclass and implement connect + the four _fetch_* hooks."""
    is_live = True
    supports_reprice = False
    name = "broker"
    label = "Broker"
    fields = ()                 # credential fields the app must ask for, e.g. ("api_key",)
    candle_ttl = 3.0            # seconds to reuse a candle download
    quote_ttl = 1.0             # seconds to reuse a spot/premium quote

    def __init__(self, tf_min=5):
        self.tf = tf_min
        self._cache, self._lock = {}, threading.Lock()
        self.last_error = ""

    # ---- to implement -------------------------------------------------
    def connect(self, creds):               # login; raise BrokerError("readable text")
        raise NotImplementedError

    def _fetch_candles(self, u, tf_min, limit):   # list of dict(t=IST dt,o,h,l,c,v), oldest first
        raise NotImplementedError

    def _fetch_spot(self, u):               # float
        raise NotImplementedError

    def _fetch_contracts(self, u):          # dicts: underlying,expiry(date),strike,type,lot,key
        raise NotImplementedError

    def _fetch_ltp(self, contract):         # float premium or None
        raise NotImplementedError

    # ---- shared behaviour ---------------------------------------------
    def _cached(self, key, ttl, fn):
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        try:
            val = fn()
            self.last_error = ""
        except Exception as e:          # keep running on the last good value
            self.last_error = f"{type(e).__name__}: {e}"
            if hit:
                return hit[1]
            raise
        with self._lock:
            self._cache[key] = (now, val)
        return val

    def now(self):
        return datetime.now(IST)

    def get_candles(self, u, tf_min, limit):
        cs = self._cached(("c", u, tf_min, limit), self.candle_ttl,
                          lambda: self._fetch_candles(u, tf_min, limit + 1))
        now = self.now()
        # CLOSED candles only: drop a candle whose bar has not finished yet
        cs = [c for c in cs if c["t"] + timedelta(minutes=tf_min) <= now]
        return cs[-limit:]

    def get_last_candle(self, u):
        cs = self._cached(("c", u, self.tf, 2), self.candle_ttl,
                          lambda: self._fetch_candles(u, self.tf, 2))
        return cs[-1] if cs else None      # may be the forming candle (live O/H/L/C)

    def get_forming_candle(self, u, tf_min):
        cs = self._cached(("f", u, int(tf_min)), self.candle_ttl,
                          lambda: self._fetch_candles(u, int(tf_min), 2))
        return cs[-1] if cs else None

    def get_spot(self, u):
        return self._cached(("s", u), self.quote_ttl, lambda: float(self._fetch_spot(u)))

    def get_contracts(self, u):
        day = self.now().date()
        return self._cached(("k", u, day), 3600, lambda: self._fetch_contracts(u))

    def get_option_ltp(self, contract, spot=None):
        v = self._cached(("o", contract["key"]), self.quote_ttl,
                         lambda: self._fetch_ltp(contract))
        return float(v) if v else None


_REG = {}


def register(name, cls):
    _REG[name] = cls


def make_provider(name, tf_min=5):
    if name not in _REG:
        raise BrokerError(f"Broker '{name}' is not installed yet")
    return _REG[name](tf_min=tf_min)


def available():
    return {n: {"label": c.label, "fields": list(c.fields)} for n, c in _REG.items()}
