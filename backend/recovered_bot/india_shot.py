"""india_shot.py - ONE chart photo for each India Telegram signal (notification layer only).

* Called by india_telegram.py AFTER the normal signal card was sent. It never touches entry, SL, TP,
  execution or the Telegram token handling: the token and chat id are passed in, never stored or logged.
* Exactly one photo per signal: the signal id (same "coin|tf|candle|action" id the card uses) is saved
  to state["shots"] on disk BEFORE anything is drawn or sent. A repeat of the same id never sends again.
* The photo is drawn and sent in its own daemon thread, with NO retry. If drawing or sending fails the
  card has already gone out and nothing else is affected (a failed photo is simply missed, never doubled).
* Chart = the existing ai_vision.render_chart() (Pillow only): EMA30/50, SD bands, TSI, Z-score, ENTRY, STOP
  and TARGET (= TP4). Candles = the same 300 the strategy read for this signal.
"""
import io
import logging
import threading

import requests

log = logging.getLogger("india_shot")

KEEP = 200            # how many shot ids are kept on disk (same size as the card list)
SEND_TIMEOUT = 20


def claim(state, lock, save, dedupe):
    """True only the first time this signal id is seen. The id is written to disk before any send."""
    with lock:
        shots = state.setdefault("shots", [])
        if dedupe in shots:
            return False
        shots.append(dedupe)
        del shots[:-KEEP]
        save()
    return True


def make_png(underlying, tf, cs, sig, opened):
    """PNG bytes of the signal chart. cs = provider candles (dicts t,o,h,l,c,v), opened = signal candle open time."""
    from . import ai_vision
    try:
        from .india_bridge import to_strategy_candles
    except ImportError:  # flat-import fallback (tests / scripts)
        from india_bridge import to_strategy_candles
    marks = {"entry": float(sig.entry_price), "sl": float(sig.stop_loss), "target": float(sig.tp4),
             "bar_ts": int(opened.timestamp() * 1000)}
    side = "BUY" if str(sig.action).upper() == "BUY" else "SELL"
    return ai_vision.render_chart(underlying, to_strategy_candles(cs), f"{int(tf)}m", side=side, marks=marks,
                                  title_extra="TP4 = target line")


def post_photo(png, caption, token, chat):
    """-> True/False. One try, no retry, never raises, never logs the token."""
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                          data={"chat_id": chat, "caption": caption[:200]},
                          files={"photo": ("signal.png", io.BytesIO(png), "image/png")}, timeout=SEND_TIMEOUT)
        return r.status_code == 200
    except Exception as e:
        log.warning("india shot send failed: %s", str(e).replace(token or "-", "***")[:120])
        return False


def _work(underlying, tf, cs, sig, opened, token, chat):
    try:
        png = make_png(underlying, tf, cs, sig, opened)
        cap = f"{underlying} {int(tf)}m {str(sig.action).upper()} - signal chart"
        post_photo(png, cap, token, chat)
    except Exception as e:
        log.warning("india shot skipped: %s", str(e).replace(token or "-", "***")[:120])


def send_async(state, lock, save, dedupe, underlying, tf, cs, sig, opened, token, chat):
    """Start the one-photo job in a background thread. Returns True if a job was started."""
    if not token or not chat or not claim(state, lock, save, dedupe):
        return False
    threading.Thread(target=_work, args=(underlying, tf, list(cs), sig, opened, token, chat),
                     daemon=True, name="india_shot").start()
    return True
