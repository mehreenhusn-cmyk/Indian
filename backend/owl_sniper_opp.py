"""owl_sniper_opp.py - OwlSniper OPPORTUNITY COST: small profit in hand, trade is slow - STAY or ROTATE? (Part 32 / FILE 27). REPORT ONLY: read only, pure sums, nothing is closed, opened or written, no network, no order code.
The question (owner): "This trade shows only a small profit and is slow. Is a better setup waiting somewhere else? Stay, take the profit, or rotate?" The answer is ONE plain line with the reason.
Inputs the CALLER gives (this file measures nothing by itself):
  trade = {id, symbol?, tf?, side?, age_secs, r_net_now (the profit in hand in R AFTER the exit cost, minus = loss), risk_usdt? (1R in USDT, for the USDT line), box (the Risk Box of this setup, state OK: exp_r, median_secs, p75_secs)}
  alts  = the PROVEN setups available right now, from owl_sniper_scalp.rank(...)["ranked"] (each has id, label, r_per_hour). Unproven setups are never offered here.
  can_open = True when a slot and margin are free after this trade is closed (owl_sniper_capital.size_trade answered OK for the alternative).
Rules, the first one that fits wins (every number is a measured one; the limits are starting values the owner may tune):
  KEEP        = no measured time for this setup (box not OK), or the profit in hand is below MIN_PROFIT_R (0.15 R) or a loss. Closing a loser or a tiny profit to rotate only pays costs twice: the stop and the target decide.
  STAY        = the trade is still inside the normal time (age <= median of similar trades).
  TAKE_PROFIT = the trade is slow (age > median) and similar trades end at about the same or less than what is already in hand (expected R at the close - profit now <= 0). Waiting is not expected to add anything.
  ROTATE      = slow, more could still come, BUT a proven alternative exists, a slot is free, and its expected R per hour is at least ROTATE_FACTOR (2.0) x the rate left in this trade. The rate left = (expected R at the close - profit now) / hours until the 75th-percentile time; past that time (slower than 3 of 4 similar trades) the rate left is counted as 0.
  STAY        = otherwise, with the reason (no better proven setup, no free slot, or the gain is not big enough).
This is ROUGH on purpose: the saved labels keep no path of an open trade, so "what comes next" is the average of the setup, not a forecast of this trade. The line says "about" and "rough". Nothing here replaces the stop, the target or the kill criteria (FILE 20).
Each alternative is used for ONE trade only (slowest trade first). arrival_rate() answers "how often does a new setup of this kind show up?" from the bridge entries (days with data only), as info for the line, never as a promise.
API: decide(trade, alts=(), can_open=True, c=None), report(trades, alts=(), can_open=True, c=None), arrival_rate(examples, days=7, now=None), build(d, limit=0, since_days=None). CLI:
  python3 backend/owl_sniper_opp.py --data DIR [--limit 2000]    -> arrival rate per interval x side (JSON)
  python3 backend/owl_sniper_opp.py --file FILE.json            -> FILE = {"trades": [...], "alts": [...], "can_open": true}"""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "owl_sniper_opp 1 (Part 32)"
LIVE_ALLOWED = False
MIN_PROFIT_R = 0.15           # below this the profit in hand is too small (or a loss): no rotation
ROTATE_FACTOR = 2.0           # the alternative must earn at least this many times more R per hour
MIN_LEFT_SECS = 300.0         # the time left to the 75th percentile never counts below 5 min
MIN_ARRIVALS = 30             # entries before an arrival rate is shown
DEFAULTS = {"min_profit_r": MIN_PROFIT_R, "rotate_factor": ROTATE_FACTOR}


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _dur(sec):
    """Owner rule: more than 60 minutes = hours + minutes, never '220 min'."""
    if sec is None:
        return "-"
    if sec < 90:
        return "%d s" % round(sec)
    m = round(sec / 60.0)
    return "%d min" % m if m <= 60 else ("%d h" % (m // 60) if m % 60 == 0 else "%d h %d min" % (m // 60, m % 60))


def _out(d, code, text, **kw):
    r = {"id": d.get("id"), "decision": code, "text": text, "lines": [text], "paper_only": True, "live_allowed": LIVE_ALLOWED, "report_only": True}
    r.update(kw)
    return r


def decide(trade, alts=(), can_open=True, c=None):
    """ONE open trade -> {decision KEEP / STAY / TAKE_PROFIT / ROTATE, text (one plain line), numbers}. Never raises; bad input = KEEP."""
    c = dict(DEFAULTS, **(c or {}))
    t = trade if isinstance(trade, dict) else {}
    box, age, r = t.get("box"), _num(t.get("age_secs")), _num(t.get("r_net_now"))
    med, p75, er = (_num((box or {}).get(k)) for k in ("median_secs", "p75_secs", "exp_r"))
    if not isinstance(box, dict) or box.get("state") != "OK" or None in (age, r, med, p75, er) or med <= 0:
        return _out(t, "KEEP", "Nothing to do. There is not enough past data for this kind of trade to give advice. The stop or the target will close it.")
    usd = _num(t.get("risk_usdt"))
    prof = "%+.2f R%s" % (r, (" = %+.2f USDT" % (r * usd)) if usd else "")
    nowtxt = ("%s %.2f USDT" % ("up" if r * usd >= 0 else "down", abs(r * usd))) if usd else ("%s %.2f of the amount at risk" % ("up" if r >= 0 else "down", abs(r)))
    base = {"profit_r": round(r, 3), "profit_usdt": round(r * usd, 4) if usd else None, "age_secs": age, "median_secs": med, "p75_secs": p75, "exp_r": er}
    if r < c["min_profit_r"]:
        return _out(t, "KEEP", "Nothing to do. Right now it is %s. %s The stop or the target will close it." % (nowtxt, "Closing a losing trade early only adds fees." if r <= 0 else "The gain is too small to be worth closing early."), **base)
    if age <= med:
        return _out(t, "STAY", "Wait. Right now it is %s after %s. That is still a normal time: half of similar trades close within %s." % (nowtxt, _dur(age), _dur(med)), **base)
    slow = "slower than half of similar trades" if age <= p75 else "slower than 3 of 4 similar trades"
    gain = er - r
    if gain <= 0:
        return _out(t, "TAKE_PROFIT", "Good time to take the profit. Right now it is %s after %s, %s. Similar trades finish with about the same gain, so waiting is not expected to add more." % (nowtxt, _dur(age), slow), stay_gain_r=round(gain, 3), **base)
    left = max(p75 - age, MIN_LEFT_SECS) if age < p75 else None
    stay_rate = (gain / (left / 3600.0)) if left else 0.0
    best = next((a for a in sorted((a for a in alts or () if isinstance(a, dict) and _num(a.get("r_per_hour")) and a["r_per_hour"] > 0), key=lambda a: -a["r_per_hour"]) if a.get("id") != t.get("id")), None)
    head = "Right now it is %s after %s, %s. It may still gain a little more (a rough guess)." % (nowtxt, _dur(age), slow)
    extra = dict(base, stay_gain_r=round(gain, 3), stay_rate_r_per_hour=round(stay_rate, 3))
    if best is None:
        return _out(t, "STAY", "Wait. " + head + " No better trade is available right now.", **extra)
    if not can_open:
        return _out(t, "STAY", "Wait. " + head + " A better trade exists (%s) but there is no free slot." % best.get("id"), alt=best, **extra)
    if best["r_per_hour"] >= c["rotate_factor"] * stay_rate and best["r_per_hour"] > 0:
        txt = "Consider switching. %s Another trade (%s) looks clearly better right now." % (head, best.get("id"))
        return _out(t, "ROTATE", txt, alt=best, **extra)
    return _out(t, "STAY", "Wait. " + head + " The other trade (%s) is not clearly better, so no switch." % best.get("id"), alt=best, **extra)


def report(trades, alts=(), can_open=True, c=None):
    """Several open trades. Each alternative is offered to ONE trade only (the slowest first). Never writes."""
    first = {id(t): decide(t, alts, can_open, c) for t in trades or ()}
    order = sorted((t for t in trades or () if isinstance(t, dict)), key=lambda t: first[id(t)].get("stay_rate_r_per_hour") if first[id(t)].get("stay_rate_r_per_hour") is not None else 9e9)
    pool, rows = list(alts or ()), []
    for t in order:
        r = decide(t, pool, can_open, c)
        if r["decision"] == "ROTATE":
            pool = [a for a in pool if a.get("id") != r["alt"].get("id")]
        rows.append(r)
    n = {k: sum(1 for x in rows if x["decision"] == k) for k in ("KEEP", "STAY", "TAKE_PROFIT", "ROTATE")}
    text = "No open trade." if not rows else "%d open: %d to switch, %d ready to take profit, %d waiting, %d with nothing to do." % (len(rows), n["ROTATE"], n["TAKE_PROFIT"], n["STAY"], n["KEEP"])
    return {"version": VERSION, "state": "OK" if rows else "NO_TRADES", "counts": n, "rows": rows, "text": text, "lines": [text] + [x["text"] for x in rows if x["decision"] in ("ROTATE", "TAKE_PROFIT")], "paper_only": True, "report_only": True}


def arrival_rate(examples, days=7, now=None):
    """How often a new setup of each interval x side showed up (bridge entries, newest `days` days). Per hour over the UTC days that HAVE entries. Below 30 entries: no number."""
    now = time.time() if now is None else now
    g = {}
    for e in examples or []:
        ts = _num(e.get("entry_ts"))
        if ts is None or ts < now - days * 86400 or ts > now or not e.get("tf") or e.get("side") not in ("LONG", "SHORT"):
            continue
        g.setdefault("%s|%s" % (e["tf"], e["side"]), []).append(ts)
    out = {}
    for k, ts in sorted(g.items()):
        d = len({int(x // 86400) for x in ts})
        out[k] = {"state": "OK", "entries": len(ts), "days_with_data": d, "per_hour": round(len(ts) / (24.0 * d), 3)} if len(ts) >= MIN_ARRIVALS else {"state": "NOT_ENOUGH_DATA", "entries": len(ts)}
    return {"version": VERSION, "days": days, "rates": out, "paper_only": True,
            "text": ("New setups per hour (days with data only): " + "; ".join("%s %.2f" % (k, v["per_hour"]) for k, v in out.items() if v["state"] == "OK")) if any(v["state"] == "OK" for v in out.values()) else "Not enough entries (30 per interval and side) to say how often new setups show up."}


def build(d, limit=0, since_days=None, now=None):
    """Saved files -> bridge examples -> dedupe -> arrival rate. Read only. Never raises."""
    t0 = time.time()
    try:
        import owl_sniper_bridge_learn as BL
        ex, _x = BL.load_examples(d, limit=limit, since_days=since_days, now=now)
        ex, dropped = BL.dedupe(ex)
        rep = arrival_rate(ex, now=now)
        rep["dropped_duplicates"] = dropped
    except Exception as e:  # a broken file must never break the caller
        rep = {"version": VERSION, "rates": {}, "text": "Could not read the trades: %s" % type(e).__name__, "paper_only": True}
    rep["seconds"] = round(time.time() - t0, 2)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper opportunity cost: stay or rotate (report only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or ".")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--file", default=None)
    a = ap.parse_args(argv)
    if a.file:
        with open(a.file, "r", encoding="utf-8") as f:
            x = json.load(f)
        print(json.dumps(report(x.get("trades"), x.get("alts"), x.get("can_open", True)), indent=1, default=str))
    else:
        print(json.dumps(build(a.data, a.limit, a.since_days), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
