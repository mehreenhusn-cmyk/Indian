"""v2_pnl.py - Part 5: REALIZED P&L CHECK (read-only). Answers: "how much did closed trades really make, and can I trust the number?"

Reads the permanent closed-trade files in the data folder (closed_trades_archive.jsonl, closed_trades_archive_b2.jsonl,
trades.json) and NEVER writes to them, never touches a setting, a position or an order. No network, no trading module.
Uses Part 1 (safe path check), Part 2 (secret scrubber) and Part 3 (evidence label).

Four boxes that are NEVER added together (a combined total would mix real money with paper money):
  real_live       source = live, real Binance result          live_estimated  source = live, but the app had to ESTIMATE it
  paper_b1        paper trades of the main bot                paper_b2        paper trades of the old Bot 2 archive
Fee basis per trade (what the stored pnl_usdt already contains):
  applied   fee was taken off when the trade closed (fee_applied)      estimated_in_row  fee estimated into the row (fee_est)
  none_old  OLD paper trade, NO fee inside -> the fee-correct net is ESTIMATED here as invest x fee_roi_pct / 100
  live      pnl comes from Binance; whether it includes fee and funding is NOT verified here (Part 6)
Checks (each lists a count and up to 5 trade ids): duplicate trade, missing pnl, missing / future close time, pnl does not match
roi x invest, gross - fee does not match net, live trade carrying a paper-style fee, trade in the wrong box.
Dual Bot / Brain trades live in their own database and are not in this report. Floating (open) P&L, fees, funding: Parts 6-7.
Run (Termux):  python3 backend/v2_pnl.py [--data DIR] [--out FILE] [--fee-roi 1.0]   -> Download/owl_pnl_check.json
Tests: python3 test/test_v2_pnl_contamination.py"""
import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_inv_redact as R
import v2_inv_safe as S
import v2_inventory as I

VERSION = "v2_pnl 1 (Part 5)"
BOXES = ("real_live", "live_estimated", "paper_b1", "paper_b2")
FILES = (("closed_trades_archive.jsonl", "b1"), ("closed_trades_archive_b2.jsonl", "b2"))
MAX_LINES, MAX_JSON = 2000000, 30 * 1024 * 1024
CHECKS = ("duplicate_trade", "missing_pnl", "missing_close_time", "future_close_time", "pnl_not_roi_times_invest",
          "gross_minus_fee_not_net", "live_trade_with_paper_fee", "wrong_box")


def num(t, k):
    try:
        v = t.get(k)
        return None if v is None or v == "" or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


def box_of(t, file_bot):
    if str(t.get("source") or "").lower() == "live":
        return "live_estimated" if t.get("estimated") else "real_live"
    return "paper_b2" if file_bot == "b2" else "paper_b1"


def fee_basis(t):
    if str(t.get("source") or "").lower() == "live":
        return "live"
    if t.get("fee_applied"):
        return "applied"
    return "estimated_in_row" if t.get("fee_est") else "none_old"


def read_jsonl(path, roots):
    st = {"lines": 0, "unparsable": 0}
    rows = []
    try:
        real, _link = S.resolve_under(path, roots)
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                st["lines"] += 1
                if st["lines"] > MAX_LINES:
                    st["stopped_at_lines"] = MAX_LINES
                    break
                try:
                    r = json.loads(line)
                except ValueError:
                    r = None
                if isinstance(r, dict):
                    rows.append(r)
                else:
                    st["unparsable"] += 1
    except S.UnsafePath as e:
        st["status"] = "not opened: " + str(e)
    except OSError:
        st["status"] = "missing"
    return rows, st


def read_cache(path, roots):
    """trades.json: {"closed_trades": [...], "b2": {"closed_trades": [...]}} -> (b1 rows, b2 rows)."""
    try:
        real, _l = S.resolve_under(path, roots)
        if os.path.getsize(real) > MAX_JSON:
            return [], [], "over 30 MB, skipped"
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            d = json.load(f)
        b2 = (d.get("b2") or {}).get("closed_trades") or []
        return [r for r in d.get("closed_trades") or [] if isinstance(r, dict)], [r for r in b2 if isinstance(r, dict)], "ok"
    except (S.UnsafePath, OSError, ValueError, AttributeError):
        return [], [], "missing or unreadable"


def tkey(t):
    return "%s|%s" % (t.get("id"), t.get("closed_at_ts"))


def new_box():
    return {"trades": 0, "wins": 0, "losses": 0, "net_recorded_usdt": 0.0, "net_fee_correct_usdt": 0.0, "gross_usdt_known": 0.0,
            "fee_applied_usdt": 0.0, "fee_estimated_usdt": 0.0, "by_fee_basis": {}, "first_close_utc": None, "last_close_utc": None,
            "checks": {c: {"count": 0, "examples": []} for c in CHECKS}, "_ts": []}


def flag(box, name, t):
    c = box["checks"][name]
    c["count"] += 1
    if len(c["examples"]) < 5:
        c["examples"].append(str(t.get("id")))


def add_trade(box, t, file_bot, fee_roi, now):
    kind, pnl, inv = fee_basis(t), num(t, "pnl_usdt"), num(t, "invest_usdt") or 0.0
    if box_of(t, file_bot) == "paper_b1" and str(t.get("bot") or "b1").lower() == "b2":
        flag(box, "wrong_box", t)
    if file_bot == "b2" and str(t.get("bot") or "b2").lower() != "b2":
        flag(box, "wrong_box", t)
    ts = num(t, "closed_at_ts")
    if ts is None:
        flag(box, "missing_close_time", t)
    elif ts > now + 86400:
        flag(box, "future_close_time", t)
    else:
        box["_ts"].append(ts)
    if pnl is None:
        flag(box, "missing_pnl", t)
        return
    box["trades"] += 1
    box["wins"] += pnl > 0
    box["losses"] += pnl < 0
    box["by_fee_basis"][kind] = box["by_fee_basis"].get(kind, 0) + 1
    box["net_recorded_usdt"] += pnl
    fee_est = inv * fee_roi / 100.0
    if kind in ("applied", "estimated_in_row"):
        fee = num(t, "fee_usdt")
        fee = fee_est if fee is None else fee
        box["fee_applied_usdt" if kind == "applied" else "fee_estimated_usdt"] += fee
        box["gross_usdt_known"] += pnl + fee
        box["net_fee_correct_usdt"] += pnl
    elif kind == "none_old":
        box["fee_estimated_usdt"] += fee_est
        box["gross_usdt_known"] += pnl
        box["net_fee_correct_usdt"] += pnl - fee_est
    else:
        box["net_fee_correct_usdt"] += pnl
        if t.get("fee_applied"):
            flag(box, "live_trade_with_paper_fee", t)
    roi = num(t, "roi_pct")
    if inv > 0 and roi is not None and abs(pnl - inv * roi / 100.0) > max(0.02, 0.01 * abs(pnl)):
        flag(box, "pnl_not_roi_times_invest", t)
    g, f, r = num(t, "gross_roi_pct"), num(t, "fee_roi_pct"), roi
    if kind == "applied" and None not in (g, f, r) and abs((g - f) - r) > 0.05:
        flag(box, "gross_minus_fee_not_net", t)


def fmt_ts(x):
    return datetime.datetime.fromtimestamp(x, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def finish(box):
    ts = box.pop("_ts")
    if ts:
        box["first_close_utc"], box["last_close_utc"] = fmt_ts(min(ts)), fmt_ts(max(ts))
    for k in ("net_recorded_usdt", "net_fee_correct_usdt", "gross_usdt_known", "fee_applied_usdt", "fee_estimated_usdt"):
        box[k] = round(box[k], 4)
    bad = sum(box["checks"][c]["count"] for c in ("missing_close_time", "future_close_time", "missing_pnl"))
    box["label"] = I.label(box["trades"], bad == 0)
    box["needs_fee_estimate"] = box["by_fee_basis"].get("none_old", 0) > 0
    box["trusted_for_research"] = box["label"] in ("Exploratory", "Watch") and all(v["count"] == 0 for v in box["checks"].values())


def build_report(data_dir, fee_roi=1.0):
    root = os.path.realpath(data_dir)
    now = time.time()
    rep = {"tool": VERSION, "made_utc": fmt_ts(now), "read_only": True, "fee_roi_pct_used_for_old_trades": fee_roi,
           "boxes": {b: new_box() for b in BOXES}, "sources": {}, "cache_check": {}}
    if not os.path.isdir(root):
        return {"tool": VERSION, "read_only": True, "error": "data folder not found"}
    seen = {b: set() for b in BOXES}
    keys = {"b1": set(), "b2": set()}
    for name, file_bot in FILES:
        rows, st = read_jsonl(os.path.join(root, name), [root])
        rep["sources"][name] = st
        for t in rows:
            b = box_of(t, file_bot)
            k = tkey(t)
            keys[file_bot].add(k)
            if k in seen[b]:
                flag(rep["boxes"][b], "duplicate_trade", t)        # flagged, counted once
                continue
            seen[b].add(k)
            add_trade(rep["boxes"][b], t, file_bot, fee_roi, now)
    c1, c2, status = read_cache(os.path.join(root, "trades.json"), [root])
    rep["sources"]["trades.json"] = {"status": status, "b1_rows": len(c1), "b2_rows": len(c2)}
    rep["cache_check"] = {"b1_only_in_cache": sum(tkey(t) not in keys["b1"] for t in c1),
                          "b2_only_in_cache": sum(tkey(t) not in keys["b2"] for t in c2),
                          "meaning": "trades that trades.json has but the permanent archive does not (NOT counted in the boxes)"}
    for b in rep["boxes"].values():
        finish(b)
    rep["notes"] = ["The four boxes are never added together: real money and paper money must not be mixed.",
                    "net_fee_correct_usdt: old paper trades get the fee ESTIMATED; real_live is as Binance gave it (fee / funding not verified yet).",
                    "Labels describe amount and data quality, not profit.",
                    "Dual Bot / Brain trades are in their own database; floating P&L, fees and funding come in Parts 6-7."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl realized P&L check (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--fee-roi", type=float, default=1.0, help="fee %% of ROI for OLD paper trades without a fee (default 1.0)")
    a = ap.parse_args(argv)
    out = a.out or os.path.join(os.path.dirname(I.default_out()), "owl_pnl_check.json")
    rep = build_report(I.find_data_dir(a.data), a.fee_roi)
    try:
        R.write_report(rep, out)
    except R.RedactionFailed as e:
        print("REFUSED: secret-looking fields, NO file written:", ", ".join(map(str, e.paths[:20])))
        return 2
    print("P&L check written:", out)
    for n, b in rep.get("boxes", {}).items():
        print("  %-14s trades %-5d net(fee-correct) %+.2f USDT  [%s]" % (n, b["trades"], b["net_fee_correct_usdt"], b["label"]))
    print("Nothing was changed. Send this JSON file to Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
