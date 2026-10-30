"""v2_leakage.py - Part 10: MONEY MAP 3 of 3, the LEAKAGE MAP (read-only). Answers: "where does money leak out of closed trades: profit given back, break-even stops,
sideways losses, fees, reversed exits?" Same rules as Parts 8-9: same four boxes (never added together), fee-correct net per trade (Part 8), no network,
never writes to the data files, never touches a setting, position or order.
What the closed trade rows carry (read from paper_trader.py): max_roi_pct = best ROI seen while open (gross, before fee), gross_roi_pct / roi_pct / fee_roi_pct,
status CLOSED_<reason> (SL, TP4, REVERSED ...), tp_hit_levels, breakeven_auto_shifted, regime_cross_n (EMA50 crosses in the last 20 candles: 1 clean, 3+ choppy).
Leaks (each one: trades, USDT, label):
  gave_back_profit    trade peaked above where it closed. giveback = invest x (peak - gross close) / 100. HINDSIGHT: nobody can exit at the exact peak.
  peak_then_loss      peak was above the fee (a net winner was possible) but the trade closed as a net loss. Hindsight too.
  breakeven_stop      stopped at entry after TP1 (CLOSED_SL, break-even shift or TP1 hit, gross close within +-0.5 ROI%): what it really cost (fee) and its net.
                      "Would it have won?" cannot be known from these rows (no candles after the exit): it says NEEDS CANDLES (collectors, Parts 14-18). Nothing is guessed.
  sideways_loss       net losses of trades opened with regime_cross_n >= 3 (choppy). Facts: how many choppy trades, their net, their losses.
  fee_cost            fees paid (old paper trades: estimated), fees as % of gross profit, and winners the fee turned into losers (gross > 0 but net <= 0).
  reversed_exit       trades closed by an opposite signal (REVERSED): count and net.
Measured leaks (fee, sideways, reversed, break-even) and hindsight leaks (gave back, peak then loss) are NEVER added to each other, and no leak is added across leaks
(one trade can sit in several). A leak with fewer than 30 trades is NOT ENOUGH DATA: facts are shown, no conclusion is drawn. Labels describe amount, not profit.
Run (Termux):  python3 backend/v2_leakage.py [--data DIR] [--out FILE] [--fee-roi 1.0]   -> Download/owl_leakage.json
Tests: python3 test/test_v2_leakage.py"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_inv_redact as R
import v2_inventory as I
import v2_money_hour as M
import v2_pnl as P

VERSION = "v2_leakage 1 (Part 10)"
MIN_N = 30
BE_BAND = 0.5          # ROI % around entry that still counts as "stopped at entry"
CHOPPY = 3             # regime_cross_n >= 3 = choppy (strategy.py comment: 1 clean, 3+ choppy)
LEAKS = ("gave_back_profit", "peak_then_loss", "breakeven_stop", "sideways_loss", "fee_cost", "reversed_exit")
HINDSIGHT = ("gave_back_profit", "peak_then_loss")


def facts(t, fee_roi):
    """One closed trade -> dict of the numbers every leak needs (None where the row has no value)."""
    net = M.net_fee_correct(t, fee_roi)
    if net is None:
        return None
    inv, kind = P.num(t, "invest_usdt") or 0.0, P.fee_basis(t)
    fr = P.num(t, "fee_roi_pct")
    if kind == "applied" or kind == "estimated_in_row":
        fee = P.num(t, "fee_usdt")
        fee = inv * (fr if fr is not None else fee_roi) / 100.0 if fee is None else fee
    elif kind == "none_old":
        fee = inv * fee_roi / 100.0
    else:
        fee = None                                     # live: fee / funding not verified (Part 6)
    roi, g = P.num(t, "roi_pct"), P.num(t, "gross_roi_pct")
    if g is None and roi is not None:
        g = roi + (fr or 0.0) if kind in ("applied", "estimated_in_row") else roi
    status = str(t.get("status") or "").upper()
    hits = t.get("tp_hit_levels")
    return {"net": net, "inv": inv, "fee": fee, "gross_roi": g, "peak": P.num(t, "max_roi_pct"), "cross": P.num(t, "regime_cross_n"),
            "reason": status[7:] if status.startswith("CLOSED_") else (status or "UNKNOWN"),
            "be": bool(t.get("breakeven_auto_shifted")) or (isinstance(hits, list) and 1 in hits)}


def new_leak():
    return {"trades": 0, "usdt": 0.0}


def box_report(items, fee_roi):
    L = {k: new_leak() for k in LEAKS}
    ctx = {"trades_used": 0, "skipped_no_pnl": 0, "no_peak_row": 0, "no_regime_row": 0, "net_fee_correct_usdt": 0.0, "gross_usdt_known": 0.0, "fees_usdt": 0.0,
           "fee_unknown_trades": 0}
    gross_profit, choppy_n, choppy_net, fee_flipped, be_fee = 0.0, 0, 0.0, 0.0, 0.0
    by_reason = {}
    for t in items:
        f = facts(t, fee_roi)
        if f is None:
            ctx["skipped_no_pnl"] += 1
            continue
        ctx["trades_used"] += 1
        net, inv, fee = f["net"], f["inv"], f["fee"]
        ctx["net_fee_correct_usdt"] += net
        r = by_reason.setdefault(f["reason"], {"trades": 0, "net_usdt": 0.0})
        r["trades"] += 1
        r["net_usdt"] += net
        if fee is None:
            ctx["fee_unknown_trades"] += 1
        else:
            ctx["fees_usdt"] += fee
            ctx["gross_usdt_known"] += net + fee
            gross_profit += max(0.0, net + fee)
            L["fee_cost"]["trades"] += 1
            L["fee_cost"]["usdt"] += fee
            if net + fee > 0 and net <= 0:
                fee_flipped += 1
        pk, g = f["peak"], f["gross_roi"]
        if pk is None or g is None:
            ctx["no_peak_row"] += 1
        else:
            if pk > g:
                L["gave_back_profit"]["trades"] += 1
                L["gave_back_profit"]["usdt"] += inv * (pk - g) / 100.0
            if fee is not None and net < 0 and inv > 0 and pk - fee / inv * 100.0 > 0:
                L["peak_then_loss"]["trades"] += 1
                L["peak_then_loss"]["usdt"] += -net
            if f["reason"] == "SL" and f["be"] and abs(g) <= BE_BAND:
                L["breakeven_stop"]["trades"] += 1
                L["breakeven_stop"]["usdt"] += net
                be_fee += fee or 0.0
        if f["cross"] is None:
            ctx["no_regime_row"] += 1
        elif f["cross"] >= CHOPPY:
            choppy_n += 1
            choppy_net += net
            if net < 0:
                L["sideways_loss"]["trades"] += 1
                L["sideways_loss"]["usdt"] += net
        if f["reason"] == "REVERSED":
            L["reversed_exit"]["trades"] += 1
            L["reversed_exit"]["usdt"] += net
    for k, v in L.items():
        v["usdt"] = round(v["usdt"], 4)
        v["label"] = I.label(v["trades"], True)
        v["verdict"] = "NOT ENOUGH DATA" if v["trades"] < MIN_N else "ENOUGH DATA"
        v["kind"] = "hindsight" if k in HINDSIGHT else "measured"
    L["gave_back_profit"]["meaning"] = "peak minus close, in USDT. Hindsight: nobody can sell the exact peak."
    L["peak_then_loss"]["meaning"] = "usdt = the net loss of trades that were a net winner at their peak. Hindsight."
    L["breakeven_stop"].update({"meaning": "usdt = net of trades stopped at entry after TP1 (fee only).", "fees_paid_usdt": round(be_fee, 4),
                                "would_have_won": "NEEDS CANDLES AFTER THE EXIT (collectors, Parts 14-18); not guessed here"})
    L["sideways_loss"].update({"meaning": "usdt = net losses of choppy trades (regime_cross_n >= %d)." % CHOPPY, "choppy_trades": choppy_n, "choppy_net_usdt": round(choppy_net, 4)})
    L["fee_cost"].update({"meaning": "usdt = fees paid (old paper trades: estimated).", "pct_of_gross_profit": round(100.0 * L["fee_cost"]["usdt"] / gross_profit, 1) if gross_profit > 0 else None,
                          "winners_turned_loser_by_fee": int(fee_flipped)})
    L["reversed_exit"]["meaning"] = "usdt = net of trades closed by an opposite signal."
    for k in ("net_fee_correct_usdt", "gross_usdt_known", "fees_usdt"):
        ctx[k] = round(ctx[k], 4)
    ctx["box_label"] = I.label(ctx["trades_used"], True)
    ctx["by_exit_reason"] = {k: {"trades": v["trades"], "net_usdt": round(v["net_usdt"], 4)} for k, v in sorted(by_reason.items())}
    order = sorted((k for k in LEAKS if k not in HINDSIGHT and L[k]["verdict"] == "ENOUGH DATA" and k != "fee_cost"), key=lambda k: L[k]["usdt"])
    ctx["biggest_measured_leaks_by_usdt"] = order
    ctx["summary"] = ("NOT ENOUGH DATA: no measured leak has %d trades yet." % MIN_N) if not order and L["fee_cost"]["trades"] < MIN_N else \
        "Leaks overlap (one trade can be in several), so they are not added up. Hindsight leaks are not real money lost."
    return {"context": ctx, "leaks": L}


def build_report(data_dir, fee_roi=1.0):
    root = os.path.realpath(data_dir)
    if not os.path.isdir(root):
        return {"tool": VERSION, "read_only": True, "error": "data folder not found"}
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "min_trades_per_leak": MIN_N, "fee_roi_pct_used_for_old_trades": fee_roi,
           "boxes": {}, "sources": {}}
    items, seen = {b: [] for b in P.BOXES}, {b: set() for b in P.BOXES}
    for name, file_bot in P.FILES:
        rows, st = P.read_jsonl(os.path.join(root, name), [root])
        rep["sources"][name] = st
        for t in rows:
            b, k = P.box_of(t, file_bot), P.tkey(t)
            if k not in seen[b]:                              # duplicates counted once (Part 5 flags them)
                seen[b].add(k)
                items[b].append(t)
    for b in P.BOXES:
        rep["boxes"][b] = box_report(items[b], fee_roi)
    rep["notes"] = ["Boxes are never added together: real money and paper money must not be mixed.",
                    "Measured leaks and hindsight leaks (gave back, peak then loss) are never added to each other, and leaks overlap, so no grand total exists.",
                    "Break-even 'would it have won?' needs candles after the exit: not measurable from closed-trade rows.",
                    "real_live: fee / funding not verified (Part 6), so its fee leak is left out (fee_unknown_trades)."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl Money Map 3: leakage map (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--fee-roi", type=float, default=1.0, help="fee %% of ROI for OLD paper trades without a fee (default 1.0)")
    a = ap.parse_args(argv)
    out = a.out or os.path.join(os.path.dirname(I.default_out()), "owl_leakage.json")
    rep = build_report(I.find_data_dir(a.data), a.fee_roi)
    try:
        R.write_report(rep, out)
    except R.RedactionFailed as e:
        print("REFUSED: secret-looking fields, NO file written:", ", ".join(map(str, e.paths[:20])))
        return 2
    print("Leakage map written:", out)
    for n, b in rep.get("boxes", {}).items():
        c = b["context"]
        print("  %-14s trades %-5d net %+.2f USDT, fees %.2f [%s]" % (n, c["trades_used"], c["net_fee_correct_usdt"], c["fees_usdt"], c["box_label"]))
        for k, v in b["leaks"].items():
            if v["trades"]:
                print("      %-17s trades %-5d %+.2f USDT  %s (%s)" % (k, v["trades"], v["usdt"], v["verdict"], v["kind"]))
    print("Nothing was changed. Send this JSON file to Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
