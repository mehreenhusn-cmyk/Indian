#!/usr/bin/env python3
"""tools/owl_numbers_check.py - READ ONLY check of the real data folder (default ~/owl_data, or OWL_DATA_DIR, or --data DIR). Writes nothing, sends nothing, opens no trade.
Run (Termux, in the repo folder):   python3 tools/owl_numbers_check.py            then send the whole output to Claude.
Part 1  why the Dashboard "Today P&L - Main bot" and the Brain page "Main bot today" can differ: today's closed trades of the archive, summed in the ways the two pages sum them.
Part 2  the new Brain "why" answer on the real Brain file.      Part 3  the new Sniper "winners vs losers" answer on the real past trades."""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))


def _rows(path):
    out = []
    if not os.path.isfile(path):
        return out
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
                if isinstance(t, dict):
                    out.append(t)
            except Exception:
                pass
    return out


def _f(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def part1(d, now):
    a = now - now % 86400          # 00:00 UTC = 05:30 IST, the day start of both pages
    p = os.path.join(d, "closed_trades_archive.jsonl")
    rows = [t for t in _rows(p) if _f(t.get("closed_at_ts")) >= a]
    print("PART 1 - today's closed trades in closed_trades_archive.jsonl (day since 05:30 IST): %d rows" % len(rows))
    if not rows:
        print("  none found. File exists: %s" % os.path.isfile(p))
        return
    seen, uniq, dup = set(), [], 0
    for t in rows:
        k = (t.get("id"), t.get("closed_at_ts"), t.get("symbol"))
        if k in seen:
            dup += 1
            continue
        seen.add(k)
        uniq.append(t)
    tot = sum(_f(t.get("pnl_usdt")) for t in uniq)
    live = [t for t in uniq if str(t.get("source") or "").lower() == "live"]
    btc = [t for t in uniq if str(t.get("symbol") or "").upper() == "BTCUSDT"]
    old = [t for t in uniq if not t.get("fee_applied") and not t.get("fee_est") and str(t.get("source") or "").lower() != "live"]
    print("  duplicates dropped: %d | all trades: %d, sum %+.2f USDT" % (dup, len(uniq), tot))
    print("  Dashboard way (no BTC trade): sum %+.2f USDT" % (tot - sum(_f(t.get("pnl_usdt")) for t in btc)))
    print("  BTC trades: %d, sum %+.2f USDT (the Brain page counts them, the Dashboard does not)" % (len(btc), sum(_f(t.get("pnl_usdt")) for t in btc)))
    print("  live-source trades inside this file: %d" % len(live))
    est = sum(_f(t.get("invest_usdt")) * 1.0 / 100.0 for t in old)
    print("  old trades with no fee inside: %d (the Brain page subtracts about %.2f USDT as an estimate)" % (len(old), est))
    by = {}
    for t in uniq:
        s = str(t.get("source") or "?")
        c = by.setdefault(s, [0, 0.0])
        c[0] += 1
        c[1] += _f(t.get("pnl_usdt"))
    print("  by source (the Main book also holds Sniper trades):")
    for s, (n, v) in sorted(by.items(), key=lambda x: -x[1][0]):
        print("    %-14s %4d trades  %+9.2f USDT" % (s, n, v))
    ts = os.path.join(d, "trades.json")
    if os.path.isfile(ts):
        try:
            j = json.load(open(ts))
            print("  trades.json says today_pnl_usdt = %s (what the Dashboard shows)" % (j.get("today_pnl_usdt") if isinstance(j, dict) else "?"))
        except Exception as e:
            print("  trades.json not readable: %s" % str(e)[:80])


def part2(d):
    print("\nPART 2 - Brain: why no trade today (real Brain file)")
    try:
        import v2_bt_why as W
        r = W.build(d)
        print("  state %s | total %s taken %s waited %s skipped %s no_opinion %s open %s" % (r["state"], r["total"], r["taken"], r["waited"], r["skipped"], r["no_opinion"], r["open_now"]))
        for l in r["lines"]:
            print("  " + l)
        for x in r["reasons"]:
            print("   - %s x%d: %s" % (x["decision"], x["n"], x["reason"]))
    except Exception as e:
        print("  FAILED: %s" % e)


def part3(d):
    print("\nPART 3 - Sniper: winners vs losers (real past trades)")
    try:
        import owl_sniper_winners as W
        r = W.build(d)
        print("  state %s | studied %s trades (%s won, %s lost)" % (r["state"], r.get("n"), r.get("wins"), r.get("losses")))
        for l in r["lines"]:
            print("  " + l)
        for x in r.get("features", []):
            print("   - %s (gap %+.2f sd)" % (x["text"], x["gap_sd"]))
    except Exception as e:
        print("  FAILED: %s" % e)


def _find_data_dir():
    """Same pick as tools/owl_auto.sh: OWL_DATA_DIR, else the folder saved in ~/.owl_data_dir, else ~/storage/shared/owl_data (Internal storage/owl_data), else ~/owl_data."""
    home = os.path.expanduser("~")
    env = os.environ.get("OWL_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    try:
        saved = open(os.path.join(home, ".owl_data_dir")).read().strip()
        if saved and os.path.isdir(saved):
            return saved
    except Exception:
        pass
    for c in (os.path.join(home, "storage", "shared", "owl_data"), os.path.join(home, "owl_data")):
        if os.path.isdir(c):
            return c
    return "."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    a = ap.parse_args()
    d = a.data
    if not d:
        d = _find_data_dir()
    print("data folder: %s\n" % os.path.realpath(d))
    part1(d, int(time.time()))
    part2(d)
    part3(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
