"""
ai_digest.py - one short Telegram summary every night (IST): today's net P&L, best and worst entry hour, and the coin that cost the most.

Plain counting on today's CLOSED trades from trade_store. It reads no score and no ML number
(ai_guard.py scans this file too), changes no trade, and any error just skips that night.
Settings (optional): ai_digest_hour = IST hour to send (default 23), ai_digest_on = false to stop.
"""
import threading
import time
from datetime import datetime, timedelta, timezone

from . import trade_store

IST = timedelta(hours=5, minutes=30)
DEFAULT_HOUR = 23
_started = False


def _f(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def _ist(ts):
    return datetime.fromtimestamp(ts, timezone.utc) + IST


def build_digest(day=None):
    """Text for the IST day `day` (a date; default today), or "" if no trade closed that day."""
    day = day or datetime.now(timezone.utc).date()      # trading day = 5:30 AM IST = 00:00 UTC
    rows = [t for t in trade_store.get_all_closed(800)
            if t.get("closed_at_ts") and datetime.fromtimestamp(_f(t["closed_at_ts"]), timezone.utc).date() == day]
    if not rows:
        return ""
    net = sum(_f(t.get("pnl_usdt")) for t in rows)
    wins = sum(1 for t in rows if _f(t.get("pnl_usdt")) > 0)
    hours, coins = {}, {}
    for t in rows:
        ts = _f(t.get("opened_at_ts")) or _f(t.get("closed_at_ts"))
        h = _ist(ts).hour
        hours[h] = hours.get(h, 0.0) + _f(t.get("pnl_usdt"))
        s = t.get("symbol")
        if s:
            coins[s] = coins.get(s, 0.0) + _f(t.get("pnl_usdt"))
    L = [f"AI digest {day.strftime('%d %b')} (IST)",
         f"{len(rows)} trades, {wins} jeete ({wins / len(rows) * 100:.0f}%)",
         f"Net P&L: {net:+.2f} USDT"]
    if len(hours) >= 2:
        bh = max(hours, key=hours.get)
        wh = min(hours, key=hours.get)
        L.append(f"Best hour: {bh:02d}:00-{bh:02d}:59 ({hours[bh]:+.2f})")
        if hours[wh] < 0:
            L.append(f"Worst hour: {wh:02d}:00-{wh:02d}:59 ({hours[wh]:+.2f})")
    if coins:
        wc = min(coins, key=coins.get)
        if coins[wc] < 0:
            L.append(f"Sabse zyada loss: {wc} ({coins[wc]:+.2f})")
    L.append("Sirf gintee hai, salah nahi. Bot ne kuch skip nahi kiya.")
    return "\n".join(L)


def send_now():
    """Build today's digest and send it. -> {"ok": bool, "sent": bool, "text": str}"""
    try:
        text = build_digest()
        if not text:
            return {"ok": True, "sent": False, "text": "", "why": "aaj koi trade band nahi hua"}
        from . import app as _app           # the Telegram notifier lives there
        _app.bot.send_text(text)
        return {"ok": True, "sent": True, "text": text}
    except Exception as e:
        return {"ok": False, "sent": False, "text": "", "why": str(e)}


def _hour():
    try:
        from . import settings_store
        return int(settings_store.get("ai_digest_hour", DEFAULT_HOUR))
    except Exception:
        return DEFAULT_HOUR


def _on():
    try:
        from . import settings_store
        return str(settings_store.get("ai_digest_on", True)).lower() not in ("false", "0", "no")
    except Exception:
        return True


def _loop():
    sent_day = None
    time.sleep(60)
    while True:
        try:
            now = datetime.now(timezone.utc) + IST
            if _on() and now.hour == _hour() and sent_day != now.date():
                sent_day = now.date()           # at most once a day, even if sending fails
                send_now()
        except Exception as e:
            print(f"[AiDigest] error (ignored): {e}")
        time.sleep(60)


def start():
    """Start the background thread once. Safe to call repeatedly."""
    global _started
    if _started:
        return
    _started = True
    try:
        threading.Thread(target=_loop, name="ai-digest", daemon=True).start()
    except Exception as e:
        print(f"[AiDigest] could not start: {e}")
