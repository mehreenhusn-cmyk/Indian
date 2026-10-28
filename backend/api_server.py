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


app.include_router(_st_exchange_router(require_api_token))


@app.post("/api/ai/ask")
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


@app.get("/api/ai/trade-audit-context")
async def ai_trade_audit_context():
    """Lightweight trade-audit summary (win/loss streak, best-performing
    session, most common exit triggers) computed from the last 50 closed
    trades' enriched telemetry (trade_store.py). Powers the AI Assistant's
    strategy/mistake-analysis answers, but also queryable directly."""
    return await asyncio.to_thread(trade_store.get_audit_summary, 50)


@app.get("/api/ai/insights")
async def ai_insights():
    """Structured strategy statistics for the Dashboard's AI Insights card
    (win rate by SD zone / session / direction / EMA slope / volume, MFE/MAE,
    weak coins). Computed by ai_stats.py from closed paper + live trades -
    the same numbers the AI Assistant is given. Never raises: an empty
    history just returns {"sample": 0, ...}."""
    if settings_store.get("live_trading_enabled", False):
        return {"sample": 0, "min_sample": 1, "low_sample": True, "live_mode": True}   # no paper statistics in LIVE mode
    return await _swr("insights", 20.0, ai_stats.build_insights, 200)


@app.get("/api/ai/doctor")
async def ai_doctor():
    """Strategy Doctor (strategy_doctor.py): which entries of the strategy lose / win, SD-rule test, loss story,
    price after exit. Read-only - it never changes the bot. Cached 60 s (reads the trade archive)."""
    try:
        from recovered_bot import strategy_doctor
        return await _swr("doctor", 60.0, strategy_doctor.build, 5000)
    except Exception as e:
        return {"ok": False, "sample": 0, "enough": False, "headline": ["Strategy Doctor is not available yet."],
                "error": f"{type(e).__name__}: {e}"}


# The lab / Dual Bot / archive / layers / Smart Brain routes moved to api/dual.py (NEXT-6c). Included HERE so the route order stays the same.
from api.dual import make_router as _dual_make_router
app.include_router(_dual_make_router(lambda mod: _safe_status(mod)))  # lambda: _safe_status is defined further down



@app.get("/api/report/save")
async def report_save():
    """App button: writes owl_report_<date>.txt into the phone's Download folder (see ai_report.save_to_downloads)."""
    try:
        from recovered_bot import ai_report
        return await asyncio.to_thread(ai_report.save_to_downloads)
    except Exception as e:
        return {"ok": False, "path": "", "bytes": 0, "hint": f"Report failed: {type(e).__name__}: {e}"}


@app.get("/api/report/app")
async def app_report():
    """Whole-app report text (ai_report.build_app_text): what the app is, dashboard, signals, alerts, AI, backend health, settings (no keys), known problems."""
    from fastapi.responses import PlainTextResponse
    try:
        from recovered_bot import ai_report
        txt = await asyncio.to_thread(ai_report.build_app_text)
    except Exception as e:
        txt = f"Report failed: {type(e).__name__}: {e}"
    return PlainTextResponse(txt, headers={"Content-Disposition": 'attachment; filename="owl_app_report.txt"'})


@app.get("/api/report/app_save")
async def app_report_save():
    try:
        from recovered_bot import ai_report
        return await asyncio.to_thread(ai_report.save_app_to_downloads)
    except Exception as e:
        return {"ok": False, "path": "", "bytes": 0, "hint": f"Report failed: {type(e).__name__}: {e}"}


@app.get("/api/report")
async def full_report():
    """ONE downloadable text file (ai_report.py): strategy, indicators, settings (no secrets), Doctor summary, Filter Lab results and the
    closed-trades table - to send to any AI. Read-only."""
    from fastapi.responses import PlainTextResponse
    try:
        from recovered_bot import ai_report
        txt = await asyncio.to_thread(ai_report.build_text)
    except Exception as e:
        txt = f"Report failed: {type(e).__name__}: {e}"
    return PlainTextResponse(txt, headers={"Content-Disposition": 'attachment; filename="owl_report.txt"'})


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


@app.get("/api/ai/health")
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


@app.get("/api/ai/pair_replay")
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


@app.get("/api/ai/lab")
async def ai_lab(refresh: bool = False):
    """Shadow Lab numbers (strategy replayed on 3m/5m/15m: which SD / Z-score / TSI / higher-timeframe
    scenarios won or lost). refresh=true asks for a rebuild in the background."""
    from recovered_bot import ai_shadow_lab
    return await asyncio.to_thread(ai_shadow_lab.build_lab, refresh)


@app.get("/api/ai/ab_board")
async def ai_ab_board_endpoint(tf: str = ""):
    """A/B scoreboard: bot as it is vs bot + TSI filter (simple rule and AI rule), forward test + history.
    Read-only (ai_ab_board.py) - never changes a trade."""
    from recovered_bot import ai_ab_board
    return await _swr(("ab_board", tf), 15.0, ai_ab_board.build, tf)


@app.get("/api/ai/reading")
async def ai_reading_endpoint(tf: str = ""):
    """Indicator reading: what MAIN chart / Z-score / TSI said at signal time, wrong-use habits, best and
    avoid combos with the exit AI found best there. Read-only (ai_reading.py) - never changes a trade."""
    from recovered_bot import ai_reading
    return await asyncio.to_thread(ai_reading.build, tf)


@app.get("/api/ai/exit_study")
async def ai_exit_study_endpoint(tf: str = ""):
    """Phase 2: per scenario, which exit rule (TP1..TP4 hold) did best in the Shadow Lab replay. Read-only."""
    from recovered_bot import ai_exit_study
    return await asyncio.to_thread(ai_exit_study.build, tf)


@app.get("/api/ai/wait_study")
async def ai_wait_study_endpoint(tf: str = ""):
    """Phase 3: repeat-SL coins, sideways entries, and 'enter only when Z and TSI both confirm'. Read-only."""
    from recovered_bot import ai_wait_study
    return await asyncio.to_thread(ai_wait_study.build, tf)


@app.get("/api/ai/recipe")
async def ai_recipe_endpoint(tf: str = ""):
    """The result page: which signals to take, where to exit, proven on newer data (or: nothing found). Read-only."""
    from recovered_bot import ai_recipe
    return await asyncio.to_thread(ai_recipe.build, tf)


@app.get("/api/ai/desk")
async def ai_desk_endpoint():
    """AI Desk: the AI's own virtual account next to the bot (LE / SKIP / WAIT per signal, its own hold/trail
    exit, AI vs bot on the same signals). Read-only toward the bot (ai_desk.py)."""
    from recovered_bot import ai_desk
    return await _swr("desk", 3.0, ai_desk.build)      # screens re-open often: cached, refreshed behind


@app.get("/api/ai/levels")
async def ai_levels_endpoint():
    """SD level / Z-SMA behaviour study (ai_level_study.py): bounce vs break counts per situation. Read-only, cached."""
    from recovered_bot import ai_level_study
    return await _swr("levels", 30.0, ai_level_study.build)


# The AI Trade Diary routes (/api/ai/diary, /diary) moved to api/ai_pages.py (NEXT-6h part 1). Included HERE so the route order stays the same.
from api.ai_pages import make_router_diary as _ai_diary_router
app.include_router(_ai_diary_router())




@app.get("/api/ai/observer")
async def ai_observer_endpoint():
    """'Agar AI bot ke har trade ko apne exit rules se manage karta': same entry/SL/TP, alag exit, bot ke saath
    compare + entry-vs-exit verdict (ai_observer.py). Read-only. Heavy replay runs in a worker thread, cached."""
    from recovered_bot import ai_observer
    return await _swr("observer", 30.0, ai_observer.build)


@app.get("/api/ai/pick")
async def ai_pick_endpoint():
    """AI Pick: TAKE / SKIP / WATCH on every bot signal, what the AI has proven so far, scoreboard (ai_pick.py). Read-only."""
    from recovered_bot import ai_pick
    return await _swr("pick", 10.0, ai_pick.build)


@app.get("/api/ai/selfsignal")
async def ai_selfsignal_endpoint():
    """Round B: the AI's own signals (shadow only, no trade is opened): gate status, finished results vs the bot, verdict (ai_selfsignal.py)."""
    from recovered_bot import ai_selfsignal
    return await _swr("selfsignal", 30.0, ai_selfsignal.build)


@app.get("/api/ai/free_trade")
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


@app.get("/api/ai/coach")
async def ai_coach_endpoint():
    """AI Coach: AI-managed virtual trades vs the bot on the same signals, learned indicator probabilities, memo (ai_coach.py).
    The answer carries "data_info": how old it is, whether the build is stuck and why, so the app can show the real cause."""
    from recovered_bot import ai_coach
    v = ai_coach.view()                     # ready answer from the coach's own 2 s thread: instant, never stale because of a busy pool
    info = ai_coach.view_info()
    if v is not None:
        if not info["stuck"]:
            return dict(v, data_info=info)
        # the coach thread is stuck: try ONE fresh build in the shared pool (max 8 s), else show the old answer + the reason
        try:
            fresh = await asyncio.wait_for(_swr("coach", 5.0, ai_coach.build), timeout=8.0)
            return dict(fresh, data_info=dict(info, fresh_build=True))
        except Exception:
            return dict(v, data_info=info)
    try:                                                 # only until the first build has finished after start-up
        out = await asyncio.wait_for(_swr("coach", 5.0, ai_coach.build), timeout=7.0)
    except Exception:                                    # still building: say so at once (the app retries by itself)
        return {"building": True, "pairs": [], "data_info": dict(info, building=True), "ts": time.time()}
    return dict(out, data_info=info) if isinstance(out, dict) else out


@app.post("/api/ai/coach/reset")
async def ai_coach_reset(_auth=Depends(require_api_token)):
    from recovered_bot import ai_coach
    _SWR.pop("coach", None)
    return await asyncio.to_thread(ai_coach.reset)


@app.post("/api/ai/plan/config")
async def ai_plan_config(payload: dict, _auth=Depends(require_api_token)):
    """The AI's day plan (paper only): target, loss cap, max open trades, give-back %. 0 = off."""
    from recovered_bot import ai_planner
    try:
        kw = {k: payload.get(k) for k in ("target_usdt", "loss_cap_usdt", "max_open", "giveback_pct") if payload.get(k) is not None}
        for k, v in kw.items():
            float(v)
    except Exception:
        raise HTTPException(status_code=400, detail="values must be numbers")
    _SWR.pop("coach", None)
    return await asyncio.to_thread(lambda: ai_planner.set_config(**kw))


@app.post("/api/ai/coach/config")
async def ai_coach_config(payload: dict, _auth=Depends(require_api_token)):
    """Virtual balance (USDT) the AI Coach manages margin with. 0 / empty = default (20 trades' margin)."""
    from recovered_bot import ai_coach
    try:
        bal = float(payload.get("balance") or 0)
    except Exception:
        raise HTTPException(status_code=400, detail="balance must be a number")
    _SWR.pop("coach", None)
    return await asyncio.to_thread(ai_coach.set_balance, bal)


_COACH_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OWL AI Coach</title><style>
body{font-family:system-ui,sans-serif;margin:0;padding:12px;background:#f2f3f7;color:#14161c}
h1{font-size:18px;margin:4px 0 8px}h2{font-size:13px;margin:14px 0 6px;color:#667}.c{background:#fff;border-radius:12px;padding:12px;margin:0 0 8px;box-shadow:0 1px 3px #0001}
.g{color:#0a8f4f}.r{color:#d0273a}.m{color:#667}.s{font-size:12px}.b{font-weight:700}.big{font-size:22px;font-weight:800}
.row{display:flex;justify-content:space-between;gap:8px}.col{flex:1}.w{background:#fff4e0;border-left:4px solid #e08a00}
.pill{display:inline-block;font-size:11px;padding:1px 6px;border-radius:8px;background:#eef;margin:1px}.pw{background:#dff5e8}.pa{background:#fde3e6}
</style></head><body><h1>OWL AI Coach</h1><div class="s m" id="t">load ho raha hai...</div>
<div id="cmp" class="c"></div><h2>AI KE ABHI KHULE TRADE</h2><div id="op"></div>
<h2>AI NE KHUD KYA DHUNDHA (indicators ke combos)</h2><div id="tb" class="c"></div>
<h2>MEMO (kab kya hua)</h2><div id="me" class="c"></div><h2>BAND TRADE: AI vs BOT</h2><div id="cl"></div>
<script>
const P=v=>(v>=0?'+':'')+Number(v).toFixed(1)+'%',U=v=>(v>=0?'+':'')+Number(v).toFixed(2),C=v=>v>0?'g':(v<0?'r':'m');
const T=ts=>{const d=new Date((ts+19800)*1000);return d.toISOString().slice(11,16)};
const pill=(k,v)=>`<span class="pill ${v=='WITH'?'pw':'pa'}">${k} ${v=='WITH'?'saath':'khilaf'}</span>`;
async function go(){try{const d=await (await fetch('/api/ai/coach')).json();
document.getElementById('t').textContent='Update: '+new Date().toLocaleTimeString()+' - har 30 sec me khud badalta hai';
const c=d.compare;
document.getElementById('cmp').innerHTML=c.n==0?`<div class="b">DATA JAMA HO RAHA HAI 0/${d.min_n}</div><div class="s m">AI ke ${c.open} trade khule hain. Pehle trade band hone par yahan AI vs Bot dikhega.</div>`:
`<div class="row"><div class="col"><div class="s m">AI (khud manage)</div><div class="big ${C(c.ai_pnl)}">${U(c.ai_pnl)}</div><div class="s m">jeet ${c.ai_wins}/${c.n}</div></div>
<div class="col"><div class="s m">BOT akela</div><div class="big ${C(c.bot_pnl)}">${U(c.bot_pnl)}</div><div class="s m">jeet ${c.bot_wins}/${c.n}</div></div></div>
<div class="s m" style="margin-top:6px">USDT, ${c.n} same signal par. ${c.ready?'':'<b>JAMA HO RAHA HAI '+c.n+'/'+d.min_n+' - abhi verdict nahi.</b>'} Sideways (30+ min, kuch nahi mila): ${d.sideways.n} trade${d.sideways.n?', avg '+d.sideways.avg_min+' min':''}.</div>`;
const M=d.margin;document.getElementById('cmp').innerHTML+=`<div class="s m" style="margin-top:8px">MARGIN: balance ${M.balance}${M.custom?'':' (default 20 trade)'} | har trade ${M.per_trade} | free ${M.free} | ${M.open}/${M.slots} slot | skip ${M.skipped} | jagah banane ke liye band ${M.freed}</div>`;
document.getElementById('op').innerHTML=(d.open.length?'':'<div class="c s m">Abhi koi AI trade khula nahi.</div>')+d.open.map(x=>`<div class="c"><span class="b">${x.sym} ${x.side=='BUY'?'LONG':'SHORT'}</span> <span class="b ${C(x.roi)}">${P(x.roi)}</span> <span class="s m">peak ${P(x.peak)} | TP${x.hit||'-'} | ${x.min} min${x.be?' | SL entry par':''}</span>
<div>${(x.facts||[]).map(f=>`<span class="pill">${f}</span>`).join('')||'<span class="s m">indicator: pehli closed candle ka wait</span>'}</div></div>`).join('');
const L=d.learned,row=(x,cl)=>`<div class="row s"><span>${x.text}</span><span class="${cl}">${x.p}% (${x.n})</span></div>`;
document.getElementById('tb').innerHTML=`<div class="s m">${L.samples} candle samples | normal: ${L.base}% baar trade ke saath | ${L.trusted} situation ke ${L.min_n}+ cases</div>`+
(L.best.length?'<div class="b s g" style="margin-top:6px">TRADE KE SAATH JAATE HAIN</div>'+L.best.map(x=>row(x,'g')).join(''):'')+
(L.worst.length?'<div class="b s r" style="margin-top:6px">PHIR PALAT JAATE HAIN</div>'+L.worst.map(x=>row(x,'r')).join(''):'')+
(L.best.length+L.worst.length?'':'<div class="s b" style="margin-top:6px">JAMA HO RAHA HAI - abhi koi situation '+L.min_n+' cases tak nahi pahunchi</div>');
document.getElementById('me').innerHTML=d.memo.map(x=>`<div class="s"><span class="m">${T(x.t)}</span> ${x.text}</div>`).join('')||'<div class="s m">Abhi memo khali.</div>';
document.getElementById('cl').innerHTML=d.closed.map(x=>`<div class="c"><span class="b">${x.sym} ${x.side=='BUY'?'LONG':'SHORT'}</span> AI <span class="b ${C(x.roi)}">${P(x.roi)}</span> | Bot ${x.bot_roi===null?'<span class="m">abhi khula</span>':'<span class="b '+C(x.bot_roi)+'">'+P(x.bot_roi)+'</span>'} <span class="s m">| peak ${P(x.peak)} | ${T(x.t0)}</span>
<div class="s">${x.reason}${x.mode&&x.mode!='-'?' ['+x.mode+']':''}</div>${x.after?'<div class="s m">'+x.after+'</div>':'<div class="s m">band ke baad price dekh raha hai...</div>'}</div>`).join('');
}catch(e){document.getElementById('t').textContent='Backend se connect nahi hua: '+e}}
go();setInterval(go,30000);
</script></body></html>"""


@app.get("/coach")
async def ai_coach_page():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_COACH_HTML)


@app.post("/api/ai/desk/reset")
async def ai_desk_reset(_auth=Depends(require_api_token)):
    """Clear only the AI's virtual account and start counting again. The bot is untouched."""
    from recovered_bot import ai_desk
    _SWR.pop("desk", None)
    return await asyncio.to_thread(ai_desk.reset)


@app.get("/api/ai/advice")
async def ai_advice_endpoint():
    """Phase 4: advice badge per open position (display only - nothing is blocked or closed)."""
    if not settings_store.get("legacy_ai_enabled", False):
        return {}                      # the older AI modules are off: no badges, no work
    from recovered_bot import ai_advice
    return await _swr("advice", 3.0, ai_advice.current)


@app.post("/api/ai/ab_board/reset")
async def ai_ab_board_reset(_auth=Depends(require_api_token)):
    """Start the forward test again from now (the AI rule is mined again from everything older)."""
    from recovered_bot import ai_ab_board
    for k in [k for k in _SWR if isinstance(k, tuple) and k[0] == "ab_board"]:
        _SWR.pop(k, None)
    return await asyncio.to_thread(ai_ab_board.reset)


@app.get("/api/ai/learning")
async def ai_learning_endpoint(refresh: bool = False):
    """What the AI has learned about the EMA50 strategy: timeline, WORKS / FAILS / UNCERTAIN with evidence
    status, TP funnel + stalls, timeframe + higher-timeframe agreement. Read-only, historical only."""
    from recovered_bot import ai_learning
    return await asyncio.to_thread(ai_learning.build, refresh)


@app.get("/api/ai/backup")
async def ai_backup_status():
    """The AI data backups: list, last time, any error."""
    from recovered_bot import ai_backup
    return await asyncio.to_thread(ai_backup.status)


@app.post("/api/ai/backup/run")
async def ai_backup_run(_auth=Depends(require_api_token)):
    """Make a backup of the AI data right now."""
    from recovered_bot import ai_backup
    r = await asyncio.to_thread(lambda: ai_backup.run("manual"))
    return {**r, "status": ai_backup.status()}


@app.post("/api/ai/backup/restore")
async def ai_backup_restore(payload: dict, _auth=Depends(require_api_token)):
    """Queue a restore of one backup. It is applied at the next backend start (never into a running AI)."""
    from recovered_bot import ai_backup
    r = await asyncio.to_thread(lambda: ai_backup.restore(str(payload.get("name") or "")))
    return {**r, "status": ai_backup.status()}


@app.get("/api/ai/live")
async def ai_live_status(_auth=Depends(require_api_token)):
    """STAGE 2: the AI's real account: switch, limits, key (masked), open and closed real trades, events."""
    from recovered_bot import ai_live_executor
    return await asyncio.to_thread(ai_live_executor.status)


@app.post("/api/ai/live/keys")
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


@app.post("/api/ai/live/keys/clear")
async def ai_live_keys_clear(_auth=Depends(require_api_token)):
    from recovered_bot import ai_live_keys, ai_live_guard
    ai_live_guard.disable()
    return {"ok": await asyncio.to_thread(ai_live_keys.clear)}


@app.post("/api/ai/live/check")
async def ai_live_check(_auth=Depends(require_api_token)):
    from recovered_bot import ai_live_executor
    return await asyncio.to_thread(ai_live_executor.verify)


@app.post("/api/ai/live/config")
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


@app.post("/api/ai/live/enable")
async def ai_live_enable(payload: dict, _auth=Depends(require_api_token)):
    """Switch real trading for the AI ON. Needs the exact confirm text, a fresh connection check, margin and daily loss cap."""
    from recovered_bot import ai_live_guard, ai_live_keys
    ok, why = ai_live_guard.enable(payload.get("confirm"), ai_live_keys.has_keys())
    return {"ok": ok, "why": why}


@app.post("/api/ai/live/disable")
async def ai_live_disable(_auth=Depends(require_api_token)):
    """Stops NEW real trades. Real trades already open stay protected and are closed by the AI as usual."""
    from recovered_bot import ai_live_guard
    ai_live_guard.disable()
    return {"ok": True}


@app.post("/api/ai/live/panic")
async def ai_live_panic(_auth=Depends(require_api_token)):
    """PANIC: halt, cancel every stop and close every position on the AI account."""
    from recovered_bot import ai_live_executor
    return await asyncio.to_thread(ai_live_executor.panic)


@app.post("/api/ai/live/reset")
async def ai_live_reset(_auth=Depends(require_api_token)):
    """Clear a HALT after the owner has looked at why it happened."""
    from recovered_bot import ai_live_guard
    ai_live_guard.reset_halt()
    return {"ok": True}


@app.post("/api/ai/lab/replay")
async def ai_lab_replay(_auth=Depends(require_api_token)):
    """Replay the last days again for every coin (already-saved signals are never duplicated)."""
    from recovered_bot import ai_shadow_lab
    return {"ok": ai_shadow_lab.request_replay(), "status": ai_shadow_lab.status()}


@app.get("/api/ai/shadow")
async def ai_shadow_endpoint():
    """OWNER-ONLY screen card: has the ML model's quiet guess at trade-open matched the real
    result? (ai_ml.shadow_stats). These numbers are never given to the chat AI (see ai_guard)."""
    from recovered_bot import ai_ml
    return await asyncio.to_thread(ai_ml.shadow_stats)


@app.post("/api/ai/digest/send")
async def ai_digest_send():
    """Send today's AI digest to Telegram right now (same text as the nightly one)."""
    from recovered_bot import ai_digest
    return await asyncio.to_thread(ai_digest.send_now)


@app.get("/api/ai/history")
async def ai_history(chat_id: str = ""):
    """Messages for one chat (or the active chat). Also returns multi-chat list."""
    cid = chat_id or None
    msgs = await asyncio.to_thread(ai_chat_store.get_history, 200, cid)
    listing = await asyncio.to_thread(ai_chat_store.list_chats)
    active = listing.get("active")
    mode = await asyncio.to_thread(ai_chat_store.get_mode, cid or active)
    return {"messages": msgs, "chats": listing.get("chats") or [], "active": active, "mode": mode}


@app.post("/api/ai/history/clear")
async def ai_history_clear(payload: dict = None):
    """Clear messages of one chat (body: {chat_id?}) or the active chat."""
    payload = payload or {}
    cid = payload.get("chat_id")
    await asyncio.to_thread(ai_chat_store.clear, cid)
    return {"ok": True}


@app.get("/api/ai/chats")
async def ai_chats_list():
    return await asyncio.to_thread(ai_chat_store.list_chats)


@app.post("/api/ai/chats")
async def ai_chats_create(payload: dict = None):
    payload = payload or {}
    return await asyncio.to_thread(
        ai_chat_store.create_chat, payload.get("mode") or "general", payload.get("title") or ""
    )


@app.post("/api/ai/chats/rename")
async def ai_chats_rename(payload: dict):
    return await asyncio.to_thread(ai_chat_store.rename_chat, payload.get("chat_id"), payload.get("title") or "")


@app.post("/api/ai/chats/delete")
async def ai_chats_delete(payload: dict):
    return await asyncio.to_thread(ai_chat_store.delete_chat, payload.get("chat_id"))


@app.post("/api/ai/chats/active")
async def ai_chats_active(payload: dict):
    return await asyncio.to_thread(ai_chat_store.set_active, payload.get("chat_id"))


@app.get("/api/ai/app_health")
async def ai_app_health_report():
    """Plain health report for the AI assistant / debugging (freezes, REST, data)."""
    from recovered_bot import ai_health
    return await asyncio.to_thread(ai_health.build_report, DATA_DIR)


# -------------------------------------------------------------- websocket --

MAX_SOCKETS = 3
SEND_TIMEOUT_SEC = 10.0  # a client that can't take one frame in 10s (40 ticks) is dropped, not waited on (was 4s: a short phone hiccup cut the socket)


class ConnectionManager:
    """Each connection gets its OWN asyncio.Lock, held around every send to
    that socket - both the shared broadcaster below AND that connection's
    own reader() (for ping/pong, resync) write through send_to(), so two
    tasks can never write to the same WebSocket at the same time (a raw
    concurrent send_text() from two tasks is not safe)."""

    def __init__(self):
        self.active_connections: dict[WebSocket, asyncio.Lock] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[websocket] = asyncio.Lock()
        # The app only ever needs ONE live socket. After a stall it can leave several half-dead ones behind;
        # keep the newest MAX_SOCKETS and close the older ones so they stop eating every 250 ms tick.
        while len(self.active_connections) > MAX_SOCKETS:
            old_ws = next(iter(self.active_connections))
            self.active_connections.pop(old_ws, None)
            try:
                await old_ws.close()
            except Exception:
                pass

    def disconnect(self, websocket: WebSocket):
        self.active_connections.pop(websocket, None)

    async def send_to(self, websocket: WebSocket, message: str):
        conn_lock = self.active_connections.get(websocket)
        if conn_lock is None:
            return
        async with conn_lock:
            await websocket.send_text(message)

    async def _send_guarded(self, websocket: WebSocket, message: str) -> bool:
        try:
            await asyncio.wait_for(self.send_to(websocket, message), timeout=SEND_TIMEOUT_SEC)
            return True
        except Exception:
            # Dead or too-slow client: drop it so it can never hold up the
            # price/PnL stream for everyone else. The app auto-reconnects and
            # immediately gets a FULL_STATE_SNAPSHOT, so nothing is lost.
            self.disconnect(websocket)
            try:
                await websocket.close()
            except Exception:
                pass
            return False

    async def broadcast(self, message: str):
        """Sends to all clients CONCURRENTLY (was one-by-one with no timeout,
        so one stalled socket delayed every other client's tick).
        Returns (clients_targeted, clients_dropped)."""
        conns = list(self.active_connections.keys())
        if not conns:
            return 0, 0
        if len(conns) == 1:
            results = [await self._send_guarded(conns[0], message)]
        else:
            results = await asyncio.gather(*(self._send_guarded(c, message) for c in conns))
        return len(conns), results.count(False)


manager = ConnectionManager()

# PRODUCTION HARDENING - CPU/bandwidth throttle for the 1s status broadcast.
# The old code ran a full writer() loop PER CONNECTED WEBSOCKET - so N
# connected devices/tabs meant N redundant _display_status() computations
# every second, and (whenever LIVE trading is on) N simultaneous blocking
# REST calls to the exchange every second, each one stalling the event
# loop for its round-trip. Now there is exactly ONE shared loop no matter
# how many clients are connected, the exchange call runs off the event
# loop thread (asyncio.to_thread), the work is skipped entirely when
# nobody is listening, and two payload fields that rarely change
# tick-to-tick (alerts, watchlist) are only re-sent when they actually
# changed - same trick the alerts_rev check already used, now extended to
# watchlist too. Update cadence itself is left at 1s on purpose (Part 4's
# live LTP/ticker feed must stay live-feeling) - the fix is doing that
# work once and non-blockingly, not doing it less often.
BROADCAST_INTERVAL_SEC = 0.25   # was 1.0 - matches the ~250ms kline/last-price feed so the app is not a second behind Binance
_last_broadcast_watchlist = None


async def _status_broadcaster():
    global _last_broadcast_watchlist
    last_alerts_rev = None
    while True:
        # Live-trading mode makes a real exchange REST call every tick
        # (_display_status -> get_open_positions) - keep that at 1s so the
        # faster paper/price cadence never hammers the exchange rate limit.
        await asyncio.sleep(
            max(BROADCAST_INTERVAL_SEC, 1.0)
            if settings_store.get("live_trading_enabled", False)
            else BROADCAST_INTERVAL_SEC
        )
        if not manager.active_connections:
            continue  # nobody listening right now - skip all the work below
        _t0 = time.perf_counter()
        # Alerts (up to 250 detail dicts) rarely change - don't even COPY them
        # on ticks where the revision is unchanged (they used to be deep-copied
        # 4x/sec and then popped). Price / positions / PnL are untouched.
        _skip = ("alerts",) if status.alerts_rev() == last_alerts_rev else ()
        try:
            if settings_store.get("live_trading_enabled", False):
                # _display_status() hits exchange.get_open_positions() (a real
                # network call) in this branch - never run that directly on
                # the event loop that every websocket/HTTP request shares.
                data = await asyncio.to_thread(_display_status, _skip)
            else:
                data = _display_status(_skip)
        except Exception:
            continue
        if not _skip:
            last_alerts_rev = data.get("alerts_rev")
        wl = data.get("watchlist")
        if wl == _last_broadcast_watchlist:
            data.pop("watchlist", None)
        else:
            _last_broadcast_watchlist = wl
        _t1 = time.perf_counter()
        _msg = _dumps({"type": "update", "data": data})
        _dumps_ms = (time.perf_counter() - _t1) * 1000.0      # how long the JSON text takes to build (shows in the load report)
        _build_ms = (time.perf_counter() - _t0) * 1000.0
        _n, _dropped = await manager.broadcast(_msg)
        telemetry.record_broadcast((time.perf_counter() - _t0) * 1000.0, len(_msg), _n,
                                   build_ms=_build_ms, dropped=_dropped, dumps_ms=_dumps_ms)


def _dumps(obj):
    return json.dumps(obj, default=str)


def _snapshot_msg():
    """FULL_STATE_SNAPSHOT: the complete status dict (open positions with live
    PnL, alerts, movers, stats...). Sent on every (re)connect and on request,
    so the app replaces its state wholesale instead of trusting whatever it
    had before the connection dropped."""
    return _dumps({"type": "init", "kind": "FULL_STATE_SNAPSHOT", "data": _display_status()})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    async def send(text):
        await manager.send_to(websocket, text)

    async def reader():
        # Client sends {"type":"ping"} every ~5s (latency + liveness) and may
        # send {"type":"resync"} to ask for a fresh full snapshot.
        while True:
            msg = await websocket.receive_text()
            try:
                kind = json.loads(msg).get("type")
            except (json.JSONDecodeError, AttributeError):
                continue
            if kind == "ping":
                await send(_dumps({"type": "pong", "server_ts": time.time()}))
            elif kind == "resync":
                await send(await asyncio.to_thread(_snapshot_msg))

    # Periodic "update" messages now come from the single shared
    # _status_broadcaster() task (started once at server startup) instead
    # of a per-connection writer() loop - see its docstring above for why.
    # This connection's own task just accepts the initial snapshot + reads
    # client pings/resyncs until it disconnects.
    try:
        await send(await asyncio.to_thread(_snapshot_msg))
        await reader()
    except Exception:
        pass
    finally:
        manager.disconnect(websocket)
