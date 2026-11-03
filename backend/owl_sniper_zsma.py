"""owl_sniper_zsma.py - OwlSniper Z-SMA SUPPORT / RESISTANCE learning (Part 24 / FILE 15, group G4). READ ONLY: the market store is opened read-only, no network, no order code.
The owner's question (MASTER_PROMPT 4.3B-A): "Price above the Z-SMA: does it act as SUPPORT? Price below: does it act as RESISTANCE? How often, how big is the reaction, how long, and in which volatility regime is it strongest or weakest?"
This file OBSERVES and MEASURES that. No hard-coded trading rule: it only counts what happened after each touch. It reuses the outcome rule and the verdict rule of Part 23 (owl_sniper_ind_pairs.py), so all answers are comparable.
THE LINE: Z-SMA = SMA(Z-score, 200) (the black line in the Z pane). Z = (close - SMA) / SD, so the SAME line on the price pane is  LINE = SMA + Z-SMA x SD  (the price where Z would equal its Z-SMA). Every number is read on a CLOSED candle i (no look-ahead).
  UNIT = average candle range in % of price over the last 20 candles (same as Part 23). TOUCH zone = 0.25 UNIT around the line.
EVENT KINDS (the first candle where a kind starts; a price that hugs the line for 10 candles is ONE event):
  SUPPORT_HELD      the last close was ABOVE the line, this candle's LOW reached the touch zone, and it CLOSED on or above the line      (natural decision: LONG)
  SUPPORT_BROKE     the last close was above the line, this candle CLOSED below it                                                       (natural decision: SHORT)
  RESISTANCE_HELD   the last close was BELOW the line, this candle's HIGH reached the touch zone, and it CLOSED on or below the line     (natural decision: SHORT)
  RESISTANCE_BROKE  the last close was below the line, this candle CLOSED above it                                                       (natural decision: LONG)
  Each kind is also cut by regime (TRENDING / SIDEWAYS from the engine's volatility index; ALL = every regime), so "strongest / weakest regime" is measured, not assumed.
OUTCOME + VERDICT: exactly Part 23: entry = OPEN of the next candle, 1R = UNIT x price, +2R target, -1R stop, 30 candles, stop first; BASELINE = any candle; independent cases only (thinned, per coin at least 30 candles apart);
  NOT_ENOUGH_DATA below 30 independent cases (15 per half) / STEADY (both halves, 60% of coins, lift above 2 x standard error) / SOMETIMES (not proven, never used) / NO_PAY.
  Both decisions LONG and SHORT are judged for every state; the natural one is shown first. use_in_sniper = true ONLY for STEADY.
REACTION (the owner's "how big, how long"): for the natural decision of a state, reach_1r_pct = share of events where price moved at least 1R the right way before the stop, fav_r = average best move (R), median_candles + minutes = time to the result.
ANSWER per kind: STEADY = "ALWAYS-like (holds in both halves)", SOMETIMES = "only SOMETIMES", NO_PAY = "NO", NOT_ENOUGH_DATA = "UNKNOWN". 'strongest_regime' = the regime with the best lift among those with 30+ independent cases (None if none).
A run needs 450+ gap-free candles (the Z-SMA needs about 400 to warm up); shorter runs are counted in skipped.short_run. 24 states x 2 decisions = 48 checks: one STEADY by luck is possible, trust it more when it stays STEADY on a later run and on the other interval.
Run (Termux, optional):  python3 backend/owl_sniper_zsma.py [--data DIR] [--tf 5m|15m] [--cap 40] [--since-days N] [--kind NAME] [--save]  -> JSON (--save also writes v2_sniper_zsma.json). Needs owl_sniper_ind_pairs.py (Part 23) next to it."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_engine as E
import owl_sniper_feed as F
import owl_sniper_ind_pairs as IP
import owl_sniper_tf as TF
import v2_defs as D
import v2_setup_finder as SF

VERSION = "owl_sniper_zsma 1 (Part 24)"
FILE = "v2_sniper_zsma.json"
ZSMA_LEN, TOUCH_U, MIN_RUN = 200, 0.25, 450
KINDS = ("SUPPORT_HELD", "SUPPORT_BROKE", "RESISTANCE_HELD", "RESISTANCE_BROKE")
REGIMES = ("ALL", "TRENDING", "SIDEWAYS")
NATURAL = {"SUPPORT_HELD": "LONG", "SUPPORT_BROKE": "SHORT", "RESISTANCE_HELD": "SHORT", "RESISTANCE_BROKE": "LONG"}
LABEL = {"SUPPORT_HELD": "Price above the Z-SMA line touched it and stayed above (support)", "SUPPORT_BROKE": "Price above the Z-SMA line closed below it (support broke)",
         "RESISTANCE_HELD": "Price below the Z-SMA line touched it and stayed below (resistance)", "RESISTANCE_BROKE": "Price below the Z-SMA line closed above it (resistance broke)"}
ANSWER = {"STEADY": "ALWAYS-like (holds in both halves)", "SOMETIMES": "only SOMETIMES (not proven)", "NO_PAY": "NO (no better than a random candle)", "NOT_ENOUGH_DATA": "UNKNOWN (not enough cases yet)"}


def line_of(S, length=ZSMA_LEN):
    """The Z-SMA line on the PRICE pane for every candle: SMA + SMA(Z, length) x SD. None where any part is not ready (never a made-up number)."""
    zs = E.sma_any(S["z"], length)
    return [None if zs[i] is None or S["sma"][i] is None or S["sd"][i] is None else S["sma"][i] + zs[i] * S["sd"][i] for i in range(S["n"])]


def kind_at(S, L, i, u):
    """The event kind of closed candle i (or None). Needs the line at i and i-1."""
    if L[i] is None or L[i - 1] is None:
        return None
    c, z = S["c"], TOUCH_U * u * S["c"][i]
    if c[i - 1] > L[i - 1]:
        if c[i] < L[i]:
            return "SUPPORT_BROKE"
        if S["l"][i] <= L[i] + z:
            return "SUPPORT_HELD"
    elif c[i - 1] < L[i - 1]:
        if c[i] > L[i]:
            return "RESISTANCE_BROKE"
        if S["h"][i] >= L[i] - z:
            return "RESISTANCE_HELD"
    return None


def regime_of(S, i):
    ok = S["side_ok"][i]
    return None if ok is None else "TRENDING" if ok else "SIDEWAYS"


def analyse(runs, cfg, since_ts=0):
    """runs = [(symbol, gap-free candles)] -> (events {'KIND|REGIME': [row]}, base [row], coins, skipped). row = (ts, symbol, long result, short result) as in Part 23."""
    ev, base, coins, skipped = {}, [], set(), {"short_run": 0, "bad_candles": 0}
    for sym, run in runs:
        try:
            S = E.build_features(run, cfg)
        except (ValueError, KeyError, IndexError, TypeError):
            skipped["bad_candles"] += 1
            continue
        L = line_of(S)
        first = next((i for i in range(S["n"]) if L[i] is not None), S["n"])
        lo, hi = max(E.warmup_end(S), first, IP.UNIT_WIN, IP.LOOK) + 1, S["n"] - IP.HOLD - 2
        if hi - lo < 50:
            skipped["short_run"] += 1
            continue
        coins.add(sym)
        prev = None
        for i in range(lo, hi + 1):
            u = IP.unit_of(S, i)
            if S["t"][i] < since_ts or u <= 0:
                prev = None
                continue
            entry = S["o"][i + 1]
            row = (S["t"][i], sym, IP.walk(S, i, "LONG", entry, u * entry), IP.walk(S, i, "SHORT", entry, u * entry))
            base.append(row)
            k = kind_at(S, L, i, u)
            if k is not None and k != prev:
                ev.setdefault("%s|ALL" % k, []).append(row)
                rg = regime_of(S, i)
                if rg:
                    ev.setdefault("%s|%s" % (k, rg), []).append(row)
            prev = k
    return ev, base, coins, skipped


def reach_1r(rows, k):
    """Share (%) of events where the price moved at least 1R the right way before the result (the bounce / the follow-through)."""
    return round(100.0 * sum(1 for r in rows if r[k][2] >= 1.0) / len(rows), 1) if rows else None


def headline(kind, row):
    """ONE plain sentence for a kind, from its ALL-regime state."""
    nat = NATURAL[kind]
    r = row["long" if nat == "LONG" else "short"]
    if r["verdict"] == "NOT_ENOUGH_DATA":
        return "%s: %d events, but 30 independent cases are needed (15 in each half). No verdict yet." % (LABEL[kind], row["n"])
    return "%s -> %s: %s. %d independent cases, win %.0f%%, moved 1R the right way in %.0f%%, average best move %.2fR, expected %+.2fR (%+.2fR vs any candle), median %d candles." % (
        LABEL[kind], nat, ANSWER[r["verdict"]], r["n_independent"], r["win_pct"], r["reach_1r_pct"], r["fav_r"], r["exp_r"], r["lift"], r["median_candles"])


def report(ev, base, step):
    """Events + baseline -> one block per kind (headline, answer, strongest regime, one state per regime), plus the verdict counts."""
    ts = sorted(r[0] for r in base)
    cut = ts[int(len(ts) * IP.TRAIN_FRAC)] if ts else 0
    tr, te = [r for r in base if r[0] < cut], [r for r in base if r[0] >= cut]
    bl = {k: {"all": IP.mean_r(base, k) or 0.0, "tr": IP.mean_r(tr, k) or 0.0, "te": IP.mean_r(te, k) or 0.0} for k in (2, 3)}
    kinds, count = {}, {v: 0 for v in IP.RANK}
    for kind in KINDS:
        states = []
        for rg in REGIMES:
            rows = ev.get("%s|%s" % (kind, rg), [])
            res = {"LONG": IP.judge(rows, 2, cut, bl[2], IP.HOLD * step), "SHORT": IP.judge(rows, 3, cut, bl[3], IP.HOLD * step)}
            for d, k in (("LONG", 2), ("SHORT", 3)):
                res[d]["reach_1r_pct"] = reach_1r(rows, k)
            top = max(res, key=lambda x: (IP.RANK[res[x]["verdict"]], res[x].get("lift", -9.0)))
            best = top if IP.RANK[res[top]["verdict"]] >= 1 else "NONE"
            verdict = res[top]["verdict"] if best != "NONE" else ("NOT_ENOUGH_DATA" if all(r["verdict"] == "NOT_ENOUGH_DATA" for r in res.values()) else "NO_PAY")
            count[verdict] += 1
            states.append({"state": "%s|%s" % (kind, rg), "regime": rg, "n": len(rows), "best": best, "verdict": verdict, "use_in_sniper": verdict == "STEADY",
                           "avoid": [x for x in res if res[x].get("avoid")], "plain": IP.plain("%s in %s" % (kind, rg), len(rows), best, res, step), "long": res["LONG"], "short": res["SHORT"]})
        allrow = states[0]
        nat = allrow["long" if NATURAL[kind] == "LONG" else "short"]
        reg = [(s[("long" if NATURAL[kind] == "LONG" else "short")].get("lift"), s["regime"]) for s in states[1:] if s["long"].get("n_independent", 0) >= IP.MIN_N and s["short"].get("n_independent", 0) >= IP.MIN_N]
        kinds[kind] = {"natural_decision": NATURAL[kind], "answer": ANSWER[nat["verdict"]], "headline": headline(kind, allrow),
                       "strongest_regime": max(reg)[1] if len(reg) > 1 else None, "weakest_regime": min(reg)[1] if len(reg) > 1 else None, "states": states}
    return {"kinds": kinds, "verdict_counts": count, "baseline_exp_r": {"LONG": round(bl[2]["all"], 3), "SHORT": round(bl[3]["all"], 3)}, "split_ts": cut, "checks_made": 2 * len(KINDS) * len(REGIMES)}


def load_runs(con, tf, cap):
    """[(symbol, gap-free run)] with MIN_RUN+ candles (gaps are cut, never bridged)."""
    out = []
    for sym in F.symbols(con, tf, cap):
        good, _bad = D.clean_candles(D.candles_from_store(con, sym, TF.base(tf), 0, 2 ** 31), TF.base(tf))
        for r in SF.runs(good, TF.base(tf)):
            a = TF.aggregate(r, tf)
            if len(a) >= MIN_RUN:
                out.append((sym, a))
    return out


def build(d, tf="5m", cap=F.MAX_COINS, since_days=None, now=None, only=None):
    """The whole study from the saved candles. Never raises on missing data: {ready: False, note}."""
    TF.check(tf)
    now = int(time.time() if now is None else now)
    head = {"version": VERSION, "interval": tf, "paper_only": True, "ready": False, "zsma_len": ZSMA_LEN}
    con = F.open_ro(d)
    if con is None:
        return dict(head, note="No market store yet: no candles are saved.")
    try:
        runs = load_runs(con, tf, cap)
    finally:
        con.close()
    cfg, src = IP.load_cfg(d, tf)
    ev, base, coins, skipped = analyse(runs, cfg, 0 if since_days is None else now - int(since_days * 86400))
    if not base:
        return dict(head, note="Not enough gap-free candles (a run needs %d+ candles)." % MIN_RUN, skipped=skipped, cfg_source=src)
    rep = report(ev, base, TF.step(tf))
    if only:
        rep["kinds"] = {k: v for k, v in rep["kinds"].items() if k == only}
    return dict(head, ready=True, cfg_source=src, coins=len(coins), candles_checked=len(base), skipped=skipped, hold_candles=IP.HOLD, target_r=IP.TARGET_R, **rep)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--tf", default="5m", choices=TF.SUPPORTED)
    ap.add_argument("--cap", type=int, default=F.MAX_COINS)
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--kind", default=None, choices=KINDS)
    ap.add_argument("--save", action="store_true", help="also write v2_sniper_zsma.json in the data folder")
    a = ap.parse_args(argv)
    res = build(a.data, a.tf, a.cap, a.since_days, only=a.kind)
    if a.save and res.get("ready"):
        res["saved"] = F.write_json(a.data, FILE, res)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
