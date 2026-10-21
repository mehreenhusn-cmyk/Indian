"""
ai_vision_exits.py - peak/drawdown + zone exit stats for Vision paper trades.

Read-only toward the bot. Own file ai/vision_exits.json.
"""
import os
import threading
import time

KEEP = 400
_lock = threading.RLock()
_state = {"rows": [], "stats": {}}
_file = None
_loaded = False


def init(path):
    global _file
    try:
        os.makedirs(path, exist_ok=True)
        _file = os.path.join(path, "vision_exits.json")
    except Exception as e:
        print(f"[VisionExits] init: {e}")


def _load():
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            if _file:
                from . import safe_io
                d, _ = safe_io.read_json_safe(_file, "vision_exits")
                if isinstance(d, dict):
                    if isinstance(d.get("rows"), list):
                        _state["rows"] = d["rows"]
                    if isinstance(d.get("stats"), dict):
                        _state["stats"] = d["stats"]
        except Exception as e:
            print(f"[VisionExits] load: {e}")


def _save():
    with _lock:
        if not _file:
            return
        try:
            from . import safe_io
            _state["rows"] = _state["rows"][-KEEP:]
            safe_io.write_json_atomic(_file, {"rows": _state["rows"], "stats": _state["stats"]})
        except Exception as e:
            print(f"[VisionExits] save: {e}")


def record_closed(tr):
    """Call when a Vision trade closes. Stores peak ROI, zone at peak, gave-back flag."""
    _load()
    try:
        peak = float(tr.get("peak_roi") or 0)
        final = float(tr.get("roi") or 0)
        side = str(tr.get("side") or "").upper()
        src = tr.get("source") or "bot"
        gave_back = peak >= 1.0 and final <= 0
        target_hit = bool(tr.get("tgt_bar"))
        row = {
            "id": tr.get("id"), "symbol": tr.get("symbol"), "side": side, "source": src,
            "peak_roi": round(peak, 2), "final_roi": round(final, 2),
            "pnl": round(float(tr.get("pnl") or 0), 2),
            "gave_back": gave_back, "target_hit": target_hit,
            "exit_reason": str(tr.get("exit_reason") or "")[:80],
            "sd_zone_peak": tr.get("sd_zone_peak"),
            "t": time.time(),
        }
        with _lock:
            _state["rows"].append(row)
        _rebuild()
        _save()
    except Exception as e:
        print(f"[VisionExits] record: {e}")


def _rebuild():
    with _lock:
        rows = list(_state["rows"])
    stats = {}
    for src in ("bot", "own"):
        for side in ("BUY", "SELL"):
            sub = [r for r in rows if (r.get("source") or "bot") == src and r.get("side") == side]
            n = len(sub)
            if n == 0:
                continue
            reached = sum(1 for r in sub if (r.get("peak_roi") or 0) >= 1.0)
            gave = sum(1 for r in sub if r.get("gave_back"))
            tgt = sum(1 for r in sub if r.get("target_hit"))
            key = f"{src}:{side}"
            stats[key] = {
                "n": n, "reached_1pct": reached,
                "reached_pct": round(100.0 * reached / n) if n else 0,
                "gave_back": gave,
                "gave_back_pct": round(100.0 * gave / n) if n else 0,
                "target_hit": tgt,
                "small_sample": n < 20,
            }
    with _lock:
        _state["stats"] = stats


def prompt_block():
    _load()
    with _lock:
        stats = dict(_state.get("stats") or {})
        n = len(_state.get("rows") or [])
    if n < 3:
        return ""
    lines = []
    for k, d in list(stats.items())[:6]:
        nn = d.get("n") or 0
        small = " SMALL SAMPLE" if d.get("small_sample") else ""
        lines.append(
            f"{k}: n={nn}, reached +1% ROI in {d.get('reached_pct')}%, "
            f"gave back to stop/flat {d.get('gave_back_pct')}%, target-touched {d.get('target_hit')}.{small}"
        )
    return "\n\nEXIT MEMORY (measured on closed Vision trades):\n" + "\n".join(f"- {x}" for x in lines)


def snapshot():
    _load()
    with _lock:
        rows = list(_state["rows"][-40:])[::-1]
        stats = dict(_state.get("stats") or {})
    plain = []
    for k, d in stats.items():
        n = d.get("n") or 0
        if n < 1:
            continue
        s = (f"{k}: reached +1% in {d.get('reached_pct')}% of trades; "
             f"of all, {d.get('gave_back_pct')}% gave back and finished flat/red (n={n}).")
        if n < 20:
            s += " SMALL SAMPLE - do not trust yet."
        plain.append(s)
    return {"rows": rows, "stats": stats, "plain": plain, "total": len(_state.get("rows") or [])}


def apply_partial(tr, price, frac):
    """Close frac (0.25-0.75) of the trade once. Returns pnl for the leg or None if invalid."""
    try:
        frac = float(frac)
        if tr.get("partial_done"):
            return None
        if frac < 0.25 or frac > 0.75:
            return None
        from recovered_bot import ai_vision as V
        gross = V._roi(tr["side"], tr["entry"], price, tr["lev"])
        fee = float(tr.get("fee_roi") or 1.0) * frac
        net = gross * frac - fee
        pnl = float(tr.get("invest") or 10) * net / 100.0
        tr["partial_done"] = True
        tr["partial_frac"] = frac
        tr["partial_pnl"] = round(pnl, 4)
        tr["invest"] = float(tr.get("invest") or 10) * (1.0 - frac)
        return pnl
    except Exception:
        return None


def tighten_stop_only(tr, new_stop):
    """Move stop only in the profit direction. Returns True if applied."""
    try:
        new_stop = float(new_stop)
        side = str(tr.get("side") or "").upper()
        cur = float(tr.get("sl") or 0)
        if side == "BUY":
            if new_stop <= cur:
                return False
            tr["sl"] = new_stop
            return True
        else:
            if new_stop >= cur and cur > 0:
                return False
            tr["sl"] = new_stop
            return True
    except Exception:
        return False
