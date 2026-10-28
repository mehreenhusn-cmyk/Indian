"""api/ai_chats.py - Shadow card, digest, AI chat history + chats, app health report, moved out of api_server.py (NEXT-6i). Same code, same paths, same order.
"""
import asyncio

from fastapi import APIRouter

from recovered_bot import ai_chat_store


def make_router_chats(data_dir):
    """AI shadow, digest, history, chats, app health. data_dir = api_server.DATA_DIR (passed in, not copied)."""
    r = APIRouter()
    DATA_DIR = data_dir

    @r.get("/api/ai/shadow")
    async def ai_shadow_endpoint():
        """OWNER-ONLY screen card: has the ML model's quiet guess at trade-open matched the real
        result? (ai_ml.shadow_stats). These numbers are never given to the chat AI (see ai_guard)."""
        from recovered_bot import ai_ml
        return await asyncio.to_thread(ai_ml.shadow_stats)


    @r.post("/api/ai/digest/send")
    async def ai_digest_send():
        """Send today's AI digest to Telegram right now (same text as the nightly one)."""
        from recovered_bot import ai_digest
        return await asyncio.to_thread(ai_digest.send_now)


    @r.get("/api/ai/history")
    async def ai_history(chat_id: str = ""):
        """Messages for one chat (or the active chat). Also returns multi-chat list."""
        cid = chat_id or None
        msgs = await asyncio.to_thread(ai_chat_store.get_history, 200, cid)
        listing = await asyncio.to_thread(ai_chat_store.list_chats)
        active = listing.get("active")
        mode = await asyncio.to_thread(ai_chat_store.get_mode, cid or active)
        return {"messages": msgs, "chats": listing.get("chats") or [], "active": active, "mode": mode}


    @r.post("/api/ai/history/clear")
    async def ai_history_clear(payload: dict = None):
        """Clear messages of one chat (body: {chat_id?}) or the active chat."""
        payload = payload or {}
        cid = payload.get("chat_id")
        await asyncio.to_thread(ai_chat_store.clear, cid)
        return {"ok": True}


    @r.get("/api/ai/chats")
    async def ai_chats_list():
        return await asyncio.to_thread(ai_chat_store.list_chats)


    @r.post("/api/ai/chats")
    async def ai_chats_create(payload: dict = None):
        payload = payload or {}
        return await asyncio.to_thread(
            ai_chat_store.create_chat, payload.get("mode") or "general", payload.get("title") or ""
        )


    @r.post("/api/ai/chats/rename")
    async def ai_chats_rename(payload: dict):
        return await asyncio.to_thread(ai_chat_store.rename_chat, payload.get("chat_id"), payload.get("title") or "")


    @r.post("/api/ai/chats/delete")
    async def ai_chats_delete(payload: dict):
        return await asyncio.to_thread(ai_chat_store.delete_chat, payload.get("chat_id"))


    @r.post("/api/ai/chats/active")
    async def ai_chats_active(payload: dict):
        return await asyncio.to_thread(ai_chat_store.set_active, payload.get("chat_id"))


    @r.get("/api/ai/app_health")
    async def ai_app_health_report():
        """Plain health report for the AI assistant / debugging (freezes, REST, data)."""
        from recovered_bot import ai_health
        return await asyncio.to_thread(ai_health.build_report, DATA_DIR)

    return r
