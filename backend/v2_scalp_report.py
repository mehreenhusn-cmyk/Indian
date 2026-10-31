"""v2_scalp_report.py - Part 54: SCALP LAB 5 of 8 (backend, read-only). The REPORT of the Scalp Lab ledger (v2_scalp.db): per category, per version, per side, TRAIN and HOLDOUT apart.
It reads only the saved FINISHED records (written by v2_scalp_run.py) through a read-only connection; it never writes and never touches the market store.
RULES: every category / version / side is its own line and is NEVER added to another (no total over categories, README4 9.7); every number shows its n; under 30 finished = "too few to say anything" (v2_replay.summarize);
the evidence word is only "Insufficient data" (HOLDOUT under 30) or "Exploratory" (HOLDOUT 30 or more) - the ledger has no baseline, so nothing higher is ever said here (the category route shows the baseline); no win rate, no prediction, no order.
Hypothetical replay, fees and slippage already taken off, raw price %, not leveraged. Run (Termux):  python3 backend/v2_scalp_report.py [--data DIR]     Route: GET /api/v2/scalp_report (api/v2_data.py)."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_replay as R
import v2_scalp_store as SS

VERSION = "v2_scalp_report 1 (Part 54)"


def _utc(ts):
    return None if ts is None else time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts))


def build(data_dir):
    """-> the report dict, read-only. No Scalp Lab file yet = ready False (nothing replayed)."""
    con = SS.open_ro(data_dir)
    if con is None:
        return {"ready": False, "version": VERSION, "note": "no Scalp Lab file yet: nothing has been replayed (run backend/v2_scalp_run.py)"}
    try:
        defs = con.execute("SELECT category, version, definition, created_ts FROM category_def ORDER BY category, version").fetchall()
        cuts = {k[len("holdout_cut:"):]: int(v) for k, v in con.execute("SELECT key, value FROM meta WHERE key LIKE 'holdout_cut:%'")}
        cats = []
        for cat, ver, dj, created in defs:
            rows = con.execute("SELECT side, sample, status, net_pct, symbol, signal_ts, hold_candles FROM record WHERE category=? AND version=?", (cat, ver)).fetchall()
            sides = {}
            for sd in R.SIDES:
                mine = [r for r in rows if r[0] == sd]
                part = {k: R.summarize([(r[2], r[3]) for r in mine if r[1] == k]) for k in ("TRAIN", "HOLDOUT")}
                hold = [r[6] for r in mine]
                sides[sd] = {"records": len(mine), "coins": len({r[4] for r in mine}), "first_utc": _utc(min((r[5] for r in mine), default=None)), "last_utc": _utc(max((r[5] for r in mine), default=None)),
                             "median_hold_candles": R._med(hold), "TRAIN": part["TRAIN"], "HOLDOUT": part["HOLDOUT"],
                             "evidence": "Insufficient data" if part["HOLDOUT"]["n"] < R.MIN_N else "Exploratory"}
            cats.append({"category": cat, "version": ver, "saved_utc": _utc(created), "definition": json.loads(dj), "holdout_from_utc": _utc(cuts.get(cat)), "sides": sides})
        return {"ready": True, "version": VERSION, "categories": cats,
                "notes": ["hypothetical replay of saved candles, no order; fees and slippage taken off; raw price %, not leveraged",
                          "each category, version and side is its own line and is never added to another; TRAIN is older, HOLDOUT is newer than the fixed cut",
                          "a result is only interesting if it beats the baseline of ordinary candles (category routes) AND n is large; under 30 finished = too few to say anything"]}
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    a = ap.parse_args(argv)
    print(json.dumps(build(a.data), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
