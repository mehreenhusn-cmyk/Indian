"""
ai_live_guard.py - STAGE 2 (file 3 of 4): the hard limits that stand between the AI and real money.

Everything here is deliberately boring and strict:
  - OFF by default. Real orders need the master switch ON *and* not halted.
  - Turning it ON takes: an AI key stored, a connection check that passed, a margin per trade > 0, a daily loss cap > 0
    (the cap is mandatory for real money), and the exact confirm text below. One accidental tap cannot start it.
  - HALT: any doubt (hedge-mode account, an order whose result is unknown, a stop that could not be placed, a position the
    AI does not know about) stops all NEW real orders until the owner resets it. Existing positions keep being protected.
  - Hard ceilings in code (cannot be raised from the app): leverage <= HARD_MAX_LEVERAGE, open trades <= HARD_MAX_OPEN.
  - Daily loss cap counts the real closed P&L of the day plus the open P&L (day = 05:30 IST to 05:30 IST = UTC midnight).
State (limits, halt reason) is saved in ai/live_state.json, which holds NO secret. The ON switch itself is NOT restored after a
backend restart or a backup restore: the owner switches it on again (with the confirm text). Open real trades stay protected.
"""
import json
import os
import threading
import time

CONFIRM_TEXT = "ENABLE REAL TRADING"
HARD_MAX_LEVERAGE = 20
HARD_MAX_OPEN = 20
DEFAULTS = {"margin_per_trade": 0.0, "max_open": 3, "daily_loss_cap": 0.0, "max_leverage": 10}

_lock = threading.RLock()
_path = None
_st = {"enabled": False, "halted": "", "cfg": dict(DEFAULTS), "verified": 0.0, "coin_caps": {}}


def init(ai_dir):
    global _path
    _path = os.path.join(ai_dir, "live_state.json")
    try:
        os.makedirs(ai_dir, exist_ok=True)
        if os.path.isfile(_path):
            with open(_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            with _lock:
                _st["enabled"] = False         # a restart (or a restored backup) NEVER brings real trading back on by itself
                _st["halted"] = str(d.get("halted") or "")
                _st["verified"] = float(d.get("verified") or 0.0)
                _st["cfg"].update({k: d.get("cfg", {}).get(k, v) for k, v in DEFAULTS.items()})
                _st["coin_caps"] = {str(k).upper(): float(v) for k, v in (d.get("coin_caps") or {}).items() if float(v) > 0}
    except Exception as e:
        print(f"[AILiveGuard] load: {e} (starting OFF)")
        with _lock:
            _st["enabled"], _st["halted"] = False, ""


def _save():
    if not _path:
        return
    try:
        tmp = _path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_st, f)
        os.replace(tmp, _path)
    except Exception as e:
        print(f"[AILiveGuard] save: {e}")


def day_start(now=None):
    now = time.time() if now is None else now
    return now - (now % 86400)             # 00:00 UTC = 05:30 IST


def cfg():
    with _lock:
        return dict(_st["cfg"])


def set_cfg(**kw):
    """Update limits. Unknown keys are ignored; bad numbers raise ValueError. Ceilings are applied here."""
    with _lock:
        for k, v in kw.items():
            if k not in DEFAULTS or v is None:
                continue
            x = float(v)
            if x < 0:
                raise ValueError("%s cannot be negative" % k)
            if k == "max_leverage":
                x = int(min(max(1, x), HARD_MAX_LEVERAGE))
            elif k == "max_open":
                x = int(min(max(1, x), HARD_MAX_OPEN))
            _st["cfg"][k] = x
        _save()
        return dict(_st["cfg"])


def set_coin_cap(sym, margin):
    """Per-coin ceiling for the real margin of ONE trade on that coin (e.g. a thin coin gets less than the global
    margin_per_trade). margin <= 0 removes the cap. It can only lower the size, never raise it above margin_per_trade."""
    sym = str(sym or "").strip().upper()
    if not sym.endswith("USDT") or len(sym) < 6:
        raise ValueError("coin must look like BTCUSDT")
    x = float(margin)
    if x < 0:
        raise ValueError("cap cannot be negative")
    with _lock:
        if x == 0:
            _st["coin_caps"].pop(sym, None)
        else:
            _st["coin_caps"][sym] = x
        _save()
        return dict(_st["coin_caps"])


def margin_for(sym):
    """Real margin for one trade on `sym`: the global margin, lowered by the coin's own cap if it has one."""
    with _lock:
        m = float(_st["cfg"]["margin_per_trade"])
        cap = _st["coin_caps"].get(str(sym or "").upper())
        return min(m, cap) if cap else m


def note_verified(ok):
    with _lock:
        _st["verified"] = time.time() if ok else 0.0
        _save()


def enable(confirm_text, has_keys):
    """(ok, why). The only way to switch real trading on."""
    with _lock:
        c = _st["cfg"]
        if str(confirm_text or "").strip() != CONFIRM_TEXT:
            return False, 'To switch it on, type exactly: %s' % CONFIRM_TEXT
        if not has_keys:
            return False, "Save the AI's own API key first."
        if not _st["verified"] or time.time() - _st["verified"] > 600:
            return False, "Run the connection check first (it must pass within the last 10 minutes)."
        if float(c["margin_per_trade"]) <= 0:
            return False, "Set the margin per trade (USDT) first."
        if float(c["daily_loss_cap"]) <= 0:
            return False, "Set a daily loss cap (USDT) first. It is required for real money."
        _st["enabled"], _st["halted"] = True, ""
        _save()
        return True, "Real trading for the AI is ON."


def disable():
    """Stops NEW real orders. Positions already open are still protected and closed by the AI as before."""
    with _lock:
        _st["enabled"] = False
        _save()


def halt(reason):
    with _lock:
        if not _st["halted"]:
            _st["halted"] = str(reason)[:240]
            _save()


def reset_halt():
    with _lock:
        _st["halted"] = ""
        _save()


def is_on():
    with _lock:
        return bool(_st["enabled"] and not _st["halted"])


def view():
    with _lock:
        return {"enabled": bool(_st["enabled"]), "halted": _st["halted"], "cfg": dict(_st["cfg"]), "coin_caps": dict(_st["coin_caps"]),
                "verified_age_s": (round(time.time() - _st["verified"]) if _st["verified"] else None)}


def check(open_count, day_pnl, open_pnl):
    """May a NEW real trade open right now? (ok, why). day_pnl = real closed P&L today, open_pnl = unrealised now."""
    with _lock:
        c = _st["cfg"]
        if not _st["enabled"]:
            return False, "real trading is OFF"
        if _st["halted"]:
            return False, "halted: %s" % _st["halted"]
        if int(open_count) >= int(c["max_open"]):
            return False, "max real open trades (%d) reached" % int(c["max_open"])
        cap = float(c["daily_loss_cap"])
        if cap <= 0:
            return False, "no daily loss cap is set"
        if float(day_pnl) + float(open_pnl) <= -cap:
            return False, "daily loss cap (%.2f USDT) reached" % cap
        if float(c["margin_per_trade"]) <= 0:
            return False, "no margin per trade is set"
        return True, ""
