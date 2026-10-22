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


# ---- scan log: one row per coin per candle, so the app can show what the AI Own scanned and why it skipped
_DUE = {}               # symbol -> epoch seconds when its next closed candle should exist
_TAG_WORDS = {
    "slope_with": "EMA50 slope",
    "tsi_agrees": "TSI vs its signal line",
    "z_agrees": "Z-score vs Z-SMA",
    "ema_agrees": "EMA30 vs EMA50",
}


def _ind_reason(tags, side):
    """Plain words: which indicators agree with the side and which do not."""
    yes = [w for k, w in _TAG_WORDS.items() if tags.get(k) is True]
    no = [w for k, w in _TAG_WORDS.items() if tags.get(k) is False]
    out = []
    if yes:
        out.append("agree: " + ", ".join(yes))
    if no:
        out.append("against: " + ", ".join(no))
    if tags.get("stretched") is True:
        out.append("price is stretched beyond 2SD")
    return "; ".join(out) or "not enough data"


def _level_text(V, candles):
    """Where price sits against the SD bands and EMA50, in plain words. Never raises."""
    try:
        lv = V._levels(candles)[2]
        close = float(lv["close"])
        names = [("+3SD", lv.get("p3")), ("+2SD", lv.get("p2")), ("+1SD", lv.get("p1")), ("mean", lv.get("mean")),
                 ("-1SD", lv.get("m1")), ("-2SD", lv.get("m2")), ("-3SD", lv.get("m3")), ("EMA50", lv.get("e50"))]
        best = None
        for nm, px in names:
            if px:
                dist = abs(close - float(px)) / close * 100.0
                if best is None or dist < best[0]:
                    best = (dist, nm, float(px))
        if not best:
            return ""
        side = "above" if close >= best[2] else "below"
        return f"Price is {best[0]:.2f}% {side} {best[1]} ({best[2]:.6g})"
    except Exception:
        return ""


def _log_scan(V, row):
    row["t"] = time.time()
    with V._lock:
        V._state.setdefault("scan", []).append(row)
        V._state["scan"] = V._state["scan"][-600:]
        V._mark()


def _blocked_reason(V):
    """Why the scanner may not ask the AI right now, or ''. The scan itself still reads the coins."""
    try:                                                      # paper capital manager: daily target / loss lock
        from . import ai_capital as CAP
        why = CAP.lock_reason(V)
        if why:
            return why
    except Exception:
        pass
    try:
        if V.quota_resume_at() > time.time():
            return "AI quota is paused"
    except Exception:
        pass
    cap_h = int(_num("vision_own_max_calls_hour", 12))        # 0 = no limit
    if cap_h > 0 and _hour_used() >= cap_h:
        return f"Hour call limit reached ({cap_h})"
    day_cap = _num("vision_own_daily_loss_cap", 15.0)         # 0 = no daily loss limit
    if day_cap > 0 and _own_day_net(V) <= -abs(day_cap):
        return "daily own loss cap reached"
    if _own_open_count(V) >= int(float(_cfg("vision_own_max_open", 3) or 3)):
        return "Max open AI Own trades reached"
    return ""


def tick(V):
    """Scans the WHOLE watchlist once per closed candle. Coins whose next candle is not due yet are skipped
    without any network call. Stops after one AI ask (returns True) so the Vision loop comes straight back
    for the next coin. Safe to call from the Vision loop when idle."""
    if not enabled() or not V.enabled():
        return False
    blocked = _blocked_reason(V)
    with _lock:
        _stats["err"] = blocked
    if blocked:
        return False                       # nothing is marked as scanned, so the coins are read once the block ends

    syms = _watchlist()
    if not syms:
        with _lock:
            _stats["err"] = "empty watchlist"
        return False

    global _idx
    try:
        from . import settings_store
        tf = int(V._tf_min(settings_store.get("timeframe") or "15m"))
    except Exception:
        tf = 15
    tf_label = f"{tf}m"
    now = time.time()
    with _lock:
        start = _idx % len(syms)
    order = syms[start:] + syms[:start]
    for symbol in order:
        if _DUE.get(symbol, 0) > now:
            continue
        with _lock:
            _idx = (syms.index(symbol) + 1) % len(syms)
        if _own_has_symbol(V, symbol):
            _DUE[symbol] = now + 30
            continue
        try:
            candles = V._fetch(symbol, tf)
            if not candles or len(candles) < 260:
                _DUE[symbol] = now + 60
                continue
            bar_ts = candles[-1].get("timestamp")
            with _lock:
                if _last_bar.get(symbol) == bar_ts:
                    _DUE[symbol] = max(now + 5, (float(bar_ts) / 1000.0) + 2 * tf * 60 + 2)
                    continue
                _last_bar[symbol] = bar_ts
                _stats["scanned"] += 1
                _stats["last_sym"] = symbol
            _DUE[symbol] = (float(bar_ts) / 1000.0) + 2 * tf * 60 + 2
            if _bot_fired(V, symbol, bar_ts):
                _log_scan(V, {"symbol": symbol, "tf": tf_label, "bar_ts": bar_ts, "result": "bot_fired", "side": "",
                              "why": "The bot already signalled this coin on this candle (judged as a bot signal).",
                              "level": "", "ind": ""})
                continue

            from . import ai_ind_features as F
            feat = F.build(candles)
            level = _level_text(V, candles)
            chosen, last_tags, last_side = None, {}, "BUY"
            for side in ("BUY", "SELL"):
                ok, tags = _prefilter(feat, side)
                if ok:
                    chosen = (side, tags)
                    break
                if sum(1 for k in ("slope_with", "tsi_agrees", "z_agrees") if tags.get(k) is True) >= \
                        sum(1 for k in ("slope_with", "tsi_agrees", "z_agrees") if last_tags.get(k) is True) or not last_tags:
                    last_tags, last_side = tags, side
            if not chosen:
                try:                                          # keep a sample of the rejected coins: their shadow outcome shows what the scan missed
                    from . import ai_candidates as AC, ai_evidence as EV
                    if AC.sample_ok(symbol, bar_ts):
                        AC.add("own_scan", symbol, last_side, tf, bar_ts, candles[-1]["close"], candles,
                               AC.tokens_from(EV.extra_tags(feat, last_side, candles), last_tags), "rejected")
                except Exception:
                    pass
                _log_scan(V, {"symbol": symbol, "tf": tf_label, "bar_ts": bar_ts, "result": "no_setup", "side": last_side,
                              "why": "No setup: fewer than 2 of 3 indicators agree" + (", and price is stretched" if last_tags.get("stretched") else "") + ".",
                              "level": level, "ind": _ind_reason(last_tags, last_side)})
                continue

            side, tags = chosen
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
            ind = _ind_reason(tags, side)
            # run the SAME judge path as bot signals (chart, AI, validation, open trade)
            try:
                V._process_signal(rec)
            except Exception as e:
                with _lock:
                    _stats["err"] = str(e)[:120]
                _log_scan(V, {"symbol": symbol, "tf": tf_label, "bar_ts": bar_ts, "result": "error", "side": side,
                              "why": "AI step failed: " + str(e)[:80], "level": level, "ind": ind, "dec_id": oid})
                return False
            result = str(rec.get("status") or "asked")
            with _lock:
                if result == "taken":
                    _stats["took"] += 1
                    with V._lock:
                        for tr in V._state["trades"]:
                            if tr.get("dec_id") == oid:
                                tr["source"] = "own"
                                if not str(tr.get("id", "")).startswith("vo"):
                                    tr["id"] = tid
                elif result in ("skipped", "expired"):
                    _stats["skipped"] += 1
            _log_scan(V, {"symbol": symbol, "tf": tf_label, "bar_ts": bar_ts, "result": result, "side": side,
                          "why": str(rec.get("reason") or "")[:200], "level": level, "ind": ind, "dec_id": oid})
            return True
        except Exception as e:
            with _lock:
                _stats["err"] = str(e)[:120]
            _DUE[symbol] = time.time() + 60
            continue
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


def day_view(V, offset=0):
    """Everything the Vision tab needs for one trading day (5:30 AM IST to 5:30 AM IST), read-only.
    offset 0 = today, 1 = yesterday ..."""
    try:
        from . import ai_vision_days as VD
        d0, d1 = VD.day_window(offset)
    except Exception:
        d0 = V._day0_ts() - 86400 * int(offset)
        d1 = d0 + 86400
    with V._lock:
        decs = [dict(d) for d in V._state["dec"]]
        trades = [dict(t) for t in V._state["trades"]]
        scan = [dict(r) for r in V._state.get("scan", [])]

    def src(x):
        return x.get("source") or "bot"
    bot_decs = [d for d in decs if src(d) == "bot" and d0 <= float(d.get("sig_time") or d.get("decided_at") or 0) < d1]
    tr_by_dec = {t.get("dec_id"): t for t in trades}
    rows = []
    for d in sorted(bot_decs, key=lambda x: float(x.get("sig_time") or 0), reverse=True):
        t = tr_by_dec.get(d.get("id"))
        rows.append({"symbol": d.get("symbol"), "side": d.get("side"), "time": d.get("sig_time"), "status": d.get("status"),
                     "decision": d.get("decision"), "reason": d.get("reason"), "dec_id": d.get("id"),
                     "trade_id": (t or {}).get("id"),
                     "pnl": (t or {}).get("pnl") if (t or {}).get("status") == "closed" else None})
    counts = {"signals": len(bot_decs)}
    for k, sts in (("taken", ("taken",)), ("skipped", ("skipped", "expired")), ("waiting", ("waiting", "queued")),
                   ("not_judged", ("late", "error"))):
        counts[k] = sum(1 for d in bot_decs if d.get("status") in sts)
    bot_tr = [t for t in trades if src(t) == "bot" and d0 <= float(t.get("opened_at") or 0) < d1]
    own_tr = [t for t in trades if src(t) == "own" and d0 <= float(t.get("opened_at") or 0) < d1]
    own_scan = [r for r in scan if d0 <= float(r.get("t") or 0) < d1]

    def net(ts):
        return round(sum(float(t.get("pnl") or 0) for t in ts if t.get("status") == "closed"), 2)

    def margin(ts):
        return round(sum(float(t.get("invest") or 0) for t in ts), 2)
    res = {}
    for r in own_scan:
        res[r.get("result")] = res.get(r.get("result"), 0) + 1
    return {
        "day0": d0, "day1": d1, "offset": int(offset),
        "bot": dict(counts, net=net(bot_tr), margin=margin(bot_tr), trades=len(bot_tr), rows=rows[:200]),
        "own": {"scanned": len(own_scan), "results": res, "trades": len(own_tr), "open": sum(1 for t in own_tr if t.get("status") == "open"),
                "net": net(own_tr), "margin": margin(own_tr),
                "scan_rows": sorted(own_scan, key=lambda r: r.get("t") or 0, reverse=True)[:200],
                "trade_ids": [t.get("id") for t in sorted(own_tr, key=lambda x: float(x.get("opened_at") or 0), reverse=True)][:100],
                "enabled": enabled(), "blocked": scan_stats().get("err", "")},
    }
