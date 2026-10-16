"""india_data.py - data-provider interface + a replay/demo provider.

Any broker (Upstox, Dhan, Angel, Zerodha...) later = one new class implementing
DataProvider. The paper engine only talks to this interface.
"""
import random
from abc import ABC, abstractmethod
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

try:
    from . import india_options as opt, india_pricing as pricing, india_calendar as cal
except ImportError:  # flat-import fallback (tests / scripts)
    import india_options as opt, india_pricing as pricing, india_calendar as cal

IST = ZoneInfo("Asia/Kolkata")
# DEMO ONLY - real lot sizes must come from the broker contract list.
DEMO_LOT = {"NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 65}


class DataProvider(ABC):
    @abstractmethod
    def now(self): ...                       # tz-aware IST datetime
    @abstractmethod
    def get_spot(self, underlying): ...      # last index price
    @abstractmethod
    def get_candles(self, underlying, tf_min, limit): ...   # CLOSED candles only
    @abstractmethod
    def get_contracts(self, underlying): ... # dicts: underlying,expiry,strike,type,lot,key
    @abstractmethod
    def get_option_ltp(self, contract, spot=None): ...      # premium or None

    def get_last_candle(self, underlying):   # optional (intrabar SL/TP checks)
        return None

    def get_forming_candle(self, underlying, tf_min):   # candle still being built, any timeframe (chart)
        return None

    def set_tf(self, tf_min):                # timeframe the bot trades on
        self.tf = int(tf_min)

    # ---- optional extras for the terminal UI (None = not available) ----
    def get_prev_close(self, underlying):    # previous session close of the index
        return None

    def get_option_ref(self, contract):      # reference premium for the Chg column
        return None

    def get_oi(self, contract):              # open interest (broker feed only)
        return None


def weekly_tuesdays(today, n=4):
    """Next n weekly (Tuesday) expiries; one that falls on a holiday moves to the previous trading day."""
    d, out = today, []
    while len(out) < n:
        if d.weekday() == 1:
            e = cal.shift_expiry(d)
            if e >= today:
                out.append(e)
        d += timedelta(days=1)
    return out


def _bucket(bars, tf_bars):
    """Merge `tf_bars` consecutive base bars into one candle (same dict if nothing to merge)."""
    if tf_bars == 1:
        return bars[0]
    return dict(t=bars[0]["t"], o=bars[0]["o"], h=max(b["h"] for b in bars),
                l=min(b["l"] for b in bars), c=bars[-1]["c"], v=sum(b.get("v", 0) for b in bars))


class ReplayProvider(DataProvider):
    """Steps through pre-loaded candles. Premium = Black-Scholes @ fixed IV.

    `candles` are BASE bars (default: same size as tf_min). With base_tf=1 the demo can be
    traded and charted on any of 1/3/5/15 min: bars are merged on the fly and the clock
    moves tf_min/base_tf bars per step. Day length must be a multiple of tf (375 min is)."""
    supports_reprice = True   # get_option_ltp(c, spot=...) works for any spot

    def __init__(self, candles, tf_min=5, iv=0.15, expiry_fn=None, start=0, base_tf=None):
        self.c, self.tf, self.iv = candles, int(tf_min), iv
        self.base = int(base_tf or tf_min)
        self.expiry_fn = expiry_fn or weekly_tuesdays
        self.n = min(len(v) for v in candles.values())
        self.i = max(0, min(start, self.n - 1))   # index of the current base bar (history before it is pre-loaded)

    # ---- clock ----
    @property
    def _k(self):                       # base bars per bot candle
        return max(1, self.tf // self.base)

    def set_tf(self, tf_min):
        """Change the bot timeframe; the clock jumps forward to the next candle boundary."""
        self.tf = int(tf_min)
        k = self._k
        if (self.i + 1) % k:
            self.i = min(self.n - 1, ((self.i + 1) // k + 1) * k - 1)

    def ensure_history(self, n_candles):
        """Demo only: make sure at least n_candles closed candles of the bot timeframe exist."""
        need = n_candles * self.tf - 1
        if self.i < need:
            self.i = min(self.n - 1, need)

    def step(self):
        k = self._k
        if self.i + k >= self.n:
            return False
        self.i += k
        return True

    def now(self):
        u = next(iter(self.c))
        return self.c[u][self.i]["t"] + timedelta(minutes=self.base)

    def get_spot(self, u):
        return self.c[u][self.i]["c"]

    # ---- candles ----
    def _agg(self, u, tf, lo, hi):
        """One candle of `tf` minutes from base bars [lo, hi)."""
        return _bucket(self.c[u][lo:hi], 1 if tf == self.base else hi - lo)

    def get_last_candle(self, u):
        return self.get_forming_candle(u, self.tf)

    def get_forming_candle(self, u, tf_min):
        """Candle (any timeframe) that contains the current base bar - complete once the clock sits on its end."""
        kk = max(1, int(tf_min) // self.base)
        lo = (self.i // kk) * kk
        return self._agg(u, int(tf_min), lo, self.i + 1)

    def get_candles(self, u, tf_min, limit):
        """CLOSED candles of tf_min minutes, oldest first."""
        kk = max(1, int(tf_min) // self.base)
        end = ((self.i + 1) // kk) * kk              # base index after the last closed candle
        first = max(0, end - limit * kk)
        first -= first % kk
        return [self._agg(u, int(tf_min), j, j + kk) for j in range(first, end, kk)]

    def get_prev_close(self, u):
        cs, j = self.c[u], self.i
        d = cs[j]["t"].date()
        while j >= 0 and cs[j]["t"].date() == d:
            j -= 1
        return cs[j]["c"] if j >= 0 else cs[0]["o"]

    def get_option_ref(self, c):             # model premium at yesterday's close spot
        return self.get_option_ltp(c, spot=self.get_prev_close(c["underlying"]))

    def get_contracts(self, u):
        step = opt.UNDERLYINGS[u]["step"]
        atm = round(self.get_spot(u) / step) * step
        out = []
        for e in self.expiry_fn(self.now().date()):
            for k in range(-15, 16):
                for ty in ("CE", "PE"):
                    s = atm + k * step
                    out.append(dict(underlying=u, expiry=e, strike=s, type=ty,
                                    lot=DEMO_LOT[u], key=f"{u}-{e}-{s}{ty}"))
        return out

    def get_option_ltp(self, c, spot=None):
        spot = spot if spot is not None else self.get_spot(c["underlying"])
        exp = datetime.combine(c["expiry"], time(15, 30), IST)
        t = max((exp - self.now()).total_seconds(), 0) / (365 * 86400)
        return pricing.bs_price(spot, c["strike"], t, self.iv, c["type"])


def demo_start(days, today=None):
    """First day of a demo history of `days` trading days that ENDS on the latest trading day
    (so demo dates are never in the future and match the real calendar)."""
    today = today or datetime.now(IST).date()
    return cal.trading_days_back(today, days)[0]


def synthetic_candles(start_price, days=10, tf_min=5, seed=1, vol=0.0007,
                      start=date(2026, 10, 12), holidays=False):
    """Random-walk candles for 9:15-15:30 IST on trading days (demo/test data).
    vol is per 5 minutes and scales with the bar size. holidays=True also skips NSE holidays."""
    rnd, p, out, d = random.Random(seed), float(start_price), [], start
    per_day = (6 * 60 + 15) // tf_min
    vol = vol * (tf_min / 5.0) ** 0.5
    ok = cal.is_trading_day if holidays else (lambda x: x.weekday() < 5)
    while days > 0:
        if ok(d):
            t = datetime.combine(d, time(9, 15), IST)
            for _ in range(per_day):
                o = p
                cl = o * (1 + rnd.gauss(0, vol))
                hi = max(o, cl) * (1 + abs(rnd.gauss(0, vol / 2)))
                lo = min(o, cl) * (1 - abs(rnd.gauss(0, vol / 2)))
                out.append(dict(t=t, o=o, h=hi, l=lo, c=cl, v=0))
                p, t = cl, t + timedelta(minutes=tf_min)
            days -= 1
        d += timedelta(days=1)
    return out


def load_csv(path, tf_min=5):
    """CSV columns: datetime(ISO, IST),open,high,low,close[,volume]"""
    import csv
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            t = datetime.fromisoformat(r["datetime"])
            t = t if t.tzinfo else t.replace(tzinfo=IST)
            out.append(dict(t=t, o=float(r["open"]), h=float(r["high"]),
                            l=float(r["low"]), c=float(r["close"]),
                            v=float(r.get("volume") or 0)))
    return out
