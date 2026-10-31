"""v2_prepump.py - Part 47: PRE-PUMP / PRE-DUMP WATCH 1 of 3 (backend, read-only). "When did the coins that pumped (GAINER) or dumped (LOSER) FIRST show up, and how much of their move was still ahead?"
For every coin of a saved 00:00 UTC cohort (cohort_official, top 5 GAINER + top 5 LOSER of the UTC day that just ended; AUTHENTIC / PROXY kept as stored) it reads the 5-minute
top-20 snapshots (ticker_snapshot) of that UTC day and gives, for the coin's own side (GAINER = rank_gain, LOSER = rank_loss):
  first_top20_utc / hours_into_day   the FIRST snapshot in which the coin stood in the top 20 of its side, and how many hours after 00:00 UTC that was
  rank_at_first / change_at_first    its rank and its change since the UTC day open at that moment (pump = +, dump = -)
  final_change_pct                   its last saved change in the day         share_still_ahead  how much of the day move was NOT yet done at that first moment: 1 - |first| / |final|
  volume_growth                      volume_usdt at the last snapshot / at the first one
Plain meaning: a high share_still_ahead and an early hour = the coin was noticed EARLY (Parts 48-49 use this to watch today's coins); a low share = it was noticed late.
Honesty rules (README4 section 9.5): the store keeps ONLY the top 20 lists, so the moment BEFORE a coin entered the list is not saved and nothing is guessed about it; if the coin is
already in the very first snapshot the store has for that day, the real first moment is unknown = CENSORED (never counted as "early"); a coin with no snapshot at all = UNAVAILABLE with
the reason; fewer than MIN_N observed cases = "too few to say anything"; AUTHENTIC and PROXY, GAINER and LOSER, and days are counted apart and never added together; episode rule of Part 32
applied (counts for all rows and for new episodes only). No prediction, no win rate, no order, nothing is written. Read-only: mode=ro, no network.
Run (Termux):  python3 backend/v2_prepump.py [--data DIR] [--day YYYY-MM-DD | --days N]     Route: GET /api/v2/prepump[?day= | ?days=] (api/v2_data.py)."""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_radar as RD
import v2_radar_episodes as EP

VERSION = "v2_prepump 1 (Part 47)"
DEF_VERSION = 1
DAY_SEC = 86400
MIN_N = 10               # below this a median carries "too few to say anything" (NV, starting value)
SIDE_RANK = {"GAINER": "rank_gain", "LOSER": "rank_loss"}


def _na(reason):
    return {"status": "UNAVAILABLE", "reason": reason}


def _med(xs):
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return round(xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2.0, 3)


def early_profile(con, sym, kind, snap_ts, store_first_ts):
    """The early-sign numbers of one cohort coin. store_first_ts = the first snapshot time the store has inside the same UTC day (None = none at all)."""
    a = snap_ts - DAY_SEC
    col = SIDE_RANK[kind]
    rows = con.execute("SELECT run_ts, change_pct, volume_usdt, %s FROM ticker_snapshot WHERE symbol=? AND run_ts>=? AND run_ts<=? ORDER BY run_ts" % col, (sym, a, snap_ts)).fetchall()
    if not rows:
        return _na("no snapshot of this coin in that UTC day (the collector was not running, or the coin was never in a saved list)")
    top = [r for r in rows if r[3] is not None]
    if not top:
        return _na("the coin has snapshots but never stood in the top 20 of its side")
    first, last = top[0], rows[-1]
    out = {"snapshots": len(rows), "first_top20_utc": RD._utc(first[0]), "hours_into_day": round((first[0] - a) / 3600.0, 2), "rank_at_first": first[3],
           "change_at_first_pct": first[1], "final_change_pct": last[1], "window_start_utc": RD._utc(store_first_ts) if store_first_ts else None}
    if store_first_ts is not None and first[0] <= store_first_ts:
        out.update(status="CENSORED", reason="the coin is already in the very first saved snapshot of that day, so the real first moment is unknown (collector started later)")
        return out
    out["status"] = "OK"
    f, z = first[1], last[1]
    if isinstance(f, (int, float)) and isinstance(z, (int, float)) and z != 0 and (f >= 0) == (z >= 0):
        out["share_still_ahead"] = round(max(0.0, 1 - abs(f) / abs(z)), 3)
    else:
        out["share_still_ahead"] = None
        out["share_note"] = "the day change is missing or has the other sign at one of the two moments"
    v0, v1 = first[2], last[2]
    out["volume_growth"] = round(v1 / v0, 3) if isinstance(v0, (int, float)) and isinstance(v1, (int, float)) and v0 > 0 else None
    return out


def _count(rows):
    """source -> kind -> counts + medians of the observed cases (descriptive only)."""
    res = {}
    for r in rows:
        p = r["early"]
        e = res.setdefault(r["source"], {}).setdefault(r["kind"], {"coins": 0, "observed": 0, "censored": 0, "unavailable": 0, "_h": [], "_c": [], "_s": [], "_v": []})
        e["coins"] += 1
        if p.get("status") == "OK":
            e["observed"] += 1
            e["_h"].append(p["hours_into_day"])
            if isinstance(p["change_at_first_pct"], (int, float)):
                e["_c"].append(abs(p["change_at_first_pct"]))
            if p.get("share_still_ahead") is not None:
                e["_s"].append(p["share_still_ahead"])
            if p.get("volume_growth") is not None:
                e["_v"].append(p["volume_growth"])
        elif p.get("status") == "CENSORED":
            e["censored"] += 1
        else:
            e["unavailable"] += 1
    for sides in res.values():
        for e in sides.values():
            e["median_hours_into_day"], e["median_abs_change_at_first_pct"] = _med(e.pop("_h")), _med(e.pop("_c"))
            e["median_share_still_ahead"], e["median_volume_growth"] = _med(e.pop("_s")), _med(e.pop("_v"))
            e["note"] = "" if e["observed"] >= MIN_N else "too few to say anything (%d of %d needed)" % (e["observed"], MIN_N)
    return res


def _day(con, day, emap):
    rows = con.execute("SELECT kind, rank, symbol, snap_ts, source FROM cohort_official WHERE day=? ORDER BY kind, rank", (day,)).fetchall()
    if not rows:
        return {"day": day, "status": "MISSING", "rows": [], "note": "no official cohort was saved for this day. It is never filled in from other data."}
    out = []
    for k, rk, s, ts, src in rows:
        if not ts:
            early = _na("the cohort row has no snapshot time")
        else:
            first = con.execute("SELECT MIN(run_ts) FROM ticker_snapshot WHERE run_ts>=? AND run_ts<=?", (ts - DAY_SEC, ts)).fetchone()[0]
            early = early_profile(con, s, k, int(ts), first)
        out.append({"kind": k, "rank": rk, "symbol": s, "source": src, "episode": emap.get((s, k, day)), "early": early})
    new = [r for r in out if not (r["episode"] or {}).get("repeat")]
    return {"day": day, "status": "OK", "coins": len(out), "episodes": {"rows": len(out), "new_episodes": len(new), "repeats": len(out) - len(new)},
            "summary": _count(out), "summary_new_episodes_only": _count(new), "rows": out}


def build(con, now=None, day=None, days=None):
    """-> the report dict (read-only). Same day / days choice as Radar 1-5 (default the newest 2 days). Raises ValueError on a bad day / days."""
    now = int(time.time() if now is None else now)
    exp, shown = RD.pick_days(now, day, days)
    emap = EP.mark(EP.episodes(con))
    res = [_day(con, d, emap) for d in shown]
    for r in res:
        r["tab"] = RD.tab_label(exp.index(r["day"])) if r["day"] in exp else None
    return {"tool": VERSION, "made_utc": RD._utc(now), "read_only": True, "definition_version": DEF_VERSION, "days": res,
            "notes": ["Pump = GAINER cohort coins, dump = LOSER cohort coins. They are never added together. AUTHENTIC and PROXY stay apart.",
                      "The store keeps only the top 20 lists (every 5 min): the moment BEFORE a coin entered the list is not saved and is never guessed.",
                      "CENSORED = the coin was already in the first saved snapshot of that day (collector started later), so its real first moment is unknown.",
                      "share_still_ahead = 1 - |change at first| / |final change|: how much of the day move came AFTER the coin was first seen. A description of past days, not a forecast.",
                      "Fewer than %d observed cases = too few to say anything. No prediction, no win rate, no order." % MIN_N]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl pre-pump / pre-dump early-sign profile (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--day")
    ap.add_argument("--days", help="1 to 7: the newest N saved cohorts (default 2)")
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
        print(json.dumps(build(con, day=a.day, days=a.days), indent=2, default=str))
    except ValueError as e:
        print("STOP:", e)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
