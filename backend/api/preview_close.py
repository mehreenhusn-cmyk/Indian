"""api/preview_close.py - Part 19: POSITIONS 1 of 2 - the SAFE CLOSE PREVIEW (backend half). ONE new read-only route: GET /api/v2/preview_close?mode=profit|loss|all|flatten[&bot=].
It answers "what would this button close right now?" with the SAME selection the real button uses, in the SAME mode (the old /api/preview_close_all always read the PAPER snapshot, even when live was on):
 profit / loss -> LIVE: exchange positions with pnl >= 0 / < 0 (execution_router.close_all_profit / _loss) | PAPER: fresh snapshot pnl >= 0 / < 0 (paper_trader.close_all_profit / _loss)
 all           -> LIVE: every exchange position (ExecutionRouter.close_all)           | PAPER: every open paper position of the bot (close_all_with_detail)
 flatten       -> LIVE: every exchange position (only when live is on) + EVERY paper position of every bot, then live trading is switched OFF (/api/flatten)
Answer = ok, mode (live|paper), action, count, total_pnl_usdt, positions (each with source live|paper), parts.live / parts.paper, and for flatten will_turn_live_off. Positions with no fresh price are NOT hidden:
paper.unpriced_count says how many would still close. An unreadable pnl or an unreadable live list = ok False with a short text, never a made-up zero. NOTHING is closed, changed or saved here.
The existing routes and close calls are NOT changed (api/trade.py untouched). Not mounted until the owner approves (D4 + api_server.py is protected). Tests: python3 test/test_v2_preview.py"""
VERSION = "preview_close 1 (Part 19)"
MODES = ("profit", "loss", "all", "flatten")
KEEP = ("id", "symbol", "action", "entry", "ltp", "size", "qty", "leverage", "pnl_usdt", "roi_pct")


def _pnl(p):
    try:
        return float(p.get("pnl_usdt", 0) or 0)                  # the exact expression the real live close uses
    except (TypeError, ValueError, AttributeError):
        raise ValueError("a position has a P&L that cannot be read")


def _pick(mode, positions):
    if mode == "profit":
        return [p for p in positions if _pnl(p) >= 0]
    if mode == "loss":
        return [p for p in positions if _pnl(p) < 0]
    return list(positions)


def _part(picked, source, **extra):
    rows = [dict({k: p[k] for k in KEEP if k in p}, source=source) for p in picked]
    return dict({"count": len(rows), "total_pnl_usdt": round(sum(_pnl(p) for p in picked), 6), "positions": rows}, **extra)


def preview(mode, bot, live, live_positions, paper_view):
    """live = bool now; live_positions() -> list; paper_view(bot) -> (fresh snapshot list, number of open paper positions). Never raises."""
    if mode not in MODES:
        return {"ok": False, "error": "mode must be profit, loss, all or flatten"}
    parts = {}
    try:
        if live:
            parts["live"] = _part(_pick(mode, list(live_positions() or [])), "live")
        if not live or mode == "flatten":
            snap, total = paper_view(None if mode == "flatten" else bot)
            if mode in ("all", "flatten"):
                parts["paper"] = _part(snap, "paper", unpriced_count=max(0, int(total) - len(snap)))
            else:
                parts["paper"] = _part(_pick(mode, snap), "paper", unpriced_count=0)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception:
        return {"ok": False, "error": "could not read the positions right now"}
    rows = [p for part in parts.values() for p in part["positions"]]
    out = {"ok": True, "mode": "live" if live else "paper", "action": mode, "count": len(rows), "positions": rows, "parts": parts,
           "total_pnl_usdt": round(sum(part["total_pnl_usdt"] for part in parts.values()), 6)}
    if mode == "flatten":
        out["will_turn_live_off"] = True
    return out


def make_router(require_api_token, bot_arg):
    """Mounted by api_server.py ONLY after the owner's ok. bot_arg is api_server's own _bot_arg."""
    import asyncio
    from fastapi import APIRouter, Depends
    from recovered_bot import exchange, paper_trader
    from recovered_bot.execution_router import is_live

    def paper_view(bot):
        snap = paper_trader._fresh_snapshot(bot)
        with paper_trader._lock:
            total = sum(1 for p in paper_trader._positions.values() if bot is None or (p.get("bot") or "b1") == bot)
        return snap, total

    r = APIRouter()

    @r.get("/api/v2/preview_close", dependencies=[Depends(require_api_token)])
    async def preview_close(mode: str = "profit", bot: str = ""):
        return await asyncio.to_thread(lambda: preview(mode, bot_arg(bot, None), is_live(), exchange.get_open_positions, paper_view))
    return r
