"""api/vision.py - the Vision AI routes (/api/vision/*), moved out of api_server.py (NEXT-6b).

Same code, same paths, same order. api_server.py includes this router at the exact place the routes used to be.
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException

from recovered_bot import settings_store
from api.swr import _swr


def make_router(require_api_token):
    r = APIRouter()

    @r.get("/api/vision/state")
    async def vision_state(limit: int = 80):
        """Open AI trades (live P&L), closed AI trades, the AI decision on every bot signal, and the scoreboard."""
        from recovered_bot import ai_vision
        # SMOOTH FIX: the app polls this often; every poll rebuilt the whole answer (70 calls = 38 s in 4 h). Now one shared,
        # cached build (3 s) in the light lane; stale answer is returned at once while a fresh one builds behind it.
        return await _swr(f"vision_state:{max(1, min(int(limit), 200))}", 3.0, ai_vision.snapshot, max(1, min(int(limit), 200)))


    @r.get("/api/vision/image/{item_id}")
    async def vision_image(item_id: str, live: int = 0):
        """PNG of the chart: the one the AI saw when it decided (live=0) or a fresh one with entry / stop / target lines (live=1)."""
        from fastapi.responses import Response
        from recovered_bot import ai_vision
        try:
            png = await asyncio.to_thread(ai_vision.image_bytes, item_id, bool(live))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)[:200])
        if not png:
            raise HTTPException(status_code=404, detail="no chart for this item")
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store" if live else "max-age=600"})


    @r.get("/api/vision/guide")
    def vision_guide():
        from recovered_bot import ai_vision
        return {"guide": ai_vision.GUIDE, "notes": settings_store.get("vision_notes", "") or ""}


    @r.post("/api/vision/notes")
    async def vision_notes(payload: dict, _auth=Depends(require_api_token)):
        from recovered_bot import ai_vision
        return await asyncio.to_thread(ai_vision.set_notes, payload.get("notes", ""))


    @r.get("/api/vision/lessons")
    async def vision_lessons():
        """The Vision AI's learning notebook: latest lessons, proposed / approved rules and the evidence for each (ai_vision_lessons.py)."""
        from recovered_bot import ai_vision, ai_vision_lessons
        return await asyncio.to_thread(ai_vision_lessons.snapshot, ai_vision)


    @r.post("/api/vision/rule")
    async def vision_rule(payload: dict, _auth=Depends(require_api_token)):
        """Approve / delete / un-approve one proposed rule. Only approved rules are shown to the Vision AI."""
        from recovered_bot import ai_vision_lessons
        return await asyncio.to_thread(ai_vision_lessons.set_rule, str(payload.get("id", "")), payload.get("action", ""))


    @r.get("/api/vision/pumpdump")
    async def vision_pumpdump(limit: int = 40):
        """Pump/dump memory + playbook for the Vision AI (ai_pumpdump.py)."""
        from recovered_bot import ai_pumpdump
        return await asyncio.to_thread(ai_pumpdump.snapshot, max(1, min(int(limit), 100)))


    @r.post("/api/vision/pumpdump/seed")
    async def vision_pumpdump_seed(payload: dict, _auth=Depends(require_api_token)):
        """Seed pump/dump history from the longest 15m history one call gives (~15 days) for one symbol."""
        from recovered_bot import ai_pumpdump, exchange
        symbol = str(payload.get("symbol") or "").upper().strip()
        if not symbol:
            return {"ok": False, "error": "symbol required"}
        def _fetch(sym, tf):
            return exchange.get_klines(sym, tf, ai_pumpdump.SEED_CANDLES, False, None, False)
        return await asyncio.to_thread(ai_pumpdump.maybe_seed, symbol, _fetch, 15)


    @r.get("/api/vision/compare")
    async def vision_compare():
        """Bot signals vs AI-own paper stats + own-scan counters."""
        from recovered_bot import ai_vision, ai_vision_own
        return await asyncio.to_thread(ai_vision_own.compare, ai_vision)


    @r.get("/api/vision/day_view")
    async def vision_day_view(offset: int = 0):
        """One trading day (5:30 AM IST to 5:30 AM IST) for the Vision tab: bot signals with what the AI decided,
        and what AI Own scanned, took, margin used and profit. Read-only."""
        from recovered_bot import ai_vision, ai_vision_own
        return await asyncio.to_thread(ai_vision_own.day_view, ai_vision, max(0, min(int(offset), 60)))


    @r.get("/api/vision/evidence")
    async def vision_evidence(force: int = 0):
        """Bot vs Bot + AI vs AI Own after fees, plus tag combinations confirmed on the older 60% and the newer 40%. Read-only."""
        from recovered_bot import ai_vision, ai_evidence
        return await asyncio.to_thread(ai_evidence.snapshot, ai_vision, bool(force))


    @r.get("/api/vision/lab")
    async def vision_lab(limit: int = 40):
        """Paper capital status, candidate list (WATCH / READY / TAKEN / REJECTED with grade), shadow results per source. Read-only."""
        from recovered_bot import ai_vision, ai_capital, ai_candidates
        def _go():
            return {"ok": True, "capital": ai_capital.status(ai_vision), "candidates": ai_candidates.recent(ai_vision, max(5, min(limit, 100))),
                    "shadow": ai_candidates.counts(), "note": "Paper only. Shadow result = stop 1.5 ATR, target 2R, after fees, filled in from the candles later."}
        return await asyncio.to_thread(_go)


    @r.get("/api/vision/notebook_digest")
    async def vision_notebook_digest():
        """Short 'use it this way' digest: AI trade counts + pump/dump memory, with small-sample warnings. Read-only."""
        from recovered_bot import ai_vision, ai_notebook_digest
        return await asyncio.to_thread(ai_notebook_digest.build, ai_vision)


    @r.post("/api/vision/own")
    async def vision_own_toggle(payload: dict, _auth=Depends(require_api_token)):
        """Enable / disable the Vision own scanner (paper only)."""
        from recovered_bot import settings_store
        on = bool(payload.get("enabled"))
        settings_store.update(vision_own_enabled=on)
        return {"ok": True, "enabled": on}



    @r.get("/api/vision/day")
    async def vision_day(offset: int = 0, source: str = "all"):
        """One trading day (5:30 AM IST): summary + signal timeline. offset=0 today, 1 yesterday.
        source=all|bot|own filters timeline rows (summary still includes both)."""
        from recovered_bot import ai_vision, ai_vision_days
        off = max(0, min(int(offset or 0), 60))
        src = (source or "all").strip().lower()
        if src not in ("all", "bot", "own"):
            src = "all"
        return await asyncio.to_thread(ai_vision_days.day_payload, ai_vision, off, None, src)


    @r.get("/api/vision/days")
    async def vision_days(n: int = 14):
        """Last N trading-day summary rows (today live)."""
        from recovered_bot import ai_vision, ai_vision_days
        nn = max(1, min(int(n or 14), 60))
        return {"days": await asyncio.to_thread(ai_vision_days.list_days, ai_vision, nn)}


    @r.get("/api/vision/exits")
    async def vision_exits():
        from recovered_bot import ai_vision_exits
        return await asyncio.to_thread(ai_vision_exits.snapshot)

    return r
