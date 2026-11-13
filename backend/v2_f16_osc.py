"""v2_f16_osc.py - FILTER STUDY Part 18A: ZERO-LINE + STOCH + RSI gate test on the bot's own past paper trades (read-only, hindsight replay).
Owner ideas (13 Nov): (1) BUY only above the SD zero line, SELL only below it. (2) Stoch %D falling = no BUY, Stoch %D rising = no SELL. (3) a group idea: RSI side of 50, skip the middle, skip overbought.
Indicator = the old RRanjanFX Stoch+RSI: Stoch K 21, smooth 7, %D = SMA 7 of that; RSI length 10 (Wilder). All read at the SIGNAL candle (same candle store as Parts 6B / 13 / 17A).
GATES (side = +1 long, -1 short):
  Z0      price close on the right side of the SD centre line (S['sma']): long above, short below
  SLOPE   Stoch %D now against 3 candles ago: long passes when %D is not falling, short passes when %D is not rising
  RSI50   long needs RSI above 50, short needs RSI below 50
  SL+R    SLOPE and RSI50 together
  Z0+SL   Z0 and SLOPE together (the owner's two ideas)
  MID     CONTROL from the group idea: skip when RSI and %D are BOTH between 40 and 60 (assumed to cut the first signal after a flat spell)
  OB      CONTROL from the group idea: skip long when RSI >= 70 and %D >= 70, skip short when RSI <= 30 and %D <= 30 (assumed to cut long rallies)
  MID and OB are only here to SHOW the numbers; they are not proposals.
FOR EVERY GATE (ALL / LONG / SHORT, TRAIN = first 60% by time, TEST = last 40%), scopes all / 5m / 15m, two money bases:
  REAL   what the trade really made (no booking, the old bot)
  BOT    the same trade replayed with the bot's way now: 30% at TP1, the rest with a TRAIL_33 trail (stand-in)
numbers: trades per day kept, net of kept trades, BLOCKED, PROFIT MISSED (winners blocked), LOSS AVOIDED (losers blocked), net gain = loss avoided - profit missed,
RALLIES MISSED = blocked trades whose best ROI is in the top quarter (same definition as Part 7C) and the profit they carried.
VERDICT per gate: HELPS = net gain above 0 in TRAIN and TEST, 30+ blocked and 30+ kept in each half, and the gate does not cut rallies more than it cuts trades in general. HELPS_BUT_LOSES_RALLIES = net gain above 0 in both but it cuts rallies more than trades in general. FAILS / TOO_FEW otherwise.
7 gates x 3 sides x 2 bases x 3 scopes is a lot of looks: one HELPS can be luck. A HELPS is only a candidate for a LOG test (Part 15 real data decides). Main and Sniper are never added together. Paper trades only. Nothing here touches the bot.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f16_osc.py --data /home/owl/owl_data --out -     (runner id f16o)"""
import argparse
import bisect
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f6d_amd_low as D

A, BK, X, K, F, IP, E, I, P = D.A, D.BK, D.X, D.K, D.F, D.IP, D.E, D.I, D.P
VERSION = "v2_f16_osc 1 (Filter Part 18A)"
GATES, BASES, SIDES = ("Z0", "SLOPE", "RSI50", "SL+R", "Z0+SL", "MID", "OB"), ("REAL", "BOT"), D.SIDES
SCOPES = (("all", None), ("5m", "5m"), ("15m", "15m"))
MIN_HALF = 30
K_LEN, K_SMOOTH, D_LEN, SLOPE_BARS, RSI_LEN, WARM = 21, 7, 7, 3, 10, 150


def _raw_k(S, j):
    """Stoch raw K at candle j (0-100) or None."""
    if j < K_LEN - 1:
        return None
    hh, ll = max(S["h"][j - K_LEN + 1:j + 1]), min(S["l"][j - K_LEN + 1:j + 1])
    return 50.0 if hh <= ll else 100.0 * (S["c"][j] - ll) / (hh - ll)


def stoch_d(S, j):
    """%D at candle j = SMA(D_LEN) of SMA(K_SMOOTH) of the raw K, or None when there is not enough history."""
    if j < K_LEN - 1 + K_SMOOTH - 1 + D_LEN - 1:
        return None
    sm = []
    for t in range(j - D_LEN + 1, j + 1):
        ks = [_raw_k(S, x) for x in range(t - K_SMOOTH + 1, t + 1)]
        if any(v is None for v in ks):
            return None
        sm.append(sum(ks) / K_SMOOTH)
    return sum(sm) / D_LEN


def rsi_at(S, i0):
    """Wilder RSI(RSI_LEN) at candle i0 from at most WARM candles back, or None."""
    j0 = max(1, i0 - WARM + 1)
    if i0 - j0 < RSI_LEN * 3:
        return None
    c = S["c"]
    up = sum(max(c[x] - c[x - 1], 0.0) for x in range(j0, j0 + RSI_LEN)) / RSI_LEN
    dn = sum(max(c[x - 1] - c[x], 0.0) for x in range(j0, j0 + RSI_LEN)) / RSI_LEN
    for x in range(j0 + RSI_LEN, i0 + 1):
        ch = c[x] - c[x - 1]
        up = (up * (RSI_LEN - 1) + max(ch, 0.0)) / RSI_LEN
        dn = (dn * (RSI_LEN - 1) + max(-ch, 0.0)) / RSI_LEN
    if dn == 0:
        return 100.0
    if up == 0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + up / dn)


def gates(S, i0, side):
    """{gate: True / False / None} at the signal candle, or None when nothing can be computed."""
    sma = S["sma"][i0] if i0 >= 1 else None
    z0 = None if not sma else side * (S["c"][i0] - sma) > 0
    d_now = stoch_d(S, i0)
    d_old = stoch_d(S, i0 - SLOPE_BARS) if i0 - SLOPE_BARS >= 0 else None
    rsi = rsi_at(S, i0)
    slope = None if d_now is None or d_old is None else side * (d_now - d_old) >= 0
    r50 = None if rsi is None else side * (rsi - 50.0) > 0
    both = lambda a, b: None if a is None or b is None else (a and b)
    mid = None if rsi is None or d_now is None else not (40.0 <= rsi <= 60.0 and 40.0 <= d_now <= 60.0)
    if rsi is None or d_now is None:
        ob = None
    elif side == 1:
        ob = not (rsi >= 70.0 and d_now >= 70.0)
    else:
        ob = not (rsi <= 30.0 and d_now <= 30.0)
    out = {"Z0": z0, "SLOPE": slope, "RSI50": r50, "SL+R": both(slope, r50), "Z0+SL": both(z0, slope), "MID": mid, "OB": ob}
    return None if all(v is None for v in out.values()) else out


def replay_trade(S, i0, end0, r):
    side, ep, lev, inv, fee = r["side"], r.get("entry_price"), r.get("lev"), r.get("invest"), r.get("fee_roi")
    if not (side and ep and lev and inv and fee is not None) or end0 <= i0:
        return None
    gt = gates(S, i0, side)
    if gt is None:
        return None
    y5 = BK.replay_trade(S, i0, end0, r)
    if y5 is None:
        return None
    bot = y5["s"]["TRAIL_33|NONE|h0"]["n"][0] if y5.get("tp1") else y5["calib"]
    return {"BOT": round(bot, 4)}, gt


def replay_all(rows, con, cfg_by_tf, cov):
    """Same walk as Part 13 (one candle series per coin and timeframe), with the gates of this Part."""
    store, groups = X.Candles(con, cfg_by_tf), {}
    for r in rows:
        if r.get("ent") and not r.get("ent_from_close") and r.get("close") and r["tf"] in X.TFS and r.get("side") and r.get("sym"):
            groups.setdefault((r["sym"], r["tf"]), []).append(r)
        else:
            cov["no_entry_close_side_tf"] += 1
    for (sym, tf), rs in groups.items():
        runs, step = store.load(sym, tf, min(x["ent"] for x in rs), max(x["close"] for x in rs))
        for r in rs:
            sig_t = int((r["ent"] - step) // step * step)
            hit = next(((S, idx) for S, _a, idx in runs if sig_t in idx), None)
            if hit is None:
                cov["no_candles"] += 1
                continue
            S, idx = hit
            i0 = idx[sig_t]
            if i0 < E.warmup_end(S):
                cov["warmup"] += 1
                continue
            res = replay_trade(S, i0, bisect.bisect_right(S["t"], r["close"]) - 1, r)
            if res is None:
                cov["no_money_numbers"] += 1
                continue
            r["y"], r["gt"] = res
            cov["replayed"] += 1


def money(r, base):
    return r["net"] if base == "REAL" else r["y"]["BOT"]


def half(rs, gate, base, rcut):
    """One half of the data, one gate: kept / blocked numbers (trades where the gate is not computable are left out)."""
    kept = [r for r in rs if r["gt"][gate] is True]
    blk = [r for r in rs if r["gt"][gate] is False]
    m = lambda r: money(r, base)
    isrun = lambda r: r.get("mfe") is not None and r["mfe"] >= rcut
    pm = sum(m(r) for r in blk if m(r) > 0)
    la = -sum(m(r) for r in blk if m(r) <= 0)
    kn = sum(m(r) for r in kept)
    return {"kept": len(kept), "kept_net": round(kn, 2), "kept_avg": round(kn / len(kept), 3) if kept else None, "blocked": len(blk), "blocked_net": round(pm - la, 2),
            "profit_missed": round(pm, 2), "loss_avoided": round(la, 2), "net_gain": round(la - pm, 2), "winners_blocked": sum(1 for r in blk if m(r) > 0),
            "losers_blocked": sum(1 for r in blk if m(r) <= 0), "rallies_all": sum(1 for r in kept + blk if isrun(r)), "rallies_blocked": sum(1 for r in blk if isrun(r)),
            "rally_profit_missed": round(sum(m(r) for r in blk if isrun(r) and m(r) > 0), 2)}


def verdict(a, b):
    if min(a["blocked"], b["blocked"], a["kept"], b["kept"]) < MIN_HALF:
        return "TOO_FEW"
    if a["net_gain"] > 0 and b["net_gain"] > 0:
        cut = lambda h: h["rallies_blocked"] / h["rallies_all"] if h["rallies_all"] else 0.0
        share = lambda h: h["blocked"] / (h["blocked"] + h["kept"])
        return "HELPS" if all(cut(h) <= share(h) + 0.05 for h in (a, b)) else "HELPS_BUT_LOSES_RALLIES"
    return "FAILS"


def side_block(tr, te, sd, rcut, days):
    tr, te = [r for r in tr if sd is None or r["side"] == sd], [r for r in te if sd is None or r["side"] == sd]
    out = {"no_gate": {"trades": len(tr) + len(te), "per_day": round((len(tr) + len(te)) / days, 1)}}
    for b in BASES:
        v = [money(r, b) for r in tr + te]
        out["no_gate"][b] = {"net": round(sum(v), 2), "avg": round(sum(v) / len(v), 3) if v else None}
    holds = []
    for g in GATES:
        gtr, gte = [r for r in tr if r["gt"][g] is not None], [r for r in te if r["gt"][g] is not None]
        blk = {"trades_where_computable": len(gtr) + len(gte)}
        for b in BASES:
            a, c = half(gtr, g, b, rcut), half(gte, g, b, rcut)
            ver = verdict(a, c)
            blk[b] = {"train": a, "test": c, "kept_per_day": round((a["kept"] + c["kept"]) / days, 1), "verdict": ver}
            if ver == "HELPS":
                holds.append("%s %s" % (g, b))
        out[g] = blk
    return out, holds


def scope_report(rs):
    if len(rs) < A.MIN_SCOPE:
        return {"label": "NOT ENOUGH DATA", "replayed_trades": len(rs), "need": A.MIN_SCOPE}
    tr, te, cut = A.split_rows(rs)
    mf = sorted(r["mfe"] for r in rs if r.get("mfe") is not None)
    rcut = mf[int(len(mf) * 0.75)] if mf else 1e9
    days = max(1.0, (max(r["ent"] for r in rs) - min(r["ent"] for r in rs)) / 86400.0)
    out = {"replayed_trades": len(rs), "days_in_data": round(days, 1), "split_utc": P.fmt_ts(cut), "rally_definition": "best ROI at or above %.2f%% (top quarter, same as Part 7C)" % rcut,
           "gate_computable_pct": {g: round(100.0 * sum(1 for r in rs if r["gt"][g] is not None) / len(rs), 1) for g in GATES}}
    holds = []
    for sn, sd in SIDES:
        out[sn], h = side_block(tr, te, sd, rcut, days)
        holds += ["%s %s" % (sn, x) for x in h]
    out["holds"] = holds
    out["how_to_read"] = ("Per gate and money base: KEPT = trades that pass, BLOCKED = trades the gate would have skipped. loss_avoided = money lost by blocked losers, profit_missed = money made by blocked winners, "
                          "net_gain = loss_avoided - profit_missed, rallies_blocked = blocked trades in the top quarter of best ROI. HELPS needs net_gain above 0 in TRAIN and TEST with 30+ trades each way. "
                          "MID and OB are controls from the group idea, not proposals.")
    return out


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST", "gates": list(GATES), "bases": list(BASES), "indicator": "Stoch K%d smooth%d D%d, RSI %d (RRanjanFX)" % (K_LEN, K_SMOOTH, D_LEN, RSI_LEN)}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    src = K.load_rows(root)
    if not src or not src.get("rows"):
        X.build_report(root, fee_roi)
        src = K.load_rows(root)
    rows, dropped = K.prepare((src or {}).get("rows") or [])
    cov = {"replayed": 0, "no_candles": 0, "warmup": 0, "no_entry_close_side_tf": 0, "no_money_numbers": 0, "candles_used": False}
    con = F.open_ro(root)
    if con is None:
        rep["error"] = "No candle store (v2_market.db): needed for the zero-line / Stoch / RSI gate test."
        rep["coverage"] = cov
        return rep
    cov["candles_used"] = True
    cfg_by_tf = {}
    for tf in X.TFS:
        try:
            cfg_by_tf[tf] = IP.load_cfg(root, "15m" if tf == "15m" else "5m")[0]
        except Exception:
            cfg_by_tf[tf] = dict(E.DEFAULTS)
    try:
        replay_all(rows, con, cfg_by_tf, cov)
    finally:
        con.close()
    rep["rows_used"], rep["rows_without_net_result"], rep["coverage"] = len(rows), dropped, cov
    done = [r for r in rows if r.get("y")]
    for g in X.GROUPS:
        grs = [r for r in done if r["g"] == g]
        rep[g] = {nm: scope_report([r for r in grs if tf is None or r["tf"] == tf]) for nm, tf in SCOPES}
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades. Hindsight replay: a live gate sees each signal once.",
                    "Z0 = price close vs the SD centre line. SLOPE = Stoch %D now vs 3 candles ago (long: not falling, short: not rising). RSI50 = RSI(10) side of 50. MID and OB are CONTROLS from the group idea.",
                    "Stoch = K 21, smooth 7, %D = SMA 7 (the old RRanjanFX indicator). RSI = Wilder 10 over at most 150 candles back.",
                    "REAL = what the old bot really made. BOT = same trade with 30% booked at TP1 and a TRAIL_33 trail as a stand-in for the real trail.",
                    "7 gates x 3 sides x 2 bases x 3 scopes = many looks, one HELPS can be luck. A HELPS is a candidate for a LOG test, never a rule. Part 15 on real joined data has the last word."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 18A: zero-line + Stoch + RSI gate test (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out", default="-")
    ap.add_argument("--fee-roi", type=float, default=1.0)
    a = ap.parse_args(argv)
    txt = json.dumps(build_report(I.find_data_dir(a.data), a.fee_roi), indent=1, ensure_ascii=False, default=str)
    if a.out == "-":
        print(txt)
    else:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(txt)
        sys.stderr.write("Written: %s\n" % a.out)
    sys.stderr.write("Nothing was changed in trading. Send the summary file to Claude.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
