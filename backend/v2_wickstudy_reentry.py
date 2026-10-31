"""v2_wickstudy_reentry.py - Part 60: STOP-WICK STUDY 3 of 4 (backend, read-only, replay only, HYPOTHETICAL). "After a stop-wick, how fast did a re-entry confirm, and what did the price do from there?"
Replay of saved closed candles in a separate namespace: no order, no position, no trading module, nothing is written. The stop-wicks are the ones of Part 58 (v2_wickstudy.marks, imported, not copied).
The hypothetical RE-ENTRY (starting values, NV = not validated, change them in the constants):
  after a STOP_WICK_DOWN (swept lows) the re-entry is LONG: the first later candle whose CLOSE is above the HIGH of the wick candle (confirmation),
  after a STOP_WICK_UP (swept highs) the re-entry is SHORT: the first later candle whose CLOSE is below the LOW of the wick candle.
  The confirmation must come within ENTRY_SECS (1 h = 12 candles of 5m, 20 of 3m) after the wick candle. The entry price is the CLOSE of the confirmation candle (the first price anybody could have used).
  If a candle BEFORE the confirmation goes beyond the wick tip again (low under the tip of a down wick / high over the tip of an up wick) the setup is TIP_RETAKEN_FIRST and no entry happens
  (checked first, so a candle that does both counts as retaken).
Per wick the status is one of: ENTRY (confirmed, with delay in minutes), TIP_RETAKEN_FIRST, NO_REENTRY (the whole window is over and nothing confirmed), PENDING (the window is not over yet and nothing
confirmed so far), UNAVAILABLE (a candle is missing before a confirmation was seen). Never counted as 0, never bridged, never guessed.
From the entry close the same measure() as Part 44 (imported) follows 15 min, 30 min and 1 h: median end change, median highest / lowest move (raw %, + = up; a LONG reads max_up first, a SHORT max_down first),
with n, PENDING / UNAVAILABLE, a BASELINE of ordinary candles (every 12th), and stop_at_tip_hit = in how many finished windows the price went beyond the wick tip (a stop placed exactly at the tip would have been touched;
a plain count out of n). risk_pct = distance from the entry close to the wick tip in % of the entry (median with n). delay_min = minutes from the wick candle close to the confirmation candle close (median with n).
Honesty rules (README4 section 9.5): STOP_WICK_UP and STOP_WICK_DOWN are counted apart; fewer than MIN_N entries = \"too few to say anything\"; fees, slippage and
a real stop order are NOT simulated, so none of this is a result of trading: no win rate, no profit number, no prediction. Read-only: mode=ro, no network.
Run (Termux):  python3 backend/v2_wickstudy_reentry.py [--data DIR] [--days N]     Route: GET /api/v2/wickstudy_reentry[?days=N] (api/v2_data.py), N = 1 to 7 (default 1)."""
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
import v2_wickstudy as WK

VERSION = "v2_wickstudy_reentry 1 (Part 60)"
DEF_VERSION = 1
ENTRY_SECS = 3600                # the confirmation must come within 1 h after the wick candle (NV)
HORIZONS = SW.HORIZONS[:3]       # 15 m, 30 m, 1 h after the entry close
MIN_N = 30                       # below this a median carries "too few to say anything"
BASE_EVERY = SW.BASE_EVERY
MAX_EVENTS = 200
SIDE = {"STOP_WICK_DOWN": "LONG", "STOP_WICK_UP": "SHORT"}
STATUSES = ("ENTRY", "TIP_RETAKEN_FIRST", "NO_REENTRY", "PENDING", "UNAVAILABLE")


def reentry(run, i, kind, tip, step, now):
    """The re-entry of the wick candle run[i]. -> (status, j) where j is the index of the confirmation candle (only for ENTRY)."""
    k = ENTRY_SECS // step
    hi, lo = run[i][2], run[i][3]
    for j in range(i + 1, min(i + k, len(run) - 1) + 1):
        c = run[j]
        if (kind == "STOP_WICK_DOWN" and c[3] < tip) or (kind == "STOP_WICK_UP" and c[2] > tip):
            return "TIP_RETAKEN_FIRST", None
        if (kind == "STOP_WICK_DOWN" and c[4] > hi) or (kind == "STOP_WICK_UP" and c[4] < lo):
            return "ENTRY", j
    if i + k < len(run):
        return "NO_REENTRY", None
    return ("PENDING", None) if run[i][0] + step + ENTRY_SECS > now else ("UNAVAILABLE", None)


def _tip_hit(kind, tip, w):
    return min(x[3] for x in w) < tip if kind == "STOP_WICK_DOWN" else max(x[2] for x in w) > tip


def build(con, now=None, days=None):
    """-> the report dict (read-only). days = 1 to 7 (default 1) = how far back the stop-wicks are taken. Raises ValueError on a bad days value."""
    now = int(time.time() if now is None else now)
    if days in (None, ""):
        days = 1
    if not str(days).isdigit() or not 1 <= int(days) <= 7:
        raise ValueError("days must be a whole number from 1 to 7")
    days = int(days)
    a, first = now - days * 86400 - 14400, now - days * 86400
    syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM candles WHERE open_ts>=? AND open_ts<=?", (a, now))]
    st = {t: {s: 0 for s in STATUSES} for t in WK.TYPES}
    cells = {t: {h: WK._cell() for h, _ in HORIZONS} for t in WK.TYPES}
    delays = {t: [] for t in WK.TYPES}
    risks = {t: [] for t in WK.TYPES}
    base = {h: WK._cell() for h, _ in HORIZONS}
    events, used = [], 0
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
            for i in range(WK.LOOK, len(run)):
                if run[i][0] < first:
                    continue
                m = WK.marks(run, i)
                if m is not None:
                    kind, tip = m[0], m[2]
                    status, j = reentry(run, i, kind, tip, step, now)
                    st[kind][status] += 1
                    ev = {"symbol": s, "interval": iv, "type": kind, "side": SIDE[kind], "wick_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(run[i][0])), "open_ts": run[i][0], "status": status}
                    if status == "ENTRY":
                        ep = run[j][4]
                        delays[kind].append((j - i) * step / 60.0)
                        risks[kind].append(abs(ep - tip) / ep * 100.0)
                        ev.update(entry_utc=time.strftime("%Y-%m-%d %H:%M", time.gmtime(run[j][0])), delay_min=round((j - i) * step / 60.0, 1), entry_price=ep, wick_tip=tip, risk_pct=round(abs(ep - tip) / ep * 100.0, 3))
                        for h, secs in HORIZONS:
                            r = SW.measure(run, j, step, secs, now)
                            SW._add(cells[kind][h], r)
                            if r[0] == "OK" and _tip_hit(kind, tip, run[j + 1:j + 1 + secs // step]):
                                cells[kind][h]["tip"] += 1
                    events.append(ev)
                if (i - WK.LOOK) % BASE_EVERY == 0:
                    for h, secs in HORIZONS:
                        SW._add(base[h], SW.measure(run, i, step, secs, now))
    events.sort(key=lambda e: e["open_ts"], reverse=True)
    types = []
    for t in WK.TYPES:
        n = st[t]["ENTRY"]
        hz = {}
        for h, _ in HORIZONS:
            c = WK._fin(cells[t][h])
            c["stop_at_tip_hit"], c["stop_at_tip_hit_share"] = c.pop("tip_retaken"), c.pop("tip_retaken_share")
            hz[h] = c
        types.append({"type": t, "side": SIDE[t], "wicks": sum(st[t].values()), "status_counts": st[t], "entries": n,
                      "note": "" if n >= MIN_N else "too few to say anything (%d of %d entries needed)" % (n, MIN_N),
                      "median_delay_min": round(SW._med(delays[t]), 1) if delays[t] else None, "median_risk_pct": round(SW._med(risks[t]), 3) if risks[t] else None, "horizons": hz})
    return {"tool": VERSION, "read_only": True, "hypothetical": True, "definition_version": DEF_VERSION, "days": days, "symbols_scanned": used, "ready": used > 0,
            "horizons": [h for h, _ in HORIZONS], "baseline": {h: {k: v for k, v in WK._fin(base[h]).items() if not k.startswith("tip")} for h, _ in HORIZONS}, "types": types,
            "events_shown": min(len(events), MAX_EVENTS), "events_total": len(events), "events": events[:MAX_EVENTS],
            "definition": {"entry_window_secs": ENTRY_SECS, "confirmation": "close beyond the wick candle high (down wick, LONG) / low (up wick, SHORT)", "entry_price": "close of the confirmation candle",
                           "note": "starting values, not validated; HYPOTHETICAL replay of saved candles, no fees, no slippage, no real stop order"},
            "notes": ["HYPOTHETICAL: nothing was traded. A replay of saved closed candles with a made-up re-entry rule; fees, slippage and a real stop order are not simulated.",
                      "Status per wick: ENTRY, TIP_RETAKEN_FIRST (the tip was taken again before any confirmation), NO_REENTRY (window over, no confirmation), PENDING (window not over), UNAVAILABLE (a candle is missing). None of them is 0 or guessed.",
                      "After the entry close the windows are measured like Part 44 (end change, highest / lowest move, n, PENDING / UNAVAILABLE) with a baseline of ordinary candles. A LONG reads max_up first, a SHORT max_down first.",
                      "stop_at_tip_hit = in how many finished windows the price went beyond the wick tip (a stop at the tip would have been touched). A plain count out of n, not a win rate.",
                      "STOP_WICK_DOWN (LONG) and STOP_WICK_UP (SHORT) are counted apart. No prediction, no win rate, no profit number, no order, nothing is written."]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl stop-wick re-entry timing, hypothetical replay (read-only)")
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
