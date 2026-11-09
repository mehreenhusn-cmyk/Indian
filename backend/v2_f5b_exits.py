"""v2_f5b_exits.py - FILTER STUDY Part 5B: EXIT LAB, second half (read-only). Question 7 of README_FILTER. Main and Sniper always separate; scopes ALL timeframes and 5m only.
Measures only. No rule, no setting, no order, no network. Needs v2_f5a_exits.py (replay engine + the 9 fixed rules), v2_f1_counts.py, v2_f2_fakes.py. Reads v2_filter_trades.json (made first if missing) + candles from v2_market.db.
WHAT IS NEW HERE (same replay, same CALIB, same TRAIN / TEST split as Part 5A: first 60% of trades = TRAIN, last 40% = TEST, time-ordered):
  CURVE exits   the chart curve as numbers. SLOPE = price move of the last 5 candles WITH the trade side, per candle (%). The "near zero" line (FLAT_EPS) is the 25th percentile of |slope| over the candles of the TRAIN trades
                of the same timeframe: it comes from the data, TEST candles never touch it.
                CURVE_FLAT  after the open profit covered the round-trip fee: exit at the close when the slope was at or below FLAT_EPS for 4 candles in a row (the move went flat).
                CURVE_TURN  after the profit covered the fee: exit at the close when the slope was below zero AND shrinking for 2 candles in a row (the curve turned against the trade).
  AFTER TP4     if TP4 is touched, what to do next. Trades that never touch TP4 leave at the real closing candle (CALIB).  AFTER_TP4_TRAIL_25 / _50: after TP4 keep the trade and exit when price gives back 25% / 50% of the profit made
                so far (peak-trail from the TP4 price).  AFTER_TP4_CURVE: after TP4 keep the trade and exit on CURVE_FLAT.  With H1 (24 candles longer = 2 h on 5m, 6 h on 15m) the trade may run on after the real close.
  COMBOS        every pair of the 14 single rules (the 9 of Part 5A + 5 new): the pair exits at whichever rule triggers first. The best 5 pairs are chosen on TRAIN only (10+ changed trades, runners not hurt, gain), then shown on TEST.
  tp4_story     for trades that touched TP4: net of the real trade, of "leave at TP4" (Part 5A rule) and of the three AFTER_TP4 variants (H1).
Verdicts, RUNNERS (top quarter by best ROI), horizons H0 / H1 and the fee idea are exactly as in Part 5A. BETTER = gain in both halves and runners not hurt in either half. TRADEOFF = gain in both halves but runners lose. UNSTABLE = gain in one half only. WORSE. TOO_FEW = under 10 changed trades in a half.
Honest limits: hindsight replay (fills at the level, no slippage). About 14 singles + 91 pairs x 2 horizons are looked at, so a few look good by luck: a BETTER pair with a big TEST gain is a candidate for Part 7, never a rule. Fewer than 60 replayed trades = NOT ENOUGH DATA.
Day = 00:00 UTC = 5:30 AM IST. Durations over 60 min are written as hours + minutes.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f5b_exits.py --data /home/owl/owl_data --out -"""
import argparse
import bisect
import itertools
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_engine as E
import owl_sniper_feed as F
import owl_sniper_ind_pairs as IP
import v2_f1_counts as X
import v2_f2_fakes as K
import v2_f5a_exits as A
import v2_inventory as I
import v2_pnl as P

VERSION = "v2_f5b_exits 1 (Filter Part 5B)"
SLOPE_N = 5
FLAT_K = 4
TURN_K = 2
NEW = ("CURVE_FLAT", "CURVE_TURN", "AFTER_TP4_TRAIL_25", "AFTER_TP4_TRAIL_50", "AFTER_TP4_CURVE")
ALL = tuple(A.RULES) + NEW
A.RULES = ALL                         # Part 5A's rule_block reads this list, so it reports all 14 rules
TOP_PAIRS = 5


# ----------------------------------------------------------------------------- the curve as numbers
def slope(S, j, side):
    """Price move of the last 5 candles WITH the trade side, % per candle."""
    if j < SLOPE_N or not S["c"][j - SLOPE_N]:
        return None
    return side * (S["c"][j] / S["c"][j - SLOPE_N] - 1.0) * 100.0 / SLOPE_N


def sim_new(rule, S, i0, end0, end, side, ep, fee_px, tp4, eps):
    """-> (exit price, exit bar) for the five new rules. Bars i0+1 .. end are replayed."""
    c = S["c"]
    if rule.startswith("CURVE"):
        armed, cnt = False, 0
        for j in range(i0 + 1, end + 1):
            if side * (c[j] / ep - 1.0) * 100.0 > fee_px:
                armed = True
            s, p = slope(S, j, side), slope(S, j - 1, side)
            if not armed or s is None:
                cnt = 0
                continue
            if rule == "CURVE_FLAT":
                cnt, need = (cnt + 1 if s <= eps else 0), FLAT_K
            else:
                cnt, need = (cnt + 1 if (s < 0 and p is not None and s < p) else 0), TURN_K
            if cnt >= need:
                return c[j], j
        return c[end], end
    jt, p4 = None, None
    for j in range(i0 + 1, end0 + 1):
        px = A.hit_level(side, S["o"][j], S["h"][j], S["l"][j], tp4)
        if px is not None:
            jt, p4 = j, px
            break
    if jt is None:
        return c[end0], end0                                     # TP4 never touched: leave with the real trade
    best, cnt = p4, 0
    for j in range(jt + 1, end + 1):
        if rule.startswith("AFTER_TP4_TRAIL"):
            g = 0.25 if rule.endswith("25") else 0.5
            px = A.hit_level(-side, S["o"][j], S["h"][j], S["l"][j], best - g * (best - ep))
            if px is not None:
                return px, j
            best = max(best, S["h"][j]) if side == 1 else min(best, S["l"][j])
        else:
            s = slope(S, j, side)
            cnt = cnt + 1 if s is not None and s <= eps else 0
            if cnt >= FLAT_K:
                return c[j], j
    return c[end], end


def replay2(S, i0, end0, r, eps):
    """All 14 rules, both horizons, with the exit bar of each (needed for the pairs)."""
    side, ep, lev, inv, fee = r["side"], r.get("entry_price"), r.get("lev"), r.get("invest"), r.get("fee_roi")
    if not (side and ep and lev and inv and fee is not None) or end0 <= i0:
        return None
    fee_px = fee / lev
    end1 = min(len(S["t"]) - 1, end0 + A.EXTRA_BARS, i0 + 1 + A.MAX_BARS)
    end0 = min(end0, end1)
    x = {"h0": {}, "h1": {}, "exit_earlier_h0": {}, "exit_earlier_h1": {}, "bars": {"h0": {}, "h1": {}}, "calib": round(A.money(side, ep, S["c"][end0], lev, fee, inv), 4)}
    raw = {}
    for rule in ALL:
        for hz, end in (("h0", end0), ("h1", end1)):
            if rule in NEW:
                px, j = sim_new(rule, S, i0, end0, end, side, ep, fee_px, r.get("tp4"), eps)
            else:
                px, j = A.simulate(rule, S, i0, end, side, ep, fee_px, r.get("tp1"), r.get("tp4"), raw)
            x[hz][rule] = round(A.money(side, ep, px, lev, fee, inv), 4)
            x["bars"][hz][rule] = j
            x["exit_earlier_" + hz][rule] = j < end0
    hi, lo = max(S["h"][i0 + 1:end0 + 1]), min(S["l"][i0 + 1:end0 + 1])
    x["tp4_touched"] = bool(r.get("tp4")) and bool(hi >= r["tp4"] if side == 1 else lo <= r["tp4"])
    return x


def replay_all(rows, con, cfg_by_tf, cov):
    """Candles -> contexts; FLAT_EPS per timeframe from TRAIN trades only; then every trade is replayed."""
    store, groups, ctx = X.Candles(con, cfg_by_tf), {}, []
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
            ctx.append((r, S, i0, bisect.bisect_right(S["t"], r["close"]) - 1))
    if not ctx:
        return {}
    ents = sorted(c[0]["ent"] for c in ctx)
    cut, eps = ents[int(len(ents) * A.TRAIN_FRAC)], {}
    for tf in X.TFS:
        v = sorted(abs(slope(S, j, r["side"])) for r, S, i0, e0 in ctx if r["tf"] == tf and r["ent"] < cut for j in range(i0 + 1, e0 + 1) if slope(S, j, r["side"]) is not None)
        if v:
            eps[tf] = v[int(len(v) * 0.25)]
    for r, S, i0, e0 in ctx:
        if r["tf"] in eps:
            r["x"] = replay2(S, i0, e0, r, eps[r["tf"]])
            cov["replayed" if r["x"] else "no_money_numbers"] += 1
    return eps


# ----------------------------------------------------------------------------- pairs, tp4 story, report
def verdict(a, b, ru):
    if a[1] < A.MIN_CHANGED or b[1] < A.MIN_CHANGED:
        return "TOO_FEW"
    if a[0] > 0 and b[0] > 0:
        return "BETTER" if ru[0] >= 0 and ru[1] >= 0 else "TRADEOFF"
    return "UNSTABLE" if (a[0] > 0 or b[0] > 0) else "WORSE"


def pair_change(rs, hz, a, b):
    """(sum of change vs CALIB, trades changed) when the pair exits at whichever rule triggers first."""
    d, ch = 0.0, 0
    for r in rs:
        x = r["x"]
        pick = a if x["bars"][hz][a] <= x["bars"][hz][b] else b
        v = x[hz][pick] - x["calib"]
        d += v
        ch += abs(v) > 1e-9
    return round(d, 3), ch


def pairs_block(rs, hz, rcut):
    tr, te, _cut = A.split_rows(rs)
    split = lambda sub: ([r for r in sub if r["mfe"] is not None and r["mfe"] >= rcut], [r for r in sub if r["mfe"] is None or r["mfe"] < rcut])
    (rtr, _), (rte, _) = split(tr), split(te)
    cands = []
    for a, b in itertools.combinations(ALL, 2):
        t, ru = pair_change(tr, hz, a, b), pair_change(rtr, hz, a, b)[0]
        if t[1] >= A.MIN_CHANGED and t[0] > 0 and ru >= 0:
            cands.append((t[0], a, b))
    cands.sort(reverse=True)
    out = []
    for _g, a, b in cands[:TOP_PAIRS]:
        t, e = pair_change(tr, hz, a, b), pair_change(te, hz, a, b)
        ru = (pair_change(rtr, hz, a, b)[0], pair_change(rte, hz, a, b)[0])
        out.append({"pair": "%s + %s (first one to trigger)" % (a, b), "verdict": verdict(t, e, ru), "change_vs_calib_train": t[0], "change_vs_calib_test": e[0], "trades_changed_train": t[1],
                    "trades_changed_test": e[1], "runners_change_train_test": list(ru)})
    return {"pairs_tried": len(list(itertools.combinations(ALL, 2))), "pairs_qualified_on_train": len(cands), "top_by_train_judged_on_test": out}


def tp4_story(rs):
    t = [r for r in rs if r["x"].get("tp4_touched")]
    if not t:
        return {"touched_tp4": 0}
    s = lambda f: round(sum(f(r) for r in t), 3)
    return {"touched_tp4": len(t), "real_net_usdt": s(lambda r: r["net"]), "calib_net_usdt": s(lambda r: r["x"]["calib"]), "leave_at_TP4_net_usdt": s(lambda r: r["x"]["h0"]["TP4"]),
            "after_tp4_trail_25_H1_net_usdt": s(lambda r: r["x"]["h1"]["AFTER_TP4_TRAIL_25"]), "after_tp4_trail_50_H1_net_usdt": s(lambda r: r["x"]["h1"]["AFTER_TP4_TRAIL_50"]),
            "after_tp4_curve_H1_net_usdt": s(lambda r: r["x"]["h1"]["AFTER_TP4_CURVE"]), **({"label": "NOT ENOUGH DATA"} if len(t) < A.MIN_CHANGED * 3 else {})}


def scope_report(rs):
    if len(rs) < A.MIN_SCOPE:
        return {"label": "NOT ENOUGH DATA", "replayed_trades": len(rs), "need": A.MIN_SCOPE}
    mfes = sorted(r["mfe"] for r in rs if r.get("mfe") is not None)
    rcut = mfes[int(len(mfes) * 0.75)] if mfes else float("inf")
    rules, cut = A.rule_block(rs, rcut)
    return {"replayed_trades": len(rs), "split_utc": P.fmt_ts(cut), "runner_definition": "best ROI at or above %.2f%% (top quarter of this scope)" % rcut, "rules_all_14": rules,
            "tp4_story": tp4_story(rs), "pairs_H0": pairs_block(rs, "h0", rcut), "pairs_H1": pairs_block(rs, "h1", rcut)}


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST", "min_changed_trades_per_half": A.MIN_CHANGED,
           "horizons": "H0 = until the real trade closed, H1 = %d candles longer (2 h on 5m, 6 h on 15m)" % A.EXTRA_BARS,
           "curve_definition": "slope = price move of the last %d candles with the trade side (% per candle). CURVE_FLAT: slope <= FLAT_EPS for %d candles; CURVE_TURN: slope below zero and shrinking for %d candles; both only after the profit covered the fee." % (SLOPE_N, FLAT_K, TURN_K)}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    src = K.load_rows(root)
    if not src or not src.get("rows"):
        X.build_report(root, fee_roi)
        rep["note_rows"] = "v2_filter_trades.json was missing: Part 1 was run first."
        src = K.load_rows(root)
    rows, dropped = K.prepare((src or {}).get("rows") or [])
    cov = {"replayed": 0, "no_candles": 0, "warmup": 0, "no_entry_close_side_tf": 0, "no_money_numbers": 0}
    con = F.open_ro(root)
    if con is None:
        rep["error"] = "No candle store (v2_market.db): the exit lab needs candles."
        return rep
    cfg_by_tf = {}
    for tf in X.TFS:
        try:
            cfg_by_tf[tf] = IP.load_cfg(root, "15m" if tf == "15m" else "5m")[0]
        except Exception:
            cfg_by_tf[tf] = dict(E.DEFAULTS)
    try:
        eps = replay_all(rows, con, cfg_by_tf, cov)
    finally:
        con.close()
    rep["rows_used"], rep["rows_without_net_result"], rep["coverage"] = len(rows), dropped, cov
    rep["FLAT_EPS_pct_per_candle (from TRAIN candles)"] = {tf: round(v, 4) for tf, v in eps.items()}
    done = [r for r in rows if r.get("x")]
    for g in X.GROUPS:
        grs = [r for r in done if r["g"] == g]
        rep[g] = {nm: scope_report([r for r in grs if tf is None or r["tf"] == tf]) for nm, tf in A.SCOPES}
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades.", "Every rule is compared with CALIB (same entry, exit at the real closing candle). Replay is hindsight: fills assumed at the level.",
                    "Pairs are picked on TRAIN only; the TEST numbers are the judge. About 105 pairs x 2 horizons are looked at, so a few look good by luck.",
                    "A BETTER verdict in BOTH halves with runners not hurt is a candidate for Part 7, not a rule. Part 6 = ENTER / WAIT / REJECT log.",
                    "Python Z vs Pine Z is still unchecked (README_FILTER), so band numbers are the engine Z."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 5B: curve exit, after TP4, best exit pairs (read-only)")
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
