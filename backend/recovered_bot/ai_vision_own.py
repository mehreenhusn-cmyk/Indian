"""
ai_vision_own.py - Vision AI's OWN scanner (paper only).

Round-robin over the bot watchlist (top gainers+losers cache). On each newly
closed candle of the bot timeframe, a cheap measured pre-filter runs; only
candidates that pass go to the same chart + AI path as bot signals, with
source="own". Caps protect free-key quota.

Safety: paper only. Off by default (vision_own_enabled). Never touches bot
orders. Own file is not needed — decisions/trades live in ai_vision state.
"""
import threading
import time

_lock = threading.RLock()
_idx = 0
_last_bar = {}          # symbol -> bar start ts last scanned
_hour_calls = []       # timestamps of AI asks this hour
_stats = {"scanned": 0, "passed": 0, "asked": 0, "took": 0, "skipped": 0, "last_sym": None, "err": ""}
_own_seq = 0
_started = False


def _cfg(name, default):
    try:
        from . import settings_store
        v = settings_store.get(name, default)
        return default if v is None else v
    except Exception:
        return default


def _num(name, default):
    """A number setting where 0 really means 0 (the old `x or default` turned 0 back into the default)."""
    v = _cfg(name, default)
    try:
        return float(default if v is None or str(v).strip() == "" else v)
    except (TypeError, ValueError):
        return float(default)


def enabled():
    return bool(_cfg("vision_own_enabled", False))


def _hour_used():
    now = time.time()
    with _lock:
        _hour_calls[:] = [t for t in _hour_calls if now - t < 3600]
        return len(_hour_calls)


def _mark_call():
    with _lock:
        _hour_calls.append(time.time())


def _next_own_ids():
    global _own_seq
    with _lock:
        _own_seq += 1
        n = _own_seq
    return f"o{n}", f"vo{n}", 900000 + n  # signal_no high range avoids bot collision


def _watchlist():
    """The bot's watchlist (top-10 gainers + top-10 losers) from the status cache. No REST call."""
    try:
        from . import status
        wl = status.get_watchlist() or []
        syms = []
        for r in wl:
            sym = str(r.get("symbol") if isinstance(r, dict) else r or "").upper().strip()
            if sym and sym not in syms:
                syms.append(sym)
        if syms:
            return syms[:20]
    except Exception:
        pass
    return []


def _prefilter(feat, side):
    """Several measured tags must agree — protects quota."""
    try:
        from . import ai_vision_lessons as L
        tags = L.features(feat, side)
        need = ("slope_with", "tsi_agrees", "z_agrees")
        ok = sum(1 for k in need if tags.get(k) is True)
        if tags.get("stretched") is True:
            return False, tags
        return ok >= 2, tags
    except Exception:
        return False, {}


def _own_open_count(V):
    with V._lock:
        return sum(1 for t in V._state["trades"]
                   if t.get("status") == "open" and (t.get("source") or "bot") == "own")


def _own_has_symbol(V, symbol):
    with V._lock:
        return any(t.get("status") == "open" and t.get("symbol") == symbol
                   and (t.get("source") or "bot") == "own" for t in V._state["trades"])


def _own_day_net(V):
    try:
        day0 = V._day0_ts()
    except Exception:
        day0 = time.time() - 86400
    with V._lock:
        return sum(float(t.get("pnl") or 0) for t in V._state["trades"]
                   if (t.get("source") or "bot") == "own"
                   and t.get("status") == "closed"
                   and float(t.get("opened_at") or 0) >= day0)


def _bot_fired(V, symbol, bar_ts):
    with V._lock:
        for d in V._state["dec"]:
            if d.get("symbol") == symbol and d.get("bar_ts") == bar_ts and (d.get("source") or "bot") == "bot":
                return True
    return False


def tick(V):
    """One coin per call. Safe to call from the Vision loop when idle."""
    if not enabled() or not V.enabled():
        return False
    try:
        if V.quota_resume_at() > time.time():
            return False
    except Exception:
        pass
    cap_h = int(_num("vision_own_max_calls_hour", 12))        # 0 = no limit (before: 0 silently became 12)
    if cap_h > 0 and _hour_used() >= cap_h:
        return False
    day_cap = _num("vision_own_daily_loss_cap", 15.0)         # 0 = no daily loss limit (before: 0 silently became 15)
    if day_cap > 0 and _own_day_net(V) <= -abs(day_cap):
        with _lock:
            _stats["err"] = "daily own loss cap reached"
        return False
    max_open = int(float(_cfg("vision_own_max_open", 3) or 3))
    if _own_open_count(V) >= max_open:
        return False

    syms = _watchlist()
    if not syms:
        with _lock:
            _stats["err"] = "empty watchlist"
        return False

    global _idx
    with _lock:
        _idx = _idx % len(syms)
        symbol = syms[_idx]
        _idx = (_idx + 1) % len(syms)
        _stats["scanned"] += 1
        _stats["last_sym"] = symbol
        _stats["err"] = ""

    if _own_has_symbol(V, symbol):
        return False

    try:
        try:
            from . import settings_store
            tf = int(V._tf_min(settings_store.get("timeframe") or "15m"))
        except Exception:
            tf = 15
        candles = V._fetch(symbol, tf)
        if not candles or len(candles) < 260:
            return False
        bar_ts = candles[-1].get("timestamp")
        with _lock:
            if _last_bar.get(symbol) == bar_ts:
                return False
            _last_bar[symbol] = bar_ts
        if _bot_fired(V, symbol, bar_ts):
            return False

        from . import ai_ind_features as F
        feat = F.build(candles)
        # try BUY then SELL
        for side in ("BUY", "SELL"):
            ok, tags = _prefilter(feat, side)
            if not ok:
                continue
            with _lock:
                _stats["passed"] += 1
            oid, tid, sig_no = _next_own_ids()
            rec = {
                "id": oid, "signal_no": sig_no, "symbol": symbol, "side": side,
                "tf_min": tf, "status": "queued", "decision": None, "reason": "",
                "checklist": {}, "sig_time": time.time(), "sig_price": candles[-1]["close"],
                "bar_ts": bar_ts, "source": "own", "feat": tags, "waits_left": getattr(V, "WAITS", 3), "last_bar": 0,
                "checks": 0, "lev": float(_cfg("leverage", 1) or 1),
            }
            with V._lock:
                V._state["dec"].append(rec)
                V._mark()
            with _lock:
                _stats["asked"] += 1
            _mark_call()
            # run the SAME judge path as bot signals (chart, AI, validation, open trade)
            try:
                V._process_signal(rec)
            except Exception as e:
                with _lock:
                    _stats["err"] = str(e)[:120]
                return False
            with _lock:
                if rec.get("status") == "taken":
                    _stats["took"] += 1
                    # stamp source on trade
                    with V._lock:
                        for tr in V._state["trades"]:
                            if tr.get("dec_id") == oid:
                                tr["source"] = "own"
                                if not str(tr.get("id", "")).startswith("vo"):
                                    tr["id"] = tid
                elif rec.get("status") in ("skipped", "expired"):
                    _stats["skipped"] += 1
            return True
        return False
    except Exception as e:
        with _lock:
            _stats["err"] = str(e)[:120]
        return False


def scan_stats():
    with _lock:
        return dict(_stats, hour_calls=_hour_used())


def compare(V):
    """Per-source stats for /api/vision/compare."""
    _load_sources = True
    with V._lock:
        trades = [dict(t) for t in V._state["trades"]]
        decs = [dict(d) for d in V._state["dec"]]
    out = {}
    for src in ("bot", "own"):
        closed = [t for t in trades if t.get("status") == "closed" and (t.get("source") or "bot") == src]
        opens = [t for t in trades if t.get("status") == "open" and (t.get("source") or "bot") == src]
        wins = [t for t in closed if float(t.get("pnl") or 0) > 0]
        net = sum(float(t.get("pnl") or 0) for t in closed)
        rois = [float(t.get("roi") or 0) for t in closed]
        holds = []
        for t in closed:
            a, b = float(t.get("opened_at") or 0), float(t.get("closed_at") or 0)
            if a and b and b > a:
                holds.append((b - a) / 60.0)
        buy = [t for t in closed if str(t.get("side")).upper() == "BUY"]
        sell = [t for t in closed if str(t.get("side")).upper() == "SELL"]
        n = len(closed)
        block = {
            "closed": n, "open": len(opens),
            "wins": len(wins),
            "win_rate": round(100.0 * len(wins) / n, 1) if n else None,
            "net": round(net, 2),
            "avg_roi": round(sum(rois) / len(rois), 2) if rois else None,
            "avg_hold_min": round(sum(holds) / len(holds), 1) if holds else None,
            "buy": {"n": len(buy), "net": round(sum(float(t.get("pnl") or 0) for t in buy), 2)},
            "sell": {"n": len(sell), "net": round(sum(float(t.get("pnl") or 0) for t in sell), 2)},
            "small_sample": n < 20,
            "verdict_ready": n >= 30,
        }
        out[src] = block
    out["own_scan"] = scan_stats()
    out["own_enabled"] = enabled()
    return out
