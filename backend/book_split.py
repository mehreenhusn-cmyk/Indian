"""book_split.py - Part 18: ONE place that says whether a paper trade belongs to MAIN (the current bot) or SNIPER.
Why: Sniper trades are written into the SAME b1 paper book as Main trades (only the 'source' field tells them apart), so every screen / report had to remember the filter by itself, and it was forgotten 3 times.
Rule (same as v2_f1_counts.group_of): source starts with 'sniper' (sniper, sniper_learn) = SNIPER, everything else = MAIN.
This file is READ-ONLY: it only reads lists it is given, it never writes the book, never stops or opens a trade. Any error = the caller gets None (fail-open, old numbers stay).
split_status() builds the extra block data['split'] for the app: open P&L / positions / margin per group, and Today / 7D / 30D closed P&L per group.
Closed numbers come from the closed_trades list of the book (last 1500 trades). When that list does not reach back 30 days the 30D (or 7D) number is marked partial (d7_partial / d30_partial = true); the old all-in-one numbers are NOT changed.
Main and Sniper are never added together here."""
import time

VERSION = "book_split 1 (Part 18)"
GROUPS = ("main", "sniper")


def is_sniper(t):
    try:
        return str((t or {}).get("source") or "").lower().startswith("sniper")
    except Exception:
        return False


def group(t):
    return "sniper" if is_sniper(t) else "main"


def _f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def open_split(positions):
    """-> {'main': {'n', 'pnl', 'margin'}, 'sniper': {...}} from the open positions list (pnl_usdt as the app shows it, already net of fee in paper mode)."""
    out = {g: {"n": 0, "pnl": 0.0, "margin": 0.0} for g in GROUPS}
    for p in positions or []:
        o = out[group(p)]
        o["n"] += 1
        o["pnl"] += _f(p.get("pnl_usdt"))
        o["margin"] += _f(p.get("invest_usdt"))
    for o in out.values():
        o["pnl"], o["margin"] = round(o["pnl"], 4), round(o["margin"], 4)
    return out


def period_split(closed, day_start_ts, skip=None):
    """-> {'main': {...}, 'sniper': {...}, 'oldest_ts'} Today / 7D / 30D closed P&L per group. day_start_ts = start of the trading day (5:30 AM IST), same boundary as the app. skip(t) -> True leaves a trade out (e.g. BTC)."""
    s7, s30 = day_start_ts - 6 * 86400, day_start_ts - 29 * 86400
    out = {g: {"today_pnl": 0.0, "today_trades": 0, "d7_pnl": 0.0, "d7_trades": 0, "d30_pnl": 0.0, "d30_trades": 0} for g in GROUPS}
    oldest = None
    for t in closed or []:
        ts = _f(t.get("closed_at_ts"))
        if not ts:
            continue
        oldest = ts if oldest is None or ts < oldest else oldest
        if skip is not None and skip(t):
            continue
        o, pnl = out[group(t)], _f(t.get("pnl_usdt"))
        if ts >= s30:
            o["d30_pnl"] += pnl
            o["d30_trades"] += 1
            if ts >= s7:
                o["d7_pnl"] += pnl
                o["d7_trades"] += 1
                if ts >= day_start_ts:
                    o["today_pnl"] += pnl
                    o["today_trades"] += 1
    for o in out.values():
        for k in ("today_pnl", "d7_pnl", "d30_pnl"):
            o[k] = round(o[k], 4)
    out["oldest_ts"] = oldest
    out["_s7"], out["_s30"] = s7, s30
    return out


_cache = {"key": None, "val": None}


def split_status(positions, closed, day_start_ts, full_list_len=1500, skip=None):
    """The block the app shows: data['split']. Fail-open: any error -> None."""
    try:
        last = _f(closed[0].get("closed_at_ts")) if closed else 0.0
        key = (day_start_ts, len(closed or []), last, _f(closed[-1].get("closed_at_ts")) if closed else 0.0)    # the closed list only changes when a trade closes: do not loop 1500 rows every second
        if _cache["key"] == key and _cache["val"] is not None:
            per = {g: (dict(v) if isinstance(v, dict) else v) for g, v in _cache["val"].items()}
        else:
            per = period_split(closed, day_start_ts, skip)
            _cache.update(key=key, val={g: dict(v) if isinstance(v, dict) else v for g, v in per.items()})
        old = per.pop("oldest_ts")
        s7, s30 = per.pop("_s7"), per.pop("_s30")
        full = len(closed or []) >= full_list_len          # list is at its cap = it may have dropped older trades
        part7, part30 = bool(full and old is not None and old > s7), bool(full and old is not None and old > s30)
        op = open_split(positions)
        return {"tool": VERSION, "note": "Main and Sniper are separate. Never add them.",
                "main": dict(op["main"], **per["main"]), "sniper": dict(op["sniper"], **per["sniper"]),
                "d7_partial": part7, "d30_partial": part30, "generated": int(time.time())}
    except Exception:
        return None
