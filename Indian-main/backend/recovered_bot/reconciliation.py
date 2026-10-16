"""recovered_bot/reconciliation.py

PART 2 - RECONCILE & RESTART RECOVERY (Binance USDT-M Futures only).

The exchange itself is always the source of truth for what positions
actually exist - never local state (which can lag or be flat-out wrong
after a Termux/phone crash, an app restart, or a lost connection). This
module's whole job is: query Binance FIRST, then make sure every position
it reports actually has an active protective stop resting on it - never
the other way round (never trust local state and merely "check in" with
Binance).

KuCoin is COMPLETELY EXCLUDED - if `active_exchange` isn't "binance" right
now, every function here is a clean, honest no-op (same "say so rather
than silently do nothing" style as execution_router.py's existing LIVE
reconcile branch).

This module only ever ADDS a missing protective stop. It never touches an
already-protected position's existing stop/TP (that's modify_stop_loss()/
set_target_tp()'s job, called deliberately, not something a background
sync should ever do on its own).

PART 3 - ZERO-LAG EXECUTION ENGINE (BOOT-UP RECONCILIATION AGAINST SQLITE)
---------------------------------------------------------------------------
reconcile_with_binance() is now the primary entry point (reconcile_binance_
positions() below is kept as a thin backward-compatible alias - execution_
router.py's existing `reconciliation.reconcile_binance_positions(trigger=
trigger)` call site is untouched). Compared to the PART 2 version, a full
pass now does THREE things against protection_manager's SQLite-backed
live_trade_meta table (backend/data/owl.db - see protection_manager.py's
own PART 2/3 docstring for why that store moved off JSON), not just the
protective-stop check:

  1. MISSING POSITIONS -> CLOSED: any symbol protection_manager's local
     store still has status='OPEN' for, that Binance's own
     positionRisk/get_open_positions() no longer reports, means the trade
     closed (TP/SL hit, liquidated, manually closed on the Binance app
     itself, whatever) while this backend was offline/crashed/restarting.
     protection_manager.mark_trade_closed() flips it to CLOSED (never
     deleted - history stays queryable) and any pending order still
     resting on that dead symbol is purged via cancel_all_protection() so
     nothing orphaned survives the restart.
  2. ACTIVE POSITIONS -> SYNCED: every symbol Binance DOES report as open
     gets its current mark price / unrealized PnL written into the same
     SQLite row (protection_manager.update_trade_progress /
     restore_or_update_open_meta) and, when there's no local record for it
     at all yet (fresh install, or a position opened by hand directly on
     Binance), a fresh OPEN row is created for it - "restoring" whatever
     TP1-4 IS locally known (nothing, for a symbol with truly no prior
     meta - this module never invents strategy levels it was never given)
     while never touching TP1-4 for a symbol that already had them stored.
  3. PROTECTIVE STOP CHECK (unchanged from PART 2): every open position
     still gets verified/re-armed with a resting STOP_MARKET, preferring
     the exact stored SL over the generic emergency-%-fallback.

This is the (heavier, startup/reconnect-triggered) counterpart to
protection_manager.py's own lightweight CONTINUOUS guard loop (runs every
~3.5s once started) - that loop re-does step 3 and a lighter version of
step 1 constantly while the backend is up; this module's job is
specifically the "process just came back from being dead or disconnected,
rebuild the full picture before doing anything else" pass.
"""
import time

from . import settings_store, status, exchange, binance_trader, protection_manager

DEFAULT_EMERGENCY_SL_PCT = 2.0  # same default/override key as binance_trader.py's
                                  # open_market_order() fallback - one setting governs
                                  # "what's a safe emergency stop" everywhere it's needed.


def _binance_active():
    return exchange.active() == "binance"


def _emergency_sl_price(entry_price, side):
    pct = float(settings_store.get("live_emergency_sl_pct", DEFAULT_EMERGENCY_SL_PCT) or DEFAULT_EMERGENCY_SL_PCT)
    if str(side).upper() == "BUY":
        return entry_price * (1 - pct / 100.0)
    return entry_price * (1 + pct / 100.0)


def _skip_result(trigger, reason):
    result = {"ok": True, "mode": "live", "skipped": True, "reason": reason,
              "trigger": trigger, "checked": 0, "fixed": 0, "failed": 0,
              "closed": 0, "restored": 0, "pruned_meta": 0, "details": [], "ts": time.time()}
    status.update(last_reconcile=result)
    return result


def reconcile_with_binance(trigger="manual"):
    """PART 3 primary entry point - see module docstring. Binance is
    queried FIRST (positions, via binance_trader.get_open_positions(),
    which itself hits /fapi/v2/positionRisk) and is the sole source of
    truth for "what's actually open"; protection_manager's local SQLite
    store (backend/data/owl.db, table live_trade_meta) is then brought
    into agreement with it - never the other way round. Returns a summary
    dict; also written to status.last_reconcile so the Dashboard can show
    it, matching paper_trader.reconcile_all()'s shape closely enough that
    a UI reading `last_reconcile` doesn't need to branch on paper vs
    live. Honest no-op (skipped=True) if live trading is off or Binance
    isn't the active exchange - never raises, never blocks the rest of
    startup."""
    if not settings_store.get("live_trading_enabled", False):
        return _skip_result(trigger, "Live trading is OFF")
    if not _binance_active():
        return _skip_result(trigger, "KuCoin is the active exchange, not Binance - nothing to reconcile here")

    try:
        positions = binance_trader.get_open_positions()
    except Exception as e:
        result = {"ok": False, "mode": "live", "trigger": trigger, "checked": 0, "fixed": 0, "failed": 0,
                   "closed": 0, "restored": 0, "pruned_meta": 0, "details": [],
                   "error": f"Could not fetch open positions: {e}", "ts": time.time()}
        status.update(last_reconcile=result)
        status.add_alert("error", f"RECONCILE FAILED: could not fetch open Binance positions - {e}")
        return result

    active_symbols = [p.get("symbol") for p in positions if p.get("symbol")]
    active_symbol_set = {str(s) for s in active_symbols}

    # PART 2/3 compat: prune any ALREADY-CLOSED stored rows that are stale
    # (belong to a symbol not currently open on Binance) BEFORE step 1
    # below marks anything newly closed this pass - so a row this very
    # call is about to close is never immediately swept away in the same
    # pass it closed in (history survives at least until the NEXT
    # reconcile pass, by which point it's genuinely one cycle stale).
    pruned = prune_stale_trade_meta(active_symbols)

    # ---- STEP 1: local SQLite rows still OPEN, but Binance no longer
    # shows a position for them -> the trade closed while this backend
    # was offline. Mark CLOSED (never deleted) + purge any orphaned
    # pending order left resting on that dead symbol. ----
    details = []
    closed = 0
    try:
        locally_open = protection_manager.get_open_trade_meta_symbols()
    except Exception as e:
        locally_open = set()
        status.add_alert("error", f"RECONCILE: could not read local open positions from SQLite - {e}")

    for symbol in locally_open - active_symbol_set:
        try:
            protection_manager.mark_trade_closed(symbol)
            try:
                protection_manager.cancel_all_protection(symbol)
            except Exception:
                pass  # best-effort - a stale/already-gone order here is not a reconcile failure
            status.add_alert("sync", f"RECONCILE: {symbol} closed while offline - local SQLite marked CLOSED, orphan orders purged")
            details.append({"symbol": symbol, "status": "closed_while_offline"})
            closed += 1
        except Exception as e:
            status.add_alert("error", f"RECONCILE: could not mark {symbol} closed - {e}")
            details.append({"symbol": symbol, "status": "failed", "error": str(e)})

    # Trades that closed while the backend was offline: record their real
    # P&L (live_recorder re-verifies each one with Binance before saving).
    try:
        from . import live_recorder
        live_recorder.finalize_missing(active_symbol_set)
    except Exception:
        pass

    # ---- STEP 2 + 3: every symbol Binance DOES report as open -> sync
    # mark price/uPnL into SQLite, restore/keep whatever TP1-4 is known,
    # and make sure a protective stop is physically resting. ----
    fixed = 0
    restored = 0
    failed = 0
    for pos in positions:
        symbol = pos.get("symbol")
        side = pos.get("action")
        entry = pos.get("entry_price")
        mark_price = pos.get("ltp")
        unrealized_pnl = pos.get("pnl_usdt")
        try:
            meta = protection_manager.get_trade_meta(symbol)
            had_meta = meta is not None and meta.get("status") == "OPEN"

            # Sync live snapshot (mark price/uPnL) into SQLite, and create
            # a fresh OPEN row if this symbol had none at all yet - never
            # overwrites an already-stored tp1-4/sl with None.
            protection_manager.restore_or_update_open_meta(
                symbol, side, entry=entry, mark_price=mark_price, unrealized_pnl=unrealized_pnl,
            )
            if not had_meta:
                status.add_alert("sync", f"RECONCILE: {symbol} is open on Binance with no prior local record - created fresh SQLite entry")
                restored += 1

            existing_stop = protection_manager.get_active_stop(symbol)
            if existing_stop is not None:
                details.append({"symbol": symbol, "status": "protected", "stop_price": existing_stop.get("stopPrice")})
                continue

            # Orphan (no resting stop) - prefer the position's OWN stored
            # SL (protection_manager.save_trade_meta(), see that module)
            # over the generic emergency-%-stop.
            sl_price = None
            sl_source = "emergency"
            if meta and meta.get("sl") not in (None, ""):
                try:
                    sl_price = float(meta["sl"])
                    sl_source = "stored"
                except (TypeError, ValueError):
                    sl_price = None

            if sl_price is None:
                if not entry:
                    details.append({"symbol": symbol, "status": "failed",
                                      "error": "no entry_price available - cannot compute an emergency SL"})
                    failed += 1
                    continue
                sl_price = _emergency_sl_price(float(entry), side)
                sl_source = "emergency"

            order_id = protection_manager.place_stop_loss(symbol, side, sl_price)
            if order_id is not None:
                protection_manager.set_sl_order_id(symbol, order_id)
                label = "stored SL" if sl_source == "stored" else "emergency SL"
                status.add_alert("sync", f"RECONCILE: {symbol} had NO protective stop resting - placed {label} @ {sl_price:g}")
                details.append({"symbol": symbol, "status": "fixed", "stop_price": sl_price, "sl_source": sl_source})
                fixed += 1
            else:
                details.append({"symbol": symbol, "status": "failed", "error": "place_stop_loss() returned None"})
                failed += 1
        except Exception as e:
            status.add_alert("error", f"RECONCILE FAILED for {symbol}: {e}")
            details.append({"symbol": symbol, "status": "failed", "error": str(e)})
            failed += 1

    result = {
        "ok": failed == 0,
        "mode": "live",
        "trigger": trigger,
        "checked": len(positions),
        "fixed": fixed,
        "restored": restored,
        "closed": closed,
        "failed": failed,
        "still_open": len(positions),
        "pruned_meta": pruned,
        "details": details,
        "ts": time.time(),
    }
    status.update(last_reconcile=result)
    return result


def reconcile_binance_positions(trigger="manual"):
    """Backward-compatible alias for reconcile_with_binance() - kept so
    execution_router.py's existing `reconciliation.reconcile_binance_
    positions(trigger=trigger)` call site (its `reconcile()` static
    method's LIVE branch) keeps working completely unchanged."""
    return reconcile_with_binance(trigger)


def prune_stale_trade_meta(active_symbols):
    """Hard-deletes local SQLite live_trade_meta rows for any symbol NOT
    in `active_symbols` AND already CLOSED - pure housekeeping so a
    long-dead CLOSED row can't accumulate forever. `active_symbols` should
    always be a freshly fetched list of currently-open symbols
    (reconcile_with_binance() passes the positions list it just fetched,
    never a cached one) so a position that closed and reopened between
    two reconcile passes is never mistaken for stale. NOTE: this no
    longer prunes OPEN rows just because they're momentarily missing from
    `active_symbols` - reconcile_with_binance()'s STEP 1 above already
    handles "OPEN locally but Binance doesn't show it" by marking CLOSED
    (preserving history), never by deleting; this function only ever
    removes rows that are BOTH stale (not in active_symbols) AND already
    marked CLOSED, so it can never race with step 1's own closing pass.

    Returns the number of rows pruned. Never raises - a failure here is
    logged and treated as "nothing pruned this round", not a reconcile
    failure, since a stale-but-unpruned entry is a much smaller problem
    than a reconcile pass reporting failure over bookkeeping cleanup."""
    try:
        all_rows = protection_manager.get_all_trade_meta()
    except Exception as e:
        status.add_alert("error", f"PRUNE TRADE META FAILED: could not list stored meta - {e}")
        return 0

    active = {str(s) for s in active_symbols}
    pruned = 0
    for row in all_rows:
        symbol = row.get("symbol")
        if not symbol or symbol in active:
            continue
        if row.get("status") != "CLOSED":
            continue  # still OPEN locally - reconcile_with_binance()'s step 1 owns this case, not this function
        try:
            if protection_manager.clear_trade_meta(symbol):
                pruned += 1
        except Exception as e:
            status.add_alert("error", f"PRUNE TRADE META FAILED for {symbol}: {e}")

    if pruned:
        noun = "entry" if pruned == 1 else "entries"
        status.add_alert("sync", f"RECONCILE: pruned {pruned} stale closed live_trade_meta {noun}")
    return pruned


def reconcile_on_startup():
    """Call once, as the very first thing the backend does after its data
    stores are init()'d and BEFORE anything else assumes it knows what's
    open - see app.py's startup sequence. Binance is queried fresh;
    nothing here trusts whatever the local SQLite live_trade_meta table
    remembered from before the restart until it's been checked against
    Binance's own report."""
    status.add_alert("sync", "Startup reconciliation: checking Binance for open positions and protective stops...")
    return reconcile_with_binance(trigger="startup")
