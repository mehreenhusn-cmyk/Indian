"""doctor_verdict.py - plain-language "what should I change" layer on top of the Strategy Doctor rows.

READ-ONLY. Never touches the engine, strategy or any live rule. Input = rows from india_doctor.rows().
Answers (each group is checked: older 70% vs newest 30% of trades, same split the Doctor uses):
  1. Profit leakage  - peak profit vs final result, trades that hit TP1 and still lost, money given back
  2. How long to hold - win rate / result by holding time
  3. When to trade   - time of day, index, CE/PE side, timeframe, SD entry zone
  4. Verdict         - 4-7 plain sentences; "not enough data" when the sample is small
Old trades that lack a field are simply left out of that table.
"""
from datetime import datetime, timedelta, timezone

MIN_SAMPLE = 30          # same as strategy_doctor
MIN_GROUP = 8            # trades a group needs before it is judged at all
TRAIN_FRAC = 0.70
IST = timezone(timedelta(hours=5, minutes=30))

HOLD_BANDS = [(0, 5, "under 5 min"), (5, 15, "5-15 min"), (15, 30, "15-30 min"),
              (30, 60, "30-60 min"), (60, 1e9, "over 60 min")]
TOD_BANDS = [(9 * 60 + 15, 10 * 60 + 30, "09:15-10:30 (open)"), (10 * 60 + 30, 12 * 60, "10:30-12:00"),
             (12 * 60, 13 * 60 + 30, "12:00-13:30 (lunch)"), (13 * 60 + 30, 15 * 60 + 30, "13:30-15:30 (close)")]


def _f(v):
    try:
        x = float(v)
        return x if x == x else None
    except Exception:
        return None


def _stat(rs):
    n = len(rs)
    if not n:
        return {"n": 0, "win_rate": 0.0, "avg_roi": 0.0, "net": 0.0}
    return {"n": n, "win_rate": round(sum(1 for r in rs if r["pnl_usdt"] > 0) / n * 100, 1),
            "avg_roi": round(sum(r["roi_pct"] for r in rs) / n, 2), "net": round(sum(r["pnl_usdt"] for r in rs), 2)}


Z_TRAIN = 2.0            # same bars as strategy_doctor: a group must beat/lose to the REST of the trades by this many
Z_TEST = 1.64            # standard errors on the older 70% AND again on the newest 30%
MIN_OLD, MIN_NEW = 15, 5


def _zs(group, rest, kind):
    """Standard-error distance between the group's avg ROI and the rest's. Positive = group worse ('avoid') / better ('take')."""
    try:
        if len(group) < 2 or len(rest) < 2:
            return 0.0
        g = [r["roi_pct"] for r in group]
        o = [r["roi_pct"] for r in rest]
        mg, mo = sum(g) / len(g), sum(o) / len(o)
        vg = sum((x - mg) ** 2 for x in g) / (len(g) - 1)
        vo = sum((x - mo) ** 2 for x in o) / (len(o) - 1)
        se = (vg / len(g) + vo / len(o)) ** 0.5
        if se <= 0:
            return 0.0
        return ((mo - mg) if kind == "avoid" else (mg - mo)) / se
    except Exception:
        return 0.0


def _judge(group, split_ts, rest=()):
    """confirmed_bad / confirmed_good only if the group is clearly different from the REST of the trades on the older
    70% AND still on the newest 30%. (A group that merely has a negative average is NOT enough: if the whole
    strategy is negative, every group would look 'bad'.)"""
    old = [r for r in group if r["_i"] < split_ts]
    new = [r for r in group if r["_i"] >= split_ts]
    if len(old) < MIN_OLD or len(new) < MIN_NEW:
        return "too_few"
    rest_old = [r for r in rest if r["_i"] < split_ts]
    rest_new = [r for r in rest if r["_i"] >= split_ts]
    for kind, label in (("avoid", "confirmed_bad"), ("take", "confirmed_good")):
        if _zs(old, rest_old, kind) >= Z_TRAIN and _zs(new, rest_new, kind) >= Z_TEST:
            return label
    return "mixed"


def _table(rows, keyfn, order, split):
    groups = {}
    for r in rows:
        k = keyfn(r)
        if k is not None:
            groups.setdefault(k, []).append(r)
    out = []
    for k in (order or sorted(groups)):
        g = groups.get(k)
        if not g:
            continue
        s = _stat(g)
        s["label"] = str(k)
        gid = {id(x) for x in g}
        s["status"] = _judge(g, split, [x for x in rows if id(x) not in gid])
        out.append(s)
    return out


def _hold_min(r):
    a, b = _f(r.get("opened_at_ts")), _f(r.get("closed_at_ts"))
    return (b - a) / 60.0 if a and b and b >= a else None


def _band(v, bands):
    for lo, hi, name in bands:
        if lo <= v < hi:
            return name
    return None


def _tod(r):
    a = _f(r.get("opened_at_ts"))
    if not a:
        return None
    d = datetime.fromtimestamp(a, IST)
    return _band(d.hour * 60 + d.minute, TOD_BANDS)


def _leakage(rows):
    known = [r for r in rows if _f(r.get("peak_roi_pct")) is not None]
    out = {"known": len(known), "total": len(rows)}
    if not known:
        return out
    gave = [(_f(r["peak_roi_pct"]) - r["roi_pct"]) for r in known if _f(r["peak_roi_pct"]) > 0]
    tp1_lost = [r for r in rows if r.get("tp_hit_levels") and r["pnl_usdt"] < 0]
    green_lost = [r for r in known if r["pnl_usdt"] < 0 and _f(r["peak_roi_pct"]) >= 10.0]
    losers = [r for r in known if r["pnl_usdt"] < 0]
    out.update({
        "avg_peak_roi": round(sum(_f(r["peak_roi_pct"]) for r in known) / len(known), 1),
        "avg_final_roi": round(sum(r["roi_pct"] for r in known) / len(known), 1),
        "avg_given_back": round(sum(gave) / len(gave), 1) if gave else 0.0,
        "tp1_then_loss_n": len(tp1_lost), "tp1_then_loss_rs": round(sum(r["pnl_usdt"] for r in tp1_lost), 2),
        "green_then_lost_n": len(green_lost), "losers_known": len(losers),
        "green_then_lost_rs": round(sum(r["pnl_usdt"] for r in green_lost), 2),
    })
    return out


def studies_lines():
    """Crypto only. One-line headlines of the other AI studies (TSI x SD zone reading, exit rules TP1..TP4, SD-level
    behaviour). PEEKS at their already-built caches only - never computes them, so the Doctor stays fast."""
    out = []
    try:
        try:
            from . import ai_reading, ai_exit_study, ai_level_study
        except ImportError:
            import ai_reading, ai_exit_study, ai_level_study
        for label, mod, getter in (
                ("Indicators (Z / TSI / SD zone)", ai_reading, lambda m: [v[2] for v in list(m._out_cache.values())]),
                ("Exit rule (TP1 vs TP4 vs book)", ai_exit_study, lambda m: [v[1] for v in list(m._out_cache.values())]),
                ("SD level behaviour", ai_level_study, lambda m: [m._cache.get("v")])):
            try:
                best = [o for o in getter(mod) if isinstance(o, dict) and o.get("headline")]
                if best:
                    best.sort(key=lambda o: o.get("signals", o.get("n", 0)) or 0, reverse=True)
                    out.append(f"{label}: {best[0]['headline']}")
                else:
                    out.append(f"{label}: open its AI screen once so it builds, then it shows here.")
            except Exception:
                continue
    except Exception:
        pass
    return out


def build(rows, unit="Rs", studies=False):
    """Never raises. Returns {'enough': bool, 'lines': [...], tables...}."""
    try:
        out = _build(rows, unit)
        if studies:
            out["studies"] = studies_lines()
        return out
    except Exception as e:
        return {"ok": False, "enough": False, "lines": ["Verdict could not be built yet."],
                "error": f"{type(e).__name__}: {e}"}


def _build(rows, unit):
    rows = sorted([dict(r) for r in rows or [] if _f(r.get("roi_pct")) is not None],
                  key=lambda r: _f(r.get("opened_at_ts")) or 0.0)
    for i, r in enumerate(rows):
        r["_i"] = i
    n = len(rows)
    split = int(n * TRAIN_FRAC)
    enough = n >= MIN_SAMPLE
    out = {"ok": True, "n": n, "enough": enough, "min_sample": MIN_SAMPLE, "unit": unit,
           "split": {"train": split, "check": n - split}}
    if n == 0:
        out["lines"] = ["No closed trades yet. Verdict starts after trades close."]
        return out
    rs = rows
    out["leakage"] = _leakage(rs)
    out["hold"] = _table(rs, lambda r: (_band(_hold_min(r), HOLD_BANDS) if _hold_min(r) is not None else None),
                         [b[2] for b in HOLD_BANDS], split)
    out["time_of_day"] = _table(rs, _tod, [b[2] for b in TOD_BANDS], split)
    out["index"] = _table(rs, lambda r: r.get("underlying") or r.get("symbol"), None, split)
    out["side"] = _table(rs, lambda r: ({"BUY": "CE (call)", "SELL": "PE (put)"}.get(r.get("action"))), None, split)
    out["timeframe"] = _table(rs, lambda r: (f"{r['timeframe']}m" if r.get("timeframe") else None), None, split)
    out["entry_zone"] = _table(rs, lambda r: r.get("entry_zone"), None, split)
    # TSI / Z (only trades recorded after the TSI-tag update have them; older trades are left out)
    out["tsi_band"] = _table(rs, lambda r: r.get("tsi_band"), None, split)
    out["z_band"] = _table(rs, lambda r: r.get("z_band"), None, split)
    out["tsi_vs_trade"] = _table(rs, lambda r: ("TSI " + r["tsi_with_trade"] + " the trade") if r.get("tsi_with_trade") else None, None, split)
    out["tsi_x_zone"] = _table(rs, lambda r: (f"{r['entry_zone']} + TSI {r['tsi_with_trade']}"
                                              if r.get("entry_zone") and r.get("tsi_with_trade") else None), None, split)
    out["tsi_recorded"] = sum(1 for r in rs if r.get("tsi_with_trade"))

    lines = []
    total = _stat(rs)
    lines.append(f"{n} trades: win rate {total['win_rate']:.0f}%, net {total['net']:+.0f} {unit} after charges.")
    if not enough:
        lines.append(f"Not enough data yet ({n}/{MIN_SAMPLE}). Tables are a first look only - do not change anything from them.")
        out["lines"] = lines
        return out

    lk = out["leakage"]
    if lk.get("known", 0) >= 10:
        if lk["tp1_then_loss_n"]:
            lines.append(f"{lk['tp1_then_loss_n']} trades hit TP1 and still ended as a loss ({lk['tp1_then_loss_rs']:+.0f} {unit}). "
                         "Check your stop-loss move / profit booking after TP1.")
        if lk["avg_given_back"] > 0:
            lines.append(f"On trades that went green, you gave back about {lk['avg_given_back']:.0f} ROI points from the peak "
                         f"(avg peak {lk['avg_peak_roi']:+.0f}%, avg final {lk['avg_final_roi']:+.0f}%).")
    else:
        lines.append("Peak-profit data exists only on newer trades, so leakage is not judged yet.")

    def pick(tab, key, word):
        hits = [t for t in out.get(tab, []) if t["status"] == key]
        return min(hits, key=lambda t: t["avg_roi"]) if key == "confirmed_bad" and hits else (
            max(hits, key=lambda t: t["avg_roi"]) if hits else None)

    for tab, name in (("time_of_day", "time slot"), ("entry_zone", "SD zone"), ("index", "index"),
                      ("side", "side"), ("hold", "holding time"),
                      ("tsi_vs_trade", "TSI check"), ("tsi_x_zone", "TSI x SD zone"), ("z_band", "Z band")):
        bad, good = pick(tab, "confirmed_bad", ""), pick(tab, "confirmed_good", "")
        if bad:
            lines.append(f"Weak {name}: {bad['label']} clearly worse than your other trades, on older AND newer trades ({bad['n']} trades, {bad['net']:+.0f} {unit}). "
                         "Lead to avoid - watch it, bot unchanged.")
        if good:
            lines.append(f"Strong {name}: {good['label']} clearly better than your other trades, on older AND newer trades ({good['n']} trades, {good['net']:+.0f} {unit}).")
    if len(lines) <= 2:
        lines.append("No group is clearly bad (or good) compared with the rest on both older and newer trades yet - nothing reliable to change.")
    if out.get("tsi_recorded", 0) < MIN_SAMPLE:
        lines.append(f"TSI/Z is recorded on {out.get('tsi_recorded', 0)} trades so far (new trades only) - TSI tables need {MIN_SAMPLE}+.")
    lines.append("Not tracked yet: exact TP1-vs-TP4 results (needs price path per trade).")
    out["lines"] = lines[:9]
    return out
