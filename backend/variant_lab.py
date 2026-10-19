#!/usr/bin/env python3
"""
variant_lab.py - "Strategy Lab": ONE table that answers "what if the bot did X instead?". Read-only, own thread.

Idea in one line: take the bot's REAL signals (EMA50 cross, replayed on Binance candles with filter_lab.py), then re-run the SAME
signals under many scenarios and compare each one with the bot today:

  * Exit / stop-loss : wider SL, SL to entry + fee after TP1, exit at TP2, hold till the opposite signal (no TP4 exit)
  * Indicators       : TSI with the trade, Z with the trade, both agree, low chop (a scenario SKIPS some signals)
  * Bollinger        : squeeze / side / late / expanding (skips)
  * CVD (order flow) : taker buy-sell volume ("CVD proxy" from Binance candles, no extra data needed): does the money flow agree with
                       the signal? Also "wait 1 candle, then enter only if flow still agrees" (a control without CVD is shown too)
  * Bands            : EMA200 bands instead of SMA200 SD bands (TP levels move)
  * Combos           : a few mixes of the above

For each scenario the table shows: trades taken (vs the bot), net, win %, difference to the bot, "saved" (trades that got better),
"missed" (trades that got worse) and a verdict. A scenario is BETTER only when it beat the bot in BOTH the older 60% and the newer
40% of the signals. Nothing here changes the bot. It is a replay (no slippage), so it is evidence, not a promise.

  cd backend && python3 variant_lab.py 15m 14        # one timeframe, last 14 days
"""
import json
import math
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import filter_lab as FL

BIG = 1e18
TFS = ("3m", "5m", "15m")
OUT_GROUP = "Outside suggestion (4 points)"
NEW_GROUP = "Photo ideas (SD100, mean reversion, Kell)"
GROUP_ORDER = ["Exit and stop-loss", "Indicators (skip signals)", "Bollinger (skip signals)", "CVD (order flow)", "Bands", "Mixes", OUT_GROUP, NEW_GROUP]


# ---------------------------------------------------------------- CVD proxy (taker buy volume is already inside every Binance kline row)
def _patch_candles():
    """Makes the lab's candle reader keep the taker-buy volume (kline column 9) as c['tbv'] while Strategy Lab runs.
    Only adds one extra key to candle dicts; returns a function that puts the original reader back."""
    from recovered_bot import ai_shadow_lab as LAB
    orig = LAB._to_candles

    def with_tbv(raw, now_ms):
        out = orig(raw, now_ms)
        try:
            by_t = {int(r[0]): r for r in raw}
            for c in out:
                row = by_t.get(c["timestamp"])
                c["tbv"] = float(row[9]) if row is not None and len(row) > 9 else None
        except Exception:
            pass
        return out

    LAB._to_candles = with_tbv
    return lambda: setattr(LAB, "_to_candles", orig)


def _share(S, a, b):
    """taker delta share over candles a..b: (buy - sell volume) / volume, from -1 (all sellers) to +1 (all buyers). None = no data."""
    tb, vo = S.get("tbv"), S.get("vol")
    if not tb or not vo or a < 0 or b >= len(tb):
        return None
    d = v = 0.0
    for j in range(a, b + 1):
        if tb[j] is None or vo[j] is None:
            return None
        d += 2.0 * tb[j] - vo[j]
        v += vo[j]
    return round(d / v, 4) if v > 0 else None


def _agree(r, key, thr=0.0):
    """True = flow agrees with the trade side (or no CVD data: keep the signal, like the other gates)."""
    v = (r.get("cvd") or {}).get(key)
    if v is None:
        return True
    return v > thr if r["a"] == "BUY" else v < -thr


# ---------------------------------------------------------------- extra variants per signal (added while filter_lab collects)
def _ema200(S):
    e = S.get("_e200")
    if e is None:
        from recovered_bot import ai_ind_features as F
        e = S["_e200"] = F.ema(S["c"], 200, seed="sma")
    return e


def enrich(r, S, i, lev, fee):
    """r['x'] = {variant: [net ROI pts after fee, why, bars]} for exit / band variants. Same signal, same entry."""
    if not r.get("alt"):
        return
    is_long = r["a"] == "BUY"
    entry, base_sl, tps = r["e"], r["sl"], r["tp"]
    far = BIG if is_long else -BIG
    x = {}

    def put(key, sl, tp1, tp4):
        ret, why, bars = FL.sim_trade(S, i, is_long, entry, sl, tp1, tp4, 0.0)
        if why != "OPEN":
            x[key] = [round(ret * lev - fee, 3), why, bars]

    put("tp2", base_sl, tps[0], tps[1])                                   # leave at TP2
    put("run", base_sl, tps[0], far)                                      # no TP4 exit: SL / opposite cross only
    put("run_prev1", FL.sl_levels(S, i, is_long, entry, base_sl)["prev1"], tps[0], far)
    m, sd = _ema200(S)[i], S["std"][i]
    if m is not None and sd:                                              # SD ladder built around EMA200 instead of SMA200
        lv = [m + k * sd for k in (-3, -2, -1, 0, 1, 2, 3)]
        up = sorted(v for v in lv if v > entry)[:4] if is_long else sorted((v for v in lv if v < entry), reverse=True)[:4]
        if len(up) == 4:
            put("ema", base_sl, up[0], up[3])
    # --- CVD tags + "wait 1 candle" entry (same SL, same TP levels, enter at the CLOSE of the next candle if the signal still stands)
    n, c = S["n"], S["c"]
    cv = {"s1": _share(S, i, i), "s3": _share(S, i - 2, i)}
    j = i + 1
    if j < n:
        cv["w1"], cv["w2"] = _share(S, j, j), _share(S, i, j)
        e50, cj = S["e50"][j], c[j]
        still = e50 is not None and ((cj > e50 and cj > base_sl and cj < tps[0]) if is_long else (cj < e50 and cj < base_sl and cj > tps[0]))
        if still:
            ret, why, bars = FL.sim_trade(S, j, is_long, cj, base_sl, tps[0], tps[3], 0.0)
            if why != "OPEN":
                x["wait"] = [round(ret * lev - fee, 3), why, bars]
    # --- "outside suggestion" scenarios (4 points): tags, ATR-clamped stop, partial exits, confirmation candle
    try:
        ctx = _ctx(r, S, i)
        atr = ctx.get("atr")
        buf = fee / lev if lev else 0.0
        risk0 = abs(entry - base_sl)
        p0 = _partial(S, i, is_long, entry, base_sl, tps, buf)
        if p0 is not None:
            x["partial"] = [round(p0[0] * lev - fee, 3), p0[1], p0[2]]
        if atr and risk0 > 0:
            risk = min(max(risk0, 0.8 * atr), 1.8 * atr)
            sl2 = entry - risk if is_long else entry + risk
            if abs(tps[0] - entry) < risk:
                x["atr_clamp"] = None                                    # TP1 less than 1R with the new stop: skipped
                x["pkg"] = None
            else:
                ret, why, bars = FL.sim_trade(S, i, is_long, entry, sl2, tps[0], tps[3], 0.0)
                if why != "OPEN":
                    x["atr_clamp"] = [round(ret * lev - fee, 3), why, bars]
                p2 = _partial(S, i, is_long, entry, sl2, tps, buf)
                if p2 is not None:
                    x["pkg"] = [round(p2[0] * lev - fee, 3), p2[1], p2[2]]
        if i + 1 < S["n"]:
            ctx["confirm"] = (S["c"][i + 1] > S["c"][i]) if is_long else (S["c"][i + 1] < S["c"][i])
    except Exception:
        pass
    try:
        _enrich_new(r, S, i, lev, fee, x, is_long, entry, base_sl, tps)
    except Exception:
        pass
    r["cvd"] = cv
    r["x"] = x



# ---------------------------------------------------------------- photo ideas (read-only maths on the same candles, lab only)
def _ema_cached(S, n):
    k = f"_e{n}"
    e = S.get(k)
    if e is None:
        from recovered_bot import ai_ind_features as F
        e = S[k] = F.ema(S["c"], n, seed="sma")
    return e


def _enrich_new(r, S, i, lev, fee, x, is_long, entry, base_sl, tps):
    c, h, l = S["c"], S["h"], S["l"]
    # 1) SD100: the SD ladder built on a 100-candle mean / deviation instead of 200 (same SL, TP = next 4 bands)
    if i >= 100:
        w = c[i - 99:i + 1]
        m = sum(w) / 100.0
        sd = (sum((v - m) ** 2 for v in w) / 100.0) ** 0.5
        if sd > 0:
            lv = [m + k * sd for k in (-3, -2, -1, 0, 1, 2, 3)]
            up = sorted(v for v in lv if v > entry)[:4] if is_long else sorted((v for v in lv if v < entry), reverse=True)[:4]
            if len(up) == 4:
                ret, why, bars = FL.sim_trade(S, i, is_long, entry, base_sl, up[0], up[3], 0.0)
                if why != "OPEN":
                    x["sd100"] = [round(ret * lev - fee, 3), why, bars]
        # 2) mean reversion at the SD band: signal fired while price is already beyond the 2nd band in the trade's direction ->
        #    trade the OTHER way back to the mean (stop = 1 SD further out, target = the mean). Only these signals are traded.
        far2 = (entry > m + 2 * sd) if is_long else (entry < m - 2 * sd)
        if far2 and sd > 0:
            rev_long = not is_long
            sl_r = entry + sd if not rev_long else entry - sd
            tp1_r = entry + (m - entry) * 0.5
            ret, why, bars = FL.sim_trade(S, i, rev_long, entry, sl_r, tp1_r, m, 0.0)
            if why != "OPEN":
                x["meanrev"] = [round(ret * lev - fee, 3), why, bars]
    # 3) abnormal candle: the signal candle is a spike (range bigger than 3 x ATR) -> often a late chase
    a = FL._atr(S, i)
    ctx = r.get("ctx") or {}
    if a:
        ctx["spike"] = (h[i] - l[i]) > 3.0 * a
    # 4) Kell "base and break": the 8 candles before the signal were a tight base (range <= 2.5 ATR) and the signal candle closes beyond it
    if a and i >= 9:
        hi8, lo8 = max(h[i - 8:i]), min(l[i - 8:i])
        tight = (hi8 - lo8) <= 2.5 * a
        broke = (c[i] > hi8) if is_long else (c[i] < lo8)
        ctx["base_break"] = bool(tight and broke)
    # 5) Kell exit: stay in the trade until a candle CLOSES beyond BOTH EMA10 and EMA20 against it (no TP4 exit; stop as the bot)
    e10, e20 = _ema_cached(S, 10), _ema_cached(S, 20)
    end = min(S["n"] - 1, i + FL.MAX_FWD)
    got = None
    for j in range(i + 1, end + 1):
        if (l[j] <= base_sl) if is_long else (h[j] >= base_sl):
            got = (base_sl, "SL", j - i)
            break
        if e10[j] is not None and e20[j] is not None and ((c[j] < e10[j] and c[j] < e20[j]) if is_long else (c[j] > e10[j] and c[j] > e20[j])):
            got = (c[j], "EMA", j - i)
            break
    if got is not None:
        ret = (got[0] - entry) / entry * 100.0 * (1.0 if is_long else -1.0)
        x["kell_exit"] = [round(ret * lev - fee, 3), got[1], got[2]]
    r["ctx"] = ctx
    # 6) EMA30 / EMA200-SMA side filters (the bot's entry is EMA50 only, so these are FILTERS on its signals, not new entries)
    e30, e50 = _ema_cached(S, 30), S["e50"]
    if e30[i] is not None and e50[i] is not None:
        ctx["e30_side"] = (e30[i] > e50[i]) if is_long else (e30[i] < e50[i])
    sm = S.get("sma")
    if sm and sm[i] is not None:
        ctx["sma_side"] = (c[i] > sm[i]) if is_long else (c[i] < sm[i])


# ---------------------------------------------------------------- "outside suggestion" helpers (read-only maths on the same candles)
def _adx_series(S, period=14):
    """Wilder ADX per candle (same maths as recovered_bot/entry_context.adx), computed once per coin and cached."""
    a = S.get("_adx")
    if a is not None:
        return a
    h, l, c, n = S["h"], S["l"], S["c"], S["n"]
    a = [None] * n
    if n > period * 2 + 1:
        tr, pdm, mdm = [0.0], [0.0], [0.0]
        for i in range(1, n):
            up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
            pdm.append(up if (up > dn and up > 0) else 0.0)
            mdm.append(dn if (dn > up and dn > 0) else 0.0)
            tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
        s_tr, s_p, s_m = sum(tr[1:period + 1]), sum(pdm[1:period + 1]), sum(mdm[1:period + 1])
        dx = {}
        for i in range(period, n):
            if i > period:
                s_tr = s_tr - s_tr / period + tr[i]
                s_p = s_p - s_p / period + pdm[i]
                s_m = s_m - s_m / period + mdm[i]
            if s_tr <= 0:
                dx[i] = 0.0
                continue
            pdi, mdi = 100.0 * s_p / s_tr, 100.0 * s_m / s_tr
            dx[i] = 100.0 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0.0
        first = period * 2 - 1
        if first < n:
            cur = sum(dx[k] for k in range(period, period * 2)) / period
            a[first] = cur
            for i in range(first + 1, n):
                cur = (cur * (period - 1) + dx[i]) / period
                a[i] = cur
    S["_adx"] = a
    return a


def _htf(S, i, factor=5, ema_len=20, window=600):
    """Higher-timeframe trend like recovered_bot/entry_context.htf_trend: 'up' / 'down' / 'flat' / None (approximate)."""
    c = S["c"][max(0, i + 1 - window):i + 1]
    m = len(c) // factor
    if m < ema_len + 3:
        return None
    start = len(c) - m * factor
    closes = [c[start + (k + 1) * factor - 1] for k in range(m)]
    kk = 2.0 / (ema_len + 1)
    e = sum(closes[:ema_len]) / ema_len
    ser = [e]
    for x in closes[ema_len:]:
        e = x * kk + e * (1 - kk)
        ser.append(e)
    last, back = ser[-1], ser[-3]
    if last <= 0:
        return None
    slope = (last - back) / last * 100.0
    if closes[-1] > last and slope > 0.02:
        return "up"
    if closes[-1] < last and slope < -0.02:
        return "down"
    return "flat"


def _partial(S, i, is_long, entry, sl, tps, be_pct, fracs=(0.4, 0.3, 0.2, 0.1)):
    """Partial exits: 40% at TP1, 30% at TP2, 20% at TP3, 10% at TP4. After TP1 the SL moves to entry (+ fee buffer) from the NEXT candle.
    The rest leaves at the SL, or at the close of an opposite EMA50 cross. Returns [ret % of price, why, bars] or None while still open."""
    h, l, c, n = S["h"], S["l"], S["c"], S["n"]
    end = min(n - 1, i + FL.MAX_FWD)
    opp = S["xdn"] if is_long else S["xup"]
    be_px = entry * (1 + be_pct / 100.0) if is_long else entry * (1 - be_pct / 100.0)
    if (is_long and be_px >= tps[0]) or (not is_long and be_px <= tps[0]):
        be_px = entry
    sign = 1.0 if is_long else -1.0
    left, tot, hit, cur, be = 1.0, 0.0, 0, sl, False
    for j in range(i + 1, end + 1):
        if (l[j] <= cur) if is_long else (h[j] >= cur):
            tot += left * (cur - entry) / entry * 100.0 * sign
            return [tot, "BE" if be else "SL", j - i]
        newhit = False
        while hit < 4 and ((h[j] >= tps[hit]) if is_long else (l[j] <= tps[hit])):
            part = fracs[hit]
            tot += part * (tps[hit] - entry) / entry * 100.0 * sign
            left -= part
            hit += 1
            newhit = True
        if hit >= 4 or left <= 1e-9:
            return [tot, "TP", j - i]
        if opp[j]:
            tot += left * (c[j] - entry) / entry * 100.0 * sign
            return [tot, "REV", j - i]
        if newhit and not be and hit >= 1 and ((be_px > cur) if is_long else (be_px < cur)):
            cur, be = be_px, True
    if end - i >= FL.MAX_FWD:
        tot += left * (c[end] - entry) / entry * 100.0 * sign
        return [tot, "TIMEOUT", end - i]
    return None


def _ctx(r, S, i):
    """r['ctx']: the values the 4-point suggestion looks at, measured at the signal candle."""
    is_long = r["a"] == "BUY"
    entry, sl, tps = r["e"], r["sl"], r["tp"]
    ctx = {}
    adx = _adx_series(S)
    ctx["adx"] = round(adx[i], 2) if adx[i] is not None else None
    ctx["htf"] = _htf(S, i)
    e50 = S["e50"]
    if e50[i] is not None and i >= 3 and e50[i - 3]:
        ctx["slope"] = (e50[i] - e50[i - 3]) / e50[i - 3] * 100.0
    a = FL._atr(S, i)
    ctx["atr"] = a
    if a and e50[i] is not None:
        ctx["gap"] = abs(S["c"][i] - e50[i]) / a
    vol = S.get("vol")
    if vol and i >= 20 and all(v is not None for v in vol[i - 20:i + 1]):
        avg = sum(vol[i - 20:i]) / 20.0
        if avg > 0:
            ctx["volr"] = vol[i] / avg
    r["ctx"] = ctx
    return ctx


def _agree_dir(r, key, up_when_long=True):
    v = (r.get("ctx") or {}).get(key)
    if v is None:
        return True
    return v > 0 if r["a"] == "BUY" else v < 0


def _g_adx(r):
    v = (r.get("ctx") or {}).get("adx")
    return v is None or v >= 20.0


def _g_htf(r):
    v = (r.get("ctx") or {}).get("htf")
    return v is None or v == ("up" if r["a"] == "BUY" else "down")


def _g_slope(r):
    return _agree_dir(r, "slope")


def _g_vol(r):
    v = (r.get("ctx") or {}).get("volr")
    return v is None or v >= 1.1


def _g_gap(r):
    v = (r.get("ctx") or {}).get("gap")
    return v is None or v <= 0.75


def _g_1r(r):
    return FL._g_reward(r)


def _g_bundle(r):
    return all(f(r) for f in (_g_adx, _g_htf, _g_slope, FL._g_chop, _g_vol, _g_gap, _g_1r))


def _xs(key):
    """scenario value that can also SKIP: key missing = data problem (use the bot's value), key stored as None = the scenario skipped it."""
    def fn(r):
        x = r.get("x") or {}
        if key not in x:
            return _b(r)
        return None if x[key] is None else x[key][0]
    return fn


def _confirm(r):
    """wait 1 candle, enter only if that candle also CLOSED beyond the cross candle's close (a real follow-through)."""
    return _wait(r) if (r.get("ctx") or {}).get("confirm", True) else None


def _pkg(r):
    return _xs("pkg")(r) if _g_bundle(r) else None


# ---------------------------------------------------------------- scenarios: fn(row) -> net of the scenario, or None = signal skipped
def _b(r):
    return r["alt"]["base|be0"][0]


def _alt(key):
    return lambda r: r["alt"][key][0] if key in r["alt"] else _b(r)


def _x(key):
    return lambda r: r["x"][key][0] if key in (r.get("x") or {}) else _b(r)


def _gate(fn):
    return lambda r: _b(r) if fn(r) else None


def _wait(r):
    """'wait 1 candle' scenario: net of the delayed entry, or None when the signal no longer stood one candle later (skipped)."""
    w = (r.get("x") or {}).get("wait")
    return w[0] if w else None


def _wait_cvd(r):
    return _wait(r) if _agree(r, "w1") and _agree(r, "w2") else None


def _both(r):
    return FL._g_tsi_line(r) and FL._g_z_moving(r)


SCENARIOS = [
    ("Exit and stop-loss", "sl_prev1", "Wider SL: previous candle", _alt("prev1|be0")),
    ("Exit and stop-loss", "sl_prev3", "Wider SL: last 3 candles", _alt("prev3|be0")),
    ("Exit and stop-loss", "sl_swing", "Wider SL: last 10 candles", _alt("swing10|be0")),
    ("Exit and stop-loss", "sl_atr", "Wider SL: 1.5 x ATR", _alt("atr15|be0")),
    ("Exit and stop-loss", "be_fee", "After TP1: SL to entry + fee", _alt("base|bef")),
    ("Exit and stop-loss", "tp2", "Exit at TP2 (not TP4)", _x("tp2")),
    ("Exit and stop-loss", "run", "Hold till opposite signal (no TP4 exit)", _x("run")),
    ("Exit and stop-loss", "run_prev1", "Hold till opposite + wider SL (prev candle)", _x("run_prev1")),
    ("Indicators (skip signals)", "tsi", "TSI with the trade", _gate(FL._g_tsi_line)),
    ("Indicators (skip signals)", "zmove", "Z moving with the trade", _gate(FL._g_z_moving)),
    ("Indicators (skip signals)", "zrule", "No long below mean / no short above", _gate(FL._g_z_user)),
    ("Indicators (skip signals)", "both", "TSI and Z both agree", _gate(_both)),
    ("Indicators (skip signals)", "chop", "Low chop (max 2 EMA50 crosses)", _gate(FL._g_chop)),
    ("Bollinger (skip signals)", "bb_sq", "Skip squeeze (sideways)", _gate(FL._g_bb_squeeze)),
    ("Bollinger (skip signals)", "bb_side", "Long above / short below mid band", _gate(FL._g_bb_side)),
    ("Bollinger (skip signals)", "bb_late", "Skip late (outside band)", _gate(FL._g_bb_not_late)),
    ("Bollinger (skip signals)", "bb_exp", "Only when bands expanding", _gate(FL._g_bb_expanding)),
    ("CVD (order flow)", "cvd3", "CVD agrees with the trade (last 3 candles)", _gate(lambda r: _agree(r, "s3"))),
    ("CVD (order flow)", "cvd_push", "Signal candle pushed by real flow (>=10%)", _gate(lambda r: _agree(r, "s1", 0.10))),
    ("CVD (order flow)", "cvd_exp", "CVD agrees + only when bands expanding",
     _gate(lambda r: _agree(r, "s3") and FL._g_bb_expanding(r))),
    ("CVD (order flow)", "wait", "Wait 1 candle, then enter (no CVD, control)", _wait),
    ("CVD (order flow)", "wait_cvd", "Wait 1 candle + CVD still agrees", _wait_cvd),
    ("CVD (order flow)", "run_cvd", "Hold till opposite + CVD agrees",
     lambda r: _x("run")(r) if _agree(r, "s3") else None),
    ("Bands", "ema", "EMA200 bands instead of SMA200 SD bands", _x("ema")),
    ("Mixes", "mix1", "Wider SL (prev) + skip squeeze",
     lambda r: _alt("prev1|be0")(r) if FL._g_bb_squeeze(r) else None),
    ("Mixes", "mix2", "TSI and Z agree + wider SL (prev)",
     lambda r: _alt("prev1|be0")(r) if _both(r) else None),
    ("Mixes", "mix3", "Hold till opposite + TSI with trade",
     lambda r: _x("run")(r) if FL._g_tsi_line(r) else None),
    ("Mixes", "mix4", "Hold till opposite + wider SL + skip squeeze",
     lambda r: _x("run_prev1")(r) if FL._g_bb_squeeze(r) else None),
    (OUT_GROUP, "o_adx", "Trend strength: ADX 20 or more", _gate(_g_adx)),
    (OUT_GROUP, "o_htf", "Higher-timeframe trend agrees", _gate(_g_htf)),
    (OUT_GROUP, "o_slope", "EMA50 slope agrees with the trade", _gate(_g_slope)),
    (OUT_GROUP, "o_vol", "Volume at least 1.1x of last 20 candles", _gate(_g_vol)),
    (OUT_GROUP, "o_gap", "Price not stretched from EMA50 (0.75 ATR)", _gate(_g_gap)),
    (OUT_GROUP, "o_1r", "TP1 at least 1R away", _gate(_g_1r)),
    (OUT_GROUP, "o_bundle", "All filters together (ADX+HTF+slope+chop+vol+gap+1R)", _gate(_g_bundle)),
    (OUT_GROUP, "o_atr", "ATR stop (0.8 to 1.8 ATR), skip if TP1 < 1R", _xs("atr_clamp")),
    (OUT_GROUP, "o_part", "Partial exits 40/30/20/10 at TP1-TP4", _xs("partial")),
    (OUT_GROUP, "o_conf", "Wait 1 candle, enter only if it closes beyond", _confirm),
    (OUT_GROUP, "o_pkg", "FULL PACKAGE: filters + ATR stop + partial exits", _pkg),
    (NEW_GROUP, "sd100", "SD100: SD bands on 100 candles instead of 200", _x("sd100")),
    (NEW_GROUP, "meanrev", "Mean reversion: signal beyond 2nd SD band -> trade back to the mean", lambda r: (r.get("x") or {}).get("meanrev", [None])[0]),
    (NEW_GROUP, "nospike", "Skip spike candle (signal candle bigger than 3 ATR)", _gate(lambda r: not (r.get("ctx") or {}).get("spike", False))),
    (NEW_GROUP, "e30side", "EMA30 on the trade's side of EMA50 (filter)", _gate(lambda r: (r.get("ctx") or {}).get("e30_side", True))),
    (NEW_GROUP, "smaside", "Price on the trade's side of SMA200 (filter)", _gate(lambda r: (r.get("ctx") or {}).get("sma_side", True))),
    (NEW_GROUP, "kell_base", "Kell: take only a break out of a tight base", _gate(lambda r: (r.get("ctx") or {}).get("base_break", False))),
    (NEW_GROUP, "kell_exit", "Kell exit: leave when price closes beyond EMA10 and EMA20", _x("kell_exit")),
    (NEW_GROUP, "kell_mix", "Kell base break + Kell exit", lambda r: _x("kell_exit")(r) if (r.get("ctx") or {}).get("base_break", False) else None),
]


# ---------------------------------------------------------------- the table
def _line(vals):
    n = len(vals)
    if not n:
        return {"n": 0, "net": 0.0, "avg": 0.0, "win": 0.0}
    return {"n": n, "net": round(sum(vals), 1), "avg": round(sum(vals) / n, 2),
            "win": round(100.0 * sum(1 for v in vals if v > 0) / n, 1)}


def analyse(rows):
    """rows: filter_lab replay rows (after enrich). -> {"n", "bot", "rows": [...], "answer": [...]}"""
    rs = [r for r in rows if r.get("alt")]
    if len(rs) < 40:
        return {"n": len(rs), "ok": False, "answer": [f"Only {len(rs)} usable signals - too few to compare. Run again later or use more days."]}
    old, new = FL.split_rows(rs)
    bot = _line([_b(r) for r in rs])
    out = {"ok": True, "n": len(rs), "n_old": len(old), "n_new": len(new), "bot": bot, "rows": []}
    for group, key, title, fn in SCENARIOS:
        vo = [fn(r) for r in old]
        vn = [fn(r) for r in new]
        do = [(0.0 if v is None else v) - _b(r) for v, r in zip(vo, old)]
        dn = [(0.0 if v is None else v) - _b(r) for v, r in zip(vn, new)]
        taken = [v for v in vo + vn if v is not None]
        d = do + dn
        zo, zn = FL._paired_z(do), FL._paired_z(dn)
        ch_o, ch_n = sum(1 for x in do if abs(x) > 1e-9), sum(1 for x in dn if abs(x) > 1e-9)
        if len(old) < FL.MIN_PAIR_OLD or len(new) < FL.MIN_PAIR_NEW or ch_o < FL.MIN_SKIP_OLD or ch_n < FL.MIN_SKIP_NEW:
            verdict = "not_enough"
        elif zo >= FL.Z_OLD and zn >= FL.Z_NEW:
            verdict = "better"
        elif zo <= -FL.Z_OLD and zn <= -FL.Z_NEW:
            verdict = "worse"
        else:
            verdict = "unclear"
        ln = _line(taken)
        out["rows"].append({
            "group": group, "key": key, "title": title, "taken": ln["n"], "net": ln["net"], "avg": ln["avg"], "win": ln["win"],
            "vs_bot": round(sum(d), 1), "saved": round(sum(x for x in d if x > 0), 1), "missed": round(-sum(x for x in d if x < 0), 1),
            "d_old": round(sum(do) / len(do), 2) if do else 0.0, "d_new": round(sum(dn) / len(dn), 2) if dn else 0.0,
            "verdict": verdict})
    better = sorted((r for r in out["rows"] if r["verdict"] == "better"), key=lambda r: -r["vs_bot"])
    unclear_pos = sorted((r for r in out["rows"] if r["verdict"] == "unclear" and r["vs_bot"] > 0), key=lambda r: -r["vs_bot"])
    ans = [f"Bot today: {bot['n']} trades, net {bot['net']} ROI pts after fees, win {bot['win']}%."]
    if better:
        ans.append("Beat the bot in BOTH older and newer data: " + "; ".join(f"{r['title']} ({r['vs_bot']:+.0f})" for r in better[:3]) + ".")
        ans.append("Keep the best one on paper for a few days before using it. Many tests on the same data can still give a lucky winner.")
    else:
        ans.append("No scenario beat the bot in BOTH halves. So nothing is proven yet.")
        if unclear_pos:
            ans.append("Looked a little better but not proven: " + "; ".join(f"{r['title']} ({r['vs_bot']:+.0f})" for r in unclear_pos[:3]) + ".")
    out["answer"] = ans
    return out


# ---------------------------------------------------------------- text version (terminal / report)
def text_report(res, tf, days):
    L = [f"STRATEGY LAB - {tf} candles, last {days} days (net = ROI pts after fee; replay, no slippage)"]
    L += res.get("answer", [])
    if res.get("ok"):
        L.append("scenario | trades | net | win% | vs bot | saved | missed | verdict")
        for g in GROUP_ORDER:
            for r in res["rows"]:
                if r["group"] == g:
                    L.append(f"[{g}] {r['title']} | {r['taken']} | {r['net']} | {r['win']} | {r['vs_bot']:+} | {r['saved']} | {r['missed']} | {r['verdict']}")
    return "\n".join(L)


# ---------------------------------------------------------------- background job + saved result (survives a restart)
_STATE = {"running": False, "progress": "", "tfs": {}, "days": 14}
_LOCK = threading.Lock()


def _file():
    base = os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/owl_data")
    return os.path.join(base, "variant_lab.json")


def _load():
    try:
        with open(_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("tfs"), dict):
            _STATE["tfs"] = d["tfs"]
            _STATE["days"] = int(d.get("days", 14))
    except Exception:
        pass


def _save():
    try:
        os.makedirs(os.path.dirname(_file()), exist_ok=True)
        tmp = _file() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"tfs": _STATE["tfs"], "days": _STATE["days"]}, f)
        os.replace(tmp, _file())
    except Exception:
        pass


def _worker(days, lev, fee):
    FL.EXTRA_ENRICH = enrich
    restore = None
    try:
        restore = _patch_candles()
        coins = FL.default_coins(lambda m: None)
        for tf in TFS:
            def log(m, tf=tf):
                _STATE["progress"] = f"{tf}: {m}"
            try:
                rows = FL.collect(tf, days, coins, lev, fee, log)
                res = analyse(rows)
            except Exception as e:
                res = {"ok": False, "n": 0, "answer": [f"{tf} failed: {type(e).__name__}: {e}"]}
            res["t"] = time.time()
            res["days"] = days
            with _LOCK:
                _STATE["tfs"][tf] = res
            _save()
    except Exception as e:
        _STATE["progress"] = f"failed: {type(e).__name__}: {e}"
    finally:
        FL.EXTRA_ENRICH = None
        if restore:
            restore()
        _STATE["running"] = False


def start(days=14, lev=10.0, fee=1.0):
    """starts 3m, 5m, 15m one after the other in ONE thread. Returns False if already running."""
    with _LOCK:
        if _STATE["running"]:
            return False
        _STATE["running"] = True
        _STATE["days"] = int(days)
        _STATE["progress"] = "starting..."
    threading.Thread(target=_worker, args=(int(days), float(lev), float(fee)), daemon=True, name="variant_lab").start()
    return True


def status():
    if not _STATE["tfs"] and not _STATE["running"]:
        _load()
    out = {"running": _STATE["running"], "progress": _STATE["progress"], "days": _STATE["days"], "tfs": {}}
    for tf in TFS:
        r = _STATE["tfs"].get(tf)
        if r is None:
            out["tfs"][tf] = {"state": "not run"}
        else:
            out["tfs"][tf] = dict(r, state="done", age_min=int((time.time() - r.get("t", time.time())) / 60))
    return out


def main(argv):
    tf = argv[1] if len(argv) > 1 else "15m"
    days = int(argv[2]) if len(argv) > 2 else 14
    if tf not in FL.TF_MS:
        print("timeframe must be 3m, 5m or 15m")
        return 1
    FL.EXTRA_ENRICH = enrich
    restore = _patch_candles()
    try:
        rows = FL.collect(tf, days, FL.default_coins(), 10.0, 1.0)
    finally:
        restore()
    print("\n" + text_report(analyse(rows), tf, days))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
