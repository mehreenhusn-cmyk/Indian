"""v2_playbook_next.py - Part 12: INDICATOR PLAYBOOK 2 of 3 (read-only). Answers: "after the TSI + Z-score showed a state, what did the trade do NEXT,
and would leaving at the first warning have paid after fees?"  (Part 11 looked at the first candle only; this looks at EVERY candle after entry.)

Same data and join as Part 11 (reused: v2_playbook): ai_trade_paths.jsonl (ind = [t_sec, z, tsi, tsi_signal] per closed candle, s = gross ROI path,
roi_final = GROSS ROI %) joined by key "<id>@<opened_ts>" to the closed paper trades. Paper boxes only; boxes are never added together.
1) NEXT-CANDLE TABLE. Every indicator candle of every trade is one observation, with its state in trade direction (SELL turned around, same fixed cut
   points as Part 11). For each state, in GROSS ROI points (a fee is paid once per trade either way, so it cancels in hold-vs-leave):
     next_candle = ROI at the next candle - ROI now       to_exit = ROI at the real exit - ROI now  (> 0: holding beat leaving at that candle)
   Bars of one trade are not independent, so the guard counts TRADES: a state under 30 distinct trades = NOT ENOUGH DATA. CONSISTENT = both halves
   (older / newer trades) have the same sign for next_candle and to_exit; otherwise MIXED. A state is a description, never a rule to trade.
2) EXIT-AT-WARNING REPLAY. Warning = TSI against its signal AND Z fell 0.5 from its best (Part 11 rule). Replay: leave at the ROI of the warning candle
   instead of the real exit; same round-trip fee, no slippage. Result in USDT = invest x (ROI at warning - ROI at exit) / 100 (pnl = invest x roi / 100,
   Part 5). Judged with the Part 8 guard (>= 30 trades, net > 0, both halves > 0, > 0 without the best trade). A REPLAY on saved candles, not a result.
Run (Termux):  python3 backend/v2_playbook_next.py [--data DIR] [--out FILE] [--fee-roi 1.0]   -> Download/owl_playbook_next.json
Tests: python3 test/test_v2_playbook_next.py"""
import argparse
import bisect
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_inv_redact as R
import v2_inventory as I
import v2_money_hour as M
import v2_playbook as B
import v2_pnl as P

VERSION = "v2_playbook_next 1 (Part 12)"
DIMS = ("z_state", "tsi_vs_signal", "tsi_zone", "agreement")


def roi_at(times, rois, t):
    """ROI of the last saved sample at or before t (None when the path starts later)."""
    i = bisect.bisect_right(times, t) - 1
    return rois[i] if i >= 0 else None


def reduce_bars(rec):
    """One saved path line -> one record per trade with one tuple per indicator candle: (4 state names, ROI now, ROI next). None when unusable."""
    base = B.reduce_path(rec)
    if base is None or base["final"] is None:
        return None
    d = base["dir"]
    ind = sorted(([float(v) for v in x[:4]] for x in (rec.get("ind") or []) if B.sample_ok(x)), key=lambda x: x[0])
    path = sorted(((B.fnum(x[0]), B.fnum(x[1])) for x in (rec.get("s") or []) if isinstance(x, (list, tuple)) and len(x) >= 2
                   and B.fnum(x[0]) is not None and B.fnum(x[1]) is not None))
    times, rois = [p[0] for p in path], [p[1] for p in path]
    bars = []
    for k, bar in enumerate(ind):
        now = roi_at(times, rois, bar[0])
        nxt = roi_at(times, rois, ind[k + 1][0]) if k + 1 < len(ind) else base["final"]   # the last candle's "next" is the real exit
        if now is None or nxt is None:
            continue
        st = B.states({"first": bar, "dir": d, "warn_t": None})
        bars.append(tuple(st[n] for n in DIMS) + (now, nxt))
    return {"bars": bars, "final": base["final"], "warn_roi": base["warn_roi"], "warn_t": base["warn_t"]}


def sign(x):
    return (x > 0) - (x < 0)


def state_facts(obs, order):
    """obs = [(trade_index, next_move, to_exit)] of ONE state; order = trade_index -> rank by open time (for the two halves)."""
    trades = {o[0] for o in obs}
    n = len(trades)
    f = {"candles": len(obs), "trades": n, "label": I.label(n, True),
         "avg_next_candle_roi": round(sum(o[1] for o in obs) / len(obs), 3), "up_next_candle_pct": round(100.0 * sum(o[1] > 0 for o in obs) / len(obs), 1),
         "avg_to_exit_roi": round(sum(o[2] for o in obs) / len(obs), 3)}
    if n < M.MIN_SLOT:
        f["verdict"] = "NOT ENOUGH DATA"
        return f
    cut = sorted(order[t] for t in trades)[n // 2]
    halves = ([o for o in obs if order[o[0]] < cut], [o for o in obs if order[o[0]] >= cut])
    sg = [(sign(sum(o[1] for o in h)), sign(sum(o[2] for o in h))) for h in halves if h]
    f["first_half_to_exit_roi"] = round(sum(o[2] for o in halves[0]) / max(1, len(halves[0])), 3)
    f["second_half_to_exit_roi"] = round(sum(o[2] for o in halves[1]) / max(1, len(halves[1])), 3)
    f["verdict"] = "CONSISTENT" if len(sg) == 2 and sg[0] == sg[1] and 0 not in sg[0] else "MIXED"
    return f


def replay(rows):
    """rows = [(ts, usdt)] exit-at-warning minus real exit. Part 8 guard decides; the verdict names are Part 8's."""
    v, f = M.verdict(rows)
    f["verdict"] = {"CANDIDATE": "LEAVING AT THE WARNING PAID (lead)", "NEGATIVE": "LEAVING AT THE WARNING COST MONEY"}.get(v, v)
    f["label_kind"] = "REPLAY on saved candles: same fee, no slippage, exit at the ROI of the warning candle"
    return f


def box_report(items, paths, fee_roi):
    st = {"closed_trades": len(items), "no_pnl": 0, "no_time": 0, "no_samples": 0, "with_samples": 0}
    used, per = [], {d: {} for d in DIMS}
    for t in items:
        net, (ts, _fc) = M.net_fee_correct(t, fee_roi), M.entry_ts(t)
        red = paths.get("%s@%d" % (t.get("id"), int(P.num(t, "opened_at_ts") or 0)))
        if net is None:
            st["no_pnl"] += 1
        elif ts is None:
            st["no_time"] += 1
        elif red is None:
            st["no_samples"] += 1
        else:
            st["with_samples"] += 1
            used.append((ts, t, red))
    used.sort(key=lambda x: x[0])
    order = {i: i for i in range(len(used))}                  # rank by open time, oldest first
    rows = []
    for i, (ts, t, red) in enumerate(used):
        for b in red["bars"]:
            for k, d in enumerate(DIMS):
                per[d].setdefault(b[k], []).append((i, b[5] - b[4], red["final"] - b[4]))
        inv = P.num(t, "invest_usdt")
        if red["warn_t"] is not None and red["warn_roi"] is not None and inv is not None and inv > 0:
            rows.append((ts, inv * (red["warn_roi"] - red["final"]) / 100.0))
    out = {"trades_used": st["with_samples"], "stats": st, "box_label": I.label(st["with_samples"], True), "next_candle": {}}
    for d in DIMS:
        facts = {s: state_facts(o, order) for s, o in sorted(per[d].items())}
        ok = [s for s, f in facts.items() if f["verdict"] != "NOT ENOUGH DATA"]
        out["next_candle"][d] = {"states_tested": len(ok), "consistent": sum(facts[s]["verdict"] == "CONSISTENT" for s in ok), "states": facts,
                                 "luck_note": "NOT ENOUGH DATA: no state has %d trades." % M.MIN_SLOT if not ok else
                                 "%d of %d states are CONSISTENT in both halves; several states are compared at once, so read it as a description, not a rule." % (
                                     sum(facts[s]["verdict"] == "CONSISTENT" for s in ok), len(ok))}
    out["exit_at_warning_replay"] = replay(rows)
    return out


def build_report(data_dir, fee_roi=1.0):
    root = os.path.realpath(data_dir)
    if not os.path.isdir(root):
        return {"tool": VERSION, "read_only": True, "error": "data folder not found"}
    paths, pst = B.read_paths(os.path.join(root, B.PATHS_FILE), [root], reduce_bars)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "min_trades_per_state": M.MIN_SLOT, "fee_roi_pct_used_for_old_trades": fee_roi,
           "paths_file": pst, "boxes": {}, "sources": {}}
    items, seen = {b: [] for b in B.PAPER_BOXES}, {b: set() for b in B.PAPER_BOXES}
    for name, file_bot in P.FILES:
        rows, s = P.read_jsonl(os.path.join(root, name), [root])
        rep["sources"][name] = s
        for t in rows:
            b, k = P.box_of(t, file_bot), P.tkey(t)
            if b in items and k not in seen[b]:
                seen[b].add(k)
                items[b].append(t)
    for b in B.PAPER_BOXES:
        rep["boxes"][b] = box_report(items[b], paths, fee_roi)
    rep["notes"] = ["Boxes are never added together. Real live boxes are not analysed: indicator samples exist for paper trades only.",
                    "next_candle / to_exit are GROSS ROI points (the fee is paid once per trade either way). They are not money and are never added to a net.",
                    "The replay is in USDT with the same fee and NO slippage; it uses saved candles only. A lead to test later (Parts 39-46), never proof of profit.",
                    "Trades without saved indicator samples are counted as no_samples and are not used."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl Indicator Playbook 2: what each TSI + Z state does next; exit-at-warning replay (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--fee-roi", type=float, default=1.0, help="fee %% of ROI for OLD paper trades without a fee (default 1.0)")
    a = ap.parse_args(argv)
    out = a.out or os.path.join(os.path.dirname(I.default_out()), "owl_playbook_next.json")
    rep = build_report(I.find_data_dir(a.data), a.fee_roi)
    try:
        R.write_report(rep, out)
    except R.RedactionFailed as e:
        print("REFUSED: secret-looking fields, NO file written:", ", ".join(map(str, e.paths[:20])))
        return 2
    print("Indicator Playbook 2 written:", out, "| paths file:", rep.get("paths_file", {}).get("status", "ok"))
    for n, b in rep.get("boxes", {}).items():
        print("  %-9s trades with samples %-5d [%s]" % (n, b["trades_used"], b["box_label"]))
        for d, x in b["next_candle"].items():
            print("      %-14s states tested %-2d consistent %-2d" % (d, x["states_tested"], x["consistent"]))
        r = b["exit_at_warning_replay"]
        print("      exit-at-warning replay: %d trades, net %+.2f USDT  %s" % (r["trades"], r["net_usdt"], r["verdict"]))
    print("Nothing was changed. Send this JSON file to Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
