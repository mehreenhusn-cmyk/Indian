"""v2_f15_ema2.py - FILTER STUDY Part 17A: the TWO-EMA50 GATE test on the bot's own past paper trades (read-only, hindsight replay).
Owner idea (12 Nov): trade only when BOTH indicators agree, price and the lower-pane candle on the right side of their EMA50 (long: above, short: below).
GATES (at the signal candle, same candle store as Parts 6B / 13):
  P    price close on the right side of the EMA50 (S['ema_s'], the same EMA50 as Part 13)
  L    the LOWER candle on the right side of ITS OWN EMA50 = the Z-score candle (Z of the close vs the last 200 closes) against the EMA50 of the Z-close series.
       ASSUMPTION: the owner's lower pane is the Z-score candles; if his indicator is something else, L is the wrong test. Needs 100+ Z values (else the trade is left out of L and P+L).
  P+L  both
FOR EVERY GATE (ALL / LONG / SHORT, TRAIN = first 60% by time, TEST = last 40%), two money bases:
  REAL   what the trade really made (no booking, the old bot)
  BOT    the same trade replayed with the bot's way now: 30% at TP1, the rest with a TRAIL_33 trail (stand-in)
the numbers the owner asked for: trades per day kept, net of kept trades, how many trades the gate BLOCKS, PROFIT MISSED (winners blocked), LOSS AVOIDED (losers blocked), net gain = loss avoided - profit missed,
and RALLIES MISSED = blocked trades whose best ROI is in the top quarter (same runner definition as Part 7C) and the profit they carried.
VERDICT per gate: HELPS = net gain above 0 in TRAIN and TEST, 30+ blocked and 30+ kept in each half, and the gate does not cut rallies more than it cuts trades in general. HELPS_BUT_LOSES_RALLIES = net gain above 0 in both but it cuts rallies too much. TOO_FEW. FAILS.
Main and Sniper are never added together. 3 gates x 3 sides x 2 bases is a small number of looks, but a HELPS here is still only a candidate for a LOG test (Part 15 real data decides). Paper trades only. Nothing here touches the bot.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f15_ema2.py --data /home/owl/owl_data --out -     (runner id f15e)"""
import argparse
import bisect
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f6d_amd_low as D

A, BK, X, K, F, IP, E, I, P = D.A, D.BK, D.X, D.K, D.F, D.IP, D.E, D.I, D.P
VERSION = "v2_f15_ema2 1 (Filter Part 17A)"
GATES, BASES, SIDES = ("P", "L", "P+L"), ("REAL", "BOT"), D.SIDES
MIN_HALF, EMA_Z, ZMIN, WARM = 30, 50, 100, 150


def z_ema50(S, i0):
    """-> (Z close at i0 or None, EMA50 of the Z-close series or None). Needs ZMIN Z values."""
    j0 = max(D.ZN - 1, i0 - WARM + 1)
    if i0 - j0 + 1 < ZMIN:
        return None, None
    a, ema, zc = 2.0 / (EMA_Z + 1), None, None
    for j in range(j0, i0 + 1):
        z = D.zcandle(S, j)
        zc = None if z is None else z[3]
        if zc is not None:
            ema = zc if ema is None else ema + a * (zc - ema)
    return zc, ema


def gates(S, i0, side):
    """{'P', 'L', 'P+L'} True / False / None at the signal candle, or None when the EMA50 is missing."""
    ema = S["ema_s"][i0] if i0 >= 2 else None
    if not ema:
        return None
    p = side * (S["c"][i0] - ema) > 0
    zc, ze = z_ema50(S, i0)
    l = None if zc is None or ze is None else side * (zc - ze) > 0
    return {"P": p, "L": l, "P+L": None if l is None else (p and l)}


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
           "gate_L_computable_pct": round(100.0 * sum(1 for r in rs if r["gt"]["L"] is not None) / len(rs), 1)}
    holds = []
    for sn, sd in SIDES:
        out[sn], h = side_block(tr, te, sd, rcut, days)
        holds += ["%s %s" % (sn, x) for x in h]
    out["holds"] = holds
    out["how_to_read"] = ("Per gate and money base: KEPT = trades that pass, BLOCKED = trades the gate would have skipped. loss_avoided = money lost by blocked losers, profit_missed = money made by blocked winners, "
                          "net_gain = loss_avoided - profit_missed, rallies_blocked = blocked trades in the top quarter of best ROI. HELPS needs net_gain above 0 in TRAIN and TEST with 30+ trades each way.")
    return out


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST", "gates": list(GATES), "bases": list(BASES)}
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
        rep["error"] = "No candle store (v2_market.db): needed for the EMA50 gate test."
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
        rep[g] = {nm: scope_report([r for r in grs if tf is None or r["tf"] == tf]) for nm, tf in A.SCOPES}
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades. Hindsight replay: a live gate sees each signal once.",
                    "P = price close vs EMA50 (the bot's EMA). L = the Z-score candle close vs the EMA50 of the Z closes (assumes the owner's lower pane is the Z candles).",
                    "REAL = what the old bot really made. BOT = same trade with 30% booked at TP1 and a TRAIL_33 trail as a stand-in for the real trail.",
                    "A HELPS is a candidate for a LOG test, never a rule. Part 15 on real joined data has the last word."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 17A: two-EMA50 gate test (read-only)")
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
