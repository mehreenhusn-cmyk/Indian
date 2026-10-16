import os
import threading
import time
from datetime import datetime, timezone

import requests

from . import status
from . import settings_store

BOT_NAME_DEFAULT = "HUSSAIN"  # overridable via settings key "bot_name"


class TelegramNotifier:
    def __init__(self, bot_token, chat_id):
        # Constructor values are only a fallback: app.py builds this object at
        # import time, BEFORE settings_store.init() has loaded settings.json, so
        # a token saved in the app's Settings would never be seen. Credentials
        # are re-read on every send instead (see _creds()).
        self.bot_token = bot_token or ""
        self.chat_id = chat_id or ""
        self.signal_count = 0
        print(f"[Telegram] Initialized (credentials are read from env/Settings at send time)")

    def _creds(self):
        token = (os.getenv("BOT_TOKEN") or settings_store.get("telegram_bot_token", "") or self.bot_token or "").strip()
        chat = (os.getenv("CHAT_ID") or settings_store.get("telegram_chat_id", "") or self.chat_id or "").strip()
        return token, chat

    @staticmethod
    def _mover_info(symbol):
        """(type, rank, pct) of `symbol` in the current top-10 gainers/losers
        list (same list the app's Market screen shows), else None."""
        gainers = losers = 0
        for m in (status.get().get("market_movers") or []):
            is_gainer = m.get("category") == "gainer"
            if is_gainer:
                gainers += 1
            else:
                losers += 1
            if m.get("symbol") == symbol:
                return ("Gainer" if is_gainer else "Loser",
                        gainers if is_gainer else losers,
                        float(m.get("change_pct") or 0.0))
        return None

    def _format_signal(self, signal):
        """Same card as scanner/5mins_scanner_binance_top10_bothside.py::format_signal."""
        is_long = signal.action.upper() == "BUY"
        entry = float(signal.entry_price)
        sl = float(signal.stop_loss)

        def pct(tp):  # direction-aware, like the scanner
            tp = float(tp)
            return ((tp - entry) if is_long else (entry - tp)) / entry * 100 if entry else 0.0

        sl_pct = ((entry - sl) if is_long else (sl - entry)) / entry * 100 if entry else 0.0

        try:
            from . import market_ws
            live_price = market_ws.get_best_live_price(signal.symbol)[0]
        except Exception:
            live_price = None
        if live_price is None:
            live_price = entry

        try:
            candle_utc = datetime.strptime(signal.signal_time, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            candle_utc = str(signal.signal_time)

        mover = self._mover_info(signal.symbol)
        market_label = f"{mover[0]} #{mover[1]}" if mover else "-"
        pct24h = f"{mover[2]:+.3f}%" if mover else "-"
        timeframe_label = settings_store.get("timeframe", "5m") or "5m"
        bot_name = settings_store.get("bot_name", BOT_NAME_DEFAULT) or BOT_NAME_DEFAULT
        chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{signal.symbol}.P"

        lines = [
            "🟢 LONG SIGNAL" if is_long else "🔴 SHORT SIGNAL",
            "--------------------------",
            f"Symbol    : {signal.symbol}",
            f"Timeframe : {timeframe_label}",
            f"Market    : {market_label}",
            f"Binance 24h: {pct24h}",
            "--------------------------",
            f"Entry      : {entry:.8f}",
            f"Live Price : {float(live_price):.8f}",
            f"Stop Loss  : {sl:.8f} ({sl_pct:.2f}%)",
            f"TP1        : {float(signal.tp1):.8f} ({pct(signal.tp1):.2f}%)",
            f"TP2        : {float(signal.tp2):.8f} ({pct(signal.tp2):.2f}%)",
            f"TP3        : {float(signal.tp3):.8f} ({pct(signal.tp3):.2f}%)",
            f"TP4        : {float(signal.tp4):.8f} ({pct(signal.tp4):.2f}%)",
            "--------------------------",
            f"Candle UTC : {candle_utc}",
            f"Chart      : {chart_url}",
            f"Bot        : {bot_name}",
        ]
        return "\n".join(lines)

    def _post_signal(self, text, symbol, action, entry):
        token, chat = self._creds()
        print(f"[Telegram] Sending signal: {symbol} - {action} @ {entry}")
        status.update(telegram_last_attempt_ts=time.time())
        if not token or not chat:
            status.update(telegram_last_ok=False, telegram_last_error="Bot Token / Chat ID not set in Settings")
            return
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            resp = requests.post(
                url,
                data={"chat_id": chat, "text": text, "disable_web_page_preview": True},
                timeout=10,
            )
            if resp.status_code == 200:
                status.update(telegram_last_ok=True, telegram_last_error=None)
            else:
                print(f"[Telegram] Send failed: {resp.status_code} - {resp.text}")
                status.update(telegram_last_ok=False, telegram_last_error=f"HTTP {resp.status_code}: {resp.text[:150]}")
        except Exception as e:
            print(f"[Telegram] Send error: {e}")
            status.update(telegram_last_ok=False, telegram_last_error=str(e))

    def send_signal(self, signal):
        """Formats on the caller's thread (cheap), posts on a background thread
        so a slow Telegram (10s timeout) can't eat into the 25s signal-age gate
        that decides whether the trade opens."""
        try:
            text = self._format_signal(signal)
        except Exception as e:
            print(f"[Telegram] Format error: {e}")
            status.update(telegram_last_ok=False, telegram_last_error=f"format: {e}")
            return
        threading.Thread(
            target=self._post_signal,
            args=(text, signal.symbol, signal.action, signal.entry_price),
            daemon=True,
        ).start()

    def send_document(self, path, caption=""):
        """Upload one file to the configured Telegram chat (used by the
        Settings 'Backup to Telegram' button). Returns (ok, message). Never
        raises and never touches the signal-status fields."""
        token, chat = self._creds()
        if not token or not chat:
            return False, "Telegram Bot Token / Chat ID Settings me set nahi hai"
        try:
            with open(path, "rb") as f:
                resp = requests.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": chat, "caption": caption[:900]},
                    files={"document": (os.path.basename(path), f)},
                    timeout=60,
                )
            if resp.status_code == 200:
                return True, "sent"
            return False, f"Telegram HTTP {resp.status_code}: {resp.text[:120]}"
        except Exception as e:
            return False, f"Telegram error: {e}"

    def send_text(self, text):
        """Plain-text send for diagnostics/alerts that aren't a full trade
        signal card (see app.py's [SIGNAL CHECK] diagnostic). Best-effort -
        never raises, never touches the telegram_last_ok/_error status
        fields (send_signal already owns those for the Dashboard's
        TELEGRAM card; this is a secondary, lower-priority channel)."""
        token, chat = self._creds()
        if not token or not chat:
            return
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, data={"chat_id": chat, "text": text}, timeout=10)
        except Exception as e:
            print(f"[Telegram] send_text error: {e}")
