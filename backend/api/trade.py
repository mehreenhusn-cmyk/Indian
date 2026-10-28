"""api/trade.py - close / flatten / TP / SL / reconcile routes (the money paths), moved out of api_server.py (NEXT-6d).

close_one, close_all, flatten, preview_close_all, close_all_profit, close_all_loss, set_target_tp, trail_sl,
move_sl_breakeven, reconcile. Same code, same paths, same order, same checks (token, ExecutionRouter, kill switch order).
api_server.py includes this router at the exact place the routes used to be.
Not moved on purpose: /api/ai/live/panic (AI routes, part 6i).
"""
import asyncio

from fastapi import APIRouter, Depends

from recovered_bot import settings_store, paper_trader, status, exchange
from recovered_bot.execution_router import ExecutionRouter


def make_router(require_api_token, bot_arg):
    """require_api_token and bot_arg(bot, default) are api_server's own functions (passed in, not copied)."""
    r = APIRouter()
    _bot_arg = bot_arg

    @r.post("/api/close/{trade_id}")
    async def close_one(trade_id: str, _auth=Depends(require_api_token)):
        # trade_id is a str, not int: in PAPER mode it's still the numeric
        # trade_store id (ExecutionRouter parses it to int internally), but in
        # LIVE mode there is no local integer id at all - binance_trader.py's
        # get_open_positions() sets a live position's "id" to its symbol
        # (e.g. "BTCUSDT"). An `int` type hint here would 422 on
        # every live close - ExecutionRouter.close_one() is what actually
        # branches PAPER vs LIVE and interprets the identifier accordingly.
        #
        # Runs in a thread because both the paper (blocking REST price fetch)
        # and live (blocking exchange REST call) paths can block - never stall
        # the event loop the WebSocket also runs on (a stalled loop is what
        # made uvicorn's WebSocket keepalive ping time out -> code 1011).
        # Returns the full dict (ok/mode/forced/symbol/error) - not just a bare
        # bool - so the app can tell the user WHY a close failed, or that it
        # succeeded via a force-close fallback (dead price feed) instead of a
        # normal exit.
        result = await asyncio.to_thread(ExecutionRouter.close_one, trade_id)
        return result


    @r.post("/api/close_all")
    async def close_all(bot: str = "", _auth=Depends(require_api_token)):
        """Flatten All (PAPER or LIVE, via ExecutionRouter - see that module's
        docstring for why every action needs to check live_trading_enabled
        instead of always hitting paper_trader). PAPER force-closes any symbol
        with a dead/thin price feed instead of silently skipping it (see
        paper_trader.py); LIVE closes every real open position on the active
        exchange. Returns exactly what happened either way, so the app's toast
        always matches reality instead of always claiming success."""
        result = await asyncio.to_thread(ExecutionRouter.close_all, _bot_arg(bot, None))
        return {"ok": result["failed_count"] == 0, **result}


    @r.post("/api/flatten")
    async def flatten(_auth=Depends(require_api_token)):
        """EMERGENCY PANIC KILL SWITCH - deliberately kept distinct from
        /api/close_all above and from the plain "turn live trading off" toggle
        in Settings. Those two only ever act within the CURRENTLY active mode
        (close_all via ExecutionRouter now correctly does that - see that
        module's docstring for the bug this fixed) and neither one touches the
        live_trading_enabled switch itself. /api/flatten does both, unconditionally:

          1) Close every REAL exchange position first, while live_trading_enabled
             is still True. Order matters here: binance_trader.py's
             close_position_market() refuses to place a
             closing order at all once live_trading_enabled is False (its own
             master-switch guard) - flipping the switch off before this step
             would make every live close silently no-op.
          2) Close every PAPER position too (close_all_with_detail - same call
             ExecutionRouter.close_all() uses in PAPER mode) - a harmless no-op
             if paper is empty, which it normally is whenever live is the
             active mode.
          3) THEN set live_trading_enabled = False, so no new entries can open
             on EITHER engine after this call returns - the "automatically sets
             live_trading: false" half of the panic switch, which close_all/the
             Settings toggle deliberately do NOT do on their own.

        Returns enough detail for the app to show exactly what happened on each
        side, same "never just claim success" philosophy as close_all_with_detail."""
        was_live = settings_store.get("live_trading_enabled", False)

        live_details = []
        if was_live:
            try:
                live_positions = await asyncio.to_thread(exchange.get_open_positions)
            except Exception as e:
                live_positions = []
                status.add_alert("manual", f"PANIC FLATTEN: could not list live positions - {e}")
            for p in live_positions:
                symbol = p.get("symbol")
                action = p.get("action")
                try:
                    order_id = await asyncio.to_thread(exchange.close_position_market, symbol, action)
                    live_details.append({"symbol": symbol, "ok": order_id is not None, "order_id": order_id})
                except Exception as e:
                    live_details.append({"symbol": symbol, "ok": False, "error": str(e)})

        paper_result = await asyncio.to_thread(paper_trader.close_all_with_detail)

        # Master kill switch - stop any further auto-entries (paper OR live)
        # from this point on, regardless of which mode was actually active
        # above. Deliberately done LAST - see the docstring ordering note.
        settings_store.update(live_trading_enabled=False)
        status.add_alert("manual", "PANIC FLATTEN triggered - all positions closed, live trading disabled")

        live_closed = sum(1 for d in live_details if d.get("ok"))
        live_failed = len(live_details) - live_closed
        return {
            "ok": live_failed == 0 and paper_result["failed_count"] == 0,
            "was_live": was_live,
            "live_closed_count": live_closed,
            "live_failed_count": live_failed,
            "live_details": live_details,
            "paper_closed_count": paper_result["closed_count"],
            "paper_failed_count": paper_result["failed_count"],
            "paper_details": paper_result["details"],
            "live_trading_disabled": True,
        }


    @r.get("/api/preview_close_all")
    async def preview_close_all(mode: str = "profit", bot: str = ""):
        """Re-prices every open position at a fresh live price (no caching) and
        returns which ones WOULD close for mode=profit/loss, plus the total
        P&L - called by the confirmation dialog before Close All Profit/Loss
        actually closes anything, so the number shown matches what's about to
        happen instead of a possibly-stale figure."""
        if mode not in ("profit", "loss"):
            return {"ok": False, "error": "mode must be 'profit' or 'loss'"}
        result = await asyncio.to_thread(paper_trader.preview_close_all, mode, _bot_arg(bot, None))
        return {"ok": True, **result}


    @r.post("/api/close_all_profit")
    async def close_all_profit(bot: str = "", _auth=Depends(require_api_token)):
        """Closes every open position currently sitting in profit (pnl_usdt >= 0)
        at a fresh price - PAPER re-verifies against a fresh live price per
        position (paper_trader.close_all_profit()); LIVE re-reads the exchange's
        own open-positions feed (already fresh, no caching - see exchange.py)
        and closes every matching real position. Returns how many closed so the
        button can actually tell the user what happened, in either mode."""
        result = await asyncio.to_thread(ExecutionRouter.close_all_profit, _bot_arg(bot, None))
        return result


    @r.post("/api/close_all_loss")
    async def close_all_loss(bot: str = "", _auth=Depends(require_api_token)):
        """Same as above but for positions currently in loss - 'Close All Loss'."""
        result = await asyncio.to_thread(ExecutionRouter.close_all_loss, _bot_arg(bot, None))
        return result


    @r.post("/api/set_target_tp/{trade_id}")
    async def set_target_tp(trade_id: str, payload: dict, _auth=Depends(require_api_token)):
        """Tapping a TP1-4 box on a position card that price hasn't reached yet.
        payload = {"level": 1-4} or {"level": null} to clear back to the
        default target (TP4). trade_id is str for the same reason /api/close/{}
        is - see close_one()'s comment. In LIVE mode this currently returns
        ok=False until Part 2's exchange.set_target_tp() exists (see
        execution_router.py's interface-contract docstring) - it does NOT
        silently no-op."""
        level = payload.get("level")
        result = await asyncio.to_thread(ExecutionRouter.set_target_tp, trade_id, level)
        return result


    @r.post("/api/trail_sl/{trade_id}")
    async def trail_sl(trade_id: str, payload: dict, _auth=Depends(require_api_token)):
        """Tapping a TP1-4 box that price has ALREADY passed - moves the SL up
        to that level instead of closing the trade. Returns ok=False (no-op)
        if that would loosen the SL instead of tightening it (PAPER), or if
        Part 2's live exchange.modify_sl() doesn't exist yet (LIVE - see
        execution_router.py)."""
        level = payload.get("level")
        if level is None:
            return {"ok": False, "error": "level is required"}
        result = await asyncio.to_thread(ExecutionRouter.trail_sl, trade_id, level)
        return result


    @r.post("/api/move_sl_breakeven/{trade_id}")
    async def move_sl_breakeven(trade_id: str, _auth=Depends(require_api_token)):
        """"Move Stop Loss to Break-Even (Entry)" quick pill on a position card.
        Returns ok=False (no-op) if the SL is already at or past entry (PAPER),
        or if Part 2's live exchange.move_sl_to_breakeven() doesn't exist yet
        (LIVE - see execution_router.py)."""
        result = await asyncio.to_thread(ExecutionRouter.move_sl_breakeven, trade_id)
        return result


    @r.post("/api/reconcile")
    async def reconcile(payload: dict = None, _auth=Depends(require_api_token)):
        """Catch-up check of every open PAPER trade against the 5m candles since
        it was last watched live (see paper_trader.reconcile_position) - the
        app calls this right after its connection comes back, so a TP/SL that
        was touched while the phone/backend was disconnected is applied
        immediately instead of waiting for luck. In LIVE mode this is a
        reported no-op (real positions are always read fresh from the exchange
        already - see execution_router.py's reconcile() docstring)."""
        trigger = (payload or {}).get("trigger", "reconnect")
        result = await asyncio.to_thread(ExecutionRouter.reconcile, trigger)
        return result

    return r
