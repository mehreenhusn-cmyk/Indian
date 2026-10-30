"""v2_playbook.py - Part 11: INDICATOR PLAYBOOK 1 of 3 (read-only). Post-mortem of the Special Master pane (TSI + Z-score) on CLOSED paper trades.
Answers: "when the indicators agreed with the trade right after entry, did the trade make money AFTER fees, and did they warn before profit was given back?"

Data (read from ai_ind_tracker.py / ai_path_logger.py, not guessed): ai_trade_paths.jsonl holds one line per closed paper trade with
  ind = [[t_sec, z, tsi, tsi_signal], ...]  one sample per CLOSED candle after entry (t_sec = candle close, seconds since entry)
  s = [[t_sec, roi, lo, hi], ...]  gross ROI path      roi_final = GROSS ROI %      key = "<id>@<opened_ts>"
It is joined to the closed-trade archives (same key) so every trade keeps the fee-correct net of Part 5 / 8. Older trades have no samples: they are
counted as UNKNOWN (= no samples), shown, and NEVER ranked. Nothing is guessed. Boxes (paper_b1, paper_b2) are never added together. Real live boxes are not
analysed here: samples are recorded for paper trades only.
STATE = the FIRST closed candle after entry (not the exact entry tick), turned into the trade direction (BUY = +, SELL = -), fixed cut points (not tuned):
  z_state       Z with the trade >= 1 / 0..1 / against        tsi_vs_signal  TSI above its signal (BUY) or below it (SELL) = WITH
  tsi_zone      TSI x direction: > 30 / 0..30 / -30..0 / < -30 (OB / OS = 30 as on the chart)
  agreement     BOTH_WITH / Z_ONLY / TSI_ONLY / NEITHER        warning       WARNED = TSI against its signal AND Z fell 0.5 from its best (same rule as ai_observer)
Same FAKE-WINNER GUARD as Parts 8-9 (reused): < 30 trades = NOT ENOUGH DATA, never ranked; CANDIDATE needs net > 0, both halves > 0, > 0 without the best trade.
Several states are compared at once, so each split gives a luck_note. The warning table is HINDSIGHT (gross ROI points, never a profit claim).
Run (Termux):  python3 backend/v2_playbook.py [--data DIR] [--out FILE] [--fee-roi 1.0]   -> Download/owl_playbook.json
Tests: python3 test/test_v2_playbook.py"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_inv_redact as R
import v2_inv_safe as SF
import v2_inventory as I
import v2_money_hour as M
import v2_money_split as S
import v2_pnl as P

VERSION = "v2_playbook 1 (Part 11)"
PATHS_FILE = "ai_trade_paths.jsonl"
PAPER_BOXES = ("paper_b1", "paper_b2")
Z_STRONG, TSI_OB, Z_DROP = 1.0, 30.0, 0.5
NO_DATA = S.UNKNOWN          # trade without indicator samples: split_report shows it but never ranks it
SPLITS = ("z_state", "tsi_vs_signal", "tsi_zone", "agreement", "warning")


def fnum(x):
    try:
        v = float(x)
        return v if v == v and abs(v) != float("inf") else None
    except (TypeError, ValueError):
        return None


def sign_of(action):
    a = str(action or "").strip().upper()
    return 1.0 if a == "BUY" else (-1.0 if a == "SELL" else None)


def sample_ok(x):
    return isinstance(x, (list, tuple)) and len(x) >= 4 and all(fnum(v) is not None for v in x[:4])


def reduce_path(rec):
    """One saved path line -> the few numbers Part 11 needs (None when the line has no usable indicator sample or direction)."""
    d = sign_of(rec.get("action"))
    ind = [x for x in (rec.get("ind") or []) if sample_ok(x)]
    if d is None or not ind:
        return None
    ind = sorted(([float(v) for v in x[:4]] for x in ind), key=lambda x: x[0])
    first, zbest, warn = ind[0], None, None
    for t, z, tsi, tsl in ind:
        zd = z * d
        zbest = zd if zbest is None else max(zbest, zd)
        if warn is None and (tsi - tsl) * d < 0 and zbest - zd >= Z_DROP:
            warn = t
    path = [x for x in (rec.get("s") or []) if isinstance(x, (list, tuple)) and len(x) >= 4 and fnum(x[0]) is not None and fnum(x[1]) is not None]
    out = {"dir": d, "first": first, "n_ind": len(ind), "warn_t": warn, "final": fnum(rec.get("roi_final")), "warn_roi": None,
           "peak": max([fnum(x[3]) for x in path if fnum(x[3]) is not None] or [None]) if path else None}
    if warn is not None:
        at = [fnum(x[1]) for x in sorted(path, key=lambda x: fnum(x[0])) if fnum(x[0]) >= warn]
        out["warn_roi"] = at[0] if at else None
    return out


def read_paths(path, roots, reducer=None):
    """Streaming read (the file can be tens of MB): key -> reduced record. Read-only, path-safe. reducer = how one line is boiled down (Part 12 passes its own)."""
    reducer = reducer or reduce_path
    st, res = {"lines": 0, "unparsable": 0, "usable": 0}, {}
    try:
        real, _ = SF.resolve_under(path, roots)
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                st["lines"] += 1
                if st["lines"] > P.MAX_LINES:
                    st["stopped_at_lines"] = P.MAX_LINES
                    break
                try:
                    r = json.loads(line)
                except ValueError:
                    r = None
                if not isinstance(r, dict):
                    st["unparsable"] += 1
                    continue
                red = reducer(r)
                if red and r.get("key") not in res:
                    res[r.get("key")] = red
                    st["usable"] += 1
    except SF.UnsafePath as e:
        st["status"] = "not opened: " + str(e)
    except OSError:
        st["status"] = "missing"
    return res, st


def states(red):
    """Trade-direction state of the first closed candle after entry."""
    t, z, tsi, tsl = red["first"]
    d = red["dir"]
    zd, td, gap = z * d, tsi * d, (tsi - tsl) * d
    z_state = "Z_WITH_1_OR_MORE" if zd >= Z_STRONG else ("Z_WITH_0_TO_1" if zd >= 0 else "Z_AGAINST")
    tsi_zone = "TSI_WITH_OVER_30" if td > TSI_OB else ("TSI_WITH_0_30" if td >= 0 else ("TSI_AGAINST_0_30" if td >= -TSI_OB else "TSI_AGAINST_OVER_30"))
    z_ok, t_ok = zd > 0, gap > 0
    agree = "BOTH_WITH" if z_ok and t_ok else ("Z_ONLY" if z_ok else ("TSI_ONLY" if t_ok else "NEITHER"))
    return {"z_state": z_state, "tsi_vs_signal": "TSI_WITH_SIGNAL" if t_ok else "TSI_AGAINST_SIGNAL", "tsi_zone": tsi_zone, "agreement": agree,
            "warning": "WARNED" if red["warn_t"] is not None else "NO_WARNING"}


def warning_table(reds):
    """HINDSIGHT only: for trades that were WARNED, gross ROI at the warning vs at the real exit (ROI points, same fee either way)."""
    rows = [(r["warn_roi"], r["final"], r["peak"]) for r in reds if r["warn_t"] is not None and r["warn_roi"] is not None and r["final"] is not None]
    n = len(rows)
    out = {"label": "HINDSIGHT (gross ROI points, not money, never added to a net)", "warned_trades": n}
    if n < M.MIN_SLOT:
        out["verdict"] = "NOT ENOUGH DATA"
        return out
    better = sum(f < w for w, f, _ in rows)
    out.update({"verdict": "MEASURED", "exit_at_warning_was_better": better, "real_exit_was_better": sum(f > w for w, f, _ in rows),
                "avg_roi_at_warning": round(sum(w for w, _, _ in rows) / n, 3), "avg_roi_at_real_exit": round(sum(f for _, f, _ in rows) / n, 3),
                "note": "Whether exiting at the warning would have paid after fees is Part 12; this only shows where the trade stood."})
    return out


def box_report(items, paths, fee_roi):
    st = {"closed_trades": len(items), "no_pnl": 0, "no_time": 0, "no_samples": 0, "with_samples": 0}
    prepared = []
    for t in items:
        net, (ts, _fc) = M.net_fee_correct(t, fee_roi), M.entry_ts(t)
        key = "%s@%d" % (t.get("id"), int(P.num(t, "opened_at_ts") or 0))
        red = paths.get(key)
        if net is None:
            st["no_pnl"] += 1
        elif ts is None:
            st["no_time"] += 1
        else:
            st["with_samples" if red else "no_samples"] += 1
            prepared.append((ts, net, red))
    used = len(prepared)
    out = {"trades_used": used, "stats": st, "box_label": I.label(used, True), "splits": {}}
    sts = [(ts, net, states(red) if red else None) for ts, net, red in prepared]
    for name in SPLITS:
        out["splits"][name] = S.split_report([(ts, net, s[name] if s else NO_DATA) for ts, net, s in sts])
    out["warning_hindsight"] = warning_table([red for _, _, red in prepared if red])
    return out


def build_report(data_dir, fee_roi=1.0):
    root = os.path.realpath(data_dir)
    if not os.path.isdir(root):
        return {"tool": VERSION, "read_only": True, "error": "data folder not found"}
    paths, pst = read_paths(os.path.join(root, PATHS_FILE), [root])
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "min_trades_per_slot": M.MIN_SLOT, "fee_roi_pct_used_for_old_trades": fee_roi,
           "paths_file": pst, "boxes": {}, "sources": {}}
    items, seen = {b: [] for b in PAPER_BOXES}, {b: set() for b in PAPER_BOXES}
    for name, file_bot in P.FILES:
        rows, st = P.read_jsonl(os.path.join(root, name), [root])
        rep["sources"][name] = st
        for t in rows:
            b, k = P.box_of(t, file_bot), P.tkey(t)
            if b in items and k not in seen[b]:
                seen[b].add(k)
                items[b].append(t)
    for b in PAPER_BOXES:
        rep["boxes"][b] = box_report(items[b], paths, fee_roi)
    rep["notes"] = ["Boxes are never added together. Real live boxes are not analysed: indicator samples exist for paper trades only.",
                    "State = first CLOSED candle after entry (up to one candle after the entry tick), in trade direction. Fixed cut points, not tuned.",
                    "UNKNOWN = older trade without indicator samples: shown, never ranked. Dual Bot / Brain have no time column (Part 3), so they are not used here.",
                    "Result per trade is fee-correct (Part 5 / 8). CANDIDATE = a lead to test later, never proof. The warning table is hindsight."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl Indicator Playbook 1: TSI + Z-score state vs result after fees (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--fee-roi", type=float, default=1.0, help="fee %% of ROI for OLD paper trades without a fee (default 1.0)")
    a = ap.parse_args(argv)
    out = a.out or os.path.join(os.path.dirname(I.default_out()), "owl_playbook.json")
    rep = build_report(I.find_data_dir(a.data), a.fee_roi)
    try:
        R.write_report(rep, out)
    except R.RedactionFailed as e:
        print("REFUSED: secret-looking fields, NO file written:", ", ".join(map(str, e.paths[:20])))
        return 2
    print("Indicator Playbook 1 written:", out, "| paths file:", rep.get("paths_file", {}).get("status", "ok"))
    for n, b in rep.get("boxes", {}).items():
        s = b["stats"]
        print("  %-9s trades %-5d with indicator samples %-5d no samples %-5d [%s]" % (n, b["trades_used"], s["with_samples"], s["no_samples"], b["box_label"]))
        for d, sp in b["splits"].items():
            if sp["slots_tested"]:
                print("      %-14s tested %-2d candidates %-2d  %s" % (d, sp["slots_tested"], sp["candidates"], sp["luck_note"][:60]))
    print("Nothing was changed. Send this JSON file to Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
