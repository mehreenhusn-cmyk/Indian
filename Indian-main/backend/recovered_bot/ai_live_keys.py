"""
ai_live_keys.py - STAGE 2 (file 1 of 4): the AI's OWN Binance API key, kept apart from the bot's key.

Why separate: the bot and the AI must never share one Binance account. With one account they would share margin and
could open the same coin against each other. The AI gets its own (sub-)account and its own key.

Rules this file enforces:
  - the key is stored OUTSIDE the ai/ data folder (in ai_secrets/ next to it), so the daily AI backup zip, which zips
    the whole ai/ folder, can never contain the secret;
  - the file is written with mode 0600 (owner only), through a temp file, so a half-written key is never left behind;
  - a key equal to the bot's own key (settings_store binance_api_key) is refused;
  - the secret is never returned by any function here. status() shows only the last 4 characters of the key.
Recommended Binance key permissions: Futures trading ON, Withdrawals OFF, and restrict to this phone's IP if possible.
"""
import json
import os
import threading
import time

_lock = threading.Lock()
_dir = None
_NAME = "ai_live_keys.json"


def init(ai_dir):
    """ai_dir = DATA_DIR/ai. The secret folder is its sibling, DATA_DIR/ai_secrets."""
    global _dir
    try:
        _dir = os.path.join(os.path.dirname(os.path.abspath(ai_dir)), "ai_secrets")
        os.makedirs(_dir, exist_ok=True)
        try:
            os.chmod(_dir, 0o700)
        except Exception:
            pass
    except Exception as e:
        _dir = None
        print(f"[AILiveKeys] init: {e}")


def _path():
    return os.path.join(_dir, _NAME) if _dir else None


def get():
    """(key, secret) for the signing client only. ("", "") when nothing is stored."""
    p = _path()
    if not p or not os.path.isfile(p):
        return "", ""
    try:
        with _lock, open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return str(d.get("key") or "").strip(), str(d.get("secret") or "").strip()
    except Exception:
        return "", ""


def has_keys():
    k, s = get()
    return bool(k and s)


def mask():
    k, _ = get()
    return ("..." + k[-4:]) if len(k) >= 8 else ""


def _bot_key():
    try:
        from . import settings_store
        return str(settings_store.get("binance_api_key", "") or "").strip()
    except Exception:
        return ""


def set_keys(key, secret):
    """Store the AI key. Returns {"ok": bool, "error": str}. Never echoes the secret."""
    key, secret = str(key or "").strip(), str(secret or "").strip()
    if len(key) < 32 or len(secret) < 32 or any(c.isspace() for c in key + secret):
        return {"ok": False, "error": "That does not look like a Binance API key and secret (both are long, with no spaces)."}
    bk = _bot_key()
    if bk and key == bk:
        return {"ok": False, "error": "This is the BOT's key. The AI needs its own key from its own (sub-)account."}
    p = _path()
    if not p:
        return {"ok": False, "error": "Key storage is not ready (start-up has not run)."}
    tmp = p + ".tmp"
    try:
        with _lock:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"key": key, "secret": secret, "saved": int(time.time())}, f)
            try:
                os.chmod(tmp, 0o600)
            except Exception:
                pass
            os.replace(tmp, p)
        return {"ok": True, "error": ""}
    except Exception as e:
        try:
            os.remove(tmp)
        except Exception:
            pass
        return {"ok": False, "error": "Could not save the key: %s" % type(e).__name__}


def clear():
    p = _path()
    try:
        with _lock:
            if p and os.path.isfile(p):
                os.remove(p)
        return True
    except Exception:
        return False
