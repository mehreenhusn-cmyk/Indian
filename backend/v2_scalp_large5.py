"""v2_scalp_large5.py - Part 56: SCALP LAB 7 of 8 (backend, read-only, HYPOTHETICAL replay). Large-trade replay on 5m candles + REAL vs hypothetical SIDE BY SIDE, for 3m and 5m.
It reuses the Part 55 engine (v2_scalp_large3.build with interval 5m) and writes NOTHING: no ledger, no trade file, no setting. The real trade is never changed. Every number is a hypothetical beside it.
SIDE BY SIDE (the "side_by_side" list; one line per box x interval x sample, TRAIN and HOLDOUT apart, boxes never added together):
  REAL = the recorded trade: its real entry price to its real exit price (raw price move %), minus the SAME costs the replay pays (fee + slippage per side), so all columns stand on equal footing. The real fees may differ.
  ONE  = the same trade re-drawn on candle closes (whole size in at the entry candle close, out at the exit candle close).   IN3 = the entry split in 3 pieces (see Part 55).
  ONE_minus_REAL = per trade (ONE - REAL), then the median: how far candle-close prices are from the real fills. A big number means the replay is NOT a fair copy of the real trade and IN3 must not be trusted.
  The SAME trades are in every column (paired: only trades with a real entry and exit price). Under 30 paired trades = "too few to say anything" (number shown as None). No win rate, no prediction, no order, no advice to change a real trade.
Starting values (3 pieces, 2 candles apart, top quarter = large, costs) are NOT validated. 5m needs saved 5m candles; trades older than them are NO_CANDLES (never 0).
Run (Termux):  python3 backend/v2_scalp_large5.py [--data DIR] [--days N]     Route: GET /api/v2/scalp_large5[?days=N] (api/v2_data.py), N = 1 to 365 (default: all)."""
import argparse
import json
import os
import sqlite3
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_replay as R
import v2_scalp_large3 as L3
import v2_store as S

VERSION = "v2_scalp_large5 1 (Part 56)"
INTERVAL = "5m"
OTHER = "3m"
KEEP_ROWS = 30
SAMPLES = ("TRAIN", "HOLDOUT")
COLS = ("REAL_net_pct", "ONE_net_pct", "IN3_net_pct", "ONE_minus_REAL")


def _line(box, interval, sample, s):
    p = (s or {}).get("paired") or {}
    n = p.get("n", 0)
    out = {"box": box, "interval": interval, "sample": sample, "n_replayed": (s or {}).get("n", 0), "n_paired": n}
    for c in COLS:
        out[c] = (p.get(c) or {}).get("median")
    out["IN3_better"], out["IN3_worse"], out["same"] = (s or {}).get("IN3_better", 0), (s or {}).get("IN3_worse", 0), (s or {}).get("same", 0)
    if n < R.MIN_N:
        out["note"] = "too few to say anything (under %d paired trades)" % R.MIN_N
    return out


def side_by_side(rep, interval):
    rows = []
    for box, b in (rep.get("boxes") or {}).items():
        for sm in SAMPLES:
            if sm in b:
                rows.append(_line(box, interval, sm, b[sm]))
    return rows


def build(con, data_dir, now=None, days=None):
    """-> the report dict (read-only). days = 1 to 365 (default all). Raises ValueError on a bad days value."""
    r5 = L3.build(con, data_dir, now, days, INTERVAL)
    if not r5.get("ready"):
        return dict(r5, version=VERSION)
    r3 = L3.build(con, data_dir, now, days, OTHER)
    boxes = {}
    for box, b in r5["boxes"].items():
        boxes[box] = dict(b, rows=b.get("rows", [])[-KEEP_ROWS:])
    return {"ready": True, "version": VERSION, "interval": INTERVAL, "days": r5.get("days"), "definition": r5["definition"],
            "candles_from_utc": {INTERVAL: r5.get("candles_from_utc"), OTHER: r3.get("candles_from_utc")}, "sources": r5.get("sources"),
            "side_by_side": side_by_side(r3, OTHER) + side_by_side(r5, INTERVAL), "boxes": boxes,
            **({"note": r5["note"]} if r5.get("note") else {}),
            "notes": ["HYPOTHETICAL replay of saved candles, no order, nothing written; the real trades are never changed",
                      "REAL = recorded entry to exit price move minus the same costs as the replay (real fees may differ); ONE = same trade on candle closes; IN3 = entry split in 3 pieces",
                      "the same trades stand in every column (paired); each box is its own world and is never added to another; TRAIN and HOLDOUT are never added",
                      "ONE_minus_REAL is the honesty check: a big gap means candle-close prices are far from the real fills and the replay is not a fair copy",
                      "trades older than the saved candles are NO_CANDLES, never 0; under 30 paired trades = too few to say anything; all numbers are starting values, not validated"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--days", default="")
    a = ap.parse_args(argv)
    path = S.store_path(a.data)
    if not os.path.isfile(path):
        print(json.dumps({"ready": False, "note": "the market store is not created yet"}))
        return 0
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    try:
        con.execute("PRAGMA query_only=ON")
        rep = build(con, a.data, None, a.days)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    finally:
        con.close()
    for bx in rep.get("boxes", {}).values():
        bx["rows"] = bx.get("rows", [])[-3:]
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
