"""v2_wickstudy.py - Part 58 + 59: STOP-WICK STUDY 1-2 of 4 (backend, read-only, replay only). "Where did a candle sweep a recent swing level with a wick and close back inside?"
It reads the closed 3m / 5m candles the collectors saved and MARKS the stop-wick candles (symbol, candle time, swing level, how deep the wick went, wick share, volume). That is all.
It does NOT look at what the price did afterwards (continuation = Part 59, re-entry timing = Part 60, Flutter card = Part 61), it gives no win rate, no prediction, no order, and it is a
separate namespace: no trading module is imported and nothing is written. Same candle rules as the Setup Finder (v2_setup_finder.runs / _med are imported, not copied), no EMA, no indicator.
The 2 types (plain price and volume only). N = the 20 candles BEFORE the candle (the candle itself is never in its own swing):
  STOP_WICK_DOWN   the low goes below the lowest low of the 20 before (a sweep of the lows = where long stops sit) AND the close is back at or above that old low
  STOP_WICK_UP     the high goes above the highest high of the 20 before (a sweep of the highs = where short stops sit) AND the close is back at or below that old high
  both also need: the wick (the part of the range on the swept side, beyond the body) is at least 50% of the candle range AND at least 2x the body (body 0 counts as a tiny body).
A candle that sweeps AND closes beyond the old level is a BREAK of Part 43, not a stop-wick, and is not marked here.
Numbers per event: swing_level, extreme (the wick tip), pierce_pct (how far beyond the swing level, % of the level), wick_share (wick / range), volume_x (volume / median volume of the 20 before), close.
All numbers above are STARTING values (NV = not validated): change them in the constants.
Honesty rules (README4 section 9.5): a bad row or a GAP is never bridged: the series is cut at each gap and a mark needs its whole 20-candle history inside the SAME gap-free run (otherwise it is not marked;
the gap count is shown). 3m and 5m are never mixed (per symbol the series with more clean candles in the window is used). STOP_WICK_UP and STOP_WICK_DOWN are counted apart, never added. A type with 0 hits
says 0 hits; fewer than MIN_HITS_NOTE hits carries \"too few to say anything\" and its medians are still shown with n. Read-only: mode=ro, no network.
Part 59 (continuation, function build_forward, route GET /api/v2/wickstudy_forward[?days=N]): after each stop-wick, measured from the CLOSE of the wick candle over the next 15 min / 30 min / 1 h / 4 h (same rules and
same measure() as Part 44, imported): median end change, median highest / lowest move, n, PENDING (window not over) / UNAVAILABLE (a candle is missing), a BASELINE of ordinary candles (every 12th), and per cell how many
windows went BEYOND the wick tip again (tip_retaken, a plain count with n: STOP_WICK_DOWN = the low went under the tip, STOP_WICK_UP = the high went over it). reversal_side = the side AWAY from the sweep (DOWN wick -> UP): read it first,
both sides are shown. Fewer than 30 cases = "too few to say anything". No win rate, no prediction, no order.
Run (Termux):  python3 backend/v2_wickstudy.py [--data DIR] [--days N] [--forward]     Routes: GET /api/v2/wickstudy[?days=N] and /api/v2/wickstudy_forward[?days=N] (api/v2_data.py), N = 1 to 7 (default 1)."""
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
import v2_setup_forward as SW

VERSION = "v2_wickstudy 2 (Part 59)"
DEF_VERSION = 1
LOOK = 20                 # candles before the candle that make the swing level (NV)
WICK_SHARE = 0.5          # the wick is at least this part of the candle range (NV)
WICK_BODY_X = 2.0         # the wick is at least this many times the body (NV)
MIN_HITS_NOTE = 30        # below this a count carries "too few to say anything"
MAX_EVENTS = 300          # newest events returned (counts are always complete)
TYPES = ("STOP_WICK_DOWN", "STOP_WICK_UP")
HORIZONS = SW.HORIZONS[:4]          # Part 59: 15 m, 30 m, 1 h, 4 h (the day / week windows of Part 45 are not used here)
REVERSAL = {"STOP_WICK_DOWN": "UP", "STOP_WICK_UP": "DOWN"}   # the side away from the sweep
BASE_EVERY = SW.BASE_EVERY


def marks(run, i):
    """The stop-wick type of candle run[i] (needs LOOK candles before it inside the same run). -> None or (type, swing_level, extreme, wick, rng)."""
    if i < LOOK:
        return None
    ts, o, h, l, c, v = run[i]
    prev = run[i - LOOK:i]
    rng, body = h - l, abs(c - o)
    if rng <= 0:
        return None
    lo, hi = min(x[3] for x in prev), max(x[2] for x in prev)
    tiny = rng * 1e-6
    if l < lo and c >= lo:
        wick = min(o, c) - l
        if wick >= WICK_SHARE * rng and wick >= WICK_BODY_X * max(body, tiny):
            return "STOP_WICK_DOWN", lo, l, wick, rng
    if h > hi and c <= hi:
        wick = h - max(o, c)
        if wick >= WICK_SHARE * rng and wick >= WICK_BODY_X * max(body, tiny):
            return "STOP_WICK_UP", hi, h, wick, rng
    return None


def scan_symbol(con, sym, a, b):
    """-> (interval, events, gap_count, candles_used) or None when no clean candles. events = dicts without the symbol."""
    best = (None, [], 0)
    for iv in ("5m", "3m"):
        good, bad = D.clean_candles(D.candles_from_store(con, sym, iv, a, b), iv)
        if len(good) > len(best[1]):
            best = (iv, good, bad)
    iv, good, bad = best
    if iv is None:
        return None
    rs = SF.runs(good, iv)
    ev = []
    for run in rs:
        for i in range(len(run)):
            m = marks(run, i)
            if m is None:
                continue
            t, level, ext, wick, rng = m
            mv = SF._med([x[5] for x in run[i - LOOK:i]])
            ev.append({"interval": iv, "type": t, "candle_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(run[i][0])), "open_ts": run[i][0], "swing_level": level, "extreme": ext,
                       "pierce_pct": round(abs(ext - level) / level * 100, 3) if level > 0 else None, "wick_share": round(wick / rng, 3),
                       "volume_x": round(run[i][5] / mv, 2) if mv > 0 else None, "close": run[i][4]})
    return iv, ev, len(rs) - 1, len(good), bad


def _summary(evs):
    """Per type: hits, medians (with n) of pierce / wick share / volume. Descriptive only."""
    out = []
    for t in TYPES:
        e = [x for x in evs if x["type"] == t]
        pc = [x["pierce_pct"] for x in e if x["pierce_pct"] is not None]
        ws = [x["wick_share"] for x in e]
        vx = [x["volume_x"] for x in e if x["volume_x"] is not None]
        out.append({"type": t, "hits": len(e), "note": "" if len(e) >= MIN_HITS_NOTE else "too few to say anything (%d of %d needed)" % (len(e), MIN_HITS_NOTE),
                    "median_pierce_pct": round(SF._med(pc), 3) if pc else None, "median_wick_share": round(SF._med(ws), 3) if ws else None,
                    "median_volume_x": round(SF._med(vx), 2) if vx else None, "n_pierce": len(pc), "n_volume": len(vx)})
    return out


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
    events, gaps, used, skipped = [], 0, 0, 0
    for s in sorted(syms):
        r = scan_symbol(con, s, a, now)
        if r is None:
            skipped += 1
            continue
        iv, ev, g, n, bad = r
        gaps += max(g, 0)
        used += 1
        for x in ev:
            x["symbol"] = s
            events.append(x)
    events.sort(key=lambda e: e["open_ts"], reverse=True)
    return {"tool": VERSION, "read_only": True, "definition_version": DEF_VERSION, "days": days, "symbols_scanned": used, "symbols_without_clean_candles": skipped, "gaps_cut": gaps,
            "ready": used > 0, "types": _summary(events), "events_shown": min(len(events), MAX_EVENTS), "events_total": len(events), "events": events[:MAX_EVENTS],
            "definition": {"look_candles": LOOK, "wick_share": WICK_SHARE, "wick_body_x": WICK_BODY_X,
                           "note": "starting values, not validated; a stop-wick is only a marked moment, not a forecast"},
            "notes": ["Part 58 only MARKS stop-wick candles. What the price did afterwards is Part 59 (continuation) and Part 60 (re-entry timing); the app card is Part 61.",
                      "STOP_WICK_DOWN sweeps the lows of the 20 candles before and closes back above; STOP_WICK_UP sweeps the highs and closes back below. They are never added together.",
                      "A candle that also closes beyond the old level is a BREAK (Part 43), not a stop-wick. No EMA and no indicator: only open / high / low / close / volume of the saved closed candles.",
                      "A gap in the candles cuts the series; a mark needs its 20 candles before it inside the same run. Nothing is bridged or guessed.",
                      "No prediction, no win rate, no order, nothing is written. Replay of saved candles only."]}


def _cell():
    c = SW._empty()
    c["tip"] = 0
    return c


def _fin(cell):
    out = SW._fin(cell)
    out["tip_retaken"] = cell["tip"] if cell["n"] else None
    out["tip_retaken_share"] = round(cell["tip"] / cell["n"], 3) if cell["n"] else None
    return out


def build_forward(con, now=None, days=None):
    """Part 59 -> the report dict (read-only). days = 1 to 7 (default 1) = how far back the stop-wicks are taken. Raises ValueError on a bad days value."""
    now = int(time.time() if now is None else now)
    if days in (None, ""):
        days = 1
    if not str(days).isdigit() or not 1 <= int(days) <= 7:
        raise ValueError("days must be a whole number from 1 to 7")
    days = int(days)
    a, first = now - days * 86400 - 14400, now - days * 86400
    syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM candles WHERE open_ts>=? AND open_ts<=?", (a, now))]
    cells = {t: {h: _cell() for h, _ in HORIZONS} for t in TYPES}
    base = {h: _cell() for h, _ in HORIZONS}
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
            for i in range(LOOK, len(run)):
                if run[i][0] < first:
                    continue
                m = marks(run, i)
                if m is not None:
                    for h, secs in HORIZONS:
                        r = SW.measure(run, i, step, secs, now)
                        SW._add(cells[m[0]][h], r)
                        if r[0] == "OK":
                            w = run[i + 1:i + 1 + secs // step]
                            if (m[0] == "STOP_WICK_DOWN" and min(x[3] for x in w) < m[2]) or (m[0] == "STOP_WICK_UP" and max(x[2] for x in w) > m[2]):
                                cells[m[0]][h]["tip"] += 1
                if (i - LOOK) % BASE_EVERY == 0:
                    for h, secs in HORIZONS:
                        SW._add(base[h], SW.measure(run, i, step, secs, now))
    types = [{"type": t, "reversal_side": REVERSAL[t], "horizons": {h: _fin(cells[t][h]) for h, _ in HORIZONS}} for t in TYPES]
    return {"tool": VERSION, "read_only": True, "definition_version": DEF_VERSION, "days": days, "symbols_scanned": used, "ready": used > 0, "horizons": [h for h, _ in HORIZONS],
            "baseline": {h: {k: v for k, v in _fin(base[h]).items() if not k.startswith("tip")} for h, _ in HORIZONS}, "types": types,
            "notes": ["Measured from the CLOSE of the stop-wick candle; end_pct is the close of the last candle of the window, max_up / max_down are the extremes inside the window.",
                      "reversal_side is the side away from the sweep (STOP_WICK_DOWN -> UP, STOP_WICK_UP -> DOWN). Both sides are shown; the medians are descriptions of saved candles, not signals.",
                      "tip_retaken = in how many finished windows the price went beyond the wick tip again (a plain count out of n). The baseline has no wick tip, so it has no such count.",
                      "BASELINE = ordinary candles of the same runs (every %dth, no wick needed). A stop-wick only means something if it differs from the baseline AND n is big." % BASE_EVERY,
                      "PENDING = the window is not over yet; UNAVAILABLE = a candle is missing (gap). Neither is counted as 0 and nothing is bridged or guessed.",
                      "Medians only, with n. No win rate, no prediction, no order, nothing is written."]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl stop-wick marks (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--days", help="1 to 7 (default 1)")
    ap.add_argument("--forward", action="store_true", help="Part 59: what the price did after each stop-wick")
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
        print(json.dumps((build_forward if a.forward else build)(con, days=a.days), indent=2, default=str))
    except ValueError as e:
        print("STOP:", e)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
