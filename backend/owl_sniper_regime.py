"""owl_sniper_regime.py - OwlSniper VOLATILITY REGIME + LOOKBACK OPTIMIZER (Part 27 / FILE 18, group G4). READ ONLY: the market store is opened read-only, no network, no order code.
Two questions of the owner (MASTER_PROMPT 4.2 and 4.4):  (1) "Is the market LOW / MEDIUM / HIGH / EXTREME volatility now?"  (2) "Which lookback length (50 ... 300) is best, and does the best one change with the regime?"
This file OBSERVES and MEASURES. No hard-coded rule. It reuses the outcome + verdict rule of Part 23 (owl_sniper_ind_pairs.py) and the SD-band touches of Part 25 (owl_sniper_sdbands.py).
(1) REGIME of a closed candle i = where the coin's own recent range sits in its own past. UNIT(i) = average candle range in % over the last 20 candles (Part 23). The rank p = share of the PAST 500 UNIT values (candles before i only, never i itself, at least 100 of them) that are below UNIT(i).
    LOW p < 0.25 / MEDIUM p < 0.75 / HIGH p < 0.95 / EXTREME p >= 0.95. Every coin is ranked against ITSELF, so a quiet coin and a wild coin both have all four regimes. (This is not the engine's TRENDING / SIDEWAYS flag; that one is a different question.)
(2) LOOKBACK = the SD / SMA / Z length of the owner's indicators (sd_len). Tested: 50, 100, 150, 200, 250, 300 (and the live model's own value if it is a different one). The Z-SMA length is not changed here.
    SETUP used for the test = the SD band HELD touches (LOWER1 / LOWER2 = support, UPPER1 / UPPER2 = resistance, Part 25 rule, touch zone 0.25 UNIT). Natural decision: support = LONG, resistance = SHORT. These touches CHANGE with the lookback (the band moves), so the lookback is measured, not guessed.
    FAIR TEST: the same candles for every lookback (the first candle where ALL lookbacks are warmed up), the same outcomes (entry = open of the next candle, 1R = UNIT x price, +2R / -1R, 30 candles, stop first), the same baseline (any candle IN THE SAME REGIME, mixed by the share of LONG / SHORT events), independent cases only.
    VERDICT per (lookback, regime): NOT_ENOUGH_DATA below 30 independent cases (15 per half) / STEADY (both halves, 60% of coins, lift above 2 x standard error) / SOMETIMES (not proven) / NO_PAY. 'ALL' = every regime together.
RECOMMENDATION per regime: best_seen = the lookback with the best verdict, then lift, among those that are at least SOMETIMES and still positive in the new 40% of the time. It is RECOMMENDED only when it is STEADY, is not the default, and beats the default by at least 0.03R
    (basis STEADY_BEST); otherwise the default stays (basis DEFAULT_KEPT, or SOMETIMES_BEST_NOT_PROVEN when a better-looking one exists but is not proven). 6 lookbacks x 5 regimes = 30 checks: picking the best of 6 favours luck, so a choice is only trusted when STEADY and it stays so on a later run.
    Re-run every 7 to 14 days (rolling): the file only reads, so a re-run is just calling build() again (--since-days 30 uses the latest month).
LIVE HELPERS: regime_now(candles, cfg) -> {'regime', 'percentile', 'unit_pct'} for the Risk Box line;  risk_line(report, regime) -> 'Volatility Regime: MEDIUM | Recommended Lookback: 200 (DEFAULT_KEPT)'.
Run (Termux, optional):  python3 backend/owl_sniper_regime.py [--data DIR] [--tf 5m|15m] [--cap 40] [--since-days N] [--save]  -> JSON (--save also writes v2_sniper_regime.json). Needs the Part 23, 24 and 25 files next to it."""
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
import owl_sniper_sdbands as SB
import owl_sniper_tf as TF
import owl_sniper_zsma as Z

VERSION = "owl_sniper_regime 1 (Part 27)"
FILE = "v2_sniper_regime.json"
LOOKBACKS, RW, RW_MIN, CUTS, NAMES = (50, 100, 150, 200, 250, 300), 500, 100, (0.25, 0.75, 0.95), ("LOW", "MEDIUM", "HIGH", "EXTREME")
SETUP, GAIN_MIN, RANK = ("LOWER1_HELD", "LOWER2_HELD", "UPPER1_HELD", "UPPER2_HELD"), 0.03, IP.RANK


def regimes_of(units):
    """[(regime, percentile)] for a list of UNIT values, oldest first. Candle i is ranked against the 500 values BEFORE it (no look-ahead); (None, None) until 100 are known."""
    out, win = [(None, None)] * len(units), []
    for i, u in enumerate(units):
        if len(win) >= RW_MIN:
            p = bisect.bisect_left(win, u) / len(win)
            out[i] = (NAMES[sum(1 for c in CUTS if p >= c)], p)
        bisect.insort(win, u)
        if len(win) > RW:
            win.pop(bisect.bisect_left(win, units[i - RW]))
    return out


def analyse(runs, cfg, since_ts=0):
    """-> (events {lookback: {'ALL' or regime: [row]}}, base [row], coins, skipped, lookbacks). event row = (ts, symbol, result, result, side) (result = the natural decision's outcome, in both slots so Part 23's judge() reads it);
    base row = (ts, symbol, long result, short result, regime, unit)."""
    Ls = sorted(set(LOOKBACKS) | {int(cfg.get("sd_len", 200))})
    ev, base, coins, skipped = {L: {} for L in Ls}, [], set(), {"short_run": 0, "bad_candles": 0}
    for sym, run in runs:
        try:
            S0 = E.build_features(run, dict(cfg, sd_len=Ls[0]))
            pack = (S0["tsi"], S0["tsl"], S0["hist"])
            Ss = {L: S0 if L == Ls[0] else E.build_features(run, dict(cfg, sd_len=L), tsi_pack=pack) for L in Ls}
        except (ValueError, KeyError, IndexError, TypeError):
            skipped["bad_candles"] += 1
            continue
        lo, hi = max(max(E.warmup_end(S) for S in Ss.values()), IP.UNIT_WIN, IP.LOOK, RW_MIN) + 1, S0["n"] - IP.HOLD - 2
        if hi - lo < 50:
            skipped["short_run"] += 1
            continue
        coins.add(sym)
        units = [IP.unit_of(S0, i) for i in range(S0["n"])]
        reg = regimes_of(units)
        prev = {L: set() for L in Ls}
        for i in range(lo, hi + 1):
            u, rg = units[i], reg[i][0]
            if S0["t"][i] < since_ts or u <= 0 or rg is None:
                prev = {L: set() for L in Ls}
                continue
            entry = S0["o"][i + 1]
            lr, sr = IP.walk(S0, i, "LONG", entry, u * entry), IP.walk(S0, i, "SHORT", entry, u * entry)
            base.append((S0["t"][i], sym, lr, sr, rg, u))
            for L, S in Ss.items():
                now = {k for k in SB.kinds_at(S, i, u) if k in SETUP}
                for side in {"LONG" if k.startswith("LOWER") else "SHORT" for k in now - prev[L]}:
                    res = lr if side == "LONG" else sr
                    row = (S0["t"][i], sym, res, res, side)
                    ev[L].setdefault("ALL", []).append(row)
                    ev[L].setdefault(rg, []).append(row)
                prev[L] = now
    return ev, base, coins, skipped, Ls


def pooled(rows, cut, blr, gap):
    """Part 23 verdict for the pooled natural-decision events of one (lookback, regime). The baseline is mixed by the share of LONG events."""
    wl = sum(1 for r in rows if r[4] == "LONG") / len(rows) if rows else 0.5
    bl = {x: wl * blr[2][x] + (1 - wl) * blr[3][x] for x in ("all", "tr", "te")}
    out = IP.judge(rows, 2, cut, bl, gap)
    out["share_long_pct"] = round(100.0 * wl)
    return out


def recommend(res, Ls, default):
    """{'lookback', 'basis', 'best_seen', 'gain_vs_default_r', 'note'} for one regime from {lookback: judged block}."""
    ok = [(RANK[b["verdict"]], b["lift_low"], L) for L, b in res.items() if RANK[b["verdict"]] >= 1 and b["lift_test"] > 0]
    if not ok:
        return {"lookback": default, "basis": "DEFAULT_KEPT", "best_seen": None, "gain_vs_default_r": None, "note": "No lookback has a proven edge for this setup here: the default %d stays." % default}
    rk, _low, best = max(ok)
    d = res.get(default, {})
    gain = round(res[best]["lift"] - d["lift"], 3) if "lift" in d else None
    if rk == RANK["STEADY"] and best != default and (gain is None or gain >= GAIN_MIN):
        return {"lookback": best, "basis": "STEADY_BEST", "best_seen": best, "gain_vs_default_r": gain, "note": "%d is STEADY and beats the default %d%s." % (best, default, "" if gain is None else " by %+.2fR" % gain)}
    if best != default and rk == RANK["SOMETIMES"]:
        return {"lookback": default, "basis": "SOMETIMES_BEST_NOT_PROVEN", "best_seen": best, "gain_vs_default_r": gain, "note": "%d looks best but only sometimes (not proven): the default %d stays." % (best, default)}
    return {"lookback": default, "basis": "DEFAULT_KEPT", "best_seen": best, "gain_vs_default_r": gain, "note": "No lookback beats the default %d by a proven margin." % default}


def report(ev, base, Ls, default, step):
    ts = sorted(r[0] for r in base)
    cut = ts[int(len(ts) * IP.TRAIN_FRAC)] if ts else 0
    regs, blr, count = {}, {}, {v: 0 for v in RANK}
    for rg in ("ALL",) + NAMES:
        rows = base if rg == "ALL" else [r for r in base if r[4] == rg]
        tr, te = [r for r in rows if r[0] < cut], [r for r in rows if r[0] >= cut]
        blr[rg] = {k: {"all": IP.mean_r(rows, k) or 0.0, "tr": IP.mean_r(tr, k) or 0.0, "te": IP.mean_r(te, k) or 0.0} for k in (2, 3)}
        us = sorted(r[5] for r in rows)
        regs[rg] = {"share_pct": round(100.0 * len(rows) / len(base), 1), "typical_range_pct": round(100.0 * us[len(us) // 2], 3) if us else None,
                    "base_exp_r": {"LONG": round(blr[rg][2]["all"], 3), "SHORT": round(blr[rg][3]["all"], 3)}}
    table = {L: {rg: pooled(ev[L].get(rg, []), cut, blr[rg], IP.HOLD * step) for rg in regs} for L in Ls}
    for L in Ls:
        for b in table[L].values():
            count[b["verdict"]] += 1
    rec = {rg: recommend({L: table[L][rg] for L in Ls}, Ls, default) for rg in regs}
    dl = [(table[default][rg]["lift"], rg) for rg in NAMES if table[default][rg].get("n_independent", 0) >= IP.MIN_N]
    return {"setup": "SD band HELD touches (lower / upper 1 and 2 SD): support = LONG, resistance = SHORT", "default_lookback": default, "lookbacks_tested": Ls, "regimes": regs, "lookbacks": {str(L): table[L] for L in Ls},
            "recommended": rec, "setup_strongest_regime": max(dl)[1] if len(dl) > 1 else None, "setup_weakest_regime": min(dl)[1] if len(dl) > 1 else None,
            "verdict_counts": count, "split_ts": cut, "checks_made": len(Ls) * len(regs)}


def regime_now(candles, cfg=None):
    """The regime of the LAST candle: {'regime', 'percentile', 'unit_pct'} or None while fewer than 100 earlier candles exist."""
    S = E.build_features(candles, cfg)
    units = [IP.unit_of(S, i) for i in range(S["n"])]
    name, p = regimes_of(units)[-1]
    return None if name is None else {"regime": name, "percentile": round(p, 3), "unit_pct": round(100.0 * units[-1], 3)}


def risk_line(rep, regime):
    """The Risk Box line of the master prompt 4.1. Says plainly when nothing is known."""
    r = (rep or {}).get("recommended", {}).get(regime)
    if not r:
        return "Volatility Regime: %s | Recommended Lookback: not studied yet" % (regime or "UNKNOWN")
    return "Volatility Regime: %s | Recommended Lookback: %d (%s)" % (regime, r["lookback"], r["basis"])


def build(d, tf="5m", cap=F.MAX_COINS, since_days=None, now=None):
    """The whole study from the saved candles. Never raises on missing data: {ready: False, note}."""
    TF.check(tf)
    now = int(time.time() if now is None else now)
    head = {"version": VERSION, "interval": tf, "paper_only": True, "ready": False}
    con = F.open_ro(d)
    if con is None:
        return dict(head, note="No market store yet: no candles are saved.")
    try:
        runs = Z.load_runs(con, tf, cap)
    finally:
        con.close()
    cfg, src = IP.load_cfg(d, tf)
    ev, base, coins, skipped, Ls = analyse(runs, cfg, 0 if since_days is None else now - int(since_days * 86400))
    if not base:
        return dict(head, note="Not enough gap-free candles (a run needs %d+ candles)." % Z.MIN_RUN, skipped=skipped, cfg_source=src)
    return dict(head, ready=True, cfg_source=src, coins=len(coins), candles_checked=len(base), skipped=skipped, hold_candles=IP.HOLD, target_r=IP.TARGET_R, **report(ev, base, Ls, int(cfg.get("sd_len", 200)), TF.step(tf)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--tf", default="5m", choices=TF.SUPPORTED)
    ap.add_argument("--cap", type=int, default=F.MAX_COINS)
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--save", action="store_true", help="also write v2_sniper_regime.json in the data folder")
    a = ap.parse_args(argv)
    res = build(a.data, a.tf, a.cap, a.since_days)
    if a.save and res.get("ready"):
        res["saved"] = F.write_json(a.data, FILE, res)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
