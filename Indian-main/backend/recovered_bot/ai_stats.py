"""
ai_stats.py - turns the closed-trade history into statistics for the AI
Assistant (text) and the Dashboard "AI Insights" card (structured data).

WHY THIS EXISTS: an LLM must never do the maths itself (it invents numbers).
All counting/averaging happens here in plain Python; the AI only explains the
result in Hinglish and the card only displays it. Read-only: it never changes
trading behaviour and never raises - any failure just returns "" / an empty
result so the chat and the dashboard keep working.

  build_insights()  -> dict   (GET /api/ai/insights -> ai_insights_card.dart)
  build_summary()   -> str    (ai_assistant.py prompt context)
Both come from the SAME numbers, so the card and the AI can never disagree.

Data source: trade_store.get_recent_closed() - the rolling closed-trade cache,
which already carries peak_roi_pct (MFE), worst_drawdown_pct (MAE), session,
exit reason, and (for trades opened after tagging was added) entry_zone /
ema_slope_pct / volume_ratio / timeframe. Paper AND live trades are included.
"""
from . import trade_store
try:
    from . import ai_miner
except Exception:      # miner is optional - never break the old stats
    ai_miner = None
try:
    from . import ai_ml
except Exception:
    ai_ml = None
try:
    from . import ai_playbook
except Exception:
    ai_playbook = None
try:
    from . import ai_rules
except Exception:
    ai_rules = None

LOW_SAMPLE = 30      # below this many closed trades, tell the AI "not enough data"
MIN_GROUP = 5        # a group (zone/session/...) with fewer trades is not shown
VOL_SURGE = 1.5      # volume_ratio at/above this = "volume surge"


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _has(v):
    return v is not None and v != ""


def _grouped(trades, key_fn):
    """[{label, n, wins, win_rate, avg_roi, pnl}] for every group of at least
    MIN_GROUP trades, sorted by label."""
    groups = {}
    for t in trades:
        k = key_fn(t)
        if k is not None:
            groups.setdefault(k, []).append(t)
    rows = []
    for k, v in sorted(groups.items()):
        n = len(v)
        if n < MIN_GROUP:
            continue
        wins = sum(1 for t in v if _f(t.get("pnl_usdt")) > 0)
        rows.append({
            "label": str(k),
            "n": n,
            "wins": wins,
            "win_rate": wins / n * 100.0,
            "avg_roi": sum(_f(t.get("roi_pct")) for t in v) / n,
            "pnl": sum(_f(t.get("pnl_usdt")) for t in v),
            # what-if ("agar ye group skip hota"): winners lost, losses avoided, fee saved
            "win_pnl": sum(_f(t.get("pnl_usdt")) for t in v if _f(t.get("pnl_usdt")) > 0),
            "loss_pnl": sum(_f(t.get("pnl_usdt")) for t in v if _f(t.get("pnl_usdt")) <= 0),
            "fee": sum(_f(t.get("fee_usdt")) for t in v),
        })
    return rows


def _sl_dist_pct(t):
    """SL distance from entry in PRICE % (not leveraged ROI), from the
    strategy's own signal_stop_loss saved on every trade. None if unknown."""
    try:
        e = float(t.get("entry_price"))
        sl = float(t.get("signal_stop_loss"))
        if e <= 0 or sl <= 0:
            return None
        return abs(e - sl) / e * 100.0
    except (TypeError, ValueError):
        return None


def _sl_bucket(t):
    d = _sl_dist_pct(t)
    if d is None:
        return None
    if d < 1.0:
        return "0-1%"
    if d < 2.0:
        return "1-2%"
    if d < 4.0:
        return "2-4%"
    return "4%+"


# Data quality (tag written by paper_trader at close). The AI LEARNS PATTERNS only
# from "clean" trades and old untagged ones ("unknown" = closed before tagging
# existed - kept, not thrown away). Recovered / reversed / outdated /
# restart_affected trades still count in the money numbers (P&L, win rate) but
# their exit, peak or drawdown is estimated or the signal was stale.
_LEARN_TAGS = ("clean", "unknown")


def _tag(t):
    return t.get("quality_tag") or "unknown"


def _quality_summary(trades):
    q = {"clean": 0, "unknown": 0, "excluded": {}}
    for t in trades:
        tg = _tag(t)
        if tg in _LEARN_TAGS:
            q[tg] += 1
        else:
            q["excluded"][tg] = q["excluded"].get(tg, 0) + 1
    return q


def _gap_lessons(trades):
    """What the AI can learn from the NON-clean trades WITHOUT mixing them into
    strategy patterns: how often the bot missed/delayed a signal, and how much
    those trades differ in result from clean ones. Money-only facts (count, win
    rate, avg P&L) - never entry/exit-shape patterns, those are estimated."""
    def agg(ts):
        if not ts:
            return None
        pn = [_f(t.get("pnl_usdt")) for t in ts]
        return {"n": len(ts), "wins": sum(1 for x in pn if x > 0), "avg": sum(pn) / len(pn)}
    by = {}
    for t in trades:
        tg = _tag(t)
        if tg not in _LEARN_TAGS:
            by.setdefault(tg, []).append(t)
    if not by:
        return None
    out = {"clean": agg([t for t in trades if _tag(t) in _LEARN_TAGS]),
           "tags": {k: agg(v) for k, v in by.items()}}
    return out


def _sd_path(learn):
    """How far price moved in SD units from entry, winners vs losers."""
    rows = [t for t in learn if _has(t.get("sd_best_move")) and _has(t.get("sd_worst_move"))]
    if len(rows) < MIN_GROUP:
        return None

    def part(ts):
        if not ts:
            return None
        mins = [_f(t.get("sd_best_min")) for t in ts if _has(t.get("sd_best_min"))]
        return {"n": len(ts),
                "best": sum(_f(t.get("sd_best_move")) for t in ts) / len(ts),
                "worst": sum(_f(t.get("sd_worst_move")) for t in ts) / len(ts),
                "best_min": (sum(mins) / len(mins)) if mins else None}

    return {"n": len(rows),
            "win": part([t for t in rows if _f(t.get("pnl_usdt")) > 0]),
            "loss": part([t for t in rows if _f(t.get("pnl_usdt")) <= 0]),
            "bands": _grouped(rows, lambda t: t.get("sd_best_band") or None)}


def _open_stats():
    """Live snapshot of OPEN trades (paper or live) - their profit is not in
    closed stats yet, so without this the AI wrongly calls a payoff-style
    strategy a failure. Never raises."""
    try:
        from . import status
        pos = status.get().get("open_positions", []) or []
        if not pos:
            return {"n": 0}
        rois = [_f(p.get("roi_pct")) for p in pos]
        return {
            "n": len(pos),
            "pnl": sum(_f(p.get("pnl_usdt")) for p in pos),
            "green_n": sum(1 for r in rois if r > 0),
            "avg_roi": sum(rois) / len(rois),
            "best_roi": max(rois),
            "worst_roi": min(rois),
            "avg_peak": sum(_f(p.get("max_roi_pct")) for p in pos) / len(pos),
            "tp1_n": sum(1 for p in pos if p.get("tp_hit_levels")),
        }
    except Exception:
        return {"n": 0}


IST_OFFSET_S = 5.5 * 3600
_LOSS_RUN = 5          # this many losses in a row = a "bad phase"
_FAST_SL_MIN = 15.0    # an SL this soon after entry = quick stop-out (chop / SL hunt sign)


def _ts(t):
    return _f(t.get("closed_at_ts"), 0.0)


def build_cycle():
    """The bot's day-to-day rhythm, all counted by code from the permanent
    closed-trade archive (survives restarts / new builds):
      - today by IST hour (W/L, P&L), today vs yesterday
      - current + longest loss run, last-10 W/L
      - quick-stop share (SL within _FAST_SL_MIN minutes) for last 20 trades
      - what usually happened AFTER a bad phase (next 10 trades)
      - 'phase' = choppy / recovering / normal (a hint, never a rule)
    Never raises; returns {} when there is no history."""
    try:
        trades = trade_store.get_all_closed(5000)
        trades = [t for t in trades if _ts(t) > 0]
        if not trades:
            return {}
        import time as _t
        now = _t.time()
        day_len = 86400.0
        ist_day = lambda ts: int((ts + IST_OFFSET_S) // day_len)
        today_i = ist_day(now)
        pnl = lambda t: _f(t.get("pnl_usdt"))

        def day_stats(d):
            xs = [t for t in trades if ist_day(_ts(t)) == d]
            return {"n": len(xs), "w": sum(1 for t in xs if pnl(t) > 0),
                    "l": sum(1 for t in xs if pnl(t) <= 0), "pnl": sum(pnl(t) for t in xs)}

        out = {"today": day_stats(today_i), "yesterday": day_stats(today_i - 1),
               "days_of_history": len({ist_day(_ts(t)) for t in trades}), "total": len(trades)}

        hours = {}
        for t in trades:
            if ist_day(_ts(t)) != today_i:
                continue
            h = int(((_ts(t) + IST_OFFSET_S) % day_len) // 3600)
            r = hours.setdefault(h, {"h": h, "n": 0, "w": 0, "pnl": 0.0})
            r["n"] += 1
            r["w"] += 1 if pnl(t) > 0 else 0
            r["pnl"] += pnl(t)
        out["hours"] = [hours[h] for h in sorted(hours)]

        # loss runs over the whole history
        runs, cur = [], 0
        for t in trades:
            if pnl(t) <= 0:
                cur += 1
            else:
                if cur:
                    runs.append(cur)
                cur = 0
        cur_run = cur
        if cur:
            runs.append(cur)
        out["loss_run_now"] = cur_run
        out["loss_run_max"] = max(runs) if runs else 0
        last10 = trades[-10:]
        out["last10"] = {"w": sum(1 for t in last10 if pnl(t) > 0), "l": sum(1 for t in last10 if pnl(t) <= 0)}

        last20 = trades[-20:]
        sl20 = [t for t in last20 if pnl(t) <= 0]
        fast = [t for t in sl20 if 0 < _f(t.get("duration_minutes"), 0.0) <= _FAST_SL_MIN]
        out["fast_sl"] = {"n": len(fast), "of": len(last20)}

        # what came after a bad phase (>= _LOSS_RUN losses in a row)?
        after = []
        i, n = 0, len(trades)
        while i < n:
            if pnl(trades[i]) <= 0:
                j = i
                while j < n and pnl(trades[j]) <= 0:
                    j += 1
                if j - i >= _LOSS_RUN and j < n:
                    nxt = trades[j:j + 10]
                    after.append({"n": len(nxt), "w": sum(1 for t in nxt if pnl(t) > 0),
                                  "pnl": sum(pnl(t) for t in nxt)})
                i = j
            else:
                i += 1
        if after:
            out["after_bad_phase"] = {
                "phases": len(after),
                "positive": sum(1 for a in after if a["pnl"] > 0),
                "avg_pnl_next10": sum(a["pnl"] for a in after) / len(after),
            }

        last5_losses = sum(1 for t in trades[-5:] if pnl(t) <= 0)
        if cur_run >= _LOSS_RUN or (out["fast_sl"]["of"] >= 10 and out["fast_sl"]["n"] >= 0.5 * out["fast_sl"]["of"]
                                    and last5_losses >= 3):
            out["phase"] = "choppy"
        elif out["last10"]["w"] >= 3 and cur_run == 0:
            out["phase"] = "recovering"
        else:
            out["phase"] = "normal"
        return out
    except Exception:
        return {}


def _cycle_lines(c):
    if not c:
        return []
    td, yd = c["today"], c["yesterday"]
    L = [f"Bot cycle (code-counted from {c['total']} archived trades over {c['days_of_history']} days):"]
    L.append(f"  Today: {td['n']} closed, {td['w']}W/{td['l']}L, P&L {td['pnl']:+.2f} USDT | "
             f"Yesterday: {yd['n']} closed, {yd['w']}W/{yd['l']}L, P&L {yd['pnl']:+.2f} USDT")
    if c.get("hours"):
        L.append("  Today by IST hour: " + ", ".join(
            f"{h['h']:02d}h {h['w']}W/{h['n'] - h['w']}L {h['pnl']:+.0f}" for h in c["hours"]))
    L.append(f"  Losses in a row right now: {c['loss_run_now']} (longest ever {c['loss_run_max']}); "
             f"last 10 trades: {c['last10']['w']}W/{c['last10']['l']}L")
    fs = c["fast_sl"]
    if fs["of"]:
        L.append(f"  Quick stop-outs (loss within {_FAST_SL_MIN:.0f} min): {fs['n']} of last {fs['of']} trades")
    ab = c.get("after_bad_phase")
    if ab:
        L.append(f"  After {ab['phases']} earlier bad phases ({_LOSS_RUN}+ losses in a row): "
                 f"{ab['positive']} were followed by profit in the next 10 trades "
                 f"(avg next-10 P&L {ab['avg_pnl_next10']:+.2f} USDT)")
    L.append(f"  Phase hint (by code): {c['phase'].upper()}")
    return L


# ---------------------------------------------------------------------------
# Speed / regime / filter-simulation helpers (all plain counting - the AI only
# explains what these return, it never calculates).
MIN_RULE = 8          # a group needs at least this many trades to appear as a take/avoid candidate


def _median(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    m = len(vals) // 2
    return vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2.0


def _regime_bucket(t):
    """EMA50 crosses in the last 20 candles at entry: 1 = clean fresh cross,
    2 = mixed, 3+ = choppy (price keeps flipping around EMA50 = sideways)."""
    if not _has(t.get("regime_cross_n")):
        return None
    n = int(_f(t.get("regime_cross_n")))
    if n <= 1:
        return "clean cross (1 in 20 candles)"
    if n == 2:
        return "mixed (2 crosses)"
    return "choppy (3+ crosses)"


def _median_split(rows, field, lo_label, hi_label):
    """Group rows by whether `field` is at/above the median of this sample."""
    vals = [abs(_f(t.get(field))) for t in rows if _has(t.get(field))]
    if len(vals) < MIN_GROUP * 2:
        return [], None
    med = _median(vals)
    have = [t for t in rows if _has(t.get(field))]
    return _grouped(have, lambda t: hi_label if abs(_f(t.get(field))) >= med else lo_label), med


def _behaviour_part(ts):
    n = len(ts)
    wins = sum(1 for t in ts if _f(t.get("pnl_usdt")) > 0)
    hit = [t for t in ts if t.get("tp_hit_levels")]
    t1 = [_f(t.get("tp1_min")) for t in ts if _has(t.get("tp1_min"))]
    dur = [_f(t.get("duration_minutes")) for t in ts if _has(t.get("duration_minutes"))]
    quick = sum(1 for t in ts if _f(t.get("pnl_usdt")) <= 0
                and _has(t.get("duration_minutes")) and _f(t.get("duration_minutes")) <= _FAST_SL_MIN)
    return {
        "n": n, "wins": wins, "win_rate": wins / n * 100.0,
        "pnl": sum(_f(t.get("pnl_usdt")) for t in ts),
        "tp1_reach": len(hit) / n * 100.0,
        "tp1_min": _median(t1), "tp1_timed": len(t1),
        "quick_sl": quick / n * 100.0,
        "hold_min": _median(dur),
    }


def _behaviour_label(g, base):
    """Code-decided label. FAST = reaches TP1 more often AND sooner than the
    overall average; QUICK-SL = half or more of its trades stop out within
    _FAST_SL_MIN minutes AND that is at least 10 points worse than the overall
    quick-SL rate (this strategy loses most trades by design, so the absolute
    rate alone says nothing); SIDEWAYS = rarely reaches TP1 and trades hang around
    longer than average (no clean move either way); otherwise MIXED."""
    if g["quick_sl"] >= 50.0 and g["quick_sl"] >= base["quick_sl"] + 10.0:
        return "QUICK-SL"
    faster = (g["tp1_min"] is not None and base.get("tp1_min") is not None
              and g["tp1_min"] <= base["tp1_min"])
    if g["tp1_reach"] > base["tp1_reach"] and (faster or base.get("tp1_min") is None or g["tp1_min"] is None):
        return "FAST"
    slow = (g["hold_min"] is not None and base.get("hold_min") is not None
            and g["hold_min"] >= base["hold_min"])
    if g["tp1_reach"] < base["tp1_reach"] * 0.6 and slow:
        return "SIDEWAYS"
    return "MIXED"


def _behaviour_table(rows, key_fn, base):
    groups = {}
    for t in rows:
        k = key_fn(t)
        if k is not None:
            groups.setdefault(k, []).append(t)
    out = []
    for k, ts in sorted(groups.items()):
        if len(ts) < MIN_GROUP:
            continue
        g = _behaviour_part(ts)
        g["label"] = str(k)
        g["tag"] = _behaviour_label(g, base)
        out.append(g)
    return out


_KIND_NAMES = {
    "direction": "direction", "session": "session", "zone": "SD zone at entry",
    "ema": "EMA slope", "volume": "signal-candle volume", "sl_dist": "SL distance",
    "timeframe": "timeframe", "regime": "market regime", "atr": "volatility (ATR%)",
    "sd_width": "SD band width", "hour": "entry hour (IST)",
}


def _simulate(groups, total_n, top=4):
    """Hindsight filter simulation: for each group, what total P&L would have
    been if the bot had skipped that group's trades. Groups that lost money are
    AVOID candidates, groups that made money are TAKE candidates."""
    avoid, take = [], []
    all_n = total_n or 0
    all_wins = sum(r["wins"] for r in groups.get("direction", []))   # direction splits every trade once
    base_wr = (all_wins / sum(r["n"] for r in groups["direction"]) * 100.0) if groups.get("direction") else None
    for kind, rows in groups.items():
        for g in rows:
            if g["n"] < MIN_RULE:
                continue
            if all_n and g["n"] / all_n >= 0.9:
                continue            # covers (almost) every trade - not a filter, tells nothing
            if base_wr is not None:
                # must actually differ from average, otherwise it is just noise
                if g["pnl"] < 0 and g["win_rate"] >= base_wr:
                    continue
                if g["pnl"] > 0 and g["win_rate"] <= base_wr:
                    continue
            item = {"kind": _KIND_NAMES.get(kind, kind), "label": g["label"], "n": g["n"],
                    "wins": g["wins"], "pnl": g["pnl"],
                    "share": g["n"] / total_n * 100.0 if total_n else 0.0}
            if g["pnl"] < 0:
                avoid.append(item)
            elif g["pnl"] > 0:
                take.append(item)
    avoid.sort(key=lambda x: x["pnl"])             # biggest loser first
    take.sort(key=lambda x: -x["pnl"])             # biggest earner first
    return {"avoid": avoid[:top], "take": take[:top], "min_rule": MIN_RULE}


def _speed_block(learn, base_ctx):
    """Speed/behaviour tables: overall baseline + by SD zone + by regime + zone x regime."""
    if not learn:
        return None
    base = _behaviour_part(learn)
    ctx = [t for t in learn if _has(t.get("entry_zone"))]
    reg = [t for t in learn if _has(t.get("regime_cross_n"))]
    both = [t for t in reg if _has(t.get("entry_zone"))]
    return {
        "overall": base,
        "zone": _behaviour_table(ctx, lambda t: t.get("entry_zone"), base),
        "regime": _behaviour_table(reg, _regime_bucket, base),
        "zone_regime": _behaviour_table(
            both, lambda t: f"{t.get('entry_zone')} + {_regime_bucket(t)}", base),
        "regime_trades": len(reg),
    }


# ---------------------------------------------------------------------------
# TP ladder: how far trades climb TP1 -> TP4, how long each step takes, and
# where they stall. Pure counting on tp_hit_levels / tpN_min.
_MIN_LADDER = 5


def _ladder_part(ts):
    n = len(ts)
    hit = {k: [t for t in ts if k in (t.get("tp_hit_levels") or [])] for k in (1, 2, 3, 4)}

    def mins(k):
        return [_f(t.get(f"tp{k}_min")) for t in hit[k] if _has(t.get(f"tp{k}_min"))]

    def gaps(k):          # minutes from TP1 touch to TPk touch
        return [_f(t.get(f"tp{k}_min")) - _f(t.get("tp1_min")) for t in hit[k]
                if _has(t.get(f"tp{k}_min")) and _has(t.get("tp1_min"))]

    out = {"n": n, "reach": {k: len(hit[k]) / n * 100.0 for k in hit},
           "count": {k: len(hit[k]) for k in hit},
           "entry_min": {k: _median(mins(k)) for k in (1, 2, 3, 4)},
           "after_tp1_min": {k: _median(gaps(k)) for k in (2, 3, 4)}}
    n1 = len(hit[1])
    # conversion: of the trades that touched TP1, how many went on to TP2/3/4
    out["conv"] = {k: (len(hit[k]) / n1 * 100.0 if n1 else None) for k in (2, 3, 4)}
    stalled = [t for t in hit[1] if 2 not in (t.get("tp_hit_levels") or [])]
    out["stalled_after_tp1"] = len(stalled)
    out["stalled_pnl"] = sum(_f(t.get("pnl_usdt")) for t in stalled)
    # WHY did the stalled trades end? SL/TSL = the market came back (profit given
    # back); SCALP/MANUAL/REVERSED = the bot/user closed it, the market never got
    # a chance to reach TP2; TP = it simply reached its (lower) target.
    why = {"market reversed (SL/TSL)": 0, "closed early by bot/user (SCALP/MANUAL/REVERSED)": 0,
           "reached its own target (TP)": 0, "other": 0}
    for t in stalled:
        r = t.get("clean_exit_reason") or ""
        if r in ("SL", "TSL"):
            why["market reversed (SL/TSL)"] += 1
        elif r in ("SCALP", "MANUAL", "REVERSED"):
            why["closed early by bot/user (SCALP/MANUAL/REVERSED)"] += 1
        elif r == "TP":
            why["reached its own target (TP)"] += 1
        else:
            why["other"] += 1
    out["stalled_why"] = {k: v for k, v in why.items() if v}
    # "profit khaa gayi": touched TP1 (so it WAS in profit) but finished flat/negative
    out["tp1_then_loss"] = sum(1 for t in hit[1] if _f(t.get("pnl_usdt")) <= 0)
    gb = [_f(t.get("peak_roi_pct")) - _f(t.get("roi_pct")) for t in hit[1]
          if _has(t.get("peak_roi_pct")) and _has(t.get("roi_pct"))]
    out["giveback"] = (sum(gb) / len(gb)) if gb else None
    out["pnl"] = sum(_f(t.get("pnl_usdt")) for t in ts)
    out["win_rate"] = sum(1 for t in ts if _f(t.get("pnl_usdt")) > 0) / n * 100.0
    return out


def _ladder_table(rows, key_fn):
    groups = {}
    for t in rows:
        k = key_fn(t)
        if k is not None:
            groups.setdefault(k, []).append(t)
    res = []
    for k, ts in sorted(groups.items()):
        if len(ts) < _MIN_LADDER:
            continue
        g = _ladder_part(ts)
        g["label"] = str(k)
        res.append(g)
    return res


def _ladder_block(learn):
    if not learn:
        return None
    ctx = [t for t in learn if _has(t.get("entry_zone"))]
    reg = [t for t in learn if _has(t.get("regime_cross_n"))]
    timed = sum(1 for t in learn if _has(t.get("tp1_min")))
    return {"overall": _ladder_part(learn), "zone": _ladder_table(ctx, lambda t: t.get("entry_zone")),
            "regime": _ladder_table(reg, _regime_bucket), "timed_trades": timed}


def _fmt_m(v):
    return f"~{v:.0f}m" if v is not None else "n/a"


def _ladder_line(g):
    r, c = g["reach"], g["conv"]
    em, am = g["entry_min"], g["after_tp1_min"]
    cv = lambda k: (f"{c[k]:.0f}%" if c.get(k) is not None else "n/a")
    return (f"  {g['label']}: {g['n']} trades | reached TP1 {r[1]:.0f}% ({_fmt_m(em[1])} from entry), "
            f"TP2 {r[2]:.0f}%, TP3 {r[3]:.0f}%, TP4 {r[4]:.0f}% | of those that hit TP1, went on to "
            f"TP2 {cv(2)} (+{_fmt_m(am[2])} after TP1), TP3 {cv(3)} (+{_fmt_m(am[3])}), TP4 {cv(4)} (+{_fmt_m(am[4])}) | "
            f"stalled after TP1 (never TP2): {g['stalled_after_tp1']} trades, P&L {g['stalled_pnl']:+.2f} USDT"
            + (" - ended by: " + ", ".join(f"{k} x{v}" for k, v in g["stalled_why"].items()) if g.get("stalled_why") else "")
            + (f" | TP1 touched but finished flat/loss: {g['tp1_then_loss']}/{g['count'][1]}"
               f", avg profit given back from peak {g['giveback']:.1f}% ROI" if g.get("giveback") is not None else ""))


# ---------------------------------------------------------------------------
# MARKET REVERSAL AFTER TP1: among trades that touched TP1 (so they WERE in
# profit), which ended because the market came back (SL / TSL-breakeven)?
# Where (zone/regime/volatility/EMA/volume/direction), when (session, IST time
# block, minutes after TP1), and at which SD band price topped out before it
# turned. Pure counting - the AI only reads it.
_REV_MIN = 4          # TP1-touchers needed in a group before it is shown
_REVERSAL_EXITS = ("SL", "TSL")


def _is_reversed(t):
    return (t.get("clean_exit_reason") or "") in _REVERSAL_EXITS


def _ist_block(t):
    """4-hour IST block of the moment TP1 was touched (falls back to entry time)."""
    ts = t.get("tp1_ts") or t.get("opened_at_ts")
    if not _has(ts):
        return None
    try:
        h = int(((float(ts) + IST_OFFSET_S) % 86400) // 3600)
    except (TypeError, ValueError):
        return None
    lo = (h // 4) * 4
    return f"{lo:02d}-{lo + 4:02d} IST"


def _mode(vals):
    vals = [v for v in vals if v]
    if not vals:
        return None
    best = max(set(vals), key=vals.count)
    return best, vals.count(best)


def _rev_part(ts):
    n = len(ts)
    rev = [t for t in ts if _is_reversed(t)]
    after = []
    for t in rev:                       # minutes from the TP1 touch to the reversal exit
        if _has(t.get("duration_minutes")) and _has(t.get("tp1_min")):
            d = _f(t.get("duration_minutes")) - _f(t.get("tp1_min"))
            if d >= 0:
                after.append(d)
    peaks = [_f(t.get("peak_roi_pct")) for t in rev if _has(t.get("peak_roi_pct"))]
    fins = [_f(t.get("roi_pct")) for t in rev if _has(t.get("roi_pct"))]
    return {"n": n, "rev": len(rev), "rate": len(rev) / n * 100.0 if n else 0.0,
            "after_min": _median(after),
            "peak": (sum(peaks) / len(peaks)) if peaks else None,
            "final": (sum(fins) / len(fins)) if fins else None,
            "band": _mode([t.get("sd_best_band") for t in rev]),
            "pnl": sum(_f(t.get("pnl_usdt")) for t in rev)}


def _rev_table(rows, key_fn):
    groups = {}
    for t in rows:
        k = key_fn(t)
        if k is not None:
            groups.setdefault(k, []).append(t)
    out = []
    for k, ts in sorted(groups.items()):
        if len(ts) < _REV_MIN:
            continue
        g = _rev_part(ts)
        g["label"] = str(k)
        out.append(g)
    return out


def _reversal_block(learn):
    touched = [t for t in learn if 1 in (t.get("tp_hit_levels") or [])]
    if len(touched) < _REV_MIN:
        return None
    base = _rev_part(touched)
    slopes = sorted(abs(_f(t.get("ema_slope_pct"))) for t in touched if _has(t.get("ema_slope_pct")))
    med_slope = slopes[len(slopes) // 2] if len(slopes) >= _REV_MIN * 2 else None
    atrs = sorted(abs(_f(t.get("atr_pct"))) for t in touched if _has(t.get("atr_pct")))
    med_atr = atrs[len(atrs) // 2] if len(atrs) >= _REV_MIN * 2 else None
    tables = {
        "SD zone at entry": _rev_table([t for t in touched if _has(t.get("entry_zone"))], lambda t: t.get("entry_zone")),
        "market regime": _rev_table(touched, _regime_bucket),
        "direction": _rev_table(touched, lambda t: t.get("action")),
        "session": _rev_table(touched, lambda t: t.get("session_tag") or None),
        "time of day (IST, when TP1 was touched)": _rev_table(touched, _ist_block),
        "volume on signal candle": _rev_table(
            [t for t in touched if _has(t.get("volume_ratio"))],
            lambda t: "surge" if _f(t.get("volume_ratio")) >= VOL_SURGE else "normal/low"),
    }
    if med_slope is not None:
        tables["EMA slope"] = _rev_table(
            [t for t in touched if _has(t.get("ema_slope_pct"))],
            lambda t: "steep" if abs(_f(t.get("ema_slope_pct"))) >= med_slope else "flat")
    if med_atr is not None:
        tables["volatility (ATR%)"] = _rev_table(
            [t for t in touched if _has(t.get("atr_pct"))],
            lambda t: "violent candles" if abs(_f(t.get("atr_pct"))) >= med_atr else "calm candles")
    # quick reversals: how many reversals came within 10 min of the TP1 touch
    quick = 0
    for t in touched:
        if _is_reversed(t) and _has(t.get("duration_minutes")) and _has(t.get("tp1_min")):
            if 0 <= _f(t.get("duration_minutes")) - _f(t.get("tp1_min")) <= 10:
                quick += 1
    pool = [dict(g, kind=k) for k, rows in tables.items() for g in rows]
    hot = sorted([g for g in pool if g["rate"] >= base["rate"] + 15.0 and g["rev"] >= 3 and g["n"] >= 6],
                 key=lambda g: (-g["rate"], -g["n"]))[:4]
    calm = sorted([g for g in pool if g["rate"] <= base["rate"] - 15.0 and g["n"] >= 6],
                  key=lambda g: (g["rate"], -g["n"]))[:3]
    return {"base": base, "tables": {k: v for k, v in tables.items() if v}, "quick": quick,
            "hot": hot, "calm": calm}


def _rev_line(g):
    bits = [f"{g['label']}: {g['rev']}/{g['n']} TP1-touchers reversed ({g['rate']:.0f}%)"]
    if g.get("after_min") is not None:
        bits.append(f"usually ~{g['after_min']:.0f} min after TP1")
    if g.get("peak") is not None and g.get("final") is not None:
        bits.append(f"peak {g['peak']:+.1f}% ROI -> exit {g['final']:+.1f}%")
    if g.get("band"):
        bits.append(f"price topped out in {g['band'][0]} ({g['band'][1]}x)")
    return "  " + ", ".join(bits)


def ema_median(limit=200):
    """The 'steep vs flat' EMA-slope cut the Insights screen uses (median of |slope| over the
    same trade pool as build_insights), or None while there are too few trades. Lets the Trade
    Book filter an EMA row with exactly the same cut."""
    try:
        trades = trade_store.get_recent_closed(limit, net=True)
        ctx = [t for t in trades if _tag(t) in _LEARN_TAGS and _has(t.get("entry_zone")) and _has(t.get("ema_slope_pct"))]
        slopes = sorted(abs(_f(t.get("ema_slope_pct"))) for t in ctx)
        return slopes[len(slopes) // 2] if len(slopes) >= MIN_GROUP * 2 else None
    except Exception:
        return None


def build_insights(limit=200):
    """Structured statistics dict. Always has "sample" (0 = nothing yet)."""
    try:
        trades = trade_store.get_recent_closed(limit, net=True)  # most recent first, fee-adjusted
        n = len(trades)
        out = {"sample": n, "min_sample": LOW_SAMPLE, "low_sample": n < LOW_SAMPLE}
        if not n:
            return out

        wins = [t for t in trades if _f(t.get("pnl_usdt")) > 0]
        losses = [t for t in trades if _f(t.get("pnl_usdt")) <= 0]
        out["overall"] = {
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / n * 100.0,
            "avg_win": sum(_f(t.get("roi_pct")) for t in wins) / len(wins) if wins else 0.0,
            "avg_loss": sum(_f(t.get("roi_pct")) for t in losses) / len(losses) if losses else 0.0,
        }
        avg_win = out["overall"]["avg_win"]
        avg_loss = out["overall"]["avg_loss"]
        if avg_win > 0 and avg_loss < 0:
            ratio = avg_win / abs(avg_loss)
            out["payoff"] = {
                "ratio": ratio,                                  # 1 win = `ratio` losses
                "breakeven_wr": 100.0 / (1.0 + ratio),           # win rate needed to break even
            }
        closed_pnl = sum(_f(t.get("pnl_usdt")) for t in trades)
        op = _open_stats()
        out["open"] = op
        out["closed_pnl"] = closed_pnl
        out["combined_pnl"] = closed_pnl + (op.get("pnl", 0.0) if op.get("n") else 0.0)
        # TP1 reach: did the trade ever touch TP1 (monotonic tp_hit_levels)?
        tp_seen = [t for t in trades if isinstance(t.get("tp_hit_levels"), list) and _tag(t) in _LEARN_TAGS]
        if tp_seen:
            hit = [t for t in tp_seen if t.get("tp_hit_levels")]
            out["tp_reach"] = {
                "n": len(tp_seen),
                "hit_tp1": len(hit),
                "hit_tp1_then_lost": sum(1 for t in hit if _f(t.get("pnl_usdt")) <= 0),
            }

        # Pattern learning pool (see _LEARN_TAGS). Money numbers above/below stay on ALL trades.
        learn = [t for t in trades if _tag(t) in _LEARN_TAGS]
        out["quality"] = _quality_summary(trades)
        out["gap_lessons"] = _gap_lessons(trades)
        out["learn_n"] = len(learn)
        out["sd_path"] = _sd_path(learn)
        ctx = [t for t in learn if _has(t.get("entry_zone"))]
        out["context_trades"] = len(ctx)
        groups = {
            "direction": _grouped(learn, lambda t: t.get("action")),
            "session": _grouped(learn, lambda t: t.get("session_tag") or None),
            "zone": [], "ema": [], "volume": [],
            "sl_dist": _grouped(learn, _sl_bucket),
            "timeframe": _grouped(learn, lambda t: t.get("timeframe") or None),
        }
        out["ema_median"] = None
        if ctx:
            groups["zone"] = _grouped(ctx, lambda t: t.get("entry_zone"))
            with_slope = [t for t in ctx if _has(t.get("ema_slope_pct"))]
            slopes = sorted(abs(_f(t.get("ema_slope_pct"))) for t in with_slope)
            if len(slopes) >= MIN_GROUP * 2:
                median = slopes[len(slopes) // 2]
                out["ema_median"] = median
                groups["ema"] = _grouped(
                    with_slope,
                    lambda t: "steep" if abs(_f(t.get("ema_slope_pct"))) >= median else "flat",
                )
            groups["volume"] = _grouped(
                [t for t in ctx if _has(t.get("volume_ratio"))],
                lambda t: "surge" if _f(t.get("volume_ratio")) >= VOL_SURGE else "normal/low",
            )
        # Market-regime groups (only trades opened after regime tagging existed).
        reg_rows = [t for t in learn if _has(t.get("regime_cross_n"))]
        groups["regime"] = _grouped(reg_rows, _regime_bucket)
        groups["atr"], out["atr_median"] = _median_split(reg_rows, "atr_pct", "calm candles", "violent candles")
        groups["sd_width"], out["sd_width_median"] = _median_split(reg_rows, "sd_width_pct", "narrow SD bands", "wide SD bands")
        groups["hour"] = _grouped(learn, _hour_block)
        out["groups"] = groups
        out["speed"] = _speed_block(learn, None)
        out["sim"] = _simulate(groups, len(learn))
        try:
            out["story"] = build_story(trades, groups, len(learn))
        except Exception:
            out["story"] = None
        out["ladder"] = _ladder_block(learn)
        out["reversal"] = _reversal_block(learn)
        out["cycle"] = build_cycle()
        try:
            out["playbook"] = ai_playbook.build_playbook() if ai_playbook else None
        except Exception:
            out["playbook"] = None
        try:
            out["rules"] = ai_rules.build_rules() if ai_rules else None
        except Exception:
            out["rules"] = None
        out["miner"] = ai_miner.build_miner() if ai_miner else None
        out["ml"] = ai_ml.build_ml() if ai_ml else None

        # ---- best / weakest situation (tentative hint for the card) ----
        pool = [dict(g, kind=k) for k, rows in groups.items() for g in rows]
        if len(pool) >= 2:
            best = max(pool, key=lambda g: (g["win_rate"], g["n"]))
            worst = min(pool, key=lambda g: (g["win_rate"], -g["n"]))
            if best is not worst:
                out["best"] = best
                out["worst"] = worst

        # ---- MFE / MAE: what the trade saw BEFORE it closed ----
        mfe_mae = [t for t in learn if _has(t.get("peak_roi_pct")) and _has(t.get("worst_drawdown_pct"))]
        mm = {"loser": None, "winner": None}
        l2 = [t for t in mfe_mae if _f(t.get("pnl_usdt")) <= 0]
        w2 = [t for t in mfe_mae if _f(t.get("pnl_usdt")) > 0]
        if l2:
            thr = max(abs(avg_win) / 2.0, 0.5)
            mm["loser"] = {
                "n": len(l2),
                "avg_mfe": sum(_f(t.get("peak_roi_pct")) for t in l2) / len(l2),
                "green_n": sum(1 for t in l2 if _f(t.get("peak_roi_pct")) >= thr),
                "thr": thr,
            }
        if w2:
            mm["winner"] = {
                "n": len(w2),
                "avg_mae": sum(_f(t.get("worst_drawdown_pct")) for t in w2) / len(w2),
                "giveback": sum(_f(t.get("peak_roi_pct")) - _f(t.get("roi_pct")) for t in w2) / len(w2),
            }
        out["mfe_mae"] = mm if (mm["loser"] or mm["winner"]) else None

        # ---- exits + weak symbols ----
        exits = {}
        for t in trades:
            r = t.get("clean_exit_reason") or "UNKNOWN"
            e = exits.setdefault(r, [0, 0.0])
            e[0] += 1
            e[1] += _f(t.get("pnl_usdt"))
        top = sorted(exits.items(), key=lambda kv: -kv[1][0])[:5]
        out["exits"] = [{"reason": r, "count": c, "pnl": p} for r, (c, p) in top]

        by_sym = {}
        for t in trades:
            by_sym.setdefault(t.get("symbol"), []).append(_f(t.get("pnl_usdt")))
        weak = sorted(((s, sum(v), len(v)) for s, v in by_sym.items() if s and len(v) >= 3),
                      key=lambda x: x[1])[:3]
        out["weak_coins"] = [{"symbol": s, "pnl": p, "n": c} for s, p, c in weak if p < 0]
        out["coins"] = coin_report(trades)
        return out
    except Exception:
        return {"sample": 0, "min_sample": LOW_SAMPLE, "low_sample": True}


def _hour_block(t):
    """3-hour IST block the trade OPENED in ('21:00-23:59'). 3h blocks (not 24 single hours)
    so each block has enough trades to mean something. None if the open time is unknown."""
    ts = _f(t.get("opened_at_ts")) or (_f(t.get("closed_at_ts")) - _f(t.get("duration_s")))
    if ts <= 0:
        return None
    h = int(((ts + 19800.0) % 86400.0) // 3600.0)
    a = (h // 3) * 3
    return f"{a:02d}:00-{a + 2:02d}:59"


# ---------------------------------------------------------------- the "story" --
# One plain-language answer to: "where is the strategy being hurt, where does it earn,
# and for each hurt-spot: SKIP those trades, or CHANGE that part of the strategy?"
# Pure counting on the same closed trades as everything else (never predicts, never
# changes the bot). The Insights top card shows it and build_summary() gives the SAME
# lines to the chat AI, so you and the AI read the same facts.
STORY_SOLID = 30        # a spot with >= this many trades is "pakka", fewer = "ishaara"
_SKIP_KINDS = ("hour", "session", "direction", "timeframe")   # WHEN / WHICH SIDE -> skip trades
_STORY_HINT = {
    "sl_dist": "SL ka distance rule badlo (door SL) ya aise signal skip karo",
    "zone": "Is SD zone mein entry ka rule badlo ya skip karo",
    "ema": "EMA slope ka filter lagao",
    "volume": "Volume ka filter lagao",
    "regime": "Sideways/choppy bazaar ka filter lagao",
    "atr": "Volatility ka filter lagao",
    "sd_width": "SD band ki chaudai ka filter lagao",
}


def _story_title(kind, label):
    if kind == "hour":
        return f"{label} (IST) ke beech khule trade"
    if kind == "sl_dist":
        return f"SL entry se {label} door wale trade"
    if kind == "zone":
        return f"Entry SD zone '{label}' mein"
    if kind == "session":
        return f"{label} session ke trade"
    if kind == "direction":
        return f"{label} trade"
    if kind == "timeframe":
        return f"{label} timeframe ke trade"
    if kind == "ema":
        return "EMA slope tez (steep) hone par" if label == "steep" else "EMA slope dheela (flat) hone par"
    if kind == "volume":
        return "Signal candle par volume surge hone par" if label == "surge" else "Signal candle par volume normal/kam hone par"
    return f"{label}"


def _story_item(kind, g, learn_n):
    k = _KIND_NAMES.get(kind, kind)
    skip = kind in _SKIP_KINDS
    n, wins, pnl = g["n"], g["wins"], g["pnl"]
    it = {
        "kind": kind, "title": _story_title(kind, g["label"]), "n": n, "wins": wins,
        "win_rate": round(g["win_rate"]), "pnl": round(pnl, 2),
        "share": round(n / learn_n * 100.0) if learn_n else 0,
        "sure": n >= STORY_SOLID,
        "action": "skip" if skip else "change",
        "what": k,
    }
    if pnl < 0:
        it["effect"] = round(-pnl, 2)    # past P&L change had these trades been skipped (hindsight)
        it["hint"] = "In trades ko skip karke dekho" if skip else _STORY_HINT.get(kind, "Strategy ka ye hissa badalne par socho")
    return it


def build_story(trades, groups, learn_n, top=3):
    """{n, net, win_rate, killers[], earners[], verdict, low}. Uses _simulate (take/avoid
    candidates: group must differ from the average and have >= MIN_RULE trades)."""
    n = len(trades)
    if not n:
        return None
    net = sum(_f(t.get("pnl_usdt")) for t in trades)
    wins = sum(1 for t in trades if _f(t.get("pnl_usdt")) > 0)
    sim = _simulate(groups, learn_n, top=60)

    def pick(items):
        out, seen = [], set()
        for it in items:                      # one per kind first, so the card shows variety
            if it["kind"] not in seen:
                seen.add(it["kind"])
                out.append(it)
            if len(out) >= top:
                return out
        return out

    by_kind = {}
    for kind, rows in groups.items():
        for g in rows:
            by_kind[(_KIND_NAMES.get(kind, kind), g["label"])] = (kind, g)
    def build(items):
        res = []
        for x in items:
            kg = by_kind.get((x["kind"], x["label"]))
            if kg:
                res.append(_story_item(kg[0], kg[1], learn_n))
        return res
    # a "spot" covering most trades is the strategy itself, not a filter -> not shown as a killer
    killers = pick([x for x in build(sim["avoid"]) if x["share"] <= 70])
    earners = pick(build(sim["take"]))
    low = n < LOW_SAMPLE
    if killers:
        k = killers[0]
        verdict = (f"Sabse bada nuksaan: {k['title']} ({k['n']} trade, {k['win_rate']}% jeete, {k['pnl']:+.0f} USDT). "
                   + ("Ye trade skip karke dekho." if k["action"] == "skip" else "Strategy ka ye hissa badalne par socho."))
    else:
        verdict = "Abhi koi ek jagah saaf nuksaan wali nahi mili (ya trades kam hain)."
    return {"n": n, "net": round(net, 2), "wins": wins, "win_rate": round(wins / n * 100.0),
            "low": low, "killers": killers, "earners": earners, "verdict": verdict,
            "note": "Ye pichhle trades ka hindsight hai. Alag-alag numbers jodo mat, trade overlap ho sakte hain."}


def story_lines(st):
    """Same story as plain text for the chat AI prompt (numbers come ONLY from code)."""
    if not st:
        return []
    L = [f"STRATEGY KAHAN MAAR KHA RAHI HAI (code se, last {st['n']} closed trades, net {st['net']:+.2f} USDT, "
         f"win {st['win_rate']}%). Har jagah ke liye batao: SKIP (trade chhodo) ya CHANGE (strategy ka hissa badlo):"]
    for tag, rows in (("NUKSAAN", st.get("killers") or []), ("KAMAYI", st.get("earners") or [])):
        for it in rows:
            sure = "pakka" if it["sure"] else "sirf ishaara (kam trades)"
            act = ""
            if tag == "NUKSAAN":
                act = (f" -> agar skip hota to P&L ~{it['effect']:+.2f} behtar; suggestion: "
                       f"{'SKIP' if it['action'] == 'skip' else 'CHANGE'} ({it.get('hint', '')})")
            L.append(f"  {tag}: {it['title']}: {it['n']} trades, {it['wins']} jeete ({it['win_rate']}%), "
                     f"P&L {it['pnl']:+.2f} USDT [{sure}]{act}")
    L.append("  NOTE: ye hindsight hai; skip karne par us group ke winners bhi hat jaate hain; numbers jodo mat (overlap).")
    return L


def coin_report(trades, min_n=3, top=8):
    """Per-coin report card (screen + AI text): trades, wins, net P&L, fee. A coin gets the
    'DHYAN SE' tag when it has >= 4 trades and its net P&L is negative. Plain counting only -
    the tag is a heads-up, the bot never skips a coin because of it."""
    by = {}
    for t in trades:
        s = t.get("symbol")
        if s:
            by.setdefault(s, []).append(t)
    rows = []
    for s, v in by.items():
        n = len(v)
        if n < min_n:
            continue
        pnl = sum(_f(t.get("pnl_usdt")) for t in v)
        wins = sum(1 for t in v if _f(t.get("pnl_usdt")) > 0)
        rows.append({"symbol": s, "n": n, "wins": wins, "win_rate": wins / n * 100.0, "pnl": pnl,
                     "fee": sum(_f(t.get("fee_usdt")) for t in v),
                     "caution": bool(n >= 4 and pnl < 0)})
    rows.sort(key=lambda r: r["pnl"])
    return rows[:top]


def _line(g):
    return (f"  {g['label']}: {g['n']} trades, win {g['win_rate']:.0f}%, "
            f"avg ROI {g['avg_roi']:+.2f}%, P&L {g['pnl']:+.2f} USDT")


def build_summary(limit=200):
    """Multi-line text summary for the AI prompt, or "" if no closed trades."""
    try:
        d = build_insights(limit)
        n = d.get("sample", 0)
        if not n:
            return ""
        o = d["overall"]
        g = d["groups"]
        lines = [f"Strategy statistics (computed by code from last {n} closed trades - use ONLY these numbers):"]
        if d["low_sample"]:
            lines.append(f"  ⚠ LOW SAMPLE: only {n} trades (<{LOW_SAMPLE}). Say clearly that patterns are "
                         f"not reliable yet; do NOT present any pattern as a fact.")
        lines.append(f"  Overall: win rate {o['win_rate']:.0f}% ({o['wins']}W/{o['losses']}L), "
                     f"avg win {o['avg_win']:+.2f}% ROI, avg loss {o['avg_loss']:+.2f}% ROI")

        qd = d.get("quality")
        if qd:
            ex = qd["excluded"]
            ex_txt = (", ".join(f"{k} {v}" for k, v in sorted(ex.items())) if ex else "none")
            lines.append(f"  DATA QUALITY: {qd['clean']} clean, {qd['unknown']} older untagged (kept as usable), "
                         f"excluded from pattern learning: {ex_txt}. Win rate / P&L here count ALL trades "
                         f"(real result); every 'By ...' pattern below learns only from the {d.get('learn_n', 0)} "
                         f"clean+older trades. Recovered/restart-affected trades have exits, peaks and drawdowns "
                         f"estimated from 5m candles; outdated/reversed ones had a stale or opposite signal.")
        gl = d.get("gap_lessons")
        if gl and gl.get("tags"):
            parts = []
            for k, v in sorted(gl["tags"].items()):
                if v:
                    parts.append(f"{k}: {v['n']} trades, {v['wins']}W, avg {v['avg']:+.2f} USDT")
            cl = gl.get("clean")
            cl_txt = f"clean: {cl['n']} trades, {cl['wins']}W, avg {cl['avg']:+.2f} USDT" if cl else "clean: n/a"
            lines.append("  GAP LESSONS (money facts only, NOT strategy patterns): " + "; ".join(parts) +
                         f" | {cl_txt}. Use these to explain how much missed/late signals cost or helped and to "
                         f"say the bot's uptime/connection matters; never use these trades to claim an SD/zone/"
                         f"time pattern, and never say they 'prove' anything while their count is small.")
        po = d.get("payoff")
        if po:
            lines.append(f"  Payoff: 1 average win = {po['ratio']:.1f} average losses, so this strategy "
                         f"breaks even at ~{po['breakeven_wr']:.0f}% win rate. A low win rate alone is NOT failure.")
        lines += story_lines(d.get("story"))
        if ai_playbook and d.get("playbook"):
            lines += ai_playbook.playbook_lines(d.get("playbook"))
        if ai_rules and d.get("rules"):
            lines += ai_rules.rules_lines(d.get("rules"))
        op = d.get("open") or {}
        if op.get("n"):
            lines.append(f"  OPEN trades right now ({op['n']}): unrealized {op['pnl']:+.2f} USDT, "
                         f"{op['green_n']} in profit, avg ROI {op['avg_roi']:+.2f}%, best {op['best_roi']:+.2f}%, "
                         f"worst {op['worst_roi']:+.2f}%, {op['tp1_n']} already touched TP1. "
                         f"These are NOT counted in the win rate above (still running).")
        lines += _cycle_lines(d.get("cycle"))
        lines.append(f"  Closed P&L {d.get('closed_pnl', 0):+.2f} USDT; closed + open together "
                     f"{d.get('combined_pnl', 0):+.2f} USDT")
        tr = d.get("tp_reach")
        if tr:
            lines.append(f"  TP1 reached by {tr['hit_tp1']}/{tr['n']} closed trades; "
                         f"{tr['hit_tp1_then_lost']} of them still ended as a loss")

        def block(title, rows):
            return ([title] + [_line(r) for r in rows]) if rows else []

        lines += block("By direction:", g["direction"])
        lines += block("By session:", g["session"])
        lines.append(f"Entry-context data available for {d['context_trades']}/{n} trades "
                     f"(older trades were opened before tagging existed).")
        lines += block("By timeframe:", g.get("timeframe") or [])
        lines += block("By SL distance from entry (price %):", g.get("sl_dist") or [])
        lines += block("By SD zone at entry:", g["zone"])
        if d.get("ema_median") is not None:
            lines += block(f"By EMA slope (steep = |slope| >= {d['ema_median']:.3f}% over 3 candles):", g["ema"])
        lines += block(f"By volume on signal candle (surge = >= {VOL_SURGE}x avg of prev 20):", g["volume"])

        lines += block("By market regime at entry (EMA50 crosses in the last 20 candles; many = sideways/choppy):",
                       g.get("regime") or [])
        if d.get("atr_median") is not None:
            lines += block(f"By volatility at entry (violent = ATR% >= {d['atr_median']:.3f}%):", g.get("atr") or [])
        if d.get("sd_width_median") is not None:
            lines += block(f"By SD band width at entry (wide = 1SD >= {d['sd_width_median']:.3f}% of mean):",
                           g.get("sd_width") or [])

        sb = d.get("speed")
        if sb and sb.get("overall"):
            o2 = sb["overall"]
            t1 = f"~{o2['tp1_min']:.0f} min" if o2.get("tp1_min") is not None else "n/a"
            lines.append(f"SPEED / BEHAVIOUR (code labels: FAST = reaches TP1 more often AND sooner than average; "
                         f"SIDEWAYS = rarely reaches TP1 and holds longer than average; QUICK-SL = half+ of trades "
                         f"stop out within {_FAST_SL_MIN:.0f} min AND clearly more than the baseline). Baseline of all learn trades: TP1 reach "
                         f"{o2['tp1_reach']:.0f}%, median time to TP1 {t1}, quick-SL {o2['quick_sl']:.0f}%:")

            def _beh(title, rows):
                if not rows:
                    return
                lines.append(title)
                for r in rows:
                    tt = f"TP1 in ~{r['tp1_min']:.0f} min" if r.get("tp1_min") is not None else "TP1 time n/a"
                    hold = f", held ~{r['hold_min']:.0f} min" if r.get("hold_min") is not None else ""
                    lines.append(f"  {r['label']}: {r['n']} trades, win {r['win_rate']:.0f}%, P&L {r['pnl']:+.2f} USDT, "
                                 f"TP1 reach {r['tp1_reach']:.0f}%, {tt}, quick-SL {r['quick_sl']:.0f}%{hold} -> {r['tag']}")

            _beh("  By SD zone:", sb.get("zone"))
            _beh("  By market regime:", sb.get("regime"))
            _beh("  By SD zone + regime (most specific; needs the most data):", sb.get("zone_regime"))
            if not (sb.get("zone") or sb.get("regime")):
                lines.append("  (no group has enough trades yet - say the data is still thin)")

        ld = d.get("ladder")
        if ld and ld.get("overall") and ld["overall"]["count"][1]:
            lines.append("TP LADDER (how far trades climb TP1->TP4 and how long each step takes; minutes are medians "
                         f"over trades that actually touched that level; {ld['timed_trades']} trades have timing data). "
                         "NOTE: a trade closes at its target level (default TP4), by SL, or by scalp/manual close, so "
                         "levels above the close were never tested; TP2-TP4 can share one price near the band edge and "
                         "then hit together (0 min gap):")
            lines.append(_ladder_line(dict(ld["overall"], label="ALL learn trades")))
            if ld.get("zone"):
                lines.append("  By SD zone at entry:")
                lines += [_ladder_line(g) for g in ld["zone"]]
            if ld.get("regime"):
                lines.append("  By market regime:")
                lines += [_ladder_line(g) for g in ld["regime"]]
            # zones where TP1 is common but TP2 rarely follows
            weak = [g for g in (ld.get("zone") or []) if g["count"][1] >= 3 and g["conv"].get(2) is not None
                    and g["conv"][2] < 40.0]
            if weak:
                lines.append("  ZONES WHERE TP2/TP3 RARELY HIT after TP1 (TP2 conversion < 40%, >=3 TP1 trades): "
                             + "; ".join(f"{g['label']} ({g['conv'][2]:.0f}% -> TP2, {g['conv'][3] if g['conv'][3] is None else round(g['conv'][3])}% -> TP3)"
                                         for g in weak))
        if ld and ld.get("overall") and ld["overall"]["count"][1]:
            cand = [g for g in (ld.get("zone") or []) + (ld.get("regime") or [])]
            best = sorted([g for g in cand if g["pnl"] > 0 and g["win_rate"] >= ld["overall"]["win_rate"]
                           and (g["count"][1] == 0 or g["tp1_then_loss"] / max(g["count"][1], 1) < 0.25)],
                          key=lambda g: -g["pnl"])[:3]
            eaters = sorted([g for g in cand if g["count"][1] >= 3
                             and g["tp1_then_loss"] / g["count"][1] >= 0.30],
                            key=lambda g: -(g["tp1_then_loss"] / g["count"][1]))[:3]
            lines.append("WHEN THE STRATEGY IS BEST vs WHEN IT EATS PROFIT (code-picked from the ladder groups above; "
                         "'eats profit' = trade touched TP1 so it WAS in profit, then finished flat/negative):")
            for g in best:
                lines.append(f"  BEST: {g['label']} - {g['n']} trades, win {g['win_rate']:.0f}%, P&L {g['pnl']:+.2f} USDT, "
                             f"only {g['tp1_then_loss']}/{g['count'][1]} TP1-touchers gave the profit back")
            for g in eaters:
                lines.append(f"  EATS PROFIT: {g['label']} - {g['tp1_then_loss']}/{g['count'][1]} trades that touched TP1 "
                             f"ended flat/loss, avg {g['giveback'] if g['giveback'] is not None else 0:.1f}% ROI given back from peak")
            if not best and not eaters:
                lines.append("  (no group clearly stands out yet - say the data is still thin)")
        rv = d.get("reversal")
        if rv:
            b = rv["base"]
            lines.append("MARKET REVERSAL AFTER TP1 (trades that touched TP1 were IN profit; 'reversed' = they then ended "
                         "by SL/TSL-breakeven, i.e. the market came back and ate the profit. Hindsight counts from "
                         f"{b['n']} TP1-touching trades; groups need >= {_REV_MIN} such trades):")
            lines.append(f"  OVERALL: {b['rev']}/{b['n']} reversed ({b['rate']:.0f}%)"
                         + (f", median ~{b['after_min']:.0f} min after the TP1 touch" if b.get("after_min") is not None else "")
                         + (f", price usually topped out in {b['band'][0]}" if b.get("band") else "")
                         + f"; {rv['quick']} of them reversed within 10 min of TP1")
            for title, rows in rv["tables"].items():
                lines.append(f"  By {title}:")
                lines += ["  " + _rev_line(g) for g in rows]
            if rv["hot"]:
                lines.append("  REVERSAL HOT-SPOTS (reverse clearly MORE often than average): "
                             + "; ".join(f"{g['kind']} = {g['label']} ({g['rate']:.0f}%, n={g['n']})" for g in rv["hot"]))
            if rv["calm"]:
                lines.append("  HOLDS PROFIT BEST (reverse clearly LESS often): "
                             + "; ".join(f"{g['kind']} = {g['label']} ({g['rate']:.0f}%, n={g['n']})" for g in rv["calm"]))
            if not rv["hot"] and not rv["calm"]:
                lines.append("  (no group with >= 6 TP1-touchers differs clearly from the average yet - say the data is still thin)")
            if d.get("low_sample"):
                lines.append("  ⚠ Sample is LOW - every reversal pattern above is a weak hint, not a rule.")
        sim = d.get("sim")
        if sim and (sim.get("avoid") or sim.get("take")):
            lines.append(f"FILTER SIMULATION (HINDSIGHT on closed learn-trades, groups of >= {sim['min_rule']} trades). "
                         f"It shows what skipping a group WOULD HAVE changed in the past - not a promise; skipping also "
                         f"removes that group's winners. The bot itself still takes every signal:")
            for it in sim.get("avoid") or []:
                lines.append(f"  AVOID candidate - {it['kind']} = {it['label']}: {it['n']} trades "
                             f"({it['wins']}W/{it['n'] - it['wins']}L), P&L {it['pnl']:+.2f} USDT -> skipping would have "
                             f"changed total P&L by {-it['pnl']:+.2f} USDT ({it['share']:.0f}% of trades removed)")
            for it in sim.get("take") or []:
                lines.append(f"  TAKE candidate - {it['kind']} = {it['label']}: {it['n']} trades "
                             f"({it['wins']}W/{it['n'] - it['wins']}L), P&L {it['pnl']:+.2f} USDT "
                             f"({it['share']:.0f}% of trades)")
            if d.get("low_sample"):
                lines.append("  ⚠ Sample is LOW - treat every candidate above as a weak hint to keep watching, never as a rule.")
        elif d.get("learn_n", 0):
            lines.append("FILTER SIMULATION: no group has enough trades yet (needs >= "
                         f"{MIN_RULE} per group) - say there is no take/avoid evidence yet.")

        sp = d.get("sd_path")
        if sp:
            lines.append(f"SD path (distance price travelled from the entry, in SD units; {sp['n']} trades with data):")
            for key, name in (("win", "Winners"), ("loss", "Losers")):
                x = sp.get(key)
                if x:
                    when = f", usually after ~{x['best_min']:.0f} min" if x.get("best_min") is not None else ""
                    lines.append(f"  {name} ({x['n']}): best move {x['best']:.2f} SD in favour{when}; "
                                 f"worst move {x['worst']:.2f} SD against")
            lines += block("By farthest SD band reached in favour (hindsight - how far trades ran, not an entry filter):",
                           sp.get("bands") or [])

        mm = d.get("mfe_mae")
        if mm:
            lines.append("MFE/MAE (MFE = best profit trade saw before closing, MAE = worst loss it saw):")
            if mm["loser"]:
                l = mm["loser"]
                lines.append(f"  Losers: avg MFE {l['avg_mfe']:+.2f}%; {l['green_n']}/{l['n']} losers were at least "
                             f"{l['thr']:+.2f}% in profit at some point before turning into a loss")
            if mm["winner"]:
                w = mm["winner"]
                lines.append(f"  Winners: avg MAE {w['avg_mae']:+.2f}% (dip suffered before winning); "
                             f"avg profit given back from peak to exit {w['giveback']:.2f}% ROI")

        lines.append("Exits: " + ", ".join(f"{e['reason']} x{e['count']} ({e['pnl']:+.2f} USDT)" for e in d["exits"]))
        if d["weak_coins"]:
            lines.append("Weakest coins (>=3 trades): " + ", ".join(
                f"{w['symbol']} {w['pnl']:+.2f} USDT/{w['n']}" for w in d["weak_coins"]))
        if ai_miner:
            mt = ai_miner.build_text()
            if mt:
                lines.append(mt)
        try:
            from . import ai_shadow_lab
            lt = ai_shadow_lab.build_text()
            if lt:
                lines.append(lt)
            from . import ai_learning
            lg = ai_learning.build_text()
            if lg:
                lines.append(lg)
        except Exception:
            pass
        if ai_ml:
            ml = ai_ml.build_text()
            if ml:
                lines.append(ml)
        return "\n".join(lines)
    except Exception:
        return ""
