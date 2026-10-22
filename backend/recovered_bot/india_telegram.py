"""india_telegram.py - Telegram signals for the India mode (separate from the crypto Telegram).

* Only India signals go here, never crypto. The crypto Telegram (telegram.py) is not touched.
* A small WATCHER thread runs the SAME strategy (ABCDStrategy EMA50 + SD) on the closed candles of
  the chosen timeframe (5m or 15m) from the SAME live broker feed the bot uses (Fyers). It is
  independent of the trading loop: it never opens/closes a trade and a slow Telegram can never delay one.
* Nothing is sent in demo mode (synthetic candles) - only when a real broker feed is connected.
* The Bot Token and Chat ID are saved on the server only (file mode 600, same store as the broker keys).
  They are never written in the code, never returned in full by the API (masked), never logged.
* The card shows the candle close time AND the send time, so you can see how fresh a signal is.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta

import requests

try:
    from .strategy import ABCDStrategy
    from .india_bridge import to_strategy_candles
    from .india_data import IST
    from . import india_options as opt
    from . import india_broker
except ImportError:  # flat-import fallback (tests / scripts)
    from strategy import ABCDStrategy
    from india_bridge import to_strategy_candles
    from india_data import IST
    import india_options as opt
    import india_broker

log = logging.getLogger("india_telegram")

CRED_NAME = "india_telegram"        # key inside india_broker.json (file mode 600)
TG_TFS = (5, 15)
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
FEED_WAIT_SEC = 120                 # how long we keep asking for a candle the feed has not delivered yet
HISTORY = 300                       # same as the bot's runner, so the candle cache is shared when tf matches
BOT_NAME = "Faisal sir"


def _clean(text, token):
    """Never let the token appear in an error text (requests puts the URL, with the token, in errors)."""
    t = str(text)
    if token:
        t = t.replace(token, "***")
    return t[:200]


def _hhmm(dt):
    return dt.astimezone(IST).strftime("%H:%M")


def format_card(sig, underlying, tf, number, candle_open, sent_at, itm_depth=1, data_label="Fyers", bot_name=BOT_NAME, demo=False):
    """Plain-text signal card, same layout as the crypto card. `sig` = strategy.Signal."""
    is_long = str(sig.action).upper() == "BUY"
    entry = float(sig.entry_price)
    sl = float(sig.stop_loss)

    def pct(tp):
        tp = float(tp)
        return ((tp - entry) if is_long else (entry - tp)) / entry * 100 if entry else 0.0

    sl_pct = ((entry - sl) if is_long else (sl - entry)) / entry * 100 if entry else 0.0
    candle_close = candle_open + timedelta(minutes=tf)
    delay = max(0, int((sent_at - candle_close).total_seconds()))
    lines = [
        "🟢 LONG SIGNAL" if is_long else "🔴 SHORT SIGNAL",
        "--------------------------",
        f"Signal #   : {number}",
        f"Date       : {candle_close.astimezone(IST).strftime('%Y-%m-%d')}",
        f"Symbol     : {underlying}",
        f"Direction  : {'BUY (Call)' if is_long else 'SELL (Put)'}",
        f"Timeframe  : {tf}m",
        "--------------------------",
        f"Entry      : {entry:.2f}",
        f"Stop Loss  : {sl:.2f} ({sl_pct:.2f}%)",
        f"TP1        : {float(sig.tp1):.2f} ({pct(sig.tp1):.2f}%)",
        f"TP2        : {float(sig.tp2):.2f} ({pct(sig.tp2):.2f}%)",
        f"TP3        : {float(sig.tp3):.2f} ({pct(sig.tp3):.2f}%)",
        f"TP4        : {float(sig.tp4):.2f} ({pct(sig.tp4):.2f}%)",
        "--------------------------",
        f"Candle     : {_hhmm(candle_open)} - {_hhmm(candle_close)} IST (closed {_hhmm(candle_close)})",
        f"Sent       : {sent_at.astimezone(IST).strftime('%H:%M:%S')} IST" + ("" if demo else f" ({delay}s after close)"),
        f"Data       : {data_label}",
        f"Bot        : {bot_name}",
    ]
    return "\n".join(lines)


def boundary(now, tf):
    """Close time of the latest candle that must already be finished at `now` (candles start on tf boundaries from midnight IST,
    which lines up with 09:15 for 5m and 15m)."""
    now = now.astimezone(IST)
    mins = now.hour * 60 + now.minute
    m = (mins // tf) * tf
    return now.replace(hour=m // 60, minute=m % 60, second=0, microsecond=0)


def in_session(close_dt, tf):
    """True when a candle that CLOSES at close_dt belongs to the 09:15-15:30 session."""
    mins = close_dt.hour * 60 + close_dt.minute
    return MARKET_OPEN[0] * 60 + MARKET_OPEN[1] + tf <= mins <= MARKET_CLOSE[0] * 60 + MARKET_CLOSE[1]


class IndiaTelegram:
    def __init__(self, rt, data_dir):
        self.rt = rt
        self.dir = data_dir
        self.creds = india_broker.CredStore(data_dir)
        self._state_path = os.path.join(data_dir, "india_telegram_state.json")
        self._lock = threading.Lock()
        self.strategy = ABCDStrategy(lookback_len=200, ema_length=50)   # own instance, never shared with the bot
        self._checked = {}            # (underlying, tf) -> close time (iso) already evaluated
        self._try_at = {}             # (underlying, tf) -> next time we may ask the feed again
        self.last = {"ok": None, "error": "", "at": None, "kind": "", "signal_at": None}
        self.token_check = {"ok": None, "text": ""}    # result of the last Telegram getMe check
        self.note = ""
        self._wake = threading.Event()
        self.state = {"count": 0, "sent": []}
        try:
            with open(self._state_path) as f:
                self.state.update(json.load(f))
        except Exception:
            pass
        self.thread = threading.Thread(target=self._loop, daemon=True, name="india_telegram")
        self.thread.start()

    # ------------------------------------------------------------ settings ---
    @property
    def enabled(self):
        return bool(self.rt.settings.get("tg_enabled"))

    @property
    def tf(self):
        v = self.rt.settings.get("tg_tf", 15)
        return v if v in TG_TFS else 15

    def _creds(self):
        c = self.creds.get(CRED_NAME)
        return str(c.get("bot_token", "")).strip(), str(c.get("chat_id", "")).strip()

    def save_creds(self, bot_token=None, chat_id=None):
        old = self.creds.get(CRED_NAME)
        new = dict(old)
        if bot_token is not None and str(bot_token).strip():
            new["bot_token"] = str(bot_token).strip()
        if chat_id is not None and str(chat_id).strip():
            new["chat_id"] = str(chat_id).strip()
        if new != old:
            self.creds.save(CRED_NAME, new)
            self._wake.set()
        if bot_token is not None and str(bot_token).strip():
            self.check_token()                # tells at once if the token is wrong (no more plain "404")

    def forget(self):
        self.creds.clear(CRED_NAME)
        self.token_check = {"ok": None, "text": ""}

    def check_token(self):
        """Asks Telegram getMe. -> (ok, text). Never raises, never shows the token."""
        token, _ = self._creds()
        if not token:
            self.token_check = {"ok": False, "text": "Bot Token not set"}
            return False, self.token_check["text"]
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
            if r.status_code == 200 and r.json().get("ok"):
                name = r.json().get("result", {}).get("username", "")
                self.token_check = {"ok": True, "text": f"Token OK: @{name}"}
            elif r.status_code in (401, 404):
                self.token_check = {"ok": False, "text": "Token is wrong or revoked. Copy it again from BotFather (only the token line)"}
            else:
                self.token_check = {"ok": False, "text": f"Telegram answered {r.status_code}. Try again"}
        except Exception as e:
            self.token_check = {"ok": False, "text": _clean(f"Could not reach Telegram: {type(e).__name__}", token)}
        return self.token_check["ok"], self.token_check["text"]

    def info(self):
        token, chat = self._creds()
        live = self.rt.live
        return {"enabled": self.enabled, "tf": self.tf, "tf_choices": list(TG_TFS),
                "token_saved": bool(token), "token_masked": india_broker.mask(token),
                "chat_id": chat, "data_live": live is not None,
                "data_label": getattr(live, "name", None) or "Fyers",
                "sent_count": int(self.state.get("count", 0)),
                "token_check": dict(self.token_check),
                "last": dict(self.last), "note": self.note}

    # --------------------------------------------------------------- send ---
    def _post(self, text, token, chat, kind):
        """-> (ok, message). Never raises, never logs the token."""
        if not token or not chat:
            msg = "Bot Token / Chat ID not set"
            self.last = {"ok": False, "error": msg, "at": datetime.now(IST).isoformat(), "kind": kind, "signal_at": self.last.get("signal_at")}
            return False, msg
        err = ""
        for attempt in range(2):           # one quick retry
            try:
                r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                  data={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=10)
                if r.status_code == 200:
                    now = datetime.now(IST).isoformat()
                    self.last = {"ok": True, "error": "", "at": now, "kind": kind,
                                 "signal_at": now if kind == "signal" else self.last.get("signal_at")}
                    return True, "sent"
                err = f"Telegram HTTP {r.status_code}: {_clean(r.text, token)[:120]}"
                if r.status_code in (400, 401, 403, 404):
                    break                   # wrong token / chat: a retry cannot help
            except Exception as e:
                err = _clean(f"{type(e).__name__}: {e}", token)
            time.sleep(1.0)
        self.last = {"ok": False, "error": err, "at": datetime.now(IST).isoformat(), "kind": kind, "signal_at": self.last.get("signal_at")}
        return False, err

    def send_test(self):
        token, chat = self._creds()
        now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        return self._post(f"✅ Owl Terminal - India Telegram test\nTime : {now} IST\n"
                          f"Timeframe : {self.tf}m\nIf you see this, India signals will come here.", token, chat, "test")

    def send_demo_signal(self):
        """Sends a card that looks exactly like a real signal, with SAMPLE numbers (marked DEMO). -> (ok, message)."""
        token, chat = self._creds()
        now = datetime.now(IST)
        tf = self.tf
        opened = boundary(now, tf) - timedelta(minutes=tf)

        class _S:                                    # sample numbers only
            action, entry_price, stop_loss = "BUY", 24500.0, 24420.0
            tp1, tp2, tp3, tp4 = 24560.0, 24620.0, 24680.0, 24760.0

        und = (self.rt.settings.get("underlyings") or ["NIFTY"])[0]
        card = format_card(_S, und, tf, 0, opened, now, itm_depth=self.rt.settings.get("itm_depth", 1),
                           data_label="DEMO (sample numbers)", bot_name=BOT_NAME, demo=True)
        return self._post("🧪 DEMO - not a real signal\n" + card, token, chat, "test")

    def find_chat(self):
        """Reads the newest chat that messaged the bot (send /start to the bot first). -> (ok, message)."""
        token, _ = self._creds()
        if not token:
            return False, "Save the Bot Token first"
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
            if r.status_code != 200:
                return False, f"Telegram HTTP {r.status_code}: {_clean(r.text, token)[:120]}"
            best = None
            for u in r.json().get("result", []):
                m = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
                ch = m.get("chat") or {}
                if ch.get("id") is not None:
                    best = ch
            if not best:
                return False, "No chat found - open your bot in Telegram, send /start, then tap this again"
            self.save_creds(chat_id=str(best["id"]))
            return True, f"Chat ID saved: {best['id']}"
        except Exception as e:
            return False, _clean(f"{type(e).__name__}: {e}", token)

    # ------------------------------------------------------------ watcher ---
    def _save_state(self):
        try:
            tmp = self._state_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"count": self.state["count"], "sent": self.state["sent"][-200:], "login_remind_day": self.state.get("login_remind_day", "")}, f)
            os.replace(tmp, self._state_path)
        except Exception:
            log.exception("save india telegram state")

    def _loop(self):
        while True:
            self._wake.wait(3.0)
            self._wake.clear()
            try:
                self.tick()
            except Exception:
                log.exception("india telegram watcher")
                time.sleep(2.0)

    def remind_login(self, now=None):
        """Once a day, when the Fyers browser login is due in 2 days or less, send ONE Telegram reminder. Never raises."""
        try:
            who = self.rt.live or getattr(self.rt, "login_ok", None)
            info = who.auth_info() if who is not None and hasattr(who, "auth_info") else None
            left = (info or {}).get("refresh_days_left")
            if left is None or left > 2:
                return False
            now = (now or datetime.now(IST)).astimezone(IST)
            day = now.date().isoformat()
            if self.state.get("login_remind_day") == day or now.hour < 8:
                return False
            token, chat = self._creds()
            if not token or not chat:
                return False
            when = "today" if left <= 0 else f"in {left} day(s)"
            ok, _ = self._post(f"\u23f0 Owl Terminal - Fyers login due {when}.\nOpen the app > India > broker card > get the login link and paste a new auth code. "
                               f"Until then the daily auto-login keeps working.", token, chat, "reminder")
            if ok:
                self.state["login_remind_day"] = day
                self._save_state()
            return ok
        except Exception:
            return False

    def tick(self, now=None):
        """One watcher step (also called directly by the tests). Returns the list of cards it sent."""
        sent = []
        self.remind_login(now)
        live = self.rt.live
        if not self.enabled:
            self.note = "Off"
            return sent
        if live is None:
            self.note = "Waiting for a live broker feed (nothing is sent in demo)"
            return sent
        token, chat = self._creds()
        if not token or not chat:
            self.note = "Bot Token / Chat ID not set"
            return sent
        now = (now or datetime.now(IST)).astimezone(IST)
        tf = self.tf
        close = boundary(now, tf)
        if not in_session(close, tf) or now.weekday() >= 5:
            self.note = "Market closed - waiting for the next session"
            return sent
        try:
            from . import india_calendar as cal
        except ImportError:
            import india_calendar as cal
        if not cal.is_trading_day(now.date()):
            self.note = "Market holiday"
            return sent
        self.note = f"Watching {', '.join(self.rt.settings['underlyings'])} on {tf}m"
        if (now - close).total_seconds() < 3:       # give the feed a moment to build the candle
            return sent
        opened = close - timedelta(minutes=tf)
        for u in list(self.rt.settings["underlyings"]):
            key = (u, tf)
            if self._checked.get(key) == close.isoformat():
                continue
            if now.timestamp() < self._try_at.get(key, 0):
                continue
            try:
                cs = live.get_candles(u, tf, HISTORY)
            except india_broker.RateLimited:
                self._try_at[key] = now.timestamp() + 8
                self.note = "Fyers limit reached - will retry"
                continue
            except Exception as e:
                self._try_at[key] = now.timestamp() + 8
                self.note = _clean(f"{u} candles: {e}", token)
                continue
            if not cs or cs[-1]["t"] < opened:
                if (now - close).total_seconds() > FEED_WAIT_SEC:
                    self._checked[key] = close.isoformat()          # feed never delivered it: do not send an old signal later
                    self.note = f"{u}: feed was late for the {_hhmm(close)} candle - skipped"
                else:
                    self._try_at[key] = now.timestamp() + 6
                continue
            self._checked[key] = close.isoformat()
            if cs[-1]["t"] != opened:
                continue                                           # unexpected candle: never signal on it
            sig = self.strategy.generate_signal(to_strategy_candles(cs), u, tf_min=tf)
            if sig is None:
                continue
            dedupe = f"{u}|{tf}|{opened.isoformat()}|{sig.action}"
            if dedupe in self.state["sent"]:
                continue
            with self._lock:
                self.state["count"] = int(self.state.get("count", 0)) + 1
                number = self.state["count"]
                self.state["sent"].append(dedupe)
                self._save_state()
            card = format_card(sig, u, tf, number, opened, datetime.now(IST),
                               itm_depth=self.rt.settings.get("itm_depth", 1),
                               data_label=(getattr(live, "name", None) or "Fyers").title(),
                               bot_name=BOT_NAME)
            self._post(card, token, chat, "signal")
            sent.append(card)
        return sent
