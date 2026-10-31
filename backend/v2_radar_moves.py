"""v2_radar_moves.py - Part 33: RADAR 5 of 6 (backend, read-only). "After the snapshot, how far did each cohort coin run, how fast, and was the volume unusual?"
For every coin of a saved 00:00 UTC cohort (cohort_official, AUTHENTIC / PROXY kept as the collector stored them) it reads the closed candles saved from the
snapshot time on (first 24 hours) and gives, in the direction of the cohort (GAINER = up, LOSER = down), measured from the SNAPSHOT price:
  max_favourable_pct  best move in the cohort direction (highest high for GAINER, lowest low for LOSER)    max_adverse_pct  worst move against it
  time_to_peak_min    minutes from the snapshot to the candle holding the best price (v2_defs.time_to_peak)
  max_drawdown_pct    biggest fall from the best price so far (v2_defs.max_drawdown, harsher reading inside one candle)
  volume_decay        v2_defs.volume_decay (1.0 = no decay)
  volume_state        volume of the first full UTC hour after the snapshot / the median of the SAME UTC hour on the 7 days before (v2_defs.same_hour_baseline):
                      HIGH (ratio 2.0 or more) | NORMAL | LOW (below 0.5)  - starting values NOT validated, change them in the constants below.
Honesty rules (README4 section 9.5): the candles must be clean (v2_defs refuses bad rows and gaps and says so: UNAVAILABLE + reason, never a guess); the 3m or 5m
series with more saved candles is used, never mixed; fewer than 7 days of old candles = the baseline says UNAVAILABLE (that is normal in the first week of data);
a window that is not over yet is marked window_complete false and the numbers are "so far"; AUTHENTIC and PROXY are counted apart; days and sides are never added
together; no prediction, no win rate, no pattern claim. Episode rule of Part 32 is applied (counts for all rows and for new episodes only).
Read-only: the store is opened with mode=ro and is never created here. No network, no trading module, no ledger row.
Run (Termux):  python3 backend/v2_radar_moves.py [--data DIR] [--day YYYY-MM-DD | --days N]     Route: GET /api/v2/radar_moves[?day= | ?days=] (api/v2_data.py)."""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_defs as D
import v2_radar as RD
import v2_radar_episodes as EP

VERSION = "v2_radar_moves 1 (Part 33)"
DEF_VERSION = 1
WINDOW_SEC = 86400                # first 24 hours after the snapshot
HIGH_RATIO = 2.0                  # starting value (NV): hour volume at least 2x the same-hour median = HIGH
LOW_RATIO = 0.5                   # starting value (NV): below half of it = LOW
SIDE_OF = {"GAINER": "LONG", "LOSER": "SHORT"}      # the cohort direction (a description, not a trade)


def _na(reason):
    return {"status": "UNAVAILABLE", "value": None, "reason": reason}


def _candles(con, sym, iv, a, b):
    return D.candles_from_store(con, sym, iv, a, b)


def pick_interval(con, sym, a, b):
    """The saved series (3m or 5m) with more candles in [a, b]; a tie goes to 5m. -> (interval, rows) or (None, [])."""
    best = (None, [])
    for iv in ("5m", "3m"):
        rows = _candles(con, sym, iv, a, b)
        if len(rows) > len(best[1]):
            best = (iv, rows)
    return best


def volume_state(con, sym, iv, snap_ts):
    """Volume of the first full UTC hour at or after the snapshot vs the same-hour median of the 7 days before. Only that hour of each day is read."""
    step = D.STEP[iv]
    hour = snap_ts + (-snap_ts) % 3600
    rows = []
    for d in range(0, D.BASELINE_DAYS + 1):
        rows += _candles(con, sym, iv, hour - d * 86400, hour - d * 86400 + 3600 - step)
    hv = D.hourly_volumes(rows, iv)
    if hour not in hv:
        return dict(_na("the first full hour after the snapshot is not complete in the saved candles"), hour_utc=RD._utc(hour))
    base = D.same_hour_baseline(hv, hour)
    if base["status"] != "OK":
        return dict(base, hour_utc=RD._utc(hour), hour_volume=round(hv[hour], 4))
    if base["value"] <= 0:
        return dict(_na("the same-hour baseline is zero: a ratio would be meaningless"), hour_utc=RD._utc(hour))
    ratio = round(hv[hour] / base["value"], 3)
    state = "HIGH" if ratio >= HIGH_RATIO else ("LOW" if ratio < LOW_RATIO else "NORMAL")
    return {"status": "OK", "state": state, "ratio": ratio, "hour_utc": RD._utc(hour), "hour_volume": round(hv[hour], 4),
            "baseline_median": round(base["value"], 4), "baseline_days": base["days_used"]}


def move_numbers(con, kind, sym, op, sts, now):
    """-> the numbers of one cohort coin. Every number is its own {status, value, reason}; a missing one never blocks the others."""
    if not sts or not op or float(op) <= 0:
        return {"status": "UNAVAILABLE", "reason": "no snapshot price or time saved for this coin"}
    end = min(int(now), int(sts) + WINDOW_SEC)
    iv, rows = pick_interval(con, sym, int(sts) - 300, end)
    if not iv:
        return {"status": "UNAVAILABLE", "reason": "no closed candle saved in the first 24 hours after the snapshot"}
    step, side = D.STEP[iv], SIDE_OF[kind]
    cs, err = D._prepare(rows, iv, need=1)
    if err:
        return {"status": "UNAVAILABLE", "interval": iv, "reason": err["reason"]}
    cs = [c for c in cs if c[0] + step > int(sts)]
    if not cs or cs[0][0] > int(sts):
        return {"status": "UNAVAILABLE", "interval": iv, "reason": "the candle holding the snapshot time is missing"}
    if len(cs) < D.MIN_CANDLES:
        return {"status": "UNAVAILABLE", "interval": iv, "reason": "only %d candle(s) from the snapshot on, need %d" % (len(cs), D.MIN_CANDLES)}
    hi, lo = max(c[2] for c in cs), min(c[3] for c in cs)
    up, down = RD._pct(hi, op), RD._pct(lo, op)
    fav, adv = (up, down) if side == "LONG" else (-down, -up)          # both read as "% in the cohort direction / against it"
    done = int(now) >= int(sts) + WINDOW_SEC
    ttp = D.time_to_peak(cs, iv, int(sts), side, window=len(cs))
    return {"status": "OK", "interval": iv, "side_used": side, "candles_used": len(cs), "window_complete": done,
            "window_note": "" if done else "the 24-hour window is not over yet: numbers are so far",
            "max_favourable_pct": round(max(fav, 0.0), 3), "max_adverse_pct": round(max(-adv, 0.0), 3),
            "time_to_peak_min": ttp["value"] if ttp["status"] == "OK" else None,
            "time_to_peak_note": "" if ttp["status"] == "OK" else ttp["reason"],
            "max_drawdown": D.max_drawdown(cs, iv, side), "volume_decay": D.volume_decay(cs, iv),
            "volume_state": volume_state(con, sym, iv, int(sts))}


def _med(xs):
    xs = sorted(xs)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else round((xs[m - 1] + xs[m]) / 2.0, 3)


def _count(rows):
    """source -> side -> counts + median of the numbers (descriptive only). AUTHENTIC and PROXY are never mixed."""
    res = {}
    for r in rows:
        m = r["moves"]
        e = res.setdefault(r["source"], {}).setdefault(r["kind"], {"coins": 0, "with_numbers": 0, "volume_HIGH": 0, "volume_NORMAL": 0, "volume_LOW": 0, "volume_unknown": 0, "_f": [], "_a": [], "_t": []})
        e["coins"] += 1
        if m.get("status") == "OK":
            e["with_numbers"] += 1
            e["_f"].append(m["max_favourable_pct"])
            e["_a"].append(m["max_adverse_pct"])
            if m["time_to_peak_min"] is not None:
                e["_t"].append(m["time_to_peak_min"])
            vs = m["volume_state"]
            e["volume_" + (vs["state"] if vs["status"] == "OK" else "unknown")] += 1
        else:
            e["volume_unknown"] += 1
    for sides in res.values():
        for e in sides.values():
            e["median_max_favourable_pct"], e["median_max_adverse_pct"], e["median_time_to_peak_min"] = _med(e.pop("_f")), _med(e.pop("_a")), _med(e.pop("_t"))
    return res


def _day(con, day, now, emap):
    rows = con.execute("SELECT kind, rank, symbol, open_price, snap_ts, source FROM cohort_official WHERE day=? ORDER BY kind, rank", (day,)).fetchall()
    if not rows:
        return {"day": day, "status": "MISSING", "rows": [], "note": "no official cohort was saved for this day. It is never filled in from other data."}
    out = [{"kind": k, "rank": rk, "symbol": s, "source": src, "snap_utc": RD._utc(ts) if ts else None, "snapshot_price": op,
            "episode": emap.get((s, k, day)), "moves": move_numbers(con, k, s, op, ts, now)} for k, rk, s, op, ts, src in rows]
    new = [r for r in out if not (r["episode"] or {}).get("repeat")]
    return {"day": day, "status": "OK", "coins": len(out), "episodes": {"rows": len(out), "new_episodes": len(new), "repeats": len(out) - len(new)},
            "summary": _count(out), "summary_new_episodes_only": _count(new), "rows": out}


def build(con, now=None, day=None, days=None):
    """-> the report dict (read-only). Same day / days choice as Radar 1-4 (default the newest 2 days). Raises ValueError on a bad day / days."""
    now = int(time.time() if now is None else now)
    exp, shown = RD.pick_days(now, day, days)
    emap = EP.mark(EP.episodes(con))
    res = [_day(con, d, now, emap) for d in shown]
    for r in res:
        r["tab"] = RD.tab_label(exp.index(r["day"])) if r["day"] in exp else None
    return {"tool": VERSION, "made_utc": RD._utc(now), "read_only": True, "definition_version": DEF_VERSION, "window_hours": WINDOW_SEC // 3600,
            "definition": {"high_ratio": HIGH_RATIO, "low_ratio": LOW_RATIO, "baseline": "median of the same UTC hour on the 7 days before, at least %d days" % D.MIN_BASELINE_DAYS,
                           "note": "starting values, not validated; a number describes what the saved candles did, not a forecast"},
            "days": res,
            "notes": ["Every move is measured from the SNAPSHOT price in the direction of the cohort (GAINER up, LOSER down); max_adverse is the worst move against it.",
                      "Candles with a gap or a bad row are refused (UNAVAILABLE with the reason); nothing is bridged or guessed.",
                      "volume_state needs the same hour on at least 3 of the 7 earlier days: in the first week of data it is UNAVAILABLE, and that is correct.",
                      "AUTHENTIC and PROXY are counted apart; days and sides are never added together; every count shows how many coins stand behind it.",
                      "No prediction, no win rate, no pattern claim: that needs many episodes AND counterexamples."]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl Radar moves + volume state (read-only)")
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
