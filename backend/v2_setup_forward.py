"""v2_setup_forward.py - Part 44: EMA-FREE SETUP FINDER 2 of 4 (backend, read-only). "After a formation of Part 43, what did the price do in the next 15 min / 30 min / 1 h / 4 h?"
For every formation mark (same 7 types and same rules as v2_setup_finder.py, imported, not copied) it reads the NEXT closed candles of the same gap-free run and measures from the
CLOSE of the formation candle (the first price anybody could have used):
  end_pct     change of the close of the last candle of the window vs that close (raw %, + = up)
  max_up_pct  highest high in the window vs that close        max_down_pct  lowest low in the window vs that close (shown as a positive number)
Per type and per horizon only the MEDIANS of those numbers and the counts are shown, together with a BASELINE: the same numbers for ordinary candles (every 12th candle of the
same runs, no formation needed). A formation only means something if it differs from that baseline AND the sample is big. Direction of a type: UP types read max_up first, DOWN types max_down first,
SQUEEZE has no direction (read both).
Honesty rules (README4 section 9.5): a window that is not over yet = PENDING; a window with a missing candle (gap) = UNAVAILABLE; neither is ever counted as 0 or filled in; every median
shows n; fewer than MIN_N cases = "too few to say anything"; no win rate, no prediction, no order, nothing is written. 3m / 5m never mixed (per symbol). Read-only: mode=ro, no network.
Horizons are in the HORIZONS table (Part 44: 15 min to 4 h, Part 45: 1 day and 7 days). A day / week window needs EVERY candle of it (one missing candle = UNAVAILABLE), so in the first weeks of data most week windows say PENDING or UNAVAILABLE, and that is correct (the 3m series is kept 14 days, the 5m series 30 days). Run (Termux):  python3 backend/v2_setup_forward.py [--data DIR] [--days N]     Route: GET /api/v2/setups_forward[?days=N] (api/v2_data.py)."""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_defs as D
import v2_setup_finder as SF

VERSION = "v2_setup_forward 2 (Part 45)"
DEF_VERSION = 1
HORIZONS = (("15m", 900), ("30m", 1800), ("1h", 3600), ("4h", 14400), ("1d", 86400), ("7d", 604800))      # Part 44 = minutes / hours, Part 45 = day / week
MIN_N = 30                       # below this a median carries "too few to say anything"
BASE_EVERY = 12                  # baseline: every 12th candle of the runs (cheap, no formation needed)
DIRECTION = {"BREAK_UP": "UP", "IMPULSE_UP": "UP", "VOLUME_SPIKE_UP": "UP", "BREAK_DOWN": "DOWN", "IMPULSE_DOWN": "DOWN", "VOLUME_SPIKE_DOWN": "DOWN", "SQUEEZE": "NONE"}


def measure(run, i, step, secs, now):
    """The window after run[i]. -> ("OK", end_pct, max_up_pct, max_down_pct) or ("PENDING",) / ("UNAVAILABLE",)."""
    k = secs // step
    entry = run[i][4]
    if i + k >= len(run):
        return ("PENDING",) if run[i][0] + step + secs > now else ("UNAVAILABLE",)
    w = run[i + 1:i + 1 + k]
    return ("OK", round((w[-1][4] / entry - 1) * 100, 3), round((max(x[2] for x in w) / entry - 1) * 100, 3), round((1 - min(x[3] for x in w) / entry) * 100, 3))


def _med(xs):
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return round(xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2.0, 3)


def _empty():
    return {"n": 0, "pending": 0, "unavailable": 0, "_e": [], "_u": [], "_d": []}


def _add(cell, r):
    if r[0] == "OK":
        cell["n"] += 1
        cell["_e"].append(r[1]), cell["_u"].append(r[2]), cell["_d"].append(r[3])
    else:
        cell[r[0].lower()] += 1


def _fin(cell):
    out = {"n": cell["n"], "pending": cell["pending"], "unavailable": cell["unavailable"], "median_end_pct": _med(cell["_e"]), "median_max_up_pct": _med(cell["_u"]), "median_max_down_pct": _med(cell["_d"])}
    out["note"] = "" if cell["n"] >= MIN_N else "too few to say anything (%d of %d needed)" % (cell["n"], MIN_N)
    return out


def build(con, now=None, days=None):
    """-> the report dict (read-only). days = 1 to 7 (default 1) = how far back the FORMATIONS are taken. Raises ValueError on a bad days value."""
    now = int(time.time() if now is None else now)
    if days in (None, ""):
        days = 1
    if not str(days).isdigit() or not 1 <= int(days) <= 7:
        raise ValueError("days must be a whole number from 1 to 7")
    days = int(days)
    a, first = now - days * 86400 - 14400, now - days * 86400          # a little earlier so every formation has its 20 candles; formations count from "first"
    syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM candles WHERE open_ts>=? AND open_ts<=?", (a, now))]
    cells = {t: {h: _empty() for h, _ in HORIZONS} for t in SF.TYPES}
    base = {h: _empty() for h, _ in HORIZONS}
    used = 0
    for s in sorted(syms):
        best = (None, [])
        for iv in ("5m", "3m"):
            good, _bad = D.clean_candles(D.candles_from_store(con, s, iv, a, now), iv)
            if len(good) > len(best[1]):
                best = (iv, good)
        iv, good = best
        if iv is None:
            continue
        used += 1
        step = D.STEP[iv]
        for run in SF.runs(good, iv):
            for i in range(SF.LOOK, len(run)):
                if run[i][0] < first:
                    continue
                for t in SF.formations(run, i):
                    for h, secs in HORIZONS:
                        _add(cells[t][h], measure(run, i, step, secs, now))
                if (i - SF.LOOK) % BASE_EVERY == 0:
                    for h, secs in HORIZONS:
                        _add(base[h], measure(run, i, step, secs, now))
    types = [{"type": t, "direction": DIRECTION[t], "horizons": {h: _fin(cells[t][h]) for h, _ in HORIZONS}} for t in SF.TYPES]
    return {"tool": VERSION, "read_only": True, "definition_version": DEF_VERSION, "days": days, "symbols_scanned": used, "ready": used > 0,
            "horizons": [h for h, _ in HORIZONS], "baseline": {h: _fin(base[h]) for h, _ in HORIZONS}, "types": types,
            "notes": ["Measured from the CLOSE of the formation candle; end_pct is the close of the last candle of the window, max_up / max_down are the extremes inside the window.",
                      "BASELINE = ordinary candles of the same runs (every %dth, no formation). A formation only means something if it differs from the baseline AND n is big." % BASE_EVERY,
                      "PENDING = the window is not over yet; UNAVAILABLE = a candle is missing (gap). Neither is counted as 0 and nothing is bridged or guessed.",
                      "Medians only, with n. No win rate, no prediction, no order. 1 day and 7 day windows (Part 45) are strict: one missing candle makes the whole window UNAVAILABLE."]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl EMA-free setup finder, forward tracking (read-only)")
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
