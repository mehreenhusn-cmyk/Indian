"""
ai_capital.py - paper capital manager for the AI Own account. PAPER ONLY: it never touches a real order.

  Start balance  vision_cap_start  (default 100 USDT), plus all earlier AI Own results.
  Target lock    vision_cap_target (default +30 USDT in a trading day) = stop opening trades. NOT a goal to force.
  Loss lock      vision_cap_loss   (default 10 USDT) = stop opening trades.
  Risk / trade   vision_cap_risk   (default 2 USDT lost if the stop hits) - leverage only changes the margin, never the risk.
  Max open       vision_cap_max_open (default 2).
The day is the 5:30 AM IST trading day. A lock holds until the next day starts; learned data is never reset.
Only AI Own trades are governed (source "own"); AI trades on bot signals are left exactly as they are.
"""
import threading
import time

_lock = threading.Lock()
_file = None
_st = {"day0": 0.0, "lock": ""}
_loaded = False


def init(path):
    global _file
    import os
    try:
        os.makedirs(path, exist_ok=True)
        _file = os.path.join(path, "vision_capital.json")
    except Exception as e:
        print(f"[Capital] init: {e}")


def _f(v, d=0.0):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


def _load():
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        if _file:
            from . import safe_io
            d, _s = safe_io.read_json_safe(_file, "vision_capital")
            if isinstance(d, dict):
                _st["day0"], _st["lock"] = _f(d.get("day0")), str(d.get("lock") or "")
    except Exception as e:
        print(f"[Capital] load: {e}")


def _save():
    try:
        if _file:
            from . import safe_io
            safe_io.write_json_atomic(_file, dict(_st))
    except Exception:
        pass


def free_mode(V):
    """AI Own FREE MONEY mode (paper): no locks, no max open, no grade gate. Own margin x own leverage."""
    return bool(V._cfg("vision_own_free_money", True))


def enabled(V):
    if free_mode(V):
        return False                                         # every lock / gate below is skipped
    return bool(V._cfg("vision_cap_enabled", True))


def status(V):
    _load()
    day0 = V._day0_ts()
    with V._lock:
        trades = [dict(t) for t in V._state.get("trades", []) if (t.get("source") or "bot") == "own"]
    realized_before = sum(_f(t.get("pnl")) for t in trades if t.get("status") == "closed" and _f(t.get("closed_at")) < day0)
    realized_today = sum(_f(t.get("pnl")) for t in trades if t.get("status") == "closed" and _f(t.get("closed_at")) >= day0)
    opens = [t for t in trades if t.get("status") == "open"]
    unreal = 0.0
    for t in opens:
        try:
            unreal += _f(V._trade_view(t).get("pnl"))
        except Exception:
            pass
    start = _f(V._cfg("vision_cap_start", 100.0), 100.0)
    target = _f(V._cfg("vision_cap_target", 30.0), 30.0)
    loss = abs(_f(V._cfg("vision_cap_loss", 10.0), 10.0))
    net = realized_today + unreal
    with _lock:
        if _st["day0"] != day0:                              # new trading day: the lock resets, nothing learned is touched
            _st["day0"], _st["lock"] = day0, ""
            _save()
        if not _st["lock"]:
            if target > 0 and net >= target:
                _st["lock"] = "target"
                _save()
            elif loss > 0 and net <= -loss:
                _st["lock"] = "loss"
                _save()
        lock = _st["lock"]
    return {"enabled": enabled(V), "day0": day0, "balance": round(start + realized_before + realized_today, 2),
            "day_start_balance": round(start + realized_before, 2), "realized": round(realized_today, 2), "unrealized": round(unreal, 2),
            "net": round(net, 2), "target": target, "loss_limit": loss,
            "progress_pct": round(100.0 * net / target) if target > 0 else 0,
            "state": {"target": "target_locked", "loss": "loss_locked"}.get(lock, "active"),
            "open": len(opens), "max_open": int(_f(V._cfg("vision_cap_max_open", 2), 2)),
            "risk": _f(V._cfg("vision_cap_risk", 2.0), 2.0), "trades_today": sum(1 for t in trades if _f(t.get("opened_at")) >= day0)}


def lock_reason(V):
    """Why AI Own must not open anything right now, or ''."""
    try:
        if not enabled(V):
            return ""
        s = status(V)
        if s["state"] == "target_locked":
            return f"Daily target reached (+{s['net']:.2f} USDT). Locked until 5:30 AM IST"
        if s["state"] == "loss_locked":
            return f"Daily loss limit reached ({s['net']:.2f} USDT). Locked until 5:30 AM IST"
    except Exception:
        pass
    return ""


def gate(V, rec, price, stop, grade):
    """For one AI Own TAKE. -> (ok, reason, invest, wait). wait=True means 'hold it, ask again later' (only for max open)."""
    if (rec.get("source") or "bot") != "own" or not enabled(V):
        return True, "", None, False
    s = status(V)
    if s["state"] != "active":
        return False, lock_reason(V), None, False
    if s["open"] >= s["max_open"]:
        return False, f"Max open AI Own trades reached ({s['max_open']}). Waiting for a free slot", None, True
    risk = s["risk"]
    if grade == "A":
        pass
    elif grade == "U" and bool(V._cfg("vision_cap_explore", True)):
        risk = risk / 2.0                                    # still learning: half risk
    else:
        return False, f"Grade {grade or '?'}: no proven edge for this setup, so no trade (quality over quantity)", None, False
    price, stop = _f(price), _f(stop)
    sp = abs(price - stop) / price if price else 0.0
    if sp <= 0:
        return False, "no valid stop distance", None, False
    lev = _f(rec.get("lev"), 0) or _f(V._cfg("leverage", 1), 1) or 1.0
    invest = risk / (lev * sp)                               # notional = risk / stop%, margin = notional / leverage
    invest = min(invest, s["balance"] / max(1, s["max_open"]))   # never more margin than a slot of the paper account
    return True, "", round(invest, 4), False
