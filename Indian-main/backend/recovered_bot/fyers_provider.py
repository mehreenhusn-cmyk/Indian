"""fyers_provider.py - Fyers as a data source for India PAPER mode (nothing here places an order).

Index candles : Fyers history API -> the bot has its 210-candle warm-up from day one.
Spot / premium: Fyers quotes API (polled; cached 1 s).
Contracts     : Fyers NSE_FO symbol master -> REAL lot sizes, expiries, strikes.
Option chart  : history of the option symbol; if Fyers has no intraday history for it, the
                chart is built from the premiums the app polls (grows while the app runs).
"""
import csv
import io
import math
import re
import time
from datetime import date, datetime, timedelta, timezone

try:
    from .india_broker import LiveProvider, BrokerError, register
    from .india_data import IST
    from . import india_options as opt
    from .fyers_client import FyersClient
except ImportError:
    from india_broker import LiveProvider, BrokerError, register
    from india_data import IST
    import india_options as opt
    from fyers_client import FyersClient

INDEX_SYM = {"NIFTY": "NSE:NIFTY50-INDEX", "BANKNIFTY": "NSE:NIFTYBANK-INDEX", "FINNIFTY": "NSE:FINNIFTY-INDEX"}
WARMUP_CANDLES = 210
_DET = re.compile(r"^([A-Z&\-]+)\s+(\d{1,2})\s+([A-Za-z]{3})\s+(\d{2})\s+([\d.]+)\s+(CE|PE)$")
_MON = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def parse_master(text, wanted=tuple(INDEX_SYM), today=None, n_expiries=4):
    """Symbol master CSV text -> {underlying: [contract dicts]} (nearest n_expiries only)."""
    today = today or datetime.now(IST).date()
    out = {u: [] for u in wanted}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 10:
            continue
        m = _DET.match(row[1].strip().upper())
        tick = next((x for x in row if x.startswith("NSE:") and x.endswith(("CE", "PE"))), None)
        if not m or not tick or m.group(1) not in out:
            continue
        try:
            exp = date(2000 + int(m.group(4)), _MON[m.group(3)], int(m.group(2)))
            lot = int(float(row[3]))
            strike = float(m.group(5))
        except (ValueError, KeyError):
            continue
        if exp < today or lot <= 0:
            continue
        strike = int(strike) if strike == int(strike) else strike
        out[m.group(1)].append(dict(underlying=m.group(1), expiry=exp, strike=strike, type=m.group(6),
                                    lot=lot, key=tick, symbol=tick))
    for u, cs in out.items():
        keep = sorted({c["expiry"] for c in cs})[:n_expiries]
        out[u] = [c for c in cs if c["expiry"] in keep]
    return out


class FyersProvider(LiveProvider):
    name, label = "fyers", "Fyers"
    fields = ("app_id", "secret_id", "redirect_url", "auth_code", "pin")
    # saved on the server (file mode 600): the refresh token + PIN let the app renew the daily login by itself
    persist = ("app_id", "secret_id", "redirect_url", "access_token", "token_session", "refresh_token",
               "refresh_day", "pin")
    REFRESH_DAYS = 15
    data_ready = True
    pending_note = ""
    candle_ttl, quote_ttl = 2.0, 1.0

    def __init__(self, tf_min=5, client=None, data_dir=None):
        super().__init__(tf_min)
        self.client = client or FyersClient()
        self.data_dir = data_dir
        self.account, self._master, self._master_day = {}, {}, None
        self._ticks = {}                     # option symbol -> [(epoch, price)] polled by the app
        self.token_day = None
        self.creds = {}                      # live reference to the saved credentials (kept fresh on renewal)
        self.token_session = None
        self.refresh_day = None
        self.auto_note = ""
        self._last_check = 0.0
        self.client.renewer = self._renew

    # ---- connect --------------------------------------------------------
    @staticmethod
    def _session_of(dt):
        """Fyers daily tokens run until early next morning, so the trading-session date is (time - 6h)."""
        return (dt - timedelta(hours=6)).date()

    def _remember(self, creds):
        now = datetime.now(IST)
        self.token_session = self._session_of(now)
        self.token_day = now.date()
        creds["access_token"] = self.client.token
        creds["token_session"] = self.token_session.isoformat()
        if self.client.refresh_token:
            if creds.get("refresh_token") != self.client.refresh_token or not creds.get("refresh_day"):
                creds["refresh_day"] = now.date().isoformat()      # a new refresh token starts a new 15-day clock
            creds["refresh_token"] = self.client.refresh_token
        self.refresh_day = self._d(creds.get("refresh_day"))
        self.creds = creds

    @staticmethod
    def _d(v):
        try:
            return date.fromisoformat(str(v)[:10])
        except (TypeError, ValueError):
            return None

    def _renew(self):
        """Used automatically when the daily token ran out. True = renewed."""
        try:
            self.client.refresh(self.creds)
        except BrokerError as e:
            self.auto_note = f"Auto-renew failed: {e}"[:200]
            return False
        creds = self.creds
        creds["access_token"] = self.client.token
        creds["refresh_token"] = self.client.refresh_token or creds.get("refresh_token", "")
        self._remember(creds)
        self.auto_note = "Login renewed automatically at " + datetime.now(IST).strftime("%H:%M")
        self._persist_now()
        return True

    def _persist_now(self):
        cb = getattr(self, "on_creds_changed", None)       # the runtime saves the renewed token on disk
        if cb:
            try:
                cb(self.creds)
            except Exception:
                pass

    def ensure_session(self, force=False):
        """Called regularly by the runtime: renew the token when the trading session has rolled over."""
        now = time.time()
        if not force and now - self._last_check < 30:
            return
        self._last_check = now
        if not self.creds:
            return
        if force or self.token_session != self._session_of(datetime.now(IST)) or not self.client.token:
            self._renew()

    def auth_info(self):
        """For the app: when must the browser login be done again?"""
        left = None
        if self.refresh_day:
            left = (self.refresh_day + timedelta(days=self.REFRESH_DAYS) - datetime.now(IST).date()).days
        auto = bool(self.creds.get("refresh_token") and self.creds.get("pin"))
        return {"auto_renew": auto, "refresh_days_left": left,
                "needs_login_soon": (not auto) or (left is not None and left <= 2),
                "note": self.auto_note,
                "hint": ("" if auto else "Save your Fyers PIN once (PIN field) to stop the daily login")
                        if left is None or left > 2 else f"Browser login needed again in {max(left, 0)} day(s)"}

    def connect(self, creds):
        self.creds = creds
        today_session = self._session_of(datetime.now(IST))
        code = str(creds.get("auth_code", "")).strip()
        if code:                                         # browser login (first time / refresh token expired)
            self.client.login(creds)
            creds.pop("refresh_day", None)
        else:
            ok = False
            if creds.get("access_token") and creds.get("token_session") == today_session.isoformat():
                try:
                    self.client.login(creds)             # today's saved token: reuse it
                    self.client.profile()
                    ok = True
                except BrokerError:
                    ok = False
            if not ok:
                self.client.refresh(creds)               # no browser needed
                self.auto_note = "Login renewed automatically"
        self._remember(creds)
        self.refresh_account()
        self._load_master()
        self._fetch_spot("NIFTY")            # fail early (wrong token / no data permission)

    def disconnect(self):
        self.client.logout()

    def refresh_account(self):
        acc = {}
        try:
            acc.update(self.client.profile())
        except BrokerError as e:
            acc["profile_error"] = str(e)[:120]
        try:
            acc.update(self.client.funds())
        except BrokerError as e:
            acc["balance_error"] = str(e)[:120]
        self.account = acc
        return acc

    def account_info(self):
        return dict(self.account)

    def _load_master(self):
        today = datetime.now(IST).date()
        if self._master_day == today and self._master:
            return
        try:
            self._master = parse_master(self.client.symbol_master("NSE_FO"), today=today)
            self._master_day = today
        except BrokerError:
            if not self._master:
                raise

    # ---- hooks ----------------------------------------------------------
    def _to_candles(self, rows):
        return [dict(t=datetime.fromtimestamp(int(r[0]), tz=timezone.utc).astimezone(IST),
                     o=float(r[1]), h=float(r[2]), l=float(r[3]), c=float(r[4]),
                     v=float(r[5]) if len(r) > 5 else 0.0) for r in rows]

    def _fetch_candles(self, u, tf, limit):
        """Older days are downloaded once and kept 10 min; only TODAY is asked again each time
        (keeps Fyers calls and data small while the chart refreshes every few seconds)."""
        today = datetime.now(IST).date()
        need_days = int(math.ceil(limit * tf / 375.0 * 1.4)) + 3

        def old():
            end, rows, left = today - timedelta(days=1), [], need_days
            while left > 0:
                span = min(left, 90)
                rows = self.client.history(INDEX_SYM[u], tf, end - timedelta(days=span - 1), end) + rows
                end -= timedelta(days=span)
                left -= span
            return rows
        base = self._cached(("hist", u, tf, need_days), 600, old)
        fresh = self.client.history(INDEX_SYM[u], tf, today, today)
        merged = {int(r[0]): r for r in list(base) + list(fresh)}
        return self._to_candles([merged[k] for k in sorted(merged)])[-limit:]

    def _fetch_spot(self, u):
        q = self.client.quotes([INDEX_SYM[u]]).get(INDEX_SYM[u])
        if not q:
            raise BrokerError(f"No {u} price from Fyers")
        return q["lp"]

    def _fetch_contracts(self, u):
        self._load_master()
        cs = self._master.get(u) or []
        if not cs:
            raise BrokerError(f"No {u} options in the Fyers symbol master")
        spot, step = self._fetch_spot(u), opt.UNDERLYINGS[u]["step"]
        atm = round(spot / step) * step
        return [c for c in cs if abs(c["strike"] - atm) <= 15 * step]

    def _fetch_ltp(self, c):
        q = self.client.quotes([c["symbol"]]).get(c["symbol"])
        if not q:
            return None
        self._ticks.setdefault(c["symbol"], []).append((time.time(), q["lp"]))
        del self._ticks[c["symbol"]][:-3000]
        return q["lp"]

    def get_prev_close(self, u):
        def f():
            q = self.client.quotes([INDEX_SYM[u]]).get(INDEX_SYM[u]) or {}
            return float(q["prev_close"]) if q.get("prev_close") else None
        try:
            return self._cached(("pc", u), 60, f)
        except Exception:
            return None

    # ---- option chart ---------------------------------------------------
    def get_option_candles(self, c, tf, limit):
        """-> (list of candle dicts, source 'REAL' | 'LIVE-BUILT'). Raises BrokerError if nothing yet."""
        today = datetime.now(IST).date()
        rows = []
        try:
            rows = self._cached(("oc", c["symbol"], tf), 5.0,
                                lambda: self.client.history(c["symbol"], tf, today - timedelta(days=6), today))
        except BrokerError:
            rows = []
        out = self._to_candles(rows)
        if len(out) >= 3:
            return out[-limit:], "REAL"
        # fallback: candles built from the premiums this app has polled
        buckets = {}
        for ts, px in self._ticks.get(c["symbol"], []):
            k = int(ts // (tf * 60)) * tf * 60
            b = buckets.get(k)
            if b is None:
                buckets[k] = [px, px, px, px]
            else:
                b[1], b[2], b[3] = max(b[1], px), min(b[2], px), px
        built = [dict(t=datetime.fromtimestamp(k, tz=timezone.utc).astimezone(IST), o=b[0], h=b[1], l=b[2], c=b[3], v=0.0)
                 for k, b in sorted(buckets.items())]
        if not built:
            raise BrokerError("Fyers has no candle history for this option yet - keep the chart open, it will build from live prices")
        return built[-limit:], "LIVE-BUILT"

    # ---- status for the app ---------------------------------------------
    def get_status(self):
        return {"feed": "connected", "feed_error": self.last_error, "ticks": len(self.client.log),
                "premium_source": "FYERS QUOTES", "contracts": f"Fyers symbol master: "
                f"{sum(len(v) for v in self._master.values())} options",
                "candles": {u: "history" for u in INDEX_SYM}, "warmup_need": 0,
                "token_day": self.token_day.isoformat() if self.token_day else None, "auth": self.auth_info(),
                "history_note": "Fyers history: bot warm-up is ready from day one"}


register("fyers", FyersProvider)
