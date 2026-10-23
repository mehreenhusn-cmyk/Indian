#!/usr/bin/env python3
"""
z_scenarios.py - ONE-SHOT "which indicator combination gives the real signals?" test. Read-only, run by hand.

  cd backend && python3 z_scenarios.py 5m 7              # 5m candles, last 7 days, top-10 gainers + losers
  python3 z_scenarios.py 15m 14 BTCUSDT,ETHUSDT --lev 10 --fee 1.0

Idea: the bot enters on the EMA50 cross (main chart). Special Master adds two more opinions at that same candle:
  Z-Score : did the Z candle CLOSE cross its own EMA50 (the black candle in Special Master v6), is Z-EMA30 on the same side
  TSI     : is TSI on the right side of its signal line (histogram with the trade)
Every bot signal is replayed (same replay as filter_lab.py) and tagged with what these indicators said. Then each
combination ("main only", "main + Z black candle", "main + Z + TSI", ...) is scored on the OLDER 60% and the NEWER 40%
of the signals, fee included, so a combination only counts when it works in BOTH halves.
Limit: it only judges signals the bot already took (main-chart cross). A Z black candle with NO main cross is not covered.
Nothing here changes the bot. A replay is evidence, not a promise.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import filter_lab as FL

Z_FAST, Z_SLOW = 30, 50          # same defaults as Special Master v6 (EMA of the Z close value)
NEAR = 2                         # "just now" = the Z cross happened on the signal candle or up to 2 candles before
_CACHE = {}


def _z_emas(S):
    """EMA30 / EMA50 of the Z close series, cached per candle set (Z * 10 in Pine, a scale only: crosses are identical)."""
    key = id(S)
    if _CACHE.get("k") != key:
        from recovered_bot import ai_ind_features as F
        _CACHE.clear()
        _CACHE.update(k=key, f=F.ema(S["z"], Z_FAST), s=F.ema(S["z"], Z_SLOW))
    return _CACHE["f"], _CACHE["s"]


def _cross(z, e, j):
    """+1 = Z close crossed ABOVE e on candle j, -1 = crossed BELOW, 0 = no cross (Pine crossover / crossunder)."""
    if j < 1 or None in (z[j], z[j - 1], e[j], e[j - 1]):
        return 0
    if z[j - 1] <= e[j - 1] and z[j] > e[j]:
        return 1
    if z[j - 1] >= e[j - 1] and z[j] < e[j]:
        return -1
    return 0


def enrich(r, S, i, lev, fee):
    """EXTRA_ENRICH hook: adds r['zx'] = what the Z-Score said at the bot's signal candle i (read-only maths)."""
    zf, zs = _z_emas(S)
    z = S["z"]
    if None in (z[i], zf[i], zs[i]):
        return
    r["zx"] = {"x0": _cross(z, zs, i),                                          # Z close vs EMA50 cross on the signal candle
               "xn": next((c for c in (_cross(z, zs, j) for j in range(i, i - NEAR - 1, -1)) if c), 0),   # latest cross within NEAR
               "side": 1 if z[i] > zs[i] else -1,                                # Z close above/below EMA50 now
               "ee": 1 if zf[i] > zs[i] else -1}                                 # EMA30 above/below EMA50 (cloud green/red)


def _d(r):
    return 1 if r["a"] == "BUY" else -1


def _has(r):
    return r.get("zx") is not None


def _z_now(r):   return _has(r) and r["zx"]["x0"] == _d(r)                      # black candle ON the signal candle
def _z_near(r):  return _has(r) and r["zx"]["xn"] == _d(r)                      # black candle within the last 3 candles
def _z_side(r):  return _has(r) and r["zx"]["side"] == _d(r)                    # Z close on the trade side of EMA50
def _z_cloud(r): return _has(r) and r["zx"]["ee"] == _d(r)                      # cloud colour with the trade
def _z_trend(r): return _z_side(r) and _z_cloud(r)                               # both: Z above EMA50 and EMA30 above EMA50
def _tsi(r):     return FL._g_tsi_line(r) and r["ind"].get("dif") is not None   # TSI with the trade


SCENARIOS = [
    ("Z black candle on the SAME candle as the bot signal", _z_now),
    ("Z black candle within the last 3 candles", _z_near),
    ("Z close on the trade side of its EMA50", _z_side),
    ("Z cloud colour with the trade (EMA30 vs EMA50)", _z_cloud),
    ("Z trend: close AND EMA30 both on the trade side", _z_trend),
    ("TSI on the right side of its signal line", _tsi),
    ("Z black candle (3 candles) + TSI with the trade", lambda r: _z_near(r) and _tsi(r)),
    ("Z trend + TSI with the trade", lambda r: _z_trend(r) and _tsi(r)),
    ("Z black candle (3 candles) + Z trend + TSI (all three)", lambda r: _z_near(r) and _z_trend(r) and _tsi(r)),
    ("Z black candle (3 candles) + room (long below Z 0, short above Z 0)", lambda r: _z_near(r) and FL._g_z_room(r)),
]


def _votes(r):
    """how many of the 3 Special Master opinions agree with the bot signal (0-3). Main chart is always 1 more."""
    return int(_z_near(r)) + int(_z_trend(r)) + int(_tsi(r))


def analyse(rows):
    rows = [r for r in rows if _has(r)]
    old, new = FL.split_rows(rows)
    rep = {"n": len(rows), "base": FL._stat(rows), "old": FL._stat(old), "new": FL._stat(new)}
    rep["scen"] = [(n, FL.judge(old, new, fn)) for n, fn in SCENARIOS]
    rep["votes"] = FL.table_by(rows, lambda r: f"{_votes(r)} of 3 Special Master opinions agree (+ main chart)")
    rep["by_side"] = FL.table_by(rows, lambda r: ("BUY" if r["a"] == "BUY" else "SELL"))
    return rep


def _pf(rs):
    w = sum(r["net"] for r in rs if r["net"] > 0)
    l = -sum(r["net"] for r in rs if r["net"] < 0)
    return w / l if l > 0 else 0.0


def text_report(rep, tf, days, lev, fee):
    b = rep["base"]
    L = [f"Z-SCORE SCENARIO TEST  {tf}, {days} days, {lev:g}x, fee {fee:g}% ROI per trade",
         f"Bot signals judged: {rep['n']}  (older {rep['old']['n']} / newer {rep['new']['n']})",
         FL._line("Bot as it is today", b), "",
         "SHORT ANSWER (combinations that kept the better trades in BOTH halves):"]
    good = [n for n, j in rep["scen"] if j["verdict"].startswith("CONFIRMED")]
    bad = [n for n, j in rep["scen"] if j["verdict"].startswith("HARMFUL")]
    L += [f"  + {n}" for n in good] or ["  none confirmed - no combination clearly beat the plain bot on both halves"]
    if bad:
        L += ["  these made it WORSE in both halves:"] + [f"  - {n}" for n in bad]
    L += ["", "HOW MANY OPINIONS AGREE (more agree = better?):"]
    for k in sorted(rep["votes"]):
        L.append(FL._line(k, rep["votes"][k]))
    L += ["", "EVERY COMBINATION (kept = signals you would still take):"] + FL._gate_lines(rep["scen"])
    L += ["", "Reading guide: CONFIRMED = skipped trades were clearly worse in older AND newer signals. 'not enough data' = too few skipped",
          "trades to judge, run more days. Fee is already inside every number."]
    return "\n".join(L)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i].startswith("--")}
    tf = args[0] if args else "5m"
    days = int(args[1]) if len(args) > 1 else 7
    lev, fee = float(opts.get("--lev", 10)), float(opts.get("--fee", 1.0))
    if tf not in FL.TF_MS:
        print("timeframe must be 3m, 5m or 15m")
        return 1
    coins = args[2].split(",") if len(args) > 2 else FL.default_coins()
    FL.EXTRA_ENRICH = enrich
    try:
        rows = FL.collect(tf, days, coins, lev, fee)
    finally:
        FL.EXTRA_ENRICH = None
    if len([r for r in rows if _has(r)]) < 30:
        print(f"Only {len(rows)} finished signals - too few. Try more days or more coins.")
        return 1
    txt = text_report(analyse(rows), tf, days, lev, fee)
    print("\n" + txt)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"z_scenarios_{tf}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(txt)
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
