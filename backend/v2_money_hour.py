"""v2_money_hour.py - Part 8: MONEY MAP 1 of 3 (read-only). Answers: "after fees, which hours / sessions made or lost money, and is that real or luck?"

Reads the permanent closed-trade files through Part 5 (v2_pnl) and NEVER writes to them, never touches a setting, position or order. No network.
Each box is analysed ALONE and never added to another box (real money and paper money must not be mixed):
  real_live, live_estimated, paper_b1, paper_b2   (same boxes as Part 5)
Per-trade result = FEE-CORRECT net (same rule as Part 5): paper with fee inside = pnl; OLD paper trade without fee = pnl - invest x fee_roi / 100;
real live = as Binance gave it (fee / funding not verified, see Part 6).
Time = ENTRY time (opened_at_ts: the hour the decision was taken). If a trade has no entry time its CLOSE time is used and counted in time_from_close.
Hours are UTC (ist_label shows the same hour in IST = UTC+5:30). Sessions (UTC): ASIA 00-08, EUROPE 08-16, US 16-24.
FAKE-WINNER GUARD: a slot (hour or session) with fewer than 30 trades is "NOT ENOUGH DATA" and never ranked. A slot is only a CANDIDATE if it has
>= 30 trades AND net > 0 AND both time-halves of its trades are > 0 AND it is still > 0 without its single best trade. Otherwise MIXED or NEGATIVE.
24 hours are compared at once, so one of them can look good by luck: a CANDIDATE is a thing to test later (Parts 39-46), never proof of profit.
Run (Termux):  python3 backend/v2_money_hour.py [--data DIR] [--out FILE] [--fee-roi 1.0]   -> Download/owl_money_hour.json
Tests: python3 test/test_v2_money_hour.py"""
import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_inv_redact as R
import v2_inventory as I
import v2_pnl as P

VERSION = "v2_money_hour 1 (Part 8)"
MIN_SLOT = 30
SESSIONS = (("ASIA", 0, 8), ("EUROPE", 8, 16), ("US", 16, 24))
VERDICTS = ("NOT ENOUGH DATA", "CANDIDATE", "MIXED", "NEGATIVE")


def net_fee_correct(t, fee_roi):
    """Fee-correct net of ONE trade (None when pnl is missing). Same rule as Part 5."""
    pnl = P.num(t, "pnl_usdt")
    if pnl is None:
        return None
    if P.fee_basis(t) == "none_old":
        return pnl - (P.num(t, "invest_usdt") or 0.0) * fee_roi / 100.0
    return pnl


def entry_ts(t):
    """(timestamp, from_close). Entry time first; close time only as a flagged fallback; (None, False) if neither is usable."""
    for k in ("opened_at_ts", "opened_ts"):
        v = P.num(t, k)
        if v is not None and v > 0:
            return v, False
    v = P.num(t, "closed_at_ts")
    return (v, True) if v is not None and v > 0 else (None, False)


def session_of(hour):
    for name, a, b in SESSIONS:
        if a <= hour < b:
            return name
    return "US"


def ist_label(hour):
    m = hour * 60 + 330
    return "%02d:%02d IST" % ((m // 60) % 24, m % 60)


def verdict(rows):
    """rows = [(ts, net)] of ONE slot. Returns (verdict, facts). Never ranks a thin slot."""
    n = len(rows)
    nets = [x[1] for x in rows]
    total = sum(nets)
    facts = {"trades": n, "wins": sum(v > 0 for v in nets), "losses": sum(v < 0 for v in nets), "net_usdt": round(total, 4),
             "avg_usdt": round(total / n, 4) if n else 0.0, "win_rate_pct": round(100.0 * sum(v > 0 for v in nets) / n, 1) if n else 0.0,
             "label": I.label(n, True)}
    if n < MIN_SLOT:
        return "NOT ENOUGH DATA", facts
    by_time = sorted(rows)
    half = n // 2
    a, b = sum(x[1] for x in by_time[:half]), sum(x[1] for x in by_time[half:])
    without_best = total - max(nets)
    facts.update({"first_half_net_usdt": round(a, 4), "second_half_net_usdt": round(b, 4), "net_without_best_trade_usdt": round(without_best, 4)})
    if total <= 0:
        return "NEGATIVE", facts
    return ("CANDIDATE" if a > 0 and b > 0 and without_best > 0 else "MIXED"), facts


def box_report(items, fee_roi):
    """items = [trade dict] of one box -> hour / session analysis."""
    hours = {h: [] for h in range(24)}
    sess = {s[0]: [] for s in SESSIONS}
    st = {"used": 0, "time_from_close": 0, "skipped_no_time": 0, "skipped_no_pnl": 0}
    for t in items:
        net = net_fee_correct(t, fee_roi)
        ts, from_close = entry_ts(t)
        if net is None:
            st["skipped_no_pnl"] += 1
            continue
        if ts is None:
            st["skipped_no_time"] += 1
            continue
        h = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).hour
        hours[h].append((ts, net))
        sess[session_of(h)].append((ts, net))
        st["used"] += 1
        st["time_from_close"] += from_close
    out = {"trades_used": st["used"], "stats": st, "by_hour_utc": {}, "by_session_utc": {}, "box_label": I.label(st["used"], True)}
    for h, rows in hours.items():
        v, f = verdict(rows)
        f.update({"verdict": v, "ist_label": ist_label(h)})
        out["by_hour_utc"]["%02d" % h] = f
    for s, rows in sess.items():
        v, f = verdict(rows)
        f["verdict"] = v
        out["by_session_utc"][s] = f
    cand = [(k, v) for k, v in out["by_hour_utc"].items() if v["verdict"] == "CANDIDATE"]
    bad = [(k, v) for k, v in out["by_hour_utc"].items() if v["verdict"] == "NEGATIVE"]
    cand.sort(key=lambda kv: -kv[1]["net_usdt"])
    bad.sort(key=lambda kv: kv[1]["net_usdt"])
    out["candidate_hours_utc"] = [k for k, _ in cand[:3]]
    out["worst_hours_utc"] = [k for k, _ in bad[:3]]
    out["summary"] = ("No hour has >= %d trades with a steady positive result: no winner is named." % MIN_SLOT) if not cand else \
        "%d hour(s) passed the guard: a thing to test later, not proof of profit." % len(cand)
    return out


def build_report(data_dir, fee_roi=1.0):
    root = os.path.realpath(data_dir)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "min_trades_per_slot": MIN_SLOT, "fee_roi_pct_used_for_old_trades": fee_roi,
           "session_hours_utc": {s[0]: "%02d-%02d" % (s[1], s[2]) for s in SESSIONS}, "boxes": {}, "sources": {}}
    if not os.path.isdir(root):
        return {"tool": VERSION, "read_only": True, "error": "data folder not found"}
    items = {b: [] for b in P.BOXES}
    seen = {b: set() for b in P.BOXES}
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
                    "Time = entry time; hours are UTC (ist_label = IST). Labels describe amount and data quality, not profit.",
                    "CANDIDATE = >= %d trades, net > 0, both halves > 0, still > 0 without the best trade. It is a lead to test, not proof." % MIN_SLOT]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl Money Map: result after fees by hour / session (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--fee-roi", type=float, default=1.0, help="fee %% of ROI for OLD paper trades without a fee (default 1.0)")
    a = ap.parse_args(argv)
    out = a.out or os.path.join(os.path.dirname(I.default_out()), "owl_money_hour.json")
    rep = build_report(I.find_data_dir(a.data), a.fee_roi)
    try:
        R.write_report(rep, out)
    except R.RedactionFailed as e:
        print("REFUSED: secret-looking fields, NO file written:", ", ".join(map(str, e.paths[:20])))
        return 2
    print("Money Map (hour / session) written:", out)
    for n, b in rep.get("boxes", {}).items():
        s = ", ".join("%s %+.1f(%s)" % (k, v["net_usdt"], v["verdict"][:4]) for k, v in b["by_session_utc"].items())
        print("  %-14s trades %-5d [%s] sessions: %s" % (n, b["trades_used"], b["box_label"], s))
        print("      " + b["summary"])
    print("Nothing was changed. Send this JSON file to Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
