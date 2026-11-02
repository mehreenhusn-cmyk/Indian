"""owl_sniper_tf.py - OwlSniper Round 18: the 15m timeframe (backend, plain python, read-only, pure functions, no network, no file writes).

WHY THIS FILE EXISTS: the candle collector (v2_candles.py) only saves 3m and 5m candles. There are NO saved 15m candles.
So the 15m series is BUILT from real saved 5m candles, never invented and never fetched here:
  one 15m candle = exactly three 5m candles that start on a quarter-hour (:00 :15 :30 :45) and follow each other with NO gap
  open = open of the first, high = highest high, low = lowest low, close = close of the last, volume = sum.
A 15m bucket with fewer than three real 5m candles is DROPPED (the newest, still-forming bucket is never used), so nothing looks ahead.
Callers pass ONE gap-free run of clean 5m candles (see owl_sniper_feed.newest_run); this file never bridges a gap.

Run the self-check (no data needed): python3 backend/owl_sniper_tf.py"""
import sys

VERSION = "owl_sniper_tf 1 (Round 18)"
BASE = "5m"                                   # the only interval that is really saved and used for 15m
STEP = {"5m": 300, "15m": 900}                # seconds per candle
FACTOR = {"5m": 1, "15m": 3}                  # how many 5m candles make one candle
LIVE_MAX_AGE = {"5m": 270, "15m": 810}        # a scan file older than this is refreshed (a little under one candle)
SUPPORTED = ("5m", "15m")


def check(interval):
    """The interval, or ValueError. Only 5m and 15m exist for OwlSniper."""
    if interval not in SUPPORTED:
        raise ValueError("OwlSniper interval must be 5m or 15m, not %r" % (interval,))
    return interval


def base(interval):
    """The interval whose candles are really saved in the market store (always 5m)."""
    check(interval)
    return BASE


def step(interval):
    return STEP[check(interval)]


def tail_rows(interval, n):
    """How many 5m rows to read so that `n` candles of `interval` come out (a spare bucket at each end)."""
    return int(n) * FACTOR[check(interval)] + 2 * FACTOR[interval]


def files(interval):
    """(model file, live file, kick file). 5m keeps the OLD names, so api/sniper.py and the app keep working untouched."""
    check(interval)
    if interval == "5m":
        return "v2_sniper_model.json", "v2_sniper_live.json", "v2_sniper_kick"
    return "v2_sniper_model_15m.json", "v2_sniper_live_15m.json", "v2_sniper_kick_15m"


def aggregate(run, interval):
    """ONE gap-free run of 5m candles (open_ts, o, h, l, c, v), oldest first -> the candles of `interval`, same tuple shape.
    5m comes back unchanged. For 15m only COMPLETE quarter-hour buckets are kept."""
    check(interval)
    k, st = FACTOR[interval], STEP[BASE]
    if k == 1:
        return list(run)
    span = st * k
    out, i, n = [], 0, len(run)
    while i < n:
        ts = run[i][0]
        if ts % span != 0:                    # not the start of a bucket: skip until one starts (the first part is incomplete)
            i += 1
            continue
        part = run[i:i + k]
        if len(part) < k or any(part[j][0] != ts + j * st for j in range(k)):
            i += 1                            # incomplete bucket (end of run or a hole): never filled in
            continue
        out.append((ts, part[0][1], max(x[2] for x in part), min(x[3] for x in part), part[-1][4], sum(x[5] for x in part)))
        i += k
    return out


def _self_check():
    """Three tiny facts, printed. No test file is needed (owner rule: no tests); this only proves the maths on made-up numbers."""
    run = [(900 * 4 + 300 * j, 10 + j, 20 + j, 5 + j, 11 + j, 1.0) for j in range(7)]       # 7 candles starting on a quarter-hour
    a = aggregate(run, "15m")
    assert len(a) == 2 and a[0][0] == 3600 and a[0][1:] == (10, 22, 5, 13, 3.0), a           # 2 full buckets, the 7th candle is a forming bucket
    assert aggregate(run[1:], "15m")[0][0] == 3600 + 900                                        # a run that starts mid-bucket drops the first part
    assert aggregate(run[:2] + run[3:], "15m") == [] or aggregate(run[:2] + run[3:], "15m")[0][0] != 3600     # a hole kills its bucket
    assert aggregate(run, "5m") == run and files("5m")[1] == "v2_sniper_live.json"
    print(VERSION, "self-check OK:", len(a), "buckets from", len(run), "candles")
    return 0


if __name__ == "__main__":
    sys.exit(_self_check())
