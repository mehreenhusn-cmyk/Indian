"""v2_scalp_run.py - Part 54: SCALP LAB 5 of 8 (backend, the RUNNER). Replays the saved candles through the finished categories (EMA_RETEST v1, PUMP_DUMP v1 = FOLLOW and v2 = FADE) and saves the FINISHED hypothetical records in the Scalp Lab ledger (v2_scalp.db).
It is the ONLY Scalp Lab file that writes, and it writes ONLY to v2_scalp.db. The market store is opened read-only; no trading file, no network, no order. Run by hand (Termux), never started by the app.
RULES:
  1. DEFINE FIRST: each category definition + version is saved BEFORE its first record (v2_scalp_store.register_category). A changed rule needs a new version; old records are never rewritten.
  2. ONLY FINISHED: TARGET / STOP / TIME are saved. PENDING and UNAVAILABLE are counted in the output and never saved as 0; a later run saves them once they are finished.
  3. FIXED HOLDOUT: the TRAIN / HOLDOUT cut of a category is chosen ONCE (newest 30% of its finished signal times, v2_replay.holdout_cut) and then kept in the ledger meta table. A later run never moves it, so a record can never change its sample;
     new data after the cut is simply HOLDOUT (walk-forward). With fewer than 2 finished signal times no cut exists and NOTHING is saved yet.
  4. SAME RECORD TWICE = ignored (the record key holds category, version, coin, interval, side and signal time), so running again never double counts.
  5. --dry changes nothing (not even creating the file): it only counts what would be saved.
Run (Termux):  python3 backend/v2_scalp_run.py [--data DIR] [--days N] [--category EMA_RETEST|PUMP_DUMP] [--dry]     (no --days = all saved candles; the output is JSON)"""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_defs as D
import v2_replay as R
import v2_scalp_ema as SE
import v2_scalp_pump as SP
import v2_scalp_store as SS
import v2_setup_finder as SF
import v2_store as S

VERSION = "v2_scalp_run 1 (Part 54)"
CATEGORIES = ("EMA_RETEST", "PUMP_DUMP")


def _scan_ema(run, step, first, now, sym, iv):
    return SE.scan_run(run, step, first, now, sym, iv)[1]


def collect(con, scan, first, now):
    """All events of ONE category over every coin: the interval (5m / 3m) with more clean candles, cut at every gap. -> (events, coins used)."""
    syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM candles")]
    events, used = [], 0
    for s in sorted(syms):
        best = (None, [])
        for iv in ("5m", "3m"):
            good, _bad = D.clean_candles(D.candles_from_store(con, s, iv, 0, now), iv)
            if len(good) > len(best[1]):
                best = (iv, good)
        iv, good = best
        if iv is None:
            continue
        used += 1
        for run in SF.runs(good, iv):
            events.extend(scan(run, D.STEP[iv], first, now, s, iv))
    return events, used


def _finished_times(category, events):
    if category == "EMA_RETEST":
        return [e["signal_ts"] for e in events if e.get("outcome") in R.FINISHED_STATUSES]
    return [e["signal_ts"] for e in events if any(m.get("outcome") in R.FINISHED_STATUSES for m in e["modes"].values())]


def _jobs(category, events, cut):
    """-> list of (version, definition, records) of the category; records are the FINISHED ones only."""
    if category == "EMA_RETEST":
        return [(SE.DEF_VERSION, SE.DEFINITION, SE.records(events, cut))]
    return [(ver, SP.definition(mode), SP.records(events, cut, mode)) for mode, ver in SP.MODES.items()]


def _stored_cut(path_dir, category):
    ro = SS.open_ro(path_dir)
    if ro is None:
        return None
    try:
        row = ro.execute("SELECT value FROM meta WHERE key=?", ("holdout_cut:" + category,)).fetchone()
    finally:
        ro.close()
    return None if row is None else int(row[0])


def run(data_dir, now=None, days=None, categories=CATEGORIES, dry=False):
    """-> the result dict. Raises ValueError on a bad days / category value."""
    now = int(time.time() if now is None else now)
    if days not in (None, "") and (not str(days).isdigit() or int(days) < 1):
        raise ValueError("days must be a whole number from 1, or left out for all saved candles")
    bad = [c for c in categories if c not in CATEGORIES]
    if bad:
        raise ValueError("category not built yet: " + ", ".join(bad))
    first = 0 if days in (None, "") else now - int(days) * 86400
    path = S.store_path(data_dir)
    if not os.path.isfile(path):
        return {"ready": False, "note": "the market store is not created yet"}
    mcon = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    mcon.execute("PRAGMA query_only=ON")
    sc = None if dry else SS.connect(data_dir)
    out = {"ready": True, "version": VERSION, "dry": bool(dry), "days": days or "all", "categories": []}
    try:
        for cat in categories:
            events, used = collect(mcon, _scan_ema if cat == "EMA_RETEST" else SP.scan_run, first, now)
            times = _finished_times(cat, events)
            cut = _stored_cut(data_dir, cat)
            how = "kept" if cut is not None else "new"
            if cut is None:
                cut = R.holdout_cut(times)
            item = {"category": cat, "coins": used, "signals": len(events), "finished_signal_times": len(set(times)),
                    "holdout_from_utc": None if cut is None else time.strftime("%Y-%m-%d %H:%M", time.gmtime(cut)), "holdout_cut": how if cut is not None else "not set yet", "versions": []}
            if cut is None:
                item["note"] = "fewer than 2 finished signal times: no TRAIN / HOLDOUT cut yet, nothing saved"
            else:
                if sc is not None and how == "new":
                    sc.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", ("holdout_cut:" + cat, str(cut)))
                    sc.commit()
                for ver, dfn, recs in _jobs(cat, events, cut):
                    v = {"version": ver, "finished_records": len(recs), "saved_new": None, "already_there": None}
                    if sc is not None:
                        SS.register_category(sc, cat, ver, dfn, now)
                        new = sum(1 for r in recs if SS.add_record(sc, cat, ver, r))
                        v["saved_new"], v["already_there"] = new, len(recs) - new
                    item["versions"].append(v)
            out["categories"].append(item)
    finally:
        mcon.close()
        if sc is not None:
            sc.close()
    out["note"] = "hypothetical replay only; only finished records are saved; PENDING / UNAVAILABLE are never saved as 0; the holdout cut is fixed once chosen; nothing here places an order"
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--days", default="")
    ap.add_argument("--category", default="")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    try:
        res = run(a.data, None, a.days, (a.category,) if a.category else CATEGORIES, a.dry)
    except (ValueError, S.StoreRefused) as e:
        print(json.dumps({"error": str(e)}))
        return 2
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
