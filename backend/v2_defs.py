"""v2_defs.py - Part 15: COLLECTORS 2 of 5 - the VERSIONED DEFINITIONS (what each word means, in code, so every later Part counts the same way).
Pure maths on candles / tickers. No network, no signing, no order code, no writing (guard tests). Candle row = (open_ts, o, h, l, c, v), times in UTC seconds.
Honesty rule: when there is not enough clean data the answer is {"status": "UNAVAILABLE", "reason": ...} and value None - a number is NEVER invented, a gap is never filled.
A change of any meaning = a NEW DEFS_VERSION (old stored results keep the old meaning). Meanings:
 day_open_rank   change % = (price - day_open) / day_open; GAINER = highest first, LOSER = lowest first; ties by symbol A-Z; bad rows skipped and counted.
 time_to_peak    minutes from entry to the START of the candle holding the best price (LONG = highest high, SHORT = lowest low); first such candle wins.
 max_drawdown    biggest fall from the best price so far, in %; inside one candle the best price is taken BEFORE the worst (the harsher reading).
 volume_decay    mean volume of up to 3 candles AFTER the highest-volume candle divided by that peak volume (1.0 = no decay, 0.2 = faded to a fifth).
 same_hour_baseline  median of the SAME UTC hour volume on the previous 7 days; only COMPLETE hours count; fewer than 3 days = UNAVAILABLE.
Run (optional): python3 backend/v2_defs.py  -> prints the version and the meanings above (no data needed).  Tests: python3 test/test_v2_defs.py"""
import math
import statistics
import sys

VERSION = "v2_defs 1 (Part 15)"
DEFS_VERSION = 1
STEP = {"3m": 180, "5m": 300}
MIN_CANDLES = 3
BASELINE_DAYS, MIN_BASELINE_DAYS = 7, 3
SIDES = ("LONG", "SHORT")


def _na(reason):
    return {"status": "UNAVAILABLE", "value": None, "reason": reason}


def _ok(value, **extra):
    out = {"status": "OK", "value": value}
    out.update(extra)
    return out


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def clean_candles(rows, interval):
    """Rows -> (sorted unique valid candles, number dropped). Dropped = not 6 numbers, price <= 0, volume < 0, high/low not around open/close, duplicate open_ts (first stays)."""
    seen, good, bad = set(), [], 0
    for r in rows or []:
        try:
            ts, o, h, l, c, v = r
        except (TypeError, ValueError):
            bad += 1
            continue
        if not all(_num(x) for x in (ts, o, h, l, c, v)) or min(o, h, l, c) <= 0 or v < 0 or h < max(o, c) or l > min(o, c) or ts in seen:
            bad += 1
            continue
        seen.add(ts)
        good.append((int(ts), float(o), float(h), float(l), float(c), float(v)))
    good.sort()
    return good, bad


def has_gap(candles, interval):
    step = STEP[interval]
    return any(b[0] - a[0] != step for a, b in zip(candles, candles[1:]))


def _prepare(rows, interval, need=MIN_CANDLES):
    if interval not in STEP:
        return None, _na("interval must be 3m or 5m")
    cs, bad = clean_candles(rows, interval)
    if bad:
        return None, _na("%d bad candle row(s): refusing to guess" % bad)
    if len(cs) < need:
        return None, _na("only %d candle(s), need %d" % (len(cs), need))
    if has_gap(cs, interval):
        return None, _na("gap in the candles: refusing to bridge it")
    return cs, None


def day_open_change_pct(day_open, price):
    if not (_num(day_open) and _num(price)) or day_open <= 0 or price <= 0:
        return _na("day open and price must be numbers above zero")
    return _ok(round((price - day_open) / day_open * 100.0, 4))


def day_open_rank(items, kind, top=5):
    """items = [(symbol, day_open, price)]. Returns the top list with rank 1..top. Fewer than `top` valid symbols = PARTIAL (never padded)."""
    if kind not in ("GAINER", "LOSER"):
        raise ValueError("kind must be GAINER or LOSER")
    rows, skipped, seen = [], 0, set()
    for it in items or []:
        try:
            sym, op, px = it
        except (TypeError, ValueError):
            skipped += 1
            continue
        ch = day_open_change_pct(op, px)
        if ch["status"] != "OK" or not isinstance(sym, str) or not sym or sym in seen:
            skipped += 1
            continue
        seen.add(sym)
        rows.append((sym, ch["value"]))
    rows.sort(key=lambda r: (-r[1] if kind == "GAINER" else r[1], r[0]))
    ranks = [{"rank": i + 1, "symbol": s, "change_pct": c} for i, (s, c) in enumerate(rows[:top])]
    if not ranks:
        return dict(_na("no valid symbol"), ranks=[], skipped=skipped)
    return {"status": "OK" if len(ranks) >= top else "PARTIAL", "ranks": ranks, "skipped": skipped, "reason": "" if len(ranks) >= top else "only %d valid symbol(s)" % len(ranks)}


def time_to_peak(rows, interval, entry_ts, side="LONG", window=24):
    """Candles from the entry candle on (first `window`). Entry price = open of the entry candle (entry_ts must fall inside it)."""
    if side not in SIDES:
        raise ValueError("side must be LONG or SHORT")
    cs, err = _prepare([r for r in (rows or [])], interval, need=1)
    if err:
        return err
    step = STEP[interval]
    cs = [c for c in cs if c[0] + step > entry_ts][:window]
    if len(cs) < MIN_CANDLES:
        return _na("only %d candle(s) from the entry on, need %d" % (len(cs), MIN_CANDLES))
    if cs[0][0] > entry_ts:
        return _na("the entry candle is missing")
    entry = cs[0][1]
    pick = max if side == "LONG" else min
    idx = 0
    best = cs[0][2] if side == "LONG" else cs[0][3]
    for i, c in enumerate(cs):
        px = c[2] if side == "LONG" else c[3]
        if pick(px, best) != best:
            best, idx = px, i
    gain = (best - entry) / entry * 100.0 if side == "LONG" else (entry - best) / entry * 100.0
    return _ok(round((cs[idx][0] - entry_ts) / 60.0, 2), peak_pct=round(gain, 4), peak_candle_index=idx, no_gain=gain <= 0, candles_used=len(cs))


def max_drawdown(rows, interval, side="LONG"):
    if side not in SIDES:
        raise ValueError("side must be LONG or SHORT")
    cs, err = _prepare(rows, interval)
    if err:
        return err
    best, worst_dd = None, 0.0
    for _, o, h, l, c, v in cs:
        hi, lo = (h, l) if side == "LONG" else (l, h)          # best price first, worst price after it (harsher)
        best = hi if best is None else (max(best, hi) if side == "LONG" else min(best, hi))
        dd = (best - lo) / best * 100.0 if side == "LONG" else (lo - best) / best * 100.0
        worst_dd = max(worst_dd, dd)
    return _ok(round(worst_dd, 4), candles_used=len(cs))


def volume_decay(rows, interval):
    cs, err = _prepare(rows, interval)
    if err:
        return err
    vols = [c[5] for c in cs]
    pk = vols.index(max(vols))
    after = vols[pk + 1:pk + 4]
    if not after:
        return _na("the highest-volume candle is the last one: nothing after it to measure")
    if vols[pk] <= 0:
        return _na("no volume at all")
    return _ok(round((sum(after) / len(after)) / vols[pk], 4), peak_index=pk, after_used=len(after))


def hourly_volumes(rows, interval):
    """{hour_start_ts: volume} for COMPLETE UTC hours only (every candle of that hour is present and valid)."""
    cs, _ = clean_candles(rows, interval)
    step = STEP[interval]
    per = 3600 // step
    by = {}
    for c in cs:
        by.setdefault(c[0] - c[0] % 3600, []).append(c)
    return {h: sum(c[5] for c in v) for h, v in by.items() if len(v) == per and [c[0] for c in v] == [h + i * step for i in range(per)]}


def same_hour_baseline(hour_vols, now_ts):
    """Median volume of the same UTC hour on the 7 days BEFORE now's day. hour_vols = {hour_start_ts: volume} (see hourly_volumes)."""
    hour = now_ts - now_ts % 3600
    got = []
    for d in range(1, BASELINE_DAYS + 1):
        v = (hour_vols or {}).get(hour - d * 86400)
        if _num(v) and v >= 0:
            got.append(v)
    if len(got) < MIN_BASELINE_DAYS:
        return _na("only %d of the last %d days have this hour complete, need %d" % (len(got), BASELINE_DAYS, MIN_BASELINE_DAYS))
    return _ok(statistics.median(got), days_used=len(got))


def candles_from_store(con, symbol, interval, from_ts, to_ts):
    """READ-ONLY helper for the later Parts: closed candles of one symbol in [from_ts, to_ts]. One SELECT, nothing is written."""
    return con.execute("SELECT open_ts, o, h, l, c, v FROM candles WHERE symbol=? AND interval=? AND open_ts>=? AND open_ts<=? ORDER BY open_ts", (symbol, interval, int(from_ts), int(to_ts))).fetchall()


def main():
    print(VERSION, "| definitions version", DEFS_VERSION)
    for line in (__doc__ or "").splitlines():
        if line.startswith(" ") and "  " in line.strip():
            print(line.rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
