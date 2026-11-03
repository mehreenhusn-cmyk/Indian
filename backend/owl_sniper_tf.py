"""owl_sniper_tf.py - OwlSniper Round 18: the 15m timeframe (backend, plain python, read-only, pure functions, no network, no file writes).

WHY THIS FILE EXISTS: the candle collector (v2_candles.py) only saves 3m and 5m candles. There are NO saved 15m candles.
So the 15m series is BUILT from real saved 5m candles, never invented and never fetched here:
  one 15m candle = exactly three 5m candles that start on a quarter-hour (:00 :15 :30 :45) and follow each other with NO gap
  open = open of the first, high = highest high, low = lowest low, close = close of the last, volume = sum.
A 15m bucket with fewer than three real 5m candles is DROPPED (the newest, still-forming bucket is never used), so nothing looks ahead.
Callers pass ONE gap-free run of clean 5m candles (see owl_sniper_feed.newest_run); this file never bridges a gap.

PART 28 (FILE 19) ADDS the nearest HIGHER timeframe (MASTER_PROMPT 4.9): HIGHER table (3m>5m, 5m>15m, 15m>30m, 30m / 45m>1h, 1h>2h, 2h>4h), htf_candles() (30m, 1h, 2h, 4h, ... built from the same real 5m candles, complete buckets only)\nand weight_of() (the prior weight: nearest higher TF 1.0, the next one 0.25, anything further 0.0). SUPPORTED, files() and aggregate() are UNCHANGED, so nothing else in OwlSniper changes: 30m / 1h / 2h / 4h exist ONLY as context candles, never as a trading interval.\n\nRun the self-check (no data needed): python3 backend/owl_sniper_tf.py"""
import sys

VERSION = "owl_sniper_tf 2 (Round 18 + Part 28)"
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


def _buckets(run, k):
    """ONE gap-free run of 5m candles -> candles of k x 5m, same tuple shape. k == 1 returns the run unchanged. Only COMPLETE buckets that start on a multiple of the bucket span are kept (never filled in)."""
    st = STEP[BASE]
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


def aggregate(run, interval):
    """ONE gap-free run of 5m candles (open_ts, o, h, l, c, v), oldest first -> the candles of `interval`, same tuple shape.
    5m comes back unchanged. For 15m only COMPLETE quarter-hour buckets are kept."""
    return _buckets(run, FACTOR[check(interval)])


# ---------------------------------------------------------------- Part 28: the nearest HIGHER timeframe (context only)
HIGHER = {"3m": "5m", "5m": "15m", "15m": "30m", "30m": "1h", "45m": "1h", "1h": "2h", "2h": "4h"}      # MASTER_PROMPT 4.9
HTF_FACTOR = {"15m": 3, "30m": 6, "1h": 12, "2h": 24, "4h": 48}                                           # 5m candles in one higher candle
_ORDER = ("3m", "5m", "15m", "30m", "1h", "2h", "4h")


def higher_of(interval):
    """The nearest meaningful higher timeframe of a trading interval, or ValueError."""
    if interval not in HIGHER:
        raise ValueError("no higher timeframe is defined for %r" % (interval,))
    return HIGHER[interval]


def htf_candles(run, htf):
    """The candles of a higher timeframe (15m, 30m, 1h, 2h, 4h), built from ONE gap-free run of real 5m candles. Only complete buckets; the newest forming one is never used."""
    if htf not in HTF_FACTOR:
        raise ValueError("higher timeframe must be one of %s, not %r" % (sorted(HTF_FACTOR, key=_ORDER.index), htf))
    return _buckets(run, HTF_FACTOR[htf])


def weight_of(interval, htf):
    """PRIOR weight of a higher timeframe for a trading interval (before anything is learned): the nearest one 1.0, the next one 0.25, further away 0.0 (a 15m signal against 4h is ignored)."""
    if htf not in _ORDER or higher_of(interval) not in _ORDER:
        raise ValueError("unknown timeframe %r" % (htf,))
    gap = _ORDER.index(htf) - _ORDER.index(higher_of(interval))
    return 1.0 if gap == 0 else 0.25 if gap == 1 else 0.0


def _self_check():
    """Three tiny facts, printed. No test file is needed (owner rule: no tests); this only proves the maths on made-up numbers."""
    run = [(900 * 4 + 300 * j, 10 + j, 20 + j, 5 + j, 11 + j, 1.0) for j in range(7)]       # 7 candles starting on a quarter-hour
    a = aggregate(run, "15m")
    assert len(a) == 2 and a[0][0] == 3600 and a[0][1:] == (10, 22, 5, 13, 3.0), a           # 2 full buckets, the 7th candle is a forming bucket
    assert aggregate(run[1:], "15m")[0][0] == 3600 + 900                                        # a run that starts mid-bucket drops the first part
    assert aggregate(run[:2] + run[3:], "15m") == [] or aggregate(run[:2] + run[3:], "15m")[0][0] != 3600     # a hole kills its bucket
    assert aggregate(run, "5m") == run and files("5m")[1] == "v2_sniper_live.json"
    big = [(7200 * 5 + 300 * j, 10 + j, 20 + j, 5 + j, 11 + j, 1.0) for j in range(24)]           # 24 candles = two full 30m... and one 2h bucket
    h30, h2 = htf_candles(big, "30m"), htf_candles(big, "2h")
    assert len(h30) == 4 and h30[0][0] == 7200 * 5 and h30[0][1:] == (10, 25, 5, 16, 6.0), h30[0]      # 6 candles per 30m bucket
    assert len(h2) == 1 and h2[0][4] == 34 and htf_candles(big[1:], "2h") == []                         # a run that starts mid-bucket loses the first 2h bucket
    assert higher_of("5m") == "15m" and higher_of("45m") == "1h" and weight_of("5m", "15m") == 1.0 and weight_of("5m", "30m") == 0.25 and weight_of("15m", "4h") == 0.0
    print(VERSION, "self-check OK:", len(a), "buckets from", len(run), "candles")
    return 0


if __name__ == "__main__":
    sys.exit(_self_check())
