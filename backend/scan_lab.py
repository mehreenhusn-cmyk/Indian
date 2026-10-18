#!/usr/bin/env python3
"""
scan_lab.py - "Scan Lab": ONE file that answers
   * which ENTRY LINE works best?      EMA30 / EMA50 / SMA30 / SMA50 / the band's own mean line (SMA200)
   * which TIMEFRAME?                  3m 5m 15m 1h 2h
   * which COINS?                      10 fixed MAJORS (BTC, ETH, BNB, SOL ...) vs today's top gainers/losers ("movers")
   * which EXIT / SL?                  hold till the opposite cross (wide SL) | take profit 1.5 x risk (wide SL) | today's tight SL
   * do the SD BANDS act as support / resistance?  (touch statistics + "bounce at +-2SD/3SD" and "break of 2SD" trades)
Everything is a replay on public Binance futures candles (no key, no orders, nothing here touches the bot).
Fee: 10x leverage, 1% ROI per trade (= 0.1% price round trip), same as Strategy Lab. Numbers are ROI points after fee.

A row is a WINNER only when its average trade is positive in BOTH the older 60% and the newer 40% of its own trades,
clearly (not just by luck). With ~200 rows tested on the same data one lucky winner is still possible,
so keep a winner on paper for a few days before trusting it.

  cd backend && python3 scan_lab.py                  # all timeframes, majors + movers (slow: run it in the background)
  python3 scan_lab.py 15m,1h,2h                      # only these timeframes
  python3 scan_lab.py 1h --majors                    # only the fixed majors   (--movers = only the movers)
  python3 scan_lab.py --sd                           # SD length test: 200 (today) vs 150 / 100 / 50 candles, majors, all timeframes
Result: ~/owl_data/scan_lab.txt (readable report) and scan_lab.json. It is rewritten after every finished step.
"""
import json
import math
import os
import statistics
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import filter_lab as FL

LEV, FEE = 10.0, 1.0
MAX_FWD = 300                                   # candles a trade may run before it is closed (TIMEOUT)
TFS = ["3m", "5m", "15m", "1h", "2h"]
DAYS = {"3m": 25, "5m": 40, "15m": 90, "1h": 180, "2h": 300}     # history per timeframe (bigger TF needs more days for enough trades)
MAJORS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TRXUSDT"]
TF_MS = {"3m": 180_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "2h": 7_200_000}
WARM = 260                                      # extra candles before the window (SMA200 needs 200)
TOUCH_WINDOW = 12                               # candles to see whether a band touch reversed or broke
LINES = [("ema30", "EMA30"), ("ema50", "EMA50 (bot today)"), ("sma30", "SMA30"), ("sma50", "SMA50"), ("mean", "SMA200 mean line")]
EXITS = [("run_wide", "hold till opposite cross, wide SL"), ("tp15_wide", "take profit 1.5 x risk, wide SL"),
         ("run_tight", "hold till opposite cross, tight SL (bot's SL)")]
BAND_SC = [("bounce2", "Bounce at +-2SD (wick touches, closes back; target = mean)"),
           ("bounce3", "Bounce at +-3SD (wick touches, closes back; target = mean)"),
           ("break2", "Break of +-2SD (close outside; exit when it closes back inside)")]


# ---------------------------------------------------------------- indicators (plain python, no numpy)
def sma(c, n):
    out, run = [None] * len(c), 0.0
    for i, x in enumerate(c):
        run += x
        if i >= n:
            run -= c[i - n]
        if i >= n - 1:
            out[i] = run / n
    return out


def ema(c, n):
    out = [None] * len(c)
    if len(c) < n:
        return out
    k, v = 2.0 / (n + 1), sum(c[:n]) / n
    out[n - 1] = v
    for i in range(n, len(c)):
        v = c[i] * k + v * (1 - k)
        out[i] = v
    return out


def rolling_sd(c, n):
    out, ref = [None] * len(c), (c[0] if c else 0.0)
    p1, p2 = [0.0], [0.0]
    for x in c:
        d = x - ref
        p1.append(p1[-1] + d)
        p2.append(p2[-1] + d * d)
    for i in range(n - 1, len(c)):
        s1, s2 = p1[i + 1] - p1[i + 1 - n], p2[i + 1] - p2[i + 1 - n]
        m = s1 / n
        out[i] = math.sqrt(max(s2 / n - m * m, 0.0))
    return out


def build(candles):
    c = [float(x["close"]) for x in candles]
    S = {"n": len(c), "t": [int(x["timestamp"]) for x in candles], "c": c,
         "h": [float(x["high"]) for x in candles], "l": [float(x["low"]) for x in candles]}
    S["ema30"], S["ema50"] = ema(c, 30), ema(c, 50)
    S["sma30"], S["sma50"] = sma(c, 30), sma(c, 50)
    S["mean"], S["sd"] = sma(c, 200), rolling_sd(c, 200)
    return S


def cross_flags(S, line):
    """xup[i] / xdn[i]: the close crosses the line upward / downward on candle i."""
    c, L, n = S["c"], S[line], S["n"]
    xup, xdn = [False] * n, [False] * n
    for i in range(1, n):
        if L[i] is None or L[i - 1] is None:
            continue
        if c[i - 1] <= L[i - 1] and c[i] > L[i]:
            xup[i] = True
        elif c[i - 1] >= L[i - 1] and c[i] < L[i]:
            xdn[i] = True
    return xup, xdn


# ---------------------------------------------------------------- one trade replay
def sim(S, i, is_long, entry, sl, tp, xflags):
    """price move in % (signed for the side). SL is checked before TP inside one candle (cautious). None = data ended while open."""
    h, l, c, n = S["h"], S["l"], S["c"], S["n"]
    end = min(n - 1, i + MAX_FWD)
    px = None
    for j in range(i + 1, end + 1):
        if (l[j] <= sl) if is_long else (h[j] >= sl):
            px = sl
            break
        if tp is not None and ((h[j] >= tp) if is_long else (l[j] <= tp)):
            px = tp
            break
        if xflags is not None and xflags[j]:
            px = c[j]
            break
    if px is None:
        if end - i < MAX_FWD:
            return None
        px = c[end]
    return (px - entry) / entry * 100.0 * (1.0 if is_long else -1.0)


def _net(ret):
    return None if ret is None else round(ret * LEV - FEE, 3)


def trend_trades(S, line, exit_key, first):
    """every cross of `line` -> trade. Entry = close of the signal candle (as the bot)."""
    xup, xdn = cross_flags(S, line)
    out, c, h, l = [], S["c"], S["h"], S["l"]
    for i in range(max(first, 1), S["n"]):
        if not (xup[i] or xdn[i]):
            continue
        is_long = xup[i]
        entry = c[i]
        if exit_key == "run_tight":
            sl = l[i] if is_long else h[i]
        else:
            sl = min(l[i], l[i - 1]) if is_long else max(h[i], h[i - 1])
        if (is_long and sl >= entry) or (not is_long and sl <= entry):
            continue
        if exit_key == "tp15_wide":
            risk = abs(entry - sl)
            tp = entry + 1.5 * risk if is_long else entry - 1.5 * risk
            r = sim(S, i, is_long, entry, sl, tp, None)
        else:
            r = sim(S, i, is_long, entry, sl, None, xdn if is_long else xup)
        v = _net(r)
        if v is not None:
            out.append((S["t"][i], v))
    return out


def band_trades(S, key, first):
    c, h, l, mean, sd = S["c"], S["h"], S["l"], S["mean"], S["sd"]
    out = []
    if key.startswith("bounce"):
        k = 2 if key == "bounce2" else 3
        for i in range(max(first, 1), S["n"]):
            if mean[i] is None or not sd[i] or mean[i - 1] is None:
                continue
            lo, hi = mean[i] - k * sd[i], mean[i] + k * sd[i]
            lo_p, hi_p = mean[i - 1] - k * sd[i - 1], mean[i - 1] + k * sd[i - 1]
            if l[i] <= lo and c[i] > lo and l[i - 1] > lo_p:                 # first wick below the lower band, closes back inside -> long
                entry, sl, tp = c[i], l[i], mean[i]
                if sl < entry < tp:
                    v = _net(sim(S, i, True, entry, sl, tp, None))
                    if v is not None:
                        out.append((S["t"][i], v))
            elif h[i] >= hi and c[i] < hi and h[i - 1] < hi_p:               # first wick above the upper band, closes back inside -> short
                entry, sl, tp = c[i], h[i], mean[i]
                if tp < entry < sl:
                    v = _net(sim(S, i, False, entry, sl, tp, None))
                    if v is not None:
                        out.append((S["t"][i], v))
        return out
    inside_hi = [None if mean[j] is None or not sd[j] else c[j] < mean[j] + 2 * sd[j] for j in range(S["n"])]     # back inside after a long break
    inside_lo = [None if mean[j] is None or not sd[j] else c[j] > mean[j] - 2 * sd[j] for j in range(S["n"])]     # back inside after a short break
    for i in range(max(first, 1), S["n"]):
        if mean[i] is None or not sd[i] or mean[i - 1] is None or not sd[i - 1]:
            continue
        up_now, up_prev = mean[i] + 2 * sd[i], mean[i - 1] + 2 * sd[i - 1]
        dn_now, dn_prev = mean[i] - 2 * sd[i], mean[i - 1] - 2 * sd[i - 1]
        if c[i - 1] <= up_prev and c[i] > up_now:
            entry, sl = c[i], min(l[i], l[i - 1])
            if sl < entry:
                v = _net(sim(S, i, True, entry, sl, None, [bool(x) for x in inside_hi]))
                if v is not None:
                    out.append((S["t"][i], v))
        elif c[i - 1] >= dn_prev and c[i] < dn_now:
            entry, sl = c[i], max(h[i], h[i - 1])
            if sl > entry:
                v = _net(sim(S, i, False, entry, sl, None, [bool(x) for x in inside_lo]))
                if v is not None:
                    out.append((S["t"][i], v))
    return out


# ---------------------------------------------------------------- band touch statistics (support / resistance evidence)
def touch_stats(S, first):
    """{(k, 'upper'|'lower'): [reversed, broke, nothing]} - after the FIRST touch of the k-SD band, within TOUCH_WINDOW candles does the
    close come back 0.5 SD toward the mean (reversed) or go 0.5 SD beyond the band (broke)? Pure chance would be about 50 / 50."""
    c, h, l, mean, sd, n = S["c"], S["h"], S["l"], S["mean"], S["sd"], S["n"]
    res = {(k, s): [0, 0, 0] for k in (1, 2, 3) for s in ("upper", "lower")}
    for i in range(max(first, 1), n - TOUCH_WINDOW):
        if mean[i] is None or not sd[i] or mean[i - 1] is None or not sd[i - 1]:
            continue
        for k in (1, 2, 3):
            for side in ("upper", "lower"):
                sg = 1 if side == "upper" else -1
                lvl, lvl_p = mean[i] + sg * k * sd[i], mean[i - 1] + sg * k * sd[i - 1]
                touched = (h[i] >= lvl and h[i - 1] < lvl_p) if sg == 1 else (l[i] <= lvl and l[i - 1] > lvl_p)
                if not touched:
                    continue
                brk, rej = lvl + sg * 0.5 * sd[i], lvl - sg * 0.5 * sd[i]
                out = 2
                for j in range(i, i + TOUCH_WINDOW + 1):
                    if (c[j] >= brk) if sg == 1 else (c[j] <= brk):
                        out = 1
                        break
                    if (c[j] <= rej) if sg == 1 else (c[j] >= rej):
                        out = 0
                        break
                res[(k, side)][out] += 1
    return res


# ---------------------------------------------------------------- judging
def judge(trades):
    """trades: [(t, net)] -> stats + verdict vs ZERO (is the average trade clearly positive after fees in BOTH halves?)."""
    trades = sorted(trades)
    n = len(trades)
    if n == 0:
        return {"n": 0, "verdict": "no_trades"}
    v = [x[1] for x in trades]
    cut = int(n * FL.OLD_SHARE)
    old, new = v[:cut], v[cut:]
    out = {"n": n, "net": round(sum(v), 1), "avg": round(sum(v) / n, 2), "win": round(100.0 * sum(1 for x in v if x > 0) / n, 1),
           "avg_old": round(sum(old) / len(old), 2) if old else 0.0, "avg_new": round(sum(new) / len(new), 2) if new else 0.0,
           "n_old": len(old), "n_new": len(new)}
    gains, losses = sum(x for x in v if x > 0), -sum(x for x in v if x < 0)
    out["pf"] = round(gains / losses, 2) if losses > 0 else None
    zo, zn = FL._paired_z(old), FL._paired_z(new)
    if len(old) < 30 or len(new) < 15:
        out["verdict"] = "too_few"
    elif zo >= FL.Z_OLD and zn >= FL.Z_NEW:
        out["verdict"] = "winner"
    elif zo <= -FL.Z_OLD and zn <= -FL.Z_NEW:
        out["verdict"] = "loser"
    else:
        out["verdict"] = "unclear"
    return out


# ---------------------------------------------------------------- run
def _fetch(sym, tf, days):
    from recovered_bot import ai_shadow_lab as LAB
    start = int(time.time() * 1000) - days * 86_400_000 - WARM * TF_MS[tf]
    cs = LAB._fetch_range(sym, tf, start, max_pages=60)
    return cs if cs and len(cs) > WARM + 50 else None



def run_step(group, tf, coins, days, cache, log):
    """-> ({scenario_key: [(t, net)]}, touch totals, coins_used)"""
    trades, touch, used = {}, {}, 0
    since = int(time.time() * 1000) - days * 86_400_000
    for n, sym in enumerate(coins, 1):
        key = (sym, tf)
        if key not in cache:
            cache[key] = _fetch(sym, tf, days)
            time.sleep(0.01)
        cs = cache[key]
        if not cs:
            log(f"{group} {tf} [{n}/{len(coins)}] {sym}: no candles")
            continue
        S = build(cs)
        first = next((i for i, t in enumerate(S["t"]) if t >= since), S["n"])
        first = max(first, 200)
        used += 1
        for line, _ in LINES:
            for ex, _ in EXITS:
                trades.setdefault(f"{line}|{ex}", []).extend(trend_trades(S, line, ex, first))
        for bk, _ in BAND_SC:
            trades.setdefault(f"band|{bk}", []).extend(band_trades(S, bk, first))
        for k, v in touch_stats(S, first).items():
            t = touch.setdefault(k, [0, 0, 0])
            for a in range(3):
                t[a] += v[a]
        log(f"{group} {tf} [{n}/{len(coins)}] {sym}")
    return trades, touch, used


def _title(key):
    if key.startswith("band|"):
        return dict(BAND_SC)[key[5:]]
    line, ex = key.split("|")
    return f"{dict(LINES)[line]} cross | {dict(EXITS)[ex]}"


def build_report(results, touches, meta):
    """results: {(group, tf): {key: judge-dict}}; touches: {(group, tf): {(k, side): [rev, brk, none]}}"""
    L = [f"SCAN LAB - made {time.strftime('%Y-%m-%d %H:%M')} | leverage {LEV:.0f}x, fee {FEE}% ROI per trade, net = ROI points after fee",
         "Replay on Binance candles, no slippage, no max-open limit. Winner = average trade positive after fee in BOTH the older 60% and newer 40% of its trades.",
         "Honest limits: ~200 rows tested on the same data, so one lucky winner is possible; signals of different coins overlap in time, so the 'clearly' is softer than it looks.",
         "MOVERS = today's top gainers/losers, picked with hindsight of today's big moves, so movers results look better than live trading would. MAJORS have no such bias.",
         f"Coins: MAJORS = {', '.join(c.replace('USDT', '') for c in MAJORS)}; MOVERS = {meta.get('movers', 'not run')}", ""]
    winners = []
    for (g, tf), rows in results.items():
        for key, j in rows.items():
            if j.get("verdict") == "winner":
                winners.append((j["avg"], g, tf, key, j))
    L.append("WINNERS (positive in BOTH halves, after fees):")
    if winners:
        for avg, g, tf, key, j in sorted(winners, key=lambda x: -x[0]):
            L.append(f"  {g} {tf} | {_title(key)} | {j['n']} trades, avg {j['avg']:+.2f}/trade (older {j['avg_old']:+.2f}, newer {j['avg_new']:+.2f}), win {j['win']}%, net {j['net']:+.0f}")
    else:
        L.append("  none. No setup was clearly profitable after fees in both halves.")
    L.append("")
    for (g, tf), rows in results.items():
        base = rows.get("ema50|run_tight")
        L.append(f"=== {g} | {tf} | {meta.get('days', {}).get(tf, '?')} days | coins used {meta.get('used', {}).get((g, tf), '?')} ===")
        if base:
            L.append(f"  BOT-LIKE BASELINE (EMA50 cross, tight SL, hold till opposite): {base.get('n', 0)} trades, avg {base.get('avg', 0):+.2f}, win {base.get('win', 0)}%")
        ranked = sorted(((k, j) for k, j in rows.items() if j.get("n")), key=lambda kv: -kv[1]["avg"])
        L.append("  row | trades | avg/trade | older / newer | win% | verdict")
        for key, j in ranked[:6] + [x for x in ranked[-2:] if x not in ranked[:6]]:
            L.append(f"  {_title(key)} | {j['n']} | {j['avg']:+.2f} | {j['avg_old']:+.2f} / {j['avg_new']:+.2f} | {j['win']} | {j['verdict']}")
        tc = touches.get((g, tf))
        if tc:
            L.append("  SD BAND TOUCH (after first touch, within 12 candles: reversed vs broke; chance would be ~50/50):")
            for k in (1, 2, 3):
                for side in ("upper", "lower"):
                    r, b, nn = tc.get((k, side), [0, 0, 0])
                    if r + b >= 20:
                        L.append(f"    {k}SD {side}: n={r + b + nn} | reversed {100.0 * r / (r + b):.0f}% | broke {100.0 * b / (r + b):.0f}%")
        L.append("")
    L.append("HOW TO USE: look at WINNERS first. Then compare MAJORS vs MOVERS for the same timeframe. If a setup only wins on MOVERS, treat it as luck of the coin choice.")
    return "\n".join(L)


def _paths():
    base = os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/owl_data")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "scan_lab.txt"), os.path.join(base, "scan_lab.json")


# ---------------------------------------------------------------- SD LENGTH test (200 candles today vs 100 / 50 / 150)
SD_LENS = [50, 100, 150, 200]                    # 200 = the bot today
TF_MIN = {"3m": 3, "5m": 5, "15m": 15, "1h": 60, "2h": 120}


def bot_sim(S, i, is_long, entry, sl, tps, opp):
    """The bot's live rule: SL = signal candle extreme, TP1-4, SL -> entry after TP1 (from the next candle), exit at TP4 / SL / opposite
    EMA50 cross. Also records after how many candles TP1..TP4 were touched. None = data ended while the trade was still open."""
    h, l, c, n = S["h"], S["l"], S["c"], S["n"]
    end = min(n - 1, i + MAX_FWD)
    cur, be, hit = sl, False, [None, None, None, None]
    px = why = bars = None
    for j in range(i + 1, end + 1):
        if (l[j] <= cur) if is_long else (h[j] >= cur):
            px, why, bars = cur, ("BE" if be else "SL"), j - i
            break
        for k in range(4):
            if hit[k] is None and ((h[j] >= tps[k]) if is_long else (l[j] <= tps[k])):
                hit[k] = j - i
        if hit[3] is not None:
            px, why, bars = tps[3], "TP", j - i
            break
        if opp[j]:
            px, why, bars = c[j], "REV", j - i
            break
        if not be and hit[0] is not None:
            cur, be = entry, True
    if px is None:
        if end - i < MAX_FWD:
            return None
        px, why, bars = c[end], "TIMEOUT", end - i
    ret = (px - entry) / entry * 100.0 * (1.0 if is_long else -1.0)
    return {"net": round(ret * LEV - FEE, 3), "why": why, "bars": bars, "hit": hit}


def sd_step(group, tf, coins, days, cache, log):
    """-> ({N: [(t, sym, result)]}, coins_used). Only signals that finished under EVERY SD length are kept, so all lengths see the same signals."""
    from recovered_bot import strategy as ST
    strat = ST.ABCDStrategy()
    out, used = {n: [] for n in SD_LENS}, 0
    since = int(time.time() * 1000) - days * 86_400_000
    for k, sym in enumerate(coins, 1):
        key = (sym, tf)
        if key not in cache:
            cache[key] = _fetch(sym, tf, days)
            time.sleep(0.01)
        cs = cache[key]
        if not cs:
            log(f"SD {group} {tf} [{k}/{len(coins)}] {sym}: no candles")
            continue
        S = build(cs)
        first = max(next((i for i, t in enumerate(S["t"]) if t >= since), S["n"]), 200)
        used += 1
        xup, xdn = cross_flags(S, "ema50")
        c, h, l = S["c"], S["h"], S["l"]
        ser = {n: (sma(c, n), rolling_sd(c, n)) for n in SD_LENS}
        for i in range(first, S["n"]):
            if not (xup[i] or xdn[i]):
                continue
            is_long = xup[i]
            entry = c[i]
            sl = l[i] if is_long else h[i]
            if (is_long and sl >= entry) or (not is_long and sl <= entry):
                continue
            res = {}
            for n in SD_LENS:
                m, sd = ser[n][0][i], ser[n][1][i]
                if m is None or not sd:
                    res = None
                    break
                lv = {"zero_price": m, "onesd": m + sd, "twosd": m + 2 * sd, "threesd": m + 3 * sd,
                      "neg_onesd": m - sd, "neg_twosd": m - 2 * sd, "neg_threesd": m - 3 * sd}
                tps = strat.calculate_tp_levels(entry, is_long, lv)
                if (is_long and tps[0] <= entry) or (not is_long and tps[0] >= entry):     # price already beyond the last band: no target
                    res = None
                    break
                r = bot_sim(S, i, is_long, entry, sl, tps, xdn if is_long else xup)
                if r is None:
                    res = None
                    break
                res[n] = r
            if res:
                for n in SD_LENS:
                    out[n].append((S["t"][i], sym, res[n]))
        log(f"SD {group} {tf} [{k}/{len(coins)}] {sym}")
    return out, used


def _med(v):
    return int(round(statistics.median(v))) if v else None


def sd_stats(rows, tf, used, days):
    """rows: {N: [(t, sym, result)]} -> list of one stats dict per SD length (+ paired comparison with 200)."""
    tfm = TF_MIN[tf]
    base = {(t, sym): r["net"] for t, sym, r in rows[200]}
    out = []
    for N in SD_LENS:
        rs = rows[N]
        n = len(rs)
        st = {"len": N, "n": n}
        if n:
            nets = [r["net"] for _, _, r in rs]
            hits = [[r["hit"][k] for _, _, r in rs] for k in range(4)]
            tp1 = [r for _, _, r in rs if r["hit"][0] is not None]
            back = [r for r in tp1 if r["hit"][3] is None]
            j = judge([(t, r["net"]) for t, _, r in rs])
            st.update({"avg": j["avg"], "win": j["win"], "net": j["net"], "verdict": j["verdict"],
                       "rate": round(n / max(used * days, 1), 2),
                       "tp1": round(100.0 * sum(1 for x in hits[0] if x is not None) / n, 1),
                       "tp2": round(100.0 * sum(1 for x in hits[1] if x is not None) / n, 1),
                       "tp4": round(100.0 * sum(1 for x in hits[3] if x is not None) / n, 1),
                       "n_tp1": len(tp1), "n_back": len(back),
                       "back": round(100.0 * len(back) / len(tp1), 1) if tp1 else None,
                       "min_tp1": (lambda m: None if m is None else m * tfm)(_med([x for x in hits[0] if x is not None])),
                       "min_tp4": (lambda m: None if m is None else m * tfm)(_med([x for x in hits[3] if x is not None])),
                       "min_hold": (lambda m: None if m is None else m * tfm)(_med([r["bars"] for _, _, r in rs]))})
        if N != 200 and n:
            d = sorted((t, r["net"] - base[(t, sym)]) for t, sym, r in rs if (t, sym) in base)
            cut = int(len(d) * FL.OLD_SHARE)
            do, dn = [x[1] for x in d[:cut]], [x[1] for x in d[cut:]]
            zo, zn = FL._paired_z(do), FL._paired_z(dn)
            if len(do) < 30 or len(dn) < 15:
                v = "too_few"
            elif zo >= FL.Z_OLD and zn >= FL.Z_NEW:
                v = "better"
            elif zo <= -FL.Z_OLD and zn <= -FL.Z_NEW:
                v = "worse"
            else:
                v = "unclear"
            st["vs200"] = round(sum(x[1] for x in d) / len(d), 2) if d else 0.0
            st["vs200_verdict"] = v
        out.append(st)
    return out


def sd_line(st):
    if not st.get("n"):
        return f"SD {st['len']}: no trades"
    f = lambda v: "-" if v is None else str(v)
    tag = " (bot today)" if st["len"] == 200 else ""
    vs = "" if st["len"] == 200 else f" | vs 200: {st.get('vs200', 0):+.2f} ({ {'better': 'BETTER', 'worse': 'WORSE', 'unclear': 'not clear', 'too_few': 'too few'}[st.get('vs200_verdict', 'unclear')] })"
    return (f"SD {st['len']}{tag}: {st['n']} trades ({st['rate']}/coin/day) | TP1 {st['tp1']:.0f}%, TP2 {st['tp2']:.0f}%, TP4 {st['tp4']:.0f}% | "
            f"hit TP1 but never TP4: {f(st['back'])}% | median minutes: TP1 {f(st['min_tp1'])}, TP4 {f(st['min_tp4'])}, whole trade {f(st['min_hold'])} | "
            f"avg {st['avg']:+.2f}, win {st['win']:.0f}%{vs}")


def sd_summary(per_tf):
    """per_tf: {tf: [stats]} -> short answer + per-timeframe lines for the app."""
    ans, tfs = [], []
    better, worse, bestlen = [], [], []
    agg = {n: {"n": 0, "tp1": 0, "tp4": 0, "n_tp1": 0, "n_back": 0} for n in SD_LENS}
    for tf, sts in per_tf.items():
        tfs.append({"tf": tf, "lines": [sd_line(x) for x in sts]})
        ok = [x for x in sts if x.get("n", 0) >= 30]
        if ok:
            b = max(ok, key=lambda x: x["avg"])
            bestlen.append(f"{tf} {b['len']}")
        for x in sts:
            if x["len"] == 100 and x.get("vs200_verdict") == "better":
                better.append(tf)
            if x["len"] == 100 and x.get("vs200_verdict") == "worse":
                worse.append(tf)
            if x.get("n"):
                a = agg[x["len"]]
                a["n"] += x["n"]
                a["tp1"] += round(x["tp1"] * x["n"] / 100.0)
                a["tp4"] += round(x["tp4"] * x["n"] / 100.0)
                a["n_tp1"] += x["n_tp1"]
                a["n_back"] += x["n_back"]
    if not per_tf:
        return {"answer": ["Nothing finished yet."], "tfs": []}
    if better:
        ans.append(f"SD 100 beat SD 200 in BOTH older and newer data on: {', '.join(better)}.")
    else:
        ans.append("SD 100 did not clearly beat SD 200 on any timeframe." + (f" SD 200 was clearly better on: {', '.join(worse)}." if worse else ""))
    if bestlen:
        ans.append("Best average trade by timeframe (SD length): " + ", ".join(bestlen) + ".")
    for n in (200, 100):
        a = agg[n]
        if a["n"] and a["n_tp1"]:
            ans.append(f"SD {n}{' (bot today)' if n == 200 else ''}: TP1 hit {100.0 * a['tp1'] / a['n']:.0f}%, TP4 hit {100.0 * a['tp4'] / a['n']:.0f}%, "
                       f"and {100.0 * a['n_back'] / a['n_tp1']:.0f}% of trades that touched TP1 never reached TP4 (all timeframes together).")
    ans.append("Signals are the same (EMA50 cross); only the TP levels move with the SD length. Same fees, same SL.")
    return {"answer": ans, "tfs": tfs}


def run_sd(tfs=None, groups=("MAJORS",), log=print):
    tfs = tfs or TFS
    coin_sets = {"MAJORS": MAJORS}
    per_tf, text = {}, []
    base = os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/owl_data")
    os.makedirs(base, exist_ok=True)
    for tf in tfs:
        cache = {}
        for g, coins in coin_sets.items():
            days = DAYS[tf]
            rows, used = sd_step(g, tf, coins, days, cache, log)
            per_tf[tf] = sd_stats(rows, tf, used, days)
            summ = sd_summary(per_tf)
            _STATE["sd"] = summ
            _STATE["sd_made"] = time.time()
            txt = ["SD LENGTH TEST (majors) - EMA50 cross signals, bot's SL and TP1-4, only the SD length changes. ROI points after fee (10x, 1%).", ""] + summ["answer"] + [""]
            for t in summ["tfs"]:
                txt += [f"=== {t['tf']} ({DAYS[t['tf']]} days) ==="] + t["lines"] + [""]
            with open(os.path.join(base, "scan_sd.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(txt))
            with open(os.path.join(base, "scan_sd.json"), "w", encoding="utf-8") as f:
                json.dump({"made": time.time(), "sd": summ}, f)
    return _STATE.get("sd")


_STATE = {"running": False, "progress": "", "mode": "", "summary": None, "made": None, "sd": None, "sd_made": None}
_LOCK = threading.Lock()


def _avg_line(rows):
    ok = [j for j in rows.values() if j.get("n", 0) >= 30]
    return max(ok, key=lambda j: j["avg"]) if ok else None


def summarize(results, touches, meta):
    """Short plain-language answer for the app card (the long report stays in scan_lab.txt)."""
    winners, steps, tested = [], [], 0
    for (g, tf), rows in results.items():
        tested += sum(1 for j in rows.values() if j.get("n", 0) >= 30)
        for key, j in rows.items():
            if j.get("verdict") == "winner":
                winners.append({"group": g, "tf": tf, "title": _title(key), "n": j["n"], "avg": j["avg"],
                                "avg_old": j["avg_old"], "avg_new": j["avg_new"], "win": j["win"]})
        base = rows.get("ema50|run_tight") or {}
        ranked = sorted(((k, j) for k, j in rows.items() if j.get("n", 0) >= 30), key=lambda kv: -kv[1]["avg"])
        best = ranked[0] if ranked else None
        steps.append({"group": g, "tf": tf, "base_n": base.get("n", 0), "base_avg": base.get("avg"),
                      "best": _title(best[0]) if best else None, "best_n": best[1]["n"] if best else 0,
                      "best_avg": best[1]["avg"] if best else None, "best_verdict": best[1]["verdict"] if best else None})
    winners.sort(key=lambda w: -w["avg"])
    ans = []
    if not results:
        ans.append("Nothing finished yet.")
    elif winners:
        w = winners[0]
        ans.append(f"{len(winners)} setup(s) won after fees in BOTH older and newer data. Best: {w['title']} on {w['group'].lower()} {w['tf']}, "
                   f"average {w['avg']:+.1f} ROI pts per trade.")
        only_movers = all(x["group"] == "MOVERS" for x in winners)
        if only_movers:
            ans.append("All winners are on MOVERS only. Movers are picked with hindsight, so do not trust them yet.")
    else:
        ans.append(f"No setup clearly won after fees ({tested} tested). So nothing is proven yet.")
    maj = {st["tf"]: st["base_avg"] for st in steps if st["group"] == "MAJORS" and st["base_avg"] is not None}
    if maj:
        ans.append("Bot today (EMA50 cross, tight SL) on majors, average per trade: " + ", ".join(f"{tf} {v:+.1f}" for tf, v in maj.items()) + ".")
    bests = {}
    for g in ("MAJORS", "MOVERS"):
        cands = [(j, tf) for (gg, tf), rows in results.items() if gg == g for j in [_avg_line(rows)] if j]
        if cands:
            j, tf = max(cands, key=lambda x: x[0]["avg"])
            bests[g] = (j["avg"], tf)
    if len(bests) == 2:
        ans.append(f"Best average trade: majors {bests['MAJORS'][0]:+.1f} ({bests['MAJORS'][1]}), movers {bests['MOVERS'][0]:+.1f} ({bests['MOVERS'][1]}). "
                   "If movers are far better, the coin list is doing the work, not the setup.")
    r = b = 0
    for tc in touches.values():
        for (k, side), v in tc.items():
            if k == 2:
                r += v[0]
                b += v[1]
    if r + b >= 50:
        pr = 100.0 * r / (r + b)
        word = ("bands look like support/resistance (price turns back more often)" if pr >= 58 else
                "bands do NOT hold, price usually breaks through" if pr <= 42 else "no clear support/resistance effect")
        ans.append(f"SD bands: after touching 2SD price turned back {pr:.0f}% and broke through {100 - pr:.0f}% ({r + b} touches). "
                   f"50/50 = no effect, so {word}.")
    return {"answer": ans, "winners": winners[:5], "n_winners": len(winners), "steps": steps, "tested": tested,
            "days": meta.get("days", {}), "movers": meta.get("movers")}


def run(tfs=None, groups=("MAJORS", "MOVERS"), log=print):
    tfs = tfs or TFS
    results, touches, meta, cache = {}, {}, {"days": {}, "used": {}}, {}
    coin_sets = {}
    if "MAJORS" in groups:
        coin_sets["MAJORS"] = MAJORS
    if "MOVERS" in groups:
        try:
            mv = [s for s in FL.default_coins(lambda m: None) if s not in MAJORS]
            coin_sets["MOVERS"] = mv
            meta["movers"] = ", ".join(s.replace("USDT", "") for s in mv)
        except Exception as e:
            log(f"movers list failed ({type(e).__name__}); only MAJORS will run")
    txt_path, json_path = _paths()
    rep = ""
    for tf in tfs:
        for g, coins in coin_sets.items():
            days = DAYS[tf]
            meta["days"][tf] = days
            trades, touch, used = run_step(g, tf, coins, days, cache, log)
            meta["used"][(g, tf)] = used
            results[(g, tf)] = {k: judge(v) for k, v in trades.items()}
            touches[(g, tf)] = touch
            rep = build_report(results, touches, meta)
            summ = summarize(results, touches, meta)
            _STATE["summary"], _STATE["made"] = summ, time.time()
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(rep)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({"made": time.time(), "summary": summ, "meta": {"days": meta["days"], "movers": meta.get("movers")},
                           "results": {f"{g}|{tf}": rows for (g, tf), rows in results.items()},
                           "touch": {f"{g}|{tf}": {f"{k}|{s}": v for (k, s), v in tc.items()} for (g, tf), tc in touches.items()}}, f)
        cache.clear()                                   # free memory before the next timeframe
    return rep if results else "no data"


# ---------------------------------------------------------------- background job for the app (/api/scan_lab)
def _worker(mode):
    try:
        if mode == "sd":
            run_sd(TFS, ("MAJORS",), log=lambda m: _STATE.__setitem__("progress", m))
        elif mode == "full":
            run(TFS, ("MAJORS", "MOVERS"), log=lambda m: _STATE.__setitem__("progress", m))
        else:
            run(["15m", "1h", "2h"], ("MAJORS",), log=lambda m: _STATE.__setitem__("progress", m))
        _STATE["progress"] = "done"
    except Exception as e:
        _STATE["progress"] = f"failed: {type(e).__name__}: {e}"
    finally:
        _STATE["running"] = False


def start(mode="quick"):
    """quick = 10 majors on 15m, 1h, 2h; full = majors + movers on 3m..2h (slow); sd = SD length 50/100/150/200 on majors, 3m..2h.
    Returns False if already running."""
    with _LOCK:
        if _STATE["running"]:
            return False
        try:
            import variant_lab
            if variant_lab._STATE.get("running"):
                _STATE["progress"] = "Strategy Lab is running, wait for it to finish and tap again."
                return False
        except Exception:
            pass
        _STATE.update(running=True, mode=mode, progress="starting...")
    threading.Thread(target=_worker, args=(mode,), daemon=True, name="scan_lab").start()
    return True


def status():
    if _STATE["summary"] is None:
        try:
            with open(_paths()[1], "r", encoding="utf-8") as f:
                d = json.load(f)
            _STATE["summary"], _STATE["made"] = d.get("summary"), d.get("made")
        except Exception:
            pass
    if _STATE["sd"] is None:
        try:
            with open(os.path.join(os.path.dirname(_paths()[1]), "scan_sd.json"), "r", encoding="utf-8") as f:
                d = json.load(f)
            _STATE["sd"], _STATE["sd_made"] = d.get("sd"), d.get("made")
        except Exception:
            pass
    age = int((time.time() - _STATE["made"]) / 60) if _STATE["made"] else None
    return {"running": _STATE["running"], "progress": _STATE["progress"], "mode": _STATE["mode"], "summary": _STATE["summary"], "age_min": age,
            "sd": _STATE["sd"]}


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    tfs = [t for t in (args[0].split(",") if args else TFS) if t in TFS] or TFS
    if "--sd" in argv:
        run_sd([t for t in (args[0].split(",") if args else TFS) if t in TFS] or TFS, ("MAJORS",), log=lambda m: print(m, flush=True))
        print(open(os.path.join(os.path.dirname(_paths()[1]), "scan_sd.txt"), encoding="utf-8").read())
        return 0
    groups = ("MAJORS",) if "--majors" in argv else ("MOVERS",) if "--movers" in argv else ("MAJORS", "MOVERS")
    rep = run(tfs, groups, log=lambda m: print(m, flush=True))
    print("\n" + rep)
    print(f"\nSaved: {_paths()[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
