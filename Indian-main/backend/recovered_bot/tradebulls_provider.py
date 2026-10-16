"""tradebulls_provider.py - Tradebulls for India PAPER mode.

Login/balance : REST (tradebulls_client.py, from the official doc).
Prices        : Price-Feed socket (tradebulls_feed.py): index spot -> candles built from ticks.
Option premium: REAL (feed) when a contract file with exchange tokens is present at
                <data_dir>/india_contracts.csv, otherwise MODEL (Black-Scholes on the live spot).
                The app shows which one is active. Nothing here ever places an order.
Candles       : the REST doc has no history API, so candles are built from ticks from the moment
                you connect and are saved on disk; the strategy needs ~210 candles, so it warms up
                over a few sessions. get_status() shows the count.
"""
import os
import time
from datetime import datetime, time as dtime

try:
    from .india_broker import LiveProvider, BrokerError, register
    from .india_data import IST, DEMO_LOT, weekly_tuesdays
    from . import india_options as opt, india_pricing as pricing
    from .tradebulls_client import TradebullsClient
    from .tradebulls_feed import PriceFeed, TickCandles, ContractBook, load_spec
except ImportError:
    from india_broker import LiveProvider, BrokerError, register
    from india_data import IST, DEMO_LOT, weekly_tuesdays
    import india_options as opt, india_pricing as pricing
    from tradebulls_client import TradebullsClient
    from tradebulls_feed import PriceFeed, TickCandles, ContractBook, load_spec

WARMUP_CANDLES = 210
MODEL_IV = 0.15


class TradebullsProvider(LiveProvider):
    name, label = "tradebulls", "Tradebulls"
    fields = ("base_url", "user_id", "login_type", "password", "second_auth", "api_key")
    persist = ("base_url", "user_id", "login_type", "api_key")
    data_ready = True
    pending_note = ""
    candle_ttl, quote_ttl = 1.0, 0.5

    def __init__(self, tf_min=5, client=None, data_dir=None, feed_factory=None):
        super().__init__(tf_min)
        self.client = client or TradebullsClient()
        self.data_dir = data_dir
        self.feed_factory = feed_factory or PriceFeed
        self.account, self.feed, self.div = {}, None, None
        self._init_storage()

    def _init_storage(self):          # runs again at connect(), once the runtime has set data_dir
        d = self.data_dir
        self.spec = load_spec(d)
        self.candles = TickCandles(os.path.join(d, "india_tick_candles.json") if d else None)
        self.book, self.contract_note = ContractBook(self.spec["fo_segment"]), ""

    # ---- connect / disconnect ------------------------------------------
    def connect(self, creds):
        self._init_storage()
        self.client.login(creds)
        try:
            self.account = {"name": self.client.user_name, "login_time": self.client.login_time,
                            **self.client.balance()}
        except BrokerError as e:                 # login worked; balance is a bonus
            self.account = {"name": self.client.user_name, "balance_error": str(e)[:150]}
        self._load_contract_file()
        url, tok = self.client.broadcast_url, self.client.broadcast_token
        if not url or not tok:
            raise BrokerError("Login worked but Tradebulls sent no price-feed address/token "
                              "(broadcast_access_token / broadCastSocket missing in the login reply)")
        self.feed = self.feed_factory(url, str(creds["user_id"]).strip().upper(), tok,
                                      spec=self.spec, on_tick=self._on_tick)
        for tkn in self.spec["index_tokens"].values():
            self.feed.subscribe(tkn)
        self.feed.start()
        for _ in range(60):                      # wait up to ~6 s for the first index price
            if self.feed.ltp or self.feed.status == "reconnecting":
                break
            time.sleep(0.1)

    def disconnect(self):
        if self.feed:
            self.feed.stop()
        self.candles.save()
        self.client.logout()

    def account_info(self):
        return dict(self.account)

    def _load_contract_file(self):
        p = os.path.join(self.data_dir or ".", "india_contracts.csv")
        if not os.path.exists(p):
            self.contract_note = "No contract file - option premiums use the MODEL"
            return
        try:
            n, bad = self.book.load_csv(p)
            self.contract_note = f"Contract file {self.book.source}: {n} options" + (f" ({bad} rows skipped)" if bad else "")
        except BrokerError as e:
            self.contract_note = f"Contract file ignored: {e}"

    # ---- price handling -------------------------------------------------
    def _on_tick(self, key, raw, t):
        for u, tkn in self.spec["index_tokens"].items():
            if key == tkn:
                v = self._scale(u, raw)
                if v is not None:
                    self.candles.add(u, v, t)

    def _scale(self, u, raw):
        """Feed prices may be in paise. Decide once, from the index (its range is known)."""
        lo, hi = self.spec["sane"][u]
        if self.div is None:
            d = float(self.spec.get("price_div") or 0)
            if d:
                self.div = d
            elif lo <= raw / 100 <= hi:
                self.div = 100.0
            elif lo <= raw <= hi:
                self.div = 1.0
            else:
                return None                      # not a plausible index value (wrong token?)
        v = raw / self.div
        return v if lo <= v <= hi else None

    def _raw_ltp(self, token):
        if self.feed is None:
            return None
        if token not in self.feed.subs:
            self.feed.subscribe(token)
        v = self.feed.ltp.get(token)
        return None if v is None or self.div is None else v / self.div

    # ---- LiveProvider hooks ---------------------------------------------
    def _fetch_candles(self, u, tf, limit):
        return self.candles.candles(u, tf, limit)

    def _fetch_spot(self, u):
        v = self._raw_ltp(self.spec["index_tokens"][u])
        if v is not None and self._scale(u, v * self.div) is not None:
            return v
        cs = self.candles.candles(u, self.tf, 1)
        if cs:
            return cs[-1]["c"]
        f = self.feed
        raise BrokerError(f"No {u} price yet (feed {f.status if f else 'off'}"
                          f"{': ' + f.error if f and f.error else ''})")

    def _fetch_contracts(self, u):
        real = self.book.contracts(u)
        if real:
            return real
        spot, step = self._fetch_spot(u), opt.UNDERLYINGS[u]["step"]
        atm = round(spot / step) * step
        today = datetime.now(IST).date()
        return [dict(underlying=u, expiry=e, strike=atm + k * step, type=ty, lot=DEMO_LOT[u],
                     key=f"{u}-{e}-{atm + k * step}{ty}")
                for e in weekly_tuesdays(today) for k in range(-15, 16) for ty in ("CE", "PE")]

    def _fetch_ltp(self, c):
        if c.get("feed_token"):
            v = self._raw_ltp(c["feed_token"])
            if v:
                return v
        spot = self._fetch_spot(c["underlying"])
        exp = datetime.combine(c["expiry"], dtime(15, 30), IST)
        t = max((exp - datetime.now(IST)).total_seconds(), 0) / (365 * 86400)
        return pricing.bs_price(spot, c["strike"], t, MODEL_IV, c["type"])

    def get_prev_close(self, u):
        today = datetime.now(IST).date()
        prev = [c for c in self.candles.candles(u, self.tf) if c["t"].date() < today]
        return prev[-1]["c"] if prev else None

    # ---- status for the app / probe ---------------------------------------
    def get_status(self):
        f = self.feed
        n = {u: len(self.candles.candles(u, self.tf)) for u in self.spec["index_tokens"]}
        age = round(time.time() - f.last_tick_at, 1) if f and f.last_tick_at else None
        return {"feed": f.status if f else "off", "feed_error": f.error if f else "", "ticks": f.ticks if f else 0,
                "last_tick_age_s": age, "price_scale": self.div, "candles": n, "warmup_need": WARMUP_CANDLES,
                "premium_source": "FEED" if self.book.rows else "MODEL", "contracts": self.contract_note,
                "raw_sample": list(f.raw)[-5:] if f else []}


register("tradebulls", TradebullsProvider)
