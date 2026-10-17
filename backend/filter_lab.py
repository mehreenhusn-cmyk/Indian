#!/usr/bin/env python3
"""
filter_lab.py - ONE-SHOT "which signals should the bot skip?" test. Read-only, run by hand, uses no CPU afterwards.

  cd backend && python3 filter_lab.py 5m 7            # 5m candles, last 7 days, top-10 gainers + top-10 losers
  python3 filter_lab.py 15m 14 BTCUSDT,ETHUSDT        # own coin list
  python3 filter_lab.py 5m 7 --lev 10 --fee 1.0       # leverage and fee (ROI % per trade)

What it does
  1. Downloads public Binance futures candles (no key, no orders).
  2. Replays the bot's OWN strategy (strategy.ABCDStrategy, untouched): EMA50 cross, SL = signal candle extreme,
     TP1-4 from SD bands, SL -> entry after TP1, exit at TP4 / SL / opposite cross (rule "T4" = the live bot).
  3. Labels every signal with both indicators (ai_ind_features: Special 13 SD zone, Special Master TSI + Z).
  4. Tests simple "skip this signal if ..." gates, each on the OLDER 60% and the NEWER 40% of the signals.
     A gate is CONFIRMED only when the skipped trades were clearly worse than the kept ones in BOTH halves.
Nothing here changes the bot. Results are a replay (no slippage), so treat them as evidence, not a promise.
"""
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TF_MS = {"3m": 180_000, "5m": 300_000, "15m": 900_000}
MIN_SKIP_OLD, MIN_SKIP_NEW = 15, 6          # a gate needs at least this many skipped trades per half to be judged
Z_OLD, Z_NEW = 2.0, 1.3                     # how clearly the skipped group must be worse (Welch z), old / new half
OLD_SHARE = 0.60


# ---------------------------------------------------------------- numbers
def _mean(v):
    return sum(v) / len(v) if v else 0.0


def _welch_z(a, b):
    """z of (mean(a) - mean(b)); a = kept, b = skipped. Positive = kept better."""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    ma, mb = _mean(a), _mean(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    se = math.sqrt(va / len(a) + vb / len(b))
    return (ma - mb) / se if se > 0 else 0.0


def _stat(rs):
    n = len(rs)
    if not n:
        return {"n": 0, "net": 0.0, "avg": 0.0, "win": 0.0}
    net = sum(r["net"] for r in rs)
    return {"n": n, "net": round(net, 1), "avg": round(net / n, 2),
            "win": round(100.0 * sum(1 for r in rs if r["net"] > 0) / n, 1)}


# ---------------------------------------------------------------- gates (each: row -> True = KEEP the signal)
def _buy(r):
    return r["a"] == "BUY"


def _g_z_user(r):          # the rule typed in TradingView: no long below Z 0, no short above Z 0
    z = r["ind"].get("z")
    return z is None or (z >= 0 if _buy(r) else z <= 0)


def _g_z_room(r):          # the opposite: enter only where the trade has room (long below Z 0, short above)
    z = r["ind"].get("z")
    return z is None or (z <= 0 if _buy(r) else z >= 0)


def _g_z_moving(r):        # Z moved WITH the trade over the last 3 candles
    d = r["ind"].get("zd3")
    return d is None or (d > 0 if _buy(r) else d < 0)


def _g_tsi_line(r):        # TSI on the right side of its signal line (histogram with the trade)
    d = r["ind"].get("dif")
    return d is None or (d > 0 if _buy(r) else d < 0)


def _g_tsi_side(r):        # TSI itself positive for longs / negative for shorts
    t = r["ind"].get("tsi")
    return t is None or (t > 0 if _buy(r) else t < 0)


def _g_reward(r):          # distance to TP1 at least as big as the distance to the SL
    risk = abs(r["e"] - r["sl"])
    return risk > 0 and abs(r["tp"][0] - r["e"]) >= risk


def _g_reward_half(r):     # distance to TP1 at least half of the SL distance
    risk = abs(r["e"] - r["sl"])
    return risk > 0 and abs(r["tp"][0] - r["e"]) >= 0.5 * risk


def _g_chop(r):            # at most 2 EMA50 crosses in the last 20 candles (1 = clean trend start)
    n = (r.get("sig") or {}).get("cross_n")
    return n is None or n <= 2


def _g_no_wick(r):         # SL (signal candle extreme) not tiny: at least 0.25% of price
    return abs(r["e"] - r["sl"]) / r["e"] * 100.0 >= 0.25


GATES = [
    ("Your Z rule (no long if Z<0, no short if Z>0)", _g_z_user),
    ("Opposite Z rule (long only if Z<0, short only if Z>0)", _g_z_room),
    ("Z moving with the trade (last 3 candles)", _g_z_moving),
    ("TSI on the right side of its signal line", _g_tsi_line),
    ("TSI above 0 for long / below 0 for short", _g_tsi_side),
    ("Reward: TP1 distance >= SL distance", _g_reward),
    ("Reward: TP1 distance >= half the SL distance", _g_reward_half),
    ("Chop: at most 2 EMA50 crosses in last 20 candles", _g_chop),
    ("SL distance at least 0.25% of price", _g_no_wick),
]


def _cooldown_keep(rows, candles_gap):
    """keep flag per row id: skip a signal if the same coin gave a signal less than `candles_gap` candles earlier."""
    keep, last = {}, {}
    for r in sorted(rows, key=lambda x: x["t"]):
        prev = last.get(r["s"])
        step = TF_MS[r["tf"]]
        keep[id(r)] = prev is None or (r["t"] - prev) >= candles_gap * step
        last[r["s"]] = r["t"]
    return keep


# ---------------------------------------------------------------- judging
def judge(old, new, keep_fn):
    ko = [r for r in old if keep_fn(r)]
    so = [r for r in old if not keep_fn(r)]
    kn = [r for r in new if keep_fn(r)]
    sn = [r for r in new if not keep_fn(r)]
    out = {"old": {"kept": _stat(ko), "skipped": _stat(so)}, "new": {"kept": _stat(kn), "skipped": _stat(sn)}}
    zo = _welch_z([r["net"] for r in ko], [r["net"] for r in so])
    zn = _welch_z([r["net"] for r in kn], [r["net"] for r in sn])
    out["z_old"], out["z_new"] = round(zo, 2), round(zn, 2)
    if len(so) < MIN_SKIP_OLD or len(sn) < MIN_SKIP_NEW:
        out["verdict"] = "not enough data"
    elif zo >= Z_OLD and zn >= Z_NEW:
        out["verdict"] = "CONFIRMED: skipped trades were worse in both halves"
    elif zo <= -Z_OLD and zn <= -Z_NEW:
        out["verdict"] = "HARMFUL: skipped trades were better in both halves"
    else:
        out["verdict"] = "not confirmed (no clear difference on both halves)"
    out["saved_old"] = round(-out["old"]["skipped"]["net"], 1)
    out["saved_new"] = round(-out["new"]["skipped"]["net"], 1)
    return out


def split_rows(rows):
    rows = sorted(rows, key=lambda r: r["t"])
    cut = int(len(rows) * OLD_SHARE)
    return rows[:cut], rows[cut:]


def table_by(rows, keyfn):
    groups = {}
    for r in rows:
        k = keyfn(r)
        if k is not None:
            groups.setdefault(k, []).append(r)
    return {k: _stat(v) for k, v in groups.items()}


def analyse(rows):
    """rows: replay rows with r['net'] already set. Returns dict with everything the text report prints."""
    old, new = split_rows(rows)
    rep = {"n": len(rows), "n_old": len(old), "n_new": len(new), "baseline": {"old": _stat(old), "new": _stat(new), "all": _stat(rows)}}
    res = []
    for name, fn in GATES:
        res.append((name, judge(old, new, fn)))
    for gap in (3, 6, 12):
        keep = _cooldown_keep(rows, gap)
        res.append((f"Cooldown: skip if same coin signalled < {gap} candles ago", judge(old, new, lambda r, k=keep: k[id(r)])))
    combo_fns = [_g_chop, _g_tsi_line, _g_reward_half]
    res.append(("COMBO: chop + TSI line + reward>=0.5", judge(old, new, lambda r: all(f(r) for f in combo_fns))))
    rep["gates"] = res
    rep["by_zone"] = table_by(rows, lambda r: (r.get("sig") or {}).get("zone"))
    rep["by_side"] = table_by(rows, lambda r: r["a"])
    rep["by_z_band"] = table_by(rows, lambda r: None if r["ind"].get("z") is None else
                                ("Z<-2" if r["ind"]["z"] < -2 else "Z -2..-1" if r["ind"]["z"] < -1 else "Z -1..0" if r["ind"]["z"] < 0
                                 else "Z 0..1" if r["ind"]["z"] < 1 else "Z 1..2" if r["ind"]["z"] < 2 else "Z>2"))
    rep["by_tsi_line"] = table_by(rows, lambda r: None if r["ind"].get("dif") is None else
                                  ("TSI with trade" if _g_tsi_line(r) else "TSI against trade"))
    rep["by_cross_n"] = table_by(rows, lambda r: None if (r.get("sig") or {}).get("cross_n") is None else
                                 ("1 cross (clean)" if r["sig"]["cross_n"] <= 1 else "2 crosses" if r["sig"]["cross_n"] == 2 else "3+ crosses (chop)"))
    return rep


def _line(name, s):
    return f"  {name}: {s['n']} trades, net {s['net']:+.1f}, avg {s['avg']:+.2f}, win {s['win']:.0f}%"


def text_report(rep, tf, days, lev, fee):
    L = [f"FILTER LAB - {tf} candles, last {days} days, leverage {lev}x, fee {fee}% ROI per trade (net = ROI % after fee)",
         f"Signals replayed: {rep['n']} (older {rep['n_old']} / newer {rep['n_new']})", "",
         "BOT AS IT IS (no filter):",
         _line("older ", rep["baseline"]["old"]), _line("newer ", rep["baseline"]["new"]), "",
         "FILTERS - 'skipped' = trades the filter would have removed. Good filter: skipped trades lose money in BOTH halves.", ""]
    for name, j in rep["gates"]:
        L.append(f"* {name}")
        L.append(f"    {j['verdict']}")
        for half in ("old", "new"):
            k, s = j[half]["kept"], j[half]["skipped"]
            L.append(f"    {half:3s}: kept {k['n']} (net {k['net']:+.0f}, avg {k['avg']:+.2f}) | skipped {s['n']} (net {s['net']:+.0f}, avg {s['avg']:+.2f})")
        L.append(f"    P&L change if applied: older {j['saved_old']:+.0f}, newer {j['saved_new']:+.0f}")
    for title, key in (("BY SD ZONE OF ENTRY (Special 13)", "by_zone"), ("BY Z-SCORE AT ENTRY", "by_z_band"),
                       ("TSI vs ITS SIGNAL LINE", "by_tsi_line"), ("EMA50 CROSSES IN LAST 20 CANDLES", "by_cross_n"), ("BY SIDE", "by_side")):
        L += ["", title]
        for k, s in sorted(rep[key].items(), key=lambda kv: kv[1]["avg"]):
            L.append(_line(k, s))
    L += ["", "Honest limits: replay, no slippage; ~12 filters tested on the same data, so one 'CONFIRMED' can still be luck - keep it on paper "
              "for a few days before using it. Not enough data = do not act on it."]
    return "\n".join(L)


# ---------------------------------------------------------------- data
def collect(tf, days, coins, lev, fee, log=print):
    from recovered_bot import ai_shadow_lab as LAB
    rows = []
    start = int(time.time() * 1000) - days * 86_400_000 - 450 * TF_MS[tf]   # 450 extra candles = indicator warm-up
    since = int(time.time() * 1000) - days * 86_400_000
    for n, sym in enumerate(coins, 1):
        candles = LAB._fetch_range(sym, tf, start)
        if not candles:
            log(f"[{n}/{len(coins)}] {sym}: no candles (skipped)")
            continue
        got = LAB._process(sym, tf, candles, None, since)
        for r in got:
            o = (r.get("o") or {}).get("T4")
            if not o or o[1] == "OPEN":
                continue
            r["net"] = o[0] * lev - fee
            rows.append(r)
        log(f"[{n}/{len(coins)}] {sym}: {len(got)} signals")
    return rows


def default_coins(log=print):
    from recovered_bot import binance_client
    data = binance_client._get("/fapi/v1/ticker/24hr")
    usdt = [d for d in data if str(d.get("symbol", "")).endswith("USDT") and "_" not in d["symbol"]]
    usdt.sort(key=lambda d: float(d.get("priceChangePercent") or 0.0))
    coins = [d["symbol"] for d in usdt[-10:]] + [d["symbol"] for d in usdt[:10]]
    log("Coins (today's top-10 gainers + top-10 losers): " + ", ".join(coins))
    return coins


# ---------------------------------------------------------------- background job (for the browser link /api/filter_lab)
import threading

_JOBS = {}          # tf -> {"state": "running"/"done"/"error", "text": str, "progress": str, "t": float}


def _job(tf, days, lev, fee):
    j = _JOBS[tf]
    try:
        def log(msg):
            j["progress"] = msg
        coins = default_coins(log)
        rows = collect(tf, days, coins, lev, fee, log)
        if len(rows) < 30:
            j["text"] = f"Only {len(rows)} finished signals - too few. Try again later or use more days."
        else:
            j["text"] = text_report(analyse(rows), tf, days, lev, fee)
        j["state"] = "done"
    except Exception as e:
        j["state"] = "error"
        j["text"] = f"Filter Lab failed: {type(e).__name__}: {e}"
    j["t"] = time.time()


def job_status(tf="5m", days=7, lev=10.0, fee=1.0, restart=False):
    """Starts the replay in its own thread if it is not running (or restart=True) and returns plain text for the browser."""
    if tf not in TF_MS:
        return "timeframe must be 3m, 5m or 15m"
    j = _JOBS.get(tf)
    if j is None or restart and j["state"] != "running":
        j = _JOBS[tf] = {"state": "running", "text": "", "progress": "starting...", "t": time.time()}
        threading.Thread(target=_job, args=(tf, int(days), float(lev), float(fee)), daemon=True, name="filter_lab").start()
    if j["state"] == "running":
        return (f"FILTER LAB {tf}: running ({j['progress']}).\nIt downloads candles one coin at a time, about 1-3 minutes.\n"
                f"Reload this page in a minute.")
    age = int((time.time() - j["t"]) / 60)
    return j["text"] + f"\n\n(result computed {age} min ago; add &restart=1 to the link to run it again)"


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i].startswith("--")}
    tf = args[0] if args else "5m"
    days = int(args[1]) if len(args) > 1 else 7
    lev = float(opts.get("--lev", 10))
    fee = float(opts.get("--fee", 1.0))
    if tf not in TF_MS:
        print("timeframe must be 3m, 5m or 15m")
        return 1
    coins = args[2].split(",") if len(args) > 2 else default_coins()
    rows = collect(tf, days, coins, lev, fee)
    if len(rows) < 30:
        print(f"Only {len(rows)} finished signals - too few. Try more days or more coins.")
        return 1
    rep = analyse(rows)
    txt = text_report(rep, tf, days, lev, fee)
    print("\n" + txt)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"filter_lab_{tf}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(txt)
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
