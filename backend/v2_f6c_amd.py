"""v2_f6c_amd.py - FILTER STUDY Part 6C (bot Part 6): AMD test + ENTRY BIAS CHECK + STAKE-BACK check (read-only).
Reuses Part 5A (v2_f5a_exits.py) and Part 6B (v2_f6b_entry.py): both must be in the repo. Measures only. No rule, no setting, no order, no network.
THREE QUESTIONS (owner, 10 Nov 2026):
 1. AMD (Accumulation - Manipulation - Distribution), the 3 candles up to and including the signal candle (c1 = 2 candles before, c2 = 1 before, c3 = the signal candle). LONG shown, SHORT is the mirror.
      AMD_basic    c1 red, c2 breaks below the low of c1 (sweep), c3 green
      AMD_reclaim  AMD_basic AND c2 closes back above the low of c1 (the break was a fake wick)
      AMD_video    AMD_basic AND the open of c1 is above the open of c2 (rule from the owner's video)
      AMD_pull     AMD_basic AND price at the signal is near EMA50 (LOW third of distance, cut made on TRAIN)
    Judged on the REAL result of each trade, TRAIN vs TEST, same flags as 6B (LOSER / WINNER only when both halves agree).
 2. ENTRY BIAS CHECK. Part 6B showed limit entries as up to +17,000 USDT better. Suspect: it moved the entry price but kept the OLD exit price, so a lower buy price alone gives free money.
    Here both are shown for each entry type: OLD_FIXED_EXIT (as 6B) and SAME_MOVE (the filled trade makes the same % move as the real trade, so the price shift gives nothing and only the effect of SKIPPING trades is left).
    bias_part = OLD_FIXED_EXIT minus SAME_MOVE = the part that was only the price shift. A real entry gain must survive in SAME_MOVE, in BOTH halves.
 3. STAKE-BACK: how much would have to be booked at TP1 (and at TP4) to take the whole invested amount back (ROI before fee, leverage included)? If the TP1 ROI is far below 100% the stake can not come back at TP1.
TRAIN = first 60% by time, TEST = last 40%. Main and Sniper are never added together. Only paper trades. Hindsight replay: a candidate for a log test, not a rule.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f6c_amd.py --data /home/owl/owl_data --out -
Day = 00:00 UTC = 5:30 AM IST."""
import argparse
import bisect
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f5a_exits as A
import v2_f6b_entry as B

X, K, F, IP, E, I, P = A.X, A.K, A.F, A.IP, A.E, A.I, A.P

VERSION = "v2_f6c_amd 1 (Filter Part 6C)"
AMD_NAMES = ("AMD_basic", "AMD_reclaim", "AMD_video", "AMD_pull")


def amd_flags(S, i0, side):
    """AMD variants at the signal candle. side = 1 LONG, -1 SHORT (mirror). -> dict name -> bool, or None if there are not 3 candles."""
    if i0 < 2:
        return None
    o, h, l, c = S["o"], S["h"], S["l"], S["c"]
    a, b, d = i0 - 2, i0 - 1, i0
    if side == 1:
        basic = c[a] < o[a] and l[b] < l[a] and c[d] > o[d]
        reclaim = basic and c[b] > l[a]
        video = basic and o[a] > o[b]
    else:
        basic = c[a] > o[a] and h[b] > h[a] and c[d] < o[d]
        reclaim = basic and c[b] < h[a]
        video = basic and o[a] < o[b]
    return {"AMD_basic": basic, "AMD_reclaim": reclaim, "AMD_video": video}


def roi_at(side, ep, px, lev):
    """Leveraged ROI % of leaving at price px, before fee."""
    return side * (px / ep - 1.0) * 100.0 * lev if ep and px and lev else None


def replay_trade(S, i0, end0, r):
    side, ep, lev, inv, fee = r.get("side"), r.get("entry_price"), r.get("lev"), r.get("invest"), r.get("fee_roi")
    if not (side and ep and lev and inv and fee is not None) or end0 <= i0:
        return None
    end0 = min(end0, i0 + 1 + A.MAX_BARS)
    cx = S["c"][end0]
    calib = A.money(side, ep, cx, lev, fee, inv)
    y = {"calib": round(calib, 4), "e": {}}
    for name, kind, wait in B.ENTRIES:
        px = B.entry_fill(S, i0, end0, side, kind, wait)
        if px is None:
            y["e"][name] = None
        else:
            y["e"][name] = {"old": round(A.money(side, px, cx, lev, fee, inv), 4), "same": round(calib, 4)}   # same % move = same result as the real trade
    amd = amd_flags(S, i0, side)
    ema = S["ema_s"][i0]
    dist = side * (S["c"][i0] - ema) / ema * 100.0 if ema else None
    return y, amd, dist, {"tp1": roi_at(side, ep, r.get("tp1"), lev), "tp4": roi_at(side, ep, r.get("tp4"), lev)}


def replay_all(rows, con, cfg_by_tf, cov):
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
            end0 = bisect.bisect_right(S["t"], r["close"]) - 1
            res = replay_trade(S, i0, end0, r)
            if res is None:
                cov["no_money_numbers"] += 1
                continue
            r["y"], amd, dist, r["roi"] = res
            r["amd"], r["dist"] = amd, dist
            cov["replayed"] += 1


def amd_block(tr, te):
    cuts = B.tertile_cuts([r["dist"] for r in tr])
    out = {"cut_low_third_dist_pct": cuts[0]}

    def yes(r, name):
        if not r.get("amd"):
            return "n/a"
        if name == "AMD_pull":
            ok = r["amd"]["AMD_basic"] and r["dist"] is not None and cuts[0] is not None and r["dist"] < cuts[0]
        else:
            ok = r["amd"][name]
        return "AMD yes" if ok else "AMD no"
    for n in AMD_NAMES:
        out[n] = B.bucket_table(tr, te, lambda r, n=n: yes(r, n), ("AMD yes", "AMD no", "n/a"))
    return out


def entry_bias_block(rs, tr, te):
    """OLD_FIXED_EXIT (like 6B) vs SAME_MOVE (only the effect of skipping) for every entry type, TRAIN and TEST."""
    out = {"calib_net_usdt": round(sum(r["y"]["calib"] for r in rs), 3)}
    for name, _k, _w in B.ENTRIES:
        def chg(lst, key):
            tot, n = 0.0, 0
            for r in lst:
                v = r["y"]["e"][name]
                d = (0.0 if v is None else v[key]) - r["y"]["calib"]
                tot += d
                n += 1 if abs(d) > 1e-9 else 0
            return round(tot, 3), n
        o_tr, o_te, s_tr, s_te = chg(tr, "old"), chg(te, "old"), chg(tr, "same"), chg(te, "same")
        if s_tr[1] < A.MIN_CHANGED or s_te[1] < A.MIN_CHANGED:
            verdict = "TOO_FEW"
        elif s_tr[0] > 0 and s_te[0] > 0:
            verdict = "REAL_GAIN"
        else:
            verdict = "NO_GAIN_AFTER_BIAS_REMOVED" if (o_tr[0] + o_te[0]) > 0 else "WORSE"
        filled = sum(1 for r in rs if r["y"]["e"][name] is not None)
        out[name] = {"verdict": verdict, "OLD_FIXED_EXIT_change_train_test": [o_tr[0], o_te[0]], "SAME_MOVE_change_train_test": [s_tr[0], s_te[0]],
                     "bias_part_usdt": round(o_tr[0] + o_te[0] - s_tr[0] - s_te[0], 3), "filled_pct": round(100.0 * filled / len(rs), 1) if rs else None, "changed_train_test": [s_tr[1], s_te[1]]}
    return out


def med(v):
    v = sorted(x for x in v if x is not None)
    return round(v[len(v) // 2], 1) if v else None


def stake_block(rs):
    out = {"note": "ROI % before fee, leverage included. Share of the trade to book (%) = 10000 / ROI. Over 100 % of the trade can not be booked (fraction_to_book above 100 = stake can not come back at that level), so 'stake_back_possible' needs ROI >= 100."}
    for k in ("tp1", "tp4"):
        v = [r["roi"][k] for r in rs if r.get("roi") and r["roi"][k] is not None]
        m = med(v)
        out[k] = {"trades_with_level": len(v), "median_roi_pct": m, "share_roi_100_or_more_pct": round(100.0 * sum(1 for x in v if x >= 100.0) / len(v), 1) if v else None,
                  "fraction_to_book_median_pct": None if not m or m <= 0 else round(10000.0 / m, 1), "stake_back_possible_at_median": bool(m and m >= 100.0)}
    return out


def scope_report(rs):
    if len(rs) < A.MIN_SCOPE:
        return {"label": "NOT ENOUGH DATA", "replayed_trades": len(rs), "need": A.MIN_SCOPE}
    tr, te, cut = A.split_rows(rs)
    return {"replayed_trades": len(rs), "split_utc": P.fmt_ts(cut), "amd": amd_block(tr, te), "entry_bias_check": entry_bias_block(rs, tr, te), "stake_back": stake_block(rs),
            "how_to_read": "amd: real result per bucket, FLAG only when TRAIN and TEST agree. entry_bias_check: REAL_GAIN only if SAME_MOVE is positive in BOTH halves; bias_part_usdt is the share that was only the price shift."}


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST", "amd_variants": list(AMD_NAMES), "entry_types": [e[0] for e in B.ENTRIES]}
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
        rep["error"] = "No candle store (v2_market.db): needed for the AMD test."
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
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades. Hindsight replay.",
                    "AMD uses the 3 candles up to the signal candle. Short is the mirror of long.",
                    "SAME_MOVE keeps the % move of the real trade, so only skipping trades can change the result (no free price shift)."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 6C: AMD + entry bias check + stake-back (read-only)")
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
