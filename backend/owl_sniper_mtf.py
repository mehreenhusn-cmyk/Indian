"""owl_sniper_mtf.py - OwlSniper SMART MULTI-TIMEFRAME CONFLUENCE table (Part 28 / FILE 19, group G4). READ ONLY: the market store is opened read-only, no network, no order code.
The owner's question (MASTER_PROMPT 4.9): "When I trade 5m, does the NEAREST higher timeframe (15m) really help, and does a far one (4h) help less? Which higher-TF relationship improves expectancy?"
This file OBSERVES and MEASURES that. The higher candles come from owl_sniper_tf.py (htf_candles, built from real 5m candles, complete buckets only). It reuses the outcome + verdict rule of Part 23 (owl_sniper_ind_pairs.py) and pooled() of Part 27 (owl_sniper_regime.py).
PLAN:  5m trades are checked against 15m (nearest) and 4h (far control);  15m trades against 30m (nearest) and 4h (far control).  30m / 1h / 2h / 4h are context only, never a trading interval.
HIGHER-TF STATE (the only thing read): UP when the last COMPLETE higher candle closed ABOVE the average of its last 10 closes, DOWN when below (else no state). "Last complete" = the higher candle must have fully CLOSED at or before the close of the trade candle i, so nothing looks ahead.
EVERY candle with a state gives two decisions: ALIGNED (LONG when the higher TF is UP, SHORT when DOWN) and OPPOSED (the other one).
OUTCOME + VERDICT: exactly Part 23: entry = OPEN of the next trade candle, 1R = UNIT x price, +2R / -1R, 30 candles, stop first; baseline = any candle with a state (LONG / SHORT mixed by the share of each); independent cases only;
  NOT_ENOUGH_DATA below 30 independent cases (15 per half) / STEADY (both halves, 60% of coins, lift above 2 x standard error) / SOMETIMES (not proven) / NO_PAY.
GAIN = expected R of the ALIGNED decision minus the OPPOSED decision on the SAME candle (paired, independent candles only); gain_low = gain - 2 x standard error.
LABEL per (trade TF, higher TF):  STRONG = aligned is STEADY and gain_low > 0  /  MEDIUM = aligned is at least SOMETIMES and gain > 0  /  WEAK = judged, but aligned does not beat opposed or a random candle  /  UNKNOWN = not enough independent cases yet.
WEIGHT (what the Sniper may use): STRONG 1.0, MEDIUM 0.25 (only a hint, not proven), WEAK 0.0, UNKNOWN = the prior of owl_sniper_tf.weight_of (nearest 1.0, far 0.0). 'nearest_beats_far' = the nearest TF has the bigger gain (None when one is unknown).
LIVE HELPERS: htf_state_now(run5m, htf) = the state at the end of a real 5m run;  confluence_line(report, tf, side, state) = 'MTF Confluence: Strong (15m UP agrees with LONG)' for the Risk Box (Against / Weak / Medium / Strong, or 'not studied yet').
A run needs 700+ gap-free 5m candles (the 4h average needs 40 hours). 4 pairs x 2 states-of-evidence = 8 verdicts: one STEADY by luck is possible, trust it when it stays STEADY on a later run.
Run (Termux, optional):  python3 backend/owl_sniper_mtf.py [--data DIR] [--cap 40] [--since-days N] [--save]  -> JSON (--save also writes v2_sniper_mtf.json). Needs owl_sniper_ind_pairs.py (Part 23), owl_sniper_regime.py (Part 27) and the new owl_sniper_tf.py next to it."""
import argparse
import bisect
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_engine as E
import owl_sniper_feed as F
import owl_sniper_ind_pairs as IP
import owl_sniper_regime as R
import owl_sniper_tf as TF
import v2_defs as D
import v2_setup_finder as SF

VERSION = "owl_sniper_mtf 1 (Part 28)"
FILE = "v2_sniper_mtf.json"
PLAN = {"5m": ("15m", "4h"), "15m": ("30m", "4h")}
SMA_N, MIN_RUN, WEIGHT = 10, 700, {"STRONG": 1.0, "MEDIUM": 0.25, "WEAK": 0.0}


def htf_series(run, htf):
    """(ends, states) of the COMPLETE higher candles of one real 5m run: ends = close time of each, state = 'UP' / 'DOWN' / None (needs 10 closes)."""
    h, span = TF.htf_candles(run, htf), TF.STEP[TF.BASE] * TF.HTF_FACTOR[htf]
    cl = [x[4] for x in h]
    st = [None] * len(h)
    for j in range(SMA_N - 1, len(h)):
        m = sum(cl[j - SMA_N + 1:j + 1]) / SMA_N
        st[j] = "UP" if cl[j] > m else "DOWN" if cl[j] < m else None
    return [x[0] + span for x in h], st


def state_at(series, close_time):
    """The state of the last higher candle that was fully closed at close_time (None if none / no state yet)."""
    ends, st = series
    j = bisect.bisect_right(ends, close_time) - 1
    return st[j] if j >= 0 else None


def analyse(runs, since_ts=0):
    """-> (rows {(trade tf, higher tf): [(ts, symbol, long result, short result, state)]}, coins, skipped)."""
    rows, coins, skipped = {(tf, h): [] for tf in PLAN for h in PLAN[tf]}, set(), {"short_run": 0, "bad_candles": 0}
    for sym, run in runs:
        ser = {h: htf_series(run, h) for h in {h for hs in PLAN.values() for h in hs}}
        for tf, hts in PLAN.items():
            try:
                S = E.to_series(TF.aggregate(run, tf))
            except ValueError:
                skipped["bad_candles"] += 1
                continue
            lo, hi, step = IP.UNIT_WIN + 1, S["n"] - IP.HOLD - 2, TF.STEP[tf]
            if hi - lo < 50:
                skipped["short_run"] += 1
                continue
            coins.add(sym)
            for i in range(lo, hi + 1):
                u = IP.unit_of(S, i)
                if S["t"][i] < since_ts or u <= 0:
                    continue
                entry, res = S["o"][i + 1], None
                for h in hts:
                    st = state_at(ser[h], S["t"][i] + step)       # only higher candles that CLOSED by the close of candle i
                    if st is None:
                        continue
                    if res is None:
                        res = (IP.walk(S, i, "LONG", entry, u * entry), IP.walk(S, i, "SHORT", entry, u * entry))
                    rows[(tf, h)].append((S["t"][i], sym, res[0], res[1], st))
    return rows, coins, skipped


def label_of(aligned, gain, gain_low):
    v = aligned["verdict"]
    if v == "NOT_ENOUGH_DATA":
        return "UNKNOWN"
    if v == "STEADY" and gain_low > 0:
        return "STRONG"
    return "MEDIUM" if v in ("STEADY", "SOMETIMES") and gain > 0 else "WEAK"


def judge_pair(rows, tf, h, step):
    """The answer for one (trade TF, higher TF) from its rows."""
    ts = sorted(r[0] for r in rows)
    cut = ts[int(len(ts) * IP.TRAIN_FRAC)] if ts else 0
    tr, te = [r for r in rows if r[0] < cut], [r for r in rows if r[0] >= cut]
    bl = {k: {"all": IP.mean_r(rows, k) or 0.0, "tr": IP.mean_r(tr, k) or 0.0, "te": IP.mean_r(te, k) or 0.0} for k in (2, 3)}
    al = [(r[0], r[1], (r[2] if r[4] == "UP" else r[3]), (r[2] if r[4] == "UP" else r[3]), "LONG" if r[4] == "UP" else "SHORT") for r in rows]
    op = [(r[0], r[1], (r[3] if r[4] == "UP" else r[2]), (r[3] if r[4] == "UP" else r[2]), "SHORT" if r[4] == "UP" else "LONG") for r in rows]
    a, o = R.pooled(al, cut, bl, IP.HOLD * step), R.pooled(op, cut, bl, IP.HOLD * step)
    d = [(r[2][0] - r[3][0]) * (1 if r[4] == "UP" else -1) for r in IP.thin(rows, IP.HOLD * step)]
    gain = gain_low = None
    if len(d) >= IP.MIN_N:
        gain = sum(d) / len(d)
        se = (sum((x - gain) ** 2 for x in d) / (len(d) - 1)) ** 0.5 / len(d) ** 0.5
        gain_low = gain - IP.SE_MULT * se
    lab = label_of(a, gain or 0.0, gain_low if gain_low is not None else -9.0)
    prior = TF.weight_of(tf, h)
    return {"trade_tf": tf, "higher_tf": h, "prior_weight": prior, "n": len(rows), "up_pct": round(100.0 * sum(1 for r in rows if r[4] == "UP") / len(rows)) if rows else None,
            "label": lab, "weight": WEIGHT.get(lab, prior), "gain_r": None if gain is None else round(gain, 3), "gain_low_r": None if gain_low is None else round(gain_low, 3), "aligned": a, "opposed": o}


def report(rows):
    out, table = {}, {}
    for (tf, h), rs in rows.items():
        table["%s>%s" % (tf, h)] = judge_pair(rs, tf, h, TF.STEP[tf])
    for tf, (near, far) in PLAN.items():
        n, f = table["%s>%s" % (tf, near)], table["%s>%s" % (tf, far)]
        beats = None if n["gain_r"] is None or f["gain_r"] is None else n["gain_r"] > f["gain_r"]
        out[tf] = {"nearest": near, "far": far, "nearest_label": n["label"], "far_label": f["label"], "nearest_beats_far": beats,
                   "plain": "%s trades: nearest higher TF %s = %s%s; far %s = %s%s. %s" % (tf, near, n["label"], "" if n["gain_r"] is None else " (aligned beats opposed by %+.2fR)" % n["gain_r"], far, f["label"],
                                                                                       "" if f["gain_r"] is None else " (%+.2fR)" % f["gain_r"], "The nearest TF is better." if beats else "The nearest TF is NOT clearly better." if beats is False else "Not enough data to compare yet.")}
    return {"pairs": table, "by_trade_tf": out}


def htf_state_now(run, htf):
    """The state of the last complete higher candle at the END of a real 5m run (its last candle is closed)."""
    return state_at(htf_series(run, htf), run[-1][0] + TF.STEP[TF.BASE]) if run else None


def confluence_line(rep, tf, side, state):
    """The Risk Box line 'MTF Confluence: Strong (15m UP agrees with LONG)'. Plain words when nothing is known."""
    p = ((rep or {}).get("pairs") or {}).get("%s>%s" % (tf, TF.higher_of(tf)))
    if not p or state is None:
        return "MTF Confluence: not studied yet"
    agree = (state == "UP") == (side == "LONG")
    word = ("Strong" if p["label"] == "STRONG" else "Medium" if p["label"] == "MEDIUM" else "Weak") if agree else "Against"
    return "MTF Confluence: %s (%s %s %s %s)" % (word, p["higher_tf"], state, "agrees with" if agree else "is against", side)


def load_runs(con, cap):
    """[(symbol, gap-free run of real 5m candles)] with MIN_RUN+ candles (gaps are cut, never bridged)."""
    out = []
    for sym in F.symbols(con, "5m", cap):
        good, _bad = D.clean_candles(D.candles_from_store(con, sym, TF.BASE, 0, 2 ** 31), TF.BASE)
        out.extend((sym, r) for r in SF.runs(good, TF.BASE) if len(r) >= MIN_RUN)
    return out


def build(d, cap=F.MAX_COINS, since_days=None, now=None):
    """The whole study from the saved 5m candles. Never raises on missing data: {ready: False, note}."""
    now = int(time.time() if now is None else now)
    head = {"version": VERSION, "paper_only": True, "ready": False, "plan": {k: list(v) for k, v in PLAN.items()}}
    con = F.open_ro(d)
    if con is None:
        return dict(head, note="No market store yet: no candles are saved.")
    try:
        runs = load_runs(con, cap)
    finally:
        con.close()
    rows, coins, skipped = analyse(runs, 0 if since_days is None else now - int(since_days * 86400))
    if not any(rows.values()):
        return dict(head, note="Not enough gap-free 5m candles (a run needs %d+ candles)." % MIN_RUN, skipped=skipped)
    return dict(head, ready=True, coins=len(coins), skipped=skipped, hold_candles=IP.HOLD, target_r=IP.TARGET_R, **report(rows))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--cap", type=int, default=F.MAX_COINS)
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--save", action="store_true", help="also write v2_sniper_mtf.json in the data folder")
    a = ap.parse_args(argv)
    res = build(a.data, a.cap, a.since_days)
    if a.save and res.get("ready"):
        res["saved"] = F.write_json(a.data, FILE, res)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
