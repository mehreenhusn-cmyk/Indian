"""recovered_bot/protection_manager.py

PART 2 - EXCHANGE-SIDE PROTECTION LAYER (Binance USDT-M Futures only).

Standalone module: does NOT import binance_trader.py, execution_router.py,
or reconciliation.py - those import THIS module, never the other way
around, so there is no import cycle. It duplicates a small amount of
binance_trader.py's private-REST signing/precision plumbing on purpose
(same signing recipe, same LOT_SIZE/PRICE_FILTER rounding) so this file can
be read, tested, and reasoned about entirely on its own as "the one place
that manages resting stop/take-profit orders on Binance".

KuCoin is COMPLETELY EXCLUDED here - there is no kucoin_protection_manager
and nothing in this file ever talks to KuCoin's API. Binance Futures
(/fapi) is the sole exchange this module knows how to protect.

WHY closePosition=true INSTEAD OF reduceOnly+quantity
------------------------------------------------------
A STOP_MARKET / TAKE_PROFIT_MARKET order placed with `closePosition=true`
closes the ENTIRE current position the instant it triggers, whatever size
that position happens to be at that moment - no quantity to track, nothing
that can drift out of sync with partial fills or a position size that
changed since the order was placed. That is exactly the property wanted
here: this module never has to know or store "how much" a position is,
only "which symbol" and "which direction to flip to close it".

WHY MODIFY = CANCEL + RE-PLACE
--------------------------------
Binance Futures has no "amend this resting order's price" endpoint for
STOP_MARKET/TAKE_PROFIT_MARKET orders. Every modify_stop_loss()/
set_target_tp() call therefore cancels whatever is currently resting (if
anything) and places a fresh order at the new price. If the cancel
succeeds but the new placement then fails, this fails LOUD (alert +
returns None) instead of ever pretending the old, now-cancelled stop is
still protecting the position.

TIGHTEN-ONLY GUARD
--------------------
modify_stop_loss() (and therefore move_to_breakeven(), which is just
modify_stop_loss() aimed at the entry price) refuses to move the resting
stop in a direction that would ever loosen it - exactly the same rule
paper_trader.py already enforces locally for paper positions. A stale/
out-of-order UI tap can therefore never walk a live stop backwards.
"""
import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from urllib.parse import urlencode

from . import settings_store, status
from .http_client import get_session

USE_TESTNET = False  # Mirrors binance_trader.py - real trading, not testnet.
BASE_URL = "https://testnet.binancefuture.com" if USE_TESTNET else "https://fapi.binance.com"
RECV_WINDOW = 60000
REQUEST_TIMEOUT_SEC = 10

STOP_TYPES = ("STOP_MARKET", "STOP")
TP_TYPES = ("TAKE_PROFIT_MARKET", "TAKE_PROFIT")


class ProtectionAPIError(Exception):
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload
        super().__init__(f"Binance API error {status_code}: {payload}")


def _parse_binance_error(payload):
    """Duplicated from binance_trader.py on purpose - see this module's
    docstring for why it stays standalone. Best-effort parse of Binance's
    {"code":-2022,"msg":"..."} error body into (code, msg); never raises,
    returns (None, None) on anything unparseable."""
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
        if isinstance(data, dict) and "code" in data:
            return data.get("code"), data.get("msg")
    except Exception:
        pass
    return None, None


def _creds():
    s = settings_store.get_all()
    return (
        (s.get("binance_api_key") or "").strip(),
        (s.get("binance_api_secret") or "").strip(),
    )


def _sorted_urlencode(params: dict) -> str:
    return urlencode(sorted(params.items()))


def _signed_request(method, path, params=None, timeout=None):
    key, secret = _creds()
    if not key or not secret:
        raise ProtectionAPIError(0, "No Binance API key/secret set in Settings")
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
        # DIAGNOSTICS TELEMETRY - same choke-point logging as
        # binance_trader.py's _signed_request; this module is where SL/TP
        # placement errors (e.g. -4120 "would immediately trigger") most
        # often actually happen, so this is a primary source for the
        # DiagnosticsCard's recent-error log, not a secondary one.
        try:
            code, msg = _parse_binance_error(resp.text)
            if code is not None:
                status.add_api_error(code, msg, symbol=(params or {}).get("symbol"), endpoint=path)
        except Exception:
            pass
        raise ProtectionAPIError(resp.status_code, resp.text)
    return resp.json()


# ---- symbol precision (duplicated minimal subset of binance_trader.py's
# _get_symbol_filters/round_price - see module docstring for why) ----
_exchange_info_cache = {"data": None, "ts": 0}
_EXCHANGE_INFO_TTL = 3600


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


def round_price(symbol, price):
    """Rounds to the symbol's PRICE_FILTER tick size (nearest). Falls back
    to the raw price if the filter can't be read - a rejected order from
    Binance's own tick-size check is a louder, safer failure than silently
    refusing to protect the position over a precision lookup hiccup."""
    try:
        filters = _get_symbol_filters(symbol)
        tick = None
        for f in filters:
            if f.get("filterType") == "PRICE_FILTER":
                tick = float(f.get("tickSize", 0)) or None
                break
        if not tick or tick <= 0:
            return price
        steps = round(price / tick)
        return round(steps * tick, 10)
    except Exception:
        return price


# --------------------------------------------------------------- reads ----

def _norm_algo(o):
    """Algo-service order -> the classic shape the rest of this module (and reconciliation.py) already reads:
    type, orderId, stopPrice. `_algo` marks it so the cancel goes to the algo endpoint."""
    return {
        "symbol": o.get("symbol"),
        "side": o.get("side"),
        "type": o.get("orderType") or o.get("type"),
        "orderId": o.get("algoId"),
        "stopPrice": o.get("triggerPrice") or o.get("stopPrice") or 0,
        "_algo": True,
    }


def get_open_conditional_orders(symbol):
    """All resting orders on `symbol` right now - fresh from Binance every
    call, never cached (a stale view here is exactly the bug class this
    whole module exists to prevent).

    Since Binance moved STOP_MARKET / TAKE_PROFIT_MARKET to the Algo Service (2025-12), those orders are NOT in
    /fapi/v1/openOrders any more. They are read from /fapi/v1/openAlgoOrders and returned in the same shape as
    before (plus `_algo`: True). The classic list is still merged in, so an old order placed before the migration
    (or on an account where the algo endpoint answers 404) is still seen. If the ALGO read fails for a reason other
    than 404 it raises, so callers treat it as "could not check" instead of "no stop" (which would plant a duplicate)."""
    out = []
    try:
        rows = _signed_request("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol})
        for o in rows if isinstance(rows, list) else []:
            if o.get("symbol", symbol) == symbol:
                out.append(_norm_algo(o))
    except ProtectionAPIError as e:
        if e.status_code != 404:
            raise
    orders = _signed_request("GET", "/fapi/v1/openOrders", {"symbol": symbol})
    out.extend(orders if isinstance(orders, list) else [])
    return out


def get_active_stop(symbol):
    """The currently resting STOP_MARKET order on `symbol`, or None if
    there isn't one. Never raises - a lookup failure is treated the same
    as "no stop found" by every caller (reconciliation.py's job is exactly
    to notice and fix that)."""
    try:
        for o in get_open_conditional_orders(symbol):
            if o.get("type") in STOP_TYPES:
                return o
    except Exception as e:
        status.add_alert("manual", f"LIVE: could not check {symbol}'s protective stop - {e}")
    return None


def get_active_take_profit(symbol):
    try:
        for o in get_open_conditional_orders(symbol):
            if o.get("type") in TP_TYPES:
                return o
    except Exception as e:
        status.add_alert("manual", f"LIVE: could not check {symbol}'s take-profit order - {e}")
    return None


def _position_side(symbol):
    """BUY if Binance shows a net-long position on `symbol` right now, SELL
    if net-short, None if there's no open position at all (or the lookup
    failed) - callers must treat None as "nothing to protect", not as an
    error to surface on its own."""
    try:
        rows = _signed_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
    except Exception:
        return None
    for p in rows if isinstance(rows, list) else []:
        if p.get("symbol") == symbol:
            amt = float(p.get("positionAmt", 0) or 0)
            if amt > 0:
                return "BUY"
            if amt < 0:
                return "SELL"
    return None


def cancel_order(symbol, order_id, algo=None):
    """Cancels one order by id. Returns True on success, False on any
    failure (logs an alert) - never raises.
    algo=True  -> it is an algo-service order (DELETE /fapi/v1/algoOrder, algoId)
    algo=False -> classic order (DELETE /fapi/v1/order)
    algo=None  -> unknown: try algo first, then classic."""
    if not order_id:
        return False
    last = None
    if algo is not False:
        try:
            _signed_request("DELETE", "/fapi/v1/algoOrder", {"symbol": symbol, "algoId": order_id})
            return True
        except Exception as e:
            last = e
            if algo is True and not _is_gone(e):
                status.add_alert("manual", f"LIVE ORDER CANCEL FAILED: {symbol} #{order_id} - {e}")
                return False
            if algo is True:
                return True            # already gone is fine
    if algo is not True:
        try:
            _signed_request("DELETE", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id})
            return True
        except Exception as e:
            last = e
    status.add_alert("manual", f"LIVE ORDER CANCEL FAILED: {symbol} #{order_id} - {last}")
    return False


def _is_gone(e):
    """-2011 / -2013 / -4130: the order is already gone, which is what a cancel wants anyway."""
    s = str(getattr(e, "payload", e))
    return any(c in s for c in ("-2011", "-2013", "-4130"))


def place_conditional(symbol, close_side, order_type, price):
    """Places STOP_MARKET / TAKE_PROFIT_MARKET (closePosition=true, mark-price trigger) through the Algo Service.
    Falls back to the classic endpoint ONLY if the algo endpoint does not exist (HTTP 404). Returns the order id.
    Raises on failure - callers wrap it in their own try/except and alert."""
    try:
        r = _signed_request("POST", "/fapi/v1/algoOrder", {
            "algoType": "CONDITIONAL", "symbol": symbol, "side": close_side, "type": order_type,
            "triggerPrice": price, "closePosition": "true", "workingType": "MARK_PRICE"})
        oid = r.get("algoId") if isinstance(r, dict) else None
        if oid is None:
            # The order IS placed; only the id was not readable. Never raise here: the guard would place a duplicate.
            status.add_alert("manual", f"LIVE {order_type}: {symbol} placed on the algo service but the answer had no algoId: {str(r)[:120]}")
            return "algo-unparsed"
        return oid
    except ProtectionAPIError as e:
        if e.status_code != 404:
            raise
    r = _signed_request("POST", "/fapi/v1/order", {
        "symbol": symbol, "side": close_side, "type": order_type,
        "stopPrice": price, "closePosition": "true", "workingType": "MARK_PRICE"})
    return r.get("orderId")


# ------------------------------------------------------------ commands ----

def place_stop_loss(symbol, side, stop_price):
    """Places a fresh native STOP_MARKET that fully closes the position the
    instant `stop_price` is touched. `side` is the POSITION's own side
    ("BUY"/"SELL"), not the stop order's side - the close-side flip happens
    in here. Returns the Binance order id on success, None on any failure
    (logged to Alerts) - never raises into callers (binance_trader.py's
    open_market_order, reconciliation.py, this module's own modify_stop_loss)."""
    try:
        stop_price = round_price(symbol, float(stop_price))
        close_side = "SELL" if str(side).upper() == "BUY" else "BUY"
        # trigger off MARK price (inside place_conditional), not last trade - resistant to a single wick.
        order_id = place_conditional(symbol, close_side, "STOP_MARKET", stop_price)
        status.add_alert("manual", f"LIVE SL PLACED: {symbol} stop={stop_price:g}")
        return order_id
    except Exception as e:
        status.add_alert("manual", f"LIVE SL PLACE FAILED: {symbol} - {e}")
        return None


def modify_stop_loss(symbol, new_sl):
    """Moves (or places, if none exists yet) the resting stop on `symbol`
    to `new_sl` - TIGHTEN-ONLY (see module docstring). Returns the
    resulting order id on success (including the "already tighter, left
    alone" no-op case, which still counts as success - the protective goal
    is already met), or None if there's no open position, the tighten
    check fails to even read the position, or the cancel/re-place itself
    fails."""
    side = _position_side(symbol)
    if side is None:
        status.add_alert("manual", f"LIVE SL MODIFY SKIPPED: {symbol} - no open position found")
        return None
    try:
        new_sl = round_price(symbol, float(new_sl))
    except Exception:
        status.add_alert("manual", f"LIVE SL MODIFY FAILED: {symbol} - invalid new_sl {new_sl!r}")
        return None

    existing = get_active_stop(symbol)
    if existing is not None:
        try:
            old_price = float(existing.get("stopPrice", 0) or 0)
        except Exception:
            old_price = 0.0
        is_long = side == "BUY"
        tightens = (new_sl > old_price) if is_long else (new_sl < old_price)
        if not tightens:
            # Already at/through this level - success by outcome, not by
            # action. Matches paper_trader.trail_sl_to_level()'s "no step
            # backward" rule exactly.
            return existing.get("orderId")
        if not cancel_order(symbol, existing.get("orderId"), algo=bool(existing.get("_algo"))):
            status.add_alert("manual", f"LIVE SL MODIFY FAILED: {symbol} - could not cancel old stop, leaving it in place untouched")
            return None
    return place_stop_loss(symbol, side, new_sl)


def move_to_breakeven(symbol, entry_price):
    """Convenience wrapper - trails the stop to `entry_price`. Reuses
    modify_stop_loss()'s tighten-only guard as-is, so calling this after
    price already ran further (and the stop already got trailed past
    entry some other way) is a safe no-op, not a step backward."""
    return modify_stop_loss(symbol, entry_price)


def set_target_tp(symbol, side, price):
    """Sets/replaces the resting take-profit order on `symbol`. `side` is
    the position's own side; pass None to have it auto-detected from the
    live position (kept as an explicit param so a caller that already has
    it, e.g. ExecutionRouter, doesn't pay for an extra lookup). `price`
    is the actual level to place - passing None CLEARS the resting TP
    (cancels it, nothing replacing it) so the position runs unmanaged
    again. Returns the new order id, the string "cleared" (for the
    price=None case - truthy, not None, so callers checking `is not None`
    still read this as success), or None on failure."""
    if side is None:
        side = _position_side(symbol)
    if side is None:
        status.add_alert("manual", f"LIVE TP SET SKIPPED: {symbol} - no open position found")
        return None

    existing = get_active_take_profit(symbol)
    if existing is not None:
        if not cancel_order(symbol, existing.get("orderId"), algo=bool(existing.get("_algo"))):
            status.add_alert("manual", f"LIVE TP SET FAILED: {symbol} - could not cancel old target, leaving it in place untouched")
            return None

    if price is None:
        return "cleared"

    try:
        price = round_price(symbol, float(price))
        close_side = "SELL" if str(side).upper() == "BUY" else "BUY"
        order_id = place_conditional(symbol, close_side, "TAKE_PROFIT_MARKET", price)
        status.add_alert("manual", f"LIVE TP SET: {symbol} target={price:g}")
        return order_id
    except Exception as e:
        status.add_alert("manual", f"LIVE TP SET FAILED: {symbol} - {e}")
        return None


def cancel_sl(symbol):
    """Cancels only the resting stop-loss (leaves any take-profit order
    untouched). Returns True if there was nothing to cancel or the cancel
    succeeded, False on failure."""
    existing = get_active_stop(symbol)
    if existing is None:
        return True
    return cancel_order(symbol, existing.get("orderId"), algo=bool(existing.get("_algo")))


def cancel_all_protection(symbol):
    """Cancels BOTH the resting stop-loss and take-profit on `symbol`, if
    present. Used when a position is closed some other way (manual close,
    Close All) so no orphaned conditional order is left resting on a
    symbol that no longer has an open position. Returns True only if both
    cancellations succeeded (or there was nothing to cancel)."""
    ok_sl = cancel_sl(symbol)
    ok_tp = True
    existing_tp = get_active_take_profit(symbol)
    if existing_tp is not None:
        ok_tp = cancel_order(symbol, existing_tp.get("orderId"), algo=bool(existing_tp.get("_algo")))
    return ok_sl and ok_tp


# ============================================================ PART 2 =====
# LIVE TRADE META PERSISTENCE - now backed by SQLite (WAL), not a
# whole-file JSON dump.
# ---------------------------------------------------------------------
# A live Binance position (see _position_side/get_open_positions) carries
# no memory of "what TP1-4/SL were actually computed for this entry" - the
# exchange only ever tells you current size/entry/mark price, nothing
# about the strategy's own ladder. This store fills that gap: whatever
# computed the real TP1-4/SL for an entry calls save_trade_meta() once,
# and execution_router.py's _resolve_live_level_price() /
# reconciliation.py's boot-up recovery then read the EXACT stored levels
# instead of re-synthesizing an approximation from Settings' flat
# tp_value%/sl_value% every time.
#
# PART 3 (ZERO-LAG EXECUTION ENGINE): the old live_trade_meta.json
# (whole-file rewrite on every save - same crash-unsafety class db.py's
# own docstring describes for the pre-SQLite signal_log.py/positions.json)
# is replaced with one table (`live_trade_meta`) in the SAME sqlite file
# db.py already owns (backend/data/owl.db), opened here via its OWN
# connection (own WAL pragma, own lock) rather than reaching into db.py's
# private _conn - this module stays a self-contained store exactly like
# it always was (see the top-of-file docstring: "does NOT import
# binance_trader.py, execution_router.py, or reconciliation.py"), just on
# a crash-safe backend now. SQLite's WAL mode supports multiple
# connections to one file safely (one writer at a time, serialized by
# sqlite itself; readers never block on a writer) so this coexisting
# with db.py's own connection to the same file is safe.
#
# The row now carries more than the original JSON blob did - `status`
# (OPEN/CLOSED), `sl_order_id`, `breakeven_done`, `mark_price`,
# `unrealized_pnl` - so this same table doubles as the "local database"
# reconciliation.py's boot-up recovery compares against Binance, and the
# continuous guard loop (below, in this same module) uses to know whether
# breakeven has already been actioned for a position. A pre-existing
# live_trade_meta.json (installs from before this round) is imported once
# via _migrate_json_if_needed(), then renamed *.migrated so this never
# re-imports it - same pattern db.py uses for its own positions.json
# upgrade path.
# ---------------------------------------------------------------------
_TRADE_META_LOCK = threading.Lock()
_META_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "owl.db"
)
_LEGACY_JSON_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "live_trade_meta.json"
)
_meta_conn = None  # lazily opened, guarded by _TRADE_META_LOCK - see _meta_db()

_META_COLUMNS = (
    "symbol", "side", "entry", "sl", "tp1", "tp2", "tp3", "tp4",
    "sl_order_id", "breakeven_done", "status", "mark_price", "unrealized_pnl",
    "saved_ts", "updated_ts", "closed_ts",
)


def _meta_db_locked():
    """Caller must already hold _TRADE_META_LOCK. Opens (once per process)
    this module's own sqlite3 connection to backend/data/owl.db, turns on
    WAL + NORMAL sync (same pragmas db.py uses), creates the table if
    missing, and one-time-migrates the legacy JSON file if present. Safe
    to call every time - after the first call it's just returning the
    already-open connection."""
    global _meta_conn
    if _meta_conn is not None:
        return _meta_conn
    os.makedirs(os.path.dirname(_META_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_META_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS live_trade_meta (
            symbol TEXT PRIMARY KEY,
            side TEXT,
            entry REAL,
            sl REAL,
            tp1 REAL, tp2 REAL, tp3 REAL, tp4 REAL,
            sl_order_id TEXT,
            breakeven_done INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            mark_price REAL,
            unrealized_pnl REAL,
            saved_ts REAL,
            updated_ts REAL,
            closed_ts REAL
        )
        """
    )
    conn.commit()
    _meta_conn = conn
    _migrate_json_if_needed_locked()
    return _meta_conn


def _migrate_json_if_needed_locked():
    """Caller must already hold _TRADE_META_LOCK and _meta_conn must
    already be open. One-time upgrade: if the table is still empty AND
    the old live_trade_meta.json exists, import every entry it has as an
    OPEN row (breakeven_done/sl_order_id unknown from the old format, so
    default 0/NULL - the very next guard-loop tick simply re-verifies the
    resting stop from scratch, which is always safe), then rename the old
    file to *.migrated so this never runs again. Never raises - a corrupt
    or unreadable old file just means nothing to migrate, not a startup
    failure."""
    try:
        row = _meta_conn.execute("SELECT COUNT(*) FROM live_trade_meta").fetchone()
        if row and row[0]:
            return  # already has rows - either migrated before, or a live entry already exists
        if not os.path.exists(_LEGACY_JSON_PATH):
            return
        with open(_LEGACY_JSON_PATH, "r", encoding="utf-8") as f:
            legacy = json.load(f)
        if not isinstance(legacy, dict) or not legacy:
            os.rename(_LEGACY_JSON_PATH, _LEGACY_JSON_PATH + ".migrated")
            return
        now = time.time()
        for sym, rec in legacy.items():
            if not isinstance(rec, dict):
                continue
            _meta_conn.execute(
                """
                INSERT OR IGNORE INTO live_trade_meta
                    (symbol, side, entry, sl, tp1, tp2, tp3, tp4,
                     sl_order_id, breakeven_done, status, mark_price, unrealized_pnl,
                     saved_ts, updated_ts, closed_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, 'OPEN', NULL, NULL, ?, ?, NULL)
                """,
                (
                    str(sym), rec.get("side"), rec.get("entry"), rec.get("sl"),
                    rec.get("tp1"), rec.get("tp2"), rec.get("tp3"), rec.get("tp4"),
                    rec.get("saved_ts", now), now,
                ),
            )
        _meta_conn.commit()
        os.rename(_LEGACY_JSON_PATH, _LEGACY_JSON_PATH + ".migrated")
        status.add_alert("sync", f"LIVE TRADE META: migrated {len(legacy)} entries from live_trade_meta.json to SQLite (owl.db)")
    except Exception as e:
        status.add_alert("error", f"LIVE TRADE META: legacy JSON migration failed (continuing on SQLite only) - {e}")


def _row_to_dict(row):
    if row is None:
        return None
    d = dict(zip(_META_COLUMNS, row))
    d["breakeven_done"] = int(d.get("breakeven_done") or 0)   # ladder step 0..3 (truthy = at least breakeven)
    return d


_SELECT_COLS = ", ".join(_META_COLUMNS)


def save_trade_meta(symbol, side, entry, sl, tp1=None, tp2=None, tp3=None, tp4=None, sl_order_id=None):
    """Persists the exact computed levels for a FRESH live entry on
    `symbol`, overwriting any previous meta for the same symbol -
    resets breakeven_done to 0 and status to OPEN, since this call means
    a brand-new position was just opened (see app.py's _live_open() call
    site). Thread-safe. Returns True on success, False if the write
    itself failed (already alerted) - never raises into the caller (an
    open/trade flow must never fail just because this side-store
    couldn't be written)."""
    if not symbol:
        return False
    now = time.time()
    try:
        with _TRADE_META_LOCK:
            db = _meta_db_locked()
            db.execute(
                """
                INSERT INTO live_trade_meta
                    (symbol, side, entry, sl, tp1, tp2, tp3, tp4,
                     sl_order_id, breakeven_done, status, mark_price, unrealized_pnl,
                     saved_ts, updated_ts, closed_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'OPEN', NULL, NULL, ?, ?, NULL)
                ON CONFLICT(symbol) DO UPDATE SET
                    side=excluded.side, entry=excluded.entry, sl=excluded.sl,
                    tp1=excluded.tp1, tp2=excluded.tp2, tp3=excluded.tp3, tp4=excluded.tp4,
                    sl_order_id=excluded.sl_order_id, breakeven_done=0, status='OPEN',
                    mark_price=NULL, unrealized_pnl=NULL,
                    saved_ts=excluded.saved_ts, updated_ts=excluded.updated_ts, closed_ts=NULL
                """,
                (str(symbol), side, entry, sl, tp1, tp2, tp3, tp4, sl_order_id, now, now),
            )
            db.commit()
        return True
    except Exception as e:
        status.add_alert("error", f"LIVE TRADE META: could not save {symbol} - {e}")
        return False


def get_trade_meta(symbol):
    """Returns the stored meta dict for `symbol` (any status), or None if
    nothing is stored (or the store can't be read) - callers must treat
    None as "fall back to the percentage-based synthesis", not as an
    error."""
    if not symbol:
        return None
    try:
        with _TRADE_META_LOCK:
            db = _meta_db_locked()
            row = db.execute(
                f"SELECT {_SELECT_COLS} FROM live_trade_meta WHERE symbol = ?", (str(symbol),)
            ).fetchone()
        return _row_to_dict(row)
    except Exception as e:
        status.add_alert("error", f"LIVE TRADE META: could not read {symbol} - {e}")
        return None


def get_all_trade_meta():
    """Every stored row (any status), as a list of dicts - the "local
    SQLite positions" side of reconciliation.py's boot-up compare-against-
    Binance pass. Returns [] on any failure."""
    try:
        with _TRADE_META_LOCK:
            db = _meta_db_locked()
            rows = db.execute(f"SELECT {_SELECT_COLS} FROM live_trade_meta").fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        status.add_alert("error", f"LIVE TRADE META: could not list entries - {e}")
        return []


def get_open_trade_meta_symbols():
    """Symbols whose LOCAL SQLite record still says status='OPEN' - what
    reconciliation.py expects to still be open on Binance. Returns an
    empty set (never raises) if the store can't be read."""
    try:
        with _TRADE_META_LOCK:
            db = _meta_db_locked()
            rows = db.execute("SELECT symbol FROM live_trade_meta WHERE status = 'OPEN'").fetchall()
        return {r[0] for r in rows}
    except Exception as e:
        status.add_alert("error", f"LIVE TRADE META: could not list open symbols - {e}")
        return set()


def get_all_trade_meta_symbols():
    """ALL symbols currently holding stored meta, regardless of status -
    kept for backward compatibility with any existing caller that wants
    the full symbol set rather than just the OPEN ones (see
    get_open_trade_meta_symbols() for that). Returns an empty set (never
    raises) if the store can't be read."""
    try:
        with _TRADE_META_LOCK:
            db = _meta_db_locked()
            rows = db.execute("SELECT symbol FROM live_trade_meta").fetchall()
        return {r[0] for r in rows}
    except Exception as e:
        status.add_alert("error", f"LIVE TRADE META: could not list all symbols - {e}")
        return set()


def clear_trade_meta(symbol):
    """HARD-deletes the stored row for `symbol`, if any. Returns True
    whether or not there was anything to remove - only False on an actual
    write failure (already alerted). Prefer mark_trade_closed() for the
    normal "this position closed" case (keeps history for the audit
    trail); this is for genuinely forgetting a symbol (e.g. a manual
    cleanup)."""
    if not symbol:
        return True
    try:
        with _TRADE_META_LOCK:
            db = _meta_db_locked()
            db.execute("DELETE FROM live_trade_meta WHERE symbol = ?", (str(symbol),))
            db.commit()
        return True
    except Exception as e:
        status.add_alert("error", f"LIVE TRADE META: could not clear {symbol} - {e}")
        return False


def mark_trade_closed(symbol):
    """Marks the local SQLite record for `symbol` CLOSED (status='CLOSED',
    closed_ts=now) WITHOUT deleting the row - this is what boot-up
    reconciliation calls the instant Binance no longer reports an open
    position for a symbol this store still thinks is OPEN (e.g. the trade
    closed while the backend was offline). History stays queryable; the
    row simply stops counting as "should be open" for every future
    reconcile/guard pass. Idempotent - closing an already-closed (or
    never-seen) symbol is a harmless no-op. Returns True on success or
    "nothing to do", False only on an actual write failure."""
    if not symbol:
        return True
    try:
        with _TRADE_META_LOCK:
            db = _meta_db_locked()
            db.execute(
                "UPDATE live_trade_meta SET status='CLOSED', closed_ts=? WHERE symbol=? AND status != 'CLOSED'",
                (time.time(), str(symbol)),
            )
            db.commit()
        return True
    except Exception as e:
        status.add_alert("error", f"LIVE TRADE META: could not mark {symbol} closed - {e}")
        return False


def restore_or_update_open_meta(symbol, side, entry=None, sl=None, tp1=None, tp2=None, tp3=None, tp4=None,
                                 mark_price=None, unrealized_pnl=None):
    """Boot-up/continuous-guard primitive: makes sure `symbol` has an OPEN
    row with whatever fields are provided, WITHOUT resetting
    breakeven_done/sl_order_id the way save_trade_meta() (a brand-new
    entry) deliberately does. Used for two cases:
      1. Binance shows an open position reconciliation/the guard loop
         already has SOME local meta for (row exists) - only the given
         fields (mark_price/unrealized_pnl during a guard tick, or
         tp1-4/sl during a boot-up "restore the ladder" pass) are
         updated; status is force-set back to OPEN (covers the position
         having been marked CLOSED by an earlier pass and then reopening
         on the same symbol) and breakeven_done/sl_order_id are left
         exactly as they were.
      2. Binance shows an open position with NO local meta at all (fresh
         install, or meta lost some other way) - inserts a brand-new OPEN
         row with breakeven_done=0/sl_order_id=NULL, same as a fresh
         save_trade_meta() would, since there is genuinely no prior state
         to preserve.
    Only non-None arguments overwrite existing values on an UPDATE (a
    guard tick calling this with only mark_price/unrealized_pnl must
    never blank out an already-stored tp1-4/sl). Returns True on
    success, False on any write failure (already alerted)."""
    if not symbol:
        return False
    now = time.time()
    try:
        with _TRADE_META_LOCK:
            db = _meta_db_locked()
            existing = db.execute("SELECT symbol FROM live_trade_meta WHERE symbol=?", (str(symbol),)).fetchone()
            if existing is None:
                db.execute(
                    """
                    INSERT INTO live_trade_meta
                        (symbol, side, entry, sl, tp1, tp2, tp3, tp4,
                         sl_order_id, breakeven_done, status, mark_price, unrealized_pnl,
                         saved_ts, updated_ts, closed_ts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, 'OPEN', ?, ?, ?, ?, NULL)
                    """,
                    (str(symbol), side, entry, sl, tp1, tp2, tp3, tp4, mark_price, unrealized_pnl, now, now),
                )
            else:
                sets, vals = ["status='OPEN'", "updated_ts=?"], [now]
                for col, val in (("side", side), ("entry", entry), ("sl", sl), ("tp1", tp1),
                                  ("tp2", tp2), ("tp3", tp3), ("tp4", tp4),
                                  ("mark_price", mark_price), ("unrealized_pnl", unrealized_pnl)):
                    if val is not None:
                        sets.append(f"{col}=?")
                        vals.append(val)
                vals.append(str(symbol))
                db.execute(f"UPDATE live_trade_meta SET {', '.join(sets)} WHERE symbol=?", vals)
            db.commit()
        return True
    except Exception as e:
        status.add_alert("error", f"LIVE TRADE META: could not restore/update {symbol} - {e}")
        return False


def update_trade_progress(symbol, mark_price=None, unrealized_pnl=None):
    """Lightweight wrapper around restore_or_update_open_meta() for the
    continuous guard loop's per-tick "sync current mark price/uPnL into
    SQLite" job - never touches side/entry/sl/tp*, and only ever called
    for a symbol already known to be open (a guard tick that finds no
    local row for an open Binance position calls restore_or_update_open_meta
    directly instead, with the fuller field set)."""
    return restore_or_update_open_meta(symbol, side=None, mark_price=mark_price, unrealized_pnl=unrealized_pnl)


def set_sl_order_id(symbol, order_id):
    """Records the exchange order id of the currently-resting protective
    stop for `symbol`, so the guard loop's "is a physical stop still
    there" check has something concrete to reconcile against (in addition
    to the live get_open_algo_orders() read, which is always the actual
    source of truth - this is bookkeeping/observability, not itself relied
    on for correctness). Returns True/False, never raises."""
    if not symbol:
        return False
    try:
        with _TRADE_META_LOCK:
            db = _meta_db_locked()
            db.execute(
                "UPDATE live_trade_meta SET sl_order_id=?, updated_ts=? WHERE symbol=?",
                (order_id, time.time(), str(symbol)),
            )
            db.commit()
        return True
    except Exception as e:
        status.add_alert("error", f"LIVE TRADE META: could not set sl_order_id for {symbol} - {e}")
        return False


def set_breakeven_done(symbol, done=True):
    """Flags (or un-flags) `symbol` as having already had its stop moved
    to breakeven - the guard loop checks is_breakeven_done() before ever
    attempting a TP1 -> breakeven move again, so a position doesn't get
    its stop cancel+replaced on every single 3-4s tick once it's already
    at breakeven. Returns True/False, never raises."""
    if not symbol:
        return False
    try:
        with _TRADE_META_LOCK:
            db = _meta_db_locked()
            db.execute(
                "UPDATE live_trade_meta SET breakeven_done=?, updated_ts=? WHERE symbol=?",
                (1 if done else 0, time.time(), str(symbol)),
            )
            db.commit()
        return True
    except Exception as e:
        status.add_alert("error", f"LIVE TRADE META: could not set breakeven_done for {symbol} - {e}")
        return False


def get_ladder_step(symbol):
    """SL ladder step already applied to `symbol` (0 = none, 1 = SL at entry, 2 = SL at TP1,
    3 = SL at TP2). Stored in the existing breakeven_done column (it used to hold only 0/1, and
    an old '1' simply means step 1 was done), so no database change is needed."""
    meta = get_trade_meta(symbol)
    try:
        return int((meta or {}).get("breakeven_done") or 0)
    except (TypeError, ValueError):
        return 1 if (meta or {}).get("breakeven_done") else 0


def set_ladder_step(symbol, step):
    """Saves the ladder step (see get_ladder_step). Returns True/False, never raises."""
    if not symbol:
        return False
    try:
        with _TRADE_META_LOCK:
            db = _meta_db_locked()
            db.execute(
                "UPDATE live_trade_meta SET breakeven_done=?, updated_ts=? WHERE symbol=?",
                (int(step), time.time(), str(symbol)),
            )
            db.commit()
        return True
    except Exception as e:
        status.add_alert("error", f"LIVE TRADE META: could not set ladder step for {symbol} - {e}")
        return False


def _ladder_target(mode, reached, entry, tps):
    """SL price for the highest TP level touched (1..3), or None. Same table as paper_trader's
    trail modes: step1 TP1->entry, TP2->TP1, TP3->TP2 ; step2 TP2->entry, TP3->TP1 ; off TP1->entry."""
    if mode == "step1":
        return {1: entry, 2: tps.get(1), 3: tps.get(2)}.get(reached)
    if mode == "step2":
        return {2: entry, 3: tps.get(1)}.get(reached)
    return entry if reached >= 1 else None


_tp_checked = {}   # (symbol, entry) -> 0 once TP4 is confirmed resting, else time of the last try (retry after 30s)


def is_breakeven_done(symbol):
    """True only if this symbol's stored meta explicitly says
    breakeven_done - False for "no meta at all" as well as "meta says
    not done yet", so a position with no stored TP1 (nothing to trigger
    breakeven off) is never mistaken for one already at breakeven."""
    meta = get_trade_meta(symbol)
    return bool(meta and meta.get("breakeven_done"))


# ============================================================ PART 3 =====
# CONTINUOUS NATIVE SL/TP GUARD LOOP
# ---------------------------------------------------------------------
# Runs independently of reconciliation.py's (heavier, startup/reconnect-
# triggered) reconcile pass. This loop's whole job, every GUARD_INTERVAL_SEC
# (~3-4s, per spec):
#   1. Every open Binance position must have a physically-resting
#      STOP_MARKET - if get_open_algo_orders() shows none, re-place one
#      immediately (stored meta SL first, emergency %% fallback otherwise -
#      same precedence reconciliation.py already uses for orphans).
#   2. TP1 cross detection: once mark price has reached/passed a
#      position's stored tp1, cancel the existing stop and re-plant it at
#      the exact entry price (binance_trader.cancel_and_replace_sl) -
#      "Guaranteed Risk-Free Auto Breakeven" - exactly once per position
#      (is_breakeven_done() guards against repeating this every tick).
#   3. Orphan purge: any symbol this store still has status='OPEN' for,
#      that Binance no longer reports a position for, gets marked CLOSED
#      here too (belt-and-suspenders with reconciliation.py's own boot-up
#      pass - the guard loop runs continuously, so a position that closes
#      mid-session is caught within one tick instead of waiting for the
#      next restart/reconnect) and every pending order left on that symbol
#      is purged via cancel_all_protection() so nothing orphaned survives.
#
# binance_trader is imported LAZILY (inside guard_tick(), not at module
# level) because binance_trader.py itself imports this module at load
# time (for open_market_order()'s protective-stop placement) - a
# top-of-file `from . import binance_trader` here would be a circular
# import. This is the same lazy-import pattern market_ws.py already uses
# for its own exchange.py/binance_client.py dependencies.
# ---------------------------------------------------------------------
GUARD_INTERVAL_SEC = 3.5
_guard_started = False
_guard_stop_event = None


def _binance_active():
    return settings_store.get("active_exchange", "binance") == "binance"


def _emergency_sl_price(entry_price, side):
    pct = float(settings_store.get("live_emergency_sl_pct", 2.0) or 2.0)
    if str(side).upper() == "BUY":
        return entry_price * (1 - pct / 100.0)
    return entry_price * (1 + pct / 100.0)


def guard_tick(trigger="loop"):
    """One pass of the continuous guard - safe to call directly (e.g. from
    a test, or from api_server.py as a manual "run one guard pass now"
    endpoint) as well as from the background loop below. Honest no-op
    (returns a `skipped` result) if live trading is off or Binance isn't
    the active exchange, mirroring reconciliation.py's own skip shape so
    a UI reading either result doesn't need to branch on which one it
    got. Never raises - every per-symbol step is individually wrapped so
    one bad symbol can never stop the rest of the tick from running."""
    from . import binance_trader  # lazy - see module-level note above

    result = {"ok": True, "trigger": trigger, "checked": 0, "sl_replaced": 0,
              "breakeven_moved": 0, "closed": 0, "failed": 0, "ts": time.time()}
    if not settings_store.get("live_trading_enabled", False):
        result.update(skipped=True, reason="Live trading is OFF")
        status.set_unprotected_positions([])
        return result
    if not _binance_active():
        result.update(skipped=True, reason="KuCoin is the active exchange, not Binance")
        status.set_unprotected_positions([])
        return result

    try:
        positions = binance_trader.get_open_positions()
    except Exception as e:
        status.add_alert("error", f"GUARD TICK FAILED: could not fetch open Binance positions - {e}")
        result.update(ok=False, error=str(e))
        # Don't touch unprotected_positions here - this is a data-fetch
        # failure, not proof that positions are actually unprotected; the
        # last known-good list stays visible rather than being wiped or
        # guessed at.
        return result

    open_symbols = set()
    unprotected = []  # DIAGNOSTICS CONTRACT: full current list, published below - see status.set_unprotected_positions()
    for pos in positions:
        symbol = pos.get("symbol")
        if not symbol:
            continue
        open_symbols.add(symbol)
        try:
            from . import live_recorder
            live_recorder.track_tick(pos)   # MFE/MAE + real margin for the AI record
        except Exception:
            pass
        side = pos.get("action")
        entry = pos.get("entry_price")
        mark_price = pos.get("ltp")
        unrealized_pnl = pos.get("pnl_usdt")
        result["checked"] += 1
        try:
            meta = get_trade_meta(symbol)

            # ---- 1. physical stop must be resting ----
            existing_stop = get_active_stop(symbol)
            is_protected = existing_stop is not None
            if not is_protected:
                sl_price = None
                if meta and meta.get("sl") not in (None, ""):
                    try:
                        sl_price = float(meta["sl"])
                    except (TypeError, ValueError):
                        sl_price = None
                if sl_price is None and entry:
                    sl_price = _emergency_sl_price(float(entry), side)
                if sl_price is not None:
                    new_id = place_stop_loss(symbol, side, sl_price)
                    if new_id is not None:
                        set_sl_order_id(symbol, new_id)
                        status.add_alert("sync", f"GUARD: {symbol} had NO resting stop - re-placed @ {sl_price:g}")
                        result["sl_replaced"] += 1
                        is_protected = True
                    else:
                        result["failed"] += 1
                else:
                    # REAL GAP FIX: previously this branch (no stored meta
                    # AND no entry price to derive an emergency SL from) did
                    # nothing at all - not even a failed-count bump or an
                    # alert - so a position could sit completely unprotected
                    # indefinitely without a single visible signal anywhere.
                    # Now it's counted as a guard failure AND surfaced via
                    # the unprotected_positions telemetry list below, so the
                    # DiagnosticsCard's red warning badge actually catches
                    # this case instead of it being silently invisible.
                    result["failed"] += 1
                    status.add_alert(
                        "error",
                        f"GUARD: {symbol} has NO resting stop and no SL price could be "
                        f"determined (no stored meta, no entry price) - position is UNPROTECTED",
                    )
            if not is_protected:
                unprotected.append({
                    "symbol": symbol,
                    "side": side,
                    "entry": entry,
                    "mark_price": mark_price,
                    "detected_ts": time.time(),
                })

            # ---- 2. SL ladder: TP1 -> entry, TP2 -> SL at TP1, TP3 -> SL at TP2 (TP4 = full booking) ----
            if meta and entry and mark_price:
                try:
                    mode = str(settings_store.get("trail_mode", "step1") or "step1").strip().lower()
                    buy = str(side).upper() == "BUY"
                    mp = float(mark_price)
                    tps = {}
                    for k in (1, 2, 3):
                        if meta.get("tp%d" % k) not in (None, ""):
                            tps[k] = float(meta["tp%d" % k])
                    reached = 0
                    for k in (1, 2, 3):
                        if k in tps and ((mp >= tps[k]) if buy else (mp <= tps[k])):
                            reached = k
                    step = get_ladder_step(symbol)
                    if reached > step:
                        target = _ladder_target(mode, reached, float(entry), tps)
                        if target is not None:
                            new_sl_id = binance_trader.cancel_and_replace_sl(symbol, float(target))
                            if new_sl_id is not None:
                                set_sl_order_id(symbol, new_sl_id)
                                set_ladder_step(symbol, reached)
                                status.add_alert(
                                    "sync",
                                    f"GUARD: {symbol} TP{reached} reached - stop moved to {float(target):g}",
                                    kind="breakeven",
                                )
                                result["breakeven_moved"] += 1
                            else:
                                result["failed"] += 1
                        else:
                            set_ladder_step(symbol, reached)   # this mode has no move for this level
                except (TypeError, ValueError):
                    pass

            # ---- 2b. TP4 must be resting on the exchange ----
            # Keyed per trade (symbol + entry), so the SAME coin traded again later still gets its TP4.
            # (It used to be keyed by symbol only: the 2nd trade of a coin never got a TP4 order.)
            # A failed placement is retried every 30s instead of being given up until restart.
            if meta and meta.get("tp4") not in (None, ""):
                _k = (symbol, round(float(entry or 0), 8))
                _last = _tp_checked.get(_k)
                if _last != 0 and (_last is None or time.time() - _last > 30):
                    if len(_tp_checked) > 500:
                        _tp_checked.clear()
                    _tp_checked[_k] = time.time()
                    try:
                        if get_active_take_profit(symbol) is not None:
                            _tp_checked[_k] = 0
                        elif set_target_tp(symbol, side, float(meta["tp4"])) is not None:
                            _tp_checked[_k] = 0
                            status.add_alert("sync", f"GUARD: {symbol} TP4 {float(meta['tp4']):g} placed on Binance")
                    except Exception:
                        pass

            # ---- keep local SQLite meta's live snapshot in sync ----
            restore_or_update_open_meta(symbol, side, mark_price=mark_price, unrealized_pnl=unrealized_pnl)
        except Exception as e:
            status.add_alert("error", f"GUARD TICK FAILED for {symbol}: {e}")
            result["failed"] += 1

    # ---- 3. orphan purge: locally-OPEN symbols Binance no longer shows ----
    for symbol in get_open_trade_meta_symbols() - open_symbols:
        try:
            mark_trade_closed(symbol)
            cancel_all_protection(symbol)
            status.add_alert("sync", f"GUARD: {symbol} no longer open on Binance - marked CLOSED, orphan orders purged")
            result["closed"] += 1
        except Exception as e:
            status.add_alert("error", f"GUARD ORPHAN-PURGE FAILED for {symbol}: {e}")
            result["failed"] += 1

    # Record the real P&L of any live trade that has just disappeared from
    # Binance (native SL/TP hit, closed on the exchange app, closed while the
    # backend was busy). live_recorder re-verifies with Binance first, so a
    # failed positions fetch above can never be mistaken for a close.
    try:
        from . import live_recorder
        live_recorder.finalize_missing(open_symbols)
    except Exception:
        pass

    result["ok"] = result["failed"] == 0
    status.update(last_guard_tick=result)
    # Full replace, not append - a symbol fixed this tick (or closed/orphan-
    # purged above) must disappear from here immediately, never linger from
    # a previous tick's snapshot.
    status.set_unprotected_positions(unprotected)
    return result


def _guard_loop_forever(stop_event):
    while not stop_event.is_set():
        try:
            guard_tick(trigger="loop")
        except Exception as e:
            status.add_alert("error", f"GUARD LOOP crashed this tick (continuing) - {e}")
        stop_event.wait(GUARD_INTERVAL_SEC)


def start_guard_loop():
    """Starts the background continuous-guard thread if it isn't already
    running. Safe to call more than once (e.g. from app.py's startup and
    also a manual "restart guard" admin action) - only the first call
    actually starts a thread."""
    global _guard_started, _guard_stop_event
    if _guard_started:
        return
    _guard_started = True
    _guard_stop_event = threading.Event()
    t = threading.Thread(target=_guard_loop_forever, args=(_guard_stop_event,), daemon=True)
    t.start()
