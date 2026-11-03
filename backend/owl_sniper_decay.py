"""owl_sniper_decay.py - OwlSniper EDGE DECAY monitor + KILL CRITERIA (Part 29 / FILE 20). REPORT ONLY: it never pauses, switches or changes anything. Read only, no network, no order code, nothing written.
The question: "This setup paid in the past. Is it STILL paying, or is the edge fading?" and "Is it time to stop taking it for now?"
How it works (plain words):
  1. Finished trades of one SETUP FAMILY, oldest first (the order they CLOSED: entry time + time to result, so nothing from the future is used). A family = lane + interval + side, and the same again with the regime.
     Lanes are the bridge sources (dual / brain / main) judged apart, plus POOL = the deduped bridge pool the Risk Box reads. Lanes are never added together. Any other R list (later: the Sniper's own closed trades) can use assess().
  2. EDGE state, from the R after fees of the newest RECENT (25) trades:
       NOT_ENOUGH_DATA = fewer than 30 finished trades in the family. No verdict, no number.
       EXPIRED = even the best end of the recent range (mean + 2 standard errors) is below 0 R: it is losing now.
       WEAK    = recent mean is 0 or below, OR (when 30+ older trades exist) recent is clearly below its own past (the whole gap range is under 0).
       VALID   = no decay seen. This is NOT a proof of an edge (that is the Part 23 / Risk Box job), only that it has not faded.
     To avoid overreacting to a small sample: a WEAK / EXPIRED state is called CONFIRMED only if the window 5 trades earlier was also WEAK or EXPIRED; otherwise it says "first sign, not confirmed yet".
  3. KILL CRITERIA, defined here BEFORE any automatic reaction exists (nothing automatic is built; owner approval needed):
       LOSS_STREAK: 4 losses in a row = WATCH, 5 in a row = TRIPPED (owner example). The text also says how often such a run is only bad luck at the family's usual loss rate.
       EXPECTANCY:  edge EXPIRED = TRIPPED, edge WEAK = WATCH.
       DRAWDOWN:    in the newest 25 trades the cumulative R falls 4 R from its peak = WATCH, 6 R = TRIPPED (needs 10+ trades).
       EXPECTED_VS_ACTUAL: the Part 13 cohort says BELOW_EXPECTED = WATCH (optional input).
     Kill state OK / WATCH / TRIPPED. TRIPPED only SUGGESTS "stop taking this setup for now"; paused is always False. The limits are starting values the owner may tune.
API: assess(rs, eva=None), rows_from_examples(examples), report(examples), for_signal(rep, tf, side, regime=None), build(d, limit=0, since_days=None). CLI:
  python3 backend/owl_sniper_decay.py --data DIR [--limit 2000] [--since-days N]   -> JSON (no secrets)."""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "owl_sniper_decay 1 (Part 29)"
MIN_N = 30                  # finished trades before any edge verdict
RECENT = 25                 # newest trades that are judged (20-30 in the prompt)
CONFIRM = 5                 # look back this many trades to confirm a bad state
Z = 2.0                     # standard errors for the ranges
STREAK_WATCH, STREAK_KILL = 4, 5
DD_WATCH_R, DD_KILL_R, DD_MIN_N = 4.0, 6.0, 10
SEV = {"NOT_ENOUGH_DATA": 0, "VALID": 1, "WEAK": 2, "EXPIRED": 3}
KSEV = {"OK": 0, "WATCH": 1, "TRIPPED": 2}


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _ms(xs):
    """mean and standard error of the mean."""
    n = len(xs)
    m = sum(xs) / n
    return m, (math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1) / n) if n > 1 else 0.0)


def _win(xs):
    return round(100.0 * sum(1 for x in xs if x > 0) / len(xs), 1)


def _state(rs):
    """R list (oldest first) -> edge state + numbers. Below MIN_N: NOT_ENOUGH_DATA and no number."""
    n = len(rs)
    if n < MIN_N:
        return {"state": "NOT_ENOUGH_DATA", "n": n}
    rec, base = rs[-RECENT:], rs[:-RECENT]
    mr, sr = _ms(rec)
    out = {"state": "VALID", "n": n, "recent_n": len(rec), "recent_r": round(mr, 3), "recent_low": round(mr - Z * sr, 3), "recent_high": round(mr + Z * sr, 3),
           "recent_win_pct": _win(rec), "base_n": len(base), "base_r": None, "base_win_pct": None, "gap_r": None, "gap_high": None, "dropped": False}
    if len(base) >= MIN_N:
        mb, sb = _ms(base)
        gap, hi = mr - mb, mr - mb + Z * math.sqrt(sr ** 2 + sb ** 2)
        out.update(base_r=round(mb, 3), base_win_pct=_win(base), gap_r=round(gap, 3), gap_high=round(hi, 3), dropped=hi < 0)
    if mr + Z * sr < 0:
        out["state"] = "EXPIRED"
    elif mr <= 0 or out["dropped"]:
        out["state"] = "WEAK"
    return out


def _trend(rs):
    """Mean R of up to 4 blocks of RECENT trades, oldest block first (needs 2 full blocks)."""
    k = min(4, len(rs) // RECENT)
    if k < 2:
        return []
    cut = rs[len(rs) - k * RECENT:]
    return [round(sum(cut[i * RECENT:(i + 1) * RECENT]) / RECENT, 3) for i in range(k)]


def _streak(rs):
    s = 0
    for x in reversed(rs):
        if x > 0:
            break
        s += 1
    return s


def _drawdown(rs):
    """Largest fall of the cumulative R from its peak (in R, 0 or more)."""
    cur = peak = dd = 0.0
    for x in rs:
        cur += x
        peak = max(peak, cur)
        dd = max(dd, peak - cur)
    return dd


def _edge_line(st, confirmed):
    n, s = st["n"], st["state"]
    if s == "NOT_ENOUGH_DATA":
        return "NOT ENOUGH DATA: %d of %d finished trades. No edge verdict, no number." % (n, MIN_N)
    last = "Last %d trades: %+.2f R each (range %+.2f to %+.2f), %.0f%% won." % (st["recent_n"], st["recent_r"], st["recent_low"], st["recent_high"], st["recent_win_pct"])
    if s == "VALID":
        return "Edge VALID: no decay seen. %s This does not prove an edge, only that it has not faded." % last
    why = ("it is clearly below its own past (%+.2f R against %+.2f R before)" % (st["recent_r"], st["base_r"])) if st["dropped"] and st["recent_r"] > 0 else \
        ("even the best end of the range is below zero" if s == "EXPIRED" else "the recent average is not above zero")
    tail = "Confirmed (the window 5 trades earlier was also weak)." if confirmed else "First sign, not confirmed yet."
    return "Edge %s: %s. %s %s" % (s, why, last, tail)


def assess(rs, eva=None):
    """ONE family: R after fees of its finished trades, oldest first (closed order) -> edge state + kill state. Never raises on bad numbers (they are dropped).
    eva = the Part 13 cohort dict of the same lane (optional)."""
    rs = [x for x in (_num(v) for v in rs or []) if x is not None]
    n = len(rs)
    st = _state(rs)
    prev = _state(rs[:-CONFIRM]) if n - CONFIRM >= MIN_N else None
    bad = st["state"] in ("WEAK", "EXPIRED")
    confirmed = bool(prev and SEV[prev["state"]] >= SEV["WEAK"]) if bad else None
    kills = []
    s = _streak(rs)
    if s >= STREAK_WATCH:
        txt = "%d losses in a row." % s
        if n - s >= MIN_N:
            pl = sum(1 for x in rs[:-s] if x <= 0) / float(n - s)
            txt += " At its usual loss rate (%.0f%%) a run like this is bad luck only about %.1f%% of the time." % (100 * pl, 100 * pl ** s)
        kills.append({"rule": "LOSS_STREAK", "level": "TRIPPED" if s >= STREAK_KILL else "WATCH", "text": txt})
    if bad:
        kills.append({"rule": "EXPECTANCY", "level": "TRIPPED" if st["state"] == "EXPIRED" else "WATCH", "text": "Edge %s: the last %d trades average %+.2f R." % (st["state"], st["recent_n"], st["recent_r"])})
    dd = _drawdown(rs[-RECENT:]) if n >= DD_MIN_N else None
    if dd is not None and dd >= DD_WATCH_R:
        kills.append({"rule": "DRAWDOWN", "level": "TRIPPED" if dd >= DD_KILL_R else "WATCH", "text": "In the newest %d trades the result fell %.1f R from its peak (limits: %g R watch, %g R stop)." % (min(n, RECENT), dd, DD_WATCH_R, DD_KILL_R)})
    if isinstance(eva, dict) and eva.get("state") == "BELOW_EXPECTED":
        kills.append({"rule": "EXPECTED_VS_ACTUAL", "level": "WATCH", "text": "Real results are below what the Risk Box expected (Part 13)."})
    kill = max((k["level"] for k in kills), key=lambda x: KSEV[x], default="OK")
    act = {"OK": "No kill rule is near.", "WATCH": "Watch this setup: one more bad sign may trip a kill rule. Nothing was paused.",
           "TRIPPED": "Suggest: stop taking this setup for now and review it (paper / LEARN only). Nothing was paused. Owner approval is needed for any automatic stop."}[kill]
    tr = _trend(rs)
    line = _edge_line(st, confirmed)
    lines = [line] + [k["text"] for k in kills] + (["Blocks of %d trades, oldest first: %s R." % (RECENT, ", ".join("%+.2f" % x for x in tr))] if tr else []) + [act]
    return dict(st, edge_line=line, confirmed=confirmed, kill=kill, kills=kills, action=act, trend=tr, falling=len(tr) >= 3 and all(tr[i] > tr[i + 1] for i in range(len(tr) - 1)),
                streak=s, drawdown_r=round(dd, 2) if dd is not None else None, paused=False, lines=lines)


def rows_from_examples(examples):
    """Bridge examples (owl_sniper_bridge_label.join) -> flat rows sorted by CLOSE time. Rows without R, time, interval or side are left out."""
    out = []
    for e in examples or []:
        lab = e.get("label") or {}
        r, t = _num(lab.get("r_net")), _num(e.get("entry_ts"))
        if r is None or t is None or not e.get("tf") or e.get("side") not in ("LONG", "SHORT"):
            continue
        out.append({"src": str(e.get("source") or "?"), "tf": str(e["tf"]), "side": e["side"], "regime": str(e.get("regime") or "?"), "ts": t + (_num(lab.get("secs_to_result")) or 0.0), "r": r})
    out.sort(key=lambda x: x["ts"])
    return out


def _groups(rows):
    g = {}
    for x in rows:
        for lane in (x["src"], "POOL"):
            base = "%s|%s|%s" % (lane, x["tf"], x["side"])
            g.setdefault(base, []).append(x["r"])
            g.setdefault(base + "|" + x["regime"], []).append(x["r"])
    return g


def report(examples, now=None):
    """Deduped bridge examples -> edge + kill state for every family. Never writes. Lanes stay apart."""
    rows = rows_from_examples(examples)
    fams = {k: assess(v) for k, v in sorted(_groups(rows).items())}
    judged = [k for k, v in fams.items() if v["state"] != "NOT_ENOUGH_DATA"]
    alerts = sorted((k for k, v in fams.items() if v["state"] in ("WEAK", "EXPIRED") or v["kill"] != "OK"), key=lambda k: (-KSEV[fams[k]["kill"]], -SEV[fams[k]["state"]], k))
    if not rows:
        text = "No finished trade with a result yet: no edge can be judged (never a made-up number)."
    else:
        text = "%d finished trades, %d setups judged (30+ trades each), %d with a warning (WEAK / EXPIRED or a kill rule)." % (len(rows), len(judged), len(alerts))
    return {"version": VERSION, "state": "OK" if rows else "NOT_ENOUGH_DATA", "n_trades": len(rows), "n_judged": len(judged), "alerts": alerts, "families": fams, "text": text,
            "lines": [text] + ["%s: %s" % (k, fams[k]["edge_line"]) for k in alerts[:3]], "paper_only": True, "report_only": True, "now": time.time() if now is None else now}


def for_signal(rep, tf, side, regime=None):
    """The one line for the Risk Box: the POOL family of this interval + side (+ regime first, when judged). -> {state, kill, line, key}."""
    fams = (rep or {}).get("families") or {}
    base = "POOL|%s|%s" % (tf, side)
    for key in ((base + "|" + regime,) if regime else ()) + (base,):
        a = fams.get(key)
        if a and (a["state"] != "NOT_ENOUGH_DATA" or a["kill"] != "OK"):
            return {"state": a["state"], "kill": a["kill"], "line": a["edge_line"], "key": key}
    return {"state": "NOT_ENOUGH_DATA", "kill": "OK", "key": None, "line": "Edge: NOT ENOUGH DATA (fewer than %d finished trades for this setup)." % MIN_N}


def build(d, limit=0, since_days=None, now=None):
    """Saved files -> bridge examples -> dedupe -> report. Read only. Never raises."""
    t0 = time.time()
    try:
        import owl_sniper_bridge_learn as BL
        ex, _x = BL.load_examples(d, limit=limit, since_days=since_days, now=now)
        ex, dropped = BL.dedupe(ex)
        rep = report(ex, now)
        rep["dropped_duplicates"] = dropped
    except Exception as e:  # a broken file must never break the caller
        rep = {"version": VERSION, "state": "ERROR", "text": "Could not read the trades: %s" % type(e).__name__, "lines": ["Could not read the trades: %s" % type(e).__name__], "families": {}, "alerts": [], "paper_only": True, "report_only": True}
    rep["seconds"] = round(time.time() - t0, 2)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper edge decay + kill criteria (report only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or ".")
    ap.add_argument("--limit", type=int, default=0, help="only the newest N records (keeps the phone light)")
    ap.add_argument("--since-days", type=float, default=None)
    a = ap.parse_args(argv)
    print(json.dumps(build(a.data, a.limit, a.since_days), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
