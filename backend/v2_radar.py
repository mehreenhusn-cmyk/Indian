"""v2_radar.py - Part 29 + 30: RADAR 1-2 of 6 (backend, read-only). "Yesterday's top coins: how did those exact coins move since?"
The first Radar report over the collector tables of the market store (v2_market.db, Parts 6, 14-18):
  cohort_official  -> the saved 00:00 UTC cohort (top 5 GAINER + top 5 LOSER of the UTC day that just ended), each row labelled AUTHENTIC or PROXY by the collector
  ticker_snapshot  -> the 5-minute top-list snapshots (latest price, path since the cohort snapshot)
  candles          -> newest 3m / 5m candle, used only when it is newer than the newest snapshot
Rules (README4 section 9.5): a past cohort is NEVER replaced by today's ranks; a missing day is shown MISSING and never filled in; the label stored by the
collector (AUTHENTIC / PROXY) is shown as it is; every latest price shows its OWN timestamp and age; a price that cannot be found is UNKNOWN, never 0;
no prediction, no win rate, no "pattern" claim. The store is opened read-only and is never created here. No network, no trading module, no ledger row.
Part 30 adds the 7-day tabs: ?days=N (1 to 7) gives the N newest saved cohorts, every day has its tab name (Yesterday, 2 days ago ... 7 days ago) and a small
summary per side (coins, priced, UNKNOWN, median / lowest / highest change; each day alone, days are never added together); a `tabs` list always names all 7 days.
Not in these Parts (later Radar Parts): 1 / 2 / 3 / 7-day outcome classes, episode rules, volume baseline, the Flutter card.

Run (Termux):  python3 backend/v2_radar.py [--data DIR] [--day YYYY-MM-DD | --days N]     -> prints the report as JSON
Route: GET /api/v2/radar[?day=YYYY-MM-DD | ?days=N] (Part 29 + 30, in api/v2_data.py; off until v2_api_enabled exists)."""
import argparse
import datetime
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "v2_radar 2 (Part 30)"
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PER_SIDE = 5                      # the collector saves the top 5 of each side (v2_collector.COHORT_TOP)
FRESH_SEC = 900                   # a latest price older than 15 minutes is called stale
DEFAULT_DAYS = 2                  # newest two cohort days; any other day with ?day=
EXPECT_DAYS = 7
MAX_DAYS = 7                      # Part 30: ?days=N accepts 1 to 7
IV_SEC = {"3m": 180, "5m": 300}
CHANGE_FORMULA = "change % = (latest price - snapshot price) / snapshot price x 100"


def _utc(ts):
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _day_of(ts):
    return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%Y-%m-%d")


def expected_days(now, n=EXPECT_DAYS):
    """The UTC days whose cohort should exist: yesterday and the days before it (the cohort saved at 00:00 UTC ranks the day that just ended)."""
    mid = int(now) - int(now) % 86400
    return [_day_of(mid - 86400 * (i + 1)) for i in range(n)]


def tab_label(i):
    """Part 30: the tab name of the i-th expected day (0 = the cohort saved at 00:00 UTC today, ranking yesterday's UTC day)."""
    return "Yesterday" if i == 0 else "%d days ago" % (i + 1)


def _days_arg(days):
    """None / empty = the default 2 days; else a whole number 1 to 7, anything else is a ValueError (the route answers 400)."""
    if days is None or str(days).strip() == "":
        return DEFAULT_DAYS
    try:
        n = int(str(days).strip())
    except ValueError:
        raise ValueError("days must be a whole number from 1 to %d" % MAX_DAYS)
    if n < 1 or n > MAX_DAYS:
        raise ValueError("days must be a whole number from 1 to %d" % MAX_DAYS)
    return n


def pick_days(now, day, days):
    """-> (the 7 expected days, the days to show). Part 30; shared with v2_radar_outcomes. ValueError on a bad day text, a bad days number, or both given."""
    if day is not None and not DAY_RE.match(day):
        raise ValueError("day must look like 2026-10-30")
    if day and days not in (None, ""):
        raise ValueError("use day or days, not both")
    exp = expected_days(now)
    return exp, ([day] if day else exp[:_days_arg(days)])


def _side_summary(rows):
    """Part 30: per side, counts and the spread of the change since the snapshot. Descriptive only (no win rate, no forecast); a coin with no price is UNKNOWN, not 0."""
    out = {}
    for kind in ("GAINER", "LOSER"):
        rs = [r for r in rows if r["kind"] == kind]
        ch = sorted(r["change_pct"] for r in rs if r.get("change_pct") is not None)
        o = {"coins": len(rs), "priced": len(ch), "unknown": len(rs) - len(ch)}
        if ch:
            m = len(ch) // 2
            o["median_change_pct"] = ch[m] if len(ch) % 2 else round((ch[m - 1] + ch[m]) / 2.0, 3)
            o["lowest_change_pct"] = ch[0]
            o["highest_change_pct"] = ch[-1]
        out[kind] = o
    return out


def _tabs(con, exp):
    """Part 30: one entry for each of the 7 expected days (saved row counts only, nothing filled in)."""
    saved = {}
    for day, kind, n, a in con.execute("SELECT day, kind, COUNT(*), SUM(CASE WHEN source='AUTHENTIC' THEN 1 ELSE 0 END) FROM cohort_official GROUP BY day, kind"):
        d = saved.setdefault(day, {"rows": 0, "authentic": 0, "kinds": {}})
        d["rows"] += n
        d["authentic"] += a or 0
        d["kinds"][kind] = n
    tabs = []
    for i, day in enumerate(exp):
        d = saved.get(day)
        if not d:
            tabs.append({"tab": tab_label(i), "day": day, "status": "MISSING", "rows": 0})
            continue
        full = all(d["kinds"].get(k, 0) >= PER_SIDE for k in ("GAINER", "LOSER"))
        tabs.append({"tab": tab_label(i), "day": day, "status": "COMPLETE" if full else "INCOMPLETE", "rows": d["rows"],
                     "authentic": d["authentic"], "proxy": d["rows"] - d["authentic"]})
    return tabs


def _pct(a, b):
    try:
        return round((float(a) - float(b)) / float(b) * 100.0, 3) if b and float(b) > 0 else None
    except (TypeError, ValueError):
        return None


def _latest(con, sym, now, cache):
    """Newest price of a coin with its own timestamp: the newer of the newest snapshot and the newest candle. None when there is nothing."""
    if sym in cache:
        return cache[sym]
    best = None
    r = con.execute("SELECT run_ts, price FROM ticker_snapshot WHERE symbol=? AND price>0 ORDER BY run_ts DESC LIMIT 1", (sym,)).fetchone()
    if r:
        best = {"price": r[1], "ts": r[0], "source": "ticker_snapshot"}
    for iv, sec in IV_SEC.items():
        c = con.execute("SELECT open_ts, c FROM candles WHERE symbol=? AND interval=? AND c>0 ORDER BY open_ts DESC LIMIT 1", (sym, iv)).fetchone()
        if c:
            ts = min(int(c[0]) + sec, int(now))
            if best is None or ts > best["ts"]:
                best = {"price": c[1], "ts": ts, "source": "candle_" + iv}
    cache[sym] = best
    return best


def _path(con, sym, snap_price, snap_ts, last_ts):
    """What the saved snapshots show after the cohort snapshot: count, coverage, highest and lowest price, time to the high. Only the top-list snapshots exist."""
    r = con.execute("SELECT COUNT(*), MIN(price), MAX(price) FROM ticker_snapshot WHERE symbol=? AND run_ts>? AND price>0", (sym, snap_ts)).fetchone()
    n = r[0] if r else 0
    if not n:
        return {"snapshots": 0, "coverage_pct": None, "note": "no snapshot after the cohort: the coin was outside the saved top lists (UNKNOWN, not flat)"}
    hi = con.execute("SELECT run_ts FROM ticker_snapshot WHERE symbol=? AND run_ts>? AND price=? ORDER BY run_ts LIMIT 1", (sym, snap_ts, r[2])).fetchone()
    span = max(0, int(last_ts) - int(snap_ts))
    want = max(1, span // 300)
    return {"snapshots": n, "coverage_pct": min(100.0, round(n * 100.0 / want, 1)),
            "max_up_pct": _pct(r[2], snap_price), "max_down_pct": _pct(r[1], snap_price),
            "hours_to_high": None if not hi else round((hi[0] - snap_ts) / 3600.0, 2)}


def _day(con, day, now, cache):
    rows = con.execute("SELECT kind, rank, symbol, open_price, snap_ts, source FROM cohort_official WHERE day=? ORDER BY kind, rank", (day,)).fetchall()
    if not rows:
        return {"day": day, "status": "MISSING", "rows": [],
                "note": "no official cohort was saved for this day. It is never filled in from other data."}
    out, kinds, srcs = [], {}, {}
    for kind, rank, sym, op, sts, src in rows:
        kinds[kind] = kinds.get(kind, 0) + 1
        srcs[src] = srcs.get(src, 0) + 1
        lt = _latest(con, sym, now, cache)
        row = {"kind": kind, "rank": rank, "symbol": sym, "snapshot_price": op, "snap_ts": sts, "snap_utc": _utc(sts) if sts else None, "source": src}
        if lt and op and float(op) > 0:
            age = max(0, int(now) - int(lt["ts"]))
            row.update({"latest_price": lt["price"], "latest_ts": lt["ts"], "latest_utc": _utc(lt["ts"]), "latest_from": lt["source"],
                        "latest_age_sec": age, "freshness": "fresh" if age <= FRESH_SEC else "stale",
                        "change_pct": _pct(lt["price"], op), "hours_since_snapshot": round((int(lt["ts"]) - int(sts)) / 3600.0, 2),
                        "path": _path(con, sym, op, sts, lt["ts"])})
        else:
            row.update({"latest_price": None, "freshness": "none", "change_pct": None,
                        "note": "UNKNOWN: no latest price saved for this coin (it is not zero)"})
        out.append(row)
    full = all(kinds.get(k, 0) >= PER_SIDE for k in ("GAINER", "LOSER"))
    return {"day": day, "status": "COMPLETE" if full else "INCOMPLETE", "by_kind": kinds, "by_source": srcs,
            "all_authentic": srcs.get("AUTHENTIC", 0) == len(rows), "summary": _side_summary(out), "rows": out}


def build(con, now=None, day=None, days=None):
    """-> the report dict (read-only). day=None and days=None: the newest 2 expected days; days=N (1 to 7): the newest N; MISSING days are listed as MISSING.
    Raises ValueError on a bad day text, a bad days number, or both given."""
    now = int(time.time() if now is None else now)
    exp, shown = pick_days(now, day, days)
    cache = {}
    res = [_day(con, d, now, cache) for d in shown]
    for r in res:
        r["tab"] = tab_label(exp.index(r["day"])) if r["day"] in exp else None
    present = {r[0] for r in con.execute("SELECT DISTINCT day FROM cohort_official").fetchall()}
    return {"tool": VERSION, "made_utc": _utc(now), "read_only": True, "change_formula": CHANGE_FORMULA, "days": res,
            "tabs": _tabs(con, exp), "coverage": {"expected_days": exp, "days_present": [d for d in exp if d in present], "days_missing": [d for d in exp if d not in present],
                         "other_days_saved": sorted(present - set(exp))[-10:]},
            "notes": ["Cohort = top %d gainers + top %d losers at 00:00 UTC (05:30 IST) of the UTC day that just ended; each row keeps the AUTHENTIC / PROXY label the collector gave it." % (PER_SIDE, PER_SIDE),
                      "A past cohort is never replaced by today's ranks and a missing day is never filled in.",
                      "Latest price = the newest saved snapshot or candle, with its own time and age; no price saved = UNKNOWN.",
                      "Path numbers come from the 5-minute top-list snapshots only; a coin outside those lists shows fewer snapshots (coverage % says how many).",
                      "Each day stands alone: the days and the two sides are never added together. The summary describes that day's saved coins, it is not a forecast.",
                      "No prediction and no win rate. 1 / 2 / 3 / 7-day outcome classes come in later Radar Parts."]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl Radar report (read-only)")
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
