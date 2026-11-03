"""
OWL Terminal backend - FastAPI wrapper around the real bot logic in
recovered_bot/ (the same strategy/paper-trading/telegram code that ran
inside the old Kivy app). This replaces the old placeholder api_server.py
that only sent fake random BTC prices and never touched recovered_bot at
all - that's why the Flutter app showed "0 coins" / "No signals" / "No
market data" even though it connected fine (WS was live, just had nothing
real to send).

Run with: python start.py  (same as before, still uvicorn on port 8000)
Meant to run in Termux on the same phone as the Flutter app, so the
frontend's existing http://localhost:8000 / ws://localhost:8000/ws URLs
work as-is - no IP/domain needed for that setup.
"""
import asyncio
import json
import os
import sys
import threading
import time
import traceback

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from recovered_bot import settings_store, trade_store, paper_trader, status, db, ai_data_logger, ai_assistant, ai_chat_store, exchange, timeframe_manager, ai_stats, ai_book, telemetry, day_gate
from recovered_bot.execution_router import ExecutionRouter
from recovered_bot.app import main as bot_main

# ---- SMOOTH FIX 1: FastAPI's jsonable_encoder walks every value in pure Python ON THE EVENT LOOP. On a phone a big
# answer (signals / status / calendar) froze the loop for 1.5-2 s ("[STALL] ... is_dataclass <- jsonable_encoder"), so
# the price stream, REST and WebSocket all went quiet and the app showed the red "phone is busy" banner. Our answers
# are already plain dict/list/str/number, so json.dumps (C speed, ~20x faster) is used first; anything else (pydantic
# objects, datetimes ...) falls back to the original encoder, so nothing changes in what the app receives.
try:
    import fastapi.routing as _fr
    _orig_jsonable = _fr.jsonable_encoder

    def _fast_jsonable(obj, *a, **kw):
        if isinstance(obj, (dict, list)) and not a and not kw.get("include") and not kw.get("exclude"):
            try:
                json.dumps(obj, allow_nan=False)
                return obj
            except (TypeError, ValueError):
                pass
        return _orig_jsonable(obj, *a, **kw)

    _fr.jsonable_encoder = _fast_jsonable
except Exception as _e:
    print(f"[startup] fast json patch skipped: {_e}")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Browser (desktop) version of the app, served at /app/ ---
# Built by GitHub (branch web-build) and pulled onto the phone by web_update.sh
# into ~/owl_web (or the folder in OWL_WEB_DIR). No folder = no browser version.
try:
    from fastapi.staticfiles import StaticFiles
    _web_dir = os.environ.get("OWL_WEB_DIR") or os.path.join(os.path.expanduser("~"), "owl_web")
    if os.path.isfile(os.path.join(_web_dir, "index.html")):
        app.mount("/app", StaticFiles(directory=_web_dir, html=True), name="owl_web")
        print(f"[startup] browser app served at /app/ from {_web_dir}")
except Exception as _e:
    print(f"[startup] browser app skipped: {_e}")

@app.middleware("http")
async def _ai_priority_touch(request, call_next):
    """Any AI screen request marks the app as 'in use', so background AI workers slow down while you look at it."""
    try:
        path = request.url.path
        if path.startswith("/api/ai/") and path != "/api/ai/health":
            from recovered_bot import ai_priority
            ai_priority.touch()
    except Exception:
        pass
    _t0 = time.perf_counter()
    response = await call_next(request)
    try:                                   # how long every answer took -> load_report.py (where is the bottleneck?)
        if request.url.path.startswith("/api/"):
            from recovered_bot import load_report
            load_report.note_api(request.url.path, (time.perf_counter() - _t0) * 1000.0)
    except Exception:
        pass
    return response


# Set OWL_DATA_DIR (e.g. ~/owl_data) to keep settings/trades/positions OUTSIDE the
# code folder - otherwise downloading a fresh repo copy into a new folder starts
# with an empty data/ and all settings + trade history look "lost".
_OLD_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _pick_data_dir():
    """History must survive every new build / re-copied repo folder. Default is
    now ~/owl_data (OUTSIDE the code folder). The first time it is used, anything
    that still sits in the old backend/data folder is COPIED over (never moved,
    never overwriting a file that already exists in the new folder). Setting
    OWL_DATA_DIR still wins. Any problem -> falls back to the old folder."""
    env = os.environ.get("OWL_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    new_dir = os.path.join(os.path.expanduser("~"), "owl_data")
    try:
        os.makedirs(new_dir, exist_ok=True)
        if os.path.isdir(_OLD_DATA_DIR):
            import shutil
            for name in os.listdir(_OLD_DATA_DIR):
                src, dst = os.path.join(_OLD_DATA_DIR, name), os.path.join(new_dir, name)
                if os.path.exists(dst):
                    continue
                try:
                    if os.path.isdir(src):
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                except Exception as e:
                    print(f"[data-dir] could not copy {name}: {e}")
        return new_dir
    except Exception as e:
        print(f"[data-dir] ~/owl_data unusable ({e}) - using {_OLD_DATA_DIR}")
        return _OLD_DATA_DIR


DATA_DIR = _pick_data_dir()
os.makedirs(DATA_DIR, exist_ok=True)


def _daily_backup():
    """Copy the small history files into DATA_DIR/backups/<date>/ once a day
    (last 7 days kept). Best-effort - never raises."""
    try:
        import shutil, time as _t
        day = _t.strftime("%Y-%m-%d")
        dest = os.path.join(DATA_DIR, "backups", day)
        if os.path.isdir(dest):
            return
        os.makedirs(dest, exist_ok=True)
        for name in ("trades.json", "closed_trades_archive.jsonl", "alerts.json", "settings.json", "ai_chat_history.json"):
            src = os.path.join(DATA_DIR, name)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dest, name))
        root = os.path.join(DATA_DIR, "backups")
        for old in sorted(os.listdir(root))[:-7]:
            shutil.rmtree(os.path.join(root, old), ignore_errors=True)
    except Exception as e:
        print(f"[backup] skipped: {e}")

# PRODUCTION HARDENING - Bearer token guard for sensitive trading routes.
# Deliberately OFF by default: if API_TOKEN is not set in the environment,
# every request behaves exactly like before this round (no header
# required) - this matters because the Flutter app does not send an
# Authorization header yet. Only set API_TOKEN on the VPS once the app
# side is also updated to send "Authorization: Bearer <token>" on every
# request, or every close/flatten/settings-save/toggle call from the app
# will start failing with 401.
API_TOKEN = os.environ.get("API_TOKEN", "").strip()


async def require_api_token(authorization: str = Header(default="")):
    if not API_TOKEN:
        return
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


# India options PAPER mode (separate from the crypto bot) - routes live in india_api.py
try:
    from india_api import make_router as _india_make_router
    app.include_router(_india_make_router(require_api_token, DATA_DIR))
except Exception as _e:
    print(f"[startup] india paper routes skipped: {_e}")

# Ping Lab (paper-only, read-only) - only READS the snapshot written by ping_worker.py.
# Wrapped so a broken ping file can never stop the main backend from starting.
try:
    from recovered_bot.ping_api import make_router as _ping_make_router
    app.include_router(_ping_make_router())
except Exception as _e:
    print(f"[startup] ping routes skipped: {_e}")


_bot_thread_started = False
_bot_thread_lock = threading.Lock()


def _run_bot():
    try:
        bot_main()
    except Exception:
        tb = traceback.format_exc()
        status.update(last_error=f"BOT CRASHED:\n{tb}")


@app.on_event("startup")
async def on_startup():
    global _bot_thread_started
    with _bot_thread_lock:
        if _bot_thread_started:
            return
        # SCORE LOCK: the health score / ai_book must never reach an AI file. Raises (server does
        # not start) if an AI file breaks the rule - set env OWL_AI_GUARD=warn to only print it.
        from recovered_bot import ai_guard
        ai_guard.enforce()
        settings_store.init(os.path.join(DATA_DIR, "settings.json"))
        trade_store.init(os.path.join(DATA_DIR, "trades.json"))
        try:
            day_gate.start()               # IST schedule: OFF 01:30, no trades 05:30-09:30, ON 09:30 (tiny own thread)
        except Exception as _e:
            print(f"[startup] day_gate skipped: {_e}")
        # db.init() BEFORE paper_trader.init(): open positions now live in
        # db.py's SQLite `positions` table, so the connection must exist
        # before paper_trader tries to load from it. The positions.json
        # path is still passed through - paper_trader.init() only uses it
        # once, to migrate a pre-SQLite install's open positions into the
        # new table (see db.migrate_positions_json_if_needed).
        db.init(os.path.join(DATA_DIR, "owl.db"))
        paper_trader.init(os.path.join(DATA_DIR, "positions.json"))
        try:                               # a queued "restore AI backup" is applied HERE, before any AI module reads its file
            from recovered_bot import ai_backup
            ai_backup.apply_pending(os.path.join(DATA_DIR, "ai"))
            ai_backup.init(os.path.join(DATA_DIR, "ai"))
            ai_backup.start()              # one zip of the AI data per IST day, newest 7 kept (own thread)
        except Exception as e:
            print(f"[AIBackup] start-up: {e}")
        # Only the Vision AI runs. One-time switch: older builds may have saved legacy_ai_enabled=True.
        try:
            if not settings_store.get("legacy_ai_off_oct11", False):
                settings_store.update(legacy_ai_enabled=False, legacy_ai_off_oct11=True)
        except Exception as e:
            print(f"[startup] legacy AI switch-off skipped: {e}")
        # MASTER LOCK (every start): while old_labs_locked is on, the old AI modules (and with them the Shadow Lab) stay off,
        # even if a saved setting or an update switched them on. Vision AI, Dual Bot and Ping do not use this switch.
        try:
            if settings_store.get("old_labs_locked", True) and settings_store.get("legacy_ai_enabled", False):
                settings_store.update(legacy_ai_enabled=False)
                print("[startup] old_labs_locked: legacy_ai_enabled forced off")
        except Exception as e:
            print(f"[startup] old_labs_locked check skipped: {e}")
        try:                               # STAGE 2: the AI's own real account (older AI: only when legacy_ai_enabled)
            if not settings_store.get("legacy_ai_enabled", False):
                raise RuntimeError("older AI is off - AI real-account worker not started")
            from recovered_bot import ai_live_guard, ai_live_keys, ai_live_executor
            _ai_dir = os.path.join(DATA_DIR, "ai")
            ai_live_guard.init(_ai_dir)
            ai_live_keys.init(_ai_dir)
            ai_live_executor.init(_ai_dir)
            ai_live_executor.start()       # own thread; reconcile only runs when real trading is on or a real trade is open
        except Exception as e:
            print(f"[AILive] start-up: {e}")
        ai_data_logger.init(os.path.join(DATA_DIR, "ai"))
        try:
            from recovered_bot import ai_path_logger
            ai_path_logger.init(os.path.join(DATA_DIR, "ai"))
        except Exception as e:
            print(f"[startup] ai_path_logger init skipped: {e}")
        if settings_store.get("doctor_enabled", False):
            try:                           # Strategy Doctor: price after each exit (record only)
                from recovered_bot import ai_post_exit
                ai_post_exit.init(os.path.join(DATA_DIR, "ai"))
            except Exception as e:
                print(f"[startup] ai_post_exit init skipped: {e}")
        if settings_store.get("vision_enabled", True):   # OFF = Vision AI not started at boot (nothing else uses it)
            try:                           # the Vision AI: chart picture on every bot signal, own virtual account (own thread)
                from recovered_bot import ai_vision
                ai_vision.init(os.path.join(DATA_DIR, "ai"))
                ai_vision.start()
            except Exception as e:
                print(f"[Vision] start-up: {e}")
        try:                               # Dual Bot (paper only, own low-priority process, no AI key): start its worker 8 s after boot
            import dual_lab
            _t = threading.Timer(8.0, dual_lab.ensure_running)
            _t.daemon = True
            _t.start()
        except Exception as e:
            print(f"[startup] dual_lab skipped: {e}")
        try:                               # Smart Brain (Dual Bot v2 side layer): read-only on Dual Bot data, paper only, own process
            import smart_brain
            _t2 = threading.Timer(15.0, smart_brain.ensure_running)
            _t2.daemon = True
            _t2.start()
        except Exception as e:
            print(f"[startup] smart_brain skipped: {e}")
        try:                               # Price Action Light (version-2 observation layer): only watches and logs, own process, never trades
            import pa_layer
            _t3 = threading.Timer(25.0, pa_layer.ensure_running)
            _t3.daemon = True
            _t3.start()
        except Exception as e:
            print(f"[startup] pa_layer skipped: {e}")
        try:                               # Volume Context (version-2 observation layer): only watches and logs, own process, never trades
            import vol_layer
            _t4 = threading.Timer(35.0, vol_layer.ensure_running)
            _t4.daemon = True
            _t4.start()
        except Exception as e:
            print(f"[startup] vol_layer skipped: {e}")
        try:                               # V2 collectors (Part 72): public GET only, write only v2_market.db, own process; owner switch files stay in charge
            import v2_runner
            v2_runner.start_watchdog(DATA_DIR, 45.0)
        except Exception as e:
            print(f"[startup] v2 collector runner skipped: {e}")
        # The older AI modules (trackers, shadow lab, desk, coach, pick, ...) only start when legacy_ai_enabled is on.
        if settings_store.get("legacy_ai_enabled", False):
            try:
                from recovered_bot import ai_sd_tracker
                ai_sd_tracker.start()          # SD size/shape while a trade is open (own thread, read-only)
                from recovered_bot import ai_slope_tracker
                ai_slope_tracker.start()       # EMA slope while a trade is open (own thread, read-only)
                from recovered_bot import ai_ind_tracker
                ai_ind_tracker.start()         # Z-score + TSI while a trade is open (own thread, read-only)
                from recovered_bot import ai_shadow_lab
                ai_shadow_lab.init(os.path.join(DATA_DIR, "ai"))
                ai_shadow_lab.start()          # strategy replay on 3m/5m/15m for the AI (own thread, read-only, lab_enabled)
                from recovered_bot import ai_cpu_meter
                ai_cpu_meter.start()           # which thread uses the CPU (shown in /api/ai/health, read-only)
                from recovered_bot import ai_desk
                ai_desk.init(os.path.join(DATA_DIR, "ai"))
                ai_desk.start()                # AI's own virtual account next to the bot (own thread, read-only)
                from recovered_bot import ai_coach
                ai_coach.init(os.path.join(DATA_DIR, "ai"))
                ai_coach.start()               # AI Coach: AI-managed virtual trade on every bot signal + memo (own thread, read-only)
                from recovered_bot import ai_pick
                ai_pick.init(os.path.join(DATA_DIR, "ai"))
                ai_pick.start()                # AI Pick: TAKE / SKIP / WATCH on every bot signal from proven situations (own thread, read-only)
                from recovered_bot import ai_selfsignal
                ai_selfsignal.init(os.path.join(DATA_DIR, "ai"))
                ai_selfsignal.start()          # Round B: AI's OWN signals, shadow only, starts by itself once the AI Pick has proven something
                from recovered_bot import ai_level_study
                ai_level_study.init(os.path.join(DATA_DIR, "ai"))
                ai_level_study.start()         # how SD levels / Z-SMA behave: counts bounce vs break on real candles (read-only)
                from recovered_bot import ai_learning
                ai_learning.init(os.path.join(DATA_DIR, "ai"))   # evidence status + pattern lifecycle (read-only)
                from recovered_bot import ai_digest
                ai_digest.start()              # nightly Telegram summary (own thread, read-only)
            except Exception as e:
                print(f"[startup] legacy AI modules skipped: {e}")
        from recovered_bot import live_recorder
        live_recorder.init(os.path.join(DATA_DIR, "ai"))
        ai_chat_store.init(os.path.join(DATA_DIR, "ai_chat_history.json"))
        status.init_alerts(os.path.join(DATA_DIR, "alerts.json"))
        _daily_backup()
        status.update(**trade_store.get_today_stats())
        threading.Thread(target=_run_bot, daemon=True).start()
        _bot_thread_started = True

        def _warm_ai():
            # ~60 s after start (so the bot's own start-up work finishes first) build the A/B board once in
            # the background, so the first open of the A/B tab does not wait 20-40 s. Read-only, never raises.
            time.sleep(60)
            try:
                from recovered_bot import ai_ab_board
                ai_ab_board.warm()
            except Exception as e:
                print(f"[startup] ai warm-up skipped: {e}")
        if settings_store.get("legacy_ai_enabled", False):
            threading.Thread(target=_warm_ai, daemon=True).start()
        try:
            from recovered_bot import live_snapshot
            live_snapshot.start()      # LIVE only: positions + wallet read in the background, status just reads memory
        except Exception as e:
            print(f"[startup] live_snapshot skipped: {e}")
        telemetry.start()
        try:
            from recovered_bot import loop_watch
            loop_watch.start()         # records WHERE the event loop froze (System Load card + log)
            from recovered_bot import load_report
            load_report.start(DATA_DIR)  # 30 s samples -> /api/load_report (1h / 4h / 24h report + daily summary)
        except Exception as e:
            print(f"[startup] loop_watch skipped: {e}")
        asyncio.create_task(_status_broadcaster())
        asyncio.create_task(_swr_warmer())
        asyncio.create_task(_swr_prewarm())


# ---------------------------------------------------------------- basic ----

# The root + health routes moved to api/status.py (NEXT-6f). Included HERE so the route order stays the same.
from api.status import (make_router_basic as _status_basic_router, make_router_system as _status_system_router,
                        make_router_market as _status_market_router, make_router_history as _status_history_router)
from api.settings import make_router_settings as _st_settings_router, make_router_exchange as _st_exchange_router
app.include_router(_status_basic_router())




# ---------------------------------------------------------------- reads ----

_PAPER_ONLY_STAT_KEYS = ("today_pnl_usdt", "total_trades", "win_rate", "wins", "losses")

# LIVE mode asked Binance for the open positions on EVERY /api/status call AND every broadcaster tick, one request
# each. A slow Binance answer made pull-to-refresh spin until the 45 s timeout. Now all callers share ONE fetch that is
# at most 1.5 s old; a second caller arriving while a fetch runs waits for that same fetch instead of sending another.
def _live_positions_cached():
    """Real Binance positions from the background snapshot thread (live_snapshot.py). Reads memory,
    so the status tick and pull-to-refresh never wait for a slow Binance call."""
    try:
        from recovered_bot import live_snapshot
        return live_snapshot.get_positions()
    except Exception:
        return exchange.get_open_positions()


# ---- LAG FIX (SWR cache core): moved to api/swr.py (NEXT-6a). Same objects, same names - everything below works as before.
from api.swr import (
    _SWR, _SWR_TASK, _SWR_JOBS, _HEAVY_LOCK, _HOT_S, _TPE, _HEAVY_POOL, _LIGHT_POOL,
    _REPLAY_POOL, _heavy_call, _LIGHT_KEYS, _HEAVY_NOW, _TIMING, _timed_call, _SWR_MAX_RUN_S, _SWR_STARTED,
    _SWR_SLOW_X, _SWR_SLOW_MAX_S, _eff_ttl, _swr_refresh, _swr_start, _swr, _swr_warmer,
)


async def _swr_prewarm():
    """SPEED: build every AI-tab answer ONCE in the background after start-up (one at a time, spaced out), so the
    FIRST time the AI tab opens it already finds ready numbers instead of waiting 20-40 s behind the heavy lock.
    Read-only; any failure is ignored (the screens still build on demand)."""
    await asyncio.sleep(15)          # let the bot finish its own start-up work first
    steps = (
        lambda: ai_book_endpoint(0, 1),       # same cache key the Overview asks for (summary only): built once, not twice
        lambda: ai_coach_endpoint(),
        lambda: ai_pick_endpoint(),
        lambda: ai_ab_board_endpoint(""),
        lambda: ai_desk_endpoint(),
        lambda: ai_observer_endpoint(),
        lambda: ai_levels_endpoint(),
        lambda: ai_advice_endpoint(),
    )
    for st in steps:
        try:
            await asyncio.wait_for(asyncio.shield(st()), timeout=90)
        except Exception as e:
            print(f"[swr] prewarm step skipped: {type(e).__name__}")
        await asyncio.sleep(1)


_FLAG_CACHE = {}          # kind -> (time, flags); the AI badges only need refreshing about once a second
_FLAG_TTL_S = 1.0
_FLAG_BUSY = set()         # kinds whose worker thread is running right now


def _cached_flags(kind, positions):
    """ai_miner.open_flags / ai_ml.open_badges, at most once per _FLAG_TTL_S (the 250ms broadcaster used to
    recompute both on every tick). Display-only badges; an error simply means no badge."""
    if not settings_store.get("legacy_ai_enabled", False):
        return {}                      # the older AI badges are off: no pattern search, no CPU
    now = time.time()
    hit = _FLAG_CACHE.get(kind)
    if hit and now - hit[0] < _FLAG_TTL_S:
        return hit[1]
    # NEVER compute here: this runs on the event loop (every 250 ms tick). ai_miner.open_flags can start a
    # 60-90 s pattern search, which froze the whole server (price stream, REST, WebSocket) - the real reason
    # for the repeated "connection lost". The last answer is returned at once; a worker thread refreshes it.
    if kind not in _FLAG_BUSY:
        _FLAG_BUSY.add(kind)
        pos = [dict(p) for p in (positions or []) if isinstance(p, dict)]

        def _work(k=kind, ps=pos):
            try:
                with _HEAVY_LOCK:            # one heavy job at a time, same as the AI screens
                    if k == "miner":
                        from recovered_bot import ai_miner
                        fl = ai_miner.open_flags(ps)
                    else:
                        from recovered_bot import ai_ml
                        fl = ai_ml.open_badges(ps)
                _FLAG_CACHE[k] = (time.time(), fl)
            except Exception:
                _FLAG_CACHE[k] = (time.time(), (_FLAG_CACHE.get(k) or (0, {}))[1])
            finally:
                _FLAG_BUSY.discard(k)
        threading.Thread(target=_work, name=f"flags-{kind}", daemon=True).start()
    return hit[1] if hit else {}


def _bot_arg(bot, default="b1"):
    """Bot 2 was removed: every ?bot= value now means the one remaining bot ('b1')."""
    return "b1"


def _net_open_positions(positions):
    """Same NET-of-fee numbers _display_status() puts on Bot 1's open trades, for Bot 2's list."""
    fee_default = max(0.0, float(settings_store.get("fee_roi_pct", 1.0) or 0.0))
    out = []
    for p in positions:
        try:
            inv = float(p.get("invest_usdt", 0) or 0)
            g_pnl = float(p.get("pnl_usdt", 0) or 0)
            g_roi = float(p.get("roi_pct", 0) or 0)
            fee = p.get("fee_roi_pct")
            fee = fee_default if fee is None else float(fee or 0.0)
            out.append(dict(p, pnl_gross_usdt=round(g_pnl, 4), roi_gross_pct=round(g_roi, 4),
                            pnl_usdt=g_pnl - inv * fee / 100.0, roi_pct=g_roi - fee,
                            fee_usdt=round(inv * fee / 100.0, 4)))
        except Exception:
            out.append(p)
    return out


def _display_status(skip=()):
    """status.get() with open_positions swapped for the ACTIVE exchange's
    real positions whenever live_trading_enabled is on - paper positions
    (if any linger from before Live was switched on) are completely hidden
    in that case, never mixed in with real ones. When live_trading_enabled
    is off, this is identical to status.get() (paper positions as before).
    Used by every place that serves open_positions to the app: GET
    /api/status, the websocket's initial snapshot, and its 1s update loop.

    PRODUCTION HARDENING - three additional real-data contracts live here,
    all derived from whichever open_positions set was just chosen above,
    never mocked:

    1. STRICT STATE ISOLATION: today_pnl_usdt/total_trades/win_rate/wins/
       losses all come from trade_store.get_today_stats(), which only ever
       records PAPER closes (trade_store.record_close() is called
       exclusively from paper_trader.py - see that module). Showing those
       numbers while LIVE trading is on would surface a stale/irrelevant
       PAPER figure (e.g. a leftover paper loss) right next to real
       Binance positions, reading as if it were live P&L. Blocked
       completely (set to None, never a fabricated live substitute) with
       "stats_mode" telling the app which case it's in, instead of ever
       guessing a live-equivalent number this backend doesn't actually
       have yet.
    2. open_pnl / open_margin_used: previously open_pnl was read by the
       Dashboard (status['open_pnl']) but never actually populated by this
       endpoint at all - it was always the Flutter-side default of 0.0,
       silently wrong the entire time. Computed for real here, from
       whichever position list (paper or live) is actually being shown,
       so the Dashboard stat AND the Positions screen's new aggregated
       Total Bar always agree with each other and with reality.
    3. feed_age_sec: server-clock-relative age of the last successful
       market-data tick (feed_last_update_ts, written by market_ws.py),
       computed here (not on the phone) so it's immune to client/server
       clock drift - the app only ever adds locally-elapsed time on top of
       this one authoritative number.
    """
    data = status.get(skip=skip)
    if settings_store.get("live_trading_enabled", False):
        live_positions = _live_positions_cached()
        data = dict(data)
        data["open_positions"] = live_positions
        data["open_count"] = len(live_positions)
        data["stats_mode"] = "live"
        try:
            from recovered_bot import live_snapshot
            data["live_wallet"] = live_snapshot.peek_wallet()    # real USDT wallet / available / unrealized (or the reason it failed)
        except Exception:
            data["live_wallet"] = {"ok": False, "error": "wallet read failed"}
        for key in _PAPER_ONLY_STAT_KEYS:
            data[key] = None
        # LIVE account: no paper numbers anywhere. Alerts of paper trades are dropped, and "signals today"
        # counts only the signals recorded while LIVE was on.
        if "alerts" in data:
            data["alerts"] = [a for a in (data.get("alerts") or []) if status.alert_is_live(a)]
        try:
            data["signals_today"] = db.count_signals_today("LIVE", trade_store._trading_day_start_ts())
        except Exception:
            pass
    else:
        data["stats_mode"] = "paper"
        data["live_wallet"] = None
        # "Signals today" must survive an app reinstall / backend restart: the in-memory number starts at 0 after a restart,
        # so count the signals saved in the database since today's crypto day start (05:30 IST = 00:00 UTC) and show the larger one.
        try:
            n = db.count_signals_today("PAPER", trade_store._trading_day_start_ts())
            data = dict(data)
            data["signals_today"] = max(int(data.get("signals_today") or 0), int(n))
        except Exception:
            pass

    positions = data.get("open_positions") or []
    # AI badge (advice only): flag open paper trades that match a CONFIRMED AVOID
    # pattern. Copies the dicts, never touches trading state; any error = no badge.
    try:
        flags = _cached_flags("miner", positions)
        if flags:
            positions = [dict(p, ai_flag=flags[str(p.get("id"))]) if str(p.get("id")) in flags else p
                         for p in positions]
            data["open_positions"] = positions
    except Exception:
        pass
    # ML badge (advice only, shown only once the shadow log proved the model - see ai_ml.open_badges)
    try:
        mlf = _cached_flags("ml", positions)
        if mlf:
            positions = [dict(p, ml_flag=mlf[str(p.get("id"))]) if str(p.get("id")) in mlf else p
                         for p in positions]
            data["open_positions"] = positions
    except Exception:
        pass
    # ONE P&L FORMULA FOR THE WHOLE APP (paper mode):
    #   Today Total = Closed today (already net of fee) + Open (net of the round-trip fee it will pay on close)
    # Every open position goes out with pnl_usdt / roi_pct already NET (the raw numbers stay in pnl_gross_usdt /
    # roi_gross_pct), so the position card, the Positions header, the Dashboard and the top pill all add up to the
    # same figure. Live mode is untouched: exchange positions already carry the real exchange numbers.
    try:
        if data.get("stats_mode") == "paper":
            fee_default = None
            netted = []
            fee_total = 0.0
            gross_total = 0.0
            for p in positions:
                try:
                    inv = float(p.get("invest_usdt", 0) or 0)
                    g_pnl = float(p.get("pnl_usdt", 0) or 0)
                    g_roi = float(p.get("roi_pct", 0) or 0)
                    fee = p.get("fee_roi_pct")
                    if fee is None:
                        if fee_default is None:
                            fee_default = max(0.0, float(settings_store.get("fee_roi_pct", 1.0) or 0.0))
                        fee = fee_default
                    fee = float(fee or 0.0)
                    fee_usd = inv * fee / 100.0
                    q = dict(p, pnl_gross_usdt=round(g_pnl, 4), roi_gross_pct=round(g_roi, 4),
                             pnl_usdt=g_pnl - fee_usd, roi_pct=g_roi - fee, fee_usdt=round(fee_usd, 4))
                    netted.append(q)
                    gross_total += g_pnl
                    fee_total += fee_usd
                except Exception:
                    netted.append(p)
            positions = netted
            data["open_positions"] = positions
            data["open_pnl_gross"] = round(gross_total, 4)
            data["open_fee_usdt"] = round(fee_total, 4)
        data["open_pnl"] = round(sum(float(p.get("pnl_usdt", 0) or 0) for p in positions), 4)
        data["open_margin_used"] = round(sum(float(p.get("invest_usdt", 0) or 0) for p in positions), 4)
        if data.get("stats_mode") == "paper":
            closed = float(data.get("today_pnl_usdt") or 0.0)
            data["closed_pnl_usdt"] = round(closed, 4)
            data["today_total_usdt"] = round(closed + data["open_pnl"], 4)
            try:
                data["period_pnl"] = trade_store.get_period_stats()   # Today / 7D / 30D, closed only
            except Exception:
                data["period_pnl"] = None
        else:
            data["closed_pnl_usdt"] = None
            data["today_total_usdt"] = None
            data["period_pnl"] = None
    except Exception:
        data["open_pnl"] = 0.0
        data["open_margin_used"] = 0.0

    data["bot2"] = None            # Bot 2 removed (key kept so an old app build does not crash)
    data.pop("bot2_open_positions", None)

    feed_ts = data.get("feed_last_update_ts")
    data["feed_age_sec"] = (data["server_ts"] - feed_ts) if feed_ts else None
    return data


# The status / system / ops / load_report routes moved to api/status.py (NEXT-6f). Included HERE so the route order stays the same.
app.include_router(_status_system_router(_display_status, DATA_DIR))




# ---------------------------------------------------------------- AI keys: paste a key, the backend detects whose it is
from api.ai_book import make_router_keys as _ai_keys_router, make_router_book as _ai_book_router
app.include_router(_ai_keys_router(require_api_token, DATA_DIR))




# The positions / market / signals / BTC / daily-report routes moved to api/status.py (NEXT-6f). Included HERE so the route order stays the same.
app.include_router(_status_market_router(_display_status, _bot_arg))




# ---------------------------------------------------------------- Vision AI (ai_vision.py)
# The 17 /api/vision/* routes moved to api/vision.py (NEXT-6b). Included HERE so the route order stays the same.
from api.vision import make_router as _vision_make_router
app.include_router(_vision_make_router(require_api_token))



# The alerts / history / equity / calendar / candles routes moved to api/status.py (NEXT-6f). Included HERE so the route order stays the same.
app.include_router(_status_history_router(_bot_arg))




# The settings / history backup routes moved to api/settings.py (NEXT-6e). Included HERE so the route order stays the same.
app.include_router(_st_settings_router(require_api_token, DATA_DIR))




# ---------------------------------------------------------------- writes ----

# The close / flatten / TP / SL / reconcile routes moved to api/trade.py (NEXT-6d). Included HERE so the route order stays the same.
from api.trade import make_router as _trade_make_router
app.include_router(_trade_make_router(require_api_token, _bot_arg))

# V2 read-only routes (owner OK "mount ok", 30 Oct). Each block is wrapped so a bad file never stops the backend.
# /api/v2/* data routes stay OFF (404 "off") until the file v2_api_enabled exists in the data folder.
try:
    from api.v2_data import make_router as _v2_data_router
    app.include_router(_v2_data_router(require_api_token, DATA_DIR))
except Exception as _e:
    print(f"[startup] v2 data routes skipped: {_e}")
# Safe close preview (read-only, closes nothing).
try:
    from api.preview_close import make_router as _v2_preview_router
    app.include_router(_v2_preview_router(require_api_token, _bot_arg))
except Exception as _e:
    print(f"[startup] v2 preview route skipped: {_e}")
# Fees + tax report route (Part 62, read-only, same v2_api_enabled switch).
try:
    from api.v2_reports_route import make_router as _v2_reports_router
    app.include_router(_v2_reports_router(require_api_token, DATA_DIR))
except Exception as _e:
    print(f"[startup] v2 fees+tax route skipped: {_e}")
# OwlSniper routes (Round 24, read-only, same v2_api_enabled switch; owner ok "mount ok" given). Each block is wrapped: a bad file never stops the backend.
try:
    from api.sniper import make_router as _sniper_router
    app.include_router(_sniper_router(require_api_token, DATA_DIR))
except Exception as _e:
    print(f"[startup] sniper routes skipped: {_e}")
try:
    from api.health_v2 import make_router as _sniper_health_router
    app.include_router(_sniper_health_router(require_api_token, DATA_DIR))
except Exception as _e:
    print(f"[startup] sniper health route skipped: {_e}")
# OwlSniper PAPER ENTER route + paper loop (Round 30, paper only, owner ok "mount ok" for all). Wrapped: a bad file never stops the backend.
try:
    from api.sniper_paper import make_router as _sniper_paper_router
    app.include_router(_sniper_paper_router(require_api_token, DATA_DIR))
except Exception as _e:
    print(f"[startup] sniper paper route skipped: {_e}")
# OwlSniper read-only routes of Parts 9-44 (bridge, risk box, capital, study list, self log). Owner said "mount ok" on 3 Nov 2026. One helper, each route wrapped inside it.
try:
    from api.sniper_mount import mount_all as _sniper_mount_all
    _sniper_mount_all(app, require_api_token, DATA_DIR)
except Exception as _e:
    print(f"[startup] sniper mount helper skipped: {_e}")
# Ledger routes (Part 41, read-only, same v2_api_enabled switch). Owner ok "mount ok" for Part 42.
try:
    from api.v2_ledger_route import make_router as _v2_ledger_router
    app.include_router(_v2_ledger_router(require_api_token, DATA_DIR))
except Exception as _e:
    print(f"[startup] v2 ledger routes skipped: {_e}")


app.include_router(_st_exchange_router(require_api_token))


# The AI ask / trade-audit / insights / doctor routes moved to api/ai_core.py (NEXT-6i). Included HERE so the route order stays the same.
from api.ai_core import make_router_ask as _ai_ask_router
app.include_router(_ai_ask_router())


# The lab / Dual Bot / archive / layers / Smart Brain routes moved to api/dual.py (NEXT-6c). Included HERE so the route order stays the same.
from api.dual import make_router as _dual_make_router
app.include_router(_dual_make_router(lambda mod: _safe_status(mod)))  # lambda: _safe_status is defined further down



# The report routes moved to api/ai_reports.py (NEXT-6i). Included HERE so the route order stays the same.
from api.ai_reports import make_router_reports as _ai_reports_router
app.include_router(_ai_reports_router())


# The Trade Book routes moved to api/ai_book.py (NEXT-6g). Included HERE so the route order stays the same.
_ai_book_r = _ai_book_router()
app.include_router(_ai_book_r)
ai_book_endpoint = _ai_book_r.ai_book_endpoint   # the SAME handler object: _swr_prewarm (start-up warm-up) calls it directly




def _safe_status(mod):
    try:
        import importlib
        return importlib.import_module("recovered_bot." + mod).status()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# The AI health / lab / reading / studies / desk / levels routes moved to api/ai_core.py (NEXT-6i). Included HERE so the route order stays the same.
from api.ai_core import make_router_lab as _ai_lab_router
_ai_lab_r = _ai_lab_router(lambda mod: _safe_status(mod))
ai_ab_board_endpoint = _ai_lab_r.ai_ab_board_endpoint   # the SAME handler objects: _swr_prewarm (start-up warm-up) calls them directly
ai_desk_endpoint = _ai_lab_r.ai_desk_endpoint
ai_levels_endpoint = _ai_lab_r.ai_levels_endpoint
app.include_router(_ai_lab_r)


# The AI Trade Diary routes (/api/ai/diary, /diary) moved to api/ai_pages.py (NEXT-6h part 1). Included HERE so the route order stays the same.
from api.ai_pages import make_router_diary as _ai_diary_router
app.include_router(_ai_diary_router())




# The AI observer / pick / self-signal / free-trade routes moved to api/ai_core.py (NEXT-6i). Included HERE so the route order stays the same.
from api.ai_core import make_router_observer as _ai_observer_router
_ai_observer_r = _ai_observer_router()
ai_observer_endpoint = _ai_observer_r.ai_observer_endpoint   # the SAME handler objects: _swr_prewarm (start-up warm-up) calls them directly
ai_pick_endpoint = _ai_observer_r.ai_pick_endpoint
app.include_router(_ai_observer_r)


# The AI Coach routes (/api/ai/coach, reset, plan/config, coach/config, /coach page) moved to api/ai_pages.py (NEXT-6h part 2). Included HERE so the route order stays the same.
from api.ai_pages import make_router_coach as _ai_coach_router
_ai_coach_r = _ai_coach_router(require_api_token)
ai_coach_endpoint = _ai_coach_r.ai_coach_endpoint   # the SAME handler object: _swr_prewarm (start-up warm-up) calls it directly
app.include_router(_ai_coach_r)


# The AI desk / A-B reset, advice, learning, backup and AI Live routes moved to api/ai_live.py (NEXT-6i). Included HERE (a, then b, then the chats router) so the route order stays the same.
from api.ai_live import make_router_tools as _ai_tools_router, make_router_live as _ai_live_router
_ai_tools_r = _ai_tools_router(require_api_token)
ai_advice_endpoint = _ai_tools_r.ai_advice_endpoint   # the SAME handler object: _swr_prewarm (start-up warm-up) calls it directly
app.include_router(_ai_tools_r)
app.include_router(_ai_live_router(require_api_token))
# The AI shadow card, digest, history, chats and app-health routes moved to api/ai_chats.py (NEXT-6i). Included HERE so the route order stays the same.
from api.ai_chats import make_router_chats as _ai_chats_router
app.include_router(_ai_chats_router(DATA_DIR))


# -------------------------------------------------------------- websocket --
# ConnectionManager, the shared status loop and the /ws route moved to api/ws.py (NEXT-6j). The old names stay here as thin links.
import api.ws as _ws
from api.ws import manager, _dumps, ConnectionManager, MAX_SOCKETS, SEND_TIMEOUT_SEC, BROADCAST_INTERVAL_SEC


def _snapshot_msg():
    return _ws.snapshot_msg(_display_status)


async def _status_broadcaster():
    await _ws.status_broadcaster(_display_status)


app.include_router(_ws.make_router(_display_status))
