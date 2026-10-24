#!/usr/bin/env python3
"""
tag_lab.py - "TAG LAB": which combination of the two indicators really makes money? Read-only, run by hand.

  cd backend && python3 tag_lab.py 5m 7                   # 5m candles, last 7 days, top-10 gainers + losers
  python3 tag_lab.py 5m 7 BTCUSDT,ETHUSDT --lev 10 --fee 1.0
  (or tap Run in the app: Strategy Doctor > Tag Lab. Result files: ~/owl_data/tag_lab_5m.txt / .json)

Two kinds of entry are replayed, side by side, on the SAME candles:
  MAIN = the bot's own signal (EMA50 cross on the main chart)
  Z    = the Special Master v6 Z candle closes across its slow EMA50 (the black candle), even when the main chart said nothing
  BOTH = both on the same candle
Every entry gets TAGS (only things known at that candle): TSI side / signal line / histogram growing or shrinking, Z candle
vs its EMA30 + EMA50, cloud colour, ZSM (Z vs its 200 average), Z chop, main-chart chop, who came first, room left in
the SD bands, price-vs-Z divergence, time of day. The CODE then counts every 1-, 2- and 3-tag combination: trades, win %,
net after fee, minutes held, how far it went (TP1..TP4 = SD levels), worst dip. The AI never does the maths.

A combination only counts as GOOD when it is positive in the OLDER 60% AND the NEWER 40% (fee inside). Because thousands of
combinations are tried, some always win by luck, so the same test is repeated on SHUFFLED results and the report says how
many "winners" pure luck gives. Rare combinations stay recorded; under 30 trades they are NOT judged.
Exits: every entry is replayed with 9 exit rules (the bot's TP4 rule, Z black candle exit, close at TP1 / TP2, NO CAP
runners that exit on the main cross / Z candle / a trailing stop, close after 12 candles), so you see which exit lets the
rally run and which exit suits which combination. Also shown: how often price still reached TP1 AFTER the SL hit.
NO AI / API KEY is needed: all of this is plain code; an AI may later only explain the table. Nothing here changes the bot. A replay is evidence, not a promise.
"""
import json
import os
import random
import re
import subprocess
import sys
import time
from bisect import bisect_left
from itertools import combinations

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import filter_lab as FL

Z_FAST, Z_SLOW = 30, 50          # Special Master v6 defaults (EMA of the Z close)
CHOP_WIN, CHOP_N = 20, 3         # 3+ crosses in the last 20 candles = choppy / sideways
NEAR = 5                         # "who came first" looks this many candles back
MIN_N, MIN_OLD, MIN_NEW = 30, 15, 10
MIN_EDGE = 0.5                   # ROI pts per trade a half must beat: the replay fills SL/TP at the exact price (no slippage), which
                                 # gave about +0.3 per trade for free on made-up pure-noise candles, so tiny winners are noise
MAX_K = 3                        # tags per combination
TF_MIN = {"3m": 3, "5m": 5, "15m": 15}
DIMS = ("src", "order", "tsi_zero", "tsi_line", "tsi_hist", "z_ema", "cloud", "zsm", "z_chop", "main_chop", "z_room",
        "diverge", "hour")
DIM_NAME = {"src": "Entry type", "order": "Who came first", "tsi_zero": "TSI vs zero", "tsi_line": "TSI vs signal line",
            "tsi_hist": "TSI histogram", "z_ema": "Z candle vs its EMAs", "cloud": "Z cloud colour", "zsm": "Z vs ZSM",
            "z_chop": "Z sideways", "main_chop": "Main sideways", "z_room": "Room in SD bands",
            "diverge": "Price vs Z", "hour": "Time of day"}


# ---------------------------------------------------------------- series
def z_series(S):
    """Z close EMA30 / EMA50 and the Z black-candle crosses (Pine crossover / crossunder) + chop counts."""
    from recovered_bot import ai_ind_features as F
    n = S["n"]
    z, last = [], None
    for v in S["z"]:                                   # forward fill: a flat price gives Z = None, F.ema cannot take that
        last = v if v is not None else last
        z.append(last)
    zf, zs = F.ema(z, Z_FAST), F.ema(z, Z_SLOW)
    up, dn = [False] * n, [False] * n
    for j in range(1, n):
        if None in (z[j], z[j - 1], zs[j], zs[j - 1]):
            continue
        if z[j - 1] <= zs[j - 1] and z[j] > zs[j]:
            up[j] = True
        elif z[j - 1] >= zs[j - 1] and z[j] < zs[j]:
            dn[j] = True
    pm, pz = [0] * (n + 1), [0] * (n + 1)              # prefix sums of crosses -> chop count of the last CHOP_WIN candles
    for j in range(n):
        pm[j + 1] = pm[j] + (1 if (S["xup"][j] or S["xdn"][j]) else 0)
        pz[j + 1] = pz[j] + (1 if (up[j] or dn[j]) else 0)
    return {"zf": zf, "zs": zs, "up": up, "dn": dn, "pm": pm, "pz": pz}


def _recent(flags_up, flags_dn, i, d):
    """(candles back of the latest SAME-direction cross, candles back of the latest OPPOSITE cross) within 1..NEAR, else None."""
    same = opp = None
    for b in range(1, NEAR + 1):
        j = i - b
        if j < 0:
            break
        a_same, a_opp = (flags_up[j], flags_dn[j]) if d > 0 else (flags_dn[j], flags_up[j])
        if same is None and a_same:
            same = b
        if opp is None and a_opp:
            opp = b
    return same, opp


def _order(S, Z, i, d, src):
    if src == "BOTH":
        return "both on the same candle"
    other_up, other_dn = (S["xup"], S["xdn"]) if src == "Z" else (Z["up"], Z["dn"])
    same, opp = _recent(other_up, other_dn, i, d)
    name = "main chart" if src == "Z" else "Z candle"
    if same is not None:
        return f"{name} came first ({'1-2' if same <= 2 else '3-5'} candles before)"
    if opp is not None:
        return f"{name} gave the OPPOSITE signal in the last {NEAR} candles"
    return f"{name} gave nothing in the last {NEAR} candles"


def make_tags(S, Z, i, d, src, t_close):
    """All tags for one entry at candle i, direction d (+1 buy / -1 sell). Only past + present candles are used."""
    tsi, diff, z, zf, zs, zsm = S["tsi"][i], S["diff"][i], S["z"][i], Z["zf"][i], Z["zs"][i], S["zsma"][i]
    if None in (tsi, diff, z, zf, zs, zsm, S["diff"][i - 1]):
        return None
    w = (1 if z > zf else 0) + (1 if z > zs else 0) if d > 0 else (1 if z < zf else 0) + (1 if z < zs else 0)
    zv = z * d
    mv, zmv = (S["c"][i] - S["c"][i - 5]) * d, (z - (S["z"][i - 5] if S["z"][i - 5] is not None else z)) * d
    hr = (t_close // 3_600_000) % 24
    return {
        "src": src, "order": _order(S, Z, i, d, src),
        "tsi_zero": "TSI with the trade (above/below 0)" if tsi * d > 0 else "TSI against the trade",
        "tsi_line": "TSI on the trade side of its signal line" if diff * d > 0 else "TSI on the wrong side of its signal line",
        "tsi_hist": "histogram growing" if abs(diff) > abs(S["diff"][i - 1]) else "histogram shrinking",
        "z_ema": ("Z candle beyond both EMAs (with trade)", "Z candle between its EMAs", "Z candle against both EMAs")[2 - w],
        "cloud": "cloud colour with the trade" if (zf > zs) == (d > 0) else "cloud colour against the trade",
        "zsm": "Z on the trade side of ZSM" if (z > zsm) == (d > 0) else "Z on the wrong side of ZSM",
        "z_chop": "Z choppy" if Z["pz"][i + 1] - Z["pz"][max(0, i + 1 - CHOP_WIN)] >= CHOP_N else "Z clean",
        "main_chop": "main chart choppy" if Z["pm"][i + 1] - Z["pm"][max(0, i + 1 - CHOP_WIN)] >= CHOP_N else "main chart clean",
        "z_room": "lots of room (Z far from the trade side)" if zv < -1 else "stretched (Z already far with the trade)" if zv > 1 else "middle of the SD bands",
        "diverge": "price and Z agree" if (mv > 0) == (zmv > 0) else "price and Z disagree",
        "hour": f"{(hr // 6) * 6:02d}-{(hr // 6) * 6 + 6:02d} UTC",
    }


# ---------------------------------------------------------------- trade replay
EXITS = {          # name: rule. cap = TP level that closes the trade (None = no cap, the rally may run), be = SL to entry after TP1,
                   # xmode = opposite cross that closes it ('main' EMA50 / 'z' black candle / None), trail = trailing stop in R
                   # (R = distance entry-SL, starts after price moved 1R), hold = close after that many candles
    "BOT exit (TP4, main cross)": dict(cap=4, be=True, xmode="main"),
    "TP4 + Z candle exit": dict(cap=4, be=True, xmode="z"),
    "close all at TP1": dict(cap=1, be=False, xmode="main"),
    "close all at TP2": dict(cap=2, be=False, xmode="main"),
    "NO CAP, main cross exit": dict(cap=None, be=True, xmode="main"),
    "NO CAP, Z candle exit": dict(cap=None, be=True, xmode="z"),
    "NO CAP, trail 1.5R": dict(cap=None, be=True, xmode=None, trail=1.5),
    "NO CAP, trail 3R": dict(cap=None, be=True, xmode=None, trail=3.0),
    "close after 12 candles": dict(cap=None, be=False, xmode=None, hold=12),
}
BOT, ZX = "BOT exit (TP4, main cross)", "TP4 + Z candle exit"
PATH_BARS, REC_BARS = 48, 30      # exit-free look-ahead (rally check) / "did price still reach TP1 after the SL" window


def sim_rule(S, Z, i, d, entry, sl, tps, lev, fee, cap=4, be=True, xmode="main", trail=None, hold=None, allow_open=False):
    """One exit rule on one entry. SL first in a candle (conservative); stop changes apply from the NEXT candle.
    -> dict or None while the data ends before the trade finished (allow_open=True closes it at the last close instead)."""
    h, l, c, n = S["h"], S["l"], S["c"], S["n"]
    end = min(n - 1, i + FL.MAX_FWD)
    opp = None if xmode is None else ((S["xdn"] if d > 0 else S["xup"]) if xmode == "main" else (Z["dn"] if d > 0 else Z["up"]))
    R = abs(entry - sl)
    cur, be_on, hit, b1, mae, best, got = sl, False, 0, None, 0.0, entry, None
    for j in range(i + 1, end + 1):
        hh, ll = h[j], l[j]
        mae = max(mae, (entry - ll) / entry if d > 0 else (hh - entry) / entry)
        if (ll <= cur) if d > 0 else (hh >= cur):
            got = (cur, "SL" if cur == sl else "BE" if cur == entry else "TRAIL", j - i)
            break
        while hit < 4 and ((hh >= tps[hit]) if d > 0 else (ll <= tps[hit])):
            hit += 1
            if hit == 1 and b1 is None:
                b1 = j - i
        if cap and hit >= cap:
            got = (tps[cap - 1], "TP", j - i)
            break
        if opp is not None and opp[j]:
            got = (c[j], "REV", j - i)
            break
        if hold and j - i >= hold:
            got = (c[j], "HOLD", j - i)
            break
        best = max(best, hh) if d > 0 else min(best, ll)
        if be and not be_on and hit >= 1 and ((entry > cur) if d > 0 else (entry < cur)):
            cur, be_on = entry, True
        if trail and abs(best - entry) >= R:
            ns = best - d * trail * R
            if (ns > cur) if d > 0 else (ns < cur):
                cur = ns
    if got is None:
        if end - i >= FL.MAX_FWD:
            got = (c[end], "TIMEOUT", end - i)
        elif allow_open and end > i:
            got = (c[end], "OPEN", end - i)
        else:
            return None
    px, why, bars = got
    return {"net": (px - entry) / entry * 100.0 * d * lev - fee, "why": why, "bars": bars, "hit": hit, "b1": b1,
            "mae": mae * 100.0 * lev}


def simulate(S, Z, i, d, entry, sl, tps, xmode, lev, fee):
    """The bot's own rule (TP4 / SL / TP1 -> entry / opposite cross); xmode 'main' = opposite EMA50 cross, 'z' = opposite Z black candle."""
    return sim_rule(S, Z, i, d, entry, sl, tps, lev, fee, cap=4, be=True, xmode=xmode)


def path_stats(S, i, d, entry, sl, lev):
    """Exit-free: how far did price run in our direction in the next PATH_BARS candles (ROI pts), and was it 3x the SL distance."""
    h, l = S["h"], S["l"]
    end = min(S["n"] - 1, i + PATH_BARS)
    if end - i < PATH_BARS:
        return None
    mfe, mb = 0.0, 0
    for j in range(i + 1, end + 1):
        f = (h[j] - entry) / entry if d > 0 else (entry - l[j]) / entry
        if f > mfe:
            mfe, mb = f, j - i
    r_roi = abs(entry - sl) / entry * 100.0 * lev
    return {"mfe": mfe * 100.0 * lev, "mfe_bars": mb, "ran3r": mfe * 100.0 * lev >= 3 * r_roi}


def recovered(S, i, d, tp1, exit_bar):
    """After the SL: did price still touch TP1 within REC_BARS candles? None = not enough candles after it."""
    j0, j1 = i + exit_bar + 1, i + exit_bar + REC_BARS
    if j1 > S["n"] - 1:
        return None
    return any((S["h"][j] >= tp1) if d > 0 else (S["l"][j] <= tp1) for j in range(j0, j1 + 1))


def rows_from_candles(sym, tf, candles, since_close_ms, lev, fee):
    """Every MAIN / Z / BOTH entry on these candles -> rows with tags and both exit results. No network."""
    from recovered_bot import ai_ind_features as F
    from recovered_bot.strategy import ABCDStrategy
    if len(candles) < F.MIN_BARS + 5:
        return [], 0
    S = F.build(candles)
    Z = z_series(S)
    strat, step, rows, skipped = ABCDStrategy(), FL.TF_MS[tf], [], 0
    for i in range(F.MIN_BARS, S["n"]):
        t_close = S["t"][i] + step - 1
        if t_close < since_close_ms:
            continue
        m = 1 if S["xup"][i] else -1 if S["xdn"][i] else 0
        zc = 1 if Z["up"][i] else -1 if Z["dn"][i] else 0
        if not m and not zc or (m and zc and m != zc):
            continue
        d = m or zc
        src = "BOTH" if (m and zc) else ("Z" if zc else "MAIN")
        mean, sd = S["sma"][i], S["std"][i]
        if not sd or mean is None:
            continue
        tg = make_tags(S, Z, i, d, src, t_close)
        if tg is None:
            continue
        entry = S["c"][i]
        sl = S["l"][i] if d > 0 else S["h"][i]
        lv = {"zero_price": mean, "onesd": mean + sd, "twosd": mean + 2 * sd, "threesd": mean + 3 * sd,
              "neg_onesd": mean - sd, "neg_twosd": mean - 2 * sd, "neg_threesd": mean - 3 * sd}
        tps = list(strat.calculate_tp_levels(entry, d > 0, lv))
        if (d > 0 and not (sl < entry < tps[0])) or (d < 0 and not (tps[0] < entry < sl)):
            skipped += 1                                 # no room to the first SD level / SL on the wrong side: the bot would not trade it sensibly
            continue
        a = sim_rule(S, Z, i, d, entry, sl, tps, lev, fee, **EXITS[BOT])
        if a is None:
            continue
        x = {}
        for name, rule in EXITS.items():
            r_ = a if name == BOT else sim_rule(S, Z, i, d, entry, sl, tps, lev, fee, allow_open=True, **rule)
            if r_ is None:
                break
            x[name] = (round(r_["net"], 3), r_["bars"])
        if len(x) < len(EXITS):
            continue
        ps = path_stats(S, i, d, entry, sl, lev) or {}
        rows.append({"s": sym, "t": t_close, "d": d, "tg": tg, "net": a["net"], "netz": x[ZX][0], "why": a["why"],
                     "bars": a["bars"], "hit": a["hit"], "b1": a["b1"], "mae": a["mae"], "barsz": x[ZX][1], "hitz": 0,
                     "x": x, "mfe": ps.get("mfe"), "ran3r": ps.get("ran3r"),
                     "rec": recovered(S, i, d, tps[0], a["bars"]) if a["why"] == "SL" else None})
    return rows, skipped


def collect(tf, days, coins, lev, fee, log=lambda m: print(m, flush=True)):
    from recovered_bot import ai_shadow_lab as LAB
    now = int(time.time() * 1000)
    start, since = now - days * 86_400_000 - 450 * FL.TF_MS[tf], now - days * 86_400_000
    rows, skipped = [], 0
    for n, sym in enumerate(coins, 1):
        try:
            candles = LAB._fetch_range(sym, tf, start)
        except Exception as e:
            candles = None
            log(f"[{n}/{len(coins)}] {sym}: download failed ({type(e).__name__})")
        if not candles:
            log(f"[{n}/{len(coins)}] {sym}: no candles (skipped)")
            continue
        got, sk = rows_from_candles(sym, tf, candles, since, lev, fee)
        rows += got
        skipped += sk
        time.sleep(0.01)                                 # keep the phone's CPU free for the live bot
        log(f"[{n}/{len(coins)}] {sym}: {len(got)} entries")
    return rows, skipped


# ---------------------------------------------------------------- numbers
def _avg(v):
    return sum(v) / len(v) if v else 0.0


def line(label, rs, tfmin, key="net"):
    n = len(rs)
    if not n:
        return f"  {label}: no trades"
    nets = [r[key] for r in rs]
    b1 = [r["b1"] for r in rs if r["b1"]]
    return (f"  {label}: {n} trades, net {sum(nets):+.0f}, avg {_avg(nets):+.2f}, win {100.0 * sum(1 for x in nets if x > 0) / n:.0f}%, "
            f"held {_avg([r['bars'] for r in rs]) * tfmin:.0f} min, TP1 {100.0 * sum(1 for r in rs if r['hit'] >= 1) / n:.0f}% "
            f"(in {_avg(b1) * tfmin:.0f} min), TP4 {100.0 * sum(1 for r in rs if r['hit'] >= 4) / n:.0f}%, dip {_avg([r['mae'] for r in rs]):.1f}")


def build_combos(rows):
    """key (tuple of (dim, value)) -> ascending list of row indices. Rows must be sorted by time."""
    out = {}
    for ix, r in enumerate(rows):
        items = sorted((k, r["tg"][k]) for k in DIMS)
        for k in range(1, MAX_K + 1):
            for c in combinations(items, k):
                out.setdefault(c, []).append(ix)
    return {k: v for k, v in out.items() if len(v) >= MIN_N}


def _halves(idx, X, cut):
    k = bisect_left(idx, cut)
    a, b = idx[:k], idx[k:]
    return len(a), sum(X[i] for i in a), len(b), sum(X[i] for i in b)


def _good(no, so, nn, sn):
    return no >= MIN_OLD and nn >= MIN_NEW and no + nn >= MIN_N and so / no > MIN_EDGE and sn / nn > MIN_EDGE


def luck_check(combos, X, cut, shuffles, seed=11):
    """Same test on SHUFFLED results (no tag knows anything): how many combinations 'pass' by luck, and what is the BEST
    score luck alone reaches (score = the weaker of the old / new average). Returns (counts, bests)."""
    rnd, counts, bests = random.Random(seed), [], []
    Y = list(X)
    for _ in range(shuffles):
        rnd.shuffle(Y)
        cn, best = 0, -1e9
        for idx in combos.values():
            no, so, nn, sn = _halves(idx, Y, cut)
            if no < MIN_OLD or nn < MIN_NEW:
                continue
            best = max(best, min(so / no, sn / nn))
            cn += _good(no, so, nn, sn)
        counts.append(cn)
        bests.append(best)
    return counts, bests


def _name(key):
    return " + ".join(v for _, v in key)


def _pick(cands, limit, max_overlap=0.8):
    """first `limit` candidates whose trades are not mostly the same trades as one already shown."""
    shown = []
    for c in cands:
        s = set(c["idx"])
        if all(len(s & p) / max(1, min(len(s), len(p))) < max_overlap for p in shown):
            shown.append(s)
            yield c
            if len(shown) >= limit:
                return


def analyse(rows, shuffles=10):
    rows = sorted(rows, key=lambda r: r["t"])
    X, cut = [r["net"] for r in rows], int(len(rows) * FL.OLD_SHARE)
    combos = build_combos(rows)
    good, bad, best = [], [], -1e9
    for key, idx in combos.items():
        no, so, nn, sn = _halves(idx, X, cut)
        if no < MIN_OLD or nn < MIN_NEW:
            continue
        ao, an = so / no, sn / nn
        best = max(best, min(ao, an))
        c = {"key": key, "idx": idx, "n": len(idx), "ao": ao, "an": an, "tot": so + sn}
        if ao > MIN_EDGE and an > MIN_EDGE:
            c["score"] = min(ao, an)
            good.append(c)
        elif ao < 0 and an < 0:
            bad.append(c)
    good.sort(key=lambda c: -c["score"])
    bad.sort(key=lambda c: c["tot"])
    counts, bests = luck_check(combos, X, cut, shuffles)
    return {"rows": rows, "cut": cut, "n_combos": len(combos), "good": good, "bad": bad, "lucky": counts,
            "lucky_best": bests, "best": best}


def _dim_table(rows, dim, src, tfmin):
    g = {}
    for r in rows:
        if r["tg"]["src"] == src:
            g.setdefault(r["tg"][dim], []).append(r)
    out = []
    cut = int(len(rows) * FL.OLD_SHARE)
    for v, rs in sorted(g.items(), key=lambda kv: -len(kv[1])):
        if len(rs) < MIN_N:
            out.append(f"    {v}: {len(rs)} trades - data kam")
            continue
        o, nw = [r["net"] for r in rs if r["t"] <= rows[cut - 1]["t"]], [r["net"] for r in rs if r["t"] > rows[cut - 1]["t"]]
        out.append(f"    {v}: {len(rs)} trades, avg {_avg([r['net'] for r in rs]):+.2f} (old {_avg(o):+.2f} / new {_avg(nw):+.2f}), "
                   f"win {100.0 * sum(1 for r in rs if r['net'] > 0) / len(rs):.0f}%, held {_avg([r['bars'] for r in rs]) * tfmin:.0f} min")
    return out


def exit_scores(rows, idx, cut):
    """per exit rule: (old avg, new avg, avg candles held) over these rows (idx = row indices, rows sorted by time)."""
    if not idx or not rows[idx[0]].get("x"):
        return {}
    out = {}
    for name in EXITS:
        o = [rows[i]["x"][name][0] for i in idx if i < cut]
        w = [rows[i]["x"][name][0] for i in idx if i >= cut]
        out[name] = (_avg(o), _avg(w), _avg([rows[i]["x"][name][1] for i in idx]), len(o), len(w))
    return out


def best_exit(sc):
    ok = {k: v for k, v in sc.items() if v[3] >= 5 and v[4] >= 5}
    return max(ok.items(), key=lambda kv: min(kv[1][0], kv[1][1])) if ok else None


def exit_lines(rows, tfm, srcs):
    L = ["EXITS ON THE SAME ENTRIES (avg ROI pts per trade after fee; * = best exit for that entry type). This is where a rally after",
         "TP1 / TP4 shows up: 'NO CAP' / trail rules let it run, 'close all' rules cut it:"]
    cols = {s: [r for r in rows if r["tg"]["src"] == s and r.get("x")] for s in srcs}
    if not any(cols.values()):
        return []
    best = {s: max(EXITS, key=lambda e: _avg([r["x"][e][0] for r in rs])) if rs else None for s, rs in cols.items()}
    for e in EXITS:
        parts = []
        for s in srcs:
            rs = cols[s]
            parts.append(f"{s} {_avg([r['x'][e][0] for r in rs]):+.2f}{'*' if best[s] == e else ' '} ({_avg([r['x'][e][1] for r in rs]) * tfm:.0f}m)" if rs else f"{s} -")
        L.append(f"  {e[:36]:36} " + "  ".join(parts))
    return L


def rally_lines(rows, tfm, srcs):
    L = ["RALLY / SL CHECK (hindsight facts about what price did AFTER the entry; used only to judge exits, never as a tag):"]
    for s in srcs:
        rs = [r for r in rows if r["tg"]["src"] == s]
        sl = [r for r in rs if r["rec"] is not None]
        pa = [r for r in rs if r.get("mfe") is not None]
        if pa:
            L.append(f"  {s}: {100.0 * sum(1 for r in pa if r['ran3r']) / len(pa):.0f}% of entries ran 3x their SL distance within "
                     f"{PATH_BARS * tfm} min; best move avg +{_avg([r['mfe'] for r in pa]):.1f} ROI pts vs bot exit avg {_avg([r['net'] for r in pa]):+.2f}")
        if sl:
            L.append(f"     SL was hit in {len(sl)} trades; in {100.0 * sum(1 for r in sl if r['rec']) / len(sl):.0f}% price still touched TP1 within "
                     f"{REC_BARS * tfm} min after the SL (SL too tight / shaken out).")
    return L


def text_report(rep, tf, days, lev, fee, skipped=0):
    rows, tfm = rep["rows"], TF_MIN.get(tf, 5)
    srcs = [s for s in ("MAIN", "Z", "BOTH") if any(r["tg"]["src"] == s for r in rows)]
    L = [f"TAG LAB  {tf}, {days} days, {lev:g}x, fee {fee:g}% ROI per trade (all numbers = ROI points after fee)",
         f"Entries judged: {len(rows)}  (older {rep['cut']} / newer {len(rows) - rep['cut']}); {skipped} skipped (no room to TP1). "
         f"Combinations with 30+ trades tried: {rep['n_combos']}", ""]
    lk, lb = rep["lucky"], rep["lucky_best"]
    L.append("1) SHORT ANSWER")
    if rep["good"]:
        real = rep["best"] > max(lb)
        L.append(f"  {len(rep['good'])} combinations beat +{MIN_EDGE:g} per trade in BOTH halves (luck alone gives about {_avg(lk):.0f}).")
        L.append(f"  Best combination: +{rep['best']:.2f} in its weaker half. The best that pure luck reached in {len(lb)} shuffles: "
                 f"+{max(lb):.2f}.")
        L.append("  -> " + ("the best ones beat everything luck produced: worth checking on NEW live trades."
                            if real else "NOT better than luck. Do not trust these yet; run more days / more coins."))
    else:
        L.append("  No combination beat +%g per trade in both halves. Nothing to trade yet." % MIN_EDGE)
    top = list(_pick(rep["good"], 8))
    if top:
        L += ["", "2) TOP COMBINATIONS (good in older AND newer; avg = ROI points per trade)"]
    for c in top:
        rs = [rows[i] for i in c["idx"]]
        L.append(f"* {_name(c['key'])}")
        L.append(f"   old avg {c['ao']:+.2f} / new avg {c['an']:+.2f}")
        L.append(line("all", rs, tfm).replace("  all: ", "  "))
        be = best_exit(exit_scores(rows, c["idx"], rep["cut"]))
        if be:
            L.append(f"   best exit for this combo: {be[0]} (old {be[1][0]:+.2f} / new {be[1][1]:+.2f}, held {be[1][2] * tfm:.0f} min)")
    L += ["", "3) ENTRY TYPES with the bot's exit - MAIN = bot signal, Z = Z black candle even with no main signal"]
    for s in srcs:
        L.append(line(s, [r for r in rows if r["tg"]["src"] == s], tfm))
    ex = exit_lines(rows, tfm, srcs)
    if ex:
        L += ["", "4) " + ex[0]] + ex[1:] + ["", "5) " + rally_lines(rows, tfm, srcs)[0]] + rally_lines(rows, tfm, srcs)[1:]
    worst = list(_pick(rep["bad"], 6))
    if worst:
        L += ["", "6) WORST COMBINATIONS (negative in both halves - skipping them saves this much)"]
        for c in worst:
            L.append(f"* {_name(c['key'])}: {c['n']} trades, total {c['tot']:+.0f}, old {c['ao']:+.2f} / new {c['an']:+.2f}")
    L += ["", "7) IS EACH INDICATOR HELPFUL? (one tag at a time, per entry type; 'data kam' = under 30 trades)"]
    for s in [x for x in srcs if x != "BOTH"]:
        L.append(f"  [{s} entries]")
        for dim in DIMS[1:]:
            L.append(f"   {DIM_NAME[dim]}:")
            L += _dim_table(rows, dim, s, tfm)
    L += ["", f"Reading guide: a combination is GOOD only if it beats +{MIN_EDGE:g} per trade in the older 60% AND the newer 40%, fee inside.",
          "The replay fills SL/TP at the exact price (no slippage) and on made-up noise it showed about +0.3 per trade for free, so smaller",
          "winners are not trusted. 'dip' = average worst move against the trade (ROI pts). TP1/TP4 = SD levels from the bot.",
          "Hindsight facts (section 5) only judge exits; they are never used as a tag."]
    return "\n".join(L)


def to_json(rep, tf, days, lev, fee):
    rows = rep["rows"]

    def pack(c):
        rs = [rows[i] for i in c["idx"]]
        return {"combo": [list(p) for p in c["key"]], "n": c["n"], "old_avg": round(c["ao"], 3), "new_avg": round(c["an"], 3),
                "win_pct": round(100.0 * sum(1 for r in rs if r["net"] > 0) / len(rs), 1),
                "avg_hold_bars": round(_avg([r["bars"] for r in rs]), 1), "tp1_pct": round(100.0 * sum(1 for r in rs if r["hit"] >= 1) / len(rs), 1),
                "tp4_pct": round(100.0 * sum(1 for r in rs if r["hit"] >= 4) / len(rs), 1),
                "best_exit": (lambda b: None if not b else {"rule": b[0], "old_avg": round(b[1][0], 3), "new_avg": round(b[1][1], 3),
                                                          "avg_hold_bars": round(b[1][2], 1)})(best_exit(exit_scores(rows, c["idx"], rep["cut"])))}
    return {"tf": tf, "days": days, "lev": lev, "fee": fee, "entries": len(rows), "combos_tried": rep["n_combos"],
            "good_found": len(rep["good"]), "luck_counts": rep["lucky"], "luck_best": [round(x, 3) for x in rep["lucky_best"]],
            "best_score": round(rep["best"], 3), "made": int(time.time()),
            "good": [pack(c) for c in _pick(rep["good"], 12)], "bad": [pack(c) for c in _pick(rep["bad"], 8)]}


def _paths(tf):
    """Same data folder as the backend (env OWL_DATA_DIR, else the one in ~/.owl_data_dir, else ~/owl_data): text report, json for the app / AI, run log."""
    base = os.environ.get("OWL_DATA_DIR")
    if not base:                                         # run by hand: use the folder owl_auto.sh gave the backend (~/.owl_data_dir)
        try:
            with open(os.path.expanduser("~/.owl_data_dir"), "r", encoding="utf-8") as f:
                base = f.read().strip()
        except Exception:
            base = ""
    base = base or os.path.expanduser("~/owl_data")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"tag_lab_{tf}.txt"), os.path.join(base, f"tag_lab_{tf}.json"), os.path.join(base, "tag_lab_run.log")


def sections_from_text(txt):
    """The report split into {'head': [lines], 'sections': [{'title', 'lines'}]} - the app shows each section as a fold-out."""
    head, secs = [], []
    for ln in txt.split("\n"):
        if re.match(r"^\d\) ", ln):
            secs.append({"title": ln[3:].strip(), "lines": []})
        elif secs:
            if ln.strip():
                secs[-1]["lines"].append(ln.rstrip())
        elif ln.strip():
            head.append(ln.rstrip())
    return {"head": head, "sections": secs}


def save_result(rep, tf, days, lev, fee, skipped):
    txt = text_report(rep, tf, days, lev, fee, skipped)
    out = to_json(rep, tf, days, lev, fee)
    out.update(sections_from_text(txt))
    t_path, j_path, _ = _paths(tf)
    with open(t_path, "w", encoding="utf-8") as f:
        f.write(txt)
    with open(j_path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    return txt, t_path


# ---------------------------------------------------------------- run from the app (own process: the live bot is never slowed)
_PROC = {"p": None, "tf": "", "seen": True, "err": ""}


def _other_lab_running():
    for name in ("scan_lab", "variant_lab"):
        try:
            m = __import__(name)
            if m._STATE.get("running"):
                return name
        except Exception:
            pass
    return ""


def _running():
    p = _PROC["p"]
    return p is not None and p.poll() is None


def start(tf="5m", days=7):
    """Starts tag_lab.py as a separate low-priority process. False = already running / another lab runs / bad input."""
    if tf not in TF_MIN or not (1 <= int(days) <= 14) or _running():
        return False
    other = _other_lab_running()
    if other:
        _PROC["err"] = f"{other} is running, wait for it to finish and tap again."
        return False
    log = open(_paths(tf)[2], "w", encoding="utf-8")
    kw = {"preexec_fn": (lambda: os.nice(10))} if hasattr(os, "nice") else {}
    _PROC.update(p=subprocess.Popen([sys.executable, os.path.abspath(__file__), tf, str(int(days))], stdout=log, stderr=subprocess.STDOUT,
                                    cwd=os.path.dirname(os.path.abspath(__file__)), **kw), tf=tf, seen=False, err="")
    return True


def _last_lines(path, n=3):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return [x.strip() for x in f.read().splitlines() if x.strip()][-n:]
    except Exception:
        return []


def status(tf="5m"):
    """What the app shows: running?, progress line, the saved result of this timeframe (json made by save_result), its age."""
    tf = tf if tf in TF_MIN else "5m"
    running, log = _running(), _paths(tf)[2]
    if _PROC["p"] is not None and not running and not _PROC["seen"]:
        _PROC["seen"] = True
        if _PROC["p"].returncode != 0:
            _PROC["err"] = " ".join(_last_lines(log)) or f"the test stopped (code {_PROC['p'].returncode})"
    last = _last_lines(log, 1)
    result, age = None, None
    try:
        with open(_paths(tf)[1], "r", encoding="utf-8") as f:
            result = json.load(f)
        age = int((time.time() - result.get("made", time.time())) / 60)
    except Exception:
        pass
    return {"running": running, "progress": last[0] if (running and last) else "", "tf": _PROC["tf"] if running else tf,
            "error": "" if running else _PROC["err"], "result": result, "age_min": age}


def main(argv):
    args, opts = FL.parse_args(argv)
    tf = args[0] if args else "5m"
    days = int(args[1]) if len(args) > 1 else 7
    lev, fee = float(opts.get("--lev", 10)), float(opts.get("--fee", 1.0))
    if tf not in TF_MIN:
        print("timeframe must be 3m, 5m or 15m")
        return 1
    coins = args[2].split(",") if len(args) > 2 else FL.default_coins()
    rows, skipped = collect(tf, days, coins, lev, fee)
    if len(rows) < 60:
        print(f"Only {len(rows)} finished entries - too few. Try more days or more coins.", flush=True)
        return 1
    print("analysing (all combinations, luck check)...", flush=True)
    rep = analyse(rows, int(opts.get("--shuffles", 10)))
    txt, path = save_result(rep, tf, days, lev, fee, skipped)
    print("\n" + txt)
    print(f"\nSaved: {path} (+ .json, the app and the AI read that)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
