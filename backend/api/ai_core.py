"""api/ai_core.py - AI ask / insights / doctor, Lab / Reading / Desk / Levels, Observer / Pick / Self-signal routes, moved out of api_server.py (NEXT-6i).

Same code, same paths, same order. Three factories because other routers sit between the groups in api_server.py (each is included at its old place).
"""
import asyncio
import time

from fastapi import APIRouter

from recovered_bot import ai_assistant, ai_chat_store, ai_stats, settings_store, trade_store
from api.swr import _swr, _HEAVY_NOW, _REPLAY_POOL, _TIMING, _timed_call


def make_router_ask():
    """AI ask, trade-audit context, insights, strategy doctor."""
    r = APIRouter()

    @r.post("/api/ai/ask")
    async def ai_ask(payload: dict):
        """AI Assistant chat. payload = {message, history?, chat_id?, mode?, image_b64?}.
        Persists the turn into the active (or given) multi-chat thread."""
        message = (payload.get("message") or "").strip()
        image_b64 = payload.get("image_b64") or payload.get("image")
        if not message and not image_b64:
            return {"ok": False, "error": "Empty message."}
        shown = message or "(screenshot)"                 # what the chat history stores / shows: clean text, never the base64 or tags
        if image_b64 and not message:
            message = "Look at my screenshot. Comment on UI, layout, clarity and any trading-app UX issues, in simple English."
        history = payload.get("history") or []
        chat_id = payload.get("chat_id")
        mode = (payload.get("mode") or "").strip() or None
        # Prefer history from store when chat_id given
        if chat_id:
            try:
                history = await asyncio.to_thread(ai_chat_store.get_history, 40, chat_id)
            except Exception:
                pass
        if image_b64 and not isinstance(image_b64, str):
            image_b64 = None
        result = await asyncio.to_thread(ai_assistant.ask, message, history, mode, image_b64)
        if result.get("ok"):
            await asyncio.to_thread(ai_chat_store.append_turn, ("[photo] " + shown) if image_b64 else shown, result.get("reply"), chat_id)
        return result


    @r.get("/api/ai/trade-audit-context")
    async def ai_trade_audit_context():
        """Lightweight trade-audit summary (win/loss streak, best-performing
        session, most common exit triggers) computed from the last 50 closed
        trades' enriched telemetry (trade_store.py). Powers the AI Assistant's
        strategy/mistake-analysis answers, but also queryable directly."""
        return await asyncio.to_thread(trade_store.get_audit_summary, 50)


    @r.get("/api/ai/insights")
    async def ai_insights():
        """Structured strategy statistics for the Dashboard's AI Insights card
        (win rate by SD zone / session / direction / EMA slope / volume, MFE/MAE,
        weak coins). Computed by ai_stats.py from closed paper + live trades -
        the same numbers the AI Assistant is given. Never raises: an empty
        history just returns {"sample": 0, ...}."""
        if settings_store.get("live_trading_enabled", False):
            return {"sample": 0, "min_sample": 1, "low_sample": True, "live_mode": True}   # no paper statistics in LIVE mode
        return await _swr("insights", 20.0, ai_stats.build_insights, 200)


    @r.get("/api/ai/doctor")
    async def ai_doctor():
        """Strategy Doctor (strategy_doctor.py): which entries of the strategy lose / win, SD-rule test, loss story,
        price after exit. Read-only - it never changes the bot. Cached 60 s (reads the trade archive)."""
        try:
            from recovered_bot import strategy_doctor
            return await _swr("doctor", 60.0, strategy_doctor.build, 5000)
        except Exception as e:
            return {"ok": False, "sample": 0, "enough": False, "headline": ["Strategy Doctor is not available yet."],
                    "error": f"{type(e).__name__}: {e}"}

    return r


def make_router_lab(_safe_status):
    """AI health, pair replay, Lab, A/B board, Reading, studies, Recipe, Desk, Levels. _safe_status is api_server's own (passed in)."""
    r = APIRouter()

    @r.get("/api/ai/health")
    async def ai_health():
        """Small read-only check for slow screens: who holds the heavy lock, how long each screen last waited / ran,
        and how long ago the AI copier and the AI engine last ran. Open it in a browser: http://localhost:8000/api/ai/health"""
        from recovered_bot import ai_coach
        now = time.time()
        return {"heavy_lock_held_by": _HEAVY_NOW["key"],
                "held_for_s": round(now - _HEAVY_NOW["since"], 1) if _HEAVY_NOW["key"] else 0,
                "screens": {str(k): {"last_wait_s": v[0], "last_run_s": v[1], "finished_ago_s": round(now - v[2])} for k, v in _TIMING.items()},
                "ai": ai_coach.health(),
                "cpu": _safe_status("ai_cpu_meter"),
                "screen_first": _safe_status("ai_priority"),
                "own_signals": _safe_status("ai_selfsignal")}


    @r.get("/api/ai/pair_replay")
    async def ai_pair_replay(id: str = "", opened: float = 0.0):
        """Bot vs AI -> tap a row: ROI path + Z-score / TSI per closed candle + SD band of ONE signal, to replay how the AI
        read the indicators. Read-only. {"ok": false} when nothing was saved for it."""
        from recovered_bot import ai_coach
        # Timed (shows up in /api/ai/health as "pair_replay": how long it WAITED for a thread vs how long it RAN) and capped:
        # after 18 s the app gets a clear "busy" answer instead of a spinner that never ends. The app already draws the price
        # chart from the Bot vs AI row, so a slow replay only delays the Z-score / TSI lines.
        try:
            return await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(_REPLAY_POOL, _timed_call, "pair_replay", time.time(), False, ai_coach.replay, id, opened),
                timeout=18.0)
        except asyncio.TimeoutError:
            print(f"[swr] pair_replay id={id} did not finish in 18s (backend busy)")
            return {"ok": False, "why": "The backend is busy right now (the replay took longer than 18 s). Tap Retry in a moment."}


    @r.get("/api/ai/lab")
    async def ai_lab(refresh: bool = False):
        """Shadow Lab numbers (strategy replayed on 3m/5m/15m: which SD / Z-score / TSI / higher-timeframe
        scenarios won or lost). refresh=true asks for a rebuild in the background."""
        from recovered_bot import ai_shadow_lab
        return await asyncio.to_thread(ai_shadow_lab.build_lab, refresh)


    @r.get("/api/ai/ab_board")
    async def ai_ab_board_endpoint(tf: str = ""):
        """A/B scoreboard: bot as it is vs bot + TSI filter (simple rule and AI rule), forward test + history.
        Read-only (ai_ab_board.py) - never changes a trade."""
        from recovered_bot import ai_ab_board
        return await _swr(("ab_board", tf), 15.0, ai_ab_board.build, tf)


    @r.get("/api/ai/reading")
    async def ai_reading_endpoint(tf: str = ""):
        """Indicator reading: what MAIN chart / Z-score / TSI said at signal time, wrong-use habits, best and
        avoid combos with the exit AI found best there. Read-only (ai_reading.py) - never changes a trade."""
        from recovered_bot import ai_reading
        return await asyncio.to_thread(ai_reading.build, tf)


    @r.get("/api/ai/exit_study")
    async def ai_exit_study_endpoint(tf: str = ""):
        """Phase 2: per scenario, which exit rule (TP1..TP4 hold) did best in the Shadow Lab replay. Read-only."""
        from recovered_bot import ai_exit_study
        return await asyncio.to_thread(ai_exit_study.build, tf)


    @r.get("/api/ai/wait_study")
    async def ai_wait_study_endpoint(tf: str = ""):
        """Phase 3: repeat-SL coins, sideways entries, and 'enter only when Z and TSI both confirm'. Read-only."""
        from recovered_bot import ai_wait_study
        return await asyncio.to_thread(ai_wait_study.build, tf)


    @r.get("/api/ai/recipe")
    async def ai_recipe_endpoint(tf: str = ""):
        """The result page: which signals to take, where to exit, proven on newer data (or: nothing found). Read-only."""
        from recovered_bot import ai_recipe
        return await asyncio.to_thread(ai_recipe.build, tf)


    @r.get("/api/ai/desk")
    async def ai_desk_endpoint():
        """AI Desk: the AI's own virtual account next to the bot (LE / SKIP / WAIT per signal, its own hold/trail
        exit, AI vs bot on the same signals). Read-only toward the bot (ai_desk.py)."""
        from recovered_bot import ai_desk
        return await _swr("desk", 3.0, ai_desk.build)      # screens re-open often: cached, refreshed behind


    @r.get("/api/ai/levels")
    async def ai_levels_endpoint():
        """SD level / Z-SMA behaviour study (ai_level_study.py): bounce vs break counts per situation. Read-only, cached."""
        from recovered_bot import ai_level_study
        return await _swr("levels", 30.0, ai_level_study.build)

    r.ai_ab_board_endpoint = ai_ab_board_endpoint   # api_server._swr_prewarm (start-up warm-up) calls this handler directly
    r.ai_desk_endpoint = ai_desk_endpoint   # api_server._swr_prewarm (start-up warm-up) calls this handler directly
    r.ai_levels_endpoint = ai_levels_endpoint   # api_server._swr_prewarm (start-up warm-up) calls this handler directly
    return r


def make_router_observer():
    """AI Observer, Pick, Self-signal, Free trade."""
    r = APIRouter()

    @r.get("/api/ai/observer")
    async def ai_observer_endpoint():
        """'Agar AI bot ke har trade ko apne exit rules se manage karta': same entry/SL/TP, alag exit, bot ke saath
        compare + entry-vs-exit verdict (ai_observer.py). Read-only. Heavy replay runs in a worker thread, cached."""
        from recovered_bot import ai_observer
        return await _swr("observer", 30.0, ai_observer.build)


    @r.get("/api/ai/pick")
    async def ai_pick_endpoint():
        """AI Pick: TAKE / SKIP / WATCH on every bot signal, what the AI has proven so far, scoreboard (ai_pick.py). Read-only."""
        from recovered_bot import ai_pick
        return await _swr("pick", 10.0, ai_pick.build)


    @r.get("/api/ai/selfsignal")
    async def ai_selfsignal_endpoint():
        """Round B: the AI's own signals (shadow only, no trade is opened): gate status, finished results vs the bot, verdict (ai_selfsignal.py)."""
        from recovered_bot import ai_selfsignal
        return await _swr("selfsignal", 30.0, ai_selfsignal.build)


    @r.get("/api/ai/free_trade")
    async def ai_free_trade_endpoint(k: str = ""):
        """One Free AI trade as chart data (candles, entry, first stop, every stop move, exit). Read-only (ai_selfsignal.free_trade).
        Candles are saved with the trade, so this answers at once. Only old trades need Binance, and that waits at most 12 s."""
        from recovered_bot import ai_selfsignal
        try:
            r = await asyncio.wait_for(asyncio.to_thread(ai_selfsignal.free_trade, k, False), timeout=8)   # saved candles: instant
        except Exception:
            return {"ok": False, "error": "The backend is busy right now. Try again in a moment."}
        if r.get("need_net"):
            try:
                r = await asyncio.wait_for(asyncio.to_thread(ai_selfsignal.free_trade, k, True), timeout=12)
            except Exception:
                r = {"ok": False, "error": "Binance is busy right now. This older trade has no saved candles. Try again in a minute."}
        return r

    r.ai_observer_endpoint = ai_observer_endpoint   # api_server._swr_prewarm (start-up warm-up) calls this handler directly
    r.ai_pick_endpoint = ai_pick_endpoint   # api_server._swr_prewarm (start-up warm-up) calls this handler directly
    return r
