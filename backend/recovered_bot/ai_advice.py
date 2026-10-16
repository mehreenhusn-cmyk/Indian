"""
ai_advice.py - PHASE 4: sirf SALAH badge ("AI: skip - TSI aur Z alag, sideways").

For every open position, find the Shadow Lab row of the same coin / side / timeframe whose signal candle
is closest to the time the trade opened, and describe what the indicators said at that moment.
No candle fetching (no extra load). It is ONLY a label for the screen: the bot never blocks or closes
anything because of it. Never raises.
"""
import time

from . import ai_exit_study as X
from . import ai_recipe as R
from . import ai_shadow_lab as L
from . import ai_wait_study as W

MAX_GAP_MS = 2 * 3_600_000


def _tf_of(pos):
    tf = str(pos.get("timeframe") or "")
    return tf if tf in L.SIGNAL_TFS else str(X._cfg("timeframe", "3m"))


def _side(pos):
    s = str(pos.get("action") or pos.get("side") or pos.get("direction") or "").upper()
    if s in ("BUY", "LONG", "L"):
        return "BUY"
    if s in ("SELL", "SHORT", "S"):
        return "SELL"
    return ""


def _badge(lab):
    """(level, text, reasons) from the facts only."""
    why = []
    if str(lab.get("move", "")).startswith(W.SIDE):
        why.append("sideways")
    zt = lab.get("z_tsi", "")
    if zt in ("Z WITH but TSI AGAINST", "Z AGAINST but TSI WITH"):
        why.append("TSI aur Z alag")
    elif zt == "Z and TSI both AGAINST trade":
        why.append("Z aur TSI dono ulta")
    if lab.get("z_div") == "Z divergence AGAINST trade":
        why.append("Z divergence ulta")
    if lab.get("zma_vs_trade") == "Z avg-line AGAINST trade":
        why.append("Z avg-line ulta")
    confirmed = (not why) and zt == W.BOTH
    if confirmed:
        return "ok", "AI: dono confirm", ["Z aur TSI dono trade ke saath"]
    if not why:
        return "info", "AI: mixed", []
    lvl = "skip" if len(why) >= 2 else "warn"
    return lvl, ("AI: skip - " if lvl == "skip" else "AI: dhyan - ") + ", ".join(why), why


def for_positions(positions):
    """{position id: {'level','text','reasons','at'}} - only positions with a matching lab row."""
    out = {}
    try:
        lev = float(X._cfg("leverage", 1) or 1)
        fee = max(0.0, float(X._cfg("fee_roi_pct", 1.0) or 0.0))
        cache = {}
        for p in positions or []:
            try:
                pid, sym, side, tf = p.get("id"), p.get("symbol"), _side(p), _tf_of(p)
                opened = float(p.get("opened_at_ts") or 0) * 1000.0
                if pid is None or not sym or not side or not opened:
                    continue
                rows = cache.get(tf)
                if rows is None:
                    rows = cache[tf] = X.lab_rows(tf, lev, fee)
                best, gap = None, MAX_GAP_MS
                for r in rows:
                    if r["sym"] == sym and r["a"] == side:
                        g = abs(r["t"] - opened)
                        if g <= gap:
                            best, gap = r, g
                if best is None:
                    continue
                lvl, text, why = _badge(best["lab"])
                m = R.match_for(tf, best["lab"])      # True / False / None (no usable recipe yet)
                if m is True:
                    text += " | Recipe: match"
                elif m is False:
                    text += " | Recipe: match nahi"
                out[str(pid)] = {"level": lvl, "text": text, "reasons": why, "recipe": m}
            except Exception:
                continue
    except Exception:
        pass
    return out


def current():
    """Badges for what is open right now (reads the bot status; read-only)."""
    try:
        from . import status
        return {"ts": time.time(), "badges": for_positions((status.get() or {}).get("open_positions") or [])}
    except Exception as e:
        return {"ts": time.time(), "badges": {}, "error": f"{type(e).__name__}: {e}"}
