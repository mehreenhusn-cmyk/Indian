"""
ai_vision_days.py - daily history for Vision AI (trading day = 5:30 AM IST).

Own file ai/vision_days.json, ~60 days. Rows are SET from data (idempotent), never +=.
Today is always live; past days come from the store. Roll up before KEEP_DEC/TRADES trim.
"""
import os
import threading
import time
from datetime import datetime, timezone, timedelta

KEEP_DAYS = 60
_lock = threading.RLock()
_state = {"days": {}}  # key = "YYYY-MM-DD" (IST date of the 5:30 start) -> row dict
_file = None
_loaded = False
_last_day_key = None


def init(path):
    global _file
    try:
        os.makedirs(path, exist_ok=True)
        _file = os.path.join(path, "vision_days.json")
    except Exception as e:
        print(f"[VisionDays] init: {e}")


def _load():
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            if _file:
                from . import safe_io
                d, _ = safe_io.read_json_safe(_file, "vision_days")
                if isinstance(d, dict) and isinstance(d.get("days"), dict):
                    _state["days"] = {str(k): v for k, v in d["days"].items() if isinstance(v, dict)}
        except Exception as e:
            print(f"[VisionDays] load: {e}")


def _save():
    with _lock:
        if not _file:
            return
        try:
            from . import safe_io
            # keep newest KEEP_DAYS keys
            keys = sorted(_state["days"].keys())
            if len(keys) > KEEP_DAYS:
                for k in keys[:-KEEP_DAYS]:
                    _state["days"].pop(k, None)
            safe_io.write_json_atomic(_file, {"days": _state["days"]})
        except Exception as e:
            print(f"[VisionDays] save: {e}")


def day0_ts(now=None):
    """5:30 AM IST trading-day start as unix epoch. Optional now for tests."""
    if now is None:
        try:
            from . import ai_vision as V
            return float(V._day0_ts())
        except Exception:
            pass
        now = time.time()
    else:
        now = float(now)
    ist = datetime.fromtimestamp(now, tz=timezone.utc) + timedelta(hours=5, minutes=30)
    reset = ist.replace(hour=5, minute=30, second=0, microsecond=0)
    if ist < reset:
        reset = reset - timedelta(days=1)
    return (reset - timedelta(hours=5, minutes=30)).timestamp()


def day_key(now=None):
    """IST date label of the trading day that contains `now` (e.g. 2026-10-21)."""
    t0 = day0_ts(now)
    ist = datetime.fromtimestamp(t0, tz=timezone.utc) + timedelta(hours=5, minutes=30)
    return ist.strftime("%Y-%m-%d")


def day_window(offset=0, now=None):
    """(start_ts, end_ts) for offset=0 today, 1 yesterday, ... Exactly 24h from 5:30 IST."""
    t0 = day0_ts(now)
    start = t0 - offset * 86400
    end = start + 86400
    return start, end


def _status_word(d):
    st = str(d.get("status") or "")
    if st == "taken":
        return "TAKEN"
    if st in ("waiting", "queued"):
        return "WAITING"
    if st in ("late", "error"):
        return "NOT JUDGED"
    return "SKIPPED"


def _build_row(V, start, end, key, live=False):
    """Idempotent SET of one day's summary from current in-memory decs/trades + bot map."""
    bm = V._bot_outcomes()
    with V._lock:
        decs = [dict(d) for d in V._state.get("dec") or []]
        trades = [dict(t) for t in V._state.get("trades") or []]

    day_decs = [d for d in decs if start <= float(d.get("sig_time") or d.get("decided_at") or 0) < end]
    taken = skipped = waiting = queued = not_judged = 0
    delays = []
    for d in day_decs:
        st = str(d.get("status") or "")
        if st == "taken":
            taken += 1
        elif st == "waiting":
            waiting += 1
        elif st == "queued":
            queued += 1
        elif st in ("late", "error"):
            not_judged += 1
        else:
            skipped += 1
        sig_t = float(d.get("sig_time") or 0)
        dec_t = float(d.get("decided_at") or 0)
        if sig_t > 0 and dec_t >= sig_t:
            delays.append(dec_t - sig_t)

    # closed AI trades opened in this window, split by source
    bot_closed = []
    own_closed = []
    for t in trades:
        if t.get("status") != "closed":
            continue
        oa = float(t.get("opened_at") or 0)
        if not (start <= oa < end):
            continue
        src = t.get("source") or "bot"
        (own_closed if src == "own" else bot_closed).append(t)

    def _net(rows):
        return round(sum(float(x.get("pnl") or 0) for x in rows), 2)

    def _wins(rows):
        return sum(1 for x in rows if float(x.get("pnl") or 0) > 0)

    all_closed = bot_closed + own_closed
    best = worst = None
    if all_closed:
        best_t = max(all_closed, key=lambda x: float(x.get("pnl") or 0))
        worst_t = min(all_closed, key=lambda x: float(x.get("pnl") or 0))
        best = {"symbol": best_t.get("symbol"), "pnl": round(float(best_t.get("pnl") or 0), 2)}
        worst = {"symbol": worst_t.get("symbol"), "pnl": round(float(worst_t.get("pnl") or 0), 2)}

    # bot results on same bot-source signals
    bot_decs = [d for d in day_decs if (d.get("source") or "bot") == "bot"]
    taken_bot_pnls = [bm["closed"][d["signal_no"]] for d in bot_decs
                      if d.get("status") == "taken" and d.get("signal_no") in bm["closed"]]
    skip_bot_pnls = [bm["closed"][d["signal_no"]] for d in bot_decs
                     if d.get("status") in ("skipped", "expired") and d.get("signal_no") in bm["closed"]]

    # open AI trades still open from this day
    open_n = sum(1 for t in trades if t.get("status") == "open"
                 and start <= float(t.get("opened_at") or 0) < end)

    # unrealized for live today
    unreal = 0.0
    if live:
        for t in trades:
            if t.get("status") != "open":
                continue
            if not (start <= float(t.get("opened_at") or 0) < end):
                continue
            try:
                tv = V._trade_view(t)
                unreal += float(tv.get("pnl") or 0)
            except Exception:
                pass

    win_rate = None
    if all_closed:
        win_rate = round(100.0 * _wins(all_closed) / len(all_closed), 1)

    calls = 0
    try:
        # approximate: decisions with decided_at in window
        calls = sum(1 for d in day_decs if float(d.get("decided_at") or 0) >= start)
    except Exception:
        pass

    skip_saved = round(sum(-x for x in skip_bot_pnls if x < 0), 2)
    skip_cost = round(sum(x for x in skip_bot_pnls if x > 0), 2)

    return {
        "date": key,
        "start": start,
        "end": end,
        "signals": len(day_decs),
        "taken": taken,
        "skipped": skipped,
        "waiting": waiting,
        "queued": queued,
        "not_judged": not_judged,
        "open": open_n,
        "closed": len(all_closed),
        "wins": _wins(all_closed),
        "win_rate": win_rate,
        "net": _net(all_closed),
        "unrealized": round(unreal, 2),
        "net_bot_source": _net(bot_closed),
        "net_own_source": _net(own_closed),
        "closed_bot": len(bot_closed),
        "closed_own": len(own_closed),
        "bot_on_taken": {"n": len(taken_bot_pnls), "net": round(sum(taken_bot_pnls), 2) if taken_bot_pnls else 0},
        "bot_on_skipped": {"n": len(skip_bot_pnls), "net": round(sum(skip_bot_pnls), 2) if skip_bot_pnls else 0,
                           "saved": skip_saved, "cost": skip_cost},
        "avg_delay_s": round(sum(delays) / len(delays), 1) if delays else None,
        "calls": calls,
        "best": best,
        "worst": worst,
        "live": live,
    }


def rollup(V, now=None):
    """SET today's row from live data; freeze previous day if we crossed the boundary.
    Call before any KEEP_* trim. Idempotent."""
    _load()
    global _last_day_key
    now = time.time() if now is None else float(now)
    key = day_key(now)
    start, end = day_window(0, now)

    with _lock:
        prev = _last_day_key
        _last_day_key = key

    # freeze previous day once when we roll past the boundary
    if prev and prev != key:
        try:
            p_start = day0_ts(now) - 86400
            # rebuild prev from whatever is still in memory
            row = _build_row(V, p_start, p_start + 86400, prev, live=False)
            with _lock:
                _state["days"][prev] = row
        except Exception as e:
            print(f"[VisionDays] freeze prev: {e}")

    row = _build_row(V, start, end, key, live=True)
    with _lock:
        _state["days"][key] = row
    _save()
    return row


def backfill(V):
    """At startup: rebuild any days still represented in memory."""
    _load()
    with V._lock:
        times = []
        for d in V._state.get("dec") or []:
            times.append(float(d.get("sig_time") or d.get("decided_at") or 0))
        for t in V._state.get("trades") or []:
            times.append(float(t.get("opened_at") or 0))
            times.append(float(t.get("closed_at") or 0))
    times = [t for t in times if t > 0]
    if not times:
        rollup(V)
        return
    keys = set()
    for t in times:
        keys.add(day_key(t))
    for k in sorted(keys):
        # reconstruct start from key
        try:
            y, m, d = map(int, k.split("-"))
            ist = datetime(y, m, d, 5, 30, tzinfo=timezone.utc)
            # that datetime is already "IST wall clock as if UTC"; convert to real UTC epoch
            start = (ist - timedelta(hours=5, minutes=30)).timestamp()
            end = start + 86400
            live = (k == day_key())
            row = _build_row(V, start, end, k, live=live)
            with _lock:
                _state["days"][k] = row
        except Exception as e:
            print(f"[VisionDays] backfill {k}: {e}")
    _save()


def get_day_summary(V, offset=0, now=None):
    """offset=0 today (live), 1=yesterday, ..."""
    _load()
    offset = max(0, min(int(offset), 60))
    now = time.time() if now is None else float(now)
    start, end = day_window(offset, now)
    key = day_key(start + 1)  # any time inside the window
    if offset == 0:
        return _build_row(V, start, end, key, live=True)
    with _lock:
        row = _state["days"].get(key)
    if row:
        return dict(row)
    # try rebuild from memory once
    row = _build_row(V, start, end, key, live=False)
    with _lock:
        if row.get("signals") or row.get("closed"):
            _state["days"][key] = row
            _save()
    return row


def list_days(V, n=14, now=None):
    """Last n day rows newest first (today live)."""
    out = []
    for off in range(max(1, int(n))):
        out.append(get_day_summary(V, off, now))
    return out


def _verdict(d, bot_info, ai_trade):
    """Planted-testable plain sentence."""
    word = _status_word(d)
    bot_pnl = None
    bot_state = None
    if isinstance(bot_info, dict):
        bot_state = bot_info.get("state")
        if bot_state == "closed" and bot_info.get("pnl") is not None:
            bot_pnl = float(bot_info["pnl"])

    if word == "NOT JUDGED":
        return "The AI never looked at this one (busy, no quota or error)."

    if word in ("WAITING",):
        return "The AI is still waiting for a better entry."

    if word == "SKIPPED":
        if bot_state == "open" or bot_pnl is None:
            return "AI skipped; the bot result is still open." if bot_state == "open" else "AI skipped; the bot result is not known yet."
        if bot_pnl < 0:
            x = abs(bot_pnl)
            return f"AI skipped; the bot lost {bot_pnl:+.2f}. The skip saved {x:.2f}."
        if bot_pnl > 0:
            return f"AI skipped; the bot made {bot_pnl:+.2f}. The skip cost {bot_pnl:.2f}."
        return "AI skipped; the bot finished flat."

    if word == "TAKEN":
        ai_pnl = None
        ai_open = False
        if isinstance(ai_trade, dict):
            if ai_trade.get("status") == "open":
                ai_open = True
            elif ai_trade.get("pnl") is not None:
                ai_pnl = float(ai_trade["pnl"])
        # refine EXITED/STOPPED from trade
        if isinstance(ai_trade, dict) and ai_trade.get("status") == "closed":
            reason = str(ai_trade.get("exit_reason") or "").lower()
            # still "took it"
            pass
        if ai_open or (bot_state == "open"):
            a = "still open" if ai_open or ai_pnl is None else f"{ai_pnl:+.2f}"
            b = "still open" if bot_state == "open" or bot_pnl is None else f"{bot_pnl:+.2f}"
            return f"AI took it: AI result {a} vs bot result {b}."
        a = f"{ai_pnl:+.2f}" if ai_pnl is not None else "n/a"
        b = f"{bot_pnl:+.2f}" if bot_pnl is not None else "n/a"
        return f"AI took it: AI result {a} vs bot result {b}."

    return ""


def timeline(V, offset=0, limit=200, now=None):
    """Signal rows newest first for one trading day."""
    _load()
    offset = max(0, min(int(offset), 60))
    limit = max(1, min(int(limit), 200))
    now = time.time() if now is None else float(now)
    start, end = day_window(offset, now)
    bm = V._bot_outcomes()
    with V._lock:
        decs = [dict(d) for d in V._state.get("dec") or []]
        trades = [dict(t) for t in V._state.get("trades") or []]
    tv = {t.get("dec_id"): t for t in trades}
    day_decs = [d for d in decs if start <= float(d.get("sig_time") or d.get("decided_at") or 0) < end]
    day_decs.sort(key=lambda d: float(d.get("sig_time") or 0), reverse=True)

    rows = []
    for d in day_decs[:limit]:
        no = d.get("signal_no")
        src = d.get("source") or "bot"
        bot_info = None
        if src == "bot" and no is not None:
            if no in bm["closed"]:
                bot_info = {"state": "closed", "pnl": bm["closed"][no], "opened": True}
            elif no in bm["open"]:
                bot_info = {"state": "open", "pnl": None, "opened": True}
            else:
                bot_info = {"state": "none", "pnl": None, "opened": False}
        else:
            bot_info = {"state": "n/a", "pnl": None, "opened": False, "note": "Bot 2 / own not in Bot 1 map"}

        tr = tv.get(d.get("id"))
        ai_trade = None
        status_word = _status_word(d)
        if tr:
            if tr.get("status") == "closed":
                reason = str(tr.get("exit_reason") or "").lower()
                status_word = "STOPPED" if "stop" in reason else "EXITED"
            ai_trade = {
                "status": tr.get("status"),
                "pnl": tr.get("pnl"),
                "exit_reason": tr.get("exit_reason"),
                "partial": bool(tr.get("partial_done")),
                "partial_pnl": tr.get("partial_pnl"),
            }

        sig_t = float(d.get("sig_time") or 0)
        dec_t = float(d.get("decided_at") or 0)
        delay = round(dec_t - sig_t, 1) if sig_t > 0 and dec_t >= sig_t else None
        try:
            ist = V._ist(sig_t) if sig_t else ""
            # _ist often returns full string; take HH:MM
            signal_ist = ist[-5:] if ist and len(ist) >= 5 else (d.get("sig_ist") or "")
        except Exception:
            signal_ist = d.get("sig_ist") or ""

        rows.append({
            "id": d.get("id"),
            "signal_no": no,
            "symbol": d.get("symbol"),
            "side": d.get("side"),
            "source": src,
            "signal_time": sig_t,
            "signal_ist": signal_ist,
            "price": d.get("sig_price"),
            "bot": bot_info,
            "ai": {
                "status_word": status_word,
                "reason": (d.get("reason") or "")[:120],
                "decided_time": dec_t or None,
                "delay_s": delay,
            },
            "ai_trade": ai_trade,
            "verdict": _verdict(d, bot_info, ai_trade),
        })
    note = ""
    if offset > 0 and not rows:
        note = "No signals left in memory for this day (records may have been trimmed)."
    return rows, note


def day_payload(V, offset=0, now=None):
    summary = get_day_summary(V, offset, now)
    rows, note = timeline(V, offset, 200, now)
    return {"offset": int(offset), "summary": summary, "rows": rows, "note": note,
            "bot_map_note": "Bot results cover Bot 1 only; Bot 2 numbers its signals separately."}
