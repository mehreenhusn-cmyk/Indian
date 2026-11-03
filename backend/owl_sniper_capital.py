"""owl_sniper_capital.py - OwlSniper SMALL-CAPITAL SIZING (Part 30 / FILE 25). PAPER ONLY, PURE: it only does the sums. It opens nothing, closes nothing, writes nothing, no network, no order code. LIVE_ALLOWED is False.
The question: "I have 10-20 USDT. How big may ONE trade be, and may I open it at all right now?" Small capital changes only the SIZE. The risk rules stay the same, the 85% real floor is not touched here, and risk is never raised to make more activity.
How it works (plain words):
  1. 1R = the money lost when the stop is hit = capital x RISK_PCT (start 1%). Notional (position value) = 1R / stop distance. Margin = notional / leverage. Leverage is CAPPED at 10x (the owner's small-account setting) and is never raised to fit a trade.
  2. Gates, in this order. The first one that fails is named in plain words (a no-trade day is a valid result):
       day     = DAILY LOSS LIMIT: realized result of today <= -(start-of-day capital x 3%) -> no new trade today.
       open    = MAX OPEN trades (start 3) and total open risk <= 3% of capital.
       cost    = the round trip cost (fee + slippage, owl_sniper_engine_c1.cost_pct()) in R = cost % / stop %. Above MAX_COST_R (0.5 R) the stop is too tight for the cost: refused. Costs are shown on every answer. If the cost cannot be read, nothing is sized (never a guessed cost).
       stop    = stop distance inside the Sniper's own MIN / MAX_SL_PCT (0.15% - 2%).
       liq     = the stop must sit inside HALF of the way to liquidation (isolated margin, about 100 / leverage - 0.5 %).
       margin  = margin of all open trades + the new one <= 50% of capital. If the new trade does not fit, it is made SMALLER (never more leverage).
       minimum = the exchange minimum order (start 5 USDT notional; use the real filter when the caller has it). If the size by the risk rule is below it, the trade is REFUSED: the smallest order would risk more than the rule allows. The answer says how much capital that stop would need.
  3. The notional is rounded DOWN to 0.01 USDT, so the real risk is never above the rule.
  Limits are starting values, not measured. The owner may tune them inside LIMITS (anything outside is clamped). Compounding, good day / bad day throttle = FILE 28; this file never promises growth.
Not here on purpose: the win chance, expected R and time (Risk Box, FILE 21), edge decayed (FILE 20), SCALP / SWING (FILE 26), correlation of open trades (FILE 52). The caller applies those first.
API: cfg(over=None), day_status(day_start, pnls, c=None), size_trade(capital, stop_pct, c=None, lev=None, open_trades=(), day_start=None, day_pnls=(), min_notional=None), ladder(capital, c=None, stops=(0.3, 0.5, 1.0, 2.0)). open_trades = [{risk_usdt, margin_usdt}]. CLI:
  python3 backend/owl_sniper_capital.py --capital 10 --stop 0.5 [--lev 10] [--open-risk 0.1 --open-margin 2 ...] [--day-start 10 --day-pnl -0.2] | --ladder"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "owl_sniper_capital 1 (Part 30)"
LIVE_ALLOWED = False                      # constant: sizing for paper only
MM_PCT = 0.5                              # rough maintenance margin, % of notional (for the liquidation check)
DEFAULTS = {"risk_pct": 1.0, "max_open": 3, "daily_loss_pct": 3.0, "open_risk_pct": 3.0, "margin_pct": 50.0, "lev": 10.0, "min_notional": 5.0, "max_cost_r": 0.5}
LIMITS = {"risk_pct": (0.25, 2.0), "max_open": (1, 5), "daily_loss_pct": (1.0, 5.0), "open_risk_pct": (1.0, 6.0), "margin_pct": (10.0, 80.0), "lev": (1.0, 10.0), "min_notional": (5.0, 50.0), "max_cost_r": (0.2, 0.8)}


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def cfg(over=None):
    """Defaults + the owner's values, every one clamped into LIMITS (a bad value falls back to the default)."""
    out = {}
    for k, dv in DEFAULTS.items():
        v = _num((over or {}).get(k))
        lo, hi = LIMITS[k]
        out[k] = dv if v is None else min(max(v, lo), hi)
    out["max_open"] = int(out["max_open"])
    return out


def _cost():
    """-> (round trip cost %, MIN_SL_PCT, MAX_SL_PCT) from the Sniper's own engine file, or None when it cannot be read."""
    try:
        import owl_sniper_engine_c1 as C
        return float(C.cost_pct()), float(C.MIN_SL_PCT), float(C.MAX_SL_PCT)
    except Exception:
        return None


def day_status(day_start, pnls, c=None):
    """Today's loss limit. pnls = realized USDT results of today's closed trades. A profit does not widen the limit."""
    c = c or cfg()
    s = _num(day_start)
    if s is None or s <= 0:
        return {"state": "UNKNOWN", "text": "Start-of-day capital is not known: the daily loss limit cannot be checked."}
    net = sum(x for x in (_num(p) for p in pnls or ()) if x is not None)
    limit = s * c["daily_loss_pct"] / 100.0
    left = limit + min(net, 0.0)
    st = "STOP" if net <= -limit else "OK"
    txt = ("Daily loss limit reached (%+.2f of -%.2f USDT): no new trade today." % (net, limit)) if st == "STOP" else \
        ("Today %+.2f USDT. %.2f of the %.2f USDT daily loss limit is left." % (net, left, limit))
    return {"state": st, "net": round(net, 4), "limit": round(limit, 4), "left": round(max(left, 0.0), 4), "text": txt}


def _out(state, gate, text, **kw):
    d = {"version": VERSION, "state": state, "gate": gate, "text": text, "paper_only": True, "live_allowed": LIVE_ALLOWED}
    d.update(kw)
    d["lines"] = [text] + kw.get("extra_lines", [])
    return d


def size_trade(capital, stop_pct, c=None, lev=None, open_trades=(), day_start=None, day_pnls=(), min_notional=None):
    """ONE trade -> OK with the size, or BLOCKED with the first gate that failed in plain words. Never raises, never opens anything."""
    c = c or cfg()
    cap, stop = _num(capital), _num(stop_pct)
    if cap is None or cap <= 0 or stop is None or stop <= 0:
        return _out("BLOCKED", "input", "Capital and stop distance must be real numbers above 0. Nothing is sized.")
    if day_start is not None:
        ds = day_status(day_start, day_pnls, c)
        if ds["state"] == "STOP":
            return _out("BLOCKED", "day", ds["text"], day=ds)
    opens = [o for o in (open_trades or ()) if isinstance(o, dict)]
    if len(opens) >= c["max_open"]:
        return _out("BLOCKED", "open", "%d trades are open already (limit %d). No new trade." % (len(opens), c["max_open"]))
    cost = _cost()
    if cost is None:
        return _out("BLOCKED", "cost", "The round trip cost cannot be read, so nothing is sized (no guessed cost).")
    cost_pct, sl_min, sl_max = cost
    if not sl_min <= stop <= sl_max:
        return _out("BLOCKED", "stop", "The stop is %.2f%% away; only %.2f%% to %.2f%% is allowed." % (stop, sl_min, sl_max))
    lv = min(_num(lev) or c["lev"], c["lev"])
    lv = max(lv, 1.0)
    liq = 100.0 / lv - MM_PCT
    if stop * 2.0 > liq:
        return _out("BLOCKED", "liq", "A %.2f%% stop is too close to liquidation (about %.1f%% away at %gx). Use a smaller leverage." % (stop, liq, lv))
    cost_r = cost_pct / stop
    if cost_r > c["max_cost_r"]:
        return _out("BLOCKED", "cost", "Costs eat %.2f R per trade (%.2f%% cost on a %.2f%% stop); the limit is %.2f R. The stop is too tight for the cost." % (cost_r, cost_pct, stop, c["max_cost_r"]), cost_r=round(cost_r, 3))
    free = cap * c["margin_pct"] / 100.0 - sum(_num(o.get("margin_usdt")) or 0.0 for o in opens)
    if free <= 0:
        return _out("BLOCKED", "margin", "Open trades already use the margin limit (%.0f%% of capital)." % c["margin_pct"])
    risk = cap * c["risk_pct"] / 100.0
    notional, reduced = risk / (stop / 100.0), False
    if notional / lv > free:
        notional, reduced = free * lv, True
    notional = math.floor(notional * 100.0) / 100.0
    mn = max(_num(min_notional) or c["min_notional"], 0.0)
    if notional < mn:
        need = mn * stop / c["risk_pct"]
        why = "after the margin limit" if reduced else "by the risk rule (%.2f%% of capital)" % c["risk_pct"]
        return _out("BLOCKED", "minimum", "The size %s is %.2f USDT, below the exchange minimum order (%.2f USDT). The smallest order would risk more than the rule allows. For a %.2f%% stop that needs about %.0f USDT of capital." % (why, notional, mn, stop, need), notional=notional, min_notional=mn, capital_needed=round(need, 2))
    real_risk = notional * stop / 100.0
    if sum(_num(o.get("risk_usdt")) or 0.0 for o in opens) + real_risk > cap * c["open_risk_pct"] / 100.0 + 1e-9:
        return _out("BLOCKED", "open", "Total open risk would pass %.1f%% of capital. No new trade." % c["open_risk_pct"])
    fee = notional * cost_pct / 100.0
    lines = ["Costs: %.2f%% round trip = %.4f USDT = %.2f R on this stop." % (cost_pct, fee, cost_r),
             "If the stop is hit: about -%.4f USDT (1R + cost). If the 2R target is hit: about +%.4f USDT." % (real_risk + fee, 2.0 * real_risk - fee)]
    if reduced:
        lines.append("The size was made smaller to fit the margin limit; leverage was not raised.")
    text = "Size %.2f USDT at %gx: margin %.2f USDT, 1R = %.4f USDT (%.2f%% of capital), stop %.2f%% away." % (notional, lv, notional / lv, real_risk, 100.0 * real_risk / cap, stop)
    return _out("OK", None, text, notional=notional, lev=lv, margin_usdt=round(notional / lv, 4), risk_usdt=round(real_risk, 4), risk_pct=round(100.0 * real_risk / cap, 3), stop_pct=stop,
                cost_pct=round(cost_pct, 4), cost_r=round(cost_r, 3), cost_usdt=round(fee, 4), reduced=reduced, extra_lines=lines)


def ladder(capital, c=None, stops=(0.3, 0.5, 1.0, 2.0)):
    """What ONE trade looks like at this capital for a few stop distances (no open trades). Shows honestly where cost or the minimum order blocks."""
    rows = []
    for s in stops:
        r = size_trade(capital, s, c)
        rows.append({"stop_pct": s, "state": r["state"], "gate": r["gate"], "notional": r.get("notional"), "margin_usdt": r.get("margin_usdt"), "risk_usdt": r.get("risk_usdt"), "cost_r": r.get("cost_r"), "text": r["text"]})
    return {"version": VERSION, "capital": capital, "rows": rows, "paper_only": True, "lines": ["Stop %.2f%%: %s" % (x["stop_pct"], x["text"]) for x in rows]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper small-capital sizing (paper only, pure sums)")
    ap.add_argument("--capital", type=float, default=10.0)
    ap.add_argument("--stop", type=float, default=0.5, help="stop distance in %% of price")
    ap.add_argument("--lev", type=float, default=None)
    ap.add_argument("--open-risk", type=float, action="append", default=[], help="1R in USDT of an open trade (repeat per trade)")
    ap.add_argument("--open-margin", type=float, action="append", default=[], help="margin in USDT of an open trade (same order)")
    ap.add_argument("--day-start", type=float, default=None)
    ap.add_argument("--day-pnl", type=float, default=0.0)
    ap.add_argument("--ladder", action="store_true")
    a = ap.parse_args(argv)
    if a.ladder:
        print(json.dumps(ladder(a.capital), indent=1))
        return 0
    opens = [{"risk_usdt": r, "margin_usdt": (a.open_margin[i] if i < len(a.open_margin) else 0.0)} for i, r in enumerate(a.open_risk)]
    print(json.dumps(size_trade(a.capital, a.stop, None, a.lev, opens, a.day_start, [a.day_pnl]), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
