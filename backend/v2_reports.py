"""v2_reports.py - Part 61: FEES AND TAX REPORT (read-only). Answers: "how much was gross, how much went to fees, what is net, and what could the tax estimate be?"

Reads the same permanent closed-trade files as Part 5 (v2_pnl.py, its readers are reused) and NEVER writes to them, never touches a setting, a position or an
order. No network, no trading module. The four boxes are NEVER added together (real money and paper money must not be mixed):
  real_live | live_estimated | paper_b1 | paper_b2
Per box and per UTC month and per financial year it separates: gross, fees, net realized. Same fee rules as Part 5 (applied / estimated_in_row / none_old /
live). Costs already inside the stored pnl are NOT subtracted twice. Funding: shown ONLY as an extra line when a trade row carries funding_usdt; it is never
taken off the net (whether Binance realized pnl already holds it is NOT verified, the report says so). Money is summed with Decimal (no float rounding).
TAX = estimate only, never advice. There is NO built-in tax rate. The estimate needs the owner's own file v2_tax_config.json in the data folder:
  {"version": "2026-1", "jurisdiction_label": "...", "tax_rate_pct": 0-100, "financial_year_start_month": 1-12,
   "usdt_to_local_rate": optional number, "local_currency": optional text}      (rate and month must be confirmed by him / his accountant)
Without a valid file the answer is "TAX NOT CALCULATED" with the reason. Only real_live is ever taxed; paper boxes are marked "not taxable (paper)";
live_estimated trades in a year make that year "data incomplete". Simple rule only: tax = max(0, net of the year) x rate; no loss carry-forward, no other rules.
Run (Termux):  python3 backend/v2_reports.py [--data DIR] [--out FILE] [--fee-roi 1.0]   -> Download/owl_fees_tax.json"""
import argparse
import datetime
import json
import os
import sys
import time
from decimal import Decimal, InvalidOperation

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v2_inv_redact as R
import v2_inventory as I
import v2_pnl as P

VERSION = "v2_reports 1 (Part 61)"
CONFIG_FILE = "v2_tax_config.json"
NOT_TAXABLE = "not taxable (paper)"


def D(x):
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError):
        return None


def num(t, k):
    v = P.num(t, k)
    return None if v is None else D(v)


def trade_money(t, file_bot, fee_roi):
    """-> dict(box, net, fee, gross, estimated, funding) or None when pnl is missing. Same fee rules as v2_pnl.add_trade."""
    pnl = num(t, "pnl_usdt")
    if pnl is None:
        return None
    kind, inv = P.fee_basis(t), num(t, "invest_usdt") or Decimal(0)
    est = inv * D(fee_roi) / 100
    if kind in ("applied", "estimated_in_row"):
        fee = num(t, "fee_usdt")
        fee = est if fee is None else fee
        net, gross, estimated = pnl, pnl + fee, kind == "estimated_in_row" or num(t, "fee_usdt") is None
    elif kind == "none_old":
        fee, net, gross, estimated = est, pnl - est, pnl, True
    else:                                                     # live: Binance's own number; fee / funding not verified here
        fee = num(t, "fee_usdt")
        net, gross, estimated = pnl, (None if fee is None else pnl + fee), False
    return {"box": P.box_of(t, file_bot), "net": net, "fee": fee, "gross": gross, "estimated": estimated, "funding": num(t, "funding_usdt")}


def new_acc():
    return {"trades": 0, "net": Decimal(0), "fee": Decimal(0), "gross": Decimal(0), "fee_rows": 0, "gross_rows": 0, "estimated_rows": 0,
            "funding": Decimal(0), "funding_rows": 0}


def add(acc, m):
    acc["trades"] += 1
    acc["net"] += m["net"]
    if m["fee"] is not None:
        acc["fee"] += m["fee"]
        acc["fee_rows"] += 1
    if m["gross"] is not None:
        acc["gross"] += m["gross"]
        acc["gross_rows"] += 1
    acc["estimated_rows"] += bool(m["estimated"])
    if m["funding"] is not None:
        acc["funding"] += m["funding"]
        acc["funding_rows"] += 1


def out(acc):
    q = lambda v: float(round(v, 4))
    r = {"trades": acc["trades"], "gross_usdt": q(acc["gross"]), "fees_usdt": q(acc["fee"]), "net_realized_usdt": q(acc["net"]),
         "trades_with_fee": acc["fee_rows"], "trades_with_gross": acc["gross_rows"], "fee_estimated_rows": acc["estimated_rows"]}
    if acc["trades"] > acc["fee_rows"] or acc["trades"] > acc["gross_rows"]:
        r["note"] = "gross / fees cover only the trades that have them (counts above); net covers all"
    if acc["funding_rows"]:
        r["funding_usdt_shown_only"] = q(acc["funding"])
        r["funding_note"] = "NOT taken off the net: whether the stored pnl already holds funding is not verified"
    return r


def month_key(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m")


def fy_key(ts, start_month):
    d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
    y = d.year if d.month >= start_month else d.year - 1
    return ("FY%d" % y) if start_month == 1 else ("FY%d-%s (starts month %d)" % (y, str(y + 1)[2:], start_month))


def load_config(data_dir):
    """-> (config dict or None, reason text). Never guesses a rate."""
    p = os.path.join(os.path.realpath(data_dir), CONFIG_FILE)
    if os.path.islink(p) or not os.path.isfile(p):
        return None, "no %s in the data folder (the owner / his accountant must create it; no rate is built in)" % CONFIG_FILE
    try:
        with open(p, "r", encoding="utf-8") as f:
            c = json.load(f)
        rate, sm = c.get("tax_rate_pct"), c.get("financial_year_start_month")
        ok = (isinstance(c, dict) and isinstance(c.get("version"), str) and c["version"].strip() and isinstance(c.get("jurisdiction_label"), str)
              and not isinstance(rate, bool) and isinstance(rate, (int, float)) and 0 <= rate <= 100
              and not isinstance(sm, bool) and isinstance(sm, int) and 1 <= sm <= 12)
        if not ok:
            return None, "%s is not valid (needs version, jurisdiction_label, tax_rate_pct 0-100, financial_year_start_month 1-12)" % CONFIG_FILE
        fx = c.get("usdt_to_local_rate")
        if fx is not None and (isinstance(fx, bool) or not isinstance(fx, (int, float)) or fx <= 0):
            return None, "%s: usdt_to_local_rate must be a number above 0" % CONFIG_FILE
        return c, "ok"
    except (OSError, ValueError):
        return None, "%s could not be read" % CONFIG_FILE


def tax_block(fy_real, fy_est, cfg, why):
    """fy_real: {fy: net Decimal} for real_live only; fy_est: set of years that also hold live_estimated trades."""
    if cfg is None:
        return {"state": "TAX NOT CALCULATED", "reason": why, "estimate_only_not_advice": True}
    rate, fx, years = D(cfg["tax_rate_pct"]), cfg.get("usdt_to_local_rate"), {}
    for fy, net in sorted(fy_real.items()):
        y = {"net_realized_usdt": float(round(net, 4)), "tax_estimate_usdt": float(round(max(Decimal(0), net) * rate / 100, 4)),
             "data": "incomplete: this year also has live_estimated trades" if fy in fy_est else "complete for real_live rows"}
        if fx:
            y["tax_estimate_" + str(cfg.get("local_currency") or "local")] = float(round(D(y["tax_estimate_usdt"]) * D(fx), 2))
        years[fy] = y
    return {"state": "ESTIMATE", "config_version": cfg["version"], "jurisdiction_label": cfg["jurisdiction_label"], "tax_rate_pct": cfg["tax_rate_pct"],
            "years": years, "estimate_only_not_advice": True,
            "rule": "tax = max(0, net realized of the year) x rate; no loss carry-forward, no other rules; check with an accountant"}


def build_report(data_dir, fee_roi=1.0, now=None):
    now = time.time() if now is None else now
    root = os.path.realpath(data_dir)
    if not os.path.isdir(root):
        return {"tool": VERSION, "read_only": True, "error": "data folder not found"}
    cfg, why = load_config(root)
    sm = cfg["financial_year_start_month"] if cfg else 1
    tot = {b: new_acc() for b in P.BOXES}
    mon = {b: {} for b in P.BOXES}
    fy = {b: {} for b in P.BOXES}
    seen, src, no_time = {b: set() for b in P.BOXES}, {}, {b: 0 for b in P.BOXES}
    for name, file_bot in P.FILES:
        rows, st = P.read_jsonl(os.path.join(root, name), [root])
        src[name] = st
        for t in rows:
            m = trade_money(t, file_bot, fee_roi)
            if m is None:
                continue
            b, k = m["box"], P.tkey(t)
            if k in seen[b]:
                continue                                       # duplicate: counted once (Part 5 flags it)
            seen[b].add(k)
            add(tot[b], m)
            ts = P.num(t, "closed_at_ts")
            if ts is None or ts > now + 86400:
                no_time[b] += 1
                continue
            add(mon[b].setdefault(month_key(ts), new_acc()), m)
            add(fy[b].setdefault(fy_key(ts, sm), new_acc()), m)
    fy_est = {y for y in fy["live_estimated"]}
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(now), "read_only": True, "fee_roi_pct_used_for_old_trades": fee_roi, "sources": src, "boxes": {}}
    for b in P.BOXES:
        rep["boxes"][b] = {"totals": out(tot[b]), "by_month_utc": {k: out(v) for k, v in sorted(mon[b].items())},
                           "by_financial_year": {k: out(v) for k, v in sorted(fy[b].items())}, "trades_without_usable_close_time": no_time[b],
                           "tax": "estimate below (real_live only)" if b == "real_live" else (NOT_TAXABLE if b.startswith("paper") else
                                  "live but estimated by the app: shown, not taxed (data incomplete)")}
    rep["tax"] = tax_block({k: v["net"] for k, v in fy["real_live"].items()}, fy_est, cfg, why)
    rep["notes"] = ["The four boxes are never added together.",
                    "Gross = net + fee. Old paper trades without a stored fee get the fee ESTIMATED (fee_estimated_rows counts them).",
                    "Funding is shown only when a trade row has funding_usdt and is never subtracted (not verified whether pnl holds it already).",
                    "Tax is an estimate for reading only, not advice; there is no built-in rate."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl fees and tax report (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--fee-roi", type=float, default=1.0)
    a = ap.parse_args(argv)
    o = a.out or os.path.join(os.path.dirname(I.default_out()), "owl_fees_tax.json")
    rep = build_report(I.find_data_dir(a.data), a.fee_roi)
    try:
        R.write_report(rep, o)
    except R.RedactionFailed as e:
        print("REFUSED: secret-looking fields, NO file written:", ", ".join(map(str, e.paths[:20])))
        return 2
    print("Fees + tax report written:", o)
    for n, b in rep.get("boxes", {}).items():
        t = b["totals"]
        print("  %-14s trades %-5d gross %+.2f  fees %.2f  net %+.2f USDT" % (n, t["trades"], t["gross_usdt"], t["fees_usdt"], t["net_realized_usdt"]))
    print("  tax:", rep.get("tax", {}).get("state"))
    print("Nothing was changed. Send this JSON file to Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
