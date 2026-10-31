"""v2_prepump_watch.py - Part 48: PRE-PUMP / PRE-DUMP WATCH 2 of 3 (backend, read-only). "Which coins of TODAY look like the coins that pumped / dumped before, and what did their price do since they showed up?"
Two watch lists, never mixed:  PRE_PUMP = coins of today's UTC day in the top 20 GAINERS (rank_gain),  PRE_DUMP = coins in the top 20 LOSERS (rank_loss).
For every such coin it takes the FIRST saved snapshot of today in which the coin stood in the top 20 of its side (rank, change, price, hour) and compares rank and size of the change with the
OLD CASES of Part 47 (v2_prepump.build: observed cohort coins of the same side, NEW EPISODES only, AUTHENTIC and PROXY kept apart). Inside the old range = MATCH, else OUTSIDE.
Range = the 10th to 90th percentile of the old cases (rank at first, |change at first|); it is a plain description of what old cases looked like, NOT a signal. Many coins will match: the base count
(coins in the list today vs matching) is always shown so a match is never read as rare.
WATCH ONLY: from the first moment (entry) the price is followed with what the saved top-20 snapshots show (change since entry, highest / lowest saved price, hours since entry, coverage).
Nothing is written, no order, no prediction, no win rate. The track is recomputed from the store each time, so it starts at the true entry for as long as the snapshots exist.
Honesty rules (README4 section 9.5): the store keeps ONLY the top 20 lists, so a coin that left the list has no price after that (UNKNOWN, not flat; coverage shows it); a coin already in the very first saved snapshot of today =
ENTRY_CENSORED (tracked from that snapshot, but never judged as an early coin); fewer than MIN_REF old observed cases of that side + source = NOT ENOUGH DATA (never 0, never a guess); no snapshot today = NO SNAPSHOT TODAY;
a newest snapshot older than 15 minutes = STALE (collector not running now). AUTHENTIC and PROXY old cases are never added together. Read-only: mode=ro, no network.
Run (Termux):  python3 backend/v2_prepump_watch.py [--data DIR] [--days N]     (N = how many old cohort days make the old cases, 1 to 7, default 7)     Route: GET /api/v2/prepump_watch[?days=N] (api/v2_data.py)."""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_prepump as PP
import v2_radar as RD

VERSION = "v2_prepump_watch 1 (Part 48)"
DEF_VERSION = 1
DAY_SEC = 86400
MIN_REF = 10                 # old observed cases needed per side + source before a coin can be judged (NV, starting value)
LO_PCT, HI_PCT = 10, 90      # the old range = 10th to 90th percentile (NV, starting value)
MAX_ROWS = 30                # rows shown per list (the counts cover all coins)
LISTS = (("PRE_PUMP", "GAINER", "rank_gain"), ("PRE_DUMP", "LOSER", "rank_loss"))
SOURCES = ("AUTHENTIC", "PROXY")


def _pct(xs, q):
    """Nearest-rank percentile of a non-empty list."""
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, int(round(q / 100.0 * (len(xs) - 1)))))
    return xs[i]


def reference(con, now, days):
    """-> {(kind, source): {"n", "rank": (lo, hi), "change": (lo, hi), "hours": (lo, hi)}} from the observed Part 47 cases (new episodes only). A key without enough cases has "n" < MIN_REF and no ranges."""
    rep = PP.build(con, now, None, days)
    acc = {}
    for d in rep["days"]:
        for r in d.get("rows", []):
            e = r.get("early") or {}
            if e.get("status") != "OK" or (r.get("episode") or {}).get("repeat"):
                continue
            c = e.get("change_at_first_pct")
            if not isinstance(c, (int, float)) or not isinstance(e.get("rank_at_first"), (int, float)):
                continue
            a = acc.setdefault((r["kind"], r["source"]), {"rank": [], "change": [], "hours": []})
            a["rank"].append(e["rank_at_first"])
            a["change"].append(abs(c))
            a["hours"].append(e["hours_into_day"])
    out = {}
    for k, a in acc.items():
        o = {"n": len(a["rank"])}
        if o["n"] >= MIN_REF:
            for name in ("rank", "change", "hours"):
                o[name] = (round(_pct(a[name], LO_PCT), 3), round(_pct(a[name], HI_PCT), 3))
        out[k] = o
    return out


def judge(kind, rank, change, ref):
    """Compare one coin's first top-20 moment with the old range of one source. -> {"status", "why"}."""
    if not ref or ref.get("n", 0) < MIN_REF:
        return {"status": "NOT ENOUGH DATA", "old_cases": (ref or {}).get("n", 0), "why": "fewer than %d old observed cases of this side and source" % MIN_REF}
    if not isinstance(change, (int, float)) or not isinstance(rank, (int, float)):
        return {"status": "NOT JUDGED", "old_cases": ref["n"], "why": "rank or change missing"}
    if (change < 0) != (kind == "LOSER") and change != 0:
        return {"status": "NOT JUDGED", "old_cases": ref["n"], "why": "the change has the other sign than the side"}
    ok_rank = ref["rank"][0] <= rank <= ref["rank"][1]
    ok_chg = ref["change"][0] <= abs(change) <= ref["change"][1]
    return {"status": "MATCH" if ok_rank and ok_chg else "OUTSIDE", "old_cases": ref["n"], "rank_in_range": ok_rank, "change_in_range": ok_chg,
            "old_rank_range": list(ref["rank"]), "old_change_range": list(ref["change"])}


def _today(con, now, ref):
    mid = now - now % DAY_SEC
    rows = con.execute("SELECT run_ts, symbol, price, change_pct, volume_usdt, rank_gain, rank_loss FROM ticker_snapshot WHERE run_ts>=? AND run_ts<=? ORDER BY run_ts, symbol", (mid, now)).fetchall()
    day = RD._day_of(mid)
    if not rows:
        return {"day": day, "status": "NO SNAPSHOT TODAY", "lists": {}, "note": "no top-20 snapshot of today is saved yet (the collector is not running, or it is just after 00:00 UTC). Nothing is filled in."}
    first_ts, last_ts = rows[0][0], rows[-1][0]
    age = max(0, now - last_ts)
    fresh = "fresh" if age <= RD.FRESH_SEC else "stale"
    cache, lists = {}, {}
    for name, kind, col in LISTS:
        idx = 5 if col == "rank_gain" else 6
        seen, in_now = {}, set()
        for r in rows:
            if r[idx] is None:
                continue
            seen.setdefault(r[1], r)
            if r[0] == last_ts:
                in_now.add(r[1])
        coins = []
        for sym, r in seen.items():
            censored = r[0] <= first_ts
            ent = {"symbol": sym, "first_top20_utc": RD._utc(r[0]), "entry_ts": r[0], "hours_into_day": round((r[0] - mid) / 3600.0, 2), "rank_at_first": r[idx],
                   "change_at_first_pct": r[3], "entry_price": r[2], "in_top20_now": sym in in_now,
                   "entry_status": "ENTRY_CENSORED" if censored else "OK"}
            if censored:
                ent["entry_note"] = "already in the very first saved snapshot of today: the real first moment is unknown, tracked from that snapshot and never judged as early"
                ent["matches"] = {s: {"status": "NOT JUDGED", "why": "entry censored"} for s in SOURCES}
            else:
                ent["matches"] = {s: judge(kind, r[idx], r[3], ref.get((kind, s))) for s in SOURCES}
            coins.append(ent)
        n_match = {s: sum(1 for c in coins if c["matches"][s]["status"] == "MATCH") for s in SOURCES}
        coins.sort(key=lambda c: (-sum(1 for s in SOURCES if c["matches"][s]["status"] == "MATCH"), -c["entry_ts"]))
        for c in coins[:MAX_ROWS]:
            ep, ets = c["entry_price"], c["entry_ts"]
            lt = RD._latest(con, c["symbol"], now, cache)
            if lt and isinstance(ep, (int, float)) and ep > 0:
                lag = max(0, now - int(lt["ts"]))
                c.update(latest_price=lt["price"], latest_utc=RD._utc(lt["ts"]), latest_age_sec=lag, freshness="fresh" if lag <= RD.FRESH_SEC else "stale",
                         change_since_entry_pct=RD._pct(lt["price"], ep), hours_since_entry=round((int(lt["ts"]) - ets) / 3600.0, 2), path=RD._path(con, c["symbol"], ep, ets, lt["ts"]))
            else:
                c.update(latest_price=None, freshness="none", change_since_entry_pct=None, note="UNKNOWN: no entry price or no latest price saved (it is not zero)")
        lists[name] = {"side": kind, "coins_in_top20_today": len(coins), "matching": n_match, "shown": min(len(coins), MAX_ROWS), "rows": coins[:MAX_ROWS],
                       "base_note": "matching is counted against ALL %d coins of this list today, so read a match together with that base" % len(coins)}
    return {"day": day, "status": "OK", "first_snapshot_utc": RD._utc(first_ts), "last_snapshot_utc": RD._utc(last_ts), "last_snapshot_age_sec": age, "freshness": fresh,
            "note": "" if fresh == "fresh" else "STALE: the newest saved snapshot is older than 15 minutes, the collector is not running now", "lists": lists}


def build(con, now=None, days=None):
    """-> the report dict (read-only). days = how many old cohort days make the old cases (1 to 7, default 7). Raises ValueError on a bad days."""
    now = int(time.time() if now is None else now)
    n = 7 if days is None or str(days).strip() == "" else days
    ref = reference(con, now, n)
    shown = {"%s/%s" % (k, s): {kk: vv for kk, vv in v.items()} for (k, s), v in sorted(ref.items())}
    for k, s in ((k, s) for _, k, _ in LISTS for s in SOURCES):
        shown.setdefault("%s/%s" % (k, s), {"n": 0})
    for v in shown.values():
        v["status"] = "OK" if v["n"] >= MIN_REF else "NOT ENOUGH DATA (%d of %d old cases)" % (v["n"], MIN_REF)
    return {"tool": VERSION, "made_utc": RD._utc(now), "read_only": True, "definition_version": DEF_VERSION, "old_cases": shown, "today": _today(con, now, ref),
            "notes": ["PRE_PUMP = today's top 20 GAINERS, PRE_DUMP = today's top 20 LOSERS. They are never added together. AUTHENTIC and PROXY old cases stay apart.",
                      "MATCH = the coin's rank and change at its first top-20 moment lie inside the 10th to 90th percentile range of the old cases (Part 47). A description, NOT a forecast, and common: read it with the base count.",
                      "The store keeps only the top 20 lists: after a coin leaves the list its price is UNKNOWN (coverage shows it), never flat and never 0.",
                      "ENTRY_CENSORED = already in the first saved snapshot of today, real first moment unknown. Fewer than %d old cases = NOT ENOUGH DATA." % MIN_REF,
                      "Watch only. No prediction, no win rate, no order, nothing is written."]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl pre-pump / pre-dump watch lists (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--days", help="1 to 7: how many old cohort days make the old cases (default 7)")
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
