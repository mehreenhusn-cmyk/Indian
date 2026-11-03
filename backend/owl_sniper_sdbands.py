"""owl_sniper_sdbands.py - OwlSniper SD BANDS support / resistance learning (Part 25 / FILE 16, group G4). READ ONLY: the market store is opened read-only, no network, no order code.
NAME NOTE (owner, 3 Nov 2026): these are the STANDARD DEVIATION (SD) bands drawn on the MAIN chart, SMA +- 1 / 2 / 3 x SD (SMA and SD length 200, population SD). The old plan name "HD Bands" meant these. No other band exists.
The owner's question (MASTER_PROMPT 4.3B-B): "When does price respect an SD band as support, when as resistance, when is the reaction clean and when does it fail?"
This file OBSERVES and MEASURES that. No hard-coded trading rule. It reuses the outcome rule and the verdict rule of Part 23 (owl_sniper_ind_pairs.py) and the helpers of Part 24 (owl_sniper_zsma.py), so all answers are comparable.
BANDS (read on a CLOSED candle i, no look-ahead):  LOWER k = SMA - k x SD,  UPPER k = SMA + k x SD,  k = 1, 2, 3.   UNIT = average candle range in % of price over the last 20 candles. TOUCH zone = 0.25 UNIT around the band.
EVENT KINDS, per band k (the first candle where a kind starts; a price that hugs a band for 10 candles is ONE event):
  LOWERk_HELD   the last close was ABOVE the lower band, this candle's LOW reached the touch zone, and it CLOSED on or above the band   (support held; natural decision: LONG)
  LOWERk_BROKE  the last close was above the lower band, this candle CLOSED below it                                                 (support broke; natural decision: SHORT)
  UPPERk_HELD   the last close was BELOW the upper band, this candle's HIGH reached the touch zone, and it CLOSED on or below the band  (resistance held; natural decision: SHORT)
  UPPERk_BROKE  the last close was below the upper band, this candle CLOSED above it                                                (resistance broke; natural decision: LONG)
  12 kinds x 3 regimes (ALL / TRENDING / SIDEWAYS from the engine's volatility index) = 36 states, so "clean reaction vs fail, in which condition" is measured, not assumed.
OUTCOME + VERDICT: exactly Part 23: entry = OPEN of the next candle, 1R = UNIT x price, +2R target, -1R stop, 30 candles, stop first; BASELINE = any candle; independent cases only (thinned, per coin 30 candles apart);
  NOT_ENOUGH_DATA below 30 independent cases (15 per half) / STEADY (both halves, 60% of coins, lift above 2 x standard error) / SOMETIMES (not proven, never used) / NO_PAY. Both decisions are judged; the natural one is shown first. use_in_sniper = true ONLY for STEADY.
REACTION: reach_1r_pct (share of events that moved 1R the right way before the stop), fav_r (average best move, R), median candles + minutes. The 3 SD bands are rare: many of their states will say NOT_ENOUGH_DATA, and that is the honest answer.
ANSWER per kind: STEADY = "ALWAYS-like", SOMETIMES = "only SOMETIMES", NO_PAY = "NO", NOT_ENOUGH_DATA = "UNKNOWN". best_support = the LOWERk_HELD with the best verdict / lift, best_resistance = the same for UPPERk_HELD (None if none beat a random candle).
72 checks are made (36 states x 2 decisions): a STEADY by luck is possible, trust it more when it stays STEADY on a later run and on the other interval. Combos with Z-SMA and TSI are FILE 17, not here.
Run (Termux, optional):  python3 backend/owl_sniper_sdbands.py [--data DIR] [--tf 5m|15m] [--cap 40] [--since-days N] [--kind NAME] [--save]  -> JSON (--save also writes v2_sniper_sdbands.json). Needs owl_sniper_ind_pairs.py (Part 23) and owl_sniper_zsma.py (Part 24) next to it."""
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
import owl_sniper_zsma as Z

VERSION = "owl_sniper_sdbands 1 (Part 25)"
FILE = "v2_sniper_sdbands.json"
BANDS, TOUCH_U = (1, 2, 3), 0.25
KINDS = tuple("%s%d_%s" % (s, k, w) for k in BANDS for s in ("LOWER", "UPPER") for w in ("HELD", "BROKE"))
REGIMES = Z.REGIMES
ANSWER = Z.ANSWER


def natural(kind):
    """The decision the kind's name points to: support held / resistance broke = LONG, resistance held / support broke = SHORT."""
    return "LONG" if kind.startswith("LOWER") == kind.endswith("HELD") else "SHORT"


def label(kind):
    """Plain words for a kind, e.g. LOWER2_HELD -> 'Price above the lower 2 SD band touched it and stayed above (support)'."""
    low, k, w = kind.startswith("LOWER"), kind[5], kind.split("_")[1]
    name, here, there = ("lower %s SD band" % k, "above", "below") if low else ("upper %s SD band" % k, "below", "above")
    if w == "HELD":
        return "Price %s the %s touched it and stayed %s (%s)" % (here, name, here, "support" if low else "resistance")
    return "Price %s the %s closed %s it (%s)" % (here, name, there, "support broke" if low else "resistance broke")


def kinds_at(S, i, u):
    """The set of band event kinds that are TRUE on closed candle i. Needs SMA and SD at i and i-1."""
    m, s, c = S["sma"], S["sd"], S["c"]
    if None in (m[i], s[i], m[i - 1], s[i - 1]):
        return set()
    out, z = set(), TOUCH_U * u * c[i]
    for k in BANDS:
        lo, lo0, up, up0 = m[i] - k * s[i], m[i - 1] - k * s[i - 1], m[i] + k * s[i], m[i - 1] + k * s[i - 1]
        if c[i - 1] > lo0:
            if c[i] < lo:
                out.add("LOWER%d_BROKE" % k)
            elif S["l"][i] <= lo + z:
                out.add("LOWER%d_HELD" % k)
        if c[i - 1] < up0:
            if c[i] > up:
                out.add("UPPER%d_BROKE" % k)
            elif S["h"][i] >= up - z:
                out.add("UPPER%d_HELD" % k)
    return out


def analyse(runs, cfg, since_ts=0):
    """runs = [(symbol, gap-free candles)] -> (events {'KIND|REGIME': [row]}, base [row], coins, skipped). row = (ts, symbol, long result, short result) as in Part 23."""
    ev, base, coins, skipped = {}, [], set(), {"short_run": 0, "bad_candles": 0}
    for sym, run in runs:
        try:
            S = E.build_features(run, cfg)
        except (ValueError, KeyError, IndexError, TypeError):
            skipped["bad_candles"] += 1
            continue
        lo, hi = max(E.warmup_end(S), IP.UNIT_WIN, IP.LOOK) + 1, S["n"] - IP.HOLD - 2
        if hi - lo < 50:
            skipped["short_run"] += 1
            continue
        coins.add(sym)
        prev = set()
        for i in range(lo, hi + 1):
            u = IP.unit_of(S, i)
            if S["t"][i] < since_ts or u <= 0:
                prev = set()
                continue
            entry = S["o"][i + 1]
            row = (S["t"][i], sym, IP.walk(S, i, "LONG", entry, u * entry), IP.walk(S, i, "SHORT", entry, u * entry))
            base.append(row)
            now = kinds_at(S, i, u)
            rg = Z.regime_of(S, i)
            for k in now - prev:
                ev.setdefault("%s|ALL" % k, []).append(row)
                if rg:
                    ev.setdefault("%s|%s" % (k, rg), []).append(row)
            prev = now
    return ev, base, coins, skipped


def headline(kind, st):
    nat = natural(kind)
    r = st["long" if nat == "LONG" else "short"]
    if r["verdict"] == "NOT_ENOUGH_DATA":
        return "%s: %d events, but 30 independent cases are needed (15 in each half). No verdict yet." % (label(kind), st["n"])
    return "%s -> %s: %s. %d independent cases, win %.0f%%, moved 1R the right way in %.0f%%, average best move %.2fR, expected %+.2fR (%+.2fR vs any candle), median %d candles." % (
        label(kind), nat, ANSWER[r["verdict"]], r["n_independent"], r["win_pct"], r["reach_1r_pct"], r["fav_r"], r["exp_r"], r["lift"], r["median_candles"])


def report(ev, base, step):
    """Events + baseline -> one block per kind (headline, answer, strongest / weakest regime, one state per regime), best support / best resistance band, verdict counts."""
    ts = sorted(r[0] for r in base)
    cut = ts[int(len(ts) * IP.TRAIN_FRAC)] if ts else 0
    tr, te = [r for r in base if r[0] < cut], [r for r in base if r[0] >= cut]
    bl = {k: {"all": IP.mean_r(base, k) or 0.0, "tr": IP.mean_r(tr, k) or 0.0, "te": IP.mean_r(te, k) or 0.0} for k in (2, 3)}
    kinds, count = {}, {v: 0 for v in IP.RANK}
    for kind in KINDS:
        states, nk = [], "long" if natural(kind) == "LONG" else "short"
        for rg in REGIMES:
            rows = ev.get("%s|%s" % (kind, rg), [])
            res = {"LONG": IP.judge(rows, 2, cut, bl[2], IP.HOLD * step), "SHORT": IP.judge(rows, 3, cut, bl[3], IP.HOLD * step)}
            for d, k in (("LONG", 2), ("SHORT", 3)):
                res[d]["reach_1r_pct"] = Z.reach_1r(rows, k)
            top = max(res, key=lambda x: (IP.RANK[res[x]["verdict"]], res[x].get("lift", -9.0)))
            best = top if IP.RANK[res[top]["verdict"]] >= 1 else "NONE"
            verdict = res[top]["verdict"] if best != "NONE" else ("NOT_ENOUGH_DATA" if all(r["verdict"] == "NOT_ENOUGH_DATA" for r in res.values()) else "NO_PAY")
            count[verdict] += 1
            states.append({"state": "%s|%s" % (kind, rg), "regime": rg, "n": len(rows), "best": best, "verdict": verdict, "use_in_sniper": verdict == "STEADY", "avoid": [x for x in res if res[x].get("avoid")],
                           "plain": IP.plain("%s in %s" % (kind, rg), len(rows), best, res, step), "long": res["LONG"], "short": res["SHORT"]})
        reg = [(s[nk].get("lift"), s["regime"]) for s in states[1:] if s[nk].get("n_independent", 0) >= IP.MIN_N]
        kinds[kind] = {"natural_decision": natural(kind), "answer": ANSWER[states[0][nk]["verdict"]], "headline": headline(kind, states[0]),
                       "strongest_regime": max(reg)[1] if len(reg) > 1 else None, "weakest_regime": min(reg)[1] if len(reg) > 1 else None, "states": states}

    return {"kinds": kinds, "best_support": _best(kinds, "LOWER"), "best_resistance": _best(kinds, "UPPER"), "verdict_counts": count,
            "baseline_exp_r": {"LONG": round(bl[2]["all"], 3), "SHORT": round(bl[3]["all"], 3)}, "split_ts": cut, "checks_made": 2 * len(KINDS) * len(REGIMES)}


def _best(kinds, side):
    """The HELD kind of one side (LOWER = support, UPPER = resistance) with the best verdict, then lift. None when no band beat a random candle."""
    ok = []
    for k in KINDS:
        if k.startswith(side) and k.endswith("HELD"):
            r = kinds[k]["states"][0]["long" if natural(k) == "LONG" else "short"]
            if IP.RANK[r["verdict"]] >= 1:
                ok.append((IP.RANK[r["verdict"]], r.get("lift", -9.0), k))
    return max(ok)[2] if ok else None


def build(d, tf="5m", cap=F.MAX_COINS, since_days=None, now=None, only=None):
    """The whole study from the saved candles. Never raises on missing data: {ready: False, note}."""
    TF.check(tf)
    now = int(time.time() if now is None else now)
    head = {"version": VERSION, "interval": tf, "paper_only": True, "ready": False, "bands": list(BANDS)}
    con = F.open_ro(d)
    if con is None:
        return dict(head, note="No market store yet: no candles are saved.")
    try:
        runs = IP.load_runs(con, tf, cap)
    finally:
        con.close()
    cfg, src = IP.load_cfg(d, tf)
    ev, base, coins, skipped = analyse(runs, cfg, 0 if since_days is None else now - int(since_days * 86400))
    if not base:
        return dict(head, note="Not enough gap-free candles (a run needs %d+ candles)." % IP.MIN_RUN, skipped=skipped, cfg_source=src)
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
    ap.add_argument("--save", action="store_true", help="also write v2_sniper_sdbands.json in the data folder")
    a = ap.parse_args(argv)
    res = build(a.data, a.tf, a.cap, a.since_days, only=a.kind)
    if a.save and res.get("ready"):
        res["saved"] = F.write_json(a.data, FILE, res)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
