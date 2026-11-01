"""v2_bt_dataq.py - Part N1: DATA QUALITY CHECK (backend, read-only). It replaces the chip that said NOT_CHECKED on the Brain Health screen.
What it looks at (the saved candle store, the coins the collector follows, the newest 200 candles of each, one timeframe):
  stale   the newest closed candle is older than 4 candles (same limit idea as the safety guard)
  bad     rows that clean_candles throws away (not 6 numbers, price <= 0, wrong high / low, duplicate time)
  gaps    holes in the time line (a missing candle; gaps are counted, never filled)
Answer: PASS (nothing wrong), WARN (some coins have a problem), FAIL (more than 3 of 10 coins are stale), NOT_CHECKED (no store or no coins yet - never a made-up PASS).
Reads the market store read-only. No network, no write, no trading import. Limits (4 candles, 30 percent, 200 candles, 40 coins) are starting values, not validated.
Run (Termux, optional):  python3 backend/v2_bt_dataq.py [--data DIR] [--interval 5m]  -> the plain lines."""
import argparse
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_candles as K
import v2_defs as D
import v2_store as S

VERSION = "v2_bt_dataq 1 (Part N1)"
LOOK, MAX_COINS, STALE_CANDLES, FAIL_SHARE = 200, 40, 4, 0.3


def _coin(con, symbol, interval, now):
    step = D.STEP[interval]
    rows = D.candles_from_store(con, symbol, interval, now - LOOK * step, 2 ** 31)
    good, bad = D.clean_candles(rows, interval)
    if not good:
        return {"symbol": symbol, "n": 0, "stale": True, "bad": bad, "gaps": 0, "age_min": None}
    age = now - (good[-1][0] + step)
    gaps = sum(1 for a, b in zip(good, good[1:]) if b[0] - a[0] != step)
    return {"symbol": symbol, "n": len(good), "stale": age > STALE_CANDLES * step, "bad": bad, "gaps": gaps, "age_min": max(0, age // 60)}


def check(data_dir, now=None, interval="5m"):
    now = int(time.time() if now is None else now)
    if interval not in D.STEP:
        raise ValueError("interval must be 3m or 5m")
    path = S.store_path(data_dir)
    if not os.path.isfile(path):
        return {"state": "NOT_CHECKED", "note": "No candle store yet, so there is nothing to check.", "coins": 0}
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    try:
        syms = K.pick_symbols(con, now)[:MAX_COINS]
        rows = [_coin(con, s, interval, now) for s in syms]
    except sqlite3.Error as e:
        return {"state": "NOT_CHECKED", "note": "The check could not read the store (%s)." % type(e).__name__, "coins": 0}
    finally:
        con.close()
    if not rows:
        return {"state": "NOT_CHECKED", "note": "The collector follows no coin yet.", "coins": 0}
    st = [r for r in rows if r["stale"]]
    bd = [r for r in rows if r["bad"]]
    gp = [r for r in rows if r["gaps"]]
    n = len(rows)
    if len(st) > n * FAIL_SHARE:
        state = "FAIL"
    elif st or bd or gp:
        state = "WARN"
    else:
        state = "PASS"
    note = "%d coins checked on %s: %d stale, %d with bad rows, %d with gaps." % (n, interval, len(st), len(bd), len(gp))
    worst = (st or bd or gp)[:3]
    return {"state": state, "note": note, "coins": n, "stale": len(st), "bad": len(bd), "gaps": len(gp), "examples": [r["symbol"] for r in worst]}


def chip(data_dir, now=None):
    """-> (state, note) for the safety chip of the Brain Health screen."""
    r = check(data_dir, now)
    return r["state"], r["note"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--interval", default="5m")
    a = ap.parse_args(argv)
    r = check(a.data, None, a.interval)
    print(r["state"], "-", r["note"])
    if r.get("examples"):
        print("examples:", ", ".join(r["examples"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
