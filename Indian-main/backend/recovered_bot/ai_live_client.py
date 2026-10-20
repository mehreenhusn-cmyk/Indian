"""
ai_live_client.py - STAGE 2 (file 2 of 4): a small signed Binance USDT-M Futures client that uses ONLY the AI's key.

It never touches the bot's key or the bot's modules (binance_trader / protection_manager). Reasons for a separate client:
  - different account, different key;
  - Binance moved conditional orders (STOP_MARKET, ...) to the Algo Order API (POST /fapi/v1/algoOrder). The old
    /fapi/v1/order now answers -4120 for them, so stops here go to the algo endpoint first (classic only if the algo
    endpoint does not exist, HTTP 404).
Everything goes through one transport function, so tests run on a fake exchange and nothing real is ever called there.
Honest limit: field names of the algo endpoints were taken from Binance's docs, not tested against a live account.
Parsing is tolerant, but the FIRST real run must be with a tiny margin (see README).
"""
import hashlib
import hmac
import json
import threading
import time
from urllib.parse import urlencode

BASE = "https://fapi.binance.com"
RECV_WINDOW = 10000
TIMEOUT_S = 10
AMBIGUOUS = (-1006, -1007, -1008)       # Binance: "execution status unknown"
STOP_TYPES = ("STOP_MARKET", "STOP")


class ApiError(Exception):
    def __init__(self, code, msg, status=0):
        super().__init__("%s %s" % (code, msg))
        self.code, self.msg, self.status = code, str(msg), status


def _default_transport(method, url, headers, timeout):
    import requests
    r = requests.request(method, url, headers=headers, timeout=timeout)
    return r.status_code, r.text


def _f(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


class Client:
    def __init__(self, creds=None, transport=None, base=BASE):
        if creds is None:
            from . import ai_live_keys
            creds = ai_live_keys.get
        self.creds, self.transport, self.base = creds, transport or _default_transport, base
        self._info = {"t": 0.0, "d": None}
        self._lk = threading.Lock()

    # ------------------------------------------------------------ plumbing
    def _req(self, method, path, params=None, signed=True):
        params = dict(params or {})
        headers = {}
        if signed:
            key, secret = self.creds()
            if not key or not secret:
                raise ApiError(0, "No AI API key is set")
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = RECV_WINDOW
            qs = urlencode(sorted(params.items()))
            sig = hmac.new(secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
            url = "%s%s?%s&signature=%s" % (self.base, path, qs, sig)
            headers["X-MBX-APIKEY"] = key
        else:
            qs = urlencode(sorted(params.items()))
            url = "%s%s%s" % (self.base, path, ("?" + qs) if qs else "")
        try:
            status, text = self.transport(method, url, headers, TIMEOUT_S)
        except Exception as e:                      # network level: nothing reached Binance, or no answer came back
            raise ApiError(0, "network: %s" % type(e).__name__)
        try:
            data = json.loads(text)
        except Exception:
            data = text
        if status != 200:
            code, msg = 0, str(text)[:200]
            if isinstance(data, dict):
                code, msg = int(data.get("code") or 0), str(data.get("msg") or msg)[:200]
            raise ApiError(code, msg, status)
        return data

    # ------------------------------------------------------------ account
    def balance(self):
        """Free USDT on the AI account."""
        rows = self._req("GET", "/fapi/v2/balance")
        for r in rows if isinstance(rows, list) else []:
            if r.get("asset") == "USDT":
                return _f(r.get("availableBalance"))
        return 0.0

    def dual_side(self):
        d = self._req("GET", "/fapi/v1/positionSide/dual")
        return bool(d.get("dualSidePosition")) if isinstance(d, dict) else False

    def positions(self, symbol=None):
        """Open positions: [{symbol, amt (+long / -short), entry, mark}]. One-way mode assumed."""
        rows = self._req("GET", "/fapi/v2/positionRisk", {"symbol": symbol} if symbol else None)
        out = []
        for r in rows if isinstance(rows, list) else []:
            amt = _f(r.get("positionAmt"))
            if abs(amt) > 0:
                out.append({"symbol": r.get("symbol"), "amt": amt, "entry": _f(r.get("entryPrice")), "mark": _f(r.get("markPrice"))})
        return out

    def price(self, symbol):
        d = self._req("GET", "/fapi/v1/ticker/price", {"symbol": symbol}, signed=False)
        return _f(d.get("price")) if isinstance(d, dict) else 0.0

    def set_margin_type(self, symbol, kind="ISOLATED"):
        try:
            self._req("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": kind})
        except ApiError as e:
            if e.code != -4046:                      # -4046 = already that type
                raise

    def set_leverage(self, symbol, lev):
        return self._req("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(lev)})

    # ------------------------------------------------------------ symbol rules
    def _filters(self, symbol):
        with self._lk:
            if self._info["d"] is None or time.time() - self._info["t"] > 3600:
                self._info["d"] = self._req("GET", "/fapi/v1/exchangeInfo", signed=False)
                self._info["t"] = time.time()
            for s in (self._info["d"] or {}).get("symbols", []):
                if s.get("symbol") == symbol:
                    return s.get("filters", [])
        return []

    @staticmethod
    def _pick(filters, ftype, key):
        for f in filters:
            if f.get("filterType") == ftype:
                return _f(f.get(key)) or None
        return None

    def round_qty(self, symbol, qty):
        step = self._pick(self._filters(symbol), "MARKET_LOT_SIZE", "stepSize") or self._pick(self._filters(symbol), "LOT_SIZE", "stepSize")
        if not step:
            return qty
        return round(int(qty / step + 1e-9) * step, 10)

    def round_price(self, symbol, price):
        tick = self._pick(self._filters(symbol), "PRICE_FILTER", "tickSize")
        return round(round(price / tick) * tick, 10) if tick else price

    def min_notional(self, symbol):
        return self._pick(self._filters(symbol), "MIN_NOTIONAL", "notional") or 5.0

    # ------------------------------------------------------------ orders
    def market(self, symbol, side, qty, reduce_only=False, cid=None):
        p = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty}
        if reduce_only:
            p["reduceOnly"] = "true"
        if cid:
            p["newClientOrderId"] = cid
        return self._req("POST", "/fapi/v1/order", p)

    def place_stop(self, symbol, close_side, price):
        """STOP_MARKET that closes the whole position when the mark price touches `price`.
        Returns {"id", "kind"}; kind is "algo" (normal) or "classic" (only if the algo endpoint is missing)."""
        price = self.round_price(symbol, price)
        try:
            r = self._req("POST", "/fapi/v1/algoOrder", {
                "algoType": "CONDITIONAL", "symbol": symbol, "side": close_side, "type": "STOP_MARKET",
                "triggerPrice": price, "closePosition": "true", "workingType": "MARK_PRICE"})
            oid = r.get("algoId") if isinstance(r, dict) else None
            if oid is None:
                raise ApiError(0, "stop placed but no algoId in the answer: %s" % str(r)[:120])
            return {"id": oid, "kind": "algo", "price": price}
        except ApiError as e:
            if e.status != 404:
                raise
        r = self._req("POST", "/fapi/v1/order", {"symbol": symbol, "side": close_side, "type": "STOP_MARKET",
                                                 "stopPrice": price, "closePosition": "true", "workingType": "MARK_PRICE"})
        return {"id": r.get("orderId"), "kind": "classic", "price": price}

    def open_stops(self, symbol):
        """Resting stop orders on the symbol: [{id, kind, trigger}]. Never raises on the optional classic list."""
        out = []
        try:
            rows = self._req("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol})
            for o in rows if isinstance(rows, list) else []:
                if (o.get("orderType") or o.get("type")) in STOP_TYPES and o.get("symbol", symbol) == symbol:
                    out.append({"id": o.get("algoId"), "kind": "algo", "trigger": _f(o.get("triggerPrice") or o.get("stopPrice"))})
        except ApiError as e:
            if e.status != 404:
                raise
        try:
            rows = self._req("GET", "/fapi/v1/openOrders", {"symbol": symbol})
            for o in rows if isinstance(rows, list) else []:
                if o.get("type") in STOP_TYPES:
                    out.append({"id": o.get("orderId"), "kind": "classic", "trigger": _f(o.get("stopPrice"))})
        except ApiError:
            pass
        return out

    def cancel_stop(self, symbol, stop):
        try:
            if stop.get("kind") == "algo":
                self._req("DELETE", "/fapi/v1/algoOrder", {"symbol": symbol, "algoId": stop["id"]})
            else:
                self._req("DELETE", "/fapi/v1/order", {"symbol": symbol, "orderId": stop["id"]})
        except ApiError as e:
            if e.code not in (-2011, -2013, -4130):   # already gone / unknown order is fine
                raise

    def trades_since(self, symbol, since_ms):
        """My fills on the symbol since a time: realized P&L and commission (USDT) summed."""
        rows = self._req("GET", "/fapi/v1/userTrades", {"symbol": symbol, "startTime": int(since_ms), "limit": 200})
        pnl = fee = 0.0
        n = 0
        for r in rows if isinstance(rows, list) else []:
            pnl += _f(r.get("realizedPnl"))
            fee += _f(r.get("commission"))
            n += 1
        return {"pnl": pnl, "fee": fee, "n": n}
