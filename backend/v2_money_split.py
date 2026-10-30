"""v2_money_split.py - Part 9: MONEY MAP 2 of 3 (read-only). Answers: "after fees, which setup / market state / timeframe / coin made or lost money, and is that real or luck?"

Same rules as Part 8 (v2_money_hour.py), which it reuses: same boxes (never added together), same fee-correct net per trade, same entry-time ordering,
same FAKE-WINNER GUARD (a slot under 30 trades = NOT ENOUGH DATA and never ranked; CANDIDATE needs >= 30 trades, net > 0, both time-halves > 0 and
still > 0 without its best trade). Never writes to the data files, never touches a setting, position or order. No network.
What the closed trade rows really carry (read from paper_trader.py, not guessed):
  coin = symbol          timeframe = timeframe          setup = side (BUY / SELL), entry_zone, trigger, sl_type
  SIDE FIX (Part 11): a closed trade row stores BUY / SELL under "action" (paper_trader.py), "side" only in alert rows. side = "side", else "action".
  market state = htf_trend (as stored) + THIRDS (LOW / MID / HIGH of THIS box) of atr_pct, sd_width_pct, regime_cross_n, adx, ema_slope_pct
  one pair: timeframe + side.   A trade without a value goes to UNKNOWN, which is shown but NEVER ranked.
Many slots are compared at once (hundreds of coins), so some look good by luck: each split reports slots_tested, candidates and a luck_note.
A CANDIDATE is a lead to test later (Parts 39-46), never proof of profit.
Run (Termux):  python3 backend/v2_money_split.py [--data DIR] [--out FILE] [--fee-roi 1.0]   -> Download/owl_money_split.json
Tests: python3 test/test_v2_money_split.py"""
import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_inv_redact as R
import v2_inventory as I
import v2_money_hour as M
import v2_pnl as P

VERSION = "v2_money_split 2 (Part 9 + side fix in Part 11)"
UNKNOWN = "UNKNOWN"
TEXT_DIMS = (("timeframe", "timeframe"), ("side", "side"), ("coin", "symbol"), ("htf_trend", "htf_trend"), ("entry_zone", "entry_zone"),
             ("trigger", "trigger"), ("sl_type", "sl_type"))
THIRD_DIMS = ("atr_pct", "sd_width_pct", "regime_cross_n", "adx", "ema_slope_pct")
LIST_MAX = 5


SIDE_KEYS = ("side", "action")


def text_value(t, key):
    v = t.get(key)
    if key == "side" and (v is None or str(v).strip() == ""):
        v = next((t.get(k) for k in SIDE_KEYS[1:] if str(t.get(k) or "").strip()), None)
    if v is None or isinstance(v, (dict, list)) or str(v).strip() == "":
        return UNKNOWN
    return str(v).strip().upper()[:40]


def cuts(values):
    """Two cut points that split the KNOWN values of one box into thirds (None, None when fewer than 3 values)."""
    v = sorted(values)
    return (v[len(v) // 3], v[2 * len(v) // 3]) if len(v) >= 3 else (None, None)


def third_of(x, c):
    if x is None or c[0] is None:
        return UNKNOWN
    return "LOW" if x < c[0] else ("MID" if x < c[1] else "HIGH")


def slot_names(t, dim, key, c):
    if dim in THIRD_DIMS:
        return third_of(P.num(t, dim), c)
    if dim == "timeframe+side":
        a, b = text_value(t, "timeframe"), text_value(t, "side")
        return UNKNOWN if UNKNOWN in (a, b) else a + "+" + b
    return text_value(t, key)


def split_report(rows):
    """rows = [(ts, net, slot)] for ONE split -> verdict per slot, rankable lists, luck note."""
    slots = {}
    for ts, net, name in rows:
        slots.setdefault(name, []).append((ts, net))
    full, thin = {}, 0
    for name, r in slots.items():
        v, f = M.verdict(r)
        f["verdict"] = v
        if v == "NOT ENOUGH DATA" and name != UNKNOWN:
            thin += 1                                       # thin slots are only counted: hundreds of coins would bloat the file
            continue
        full[name] = f
    ranked = {n: f for n, f in full.items() if n != UNKNOWN and f["verdict"] != "NOT ENOUGH DATA"}
    cand = sorted((n for n, f in ranked.items() if f["verdict"] == "CANDIDATE"), key=lambda n: -ranked[n]["net_usdt"])
    bad = sorted((n for n, f in ranked.items() if f["verdict"] == "NEGATIVE"), key=lambda n: ranked[n]["net_usdt"])
    tested = len(ranked)
    out = {"trades": len(rows), "unknown_trades": len(slots.get(UNKNOWN, [])), "slots_total": len(slots) - (UNKNOWN in slots), "slots_tested": tested,
           "slots_too_thin": thin, "candidates": len(cand), "candidate_slots": cand[:LIST_MAX], "worst_slots": bad[:LIST_MAX], "slots": full}
    if tested == 0:
        out["luck_note"] = "NOT ENOUGH DATA: no slot has %d trades, nothing is ranked." % M.MIN_SLOT
    elif cand and len(cand) <= math.ceil(0.05 * tested):
        out["luck_note"] = "%d of %d tested slots look good: that is about what luck alone gives. Treat as a weak lead." % (len(cand), tested)
    elif cand:
        out["luck_note"] = "%d of %d tested slots passed the guard: a lead to test later, not proof of profit." % (len(cand), tested)
    else:
        out["luck_note"] = "No slot passed the guard: no winner is named."
    return out


def box_report(items, fee_roi):
    cutoffs = {d: cuts([x for x in (P.num(t, d) for t in items) if x is not None]) for d in THIRD_DIMS}
    st = {"used": 0, "skipped_no_time": 0, "skipped_no_pnl": 0}
    prepared = []
    for t in items:
        net, (ts, _fc) = M.net_fee_correct(t, fee_roi), M.entry_ts(t)
        if net is None:
            st["skipped_no_pnl"] += 1
        elif ts is None:
            st["skipped_no_time"] += 1
        else:
            st["used"] += 1
            prepared.append((t, ts, net))
    out = {"trades_used": st["used"], "stats": st, "box_label": I.label(st["used"], True), "third_cut_points": {d: list(c) for d, c in cutoffs.items()},
           "splits": {}}
    for dim, key in TEXT_DIMS + tuple((d, d) for d in THIRD_DIMS) + (("timeframe+side", ""),):
        out["splits"][dim] = split_report([(ts, net, slot_names(t, dim, key, cutoffs.get(dim))) for t, ts, net in prepared])
    return out


def build_report(data_dir, fee_roi=1.0):
    root = os.path.realpath(data_dir)
    if not os.path.isdir(root):
        return {"tool": VERSION, "read_only": True, "error": "data folder not found"}
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "min_trades_per_slot": M.MIN_SLOT, "fee_roi_pct_used_for_old_trades": fee_roi,
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
                    "Result per trade is fee-correct (old paper trades get the fee estimated); real_live fee / funding are not verified (Part 6).",
                    "Thirds (LOW / MID / HIGH) are cut inside each box from its own known values; UNKNOWN = the row has no value and is never ranked.",
                    "CANDIDATE = >= %d trades, net > 0, both halves > 0, still > 0 without the best trade. A lead to test, not proof." % M.MIN_SLOT]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl Money Map 2: result after fees by setup / market state / timeframe / coin (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--fee-roi", type=float, default=1.0, help="fee %% of ROI for OLD paper trades without a fee (default 1.0)")
    a = ap.parse_args(argv)
    out = a.out or os.path.join(os.path.dirname(I.default_out()), "owl_money_split.json")
    rep = build_report(I.find_data_dir(a.data), a.fee_roi)
    try:
        R.write_report(rep, out)
    except R.RedactionFailed as e:
        print("REFUSED: secret-looking fields, NO file written:", ", ".join(map(str, e.paths[:20])))
        return 2
    print("Money Map (split) written:", out)
    for n, b in rep.get("boxes", {}).items():
        print("  %-14s trades %-5d [%s]" % (n, b["trades_used"], b["box_label"]))
        for d, s in b["splits"].items():
            if s["slots_tested"]:
                print("      %-15s tested %-3d candidates %-2d  %s" % (d, s["slots_tested"], s["candidates"], s["luck_note"][:60]))
    print("Nothing was changed. Send this JSON file to Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
