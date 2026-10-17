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
  5. NEW: tests a WIDER stop-loss (previous candle, last 3 candles, last-10 swing, ATR) and "after TP1 move SL to entry + fee buffer",
     on the SAME signals (only the SL changes, never tighter than today), older vs newer half, fee included.
  6. NEW: Bollinger Band (20, 2) filters as their own section: squeeze (sideways), price side of the middle band, stretched, expanding.
  7. NEW: "direction check" - after the bot's SL was hit, did price still reach TP1? (SL too tight vs direction really wrong)
  8. NEW: every filter shows "loss avoided" and "profit missed", so you see what it saves and what it costs.
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



# ---------------------------------------------------------------- Bollinger Band gates (row -> True = KEEP)
def _bbt(r):
    """price position inside the band seen from the trade: 0 = lower band for a long, 1 = upper band; short is mirrored."""
    b = r.get("bb")
    if not b or b.get("pb") is None:
        return None
    return b["pb"] if _buy(r) else 1.0 - b["pb"]


def _g_bb_squeeze(r):      # skip when the bands are in the narrowest quarter of the last 100 candles (sideways)
    b = r.get("bb")
    return b is None or b.get("rk") is None or b["rk"] >= 25.0


def _g_bb_side(r):         # price on the trade's side of the middle band (long above, short below)
    t = _bbt(r)
    return t is None or t > 0.5


def _g_bb_not_late(r):     # skip when price is already outside the band in the trade's direction (late entry)
    t = _bbt(r)
    return t is None or t <= 1.0


def _g_bb_expanding(r):    # bands are wider than 5 candles ago (volatility waking up)
    b = r.get("bb")
    return b is None or b.get("exp") is None or b["exp"] >= 1.0


BB_GATES = [
    ("BB squeeze: skip if band width is in the narrowest 25% of last 100 candles", _g_bb_squeeze),
    ("BB side: long only above the middle band, short only below it", _g_bb_side),
    ("BB late: skip if price is already outside the band in the trade's direction", _g_bb_not_late),
    ("BB expanding: band width now >= 5 candles ago", _g_bb_expanding),
]


def bb_series(S, n=20):
    """Bollinger (n, 2 SD) from closes: band width in % of the middle line, and %B (0 = lower band, 1 = upper band)."""
    c = S["c"]
    N = len(c)
    ref = c[0] if N else 0.0
    p1, p2 = [0.0] * (N + 1), [0.0] * (N + 1)
    for i in range(N):
        d = c[i] - ref
        p1[i + 1] = p1[i] + d
        p2[i + 1] = p2[i] + d * d
    w, pb = [None] * N, [None] * N
    for i in range(n - 1, N):
        s1, s2 = p1[i + 1] - p1[i + 1 - n], p2[i + 1] - p2[i + 1 - n]
        m = s1 / n
        sd = math.sqrt(max(s2 / n - m * m, 0.0))
        mean = m + ref
        if mean > 0 and sd > 0:
            w[i] = 4.0 * sd / mean * 100.0
            pb[i] = (c[i] - (mean - 2.0 * sd)) / (4.0 * sd)
    return w, pb


def bb_info(w, pb, i):
    if i >= len(w) or w[i] is None:
        return None
    win = [x for x in w[max(0, i - 99):i + 1] if x is not None]
    rk = 100.0 * sum(1 for x in win if x <= w[i]) / len(win)
    prev = w[i - 5] if i >= 5 else None
    return {"w": round(w[i], 3), "rk": round(rk, 1), "pb": round(pb[i], 3), "exp": round(w[i] / prev, 3) if prev else None}


# ---------------------------------------------------------------- stop-loss variants (same signals, only the SL changes)
MAX_FWD = 300                 # same as ai_shadow_lab.MAX_FWD (candles a simulated trade may run)
BARS_AFTER = 30               # direction check: candles after the SL exit in which TP1 may still be touched
SL_NAMES = [("base", "SL = signal candle extreme (bot today)"),
            ("prev1", "SL = signal OR previous candle extreme, the wider one"),
            ("prev3", "SL = widest extreme of the last 3 candles"),
            ("swing10", "SL = extreme of the last 10 candles"),
            ("atr15", "SL at least 1.5 x ATR(14) from entry"),
            ("atr2", "SL at least 2 x ATR(14) from entry")]
BE_NAMES = {"be0": "after TP1: SL to entry (bot today)", "bef": "after TP1: SL to entry + fee buffer"}
MIN_PAIR_OLD, MIN_PAIR_NEW = 30, 15


def _atr(S, i, n=14):
    h, l, c = S["h"], S["l"], S["c"]
    if i < n:
        return None
    return sum(max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])) for k in range(i - n + 1, i + 1)) / n


def sl_levels(S, i, is_long, entry, base_sl):
    """SL price per variant. A variant is never TIGHTER than the bot's own SL."""
    h, l = S["h"], S["l"]

    def wider(x):
        return min(base_sl, x) if is_long else max(base_sl, x)

    def ext(a):
        return min(l[i - a + 1:i + 1]) if is_long else max(h[i - a + 1:i + 1])

    out = {"base": base_sl, "prev1": wider(ext(2)), "prev3": wider(ext(3)), "swing10": wider(ext(10))}
    a = _atr(S, i)
    if a:
        out["atr15"] = wider(entry - 1.5 * a if is_long else entry + 1.5 * a)
        out["atr2"] = wider(entry - 2.0 * a if is_long else entry + 2.0 * a)
    return out


def sim_trade(S, i, is_long, entry, sl, tp1, tp4, be_buf_pct=0.0):
    """The bot's live rule (T4: target TP4, SL -> entry after TP1, opposite EMA50 cross exits) with a chosen SL.
    be_buf_pct > 0 moves the SL to entry + that % (price) instead of entry. Returns [ret % price move, why, bars]."""
    h, l, c, n = S["h"], S["l"], S["c"], S["n"]
    end = min(n - 1, i + MAX_FWD)
    opp = S["xdn"] if is_long else S["xup"]
    be_px = entry * (1 + be_buf_pct / 100.0) if is_long else entry * (1 - be_buf_pct / 100.0)
    if (is_long and be_px >= tp1) or (not is_long and be_px <= tp1):
        be_px = entry
    cur, be, got = sl, False, None
    for j in range(i + 1, end + 1):
        hh, ll = h[j], l[j]
        if (ll <= cur) if is_long else (hh >= cur):
            got = (cur, "BE" if be else "SL", j - i)
            break
        if (hh >= tp4) if is_long else (ll <= tp4):
            got = (tp4, "TP", j - i)
            break
        if opp[j]:
            got = (c[j], "REV", j - i)
            break
        if not be and ((hh >= tp1) if is_long else (ll <= tp1)) and ((be_px > cur) if is_long else (be_px < cur)):
            cur, be = be_px, True              # applies from the NEXT candle
    if got is None:
        got = (c[end], "TIMEOUT", end - i) if end - i >= MAX_FWD else (c[end] if end > i else entry, "OPEN", max(end - i, 0))
    px, why, bars = got
    return [(px - entry) / entry * 100.0 * (1.0 if is_long else -1.0), why, bars]


def tp1_after_exit(S, i, is_long, tp1, exit_bar):
    """True/False: did price touch TP1 within BARS_AFTER candles after the exit candle? None = not enough candles."""
    j0, j1 = i + exit_bar + 1, min(S["n"] - 1, i + exit_bar + BARS_AFTER)
    if j1 - j0 + 1 < BARS_AFTER:
        return None
    h, l = S["h"], S["l"]
    return any((h[j] >= tp1) if is_long else (l[j] <= tp1) for j in range(j0, j1 + 1))


def enrich_row(r, S, i, w, pb, lev, fee):
    """adds r['alt'] (net per SL variant and break-even mode), r['bb'] and r['after'] to one replay row."""
    is_long = r["a"] == "BUY"
    entry, base_sl, tp1, tp4 = r["e"], r["sl"], r["tp"][0], r["tp"][3]
    r["bb"] = bb_info(w, pb, i)
    if (is_long and base_sl >= entry) or (not is_long and base_sl <= entry):
        return
    buf = fee / lev if lev else 0.0                          # fee as a % of price: 1% ROI at 10x = 0.1% price
    alt, open_seen = {}, False
    for name, sl in sl_levels(S, i, is_long, entry, base_sl).items():
        for bk, bp in (("be0", 0.0), ("bef", buf)):
            ret, why, bars = sim_trade(S, i, is_long, entry, sl, tp1, tp4, bp)
            open_seen = open_seen or why == "OPEN"
            alt[f"{name}|{bk}"] = [round(ret * lev - fee, 3), why, bars, round(abs(entry - sl) / entry * 100.0, 3)]
    if open_seen:
        return                                               # data ended while a variant was still running: do not compare
    r["alt"] = alt
    if alt["base|be0"][1] == "SL":
        r["after"] = tp1_after_exit(S, i, is_long, tp1, alt["base|be0"][2])


def _paired_z(d):
    n = len(d)
    if n < 2:
        return 0.0
    m = _mean(d)
    se = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1) / n)
    return m / se if se > 0 else 0.0


def sl_tests(rows):
    """each SL variant vs today's SL on the SAME signals, older vs newer half. Positive diff = variant better."""
    rs = [r for r in rows if r.get("alt")]
    if len(rs) < 40:
        return None
    old, new = split_rows(rs)
    base = [r["alt"]["base|be0"][0] for r in rs]
    out = {"n": len(rs), "base": {"net": round(sum(base), 1), "avg": round(_mean(base), 2),
                                  "win": round(100.0 * sum(1 for x in base if x > 0) / len(base), 1),
                                  "sl_rate": round(100.0 * sum(1 for r in rs if r["alt"]["base|be0"][1] == "SL") / len(rs), 1),
                                  "bars": round(_mean([r["alt"]["base|be0"][2] for r in rs]), 1),
                                  "sl_pct": round(_mean([r["alt"]["base|be0"][3] for r in rs]), 2)}, "rows": []}
    for bk in ("be0", "bef"):
        for sk, _ in SL_NAMES:
            key = f"{sk}|{bk}"
            if key == "base|be0":
                continue
            po, pn = [r for r in old if key in r["alt"]], [r for r in new if key in r["alt"]]
            do = [r["alt"][key][0] - r["alt"]["base|be0"][0] for r in po]
            dn = [r["alt"][key][0] - r["alt"]["base|be0"][0] for r in pn]
            allr = po + pn
            v = [r["alt"][key][0] for r in allr]
            zo, zn = _paired_z(do), _paired_z(dn)
            if len(po) < MIN_PAIR_OLD or len(pn) < MIN_PAIR_NEW:
                verdict = "not enough data"
            elif zo >= Z_OLD and zn >= Z_NEW:
                verdict = "BETTER than today in both halves (confirmed)"
            elif zo <= -Z_OLD and zn <= -Z_NEW:
                verdict = "WORSE than today in both halves"
            else:
                verdict = "not confirmed (no clear difference on both halves)"
            out["rows"].append({"key": key, "sl": dict(SL_NAMES)[sk], "be": BE_NAMES[bk], "verdict": verdict, "n": len(allr),
                                "net": round(sum(v), 1), "avg": round(_mean(v), 2),
                                "win": round(100.0 * sum(1 for x in v if x > 0) / len(v), 1) if v else 0.0,
                                "sl_rate": round(100.0 * sum(1 for r in allr if r["alt"][key][1] == "SL") / len(allr), 1) if allr else 0.0,
                                "bars": round(_mean([r["alt"][key][2] for r in allr]), 1),
                                "sl_pct": round(_mean([r["alt"][key][3] for r in allr]), 2),
                                "d_old": round(_mean(do), 2), "d_new": round(_mean(dn), 2),
                                "z_old": round(zo, 2), "z_new": round(zn, 2)})
    return out


def direction_check(rows):
    ds = [r["after"] for r in rows if r.get("after") is not None]
    return {"n": len(ds), "yes": sum(1 for x in ds if x)}


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
    sk = [r["net"] for r in so + sn]
    out["avoided"] = round(-sum(x for x in sk if x < 0), 1)      # losses of the skipped trades (the filter saved these)
    out["missed"] = round(sum(x for x in sk if x > 0), 1)        # profits of the skipped trades (the filter gave these up)
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
    rep["bb_gates"] = [(name, judge(old, new, fn)) for name, fn in BB_GATES]
    rep["sl"] = sl_tests(rows)
    rep["direction"] = direction_check(rows)
    rep["by_bb_rank"] = table_by(rows, lambda r: None if not r.get("bb") or r["bb"].get("rk") is None else
                                 ("band width narrowest 25% (squeeze)" if r["bb"]["rk"] < 25 else "band width 25-50%" if r["bb"]["rk"] < 50
                                  else "band width 50-75%" if r["bb"]["rk"] < 75 else "band width widest 25%"))
    rep["by_bb_pos"] = table_by(rows, lambda r: None if _bbt(r) is None else
                                ("outside band AGAINST the trade" if _bbt(r) < 0 else "wrong half of the band" if _bbt(r) <= 0.5
                                 else "right half of the band" if _bbt(r) <= 1.0 else "outside band IN the trade direction (late)"))
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


def _gate_lines(gates):
    L = []
    for name, j in gates:
        L.append(f"* {name}")
        L.append(f"    {j['verdict']}")
        for half in ("old", "new"):
            k, s = j[half]["kept"], j[half]["skipped"]
            L.append(f"    {half:3s}: kept {k['n']} (net {k['net']:+.0f}, avg {k['avg']:+.2f}) | skipped {s['n']} (net {s['net']:+.0f}, avg {s['avg']:+.2f})")
        L.append(f"    loss avoided {j.get('avoided', 0):+.0f} | profit missed {-j.get('missed', 0):+.0f} | net effect {j['saved_old'] + j['saved_new']:+.0f} (ROI points)")
    return L


def _sl_text(rep):
    L = []
    d = rep.get("direction") or {}
    if d.get("n"):
        L += ["", "DIRECTION CHECK - was the SL too tight, or was the direction wrong?",
              f"  Bot's SL was hit in {d['n']} trades (that had {BARS_AFTER} candles of data after). In {d['yes']} of them ({100.0 * d['yes'] / d['n']:.0f}%) "
              f"price still touched TP1 within {BARS_AFTER} candles after the SL exit.",
              "  Large share = direction was often right and the SL was too tight. The SL test below shows if a wider SL really pays after fees."]
    sl = rep.get("sl")
    if sl:
        b = sl["base"]
        L += ["", "STOP-LOSS TEST - same signals, only the SL changes (never tighter than today). Net = ROI points after fee. Positive 'vs today' = better.",
              f"  TODAY: {sl['n']} trades, net {b['net']:+.0f}, avg {b['avg']:+.2f}, win {b['win']:.0f}%, SL hit {b['sl_rate']:.0f}%, avg hold {b['bars']} candles, avg SL distance {b['sl_pct']}% of price"]
        for x in sl["rows"]:
            L.append(f"* {x['sl']} | {x['be']}")
            L.append(f"    {x['verdict']}")
            L.append(f"    net {x['net']:+.0f}, avg {x['avg']:+.2f}, win {x['win']:.0f}%, SL hit {x['sl_rate']:.0f}%, avg hold {x['bars']} candles, avg SL distance {x['sl_pct']}%")
            L.append(f"    vs today per trade: older {x['d_old']:+.2f}, newer {x['d_new']:+.2f}")
        L.append("  Note: signals are replayed one by one (overlapping trades, max-open limits and slippage are not modelled).")
    return L


def _summary(rep):
    good = [n for n, j in rep["gates"] + rep["bb_gates"] if j["verdict"].startswith("CONFIRMED")]
    sl = rep.get("sl")
    better = [f"{x['sl']} | {x['be']}" for x in (sl or {}).get("rows", []) if x["verdict"].startswith("BETTER")]
    L = ["SIMPLE VERDICT"]
    L.append("  Filters that help in BOTH halves: " + ("; ".join(good) if good else "none confirmed yet"))
    L.append("  SL changes that help in BOTH halves: " + ("; ".join(better) if better else "none confirmed yet"))
    if sl and sl["rows"]:
        top = max(sl["rows"], key=lambda x: x["d_old"] + x["d_new"])
        L.append(f"  Closest SL idea (NOT confirmed unless listed above): {top['sl']} | {top['be']} -> {top['d_old']:+.2f} older, {top['d_new']:+.2f} newer per trade")
    L.append("  How to read: 'loss avoided' = losing trades the rule would skip; 'profit missed' = winning trades it would also skip. "
             "A good rule avoids a lot and misses little, in BOTH halves.")
    return L


def text_report(rep, tf, days, lev, fee):
    L = [f"FILTER LAB - {tf} candles, last {days} days, leverage {lev}x, fee {fee}% ROI per trade (net = ROI % after fee)",
         f"Signals replayed: {rep['n']} (older {rep['n_old']} / newer {rep['n_new']})", ""] + _summary(rep) + [""] + [
         "BOT AS IT IS (no filter):",
         _line("older ", rep["baseline"]["old"]), _line("newer ", rep["baseline"]["new"]), "",
         "FILTERS - 'skipped' = trades the filter would have removed. Good filter: skipped trades lose money in BOTH halves.", ""]
    L += _gate_lines(rep["gates"])
    L += ["", "BOLLINGER BAND FILTERS (20 candles, 2 SD) - each one is its own on/off rule, tested the same way as above.",
          "  squeeze = bands narrow = sideways market; middle band = 20-candle average; 'late' = price already outside the band."]
    L += _gate_lines(rep["bb_gates"])
    for title, key in (("BY BAND WIDTH (compared with the last 100 candles)", "by_bb_rank"), ("BY PRICE POSITION IN THE BAND (seen from the trade)", "by_bb_pos")):
        L += ["", title]
        for k, s in sorted(rep[key].items(), key=lambda kv: kv[1]["avg"]):
            L.append(_line(k, s))
    L += _sl_text(rep)
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
        try:                                   # extra series for the SL test and the Bollinger filters (read-only maths)
            from recovered_bot import ai_ind_features as F
            S = F.build(candles)
            tmap = {t: k for k, t in enumerate(S["t"])}
            bw, bp = bb_series(S)
        except Exception:
            S = tmap = bw = bp = None
        for r in got:
            o = (r.get("o") or {}).get("T4")
            if not o or o[1] == "OPEN":
                continue
            r["net"] = o[0] * lev - fee
            if S is not None:
                k = tmap.get(r["t"] - TF_MS[tf] + 1)
                if k is not None:
                    try:
                        enrich_row(r, S, k, bw, bp, lev, fee)
                    except Exception:
                        pass
            rows.append(r)
        time.sleep(0.01)                       # keep the phone's CPU free for the live bot
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


_ALL = {"running": False}


def _all_worker(days, lev, fee, restart):
    try:
        for tf in ("3m", "5m", "15m"):
            j = _JOBS.get(tf)
            if j and j["state"] == "done" and not restart:
                continue
            _JOBS[tf] = {"state": "running", "text": "", "progress": "starting...", "t": time.time()}
            _job(tf, days, lev, fee)             # runs here, one timeframe after the other (kind to the phone's CPU)
    finally:
        _ALL["running"] = False


def start_all(days=7, lev=10.0, fee=1.0, restart=False):
    """starts 3m, 5m and 15m one after the other in ONE background thread (does nothing if already running)."""
    if _ALL["running"]:
        return False
    _ALL["running"] = True
    for tf in ("3m", "5m", "15m"):
        j = _JOBS.get(tf)
        if restart or not j or j["state"] != "done":
            _JOBS[tf] = {"state": "queued", "text": "", "progress": "waiting", "t": time.time()}
    threading.Thread(target=_all_worker, args=(int(days), float(lev), float(fee), bool(restart)), daemon=True, name="filter_lab_all").start()
    return True


def status_all():
    out = {"running": _ALL["running"], "tfs": {}}
    for tf in ("3m", "5m", "15m"):
        j = _JOBS.get(tf)
        out["tfs"][tf] = ({"state": "not run", "progress": "", "age_min": None} if not j else
                          {"state": j["state"], "progress": j.get("progress", ""), "age_min": int((time.time() - j["t"]) / 60)})
    return out


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
