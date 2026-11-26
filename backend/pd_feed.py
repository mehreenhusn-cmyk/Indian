"""pd_feed.py - price + volume history of every Binance USDT-M futures coin for the Pump / Dump scanner (PD).
ONE REST call every poll_sec seconds: GET /fapi/v1/ticker/24hr (all coins, gzip). Each answer adds one sample (time, last price, 24h turnover)
per coin. The volume of a short window is the DIFFERENCE of the 24h turnover between two samples (approximate: the 24h window also drops old
minutes, so it can only under-count; the spike ratio is always against the coin's own last hour, so it stays fair).
No order, no key, no websocket. Memory: about 285 samples x 3 numbers per coin (about 15 MB for 500 coins)."""
import time

import pd_config as C

URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"


class Hist:
    __slots__ = ("t", "p", "q")

    def __init__(self):
        self.t = []   # sample time (epoch s)
        self.p = []   # last price
        self.q = []   # 24h quote volume (USDT)


class Feed:
    def __init__(self, fetch=None):
        self.hist = {}      # symbol -> Hist
        self.meta = {}      # symbol -> {"qv24", "chg24"}
        self.fetch = fetch or self._fetch
        self.last_ok = 0.0
        self.first_ok = 0.0
        self.polls = 0

    @staticmethod
    def _fetch():
        import requests
        r = requests.get(URL, timeout=12)
        r.raise_for_status()
        return r.json()

    def poll(self, now=None):
        """One call. Returns the number of coins tracked. Raises on a network error (the runner counts it and backs off)."""
        data = self.fetch()
        now = time.time() if now is None else now
        keep = C.get("hist_min") * 60
        minq = C.get("min_qv24")
        seen = 0
        for d in data:
            s = d.get("symbol", "")
            if not s.endswith("USDT") or "_" in s:
                continue                       # USDT perpetuals only (no dated futures)
            try:
                p = float(d["lastPrice"])
                q = float(d["quoteVolume"])
                chg = float(d.get("priceChangePercent", 0.0))
            except Exception:
                continue
            if p <= 0 or q < minq:
                continue
            h = self.hist.get(s)
            if h is None:
                h = self.hist[s] = Hist()
            h.t.append(now)
            h.p.append(p)
            h.q.append(q)
            if h.t[0] < now - keep:            # drop what is older than the window
                k = 0
                while k < len(h.t) and h.t[k] < now - keep:
                    k += 1
                del h.t[:k], h.p[:k], h.q[:k]
            self.meta[s] = {"qv24": q, "chg24": chg}
            seen += 1
        for s in [s for s, h in self.hist.items() if h.t and h.t[-1] < now - 600]:   # coin gone / too quiet now: forget it
            del self.hist[s]
            self.meta.pop(s, None)
        self.polls += 1
        self.last_ok = now
        if not self.first_ok:
            self.first_ok = now
        return seen

    def warm_left_min(self, now=None):
        now = time.time() if now is None else now
        if not self.first_ok:
            return C.get("warm_min")
        return max(0.0, C.get("warm_min") - (now - self.first_ok) / 60.0)

    def clear(self):
        self.hist.clear()
        self.meta.clear()
        self.first_ok = 0.0
