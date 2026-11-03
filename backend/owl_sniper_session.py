"""owl_sniper_session.py - OwlSniper SESSION / TIME-OF-DAY check (Part 42 / FILE 51). REPORT ONLY: it never blocks, pauses or changes anything. Read only, no network, no order code, nothing written.
The question: "Which hours and sessions of the day paid, and which lost?"  Only OBSERVED results are used; no hour is called good or bad from belief.
How it works (plain words):
  1. Finished bridge trades (R after fees, Dual / Brain / main bot, deduped; the same examples the Risk Box and the edge decay read). Time = the ENTRY time in UTC.
     The trading day starts 00:00 UTC = 5:30 AM IST, so the text always shows the IST clock too.
  2. FAMILY = lane x interval. Lanes are the bridge sources judged apart (dual / brain / main) plus POOL = the deduped pool. Lanes are NEVER added together.
  3. In each family every BUCKET is judged: 4 SESSIONS (ASIA 00-08 UTC, EUROPE 08-13, US 13-21, LATE 21-24; starting values the owner may tune), 24 HOURS, and WEEKDAY vs WEEKEND.
     Each bucket is compared with ALL OTHER trades of the same family (same lane, same interval), so a good market week does not make every hour look good.
       NOT_ENOUGH_DATA = fewer than 30 trades in the bucket (or fewer than 30 outside it). No verdict, no number is called a result.
       PAYS   = the whole range of its own mean R is above 0 (2 standard errors) AND it is clearly better than the rest (gap low end above 0, 3.5 standard errors) AND above 0 in the older half AND in the newer half (10+ trades each).
       LOSES  = the whole range of its own mean R is below 0 AND clearly worse than the rest (gap high end below 0, 3.5 standard errors) AND below 0 in both halves. A bucket that is only worse than a lucky rest, but not losing itself, stays NO_DIFFERENCE.
       NO_DIFFERENCE = anything else. This is the normal answer; most hours will say it, and that is honest.
  4. HONEST LIMIT: trades of different coins in the same hour move together (see owl_sniper_corr.py), so the real number of independent cases is smaller than n. A PAYS / LOSES is a strong hint to test further, never a proof.
     It only SUGGESTS "prefer" or "avoid"; nothing in the Sniper reads this file yet (no gate, no size change). Many hours = many checks, so one lucky PAYS among 24 hours can happen by chance (the report says how many were checked).
API: session_of(ts), ist_text(ts), assess(rows), rows_from_examples(examples), report(examples), for_signal(rep, tf, ts=None, lane="POOL"), build(d, limit=0, since_days=None). CLI:
  python3 backend/owl_sniper_session.py --data DIR [--limit 2000] [--since-days N]   -> JSON (no secrets)."""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "owl_sniper_session 1 (Part 42)"
MIN_N = 30                  # trades in a bucket (and outside it) before any verdict
HALF_MIN = 10               # trades in each half of a bucket
Z = 2.0                     # standard errors for the ranges shown
Z_GAP = 3.5                 # standard errors for the gap to the rest (stricter: about 35 buckets are checked at once; on made-up random data about 5% of runs show one false alarm)
SESSIONS = (("ASIA", 0, 8), ("EUROPE", 8, 13), ("US", 13, 21), ("LATE", 21, 24))   # UTC hours [from, to)
IST_SHIFT_MIN = 330         # IST = UTC + 5:30
SEV = {"NOT_ENOUGH_DATA": 0, "NO_DIFFERENCE": 1, "LOSES": 2, "PAYS": 2}


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _ms(xs):
    n = len(xs)
    m = sum(xs) / n
    return m, (math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1) / n) if n > 1 else 0.0)


def session_of(ts):
    """Epoch seconds -> session name by the UTC hour."""
    h = int(ts // 3600) % 24
    for name, a, b in SESSIONS:
        if a <= h < b:
            return name
    return "LATE"


def ist_text(ts):
    """Epoch seconds -> 'HH:MM IST' (plain clock, for the owner)."""
    m = (int(ts // 60) + IST_SHIFT_MIN) % 1440
    return "%02d:%02d IST" % (m // 60, m % 60)


def _span_ist(a, b):
    """UTC hour range -> the same range in IST, e.g. (0, 8) -> '05:30-13:30 IST'."""
    f = lambda h: "%02d:%02d" % (((h * 60 + IST_SHIFT_MIN) % 1440) // 60, ((h * 60 + IST_SHIFT_MIN) % 1440) % 60)
    return "%s-%s IST" % (f(a), f(b))


def _day_type(ts):
    return "WEEKEND" if int(ts // 86400 + 3) % 7 in (5, 6) else "WEEKDAY"      # 1 Jan 1970 was a Thursday (index 3 with Monday = 0)


def _buckets(ts):
    h = int(ts // 3600) % 24
    return ("S:" + session_of(ts), "H:%02d" % h, "D:" + _day_type(ts))


def _verdict(inside, outside):
    """inside / outside = R lists oldest first (outside = the rest of the same family). -> dict with state + numbers (no number below MIN_N)."""
    n = len(inside)
    if n < MIN_N or len(outside) < MIN_N:
        return {"state": "NOT_ENOUGH_DATA", "n": n}
    m, se = _ms(inside)
    mo, so = _ms(outside)
    gap, gse = m - mo, math.sqrt(se ** 2 + so ** 2)
    k = n // 2
    halves = [inside[:k], inside[k:]]
    hm = [sum(h) / len(h) if len(h) >= HALF_MIN else None for h in halves]
    out = {"state": "NO_DIFFERENCE", "n": n, "mean_r": round(m, 3), "low": round(m - Z * se, 3), "high": round(m + Z * se, 3), "win_pct": round(100.0 * sum(1 for x in inside if x > 0) / n, 1),
           "rest_r": round(mo, 3), "gap_r": round(gap, 3), "gap_low": round(gap - Z_GAP * gse, 3), "gap_high": round(gap + Z_GAP * gse, 3), "older_r": None if hm[0] is None else round(hm[0], 3),
           "newer_r": None if hm[1] is None else round(hm[1], 3)}
    if None in hm:
        return out
    if m - Z * se > 0 and gap - Z_GAP * gse > 0 and hm[0] > 0 and hm[1] > 0:
        out["state"] = "PAYS"
    elif m + Z * se < 0 and gap + Z_GAP * gse < 0 and hm[0] < 0 and hm[1] < 0:
        out["state"] = "LOSES"
    return out


def assess(rows):
    """ONE family: rows [{ts, r}] sorted by entry time -> {sessions, hours, daytype, checked, best, worst, lines}. Never raises on bad numbers (dropped)."""
    rows = sorted(({"ts": t, "r": r} for t, r in ((_num(x.get("ts")), _num(x.get("r"))) for x in rows or []) if t is not None and r is not None), key=lambda x: x["ts"])
    idx = {}
    for i, x in enumerate(rows):
        for b in _buckets(x["ts"]):
            idx.setdefault(b, []).append(i)
    res = {}
    for b, ids in idx.items():
        s = set(ids)
        res[b] = _verdict([rows[i]["r"] for i in ids], [x["r"] for i, x in enumerate(rows) if i not in s])
    names = ["S:" + s[0] for s in SESSIONS] + ["H:%02d" % h for h in range(24)] + ["D:WEEKDAY", "D:WEEKEND"]
    for b in names:                                                  # a bucket with no trade at all is still listed, so nothing is silently missing
        res.setdefault(b, {"state": "NOT_ENOUGH_DATA", "n": 0})
    pick = lambda pre: {b[2:]: res[b] for b in names if b.startswith(pre)}
    judged = [b for b in names if res[b]["state"] != "NOT_ENOUGH_DATA"]
    pays = sorted((b for b in judged if res[b]["state"] == "PAYS"), key=lambda b: -res[b]["gap_r"])
    loses = sorted((b for b in judged if res[b]["state"] == "LOSES"), key=lambda b: res[b]["gap_r"])
    name = lambda b: {"S": "session ", "H": "hour ", "D": ""}[b[0]] + b[2:] + (" UTC" if b[0] == "H" else "")
    lines = ["%d trades; %d of %d buckets have enough trades to judge (%d checks: more checks means one lucky PAYS can happen by chance)." % (len(rows), len(judged), len(names), len(judged))]
    for b in pays[:2]:
        lines.append("PAYS: %s (%+.2f R each, %.1f R better than the rest, %d trades)." % (name(b), res[b]["mean_r"], res[b]["gap_r"], res[b]["n"]))
    for b in loses[:2]:
        lines.append("LOSES: %s (%+.2f R each, %.1f R worse than the rest, %d trades)." % (name(b), res[b]["mean_r"], -res[b]["gap_r"], res[b]["n"]))
    if not pays and not loses:
        lines.append("No bucket is clearly different from the rest: no time of day to prefer or avoid.")
    return {"n": len(rows), "sessions": pick("S:"), "hours": pick("H:"), "daytype": pick("D:"), "checked": len(judged), "pays": [name(b) for b in pays], "loses": [name(b) for b in loses], "lines": lines}


def rows_from_examples(examples):
    """Bridge examples (owl_sniper_bridge_label.join) -> flat rows. Rows without R, entry time, interval or side are left out."""
    out = []
    for e in examples or []:
        lab = e.get("label") or {}
        r, t = _num(lab.get("r_net")), _num(e.get("entry_ts"))
        if r is None or t is None or not e.get("tf") or e.get("side") not in ("LONG", "SHORT"):
            continue
        out.append({"src": str(e.get("source") or "?"), "tf": str(e["tf"]), "ts": t, "r": r})
    out.sort(key=lambda x: x["ts"])
    return out


def report(examples, now=None):
    """Deduped bridge examples -> one assessment per family (lane x interval). Never writes. Lanes stay apart."""
    rows = rows_from_examples(examples)
    g = {}
    for x in rows:
        for lane in (x["src"], "POOL"):
            g.setdefault("%s|%s" % (lane, x["tf"]), []).append(x)
    fams = {k: assess(v) for k, v in sorted(g.items())}
    alerts = [k for k, v in fams.items() if v["pays"] or v["loses"]]
    text = "No finished trade with a result yet: no time of day can be judged (never a made-up number)." if not rows else \
        "%d finished trades, %d families, %d with a bucket that clearly pays or loses." % (len(rows), len(fams), len(alerts))
    return {"version": VERSION, "state": "OK" if rows else "NOT_ENOUGH_DATA", "n_trades": len(rows), "families": fams, "alerts": alerts, "text": text,
            "lines": [text] + ["%s: %s" % (k, " ".join(fams[k]["lines"][1:])) for k in alerts[:3]], "paper_only": True, "report_only": True,
            "sessions_utc": {n: {"hours": "%02d-%02d UTC" % (a, b), "ist": _span_ist(a, b)} for n, a, b in SESSIONS}, "now": time.time() if now is None else now}


def for_signal(rep, tf, ts=None, lane="POOL"):
    """The one line for the Risk Box: how the session (and hour) of `ts` (default now) did in the family lane|tf. -> {state, session, hour, line}."""
    ts = time.time() if ts is None else ts
    a = ((rep or {}).get("families") or {}).get("%s|%s" % (lane, tf))
    sess, hr = session_of(ts), "%02d" % (int(ts // 3600) % 24)
    base = {"session": sess, "hour": hr, "clock": ist_text(ts)}
    if not a:
        return dict(base, state="NOT_ENOUGH_DATA", line="Session %s (%s): NOT ENOUGH DATA for this setup." % (sess, ist_text(ts)))
    for kind, key in (("hour", hr), ("session", sess)):             # the hour speaks first when it is judged and clearly different, else the session
        v = a["hours" if kind == "hour" else "sessions"].get(key) or {}
        if v.get("state") in ("PAYS", "LOSES"):
            return dict(base, state=v["state"], line="Time of day: %s %s %s (%+.2f R each, %d trades, %.1f R %s than the rest). Hint only." % (
                kind, key, v["state"], v["mean_r"], v["n"], abs(v["gap_r"]), "better" if v["state"] == "PAYS" else "worse"))
    v = a["sessions"].get(sess) or {}
    if v.get("state") == "NO_DIFFERENCE":
        return dict(base, state="NO_DIFFERENCE", line="Session %s (%s): no clear difference from the other hours (%d trades)." % (sess, ist_text(ts), v["n"]))
    return dict(base, state="NOT_ENOUGH_DATA", line="Session %s (%s): NOT ENOUGH DATA (%d of %d trades)." % (sess, ist_text(ts), v.get("n", 0), MIN_N))


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
    ap = argparse.ArgumentParser(description="OwlSniper session / time-of-day check (report only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or ".")
    ap.add_argument("--limit", type=int, default=0, help="only the newest N records (keeps the phone light)")
    ap.add_argument("--since-days", type=float, default=None)
    a = ap.parse_args(argv)
    print(json.dumps(build(a.data, a.limit, a.since_days), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
