"""owl_sniper_h2h.py - CURRENT BOT vs OWLSNIPER, SAME DAYS (R24a). PAPER ONLY, READ ONLY: reads closed_trades_archive.jsonl, writes nothing, no network.
Current Bot = the main paper bot (box paper_b1, source not sniper). Sniper = its own paper trades (source sniper / sniper_learn). Sizes differ (Sniper trades tiny), so the fair number is
AVG % = net USDT / money put in (invest_usdt) over the trades of that side, not USDT. Net USDT is shown too, but never used for the verdict.
Only UTC days where BOTH sides closed at least one trade are compared ("same days"). Numbers are what the archive recorded (fees as the bot booked them).
Verdict (backend only): NOT_ENOUGH_DATA while either side has fewer than MIN_TRADES (30) trades on the shared days or there are fewer than MIN_DAYS (3) shared days;
SNIPER_AHEAD / CURRENT_AHEAD when the AVG % gap is at least GAP (0.05 points) AND that side wins more than half of the shared days; else TOO_CLOSE.
A hint, never a proof: different coins and different moments. API: build(d, now=None, days=14). CLI: python3 backend/owl_sniper_h2h.py [--data DIR]"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_pnl as P

VERSION = "owl_sniper_h2h 1 (R24a)"
PAPER_ONLY = True
OWN = ("sniper", "sniper_learn")
MIN_TRADES, MIN_DAYS, GAP, DEFAULT_DAYS = 30, 3, 0.05, 14


def _side_of(t):
    """One archive row -> 'sniper' / 'current' / None (live, box 2 and others are skipped, never mixed)."""
    src = str(t.get("source") or "").lower()
    if src in OWN:
        return "sniper"
    if P.box_of(t, "b1") == "paper_b1" and not src.startswith("sniper"):
        return "current"
    return None


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _blank():
    return {"n": 0, "net": 0.0, "inv": 0.0, "wins": 0}


def _fin(a):
    avg = a["net"] / a["inv"] * 100.0 if a["inv"] > 0 else None
    return {"trades": a["n"], "net_usdt": round(a["net"], 4), "wins": a["wins"], "win_pct": round(100.0 * a["wins"] / a["n"], 1) if a["n"] else None,
            "avg_pct": None if avg is None else round(avg, 3)}


def build(d, now=None, days=DEFAULT_DAYS):
    """-> answer dict. Never raises."""
    now = float(time.time() if now is None else now)
    out = {"version": VERSION, "paper_only": True, "state": "NOT_ENOUGH_DATA", "verdict": "NOT_ENOUGH_DATA", "days_window": days, "shared_days": 0,
           "current": _fin(_blank()), "sniper": _fin(_blank()), "per_day": [], "sniper_day_wins": 0, "reasons": []}
    try:
        root = os.path.realpath(d)
        rows, st = P.read_jsonl(os.path.join(root, P.FILES[0][0]), [root])
        per = {}
        for t in rows:
            if not isinstance(t, dict):
                continue
            ts, pnl = P.num(t, "closed_at_ts"), P.num(t, "pnl_usdt")
            side = _side_of(t)
            if ts is None or pnl is None or side is None or not 0 <= now - ts <= days * 86400:
                continue
            a = per.setdefault(_day(ts), {"current": _blank(), "sniper": _blank()})[side]
            a["n"] += 1
            a["net"] += pnl
            a["inv"] += P.num(t, "invest_usdt") or 0.0
            a["wins"] += 1 if pnl > 0 else 0
        tot = {"current": _blank(), "sniper": _blank()}
        cur_w = sn_w = 0
        for day in sorted(per):
            c, s = per[day]["current"], per[day]["sniper"]
            if c["n"] == 0 or s["n"] == 0:
                continue
            for side, a in (("current", c), ("sniper", s)):
                for k in ("n", "net", "inv", "wins"):
                    tot[side][k] += a[k]
            fc, fs = _fin(c), _fin(s)
            out["per_day"].append({"day": day, "current": fc, "sniper": fs})
            if fc["avg_pct"] is not None and fs["avg_pct"] is not None:
                cur_w += 1 if fc["avg_pct"] > fs["avg_pct"] else 0
                sn_w += 1 if fs["avg_pct"] > fc["avg_pct"] else 0
        out["current"], out["sniper"] = _fin(tot["current"]), _fin(tot["sniper"])
        out["shared_days"], out["sniper_day_wins"], out["current_day_wins"] = len(out["per_day"]), sn_w, cur_w
        out["per_day"] = out["per_day"][-7:]
        if st and str(st.get("status") or "") not in ("", "ok", "OK"):
            out["reasons"].append("Trade archive: %s" % str(st.get("status"))[:80])
        need = []
        if out["shared_days"] < MIN_DAYS:
            need.append("%d shared days (need %d)" % (out["shared_days"], MIN_DAYS))
        for name in ("current", "sniper"):
            if out[name]["trades"] < MIN_TRADES:
                need.append("%s %d trades (need %d)" % (name, out[name]["trades"], MIN_TRADES))
        if need:
            out["reasons"].append("Not enough shared data yet: " + ", ".join(need) + ".")
            return out
        ca, sa = out["current"]["avg_pct"], out["sniper"]["avg_pct"]
        if ca is None or sa is None:
            out["reasons"].append("Money put in is missing in the archive, so the % per trade cannot be made.")
            return out
        out["state"] = "OK"
        gap = sa - ca
        half = out["shared_days"] / 2.0
        out["verdict"] = "SNIPER_AHEAD" if gap >= GAP and sn_w > half else "CURRENT_AHEAD" if -gap >= GAP and cur_w > half else "TOO_CLOSE"
        out["gap_pct"] = round(gap, 3)
    except Exception as e:                                       # a damaged file must never stop the backend
        out["state"], out["reasons"] = "ERROR", ["%s: %s" % (type(e).__name__, str(e)[:100])]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    a = ap.parse_args(argv)
    r = build(a.data, days=a.days)
    print("%s  verdict=%s  shared_days=%s" % (VERSION, r["verdict"], r["shared_days"]))
    for k in ("current", "sniper"):
        print(" %-8s %s" % (k, r[k]))
    for t in r["reasons"]:
        print(" -", t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
