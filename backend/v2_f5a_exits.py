"""v2_f5a_exits.py - FILTER STUDY Part 5A: EXIT LAB, first half (read-only). Question 7 of README_FILTER. Main and Sniper always separate; scopes ALL timeframes and 5m only.
Measures only. No rule, no setting, no order, no network. Part 5B (curve exit, after TP4, best combination) reads the file this part writes.
Reads: v2_filter_trades.json (Part 1 rows; made first if missing) + v2_market.db candles (read-only, same engine numbers as Part 1). Needs v2_f1_counts.py and v2_f2_fakes.py.
Writes: v2_filter_exits.json (one row per replayed trade: net of every exit rule below). Part 5B reuses it.
HOW IT WORKS: every PAPER trade is replayed candle by candle from its entry. Each exit rule is asked: "if you had been the exit, where would you have got out?" Price levels use the candle high / low (stop checked BEFORE the candle's own new peak = no look-ahead);
  close rules use the candle close. Money = invest x (price move x leverage - fee ROI), the same fee idea as Part 1.
HORIZONS: H0 = the rule may exit earlier, otherwise the trade ends when the real trade ended (isolates "was there a better exit INSIDE the same trade").  H1 = same, but the rule may run 24 candles longer
  (24 candles = 2 h on 5m, 6 h on 15m) to see if holding on would have paid. Compared with CALIB = exit at the close of the candle where the real trade closed, so every rule is judged on the same entry and the same replay.
RULES (a small FIXED set, nothing tuned):
  TP1 / TP4        full exit when the signal TP1 / TP4 price is touched.
  TRAIL_25/33/50   after the open profit covers the round-trip fee, exit when price gives back 25% / 33% / 50% of the profit made so far (peak-trail).
  CENTRE           exit when the close crosses back through the SD centre line against the trade (only after it was on the right side once).
  EMA50            exit when the close crosses back through the price EMA50 against the trade (same arming).
  BAND2            exit when Z had reached 2 SD with the trade and the close comes back inside 2 SD (band re-entry).
  OPPOSITE         exit at the close of the first candle that shows an opposite raw signal of the engine (this is the opposite-signal exit).
BLOCKS per group and scope:
  model_check   CALIB net vs the real recorded net (how close the replay is to real; slippage and partial TPs are not replayed).
  giveback      real trades: how much of the best ROI was given back; trades that were good for a moment and still lost; by exit kind; share of profit kept.
  tp_booking    did the candles touch TP1 / TP4 in the trade; how those trades really ended (touched TP4 but net not above zero = booking failed).
  rules         per rule and horizon: net, change vs CALIB in TRAIN (first 60%) and TEST (last 40%, time-ordered), trades changed, exits earlier %, change on RUNNERS (top quarter by best ROI) and on the REST.
  VERDICT       BETTER = gain in both halves and runners not hurt in either half.  TRADEOFF = gain in both halves but runners lose.  UNSTABLE = gain in one half only.  WORSE = no gain.  TOO_FEW = under 10 changed trades in a half.
Honest limits: hindsight replay (a live exit sees candles one by one, this does too, but fills are assumed at the level). A rule is a question for Part 5B / Part 7, not a rule. Fewer than 60 replayed trades = NOT ENOUGH DATA.
Day = 00:00 UTC = 5:30 AM IST. Durations over 60 min are written as hours + minutes.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f5a_exits.py --data /home/owl/owl_data --out -"""
import argparse
import bisect
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
import v2_inventory as I
import v2_pnl as P

VERSION = "v2_f5a_exits 1 (Filter Part 5A)"
EXITS_FILE = "v2_filter_exits.json"
MIN_SCOPE = 60
MIN_CHANGED = 10
TRAIN_FRAC = 0.6
EXTRA_BARS = 24                       # H1 = 24 candles longer than the real trade
MAX_BARS = 288
SCOPES = (("all", None), ("5m", "5m"))
TRAIL = {"TRAIL_25": 0.25, "TRAIL_33": 1.0 / 3.0, "TRAIL_50": 0.5}
RULES = ("TP1", "TP4", "TRAIL_25", "TRAIL_33", "TRAIL_50", "CENTRE", "EMA50", "BAND2", "OPPOSITE")


# ----------------------------------------------------------------------------- replay of ONE trade
def money(side, ep, px, lev, fee_roi, invest):
    """Net USDT of leaving at price px (leveraged ROI minus the round-trip fee, on the invested amount)."""
    return invest * (side * (px / ep - 1.0) * 100.0 * lev - fee_roi) / 100.0


def hit_level(side, o, h, l, level):
    """Fill price when a level is touched in this candle (gap through it fills at the open), else None."""
    if not level:
        return None
    if side == 1:
        return (level if o < level else o) if h >= level else None
    return (level if o > level else o) if l <= level else None


def simulate(rule, S, i0, end, side, ep, fee_px, tp1, tp4, raw_cache):
    """-> (exit price, exit bar). i0 = the signal candle (last closed before the entry). Bars i0+1 .. end are replayed."""
    o, h, l, c = S["o"], S["h"], S["l"], S["c"]
    best, armed, reached = ep, False, False

    def ok(j):
        ref = S["sma"][j] if rule == "CENTRE" else S["ema_s"][j]
        return None if not ref else (c[j] - ref) * side > 0
    if rule in ("CENTRE", "EMA50"):
        armed = bool(ok(i0))
    elif rule == "BAND2" and S["z"][i0] is not None:
        reached = S["z"][i0] * side >= 2.0
    for j in range(i0 + 1, end + 1):
        if rule in ("TP1", "TP4"):
            px = hit_level(side, o[j], h[j], l[j], tp1 if rule == "TP1" else tp4)
            if px is not None:
                return px, j
        elif rule in TRAIL:
            if armed:
                stop = best - side * TRAIL[rule] * side * (best - ep)
                px = hit_level(-side, o[j], h[j], l[j], stop)                 # price going against the trade touches the stop
                if px is not None:
                    return px, j
            best = max(best, h[j]) if side == 1 else min(best, l[j])
            armed = side * (best / ep - 1.0) * 100.0 > fee_px
        elif rule in ("CENTRE", "EMA50"):
            v = ok(j)
            if v is None:
                continue
            if v:
                armed = True
            elif armed:
                return c[j], j
        elif rule == "BAND2":
            z = S["z"][j]
            if z is None:
                continue
            if z * side >= 2.0:
                reached = True
            elif reached:
                return c[j], j
        elif rule == "OPPOSITE":
            if j not in raw_cache:
                try:
                    raw_cache[j] = E.raw_signal(S, j).get("side")
                except Exception:
                    raw_cache[j] = None
            if raw_cache[j] is not None and (raw_cache[j] == "LONG") != (side == 1):
                return c[j], j
    return c[end], end


def replay_trade(S, i0, end0, r):
    """All rules, both horizons, for one trade row. -> dict or None."""
    side, ep, lev, inv = r["side"], r.get("entry_price"), r.get("lev"), r.get("invest")
    fee = r.get("fee_roi")
    if not (side and ep and lev and inv and fee is not None) or end0 <= i0:
        return None
    fee_px = fee / lev
    end1 = min(len(S["t"]) - 1, end0 + EXTRA_BARS, i0 + 1 + MAX_BARS)
    end0 = min(end0, end1)
    raw, out = {}, {"h0": {}, "h1": {}, "bars_h0": end0 - i0, "truncated": end1 < end0 + EXTRA_BARS and end1 < i0 + 1 + MAX_BARS}
    out["calib"] = round(money(side, ep, S["c"][end0], lev, fee, inv), 4)
    out["exit_earlier_h0"], out["exit_earlier_h1"] = {}, {}
    for rule in RULES:
        for hz, end in (("h0", end0), ("h1", end1)):
            px, j = simulate(rule, S, i0, end, side, ep, fee_px, r.get("tp1"), r.get("tp4"), raw)
            out[hz][rule] = round(money(side, ep, px, lev, fee, inv), 4)
            out["exit_earlier_" + hz][rule] = j < end0
    hi = max(S["h"][i0 + 1:end0 + 1]) if end0 > i0 else None
    lo = min(S["l"][i0 + 1:end0 + 1]) if end0 > i0 else None
    for k in ("tp1", "tp4"):
        lv = r.get(k)
        out["touched_" + k] = None if not lv else bool(hi >= lv if side == 1 else lo <= lv)
    return out


def replay_all(rows, con, cfg_by_tf, cov):
    """Fills r['x'] for every paper trade that has candles around its entry and its close."""
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
            x = replay_trade(S, i0, end0, r)
            if x is None:
                cov["no_money_numbers"] += 1
                continue
            r["x"] = x
            cov["replayed"] += 1


# ----------------------------------------------------------------------------- report
def split_rows(rs):
    rs = sorted(rs, key=lambda r: r["ent"])
    cut = rs[int(len(rs) * TRAIN_FRAC)]["ent"]
    return [r for r in rs if r["ent"] < cut], [r for r in rs if r["ent"] >= cut], cut


def giveback_block(rs):
    """Real trades (not the replay): how much was given back."""
    mfe = [r for r in rs if r.get("mfe") is not None and r.get("roi") is not None]
    good = [r for r in mfe if r.get("fee_roi") is not None and r["mfe"] > r["fee_roi"]]
    won = sum(max(r["roi"], 0.0) for r in mfe)
    peak = sum(r["mfe"] for r in mfe if r["mfe"] > 0)
    gb = [r["mfe"] - r["roi"] for r in good]
    out = {"trades_with_mfe": len(mfe), "good_for_a_moment (best ROI above fee)": len(good), "of_those_ended_net_loss": sum(1 for r in good if r["net"] < 0),
           "of_those_gave_back_over_half": sum(1 for r in good if r["roi"] < r["mfe"] * 0.5), "avg_best_roi_pct": round(sum(r["mfe"] for r in mfe) / len(mfe), 2) if mfe else None,
           "avg_giveback_roi_pct_of_good": round(sum(gb) / len(gb), 2) if gb else None, "profit_kept_pct": round(won * 100.0 / peak, 1) if peak else None, "by_exit": {}}
    for k in X.CATS["exit"]:
        e = [r for r in good if r["exit_b"] == k]
        if e:
            out["by_exit"][k] = {"good_trades": len(e), "net_loss": sum(1 for r in e if r["net"] < 0), "avg_giveback_roi_pct": round(sum(r["mfe"] - r["roi"] for r in e) / len(e), 2),
                                 "net_usdt": round(sum(r["net"] for r in e), 3)}
    if len(mfe) < MIN_SCOPE:
        out["label"] = "NOT ENOUGH DATA"
    return out


def tp_block(rs):
    out = {}
    for k in ("tp1", "tp4"):
        t = [r for r in rs if r["x"].get("touched_" + k) is True]
        n = [r for r in rs if r["x"].get("touched_" + k) is False]
        out[k] = {"touched": len(t), "not_touched": len(n), "touched_but_net_not_above_zero": sum(1 for r in t if r["net"] <= 0), "touched_net_usdt": round(sum(r["net"] for r in t), 3),
                  "touched_avg_net_usdt": round(sum(r["net"] for r in t) / len(t), 4) if t else None, "not_touched_net_usdt": round(sum(r["net"] for r in n), 3)}
    return out


def delta(rs, hz, rule):
    """Change vs CALIB for a list of replayed rows: (sum of change, trades changed)."""
    d = [r["x"][hz][rule] - r["x"]["calib"] for r in rs]
    return round(sum(d), 3), sum(1 for v in d if abs(v) > 1e-9)


def rule_block(rs, runner_cut):
    tr, te, cut = split_rows(rs)
    out = {}
    for hz in ("h0", "h1"):
        for rule in RULES:
            a, b = delta(tr, hz, rule), delta(te, hz, rule)
            run_tr, rest_tr = [r for r in tr if r["mfe"] is not None and r["mfe"] >= runner_cut], [r for r in tr if r["mfe"] is None or r["mfe"] < runner_cut]
            run_te, rest_te = [r for r in te if r["mfe"] is not None and r["mfe"] >= runner_cut], [r for r in te if r["mfe"] is None or r["mfe"] < runner_cut]
            ru, re_ = (delta(run_tr, hz, rule)[0], delta(run_te, hz, rule)[0]), (delta(rest_tr, hz, rule)[0], delta(rest_te, hz, rule)[0])
            if a[1] < MIN_CHANGED or b[1] < MIN_CHANGED:
                v = "TOO_FEW"
            elif a[0] > 0 and b[0] > 0:
                v = "BETTER" if ru[0] >= 0 and ru[1] >= 0 else "TRADEOFF"
            else:
                v = "UNSTABLE" if (a[0] > 0 or b[0] > 0) else "WORSE"
            out["%s %s" % (rule, hz.upper())] = {"verdict": v, "net_usdt": round(sum(r["x"][hz][rule] for r in rs), 3), "change_vs_calib_train": a[0], "change_vs_calib_test": b[0],
                                                 "trades_changed_train": a[1], "trades_changed_test": b[1],
                                                 "exits_earlier_pct": round(sum(1 for r in rs if r["x"]["exit_earlier_" + hz][rule]) * 100.0 / len(rs), 1),
                                                 "runners_change_train_test": list(ru), "rest_change_train_test": list(re_)}
    return out, cut


def scope_report(rs):
    if len(rs) < MIN_SCOPE:
        return {"label": "NOT ENOUGH DATA", "replayed_trades": len(rs), "need": MIN_SCOPE}
    mfes = sorted(r["mfe"] for r in rs if r.get("mfe") is not None)
    rcut = mfes[int(len(mfes) * 0.75)] if mfes else float("inf")
    rules, cut = rule_block(rs, rcut)
    real, calib = sum(r["net"] for r in rs), sum(r["x"]["calib"] for r in rs)
    return {"replayed_trades": len(rs), "split_utc": P.fmt_ts(cut), "runner_definition": "best ROI at or above %.2f%% (top quarter of this scope)" % rcut,
            "model_check": {"real_net_usdt": round(real, 3), "calib_net_usdt": round(calib, 3), "avg_abs_diff_usdt": round(sum(abs(r["net"] - r["x"]["calib"]) for r in rs) / len(rs), 4),
                            "note": "CALIB leaves at the close of the real closing candle. Differences = slippage, partial TPs, intra-candle exits."},
            "giveback": giveback_block(rs), "tp_booking": tp_block(rs), "rules": rules}


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST", "min_changed_trades_per_half": MIN_CHANGED,
           "horizons": "H0 = until the real trade closed, H1 = %d candles longer (2 h on 5m, 6 h on 15m)" % EXTRA_BARS}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    src = K.load_rows(root)
    if not src or not src.get("rows"):
        X.build_report(root, fee_roi)
        rep["note_rows"] = "v2_filter_trades.json was missing: Part 1 was run first."
        src = K.load_rows(root)
    rows, dropped = K.prepare((src or {}).get("rows") or [])
    cov = {"replayed": 0, "no_candles": 0, "warmup": 0, "no_entry_close_side_tf": 0, "no_money_numbers": 0, "candles_used": False}
    con = F.open_ro(root)
    if con is None:
        rep["error"] = "No candle store (v2_market.db): the exit lab needs candles."
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
    done = [r for r in rows if r.get("x")]
    for g in X.GROUPS:
        grs = [r for r in done if r["g"] == g]
        rep[g] = {nm: scope_report([r for r in grs if tf is None or r["tf"] == tf]) for nm, tf in SCOPES}
    keep = [{"sym": r["sym"], "ent": r["ent"], "g": r["g"], "tf": r["tf"], "side": r["side"], "net": r["net"], "mfe": r.get("mfe"), "x": r["x"]} for r in done]
    rep["exits_file"] = {"name": EXITS_FILE, "rows": len(keep), "saved": F.write_json(root, EXITS_FILE, {"tool": VERSION, "made_utc": rep["made_utc"], "rules": list(RULES), "rows": keep})}
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades.", "Every rule is compared with CALIB (same entry, exit at the real closing candle). Replay is hindsight: fills are assumed at the level.",
                    "Only a BETTER verdict in BOTH halves is worth a look in Part 5B. A rule is a question, not a rule.", "Parts 5B: curve exit, after TP4, best combination (train / test).",
                    "Python Z vs Pine Z is still unchecked (README_FILTER), so band numbers are the engine Z."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 5A: exit lab, fixed exit rules (read-only)")
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
