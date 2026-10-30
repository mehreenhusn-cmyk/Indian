"""v2_pnl_open.py - Part 6: FLOATING (OPEN) P&L + LIVE FEE/FUNDING FACTS (read-only). Answers: "is my floating profit real money?"

Reads the open positions the app saved in owl.db (table `positions`) through the Part 1 safe opener (a WAL database is read by a COPY,
the original is never touched) and live_open_context.json. No network, no trading module, nothing is written next to the data.
Uses Part 1 (safe open), Part 2 (scrubber) and Part 5 (box rules, reading of the closed-trade archive).
For each open position it recomputes P&L from the SAVED price with the app's own formula (roi = price move x leverage; pnl = margin x roi / 100):
  gross = before fee | fee = the full round-trip fee the app already deducts although the trade is still open | net = what the app shows
Boxes (never added together): paper_b1, paper_b2, live_local_copy (the app's own record of a live trade; its real floating P&L needs the
exchange price and is NOT knowable offline). Checks: stale snapshot (saved more than 120 s ago: the number is old), pnl on the card differs
from the recomputed net, missing price / entry / margin, same symbol + side open twice in a box.
Live facts come from reading live_recorder.py, and test_v2_pnl_open.py re-reads that file so the facts cannot silently go stale.
Run (Termux):  python3 backend/v2_pnl_open.py [--data DIR] [--out FILE] [--fee-roi 1.0]   -> Download/owl_open_pnl_check.json
Tests: python3 test/test_v2_pnl_open.py"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_inv_redact as R
import v2_inv_safe as S
import v2_inventory as I
import v2_pnl as P

VERSION = "v2_pnl_open 1 (Part 6)"
BOXES = ("paper_b1", "paper_b2", "live_local_copy")
STALE_S = 120
CHECKS = ("stale_snapshot", "pnl_differs_from_recomputed", "missing_price_entry_or_margin", "same_symbol_side_open_twice")
CODE_FACTS = [
    "Live P&L = Binance realizedPnl minus commission (live_recorder.py). Funding fees are NOT in it: they sit in Binance's income history.",
    "Commission is subtracted only when paid in USDT, USDC or BUSD. A fee paid in BNB is NOT subtracted (BNB fee discount makes live P&L look better than it is).",
    "If Binance trade history cannot be read after several tries, the trade is ESTIMATED from the last price and saved with estimated=True.",
    "A paper open position already shows the FULL round-trip fee as if paid, so floating P&L is net of a fee that is only charged at close.",
]
TO_VERIFY = ["Binance Futures > Transaction History (Trade, Commission, Funding Fee) for the same dates: compare its total with real_live net.",
             "Binance fee settings: is 'Pay fees with BNB' ON? If yes, live P&L here is overstated by those fees."]


def gross_roi(action, entry, ltp, lev):
    raw = (ltp - entry) / entry * 100.0 if action == "BUY" else (entry - ltp) / entry * 100.0
    return raw * lev


def new_box():
    return {"positions": 0, "margin_locked_usdt": 0.0, "floating_gross_usdt": 0.0, "fee_already_deducted_usdt": 0.0,
            "floating_net_usdt": 0.0, "winners": 0, "losers": 0, "oldest_open_hours": None, "stale_rows": 0,
            "checks": {c: {"count": 0, "examples": []} for c in CHECKS}, "_seen": set(), "_open_ts": []}


def flag(box, name, pos_id):
    c = box["checks"][name]
    c["count"] += 1
    if len(c["examples"]) < 5:
        c["examples"].append(str(pos_id))


def box_of(p):
    if str(p.get("source") or "").lower() == "live":
        return "live_local_copy"
    return "paper_b2" if str(p.get("bot") or "b1").lower() == "b2" else "paper_b1"


def add_position(box, pid, p, updated_at, fee_roi, now):
    key = (p.get("symbol"), p.get("action"))
    if key in box["_seen"]:
        flag(box, "same_symbol_side_open_twice", pid)
    box["_seen"].add(key)
    box["positions"] += 1
    ts = P.num(p, "opened_at_ts")
    if ts:
        box["_open_ts"].append(ts)
    entry, ltp, inv, lev = (P.num(p, k) for k in ("entry_price", "ltp", "invest_usdt", "leverage"))
    if not entry or entry <= 0 or ltp is None or not inv or inv <= 0 or not lev:
        flag(box, "missing_price_entry_or_margin", pid)
        return
    fee_r = P.num(p, "fee_roi_pct")
    fee_r = fee_roi if fee_r is None else fee_r
    g = gross_roi(p.get("action"), entry, ltp, lev)
    gross, fee = inv * g / 100.0, inv * fee_r / 100.0
    net = gross - fee
    box["margin_locked_usdt"] += inv
    box["floating_gross_usdt"] += gross
    box["fee_already_deducted_usdt"] += fee
    box["floating_net_usdt"] += net
    box["winners"] += net > 0
    box["losers"] += net < 0
    if updated_at is None or now - updated_at > STALE_S:
        box["stale_rows"] += 1
        flag(box, "stale_snapshot", pid)
    else:
        shown = P.num(p, "pnl_usdt")
        if shown is None or abs(shown - net) > max(0.05, 0.02 * abs(net)):
            flag(box, "pnl_differs_from_recomputed", pid)


def finish(box, now):
    ots = box.pop("_open_ts")
    box.pop("_seen")
    if ots:
        box["oldest_open_hours"] = round((now - min(ots)) / 3600.0, 2)
    for k in ("margin_locked_usdt", "floating_gross_usdt", "fee_already_deducted_usdt", "floating_net_usdt"):
        box[k] = round(box[k], 4)
    box["floating_is_current"] = box["positions"] > 0 and box["stale_rows"] == 0
    box["is_real_money"] = False                         # set True only for a live box when the exchange price is known (never offline)


def open_report(data_dir, fee_roi=1.0):
    root = os.path.realpath(data_dir)
    now = time.time()
    rep = {"boxes": {b: new_box() for b in BOXES}, "source": {}}
    path = os.path.join(root, "owl.db")
    try:
        with S.open_safe(path, [root]) as db:
            rep["source"]["owl.db"] = db.label()
            rows = db.con.execute("SELECT id, data, updated_at FROM positions").fetchall()
    except (S.UnsafePath, S.OpenFailed) as e:
        rep["source"]["owl.db"] = "not opened: " + str(e)
        rows = []
    except Exception:
        rep["source"]["owl.db"] = "no readable positions table"
        rows = []
    bad = 0
    for pid, data, upd in rows:
        try:
            p = json.loads(data)
            assert isinstance(p, dict)
        except (ValueError, AssertionError, TypeError):
            bad += 1
            continue
        add_position(rep["boxes"][box_of(p)], pid, p, upd, fee_roi, now)
    rep["source"]["unreadable_rows"] = bad
    for b in rep["boxes"].values():
        finish(b, now)
    return rep


def live_checks(data_dir):
    root = os.path.realpath(data_dir)
    rows, st = P.read_jsonl(os.path.join(root, "closed_trades_archive.jsonl"), [root])
    live = [t for t in rows if P.box_of(t, "b1") in ("real_live", "live_estimated")]
    out = {"live_closed_trades": len(live), "estimated_not_real": sum(bool(t.get("estimated")) for t in live),
           "rows_with_a_fee_field": sum(P.num(t, "fee_usdt") is not None for t in live), "archive": st}
    out["fee_cannot_be_checked_per_trade"] = bool(live) and out["rows_with_a_fee_field"] == 0
    try:
        real, _l = S.resolve_under(os.path.join(root, "live_open_context.json"), [root])
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            d = json.load(f)
        out["live_open_context_entries"] = len(d) if isinstance(d, (dict, list)) else 0
    except (S.UnsafePath, OSError, ValueError):
        out["live_open_context_entries"] = None
    return out


def build_report(data_dir, fee_roi=1.0):
    if not os.path.isdir(data_dir):
        return {"tool": VERSION, "read_only": True, "error": "data folder not found"}
    rep = open_report(data_dir, fee_roi)
    rep.update(tool=VERSION, read_only=True, made_utc=P.fmt_ts(time.time()), fee_roi_pct_used_when_a_row_has_none=fee_roi,
               live_closed_checks=live_checks(data_dir), code_facts=CODE_FACTS, to_verify_by_owner=TO_VERIFY,
               notes=["Boxes are never added together. Paper floating P&L is never real money.",
                      "A snapshot saved more than %d s ago is OLD: the app was off or the price feed was down." % STALE_S])
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl floating P&L + live fee facts (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--fee-roi", type=float, default=1.0)
    a = ap.parse_args(argv)
    out = a.out or os.path.join(os.path.dirname(I.default_out()), "owl_open_pnl_check.json")
    rep = build_report(I.find_data_dir(a.data), a.fee_roi)
    try:
        R.write_report(rep, out)
    except R.RedactionFailed as e:
        print("REFUSED: secret-looking fields, NO file written:", ", ".join(map(str, e.paths[:20])))
        return 2
    print("Open P&L check written:", out)
    for n, b in rep.get("boxes", {}).items():
        print("  %-16s open %-3d floating net %+.2f USDT  current=%s" % (n, b["positions"], b["floating_net_usdt"], b["floating_is_current"]))
    print("Nothing was changed. Send this JSON file to Claude.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
