"""api/ai_book.py - AI keys, app prefs and Trade Book routes, moved out of api_server.py (NEXT-6g).

AI keys: GET /api/ai/vkeys, POST add / test / detect / clear. App prefs: GET / POST /api/app_prefs.
Trade Book: GET /api/ai/book (6 s cached, old answer served while a fresh one builds), GET /api/ai/path.
Same code, same paths, same order. Two factories because the other routers sit between them in api_server.py.
"""
import asyncio
import time

from fastapi import APIRouter, Depends

from recovered_bot import ai_book
from api.swr import _LIGHT_POOL


def make_router_keys(require_api_token, data_dir):
    """AI keys (vkeys) + app prefs. require_api_token and data_dir are api_server's own (passed in)."""
    r = APIRouter()
    DATA_DIR = data_dir

    @r.get("/api/ai/vkeys")
    async def ai_vkeys_status():
        from recovered_bot import ai_keys_api
        return await asyncio.to_thread(ai_keys_api.status)


    @r.post("/api/ai/vkeys/add")
    async def ai_vkeys_add(payload: dict, _auth=Depends(require_api_token)):
        from recovered_bot import ai_keys_api
        return await asyncio.to_thread(ai_keys_api.add, payload.get("key", ""), payload.get("slot") or None)


    @r.post("/api/ai/vkeys/test")
    async def ai_vkeys_test(payload: dict, _auth=Depends(require_api_token)):
        from recovered_bot import ai_keys_api
        return await asyncio.to_thread(ai_keys_api.test, payload.get("slot", ""))


    @r.post("/api/ai/vkeys/detect")
    async def ai_vkeys_detect(payload: dict, _auth=Depends(require_api_token)):
        from recovered_bot import ai_keys_api
        return await asyncio.to_thread(ai_keys_api.detect, payload.get("slot", ""))


    @r.post("/api/ai/vkeys/clear")
    async def ai_vkeys_clear(payload: dict, _auth=Depends(require_api_token)):
        from recovered_bot import ai_keys_api
        return await asyncio.to_thread(ai_keys_api.clear, payload.get("slot", ""))


    @r.get("/api/app_prefs")
    async def app_prefs_get():
        """App-side choices (theme, sounds) backed up on the phone's backend, so a fresh app install gets them back."""
        from recovered_bot import ops_status
        return await asyncio.to_thread(ops_status.prefs_get, DATA_DIR)


    @r.post("/api/app_prefs")
    async def app_prefs_set(payload: dict, _auth=Depends(require_api_token)):
        from recovered_bot import ops_status
        return await asyncio.to_thread(ops_status.prefs_merge, DATA_DIR, payload)

    return r


def make_router_book():
    """Trade Book (/api/ai/book, /api/ai/path). The cache dict and busy set live inside this factory (same as before: one process-wide copy)."""
    r = APIRouter()

    _BOOK_CACHE = {}      # key -> (time, answer)


    def _book_go(offset, limit, side, result, q, grp, gval, hour):
        out = {"page": ai_book.page(offset, limit, side, result, q, grp, gval, hour)}
        if offset <= 0:
            out["summary"] = ai_book.summary()
        return out


    @r.get("/api/ai/book")
    async def ai_book_endpoint(offset: int = 0, limit: int = 40, side: str = "", result: str = "", q: str = "",
                               grp: str = "", gval: str = "", hour: int = -1):
        """AI tab -> Trade Book. ALL-TIME summary (only on the first page) plus one
        filtered page of closed trades, newest first. Read-only, from the permanent
        archive with the exchange fee already taken off (ai_book.py)."""
        # Book is a cheap read: own thread pool, never behind the heavy lock. An OLD answer is returned at once while a fresh
        # one is built behind it, so the tab opens instantly after the first build.
        key = (offset, limit, side, result, q, grp, gval, hour)
        ent = _BOOK_CACHE.get(key)
        now = time.time()
        if ent is not None:
            if now - ent[0] >= 6.0 and key not in _BOOK_BUSY:
                _BOOK_BUSY.add(key)
                asyncio.ensure_future(_book_refresh(key, offset, limit, side, result, q, grp, gval, hour))
            return ent[1]
        t0 = time.time()
        out = await asyncio.get_running_loop().run_in_executor(_LIGHT_POOL, _book_go, offset, limit, side, result, q, grp, gval, hour)
        if time.time() - t0 > 1.5:
            print(f"[book] first build {time.time() - t0:.1f}s")
        if len(_BOOK_CACHE) > 60:
            _BOOK_CACHE.clear()
        _BOOK_CACHE[key] = (time.time(), out)
        return out


    _BOOK_BUSY = set()


    async def _book_refresh(key, offset, limit, side, result, q, grp, gval, hour):
        try:
            out = await asyncio.get_running_loop().run_in_executor(_LIGHT_POOL, _book_go, offset, limit, side, result, q, grp, gval, hour)
            _BOOK_CACHE[key] = (time.time(), out)
        except Exception as e:
            print(f"[book] refresh failed (old answer kept): {type(e).__name__}")
        finally:
            _BOOK_BUSY.discard(key)


    @r.get("/api/ai/path")
    async def ai_path_endpoint(id: str = "", opened: float = 0.0):
        """Trade Book replay: the saved price path of one closed trade (ai_book.path).
        {"ok": false} for trades closed before path recording existed."""
        return await asyncio.get_running_loop().run_in_executor(_LIGHT_POOL, ai_book.path, id, opened)

    r.ai_book_endpoint = ai_book_endpoint   # api_server._swr_prewarm calls this handler directly (start-up warm-up)
    return r
