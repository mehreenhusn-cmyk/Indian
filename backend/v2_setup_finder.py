"""v2_setup_finder.py - Part 43: EMA-FREE SETUP FINDER 1 of 4 (backend, read-only). "Which price formations happened in the saved candles, WITHOUT any EMA cross?"
It reads the closed 3m / 5m candles the collectors saved and marks WHEN each formation type happened (symbol, candle time, close price). That is all.
It does NOT look at what the price did afterwards (that is Part 44 minutes / hours and Part 45 day / week), it gives no win rate, no prediction, no order.
The 7 formation types (plain price and volume only, no EMA, no indicator). N = the 20 candles BEFORE the candle (the candle itself is never in its own baseline):
  BREAK_UP / BREAK_DOWN        close above the highest high / below the lowest low of the 20 candles before
  IMPULSE_UP / IMPULSE_DOWN    body at least 3x the median body of the 20 before, and the close sits in the top / bottom quarter of the candle range
  VOLUME_SPIKE_UP / _DOWN      volume at least 3x the median volume of the 20 before, and the candle is green / red
  SQUEEZE                      the high-low range of the last 10 candles is at most half of the range of the 10 candles before them (no direction)
All numbers above are STARTING values (NV = not validated): change them in the constants. One candle can carry several types (they are separate rows).
Honesty rules (README4 section 9.5): candles with a bad row or a GAP are never bridged: the series is cut at each gap and a formation needs its whole 20-candle
history inside the SAME gap-free run (otherwise it is simply not marked; the gap count is shown). 3m and 5m are never mixed (per symbol the series with more
candles in the window is used). A type with 0 hits says 0 hits; fewer than MIN_HITS_NOTE hits carries the note "too few to say anything". Read-only: mode=ro, no network.
Run (Termux):  python3 backend/v2_setup_finder.py [--data DIR] [--days N]     Route: GET /api/v2/setups[?days=N] (api/v2_data.py), N = 1 to 7 (default 1)."""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_defs as D

VERSION = "v2_setup_finder 1 (Part 43)"
DEF_VERSION = 1
LOOK = 20                 # candles before the candle that are the baseline (NV)
BODY_X = 3.0              # impulse: body >= 3x median body (NV)
VOL_X = 3.0               # volume spike: volume >= 3x median volume (NV)
CLOSE_ZONE = 0.25         # impulse: close in the top / bottom quarter of the range (NV)
SQ_N = 10                 # squeeze: last 10 candles vs the 10 before (NV)
SQ_RATIO = 0.5            # squeeze: range at most half (NV)
MIN_HITS_NOTE = 30        # below this a count carries "too few to say anything"
MAX_EVENTS = 300          # newest events returned (counts are always complete)
TYPES = ("BREAK_UP", "BREAK_DOWN", "IMPULSE_UP", "IMPULSE_DOWN", "VOLUME_SPIKE_UP", "VOLUME_SPIKE_DOWN", "SQUEEZE")


def _med(xs):
    xs = sorted(xs)
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2.0


def runs(candles, interval):
    """Cut the clean candles at every gap -> list of gap-free runs. The gaps are counted, never bridged."""
    step = D.STEP[interval]
    out, cur = [], []
    for c in candles:
        if cur and c[0] - cur[-1][0] != step:
            out.append(cur)
            cur = []
        cur.append(c)
    if cur:
        out.append(cur)
    return out


def formations(run, i):
    """The formation types of candle run[i] (needs LOOK candles before it inside the same run). -> list of type names."""
    if i < LOOK:
        return []
    ts, o, h, l, c, v = run[i]
    prev = run[i - LOOK:i]
    found = []
    if c > max(x[2] for x in prev):
        found.append("BREAK_UP")
    if c < min(x[3] for x in prev):
        found.append("BREAK_DOWN")
    body, rng = abs(c - o), h - l
    mb = _med([abs(x[4] - x[1]) for x in prev])
    if mb > 0 and rng > 0 and body >= BODY_X * mb:
        pos = (c - l) / rng
        if c > o and pos >= 1 - CLOSE_ZONE:
            found.append("IMPULSE_UP")
        if c < o and pos <= CLOSE_ZONE:
            found.append("IMPULSE_DOWN")
    mv = _med([x[5] for x in prev])
    if mv > 0 and v >= VOL_X * mv and c != o:
        found.append("VOLUME_SPIKE_UP" if c > o else "VOLUME_SPIKE_DOWN")
    if i >= 2 * SQ_N:
        last, before = run[i - SQ_N + 1:i + 1], run[i - 2 * SQ_N + 1:i - SQ_N + 1]
        r1 = max(x[2] for x in last) - min(x[3] for x in last)
        r0 = max(x[2] for x in before) - min(x[3] for x in before)
        if r0 > 0 and r1 <= SQ_RATIO * r0:
            found.append("SQUEEZE")
    return found


def scan_symbol(con, sym, a, b):
    """-> (interval, events, gap_count, candles_used) or None when no clean candles. events = [(ts, type, close)]."""
    best = (None, [], 0)
    for iv in ("5m", "3m"):
        good, bad = D.clean_candles(D.candles_from_store(con, sym, iv, a, b), iv)
        if len(good) > len(best[1]):
            best = (iv, good, bad)
    iv, good, bad = best
    if iv is None:
        return None
    rs = runs(good, iv)
    ev = []
    for run in rs:
        for i in range(len(run)):
            for t in formations(run, i):
                ev.append((run[i][0], t, run[i][4]))
    return iv, ev, len(rs) - 1, len(good), bad


def build(con, now=None, days=None):
    """-> the report dict (read-only). days = 1 to 7 (default 1). Raises ValueError on a bad days value."""
    now = int(time.time() if now is None else now)
    if days in (None, ""):
        days = 1
    if not str(days).isdigit() or not 1 <= int(days) <= 7:
        raise ValueError("days must be a whole number from 1 to 7")
    days = int(days)
    a = now - days * 86400
    syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM candles WHERE open_ts>=? AND open_ts<=?", (a, now))]
    counts = {t: 0 for t in TYPES}
    events, gaps, used, skipped = [], 0, 0, 0
    for s in sorted(syms):
        r = scan_symbol(con, s, a, now)
        if r is None:
            skipped += 1
            continue
        iv, ev, g, n, bad = r
        gaps += max(g, 0)
        used += 1
        for ts, t, c in ev:
            counts[t] += 1
            events.append({"symbol": s, "interval": iv, "type": t, "candle_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)), "open_ts": ts, "close": c})
    events.sort(key=lambda e: e["open_ts"], reverse=True)
    types = [{"type": t, "hits": counts[t], "note": "" if counts[t] >= MIN_HITS_NOTE else "too few to say anything (%d of %d needed)" % (counts[t], MIN_HITS_NOTE)} for t in TYPES]
    return {"tool": VERSION, "read_only": True, "definition_version": DEF_VERSION, "days": days, "symbols_scanned": used, "symbols_without_clean_candles": skipped,
            "gaps_cut": gaps, "ready": used > 0, "types": types, "events_shown": min(len(events), MAX_EVENTS), "events_total": len(events), "events": events[:MAX_EVENTS],
            "definition": {"look_candles": LOOK, "body_x": BODY_X, "volume_x": VOL_X, "close_zone": CLOSE_ZONE, "squeeze": "range of last %d <= %.1f x range of the %d before" % (SQ_N, SQ_RATIO, SQ_N),
                           "note": "starting values, not validated; a formation is only a marked moment, not a forecast"},
            "notes": ["Part 43 only MARKS formations. What the price did afterwards is Part 44 (minutes, hours) and Part 45 (day, week).",
                      "No EMA and no indicator is used: only open / high / low / close / volume of the saved closed candles.",
                      "A gap in the candles cuts the series; a formation needs its 20 candles before it inside the same run. Nothing is bridged or guessed.",
                      "No prediction, no win rate, no pattern claim: that needs many cases AND counterexamples."]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl EMA-free setup finder (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--days", help="1 to 7 (default 1)")
    a = ap.parse_args(argv)
    import v2_inventory as I
    import v2_store as S
    path = S.store_path(I.find_data_dir(a.data))
    if not os.path.isfile(path):
        print("The market store is not created yet: nothing to report.")
        return 0
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    con.execute("PRAGMA query_only=ON")
    try:
        print(json.dumps(build(con, days=a.days), indent=2, default=str))
    except ValueError as e:
        print("STOP:", e)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
