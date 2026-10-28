"""api/ai_live.py - Desk reset, A/B reset, Advice, Learning, Backup, and the AI Live account routes, moved out of api_server.py (NEXT-6i).

The money-related routes (/api/ai/live/*) keep Depends(require_api_token) exactly as before. Same code, same paths, same order.
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException

from recovered_bot import settings_store
from api.swr import _swr, _SWR


def make_router_tools(require_api_token):
    """Desk reset, A/B board reset, Advice, Learning, Backup (status / run / restore). require_api_token is api_server's own (passed in)."""
    r = APIRouter()

    @r.post("/api/ai/desk/reset")
    async def ai_desk_reset(_auth=Depends(require_api_token)):
        """Clear only the AI's virtual account and start counting again. The bot is untouched."""
        from recovered_bot import ai_desk
        _SWR.pop("desk", None)
        return await asyncio.to_thread(ai_desk.reset)


    @r.get("/api/ai/advice")
    async def ai_advice_endpoint():
        """Phase 4: advice badge per open position (display only - nothing is blocked or closed)."""
        if not settings_store.get("legacy_ai_enabled", False):
            return {}                      # the older AI modules are off: no badges, no work
        from recovered_bot import ai_advice
        return await _swr("advice", 3.0, ai_advice.current)


    @r.post("/api/ai/ab_board/reset")
    async def ai_ab_board_reset(_auth=Depends(require_api_token)):
        """Start the forward test again from now (the AI rule is mined again from everything older)."""
        from recovered_bot import ai_ab_board
        for k in [k for k in _SWR if isinstance(k, tuple) and k[0] == "ab_board"]:
            _SWR.pop(k, None)
        return await asyncio.to_thread(ai_ab_board.reset)


    @r.get("/api/ai/learning")
    async def ai_learning_endpoint(refresh: bool = False):
        """What the AI has learned about the EMA50 strategy: timeline, WORKS / FAILS / UNCERTAIN with evidence
        status, TP funnel + stalls, timeframe + higher-timeframe agreement. Read-only, historical only."""
        from recovered_bot import ai_learning
        return await asyncio.to_thread(ai_learning.build, refresh)


    @r.get("/api/ai/backup")
    async def ai_backup_status():
        """The AI data backups: list, last time, any error."""
        from recovered_bot import ai_backup
        return await asyncio.to_thread(ai_backup.status)


    @r.post("/api/ai/backup/run")
    async def ai_backup_run(_auth=Depends(require_api_token)):
        """Make a backup of the AI data right now."""
        from recovered_bot import ai_backup
        r = await asyncio.to_thread(lambda: ai_backup.run("manual"))
        return {**r, "status": ai_backup.status()}


    @r.post("/api/ai/backup/restore")
    async def ai_backup_restore(payload: dict, _auth=Depends(require_api_token)):
        """Queue a restore of one backup. It is applied at the next backend start (never into a running AI)."""
        from recovered_bot import ai_backup
        r = await asyncio.to_thread(lambda: ai_backup.restore(str(payload.get("name") or "")))
        return {**r, "status": ai_backup.status()}

    r.ai_advice_endpoint = ai_advice_endpoint   # api_server._swr_prewarm (start-up warm-up) calls this handler directly
    return r


def make_router_live(require_api_token):
    """AI Live account: status, keys, check, config, enable / disable, panic, reset, and the Lab replay trigger."""
    r = APIRouter()

    @r.get("/api/ai/live")
    async def ai_live_status(_auth=Depends(require_api_token)):
        """STAGE 2: the AI's real account: switch, limits, key (masked), open and closed real trades, events."""
        from recovered_bot import ai_live_executor
        return await asyncio.to_thread(ai_live_executor.status)


    @r.post("/api/ai/live/keys")
    async def ai_live_keys_set(payload: dict, _auth=Depends(require_api_token)):
        """Save the AI's OWN Binance key (never the bot's) and run the connection check. The secret is never returned."""
        from recovered_bot import ai_live_keys, ai_live_executor, ai_live_guard
        def _go():
            r = ai_live_keys.set_keys(payload.get("key"), payload.get("secret"))
            if not r["ok"]:
                return r
            ai_live_executor.set_client(None)            # build a fresh client with the new key
            ai_live_guard.disable()
            c = ai_live_executor.verify()
            return {"ok": c["ok"], "error": "" if c["ok"] else c["why"], "check": c}
        return await asyncio.to_thread(_go)


    @r.post("/api/ai/live/keys/clear")
    async def ai_live_keys_clear(_auth=Depends(require_api_token)):
        from recovered_bot import ai_live_keys, ai_live_guard
        ai_live_guard.disable()
        return {"ok": await asyncio.to_thread(ai_live_keys.clear)}


    @r.post("/api/ai/live/check")
    async def ai_live_check(_auth=Depends(require_api_token)):
        from recovered_bot import ai_live_executor
        return await asyncio.to_thread(ai_live_executor.verify)


    @r.post("/api/ai/live/config")
    async def ai_live_config(payload: dict, _auth=Depends(require_api_token)):
        """Limits for real trading: margin_per_trade, max_open, daily_loss_cap, max_leverage (ceilings are applied in code), plus coin_cap {sym, margin} for a per-coin size cap."""
        from recovered_bot import ai_live_guard
        try:
            kw = {k: payload.get(k) for k in ("margin_per_trade", "max_open", "daily_loss_cap", "max_leverage") if payload.get(k) is not None}
            out = {"ok": True, "cfg": ai_live_guard.set_cfg(**kw)}
            cc = payload.get("coin_cap")                 # {"sym": "ABCUSDT", "margin": 5}; margin 0 removes that coin's cap
            if isinstance(cc, dict):
                out["coin_caps"] = ai_live_guard.set_coin_cap(cc.get("sym"), cc.get("margin"))
            return out
        except Exception:
            raise HTTPException(status_code=400, detail="limits must be non-negative numbers")


    @r.post("/api/ai/live/enable")
    async def ai_live_enable(payload: dict, _auth=Depends(require_api_token)):
        """Switch real trading for the AI ON. Needs the exact confirm text, a fresh connection check, margin and daily loss cap."""
        from recovered_bot import ai_live_guard, ai_live_keys
        ok, why = ai_live_guard.enable(payload.get("confirm"), ai_live_keys.has_keys())
        return {"ok": ok, "why": why}


    @r.post("/api/ai/live/disable")
    async def ai_live_disable(_auth=Depends(require_api_token)):
        """Stops NEW real trades. Real trades already open stay protected and are closed by the AI as usual."""
        from recovered_bot import ai_live_guard
        ai_live_guard.disable()
        return {"ok": True}


    @r.post("/api/ai/live/panic")
    async def ai_live_panic(_auth=Depends(require_api_token)):
        """PANIC: halt, cancel every stop and close every position on the AI account."""
        from recovered_bot import ai_live_executor
        return await asyncio.to_thread(ai_live_executor.panic)


    @r.post("/api/ai/live/reset")
    async def ai_live_reset(_auth=Depends(require_api_token)):
        """Clear a HALT after the owner has looked at why it happened."""
        from recovered_bot import ai_live_guard
        ai_live_guard.reset_halt()
        return {"ok": True}


    @r.post("/api/ai/lab/replay")
    async def ai_lab_replay(_auth=Depends(require_api_token)):
        """Replay the last days again for every coin (already-saved signals are never duplicated)."""
        from recovered_bot import ai_shadow_lab
        return {"ok": ai_shadow_lab.request_replay(), "status": ai_shadow_lab.status()}

    return r
