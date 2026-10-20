"""
recovered_bot/execution_router.py

PART 2 - LIVE SL/TP + RECONCILE NOW WIRED (Binance only).

Single choke point for every "act on an open position" call coming out of
api_server.py: close one / close all / close all profit / close all loss /
set target TP / trail SL / move SL to breakeven / cancel SL / reconcile.
Every method below checks settings_store["live_trading_enabled"] FIRST and
sends the action to paper_trader (PAPER) or to the LIVE path (Binance only)
- never both, never neither. Callers never need to branch on mode
themselves.

KUCOIN IS COMPLETELY EXCLUDED FROM LIVE EXECUTION
----------------------------------------------------
Binance Futures (/fapi) is the sole exchange this file's LIVE branches
know how to act on. close_one/close_all/close_all_profit/close_all_loss
still go through exchange.py's existing dispatcher (unchanged - KuCoin's
close_position_market()/get_open_positions() still work exactly as
before, this file isn't removing that). But set_target_tp/trail_sl/
move_sl_breakeven/cancel_sl call `protection_manager` DIRECTLY - bypassing
exchange.py's dispatcher entirely, on purpose: exchange.py has no
modify_sl/set_target_tp/move_sl_to_breakeven pass-throughs (and is out of
scope to add them to this round), and protection_manager.py only ever
talks to Binance. If `active_exchange` is "kucoin" when one of these is
called, it fails loud with KUCOIN_NOT_SUPPORTED_MSG instead of silently
doing nothing or - worse - acting on the wrong exchange.

WHAT LIVE CAN DO NOW
-----------------------
  - close_one / close_all / close_all_profit / close_all_loss
        Unchanged from Part 1 - routed to exchange.close_position_market()
        for every matching live position (works for whichever exchange is
        active; KuCoin's own close path is untouched).

  - set_target_tp / trail_sl / move_sl_breakeven / cancel_sl
        Binance only. Resolves the UI's TP1-4 `level` selection to an
        actual price the same way paper_trader synthesizes TP1/TP2 for a
        percent-mode position (see _resolve_live_level_price below - live
        positions have no per-position strategy SL/TP1-4 stored the way a
        paper trade does), then calls protection_manager's cancel+re-place
        primitives. Every one of these still checks is_live() itself and
        re-reads settings_store fresh, never cached.

  - reconcile
        Binance: delegates to reconciliation.reconcile_binance_positions(),
        which queries positionRisk directly and makes sure every open
        position actually has a resting protective stop - see that
        module's docstring. KuCoin: unchanged honest no-op.
"""
import logging

from . import settings_store, paper_trader, exchange, protection_manager, reconciliation, binance_trader

log = logging.getLogger("execution_router")

KUCOIN_NOT_SUPPORTED_MSG = (
    "Live stop-loss/take-profit management only supports Binance Futures - "
    "KuCoin is excluded from live execution. Switch the active exchange to "
    "Binance in Settings to use this action, or use PAPER mode."
)

# FINAL ROUND: master trading pause/resume toggle.
# --------------------------------------------------------------------
# settings_store["trading_enabled"] - a single ON/OFF switch (Dashboard
# header pill) that pauses NEW order placement (app.py's _open_signal,
# both paper and live) while leaving everything else running exactly as
# before:
#   - market data / LTP polling (market_ws.py, app.py's poll_klines) -
#     NEVER touches this flag, keeps running unconditionally
#   - manual close of an already-open position (ExecutionRouter.close_one/
#     close_all/close_all_profit/close_all_loss) - NEVER gated by this,
#     a paused bot must never trap the user's existing positions
#   - protective SL/TP management (set_target_tp/trail_sl/
#     move_sl_breakeven/cancel_sl/reconcile) - also NEVER gated by this,
#     on purpose: pausing new entries must not leave an already-open
#     position's protective stop unmanaged
#
# Distinct from settings_store["live_trading_enabled"] (is_live() below),
# which only chooses paper vs live ROUTING for whatever orders ARE
# allowed through - the two flags are orthogonal and both are read fresh
# every call, never cached.
DEFAULT_TRADING_ENABLED = True
TRADING_PAUSED_MESSAGE = "Bot execution is PAUSED by master toggle"


def is_trading_enabled() -> bool:
    """True (the default) unless the Dashboard's master toggle has been
    explicitly switched off. Always re-reads settings_store - never cache
    this, same rule as is_live() below, so a tap on the pill takes effect
    on the very next signal, not just the next restart."""
    return bool(settings_store.get("trading_enabled", DEFAULT_TRADING_ENABLED))


def master_paused_response() -> dict:
    """The exact response shape a NEW order blocked by the master toggle
    should return. Returns a fresh dict every call so no caller can ever
    accidentally mutate a shared instance."""
    return {"ok": False, "message": TRADING_PAUSED_MESSAGE}


def is_live() -> bool:
    """Always re-reads settings_store - NEVER cache this across a request.
    The user can flip Live/Paper mid-session (Settings screen) and the very
    next tap on a position card must honour whatever the value is right
    now, not whatever it was when the server started or a websocket loop
    last checked."""
    return bool(settings_store.get("live_trading_enabled", False))


def _find_live_position(identifier):
    """`identifier` is whatever api_server.py received for a live action -
    always the position's symbol (e.g. "BTCUSDT"). Paper trade ids are
    ints from trade_store; live position ids ARE the symbol string - see
    kucoin_trader.py/binance_trader.py get_open_positions(), which sets
    "id": p.get("symbol") since a live position has no local integer id at
    all. Returns the matching live position dict, or None if it's not open
    any more (already closed on the exchange, a race with another client,
    etc.) - callers must treat None as a clean "nothing to do", not as an
    error to raise."""
    symbol = str(identifier)
    for p in exchange.get_open_positions():
        if p.get("symbol") == symbol:
            return p
    return None


def _resolve_live_level_price(pos, level):
    """PART 2: resolves a TP1-4 tap on a live position to an actual price.

    First choice - EXACT stored levels: protection_manager.get_trade_meta()
    for this position's symbol, if present, holds the real computed
    tp1/tp2/tp3/tp4 for this entry (written by whatever opened it - see
    protection_manager.save_trade_meta()). When that meta exists, this now
    supports all four levels, not just 1/2, and returns the precise stored
    price - no approximation.

    Fallback - percentage synthesis: if meta is missing (position opened
    before this round, or the write never happened), this drops back to
    the original behaviour so a live position can NEVER crash a TP/SL tap
    just because its meta wasn't recorded: split Settings' tp_value% into
    two rungs around entry. Only levels 1 and 2 exist this way; 3/4 return
    None (no synthetic equivalent) - callers must treat None as "not
    available", not as an error."""
    symbol = pos.get("symbol")
    if symbol and level in (1, 2, 3, 4):
        meta = protection_manager.get_trade_meta(symbol)
        if meta:
            stored = meta.get(f"tp{level}")
            if stored not in (None, ""):
                try:
                    return float(stored)
                except (TypeError, ValueError):
                    pass  # fall through to synthesis below

    if level not in (1, 2):
        return None
    entry = pos.get("entry_price")
    if not entry:
        return None
    tp_pct = float(settings_store.get("tp_value", 0) or 0)
    if not tp_pct:
        return None
    is_long = pos.get("action") == "BUY"
    direction = 1 if is_long else -1
    frac = 0.5 if level == 1 else 1.0
    return entry * (1 + direction * (tp_pct * frac) / 100.0)


class ExecutionRouter:
    """Stateless - every method re-reads is_live() itself, so callers never
    need to check the mode before calling in. Every method here does its
    own (potentially blocking, REST-calling) work synchronously;
    api_server.py wraps each call in asyncio.to_thread(...), exactly like
    it already did for the paper_trader calls this replaces."""

    # --------------------------------------------------------- master gate --

    @staticmethod
    def is_trading_enabled() -> bool:
        """Thin passthrough to the module-level function above - kept as a
        staticmethod too so callers already holding `ExecutionRouter` (or
        importing it as a class) don't need a second import."""
        return is_trading_enabled()

    @staticmethod
    def master_paused_response() -> dict:
        return master_paused_response()

    # -------------------------------------------------------------- close --

    @staticmethod
    def close_one(identifier):
        """identifier: a paper trade_id (int, or numeric string) in PAPER
        mode, or the position's symbol (str) in LIVE mode. Returns a dict
        that always has "ok" and "mode" keys; paper mode also carries
        paper_trader.close_position_manual()'s existing forced/symbol/error
        fields unchanged, so existing callers of those fields keep working."""
        if is_live():
            pos = _find_live_position(identifier)
            if pos is None:
                return {"ok": False, "mode": "live", "symbol": str(identifier),
                         "error": f"No open live position for {identifier} (already closed?)"}
            order_id = exchange.close_position_market(pos["symbol"], pos["action"])
            # CRASH-GUARD: binance_trader.close_position_market() returns
            # the ALREADY_CLOSED sentinel (not None) when Binance rejected
            # the reduce-only close with -2022 because the position closed
            # out from under us (guard loop / native SL-TP / another
            # client) between our own lookup and the order landing - the
            # desired end state (flat) is already true, so this is
            # reported as an ok, already-closed skip, never as a failure.
            already_closed = order_id == binance_trader.ALREADY_CLOSED_SENTINEL
            ok = order_id is not None
            return {
                "ok": ok,
                "mode": "live",
                "symbol": pos["symbol"],
                "order_id": None if already_closed else order_id,
                "already_closed": already_closed,
                "error": None if ok else "Live close order failed - see Alerts for detail",
            }
        try:
            trade_id = int(identifier)
        except (TypeError, ValueError):
            return {"ok": False, "mode": "paper", "error": f"Invalid paper trade id: {identifier!r}"}
        result = paper_trader.close_position_manual(trade_id)
        result = dict(result) if isinstance(result, dict) else {"ok": bool(result)}
        result.setdefault("mode", "paper")
        return result

    @staticmethod
    def close_all(bot=None):
        """Mirrors paper_trader.close_all_with_detail()'s existing return
        shape (closed_count/failed_count/details) in both modes, so
        api_server.py doesn't need an if/else on the response shape."""
        if is_live():
            result = ExecutionRouter._close_live_positions(exchange.get_open_positions())
            return result
        result = paper_trader.close_all_with_detail(bot)
        return {"mode": "paper", **result}

    @staticmethod
    def close_all_profit(bot=None):
        if is_live():
            positions = [p for p in exchange.get_open_positions() if float(p.get("pnl_usdt", 0) or 0) >= 0]
            result = ExecutionRouter._close_live_positions(positions)
            return {"ok": True, "mode": "live", "closed": result["closed_count"], "details": result["details"]}
        closed = paper_trader.close_all_profit(bot)
        return {"ok": True, "mode": "paper", "closed": closed}

    @staticmethod
    def close_all_loss(bot=None):
        if is_live():
            positions = [p for p in exchange.get_open_positions() if float(p.get("pnl_usdt", 0) or 0) < 0]
            result = ExecutionRouter._close_live_positions(positions)
            return {"ok": True, "mode": "live", "closed": result["closed_count"], "details": result["details"]}
        closed = paper_trader.close_all_loss(bot)
        return {"ok": True, "mode": "paper", "closed": closed}

    @staticmethod
    def _close_live_positions(positions):
        """Shared close-a-batch-of-live-positions loop. One symbol failing
        to close never aborts the rest - same "never just claim success,
        report exactly what happened" philosophy as
        paper_trader.close_all_with_detail() / api_server.py's flatten()."""
        details = []
        for p in positions:
            symbol = p.get("symbol")
            try:
                order_id = exchange.close_position_market(symbol, p.get("action"))
                # CRASH-GUARD: same ALREADY_CLOSED handling as close_one()
                # above - a position that closed out from under this batch
                # (guard loop, native SL/TP, a race with another client)
                # counts as closed (ok=True), never as a failure, so
                # "Close All Profit/Loss" never reports a scary false
                # failure for a position that's already gone.
                already_closed = order_id == binance_trader.ALREADY_CLOSED_SENTINEL
                details.append({
                    "symbol": symbol,
                    "ok": order_id is not None,
                    "order_id": None if already_closed else order_id,
                    "already_closed": already_closed,
                })
            except Exception as e:
                log.error("live close failed for %s: %s", symbol, e)
                details.append({"symbol": symbol, "ok": False, "error": str(e)})
        closed = sum(1 for d in details if d["ok"])
        return {"mode": "live", "closed_count": closed, "failed_count": len(details) - closed, "details": details}

    # ------------------------------------------------------------ SL / TP --
    # LIVE branches below are Binance-only - see module docstring's
    # "KUCOIN IS COMPLETELY EXCLUDED" section.

    @staticmethod
    def set_target_tp(identifier, level):
        if is_live():
            if exchange.active() != "binance":
                return {"ok": False, "mode": "live", "error": KUCOIN_NOT_SUPPORTED_MSG}
            pos = _find_live_position(identifier)
            if pos is None:
                return {"ok": False, "mode": "live", "error": f"No open live position for {identifier}"}
            price = None
            if level is not None:
                price = _resolve_live_level_price(pos, level)
                if price is None:
                    return {"ok": False, "mode": "live",
                             "error": f"TP{level} isn't available for this live position yet"}
            order_id = protection_manager.set_target_tp(pos["symbol"], pos["action"], price)
            return {"ok": order_id is not None, "mode": "live", "order_id": order_id}
        try:
            trade_id = int(identifier)
        except (TypeError, ValueError):
            return {"ok": False, "mode": "paper", "error": f"Invalid paper trade id: {identifier!r}"}
        paper_trader.set_target_tp(trade_id, level)
        return {"ok": True, "mode": "paper"}

    @staticmethod
    def trail_sl(identifier, level):
        if is_live():
            if exchange.active() != "binance":
                return {"ok": False, "mode": "live", "error": KUCOIN_NOT_SUPPORTED_MSG}
            pos = _find_live_position(identifier)
            if pos is None:
                return {"ok": False, "mode": "live", "error": f"No open live position for {identifier}"}
            price = _resolve_live_level_price(pos, level)
            if price is None:
                return {"ok": False, "mode": "live",
                         "error": f"TP{level} isn't available for this live position yet"}
            # protection_manager.modify_stop_loss() enforces the
            # tighten-only guard itself - refuses to loosen an existing
            # resting stop, same rule paper_trader.trail_sl_to_level()
            # already enforces locally.
            order_id = protection_manager.modify_stop_loss(pos["symbol"], price)
            return {"ok": order_id is not None, "mode": "live", "order_id": order_id}
        try:
            trade_id = int(identifier)
        except (TypeError, ValueError):
            return {"ok": False, "mode": "paper", "error": f"Invalid paper trade id: {identifier!r}"}
        moved = paper_trader.trail_sl_to_level(trade_id, level)
        return {"ok": moved, "mode": "paper"}

    @staticmethod
    def move_sl_breakeven(identifier):
        if is_live():
            if exchange.active() != "binance":
                return {"ok": False, "mode": "live", "error": KUCOIN_NOT_SUPPORTED_MSG}
            pos = _find_live_position(identifier)
            if pos is None:
                return {"ok": False, "mode": "live", "error": f"No open live position for {identifier}"}
            order_id = protection_manager.move_to_breakeven(pos["symbol"], pos.get("entry_price"))
            return {"ok": order_id is not None, "mode": "live", "order_id": order_id}
        try:
            trade_id = int(identifier)
        except (TypeError, ValueError):
            return {"ok": False, "mode": "paper", "error": f"Invalid paper trade id: {identifier!r}"}
        moved = paper_trader.move_sl_to_breakeven(trade_id)
        return {"ok": moved, "mode": "paper"}

    @staticmethod
    def cancel_sl(identifier):
        """Not called by any endpoint yet (no api_server.py route exists
        for it this round - that file is out of scope) but wired here so
        adding one later is a one-line addition, same as every other
        method in this class."""
        if is_live():
            if exchange.active() != "binance":
                return {"ok": False, "mode": "live", "error": KUCOIN_NOT_SUPPORTED_MSG}
            pos = _find_live_position(identifier)
            if pos is None:
                return {"ok": False, "mode": "live", "error": f"No open live position for {identifier}"}
            ok = protection_manager.cancel_sl(pos["symbol"])
            return {"ok": ok, "mode": "live"}
        return {"ok": False, "mode": "paper", "error": "cancel_sl has no paper-mode equivalent"}

    # ---------------------------------------------------------- reconcile --

    @staticmethod
    def reconcile(trigger="reconnect"):
        if is_live():
            result = reconciliation.reconcile_binance_positions(trigger=trigger)
            # KuCoin (or anything reconciliation.py reports as skipped) keeps
            # the same honest-no-op shape Part 1 already had.
            if result.get("skipped"):
                return {"ok": True, "mode": "live", "checked": 0, "closed": 0, "failed": 0, "still_open": 0,
                         "note": result.get("reason")}
            return result
        result = paper_trader.reconcile_all(trigger, True)
        return {"ok": True, "mode": "paper", **result}
