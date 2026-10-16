"""
ai_book.py - the "Trade Book" behind the app's AI tab.

Reads the permanent closed-trade archive (trade_store.get_all_closed, fee already
taken off) and returns:
  * summary()  - ALL-TIME numbers (not just today / last 50): net P&L, fees, win
                 rate, payoff, expectancy, profit factor, break-even win rate,
                 streaks, today vs all-time, 14 daily bars, exit-reason split and
                 a few plain-language verdict lines.
  * page()     - one filtered page of trades, newest first.

Everything here is plain arithmetic on real closed trades. Nothing is invented,
nothing is predicted, and nothing here touches trading (read-only).

AI ISOLATION (on purpose): the "health" score below is a screen-only summary
for the user. The AI Assistant / ai_stats / ai_miner must NEVER import this
module or read that score - the AI always works from the raw trades and sample
sizes, so a single number can never replace the real data.
"""
import time
from datetime import datetime, timezone

from . import trade_store

_CACHE = {"t": 0.0, "rows": []}
_TTL = 4.0          # seconds - app polls, archive is a file read
MIN_SAMPLE = 30     # below this the verdict says "not reliable yet"


def _f(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def _rows():
    now = time.time()
    if now - _CACHE["t"] > _TTL:
        try:
            _CACHE["rows"] = trade_store.get_all_closed(20000, net=True)
        except Exception:
            _CACHE["rows"] = []
        _CACHE["t"] = now
    return _CACHE["rows"]


def _reason(t):
    s = str(t.get("status") or t.get("reason") or "")
    return s[7:] if s.startswith("CLOSED_") else (s or "?")


def _compact(t):
    fee = _f(t.get("fee_usdt"))
    return {
        "id": t.get("trade_id", t.get("id")),
        "symbol": t.get("symbol"),
        "side": t.get("action") or t.get("side"),
        "reason": _reason(t),
        "roi": round(_f(t.get("roi_pct")), 2),
        "pnl": round(_f(t.get("pnl_usdt")), 3),
        "fee": round(fee, 3),
        "entry": t.get("entry_price"),
        "exit": t.get("exit_price"),
        "opened": t.get("opened_at_ts"),
        "closed": t.get("closed_at_ts"),
        "dur": round(_f(t.get("duration_s")), 0),
        "peak": t.get("max_roi_pct"),
        "dip": t.get("min_roi_pct"),
        "live": t.get("source") == "live",
        "est": bool(t.get("fee_est")),
        "sl": t.get("signal_stop_loss"),
        "tp1": t.get("signal_tp1"), "tp2": t.get("signal_tp2"), "tp3": t.get("signal_tp3"), "tp4": t.get("signal_tp4"),
        "tf": t.get("timeframe"),
    }


def _day(ts):
    # Binance day == 00:00 UTC == 5:30 AM IST (same boundary the bot's daily reset uses)
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _pf(pnls):
    """profit factor of a list of net P&Ls (None = no losing trade at all)."""
    gp = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p <= 0)
    return (gp / gl) if gl > 0 else None


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def _equity(order, max_pts=120):
    """Gross (before fee) and net (after fee) running totals, oldest -> newest.
    [[closed_ts, gross, net], ...] cut down to <= max_pts evenly spaced points
    (first and last kept). The gap between the two lines is the total fee paid."""
    g = nt = 0.0
    full = []
    for t in order:
        p = _f(t.get("pnl_usdt"))
        fee = _f(t.get("fee_usdt"))
        nt += p
        g += p + fee
        full.append([_f(t.get("closed_at_ts")), round(g, 3), round(nt, 3)])
    if len(full) > max_pts:
        step = (len(full) - 1) / float(max_pts - 1)
        idx = sorted({int(round(i * step)) for i in range(max_pts)} | {len(full) - 1})
        full = [full[i] for i in idx]
    return full


def _health(order, n, win_rate, be_wr, pf, fee_total, gross):
    """0-100 screen-only score from four plain parts (see AI ISOLATION note).
    edge 40 (profit factor) + margin 25 (win-rate vs break-even) + recent 25
    (profit factor of the last 30 trades) + fee 10 (how much of the gross
    profit the fee leaves). Under MIN_SAMPLE trades it is flagged unreliable."""
    parts = []
    # edge: pf 0.5 -> 0 pts, 1.0 -> 20, 1.5+ -> 40 (no losses at all = full)
    e = 40.0 if pf is None else _clamp((pf - 0.5) / 1.0) * 40.0
    parts.append({"name": "Edge (profit factor)", "got": round(e), "max": 40})
    # margin: win-rate 10 points under break-even -> 0, equal -> 12.5, 10 over -> 25
    m = 12.5 if be_wr is None else _clamp((win_rate - be_wr + 10.0) / 20.0) * 25.0
    parts.append({"name": "Win-rate vs break-even", "got": round(m), "max": 25})
    recent = [_f(t.get("pnl_usdt")) for t in order[-30:]]
    rp = _pf(recent) if len(recent) >= 10 else None
    if len(recent) >= 10:
        r = 25.0 if rp is None else _clamp((rp - 0.5) / 1.0) * 25.0
    else:
        r = 12.5
    parts.append({"name": "Pichhle 30 trades", "got": round(r), "max": 25})
    f = _clamp(1.0 - fee_total / gross) * 10.0 if gross > 0 else 0.0
    parts.append({"name": "Net profit bacha", "got": round(f), "max": 10})
    score = int(round(e + m + r + f))
    reliable = n >= MIN_SAMPLE
    if not reliable:
        label = "PAKKA NAHI"
    elif score >= 65:
        label = "MAJBOOT"
    elif score >= 45:
        label = "THEEK"
    else:
        label = "KAMZOR"
    return {"score": score, "label": label, "reliable": reliable, "n": n,
            "min_sample": MIN_SAMPLE, "parts": parts}


def _ist_hour(ts):
    """IST hour (0-23) of a unix timestamp, or None."""
    try:
        ts = float(ts)
        if ts <= 0:
            return None
        return int(((ts + 19800.0) % 86400.0) // 3600.0)
    except Exception:
        return None


def _open_ts(t):
    ts = _f(t.get("opened_at_ts"))
    if ts <= 0:
        ts = _f(t.get("closed_at_ts")) - _f(t.get("duration_s"))
    return ts


def _hours(rows):
    """24 IST hour buckets by the time the trade OPENED: [{h, n, wins, pnl}].
    Net P&L (fee already off). Plain counting, nothing predicted."""
    b = [[0, 0, 0.0] for _ in range(24)]
    for t in rows:
        h = _ist_hour(_open_ts(t))
        if h is None:
            continue
        p = _f(t.get("pnl_usdt"))
        b[h][0] += 1
        b[h][1] += 1 if p > 0 else 0
        b[h][2] += p
    return [{"h": i, "n": v[0], "wins": v[1], "pnl": round(v[2], 3)} for i, v in enumerate(b)]


def summary():
    rows = [t for t in _rows() if t.get("closed_at_ts")]
    n = len(rows)
    if n == 0:
        return {"n": 0, "min_sample": MIN_SAMPLE, "verdict": []}

    pnls = [_f(t.get("pnl_usdt")) for t in rows]
    fees = [_f(t.get("fee_usdt")) for t in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    net = sum(pnls)
    fee_total = sum(fees)
    gross = net + fee_total
    win_rate = len(wins) / n * 100.0
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (-sum(losses) / len(losses)) if losses else 0.0
    expectancy = net / n
    gl = -sum(losses)
    pf = (sum(wins) / gl) if gl > 0 else None
    be_wr = (avg_loss / (avg_win + avg_loss) * 100.0) if (avg_win + avg_loss) > 0 else None

    # streaks (oldest -> newest)
    order = sorted(rows, key=lambda t: _f(t.get("closed_at_ts")))
    cur = best_w = best_l = 0
    for t in order:
        p = _f(t.get("pnl_usdt"))
        if p > 0:
            cur = cur + 1 if cur > 0 else 1
            best_w = max(best_w, cur)
        else:
            cur = cur - 1 if cur < 0 else -1
            best_l = max(best_l, -cur)

    today_key = _day(time.time())
    today = [t for t in rows if _day(_f(t.get("closed_at_ts"))) == today_key]
    t_pnl = sum(_f(t.get("pnl_usdt")) for t in today)
    t_wins = sum(1 for t in today if _f(t.get("pnl_usdt")) > 0)

    by_day = {}
    for t in rows:
        k = _day(_f(t.get("closed_at_ts")))
        d = by_day.setdefault(k, [0, 0.0])
        d[0] += 1
        d[1] += _f(t.get("pnl_usdt"))
    days = [{"d": k, "n": v[0], "pnl": round(v[1], 2)} for k, v in sorted(by_day.items())[-14:]]

    by_reason = {}
    for t in rows:
        r = by_reason.setdefault(_reason(t), [0, 0.0])
        r[0] += 1
        r[1] += _f(t.get("pnl_usdt"))
    reasons = sorted(
        ({"reason": k, "n": v[0], "pnl": round(v[1], 2)} for k, v in by_reason.items()),
        key=lambda x: -x["n"],
    )[:8]

    durs = [_f(t.get("duration_s")) for t in rows if _f(t.get("duration_s")) > 0]

    verdict = []
    verdict.append(
        f"{n} trades ka net {net:+.2f} USDT. "
        f"Har trade ka average {expectancy:+.3f} USDT."
    )
    if be_wr is not None:
        verdict.append(
            f"Aapke avg jeet {avg_win:.2f} aur avg haar {avg_loss:.2f} USDT par break-even ke liye "
            f"win-rate {be_wr:.0f}% chahiye. Abhi {win_rate:.0f}% hai."
        )
    if n < MIN_SAMPLE:
        verdict.append(f"Sirf {n} trades hain. {MIN_SAMPLE}+ se pehle koi bhi pattern pakka nahi.")

    return {
        "n": n,
        "min_sample": MIN_SAMPLE,
        "equity": _equity(order),
        "hours": _hours(rows),
        "health": _health(order, n, win_rate, be_wr, pf, fee_total, gross),
        "net": round(net, 2),
        "gross": round(gross, 2),
        "fees": round(fee_total, 2),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "avg_win": round(avg_win, 3),
        "avg_loss": round(avg_loss, 3),
        "expectancy": round(expectancy, 4),
        "profit_factor": round(pf, 2) if pf is not None else None,
        "breakeven_wr": round(be_wr, 1) if be_wr is not None else None,
        "best": round(max(pnls), 2),
        "worst": round(min(pnls), 2),
        "max_win_streak": best_w,
        "max_loss_streak": best_l,
        "avg_duration_s": round(sum(durs) / len(durs), 0) if durs else 0,
        "today": {"n": len(today), "pnl": round(t_pnl, 2), "wins": t_wins},
        "days": days,
        "reasons": reasons,
        "verdict": verdict,
        "first_ts": min(_f(t.get("closed_at_ts")) for t in rows),
    }


_EMA_CUT = {"t": 0.0, "v": None}


def _ema_cut():
    """steep/flat cut, same as the Insights screen (ai_stats.ema_median); cached 20 s."""
    now = time.time()
    if now - _EMA_CUT["t"] > 20:
        try:
            from . import ai_stats
            _EMA_CUT["v"] = ai_stats.ema_median()
        except Exception:
            _EMA_CUT["v"] = None
        _EMA_CUT["t"] = now
    return _EMA_CUT["v"]


def _group_match(t, grp, gval):
    """Does this trade belong to the Insights group (grp, gval)? Same labels the
    Insights screen shows. Unknown group = no filtering."""
    if grp == "direction":
        return str(t.get("action") or "").upper() == gval.upper()
    if grp == "session":
        return str(t.get("session_tag") or "") == gval
    if grp == "zone":
        return str(t.get("entry_zone") or "") == gval
    if grp == "timeframe":
        return str(t.get("timeframe") or "") == gval
    if grp == "sl_dist":
        try:
            from . import ai_stats
            return ai_stats._sl_bucket(t) == gval
        except Exception:
            return True
    if grp == "ema":
        v = t.get("ema_slope_pct")
        med = _ema_cut()
        if v is None or v == "" or med is None:
            return False
        return ("steep" if abs(_f(v)) >= med else "flat") == gval
    if grp == "volume":
        v = t.get("volume_ratio")
        if v is None or v == "":
            return False
        return ("surge" if _f(v) >= 1.5 else "normal/low") == gval
    return True


def page(offset=0, limit=40, side="", result="", q="", grp="", gval="", hour=-1):
    rows = sorted(_rows(), key=lambda t: -_f(t.get("closed_at_ts")))
    side = (side or "").upper()
    result = (result or "").lower()
    q = (q or "").strip().upper()
    grp = (grp or "").strip()
    gval = (gval or "").strip()
    try:
        hour = int(hour)
    except Exception:
        hour = -1
    out = []
    for t in rows:
        if grp and gval and not _group_match(t, grp, gval):
            continue
        if 0 <= hour <= 23 and _ist_hour(_open_ts(t)) != hour:
            continue
        if side and str(t.get("action") or "").upper() != side:
            continue
        p = _f(t.get("pnl_usdt"))
        if result == "win" and p <= 0:
            continue
        if result == "loss" and p > 0:
            continue
        if q and q not in str(t.get("symbol") or "").upper():
            continue
        out.append(t)
    offset = max(0, int(offset))
    limit = max(1, min(100, int(limit)))
    return {
        "total": len(out),
        "offset": offset,
        "trades": [_compact(t) for t in out[offset:offset + limit]],
    }


def path(trade_id, opened):
    """Price path of ONE closed trade (Trade Book replay). The path logger only
    started recently, so older trades have none: {"ok": False}. ROI here is the
    price move x leverage BEFORE fee (the fee is returned beside it). Down-sampled
    to <= 160 points; each keeps its lowest/highest value so no spike is lost."""
    try:
        from . import ai_path_logger
        _k = ai_path_logger.make_key(trade_id, opened)
        rec = ai_path_logger.open_path_full(_k) or ai_path_logger.read_keys([_k]).get(_k)
        if not rec or not rec.get("s"):
            return {"ok": False}
        smp = rec["s"]
        mx = 160
        if len(smp) > mx:
            step = len(smp) / float(mx)
            red = []
            i = 0.0
            while int(i) < len(smp):
                a, b = int(i), min(len(smp), max(int(i) + 1, int(i + step)))
                ch = smp[a:b]
                red.append([ch[-1][0], ch[-1][1], min(c[2] for c in ch), max(c[3] for c in ch)])
                i += step
            smp = red
        hi = max(smp, key=lambda x: x[3])
        lo = min(smp, key=lambda x: x[2])
        return {
            "ok": True,
            "symbol": rec.get("symbol"),
            "side": rec.get("action"),
            "levels": rec.get("levels") or {},
            "pts": smp,
            "peak": {"t": hi[0], "v": hi[3]},
            "dip": {"t": lo[0], "v": lo[2]},
            "roi_final": rec.get("roi_final"),
            "fee": rec.get("fee"),
            "reason": rec.get("reason"),
            "gaps": rec.get("gaps") or 0,
            "dur": smp[-1][0],
        }
    except Exception:
        return {"ok": False}
