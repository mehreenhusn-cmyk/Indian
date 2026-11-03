"""owl_sniper_ind_pairs.py - OwlSniper INDICATOR-vs-PRICE learning (Part 23 / FILE 14, group G4). READ ONLY: the market store is opened read-only, no network, no order code.
The owner's question (MASTER_PROMPT_UPDATE 4.3): "What does the lower pane (indicator) say, what does the upper pane (price) say. Is it ALWAYS like that, or only SOMETIMES? When it appears, which decision paid?"
This file OBSERVES and MEASURES that. No hard-coded trading rule: it only counts what happened after each state.
STATE PAIRS (an indicator state next to a price state, read on a CLOSED candle i; LOOK = 3 candles back for the moves):
  z_vs_price      Z-Score going UP / DOWN / FLAT  next to  price going UP / DOWN / FLAT   (Z falling while price rises = divergence)
  tsi_vs_price    TSI histogram POS / NEG and RISING / FALLING  next to  price direction
  cloud_vs_price  EMA cloud UP / DOWN (fast EMA above / below slow)  next to  price ABOVE / INSIDE / BELOW the cloud
  zone_vs_price   Z-Score LEVEL (M2 < -2, M1 < -1, 0 = -1..1, P1 <= 2, P2 > 2)  next to  price direction
  Price direction: UP / DOWN when the move over LOOK candles is more than 0.5 UNIT, else FLAT. UNIT = the average candle range in % of the last 20 candles (no look-ahead). Z moves: more than 0.15 Z.
  (Z-SMA and HD Bands as support / resistance are FILE 15 and 16, not here.)
EVENT = the first candle where a pair enters a state (a state that stays for 10 candles is ONE event, not ten, so cases are not counted twice).
OUTCOME of an event, for BOTH decisions LONG and SHORT (same rule for every state, so states can be compared):
  entry = OPEN of the next candle (no free fill at the signal close). 1R = UNIT x entry price. Target +2R, stop -1R, at most HOLD = 30 candles (same as the Sniper's time barrier).
  Stop and target in the same candle = STOP first (the careful side). Time out = the move at the last close, cut to -1R..+2R. R is before fees (the same for all states, so the ranking is fair).
  Also kept: candles to the result (time), best move for the trade (fav, in R) and worst move against it (adv, in R) before the result.
BASELINE = the same outcome for EVERY candle (any state). A state only counts when it beats that baseline (lift = expected R of the state - expected R of any candle), so a rising market is not called an edge.
INDEPENDENT CASES: events of one coin that sit closer than HOLD candles share the same future candles, so they are ONE case, not many. Events are thinned (per coin, at least HOLD candles apart)
  and only the thinned cases (n_independent) count for the minimum and for the noise margin. Without this a random market shows fake "edges".
VERDICT per decision (never a number below 30 independent cases):
  NOT_ENOUGH_DATA  fewer than 30 independent cases, or fewer than 15 in the old (train) half or in the new (test) half
  STEADY           expected R > 0 AND lift > 0 in BOTH halves (old 60% of time, new 40%) AND at least 60% of the coins (with 5+ events) beat the baseline
                   AND the lift is still above 0 after a 2 x standard-error noise margin  ("it holds, and it is not just luck")
  SOMETIMES        expected R > 0 and lift > 0 over all, but one half fails, or the coins disagree, or the lift is inside the noise  ("only sometimes / not proven")
  NO_PAY           everything else.  'avoid' lists a decision that LOST vs the baseline in both halves (losses teach "do not take").
  84 checks are made (42 states x 2 decisions), so one or two STEADY by luck are possible: trust a state more when it stays STEADY on a later run and on the other interval.
A state's answer = the better decision (best = LONG / SHORT / NONE) with 'plain' = one sentence. use_in_sniper is true ONLY for STEADY (SOMETIMES is never used as a rule). Pure Python (no numpy / pandas).
Run (Termux, optional):  python3 backend/owl_sniper_ind_pairs.py [--data DIR] [--tf 5m|15m] [--cap 40] [--since-days N] [--pair NAME] [--save]  -> JSON (--save also writes v2_sniper_ind_pairs.json)."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_engine as E
import owl_sniper_feed as F
import owl_sniper_tf as TF
import v2_defs as D
import v2_setup_finder as SF

VERSION = "owl_sniper_ind_pairs 1 (Part 23)"
FILE = "v2_sniper_ind_pairs.json"
PAIRS = ("z_vs_price", "tsi_vs_price", "cloud_vs_price", "zone_vs_price")
LOOK, UNIT_WIN, HOLD, TARGET_R = 3, 20, E.MAX_HOLD, 2.0
PRICE_MOVE_U, Z_MOVE = 0.5, 0.15
MIN_N, MIN_HALF, MIN_COIN_N, MIN_COINS, STEADY_COINS, TRAIN_FRAC, MIN_RUN, SE_MULT = 30, 15, 5, 3, 0.6, 0.6, 300, 2.0
RANK = {"STEADY": 2, "SOMETIMES": 1, "NO_PAY": 0, "NOT_ENOUGH_DATA": -1}


def load_cfg(d, tf):
    """The settings the live Sniper uses (v2_sniper_model.json -> model.config), else defaults. -> (cfg, 'model' | 'defaults')."""
    try:
        c = ((F.read_json(d, TF.files(tf)[0]) or {}).get("model") or {}).get("config")
    except Exception:
        c = None
    return (dict(E.DEFAULTS, **c), "model") if isinstance(c, dict) else (dict(E.DEFAULTS), "defaults")


def unit_of(S, i):
    """UNIT = average candle range in % of price over the last UNIT_WIN candles, up to and including candle i (no look-ahead)."""
    a = max(0, i - UNIT_WIN + 1)
    return sum((S["h"][j] - S["l"][j]) / S["c"][j] for j in range(a, i + 1)) / (i + 1 - a)


def states(S, i, u):
    """{pair: state name} at closed candle i."""
    c, z, hs = S["c"], S["z"], S["hist"]
    mv = (c[i] - c[i - LOOK]) / (u * c[i])
    pd = "UP" if mv > PRICE_MOVE_U else "DOWN" if mv < -PRICE_MOVE_U else "FLAT"
    dz = z[i] - z[i - LOOK]
    zd = "UP" if dz > Z_MOVE else "DOWN" if dz < -Z_MOVE else "FLAT"
    zl = z[i]
    zb = "M2" if zl < -2 else "M1" if zl < -1 else "0" if zl <= 1 else "P1" if zl <= 2 else "P2"
    ef, es = S["ema_f"][i], S["ema_s"][i]
    pos = "ABOVE" if c[i] > max(ef, es) else "BELOW" if c[i] < min(ef, es) else "INSIDE"
    return {"z_vs_price": "Z_%s|PRICE_%s" % (zd, pd),
            "tsi_vs_price": "HIST_%s_%s|PRICE_%s" % ("POS" if hs[i] > 0 else "NEG", "RISING" if hs[i] > hs[i - 1] else "FALLING", pd),
            "cloud_vs_price": "CLOUD_%s|PRICE_%s" % ("UP" if ef > es else "DOWN", pos),
            "zone_vs_price": "ZLEVEL_%s|PRICE_%s" % (zb, pd)}


def walk(S, i, side, entry, risk):
    """One decision after candle i: (R, candles to result, fav R, adv R). Candles i+1 .. i+HOLD are read (the caller keeps i + HOLD < n)."""
    d = 1 if side == "LONG" else -1
    fav = adv = 0.0
    for k in range(1, HOLD + 1):
        j = i + k
        up, dn = (S["h"][j] - entry) / risk, (entry - S["l"][j]) / risk
        f, a = (up, dn) if d > 0 else (dn, up)
        if a >= 1.0:                                   # stop first, also when the target was touched in the same candle
            return -1.0, k, fav, 1.0
        fav, adv = max(fav, f), max(adv, a)
        if f >= TARGET_R:
            return TARGET_R, k, fav, adv
    r = d * (S["c"][i + HOLD] - entry) / risk
    return max(-1.0, min(TARGET_R, r)), HOLD, fav, adv


def analyse(runs, cfg, since_ts=0):
    """runs = [(symbol, gap-free candle list)] -> (events {pair: {state: [row]}}, base [row], coins, skipped). row = (ts, symbol, long result, short result)."""
    ev, base, coins, skipped = {p: {} for p in PAIRS}, [], set(), {"short_run": 0, "bad_candles": 0}
    for sym, run in runs:
        try:
            S = E.build_features(run, cfg)
        except (ValueError, KeyError, IndexError, TypeError):
            skipped["bad_candles"] += 1
            continue
        lo, hi = max(E.warmup_end(S), UNIT_WIN, LOOK) + 1, S["n"] - HOLD - 2
        if hi - lo < 50:
            skipped["short_run"] += 1
            continue
        coins.add(sym)
        prev = None
        for i in range(lo, hi + 1):
            u = unit_of(S, i)
            if S["t"][i] < since_ts or u <= 0:
                prev = None
                continue
            entry = S["o"][i + 1]
            row = (S["t"][i], sym, walk(S, i, "LONG", entry, u * entry), walk(S, i, "SHORT", entry, u * entry))
            base.append(row)
            st = states(S, i, u)
            if prev is not None:
                for p, s in st.items():
                    if prev[p] != s:
                        ev[p].setdefault(s, []).append(row)
            prev = st
    return ev, base, coins, skipped


def mean_r(rows, k):
    return sum(r[k][0] for r in rows) / len(rows) if rows else None


def stats(rows, k):
    n = len(rows)
    if not n:
        return {"n": 0}
    ts = sorted(r[k][1] for r in rows)
    return {"n": n, "win_pct": round(100.0 * sum(1 for r in rows if r[k][0] > 0) / n, 1), "exp_r": round(mean_r(rows, k), 3), "median_candles": ts[n // 2],
            "fav_r": round(sum(r[k][2] for r in rows) / n, 2), "adv_r": round(sum(r[k][3] for r in rows) / n, 2)}


def thin(rows, gap):
    """Independent cases: per coin keep an event only when it is at least `gap` seconds after the last kept one (HOLD candles = no shared future)."""
    last, keep = {}, []
    for r in sorted(rows, key=lambda x: (x[1], x[0])):
        if r[0] - last.get(r[1], -10 ** 12) >= gap:
            last[r[1]] = r[0]
            keep.append(r)
    return keep


def judge(rows, k, cut, bl, gap):
    """The answer for ONE decision (k = 2 LONG, 3 SHORT) of one state. bl = {'all','tr','te'} baseline expected R of this decision. gap = HOLD candles in seconds."""
    tr, te = [r for r in rows if r[0] < cut], [r for r in rows if r[0] >= cut]
    ind = thin(rows, gap)
    out = stats(rows, k)
    out["n_independent"] = len(ind)
    if len(ind) < MIN_N or sum(1 for r in ind if r[0] < cut) < MIN_HALF or sum(1 for r in ind if r[0] >= cut) < MIN_HALF:
        out["verdict"] = "NOT_ENOUGH_DATA"
        return out
    ea, et, ee = mean_r(rows, k), mean_r(tr, k), mean_r(te, k)
    xs = [r[k][0] for r in ind]
    mu = sum(xs) / len(xs)
    se = (sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5 / len(xs) ** 0.5
    out.update(lift=round(ea - bl["all"], 3), lift_train=round(et - bl["tr"], 3), lift_test=round(ee - bl["te"], 3), lift_low=round(ea - bl["all"] - SE_MULT * se, 3), train_n=len(tr), test_n=len(te))
    by = {}
    for r in rows:
        by.setdefault(r[1], []).append(r)
    q = [v for v in by.values() if len(v) >= MIN_COIN_N]
    share = sum(1 for v in q if mean_r(v, k) > bl["all"]) / len(q) if len(q) >= MIN_COINS else None
    out["coins_beat_baseline_pct"] = None if share is None else round(100.0 * share, 0)
    both = et > bl["tr"] and ee > bl["te"]
    if ea > 0 and out["lift_low"] > 0 and both and (share is None or share >= STEADY_COINS):
        out["verdict"] = "STEADY"
    elif ea > 0 and ea > bl["all"]:
        out["verdict"] = "SOMETIMES"
    else:
        out["verdict"] = "NO_PAY"
    out["avoid"] = et < bl["tr"] and ee < bl["te"] and ea < 0
    return out


def plain(state, n, best, res, step):
    if best == "NONE":
        if all(res[s]["verdict"] == "NOT_ENOUGH_DATA" for s in res):
            return "%s: %d events, but 30 independent cases are needed (and 15 in each half). No verdict yet." % (state, n)
        return "%s: neither LONG nor SHORT beat a random candle." % state
    r = res[best]
    how = "in BOTH halves, on most coins, and not by luck" if r["verdict"] == "STEADY" else "only sometimes (a half or some coins fail, or it may be luck): NOT proven"
    return "%s: %s %s %s. %d independent cases, win %.0f%%, expected %+.2fR (%+.2fR vs any candle). Median %d candles (about %d min)." % (
        state, best, "paid" if r["verdict"] == "STEADY" else "looked good", how, r["n_independent"], r["win_pct"], r["exp_r"], r["lift"], r["median_candles"], r["median_candles"] * step // 60)


def report(ev, base, step):
    """Events + baseline -> one answer per state, grouped by pair, best first."""
    ts = sorted(r[0] for r in base)
    cut = ts[int(len(ts) * TRAIN_FRAC)] if ts else 0
    tr, te = [r for r in base if r[0] < cut], [r for r in base if r[0] >= cut]
    bl = {k: {"all": mean_r(base, k) or 0.0, "tr": mean_r(tr, k) or 0.0, "te": mean_r(te, k) or 0.0} for k in (2, 3)}
    pairs, count = {}, {v: 0 for v in RANK}
    for p in PAIRS:
        out = []
        for s, rows in ev[p].items():
            res = {"LONG": judge(rows, 2, cut, bl[2], HOLD * step), "SHORT": judge(rows, 3, cut, bl[3], HOLD * step)}
            top = max(res, key=lambda x: (RANK[res[x]["verdict"]], res[x].get("lift", -9.0)))
            best = top if RANK[res[top]["verdict"]] >= 1 else "NONE"
            verdict = res[top]["verdict"] if best != "NONE" else ("NOT_ENOUGH_DATA" if all(r["verdict"] == "NOT_ENOUGH_DATA" for r in res.values()) else "NO_PAY")
            count[verdict] += 1
            out.append({"state": s, "n": len(rows), "per_100_candles": round(100.0 * len(rows) / len(base), 2), "best": best, "verdict": verdict, "use_in_sniper": verdict == "STEADY",
                        "avoid": [x for x in res if res[x].get("avoid")], "plain": plain(s, len(rows), best, res, step), "long": res["LONG"], "short": res["SHORT"]})
        out.sort(key=lambda x: (-RANK[x["verdict"]], -x["n"]))
        pairs[p] = out
    return {"pairs": pairs, "verdict_counts": count, "baseline_exp_r": {"LONG": round(bl[2]["all"], 3), "SHORT": round(bl[3]["all"], 3)}, "split_ts": cut, "checks_made": 2 * sum(len(v) for v in ev.values())}


def load_runs(con, tf, cap):
    """[(symbol, gap-free run)] for the coins with the most candles. EVERY run with MIN_RUN+ candles counts (gaps are cut, never bridged)."""
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
    head = {"version": VERSION, "interval": tf, "paper_only": True, "ready": False}
    con = F.open_ro(d)
    if con is None:
        return dict(head, note="No market store yet: no candles are saved.")
    try:
        runs = load_runs(con, tf, cap)
    finally:
        con.close()
    cfg, src = load_cfg(d, tf)
    ev, base, coins, skipped = analyse(runs, cfg, 0 if since_days is None else now - int(since_days * 86400))
    if not base:
        return dict(head, note="Not enough gap-free candles (a run needs %d+ candles)." % MIN_RUN, skipped=skipped, cfg_source=src)
    rep = report(ev, base, TF.step(tf))
    if only:
        rep["pairs"] = {p: v for p, v in rep["pairs"].items() if p == only}
    return dict(head, ready=True, cfg_source=src, coins=len(coins), candles_checked=len(base), skipped=skipped, hold_candles=HOLD, target_r=TARGET_R, **rep)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--tf", default="5m", choices=TF.SUPPORTED)
    ap.add_argument("--cap", type=int, default=F.MAX_COINS)
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--pair", default=None, choices=PAIRS)
    ap.add_argument("--save", action="store_true", help="also write v2_sniper_ind_pairs.json in the data folder")
    a = ap.parse_args(argv)
    res = build(a.data, a.tf, a.cap, a.since_days, only=a.pair)
    if a.save and res.get("ready"):
        res["saved"] = F.write_json(a.data, FILE, res)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
