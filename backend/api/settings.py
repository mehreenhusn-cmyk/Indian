"""api/settings.py - settings, history backup, Binance test and exchange routes, moved out of api_server.py (NEXT-6e).

GET / POST /api/settings (secrets masked), POST /api/backup/export, POST /api/binance/test-connection,
GET /api/exchange, POST /api/exchange/switch. Same code, same paths, same order. Two factories because the trade router
(api/trade.py) sits between the backup route and the Binance test route in api_server.py.
"""
import asyncio
import os
import time

from fastapi import APIRouter, Depends

from recovered_bot import settings_store, status, timeframe_manager, exchange


def make_router_settings(require_api_token, data_dir):
    """settings (GET / POST), history backup. require_api_token and data_dir are api_server's own (passed in)."""
    r = APIRouter()
    DATA_DIR = data_dir

    # PRODUCTION HARDENING - these settings keys hold real secrets (exchange
    # API secrets, Telegram bot token). GET /api/settings used to return them
    # to the frontend in plain text; now it returns a masked placeholder
    # string (kept as a STRING, not a boolean - settings_screen.dart reads
    # these fields as text to prefill them and to compute the Telegram
    # "linked"/"not linked" status, so changing the type here would crash
    # that screen). POST /api/settings drops any incoming value that still
    # looks like our own mask, so opening Settings and hitting Save without
    # touching a secret field can never overwrite the real stored secret with
    # the masked placeholder.
    _SETTINGS_SECRET_KEYS = ("binance_api_secret", "telegram_bot_token", "ai2_api_key", "ai3_api_key", "ai4_api_key",
                             "ai5_api_key", "ai6_api_key", "ai7_api_key", "ai8_api_key")
    _SECRET_MASK_PREFIX = "\u2022\u2022\u2022\u2022"  # "••••"


    def _mask_settings(all_settings: dict) -> dict:
        out = dict(all_settings)
        for key in _SETTINGS_SECRET_KEYS:
            val = out.get(key)
            out[key] = (_SECRET_MASK_PREFIX + str(val)[-4:]) if val else ""
        return out


    @r.get("/api/settings")
    async def get_settings(_auth=Depends(require_api_token)):
        return _mask_settings(settings_store.get_all())


    @r.post("/api/settings")
    async def update_settings(payload: dict, _auth=Depends(require_api_token)):
        clean_payload = {
            k: v for k, v in payload.items()
            if not (k in _SETTINGS_SECRET_KEYS and isinstance(v, str) and v.startswith(_SECRET_MASK_PREFIX))
        }
        settings_store.update(**clean_payload)
        if "live_trading_enabled" in clean_payload:
            try:
                status.touch_alerts()          # LIVE/PAPER switched: the Alerts feed is re-sent (live-only or paper view)
            except Exception:
                pass
        # A "timeframe" change must take effect on THIS running process
        # immediately, not just on next restart - settings_store.update() above
        # only persists it to disk. timeframe_manager caches the active
        # timeframe in memory (that cache is what app.py's candle fetch,
        # market_ws's kline subscriptions and signal generation actually read),
        # so it must be told explicitly. set_active_timeframe() also re-persists
        # the normalized value, which is harmless/idempotent here.
        if "timeframe" in clean_payload:
            timeframe_manager.set_active_timeframe(clean_payload["timeframe"])
        return _mask_settings(settings_store.get_all())


    # ------------------------------------------------------- history backup ----
    # Files worth keeping if the phone/Termux is wiped. settings.json (API keys)
    # and owl.db are deliberately NOT included - only trade/alert/AI history.
    _BACKUP_FILES = ("closed_trades_archive.jsonl", "trades.json", "alerts.json", "ai_chat_history.json")


    def _build_backup_zip():
        import zipfile
        os.makedirs(os.path.join(DATA_DIR, "exports"), exist_ok=True)
        out = os.path.join(DATA_DIR, "exports", f"owl_history_{time.strftime('%Y%m%d_%H%M%S')}.zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name in _BACKUP_FILES:
                src = os.path.join(DATA_DIR, name)
                if os.path.exists(src):
                    z.write(src, name)
        exp = os.path.join(DATA_DIR, "exports")
        for old_f in sorted(os.listdir(exp))[:-5]:          # keep the last 5 exports only
            try:
                os.remove(os.path.join(exp, old_f))
            except OSError:
                pass
        return out


    @r.post("/api/backup/export")
    async def export_backup(_auth=Depends(require_api_token)):
        """Zip the trade/alert/AI history and send it to the user's Telegram chat
        (same bot token / chat id as the signal alerts). Button-initiated only."""
        from recovered_bot.app import bot as _tg

        def _run():
            path = _build_backup_zip()
            size_kb = os.path.getsize(path) / 1024.0
            ok, msg = _tg.send_document(path, f"OWL history backup - {time.strftime('%d %b %Y %H:%M')} ({size_kb:.0f} KB)")
            return {"ok": ok, "message": msg, "file": os.path.basename(path), "size_kb": round(size_kb, 1)}

        return await asyncio.to_thread(_run)

    return r


def make_router_exchange(require_api_token):
    """Binance test connection + exchange get / switch."""
    r = APIRouter()

    @r.post("/api/binance/test-connection")
    async def binance_test_connection(_auth=Depends(require_api_token)):
        """Called from Settings' 'Test Connection' button - authenticates with
        whatever Binance API key/secret are currently saved in Settings and
        reads the futures USDT balance, without placing any order. Does NOT
        require live_trading_enabled to be on."""
        from recovered_bot import binance_trader
        result = await asyncio.to_thread(binance_trader.test_connection)
        return result


    @r.get("/api/exchange")
    async def get_exchange():
        """Current active exchange + which ones this app supports - drives the
        drawer's Exchange Selector and Settings' exchange toggle."""
        return {"active": exchange.active(), "supported": list(exchange.SUPPORTED)}


    @r.post("/api/exchange/switch")
    async def switch_exchange(payload: dict, _auth=Depends(require_api_token)):
        """Flips settings_store["active_exchange"] and forces an IMMEDIATE
        watchlist + live-price-feed refresh (instead of waiting out their normal
        ~10s/2s poll intervals), so the Exchange Selector genuinely feels
        instant rather than "eventually catches up"."""
        target = (payload.get("exchange") or "").strip().lower()
        if target not in exchange.SUPPORTED:
            return {"ok": False, "error": f"exchange must be one of {list(exchange.SUPPORTED)}"}
        settings_store.update(active_exchange=target)
        # Next refresh_watchlist() tick (app.py polls every WATCHLIST_REFRESH_INTERVAL)
        # will now see stale symbols from the old exchange and swap the whole
        # watchlist over immediately instead of waiting for the interval to elapse.
        try:
            from recovered_bot import app as bot_app
            bot_app.last_watchlist_refresh = 0
        except Exception:
            pass
        return {"ok": True, "active": target}

    return r
