"""owl_sniper_record.py - OwlSniper R29a: the TRADE RECORD. PAPER ONLY. Writes ONE own file (v2_sniper_trades.json); reads the closed-trade archive and the two order books. No order code.
Owner wish (rule 30): for EVERY Sniper trade show the signal, the basis (why), entry, TP, SL, expected profit, expected hold time, the result and what it learned.
note_open() is called by owl_sniper_paper.py the moment a paper trade opens: it keeps the card's reason + basis (the paper trader itself forgets them) and works out the numbers BEFORE the trade:
  expected profit = margin x leverage x (target % - round-trip cost %); risk = margin x leverage x (stop % + cost %); hold = the time limit (MAX_HOLD candles) - the typical hold of the closed trades is added by build().
build() = open trades first (still in the LEARN or REAL order book), then closed ones (archive row joined by sniper_id, else coin + open time within 15 s), newest first. Result, exit reason, expected vs real USDT, the mistake tag + lesson (owl_sniper_mistakes).
A closed trade with no record (opened before this part existed) is still listed with what the archive knows and the note "no record from the open".
API: note_open(d, card, order, now), build(d, now, limit). CLI: python3 backend/owl_sniper_record.py [--data DIR]"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_barriers as BR
import owl_sniper_engine_c1 as C
import owl_sniper_exec as EX
import owl_sniper_feed as F
import owl_sniper_learn as LN
import owl_sniper_lessons as LS
import owl_sniper_mistakes as MS
import owl_sniper_tf as TF
import owl_sniper_tptime as TT

VERSION = "owl_sniper_record 3 (Plan F)"
FILE, KEEP, JOIN_SEC = "v2_sniper_trades.json", 300, 15


def _num(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def note_open(d, card, order, now=None):
    """A paper trade just opened -> keep its record. Never raises, never blocks a trade."""
    now = time.time() if now is None else now
    try:
        o, c = order or {}, card or {}
        e, tp, sl = _num(o.get("entry")), _num(o.get("take_profit")), _num(o.get("stop"))
        inv, lev, cost = _num(o.get("invest_usdt")) or 0.0, _num(o.get("leverage")) or 1.0, C.cost_pct()
        tp_pct, sl_pct = abs(tp - e) / e * 100.0, abs(e - sl) / e * 100.0
        lane = "EXPLORE" if o.get("xp") else ("LEARN" if o.get("tag") == LN.TAG else "REAL")
        rec = {"id": o["id"], "symbol": o["symbol"], "side": o["side"], "lane": lane, "opened_at": int(now), "signal": c.get("action") or "", "reason": c.get("reason") or "",
               "basis": list(c.get("basis") or c.get("why") or [])[:6], "regime": o.get("regime"), "confidence": o.get("confidence"), "entry": e, "stop_loss": sl, "take_profit": tp,
               "stop_pct": round(sl_pct, 3), "target_pct": round(tp_pct, 3), "rr": round(tp_pct / sl_pct, 2) if sl_pct else None, "invest_usdt": inv, "leverage": lev,
               "expected_usdt": round(inv * lev * (tp_pct - cost) / 100.0, 2), "risk_usdt": round(inv * lev * (sl_pct + cost) / 100.0, 2), "max_hold_sec": BR.HOLD * TF.step("5m"), "exit_rule": o.get("exit_rule")}
        recs = (F.read_json(d, FILE) or {}).get("records") or {}
        recs[rec["id"]] = rec
        for k in sorted(recs, key=lambda x: recs[x].get("opened_at", 0))[:max(0, len(recs) - KEEP)]:
            recs.pop(k, None)
        return F.write_json(d, FILE, {"version": VERSION, "records": recs})
    except Exception:
        return False


def _trade_ids(d):
    """R29b: Sniper client id -> paper trade id (from the paper bridge map), so the app can join the live price + P&L of a position to its record. {} on any problem."""
    try:
        ids = (F.read_json(d, "v2_sniper_paper.json") or {}).get("ids") or {}
        return {k: v.get("trade_id") for k, v in ids.items() if isinstance(v, dict) and v.get("trade_id") is not None}
    except Exception:
        return {}


def _open_ids(d):
    ids = set()
    for mod in (LN, EX):
        try:
            ids |= set(mod._load(d)["open"])
        except Exception:
            pass
    return ids


def _match(row, recs):
    sid = row.get("sniper_id")
    if sid and sid in recs:
        return recs[sid]
    t0 = _num(row.get("opened_at_ts")) or 0
    for r in recs.values():
        if r["symbol"] == row.get("symbol") and abs(r["opened_at"] - t0) <= JOIN_SEC:
            return r
    return None


def build(d, now=None, limit=30):
    now = time.time() if now is None else now
    out = {"version": VERSION, "paper_only": True, "made": int(now), "open": [], "closed": [], "typical_hold_sec": None}
    try:
        recs = (F.read_json(d, FILE) or {}).get("records") or {}
        rows, _bad = LS.read_own(d)
        rows = rows[-400:]
        used, closed, holds = set(), [], []
        for t in reversed(rows):
            r = _match(t, recs)
            if r:
                used.add(r["id"])
            tag, info = LS.tag_trade(t)
            t0, t1 = _num(t.get("opened_at_ts")) or 0, _num(t.get("closed_at_ts")) or 0
            held = int(t1 - t0) if t0 and t1 > t0 else None
            if held:
                holds.append(held)
            side = "LONG" if str(t.get("action") or "").upper() == "BUY" else "SHORT"
            base = r or {"symbol": t.get("symbol"), "side": side, "lane": "LEARN", "entry": _num(t.get("entry_price")), "stop_loss": _num(t.get("signal_stop_loss")),
                         "regime": t.get("sniper_regime"), "basis": [], "note": "No record from the open (this trade is older than the trade record)."}
            pnl = _num(t.get("pnl_usdt"))
            closed.append(dict(base, closed_at=int(t1), held_sec=held, pnl_usdt=pnl, roi_pct=_num(t.get("roi_pct")), exit_reason=t.get("clean_exit_reason") or t.get("exit_reason") or "", tag=tag,
                               lesson=MS.LESSON[tag] % info.get("mfe_r", 0.0) if tag == "EXIT_ERROR" else MS.LESSON[tag], vs_expected=None if pnl is None or "expected_usdt" not in base else round(pnl - base["expected_usdt"], 2)))
        typ = sorted(holds)[len(holds) // 2] if len(holds) >= 5 else None
        tl = TT.build(rows)
        out["time_learn"] = tl
        live, tids = _open_ids(d), _trade_ids(d)
        opn = [dict(r, state="OPEN", age_sec=int(now - r["opened_at"]), typical_hold_sec=typ, trade_id=tids.get(r["id"]), learn_time=TT.expect(tl, r.get("regime"), r.get("side"))) for r in recs.values() if r["id"] in live and r["id"] not in used]
        opn.sort(key=lambda r: -r["opened_at"])
        out.update(open=opn[:limit], closed=closed[:limit], typical_hold_sec=typ, counts={"open": len(opn), "closed": len(closed), "with_record": sum(1 for c in closed if "expected_usdt" in c)})
    except Exception as e:
        out["state"], out["text"] = "error", "%s: %s" % (type(e).__name__, str(e)[:80])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper trade record (paper only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    a = ap.parse_args(argv)
    r = build(a.data)
    print(json.dumps(dict(r, open=r["open"][:2], closed=r["closed"][:2]), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
