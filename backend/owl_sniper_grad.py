"""owl_sniper_grad.py - SNIPER GRADUATION CHECKLIST (R24b). PAPER ONLY, READ ONLY: reads the trade archive + the saved files of the autopilot / exit learner, writes nothing, no network, no order code.
Question: may the owner THINK about letting the Sniper replace the Current Bot? The app never swaps by itself; this is only a checklist of the rules written in 04_PLAN.md.
7 checks, each PASS / FAIL / WAIT (WAIT = not enough data yet, never counted as pass):
  trades      Sniper has 100+ paper trades OR 14+ shared days with the Current Bot (owl_sniper_h2h, window 60 days)
  positive    Sniper net USDT > 0 and % per trade > 0 after fees (as the bot booked them)
  beats       the h2h verdict is SNIPER_AHEAD (more % per trade than the Current Bot on the same days)
  unseen      autopilot state LEARNED (v2_sniper_autopilot.json): picks beat 'take everything' on days it never saw
  books_more  exit learner state LEARNED_EXIT (v2_sniper_exitlearn.json): a learned profit line beats the fixed 2R on unseen days
  sideways    Sniper trades marked SIDEWAYS (field sniper_regime / regime): 10+ needed; average must be no worse than -SIDEWAYS_MAX_LOSS % per trade (a limit chosen in R24b, the owner may change it)
  drawdown    max drop of the cumulative daily % per trade (shared days): Sniper no deeper than Current Bot (30+ trades each)
Overall: READY_TO_DISCUSS only when all 7 PASS; NOT_YET when any FAIL; else COLLECTING. Not a profit promise. API: build(d, now=None). CLI: python3 backend/owl_sniper_grad.py [--data DIR]"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_pnl as P
import owl_sniper_h2h as H
import owl_sniper_autopilot as AP
import owl_sniper_exitlearn as XL

VERSION = "owl_sniper_grad 1 (R24b)"
PAPER_ONLY = True
WINDOW = 60
NEED_TRADES, NEED_DAYS, MIN_SIDE, MIN_SIDEWAYS = 100, 14, 30, 10
SIDEWAYS_MAX_LOSS = 0.10          # % per trade (points) the Sniper may lose in sideways time
NAMES = (("trades", "Enough paper trades"), ("positive", "Positive after fees"), ("beats", "More per trade than Current Bot"), ("unseen", "Holds on unseen days"),
         ("books_more", "Books more of each move"), ("sideways", "Small loss in sideways time"), ("drawdown", "Drawdown no worse"))


def _c(key, status, text):
    return {"key": key, "name": dict(NAMES)[key], "status": status, "text": text[:160]}


def _rows(d, now):
    """archive -> (per-day {day: {side: [n, pct_sum]}}, sniper sideways [n, pct_sum]). Never raises."""
    rows, _st = P.read_jsonl(os.path.join(os.path.realpath(d), P.FILES[0][0]), [os.path.realpath(d)])
    per, side_w = {}, [0, 0.0]
    for t in rows:
        if not isinstance(t, dict):
            continue
        ts, pnl, inv, side = P.num(t, "closed_at_ts"), P.num(t, "pnl_usdt"), P.num(t, "invest_usdt"), H._side_of(t)
        if ts is None or pnl is None or not inv or inv <= 0 or side is None or not 0 <= now - ts <= WINDOW * 86400:
            continue
        pct = pnl / inv * 100.0
        a = per.setdefault(H._day(ts), {"current": [0, 0.0], "sniper": [0, 0.0]})[side]
        a[0] += 1
        a[1] += pct
        if side == "sniper" and str(t.get("sniper_regime") or t.get("regime") or "").upper() == "SIDEWAYS":
            side_w[0] += 1
            side_w[1] += pct
    return per, side_w


def _dd(series):
    peak = cur = worst = 0.0
    for x in series:
        cur += x
        peak = max(peak, cur)
        worst = max(worst, peak - cur)
    return worst


def build(d, now=None):
    now = float(time.time() if now is None else now)
    out = {"version": VERSION, "paper_only": True, "overall": "COLLECTING", "passed": 0, "total": len(NAMES), "checks": [], "reasons": []}
    try:
        h = H.build(d, now=now, days=WINDOW)
        s, cur = h["sniper"], h["current"]
        ck = out["checks"]
        n, sd = s["trades"] or 0, h["shared_days"]
        ck.append(_c("trades", "PASS" if n >= NEED_TRADES or sd >= NEED_DAYS else "WAIT", "%d Sniper trades, %d shared days (need %d trades or %d days)." % (n, sd, NEED_TRADES, NEED_DAYS)))
        net, avg = s["net_usdt"], s["avg_pct"]
        ck.append(_c("positive", "WAIT" if n == 0 or avg is None else "PASS" if net > 0 and avg > 0 else "FAIL",
                     "No Sniper trades on shared days yet." if n == 0 or avg is None else "Net %+.2f USDT, %+.3f%% per trade." % (net, avg)))
        v = h["verdict"]
        ck.append(_c("beats", "PASS" if v == "SNIPER_AHEAD" else "WAIT" if v == "NOT_ENOUGH_DATA" else "FAIL", "Same-days verdict: %s." % v.replace("_", " ").lower()))
        ap = AP.load(d) or {}
        st = ap.get("state")
        ck.append(_c("unseen", "PASS" if st == "LEARNED" else "FAIL" if st == "EXPLORE" and ap.get("compare") and ap.get("n_test", 0) >= AP.MIN_TEST else "WAIT",
                     (str((ap.get("reasons") or ["Autopilot has not judged yet."])[0]))))
        xl = XL.load(d) or {}
        xs, xc = xl.get("state"), xl.get("compare") or {}
        ck.append(_c("books_more", "PASS" if xs == "LEARNED_EXIT" else "FAIL" if xs == "EXPLORE_EXIT" and (xc.get("test_trades") or 0) >= XL.MIN_TEST else "WAIT",
                     (str((xl.get("reasons") or ["Exit learner has not judged yet."])[0]))))
        per, sw = _rows(d, now)
        if sw[0] < MIN_SIDEWAYS:
            ck.append(_c("sideways", "WAIT", "%d Sniper trades in sideways time (need %d, and the archive must carry the market state)." % (sw[0], MIN_SIDEWAYS)))
        else:
            a = sw[1] / sw[0]
            ck.append(_c("sideways", "PASS" if a >= -SIDEWAYS_MAX_LOSS else "FAIL", "%+.3f%% per trade over %d sideways trades (limit -%.2f)." % (a, sw[0], SIDEWAYS_MAX_LOSS)))
        days = [x for x in sorted(per) if per[x]["current"][0] and per[x]["sniper"][0]]
        tc, ts_ = sum(per[x]["current"][0] for x in days), sum(per[x]["sniper"][0] for x in days)
        if tc < MIN_SIDE or ts_ < MIN_SIDE:
            ck.append(_c("drawdown", "WAIT", "Current %d, Sniper %d trades on shared days (need %d each)." % (tc, ts_, MIN_SIDE)))
        else:
            dc = _dd([per[x]["current"][1] / per[x]["current"][0] for x in days])
            ds = _dd([per[x]["sniper"][1] / per[x]["sniper"][0] for x in days])
            ck.append(_c("drawdown", "PASS" if ds <= dc else "FAIL", "Deepest drop: Sniper %.2f vs Current Bot %.2f points (daily %% per trade, added up)." % (ds, dc)))
        out["passed"] = sum(1 for c in ck if c["status"] == "PASS")
        out["overall"] = "READY_TO_DISCUSS" if out["passed"] == len(ck) else "NOT_YET" if any(c["status"] == "FAIL" for c in ck) else "COLLECTING"
        out["reasons"] = h["reasons"][:2]
    except Exception as e:                                       # a damaged file must never stop the backend
        out["overall"], out["reasons"] = "ERROR", ["%s: %s" % (type(e).__name__, str(e)[:100])]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    r = build(ap.parse_args(argv).data)
    print("%s  overall=%s  passed=%d/%d" % (VERSION, r["overall"], r["passed"], r["total"]))
    for c in r["checks"]:
        print(" %-5s %-32s %s" % (c["status"], c["name"], c["text"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
