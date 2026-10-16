"""Binance USDT-M Futures PRIVATE REST client - places/closes REAL live
orders with REAL money. Mirrors kucoin_trader.py's interface exactly
(open_market_order(symbol, action, live_price) / close_position_market(symbol,
position_action) / test_connection()) so exchange.py can dispatch between the
two live-trading engines the same way it already dispatches the two market-
data clients - paper_trader.py calls exchange.* and never needs to know which
exchange is actually live.

SAFETY MODEL (same shape as kucoin_trader.py):
  - Every function here is wrapped so it NEVER raises into the caller
    (paper_trader.py). A live-order failure logs to status.add_alert and
    returns None - paper-trading bookkeeping (source of truth for the
    UI/stats/Telegram) always continues regardless of whether the live leg
    succeeded.
  - Live trading only fires if settings_store.get("live_trading_enabled") is
    True - the SAME master switch KuCoin's live trading uses, since only one
    exchange is ever active at a time (settings_store["active_exchange"]).
    Default off; must be turned on explicitly in Settings.
  - Credentials (binance_api_key/binance_api_secret) live only in
    settings_store's settings.json on-device - never hardcoded, never
    logged in full.
  - Every low-level order function additionally takes an explicit
    confirm=True requirement, so a stray call from a refactor can never fire
    a real order silently.

REAL-MONEY CONFIGURATION (confirmed with user, India IP verified working):
  - USE_TESTNET = False - hits Binance's live Futures endpoint
    (https://fapi.binance.com) directly, not the testnet.
  - recvWindow = 60000 (ms) - generous tolerance for mobile network latency
    and phone clock drift, so a signed request doesn't get rejected as
    "outside recvWindow" on a slow connection.
  - Query strings are signed as a DETERMINISTIC, key-sorted string
    (urlencode(sorted(params.items()))) - same signature every time for the
    same params, easier to debug/replay than dict-insertion-order encoding.
  - Leverage is set via /fapi/v1/leverage for the traded symbol BEFORE every
    order fires - this is what lets a $1-2 USDT balance still clear
    Binance's per-symbol minimum-notional filter (order rejected with
    -4164 "Order's notional must be no smaller than X" otherwise): notional
    = invest_usdt * leverage, so configuring leverage first (rather than
    trusting whatever the account happened to have) is the fix, not
    something to skip for speed.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import requests

from . import settings_store, status, protection_manager
from .http_client import get_session

USE_TESTNET = False  # Real trading, not Binance's testnet - see module docstring.
BASE_URL = "https://testnet.binancefuture.com" if USE_TESTNET else "https://fapi.binance.com"
RECV_WINDOW = 60000
REQUEST_TIMEOUT_SEC = 10
MIN_NOTIONAL_FLOOR = 5.0  # Binance's usual USDT-M minimum notional per order, used as a
                            # fallback if a symbol's own MIN_NOTIONAL filter can't be read.

# ---- Fill confirmation (PART 2 hardening) ----
# A MARKET order's own POST response is USUALLY already FILLED by the time
# it comes back, but "usually" is exactly the assumption this module must
# never make (see module docstring) - a slow/queued fill, a partial fill,
# or a flaky response can all look like a plain 200 without the position
# actually existing yet. Every order is re-confirmed via a GET before
# anything downstream (stop-loss placement, the returned order id) trusts
# it.
FILL_POLL_ATTEMPTS = 6
FILL_POLL_DELAY_SEC = 0.5  # ~3s total worst case - Binance Futures market
                             # fills are near-instant; this is a safety net
                             # for a slow/queued response, not the normal path.
EMERGENCY_SL_PCT_DEFAULT = 2.0  # settings_store["live_emergency_sl_pct"] overrides this -
                                  # used ONLY when open_market_order() isn't given an
                                  # explicit stop_loss_price (no strategy signal SL available).

# ---- Placement-ambiguity safety net (PART 4 hardening - Issue 1) ----
# Binance's own error-code docs define these three as "we genuinely don't
# know what happened to your request" - NOT a clean rejection like a bad
# quantity or insufficient margin:
#   -1006 UNEXPECTED_RESP  "unexpected response from the message bus.
#                            Execution status unknown."
#   -1007 TIMEOUT          "Timeout waiting for response from backend
#                            server... execution status unknown."
#   -1008 (Service Unavailable - overloaded, response never confirmed)
# A plain network-level timeout/connection error (never reaching Binance
# at all, or never getting ANY response back) is the same kind of
# ambiguity, just detected one layer lower (requests/urllib3 instead of a
# Binance error body). Both trigger the same clientOrderId-verify path in
# open_market_order() below - see _recover_order_by_client_id().
AMBIGUOUS_EXECUTION_CODES = (-1006, -1007, -1008)

# The verify GET (origClientOrderId lookup) is read-only - it never
# places, modifies, or cancels anything - so, unlike the order placement
# itself, it's safe to retry on its own if IT also times out. Bounded
# (not infinite) so a genuinely unreachable Binance still gives up and
# reports "status unknown" rather than hanging the scanner loop forever.
ORDER_RECOVERY_ATTEMPTS = 3
ORDER_RECOVERY_DELAY_SEC = 1.5


class BinanceAPIError(Exception):
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload
        super().__init__(f"Binance API error {status_code}: {payload}")


def _parse_binance_error(payload):
    """Best-effort parse of Binance's {"code":-2022,"msg":"..."} error body
    into (code, msg). `payload` is normally resp.text (a raw JSON string)
    but can also be a plain non-JSON string (e.g. the local
    "No Binance API key/secret set in Settings" case above, which never
    even reaches the exchange). Never raises - returns (None, None) on
    anything unparseable, so a malformed/unexpected body can never crash
    the caller or corrupt the telemetry log."""
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
        if isinstance(data, dict) and "code" in data:
            return data.get("code"), data.get("msg")
    except Exception:
        pass
    return None, None


# ---- Conditional/algo order types this module recognises as "protective"
# (a resting STOP_MARKET or TAKE_PROFIT_MARKET/-LIMIT order) - shared by
# get_open_algo_orders()/cancel_and_replace_sl() below, and kept as the
# same set protection_manager.py's STOP_TYPES/TP_TYPES use, so both
# modules agree on what counts as "a stop" vs "a target" without either
# importing the other's constants.
_STOP_ORDER_TYPES = ("STOP_MARKET", "STOP")
_TP_ORDER_TYPES = ("TAKE_PROFIT_MARKET", "TAKE_PROFIT")
_ALGO_ORDER_TYPES = _STOP_ORDER_TYPES + _TP_ORDER_TYPES


def _extract_order_id(resp):
    """Robustly pulls the exchange order id out of ANY shape of response
    this module's order-placing/cancelling calls can hand back:
      - a normal single-order dict: {"orderId": 123456789, ...}
      - a dict where Binance (rarely, on some error-adjacent paths) only
        echoes the client id: {"clientOrderId": "OWL-...", ...}
      - a list (bulk cancel / bulk order responses) - returns the id of
        the FIRST element, since every call site here only ever expects
        one order id back per call
      - None / a non-dict / a dict missing both keys - returns None

    Never raises - a response this module can't make sense of is treated
    as "no id available", exactly like any other soft failure here, so a
    malformed/unexpected payload from Binance can never propagate as an
    exception into paper_trader.py or protection_manager.py."""
    try:
        if isinstance(resp, list):
            resp = resp[0] if resp else None
        if not isinstance(resp, dict):
            return None
        oid = resp.get("orderId")
        if oid not in (None, "", 0):
            try:
                return int(oid)
            except (TypeError, ValueError):
                return oid
        coid = resp.get("clientOrderId")
        return coid or None
    except Exception:
        return None


def _creds():
    s = settings_store.get_all()
    return (
        (s.get("binance_api_key") or "").strip(),
        (s.get("binance_api_secret") or "").strip(),
    )


def _sorted_urlencode(params: dict) -> str:
    """Deterministic key-sorted query string - same params always produce the
    same string (and therefore the same signature), regardless of dict
    insertion order."""
    return urlencode(sorted(params.items()))


def _signed_request(method, path, params=None, timeout=None):
    key, secret = _creds()
    if not key or not secret:
        raise BinanceAPIError(0, "No Binance API key/secret set in Settings")
    params = dict(params or {})
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = RECV_WINDOW

    query_string = _sorted_urlencode(params)
    signature = hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()
    full_url = f"{BASE_URL}{path}?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": key}

    session = get_session()
    resp = session.request(method, full_url, headers=headers, timeout=timeout or REQUEST_TIMEOUT_SEC)
    if resp.status_code != 200:
        # DIAGNOSTICS TELEMETRY: log every real exchange error code here,
        # centrally, regardless of which higher-level function triggered
        # it (open, close, leverage, cancel...) - this is the one choke
        # point every signed Binance call passes through, so it's the one
        # place that can promise the DiagnosticsCard's recent-error log
        # never misses a code. Never blocks the raise below on a logging
        # failure.
        try:
            code, msg = _parse_binance_error(resp.text)
            if code is not None:
                status.add_api_error(code, msg, symbol=(params or {}).get("symbol"), endpoint=path)
        except Exception:
            pass
        raise BinanceAPIError(resp.status_code, resp.text)
    return resp.json()


def test_connection():
    """Called from Settings' Binance 'Test Connection' button - authenticates with
    whatever key/secret are currently saved, without placing any order. Does NOT
    require live_trading_enabled to be on. Same return shape as before
    ({"ok": bool, "available_usdt": ...}) plus wallet / unrealized for the app."""
    try:
        w = get_wallet_summary()
        if not w.get("ok"):
            return {"ok": False, "error": w.get("error") or "Connection failed"}
        return {"ok": True, "available_usdt": w.get("available", 0.0),
                "wallet_usdt": w.get("wallet", 0.0), "unrealized_usdt": w.get("unrealized", 0.0)}
    except Exception as e:
        return {"ok": False, "error": f"Connection failed: {e}"}


def get_account_balance():
    """Returns float USDT futures wallet balance, or None on failure."""
    try:
        data = _signed_request("GET", "/fapi/v2/balance")
        if isinstance(data, list):
            for item in data:
                if item.get("asset") == "USDT":
                    return float(item.get("balance", 0.0))
        return 0.0
    except Exception:
        return None


def get_wallet_summary():
    """Real USDT futures wallet numbers for the app (Dashboard "Live wallet" card).
    One signed call to /fapi/v2/account; if that fails, falls back to /fapi/v2/balance.
    Never raises: returns {"ok": False, "error": "..."} so the app can show WHY it is empty
    (wrong key, no Futures permission, IP not whitelisted ...) instead of a blank card."""
    def _f(v):
        try:
            return float(v or 0.0)
        except Exception:
            return 0.0
    err = ""
    try:
        d = _signed_request("GET", "/fapi/v2/account")
        if isinstance(d, dict):
            wallet = _f(d.get("totalWalletBalance"))
            upnl = _f(d.get("totalUnrealizedProfit"))
            avail = _f(d.get("availableBalance"))
            margin_bal = _f(d.get("totalMarginBalance")) or (wallet + upnl)
            used = _f(d.get("totalPositionInitialMargin")) + _f(d.get("totalOpenOrderInitialMargin"))
            if not used:
                used = _f(d.get("totalInitialMargin"))
            return {"ok": True, "wallet": round(wallet, 4), "available": round(avail, 4),
                    "unrealized": round(upnl, 4), "margin_balance": round(margin_bal, 4),
                    "margin_used": round(used, 4), "asset": "USDT", "ts": time.time()}
    except Exception as e:
        err = str(e)[:160]
    try:
        data = _signed_request("GET", "/fapi/v2/balance")
        if isinstance(data, list):
            for item in data:
                if item.get("asset") == "USDT":
                    wallet = _f(item.get("balance"))
                    upnl = _f(item.get("crossUnPnl"))
                    avail = _f(item.get("availableBalance"))
                    return {"ok": True, "wallet": round(wallet, 4), "available": round(avail, 4),
                            "unrealized": round(upnl, 4), "margin_balance": round(wallet + upnl, 4),
                            "margin_used": round(max(0.0, wallet + upnl - avail), 4),
                            "asset": "USDT", "ts": time.time()}
            return {"ok": False, "error": "No USDT balance row in the Binance answer", "ts": time.time()}
    except Exception as e:
        err = str(e)[:160] or err
    return {"ok": False, "error": err or "Binance wallet fetch failed", "ts": time.time()}


# ---- Symbol precision + minimum notional (needed to size/place any real
# order correctly - Binance rejects orders whose quantity doesn't match the
# symbol's LOT_SIZE step, or whose notional is below MIN_NOTIONAL, it will
# not round or bump these for you) ----
_exchange_info_cache = {"data": None, "ts": 0}
_EXCHANGE_INFO_TTL = 3600  # symbol filters basically never change - cache 1h


def _get_symbol_filters(symbol):
    now = time.time()
    if _exchange_info_cache["data"] is None or (now - _exchange_info_cache["ts"]) > _EXCHANGE_INFO_TTL:
        session = get_session()
        resp = session.get(BASE_URL + "/fapi/v1/exchangeInfo", timeout=15)
        resp.raise_for_status()
        _exchange_info_cache["data"] = resp.json()
        _exchange_info_cache["ts"] = now
    for s in _exchange_info_cache["data"].get("symbols", []):
        if s.get("symbol") == symbol:
            return s.get("filters", [])
    return []


def _step_from_filters(filters, filter_type, key):
    for f in filters:
        if f.get("filterType") == filter_type:
            return float(f.get(key, 0)) or None
    return None


def round_qty(symbol, qty):
    """Rounds DOWN to the symbol's LOT_SIZE step - never rounds up on its
    own (min-notional bumping, when needed, is a deliberate separate step -
    see _ensure_min_notional below)."""
    filters = _get_symbol_filters(symbol)
    step = _step_from_filters(filters, "LOT_SIZE", "stepSize")
    if not step or step <= 0:
        return qty
    steps = int(qty / step)
    return round(steps * step, 10)


def round_price(symbol, price):
    """Rounds to the symbol's PRICE_FILTER tick size (nearest)."""
    filters = _get_symbol_filters(symbol)
    tick = _step_from_filters(filters, "PRICE_FILTER", "tickSize")
    if not tick or tick <= 0:
        return price
    steps = round(price / tick)
    return round(steps * tick, 10)


def _ensure_min_notional(symbol, qty, price):
    """If qty*price would fall below the symbol's own MIN_NOTIONAL filter
    (falls back to MIN_NOTIONAL_FLOOR if the filter isn't published for this
    symbol), bumps qty UP - one LOT_SIZE step at a time - just far enough to
    clear it. This is the fix for a $1-2 USDT balance getting rejected with
    -4164 even after leverage is configured: at very small invest amounts
    the raw formula can still round down to a notional a hair under the
    minimum, and re-rejecting that trade would defeat the whole point of
    setting leverage first. Never bumps by more than a few steps - if it's
    still short after that, the balance is genuinely too small for this
    symbol at the configured leverage, and the caller's normal
    "insufficient" alert path takes over instead."""
    filters = _get_symbol_filters(symbol)
    min_notional = _step_from_filters(filters, "MIN_NOTIONAL", "notional") or MIN_NOTIONAL_FLOOR
    step = _step_from_filters(filters, "LOT_SIZE", "stepSize") or 0.0
    tries = 0
    while qty * price < min_notional and step > 0 and tries < 50:
        qty = round(qty + step, 10)
        tries += 1
    return qty


def place_market_order(symbol, side, quantity, confirm=False, reduce_only=False, client_order_id=None):
    if not confirm:
        raise ValueError("place_market_order() requires confirm=True - refusing to place a real order silently")
    params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": quantity}
    if reduce_only:
        params["reduceOnly"] = "true"
    if client_order_id:
        params["newClientOrderId"] = client_order_id
    return _signed_request("POST", "/fapi/v1/order", params)


def set_leverage(symbol, leverage, confirm=False):
    if not confirm:
        raise ValueError("set_leverage() requires confirm=True")
    return _signed_request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(leverage)})


def _client_order_id(symbol, side):
    """Deterministic per-attempt id: OWL-{symbol}-{side}-{timestamp_ms}.
    Binance caps clientOrderId at 36 chars - truncated defensively so an
    unusually long symbol can never make the order request itself invalid."""
    raw = f"OWL-{symbol}-{side}-{int(time.time() * 1000)}"
    return raw[:36]


def get_order(symbol, order_id=None, client_order_id=None):
    """Raw GET /fapi/v1/order - the source of truth for what actually
    happened to an order, never inferred from the placement response
    alone. Raises BinanceAPIError/Exception on failure - callers here
    always wrap this (see _poll_until_filled)."""
    params = {"symbol": symbol}
    if order_id is not None:
        params["orderId"] = order_id
    elif client_order_id:
        params["origClientOrderId"] = client_order_id
    else:
        raise ValueError("get_order() needs order_id or client_order_id")
    return _signed_request("GET", "/fapi/v1/order", params)


def _poll_until_filled(symbol, order_id, initial=None,
                        attempts=FILL_POLL_ATTEMPTS, delay_sec=FILL_POLL_DELAY_SEC):
    """Re-queries Binance directly until the order reaches a terminal
    state (FILLED, or a genuine dead-end like CANCELED/EXPIRED/REJECTED),
    or `attempts` is exhausted. `initial` is the placement response itself
    - checked first so a fast fill doesn't cost an extra round trip - but
    it is never trusted on its own; every other attempt is a fresh GET.
    Returns the last order dict seen (which may still be non-FILLED, or
    None on repeated network failure) - the caller decides what a
    non-terminal result means, this function only fetches truth."""
    order = initial
    terminal = {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}
    for attempt in range(attempts):
        if order is not None and order.get("status") in terminal:
            return order
        time.sleep(delay_sec)
        try:
            order = get_order(symbol, order_id=order_id)
        except Exception:
            order = None
    return order


def _recover_order_by_client_id(symbol, client_order_id,
                                 attempts=ORDER_RECOVERY_ATTEMPTS,
                                 delay_sec=ORDER_RECOVERY_DELAY_SEC):
    """Read-only recovery lookup for the ONE scenario where it's actually
    needed: open_market_order()'s placement POST itself came back
    ambiguous (network timeout/connection error, or one of Binance's own
    AMBIGUOUS_EXECUTION_CODES) - we genuinely don't know whether the order
    was placed. This never retries the PLACEMENT (that's what could create
    a duplicate); it only re-queries Binance for whatever
    `client_order_id` was already deterministically generated before the
    risky call, using GET /fapi/v1/order?origClientOrderId=... - a pure
    read, safe to retry on its own.

    Returns one of three outcomes as a ("FOUND"|"NOT_FOUND"|"UNKNOWN", order_or_None)
    tuple - the caller MUST handle all three distinctly, never collapsing
    "not found" and "still unknown" into the same branch:
      - ("FOUND", order_dict)  Binance confirms this exact clientOrderId
        exists (whatever its current status) - the placement DID go
        through despite the ambiguous response. Caller should treat this
        exactly like a normal successful placement and continue into the
        regular fill-confirmation flow.
      - ("NOT_FOUND", None)    Binance's own -2013 NO_SUCH_ORDER for this
        specific clientOrderId - a DEFINITIVE answer that nothing was ever
        placed under it. Safe to report as a clean failure; the strategy
        signal can be retried next cycle without any duplicate risk (a
        fresh call generates a new, different clientOrderId).
      - ("UNKNOWN", None)      every verify attempt ALSO failed to get a
        clear answer (Binance still unreachable, or every response was
        itself ambiguous) after `attempts` tries. This is NOT the same as
        "not found" - the order may well exist. Caller must never treat
        this as either success or a safe-to-retry failure; it must stop
        and demand a manual check."""
    for attempt in range(attempts):
        try:
            order = get_order(symbol, client_order_id=client_order_id)
            return ("FOUND", order)
        except BinanceAPIError as e:
            code, _msg = _parse_binance_error(e.payload)
            if code == -2013:
                return ("NOT_FOUND", None)
            # Any other Binance-side error on the verify GET itself (rare -
            # e.g. one of the same AMBIGUOUS_EXECUTION_CODES, hit again on
            # THIS read) - fall through to the retry below, same handling
            # as a plain network error.
        except Exception:
            pass
        if attempt < attempts - 1:
            time.sleep(delay_sec)
    return ("UNKNOWN", None)


# ------------------------------------------------------- high-level API ----
# Same call shape as kucoin_trader.py's open_market_order/close_position_market
# so paper_trader.py (via exchange.py) never branches on which exchange is
# live - it just calls exchange.open_market_order(...)/close_position_market(...).

def open_market_order(symbol, action, live_price, stop_loss_price=None):
    """Places a real market order matching a paper-trade open. `stop_loss_price`
    is the strategy signal's own SL (e.g. signal.stop_loss) when the caller
    has one - pass it through so the exchange-side stop matches what
    Telegram/the UI actually promised, instead of always falling back to
    the generic emergency %. Returns the Binance order id on success, or
    None (logged to Alerts) on any failure - never raises into paper_trader.py
    or app.py.

    SAFETY MODEL ADDITION (Part 2): a 200 from Binance's own order POST is
    NOT treated as proof the position exists - see _poll_until_filled().
    Only once a GET confirms status=FILLED do we trust executedQty/avgPrice
    and hand the position off to protection_manager for its native
    exchange-side stop. If fill can never be confirmed, this returns None
    (a false "order failed") rather than ever silently leaving a position
    unprotected because we guessed it worked.

    SAFETY MODEL ADDITION (Part 4 - Issue 1, order-desync hardening): the
    PLACEMENT request itself (the POST that opens the order) is now also
    treated as possibly ambiguous, not just possibly-not-yet-filled. If
    that POST raises a network timeout/connection error, or Binance
    itself responds with one of AMBIGUOUS_EXECUTION_CODES (-1006/-1007/
    -1008 - Binance's own "execution status unknown" family), this
    function does NOT blindly retry the placement (that is exactly how a
    duplicate live order gets opened - see module docstring). Instead it
    verifies via the deterministic client_order_id already generated
    before the risky call, using a read-only GET
    (_recover_order_by_client_id) that's safe to retry on its own:
      - order genuinely exists (FOUND)     -> treated as a normal
        successful placement, continues into the same fill-confirmation
        flow below as if nothing went wrong.
      - Binance confirms NOT_FOUND (-2013) -> a clean, definitive
        failure; returns None exactly like any other rejected order (the
        next scan cycle can safely retry the signal - a fresh call
        generates a fresh, different client_order_id, so no duplicate
        risk).
      - still UNKNOWN after every verify attempt -> the one genuinely
        unresolved case. Returns None but with a distinct, louder alert
        demanding a MANUAL check on the Binance app, since this is the
        one outcome where a real, filled, unprotected position might
        exist that this function itself cannot rule out."""
    if not settings_store.get("live_trading_enabled", False):
        return None
    try:
        s = settings_store.get_all()
        leverage = float(s.get("live_leverage", 3)) or 1.0
        mode = s.get("position_size_mode", "fixed")
        value = float(s.get("position_size_value", 10.0))
        if mode == "percent_balance":
            balance = get_account_balance()
            if not balance:
                status.add_alert("manual", f"LIVE ORDER FAILED: {symbol} - could not fetch Binance balance")
                return None
            invest_usdt = max(1.0, balance * (value / 100.0))
        else:
            invest_usdt = value

        # Leverage FIRST - this is what lets a tiny balance clear the
        # exchange's minimum-notional filter (see module docstring).
        try:
            set_leverage(symbol, int(leverage), confirm=True)
        except Exception as e:
            status.add_alert("manual", f"LIVE {symbol}: set_leverage failed ({e}) - continuing with account's current leverage")

        qty = round_qty(symbol, (invest_usdt * leverage) / live_price)
        qty = _ensure_min_notional(symbol, qty, live_price)
        if not qty or qty <= 0:
            status.add_alert("manual", f"LIVE ORDER FAILED: {symbol} - computed size below exchange minimum even after leverage")
            return None

        side = "BUY" if action.upper() == "BUY" else "SELL"
        # Generated ONCE, before the risky call - this is what lets the
        # ambiguity-recovery path below re-identify this exact attempt
        # afterward, and it's never regenerated/reused for a retry, so it
        # can never itself become a source of a duplicate order.
        client_order_id = _client_order_id(symbol, side)

        placed = None
        ambiguity_reason = None
        try:
            placed = place_market_order(symbol, side, qty, confirm=True, client_order_id=client_order_id)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            # Never reached Binance, or never got ANY response back -
            # genuinely don't know if the order was placed. See
            # AMBIGUOUS_EXECUTION_CODES docstring above this function for
            # why this does NOT simply retry the placement.
            ambiguity_reason = f"placement request {type(e).__name__} ({e})"
        except BinanceAPIError as e:
            code, msg = _parse_binance_error(e.payload)
            if code in AMBIGUOUS_EXECUTION_CODES:
                ambiguity_reason = f"Binance execution-status-unknown, code={code} ({msg or e})"
            else:
                # A clean, definitive rejection (bad qty, insufficient
                # margin, invalid symbol, etc.) - no ambiguity here, this
                # order was never placed. Re-raise so the function's own
                # outer except (below, unchanged from before) handles it
                # exactly as it always has: one alert, return None. This
                # is deliberately NOT routed through the verify path -
                # verifying a clientOrderId Binance just told us it
                # definitively rejected would only ever confirm the same
                # NOT_FOUND, for no benefit.
                raise

        if ambiguity_reason is not None:
            status.add_alert(
                "manual",
                f"LIVE {symbol}: order placement response ambiguous ({ambiguity_reason}) - "
                f"verifying via clientOrderId={client_order_id} before giving up...",
            )
            outcome, recovered = _recover_order_by_client_id(symbol, client_order_id)
            if outcome == "FOUND":
                placed = recovered
                status.add_alert(
                    "manual",
                    f"LIVE {symbol}: order RECOVERED after ambiguous placement response "
                    f"(orderId={_extract_order_id(placed)}) - continuing normally, no duplicate submitted",
                )
            elif outcome == "NOT_FOUND":
                status.add_alert(
                    "manual",
                    f"LIVE ORDER FAILED: {symbol} {side} - placement response was ambiguous, but Binance "
                    f"confirms clientOrderId={client_order_id} was never placed (NO_SUCH_ORDER). Nothing "
                    f"opened on the exchange - safe to let the strategy retry this signal normally.",
                )
                return None
            else:  # "UNKNOWN"
                status.add_alert(
                    "manual",
                    f"LIVE ORDER STATUS UNKNOWN: {symbol} {side} clientOrderId={client_order_id} - both the "
                    f"placement AND every verification attempt were ambiguous. CHECK BINANCE APP MANUALLY "
                    f"right now - a real position may exist and be unprotected. Not treating this as open "
                    f"here to avoid ever submitting a second order on top of a possibly-real one.",
                )
                return None

        order_id = _extract_order_id(placed)

        confirmed = _poll_until_filled(symbol, order_id, initial=placed)
        if not confirmed or confirmed.get("status") != "FILLED":
            got_status = confirmed.get("status") if confirmed else "UNKNOWN (fill check failed)"
            status.add_alert(
                "manual",
                f"LIVE ORDER FILL UNCONFIRMED: {symbol} {side} orderId={order_id} status={got_status} - "
                f"CHECK BINANCE APP MANUALLY. Not treating this as an open position here.",
            )
            return None

        actual_qty = float(confirmed.get("executedQty", 0) or 0)
        actual_price = float(confirmed.get("avgPrice", 0) or 0)
        if actual_qty <= 0:
            status.add_alert("manual", f"LIVE ORDER FILLED BUT executedQty=0: {symbol} orderId={order_id} - check manually")
            return None
        if actual_price <= 0:
            # Should not normally happen once status is FILLED - fall back to
            # the requested price only for the SL calc below, and say so.
            actual_price = live_price
            status.add_alert("manual", f"LIVE {symbol}: avgPrice missing from confirmed fill, using requested price {live_price:g} for SL calc")

        status.add_alert(
            "manual",
            f"LIVE ORDER OK: {symbol} {side} filled {actual_qty:g} @ {actual_price:g} "
            f"(orderId={order_id}, ~{invest_usdt:.2f} USDT x{leverage:g})",
        )

        # ---- Native exchange-side protective stop - PRIMARY DEFENSE ----
        # Fires immediately after fill confirmation, using the REAL fill
        # price (not the pre-trade live_price estimate) - this is what
        # protects the position if the phone/Termux dies right after this
        # call returns, per the module's SAFETY MODEL.
        sl_price = stop_loss_price
        if sl_price is None:
            pct = float(settings_store.get("live_emergency_sl_pct", EMERGENCY_SL_PCT_DEFAULT) or EMERGENCY_SL_PCT_DEFAULT)
            sl_price = actual_price * (1 - pct / 100.0) if side == "BUY" else actual_price * (1 + pct / 100.0)
            status.add_alert("manual", f"LIVE {symbol}: no signal SL provided - using {pct:g}% emergency stop @ {sl_price:g}")
        try:
            stop_order_id = protection_manager.place_stop_loss(symbol, side, sl_price)
            if stop_order_id is None:
                status.add_alert("manual", f"LIVE {symbol}: PROTECTIVE STOP FAILED TO PLACE - position is UNPROTECTED, set SL manually now")
        except Exception as e:
            status.add_alert("manual", f"LIVE {symbol}: protective stop placement raised {e} - position is UNPROTECTED, set SL manually now")

        return order_id
    except Exception as e:
        status.add_alert("manual", f"LIVE ORDER FAILED: {symbol} {action} - {e}")
        return None


def get_open_positions(strict=False):
    """Real open positions currently held on Binance Futures - used by
    api_server.py to show the actual account state when live_trading_enabled
    is on (instead of the paper-trading positions list). Returns a list of
    dicts shaped close enough to a paper position (symbol/action/entry_price/
    ltp/pnl_usdt/roi_pct/leverage) for the existing Flutter position cards to
    render without needing a live-specific layout. Returns [] on any failure
    (never raises) - an empty list just means \"show no positions\", which is
    always a safe fallback.
    """
    try:
        rows = _signed_request("GET", "/fapi/v2/positionRisk")
    except Exception as e:
        if strict:
            raise          # caller (max-open check) must not mistake "could not read" for "no positions"
        status.add_alert("manual", f"LIVE POSITIONS FETCH FAILED: {e}")
        return []
    out = []
    for p in rows if isinstance(rows, list) else []:
        try:
            amt = float(p.get("positionAmt", 0) or 0)
            if amt == 0:
                continue
            entry = float(p.get("entryPrice", 0) or 0)
            mark = float(p.get("markPrice", 0) or 0)
            leverage = float(p.get("leverage", 1) or 1)
            action = "BUY" if amt > 0 else "SELL"
            pnl = float(p.get("unRealizedProfit", 0) or 0)
            margin = abs(amt) * entry / leverage if leverage else 0.0
            roi_pct = (pnl / margin * 100.0) if margin else 0.0
            out.append({
                "id": p.get("symbol"),
                "symbol": p.get("symbol"),
                "action": action,
                "entry_price": entry,
                "ltp": mark,
                "invest_usdt": round(margin, 4),
                "leverage": leverage,
                "pnl_usdt": pnl,
                "roi_pct": roi_pct,
                "status": "OPEN",
                "source": "live",
            })
        except Exception:
            continue
    return out


ALREADY_CLOSED_SENTINEL = "ALREADY_CLOSED"


def close_position_market(symbol, position_action):
    """Closes the REAL open position on `symbol` at market - reduce-only,
    opposite side of how it was opened. Binance has no single "closeOrder"
    flag like KuCoin's; reduceOnly + the full position quantity does the
    same job. Reads the live quantity straight from Binance's own open
    positions so it always matches exactly, even if the position was
    adjusted directly on Binance.

    CRASH-GUARD (production hardening): a position can legitimately vanish
    between the positionRisk read below and the order actually landing -
    the guard loop's own TP1-breakeven shift, Binance's native SL/TP
    firing, or another client closing it first can all do this in the
    handful of milliseconds this function takes. Binance's answer to a
    reduce-only order against a position that no longer exists is HTTP
    400 with {"code": -2022, "msg": "ReduceOnly Order is rejected."} -
    that is NOT a real failure, the end state the caller wanted (flat) is
    already true, so this is treated as a graceful skip: returns the
    ALREADY_CLOSED_SENTINEL string (truthy / not None, so callers that
    check `order_id is not None` correctly see this as "ok") instead of
    letting the exception propagate or reporting it as a failed close.
    Every other BinanceAPIError still returns None (a real failure) same
    as before."""
    if not settings_store.get("live_trading_enabled", False):
        return None
    try:
        positions = _signed_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
        amt = 0.0
        for p in positions if isinstance(positions, list) else []:
            if p.get("symbol") == symbol:
                amt = abs(float(p.get("positionAmt", 0)))
                break
        if amt <= 0:
            print(f"[binance_trader] close skipped: {symbol} already flat on Binance")
            return ALREADY_CLOSED_SENTINEL
        close_side = "SELL" if position_action.upper() == "BUY" else "BUY"
        order = place_market_order(symbol, close_side, amt, confirm=True, reduce_only=True)
        order_id = order.get("orderId")
        status.add_alert("manual", f"LIVE CLOSE OK: {symbol} orderId={order_id}")
        # Record the real result of this trade (History / P&L / AI) - see
        # live_recorder.py. Background thread, never raises, never blocks.
        try:
            from . import live_recorder
            live_recorder.finalize_close(symbol, "MANUAL")
        except Exception:
            pass
        # Best-effort cleanup: a closePosition=true stop/TP normally gets
        # auto-cancelled by Binance once the position is flat, but this
        # covers the edge case (partial-fill timing, a stale resting order
        # from an earlier crash) where one is left behind pointing at a
        # position that no longer exists. Never lets a cleanup failure
        # affect the return value - the close itself already succeeded.
        try:
            protection_manager.cancel_all_protection(symbol)
        except Exception:
            pass
        return order_id
    except BinanceAPIError as e:
        code, msg = _parse_binance_error(e.payload)
        if code == -2022:
            # See CRASH-GUARD docstring above - the position closed out
            # from under us; that's a skip, not a failure.
            print(f"[binance_trader] close skipped: {symbol} already closed on exchange (-2022)")
            try:
                protection_manager.cancel_all_protection(symbol)
            except Exception:
                pass
            return ALREADY_CLOSED_SENTINEL
        status.add_alert("manual", f"LIVE CLOSE FAILED: {symbol} - {msg or e}")
        return None
    except Exception as e:
        status.add_alert("manual", f"LIVE CLOSE FAILED: {symbol} - {e}")
        return None


# =================================================== ZERO-LAG EXECUTION ====
# PART 3 - Boot-up reconciliation / continuous SL guard support.
#
# Everything below is new plumbing for reconciliation.py (boot-up state
# recovery) and protection_manager.py's continuous guard loop (native
# SL verification + TP1 -> breakeven auto-shift). Same SAFETY MODEL as the
# rest of this module: every function here NEVER raises into its caller,
# always returns None/False/[] on any failure (logged to status.add_alert),
# and never guesses - if Binance can't be reached or the position/side
# can't be confirmed, the function says so and does nothing destructive.
# ============================================================================

def _position_side(symbol):
    """BUY if Binance currently shows a net-long position on `symbol`,
    SELL if net-short, None if there's no open position at all (or the
    lookup itself failed). Duplicates protection_manager._position_side()
    on purpose - this module is a self-contained REST client (see the
    module docstring) and must never depend on protection_manager for a
    plain read, only for the actual protective-order side-effects it
    already imports it for."""
    try:
        rows = _signed_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
    except Exception:
        return None
    for p in rows if isinstance(rows, list) else []:
        if p.get("symbol") == symbol:
            try:
                amt = float(p.get("positionAmt", 0) or 0)
            except (TypeError, ValueError):
                continue
            if amt > 0:
                return "BUY"
            if amt < 0:
                return "SELL"
    return None


def get_open_algo_orders(symbol):
    """All currently resting conditional/algo orders (STOP_MARKET/STOP/
    TAKE_PROFIT_MARKET/TAKE_PROFIT) on `symbol` - the exact set
    protection_manager.py's native-stop guard loop needs to check
    "is a physical stop still resting on Binance right now" without
    having to import protection_manager (avoids a protection_manager <->
    binance_trader import cycle, since protection_manager is imported BY
    this module already). Always a fresh GET, never cached. Returns []
    on any failure - never raises."""
    try:
        # Conditional orders live on the Algo Service now (not in /openOrders); protection_manager reads both.
        orders = protection_manager.get_open_conditional_orders(symbol)
    except Exception as e:
        status.add_alert("manual", f"LIVE: could not fetch {symbol}'s open algo orders - {e}")
        return []
    return [o for o in (orders if isinstance(orders, list) else []) if o.get("type") in _ALGO_ORDER_TYPES]


def cancel_all_open_orders(symbol, confirm=False):
    """Cancels EVERY open order on `symbol` in one shot (Binance's own
    bulk endpoint - one request, not a cancel-per-order loop) - the resting
    stop AND take-profit AND any other order type that might somehow be
    open on the symbol. Used when a position has fully closed (TP/SL hit,
    manual close, or Binance shows it flat during reconciliation) to purge
    every orphaned pending order left pointing at a symbol that no longer
    has a position, per the continuous guard's "no laawaris (orphan)
    orders survive a closed position" requirement.

    Requires confirm=True (same silent-call guard as place_market_order/
    set_leverage). Returns True on success (including "nothing was open to
    cancel" - Binance itself returns an empty/void-ish response for that
    case, not an error), False on any failure (logged to Alerts)."""
    if not confirm:
        raise ValueError("cancel_all_open_orders() requires confirm=True - refusing to bulk-cancel silently")
    try:
        _signed_request("DELETE", "/fapi/v1/allOpenOrders", {"symbol": symbol})
        try:                                     # conditional (algo) orders are NOT covered by allOpenOrders
            _signed_request("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": symbol})
        except Exception as e:
            if "404" not in str(e) and "-2011" not in str(e):
                status.add_alert("manual", f"LIVE CANCEL-ALL: {symbol} - algo orders could not be cancelled ({e})")
                return False
        return True
    except BinanceAPIError as e:
        # Binance returns -2011 "Unknown order sent" when there was nothing
        # open to cancel in the first place - that is success, not failure,
        # for this function's purpose (the end state - "no orders resting on
        # this symbol" - is exactly what was asked for).
        if "-2011" in str(e.payload):
            return True
        status.add_alert("manual", f"LIVE CANCEL-ALL FAILED: {symbol} - {e}")
        return False
    except Exception as e:
        status.add_alert("manual", f"LIVE CANCEL-ALL FAILED: {symbol} - {e}")
        return False


def cancel_and_replace_sl(symbol, new_sl_price, confirm=True):
    """Cancels whatever STOP_MARKET/STOP is currently resting on `symbol`
    (take-profit orders are left completely untouched) and places a fresh
    native STOP_MARKET closePosition=true at `new_sl_price` - the exact
    "Guaranteed Risk-Free Auto Breakeven" primitive protection_manager.py's
    guard loop calls the instant price crosses TP1: cancel the original
    stop, re-plant it at the exact entry price, so the position can no
    longer lose money even if the phone/Termux/backend dies the very next
    second.

    Position side is auto-detected fresh from Binance (never trusts a
    caller-supplied side, since a stale/reversed guess here would flip the
    new stop's close-direction and could fail to protect the position at
    all). Returns the NEW stop order's exchange order id on success
    (robustly parsed via _extract_order_id - handles Binance's normal
    dict response as well as any bulk/odd-shaped response gracefully),
    or None on any failure - never raises. A None return means the
    position may now be UNPROTECTED (old stop cancelled, new one failed to
    place) and is always accompanied by a loud status.add_alert so the
    guard loop's very next tick re-detects the missing stop and retries."""
    if not confirm:
        raise ValueError("cancel_and_replace_sl() requires confirm=True - refusing to touch a live stop silently")
    side = _position_side(symbol)
    if side is None:
        status.add_alert("manual", f"LIVE SL BREAKEVEN SKIPPED: {symbol} - no open Binance position found")
        return None
    try:
        new_sl_price = round_price(symbol, float(new_sl_price))
    except Exception:
        status.add_alert("manual", f"LIVE SL BREAKEVEN FAILED: {symbol} - invalid new_sl_price {new_sl_price!r}")
        return None

    # Cancel only the resting STOP-type order(s) - a TP order on the same
    # symbol is never touched by this function.
    try:
        for o in get_open_algo_orders(symbol):
            if o.get("type") in _STOP_ORDER_TYPES:
                if not protection_manager.cancel_order(symbol, o.get("orderId"), algo=bool(o.get("_algo"))):
                    raise RuntimeError("cancel of the old stop failed")
    except Exception as e:
        status.add_alert("manual", f"LIVE SL BREAKEVEN FAILED: {symbol} - could not cancel existing stop ({e}) - old stop left in place, NOT replaced")
        return None

    try:
        close_side = "SELL" if side == "BUY" else "BUY"
        order_id = protection_manager.place_conditional(symbol, close_side, "STOP_MARKET", new_sl_price)
        order = order_id
        if order_id is None:
            status.add_alert("manual", f"LIVE SL BREAKEVEN: {symbol} - new stop placed but response had no order id (unparsed): {order}")
        else:
            status.add_alert("manual", f"LIVE SL BREAKEVEN: {symbol} stop moved to entry @ {new_sl_price:g} (orderId={order_id})")
        return order_id
    except Exception as e:
        status.add_alert("manual", f"LIVE SL BREAKEVEN FAILED: {symbol} - old stop was cancelled but new stop @ {new_sl_price:g} FAILED to place ({e}) - POSITION IS CURRENTLY UNPROTECTED")
        return None
