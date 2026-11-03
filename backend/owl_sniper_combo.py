"""owl_sniper_combo.py - OwlSniper COMBOS + FEATURE ATTRIBUTION (Part 26 / FILE 17, group G4). READ ONLY: the market store is opened read-only, no network, no order code.
Two questions of the owner (MASTER_PROMPT 4.3B-B and 4.8):
  (1) COMBOS  "SD band + Z-SMA + TSI together: which combination gives a better edge than the band alone?"
  (2) FEATURE ATTRIBUTION  "Which indicator part is the strongest, and which one has recently become weak?"
This file OBSERVES and MEASURES. No hard-coded rule. It reuses the outcome + verdict rule of Part 23 (owl_sniper_ind_pairs.py), the Z-SMA line of Part 24 (owl_sniper_zsma.py) and the SD bands of Part 25 (owl_sniper_sdbands.py).
OUTCOME + VERDICT: exactly Part 23: entry = OPEN of the next candle, 1R = UNIT x price, +2R target, -1R stop, 30 candles, stop first; BASELINE = any candle; independent cases only (per coin 30 candles apart);
  NOT_ENOUGH_DATA below 30 independent cases (15 per half) / STEADY (both halves, 60% of coins, lift above 2 x standard error) / SOMETIMES (not proven, never used) / NO_PAY. use_in_sniper = true ONLY for STEADY.
(1) COMBOS. Base kinds (the support / resistance touches that HELD, first candle only): SUPPORT_HELD + RESISTANCE_HELD (Z-SMA line), LOWER1_HELD, LOWER2_HELD, UPPER1_HELD, UPPER2_HELD (SD bands).
  Every event is tagged with two context states read on the same closed candle:  Z side = Z ABOVE / BELOW its Z-SMA  and  TSI = TSI UP / DOWN versus its signal line.   6 kinds x 2 x 2 = 24 combos (+ the plain kind, no tag).
  vs_kind_r = expected R of the combo (natural decision: support = LONG, resistance = SHORT) minus expected R of the plain kind. adds_value = the combo is at least SOMETIMES and vs_kind_r > 0.  best_combo = best verdict, then lift (best_combo_verdict says STEADY or 'SOMETIMES (not proven)').
(2) FEATURE ATTRIBUTION. 7 features, each cut into its states; an EVENT = the first candle of a state (same as Part 23):
  zsma_side (Z above / below Z-SMA), z_level (M2 < -2, M1 < -1, 0, P1 <= 2, P2 > 2; this is also the SD band zone), z_dir (Z up / down / flat over 3 candles), tsi_vs_signal (TSI above / below its signal), tsi_zero (TSI above / below 0),
  hist (histogram POS / NEG x GROWING / SHRINKING in size), ema_cloud (EMA 30 above / below 50), price_vs_cloud (above / inside / below the cloud).
  Status of a feature (its best judged states): STRONG = one state-decision is STEADY / WEAKENING = a state paid in the old 60% (lift above 2 x its standard error, so not luck) and no longer pays in the new 40% (this answers 'what became weak recently') /
  SOMETIMES = only unproven / NO_EDGE = judged but nothing beat a random candle / UNKNOWN = no state has 30 independent cases yet. score = the best lift after the 2 x standard-error margin (lift_low).
  answers: strongest (best status, then score), recently_weak (all WEAKENING features), best_combo. The reversal arrows, CHoCH and BOS are never used.
Checks made: 24 + 6 combos-with-plain and 23 feature states, each x 2 decisions: a STEADY by luck is possible, trust one more when it stays STEADY on a later run and on the other interval.
Run (Termux, optional):  python3 backend/owl_sniper_combo.py [--data DIR] [--tf 5m|15m] [--cap 40] [--since-days N] [--only combos|attribution] [--save]  -> JSON (--save also writes v2_sniper_combo.json). Needs Part 23, 24 and 25 files next to it."""
import argparse
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

VERSION = "owl_sniper_combo 1 (Part 26)"
FILE = "v2_sniper_combo.json"
KINDS = ("SUPPORT_HELD", "RESISTANCE_HELD", "LOWER1_HELD", "LOWER2_HELD", "UPPER1_HELD", "UPPER2_HELD")
ZSIDES, TSIS = ("ZABOVE", "ZBELOW"), ("TSIUP", "TSIDN")
RANK = IP.RANK


def nat(kind):
    return "LONG" if kind.startswith(("SUPPORT", "LOWER")) else "SHORT"


def feats(S, zs, i):
    """The 7 attribution features on closed candle i (all causal)."""
    c, z, hs = S["c"], S["z"], S["hist"]
    dz, zl, ef, es = z[i] - z[i - IP.LOOK], z[i], S["ema_f"][i], S["ema_s"][i]
    return {"zsma_side": "ABOVE" if z[i] > zs[i] else "BELOW",
            "z_level": "M2" if zl < -2 else "M1" if zl < -1 else "0" if zl <= 1 else "P1" if zl <= 2 else "P2",
            "z_dir": "UP" if dz > IP.Z_MOVE else "DOWN" if dz < -IP.Z_MOVE else "FLAT",
            "tsi_vs_signal": "ABOVE" if S["tsi"][i] > S["tsl"][i] else "BELOW",
            "tsi_zero": "POS" if S["tsi"][i] > 0 else "NEG",
            "hist": "%s_%s" % ("POS" if hs[i] > 0 else "NEG", "GROWING" if abs(hs[i]) > abs(hs[i - 1]) else "SHRINKING"),
            "ema_cloud": "UP" if ef > es else "DOWN",
            "price_vs_cloud": "ABOVE" if c[i] > max(ef, es) else "BELOW" if c[i] < min(ef, es) else "INSIDE"}


def analyse(runs, cfg, since_ts=0):
    """-> (combo events {'KIND|ALL' or 'KIND|Z|TSI': [row]}, feature events {feature: {state: [row]}}, base [row], coins, skipped). row = (ts, symbol, long result, short result) as in Part 23."""
    cev, fev, base, coins, skipped = {}, {}, [], set(), {"short_run": 0, "bad_candles": 0}
    for sym, run in runs:
        try:
            S = E.build_features(run, cfg)
        except (ValueError, KeyError, IndexError, TypeError):
            skipped["bad_candles"] += 1
            continue
        L, zs = Z.line_of(S), E.sma_any(S["z"], Z.ZSMA_LEN)
        first = next((i for i in range(S["n"]) if zs[i] is not None and L[i] is not None), S["n"])
        lo, hi = max(E.warmup_end(S), first, IP.UNIT_WIN, IP.LOOK) + 1, S["n"] - IP.HOLD - 2
        if hi - lo < 50:
            skipped["short_run"] += 1
            continue
        coins.add(sym)
        pk, pf = set(), None
        for i in range(lo, hi + 1):
            u = IP.unit_of(S, i)
            if S["t"][i] < since_ts or u <= 0:
                pk, pf = set(), None
                continue
            entry = S["o"][i + 1]
            row = (S["t"][i], sym, IP.walk(S, i, "LONG", entry, u * entry), IP.walk(S, i, "SHORT", entry, u * entry))
            base.append(row)
            now = SB.kinds_at(S, i, u) | {Z.kind_at(S, L, i, u)}
            now = {k for k in now if k in KINDS}
            tag = "%s|%s" % ("ZABOVE" if S["z"][i] > zs[i] else "ZBELOW", "TSIUP" if S["tsi"][i] > S["tsl"][i] else "TSIDN")
            for k in now - pk:
                cev.setdefault("%s|ALL" % k, []).append(row)
                cev.setdefault("%s|%s" % (k, tag), []).append(row)
            pk = now
            ft = feats(S, zs, i)
            if pf is not None:
                for f, s in ft.items():
                    if pf[f] != s:
                        fev.setdefault(f, {}).setdefault(s, []).append(row)
            pf = ft
    return cev, fev, base, coins, skipped


def block(name, rows, cut, bl, step):
    """The answer for ONE state: both decisions judged by the Part 23 rule."""
    res = {"LONG": IP.judge(rows, 2, cut, bl[2], IP.HOLD * step), "SHORT": IP.judge(rows, 3, cut, bl[3], IP.HOLD * step)}
    top = max(res, key=lambda x: (RANK[res[x]["verdict"]], res[x].get("lift", -9.0)))
    best = top if RANK[res[top]["verdict"]] >= 1 else "NONE"
    verdict = res[top]["verdict"] if best != "NONE" else ("NOT_ENOUGH_DATA" if all(r["verdict"] == "NOT_ENOUGH_DATA" for r in res.values()) else "NO_PAY")
    return {"state": name, "n": len(rows), "best": best, "verdict": verdict, "use_in_sniper": verdict == "STEADY", "avoid": [x for x in res if res[x].get("avoid")],
            "plain": IP.plain(name, len(rows), best, res, step), "long": res["LONG"], "short": res["SHORT"]}


def combos(cev, cut, bl, step):
    out = {}
    for k in KINDS:
        k2 = 2 if nat(k) == "LONG" else 3
        plain = block("%s|ALL" % k, cev.get("%s|ALL" % k, []), cut, bl, step)
        base_r, cs = IP.mean_r(cev.get("%s|ALL" % k, []), k2), []
        for z in ZSIDES:
            for t in TSIS:
                rows = cev.get("%s|%s|%s" % (k, z, t), [])
                b = block("%s|%s|%s" % (k, z, t), rows, cut, bl, step)
                b["vs_kind_r"] = round(IP.mean_r(rows, k2) - base_r, 3) if rows and base_r is not None else None
                b["adds_value"] = RANK[b["verdict"]] >= 1 and (b["vs_kind_r"] or 0) > 0
                cs.append(b)
        out[k] = {"natural_decision": nat(k), "plain_kind": plain, "combos": cs}
    return out


def feature_status(states):
    """(status, score, note) for one feature from its judged states."""
    ok = [(d, s) for s in states for d in ("long", "short") if s[d].get("verdict") not in (None, "NOT_ENOUGH_DATA")]
    if not ok:
        return "UNKNOWN", None, None
    score = max(s[d]["lift_low"] for d, s in ok)
    weak = [(s["state"], d.upper()) for d, s in ok if s[d]["lift_train"] > 2.6 * (s[d]["lift"] - s[d]["lift_low"]) / 2 and s[d]["lift_test"] <= 0]   # old half paid beyond luck (2 x its standard error), new half does not
    if any(s[d]["verdict"] == "STEADY" for d, s in ok):
        return "STRONG", score, weak
    return ("WEAKENING" if weak else "SOMETIMES" if any(s[d]["verdict"] == "SOMETIMES" for d, s in ok) else "NO_EDGE"), score, weak


def attribution(fev, cut, bl, step):
    feats_out, order = {}, {"STRONG": 4, "WEAKENING": 3, "SOMETIMES": 2, "NO_EDGE": 1, "UNKNOWN": 0}
    for f, sts in fev.items():
        states = sorted((block(s, rows, cut, bl, step) for s, rows in sts.items()), key=lambda b: (-RANK[b["verdict"]], -b["n"]))
        status, score, weak = feature_status(states)
        feats_out[f] = {"status": status, "score": None if score is None else round(score, 3), "weakening_states": weak or [], "states": states}
    rank = sorted(feats_out, key=lambda f: (order[feats_out[f]["status"]], feats_out[f]["score"] if feats_out[f]["score"] is not None else -9), reverse=True)
    top = rank[0] if rank and feats_out[rank[0]]["status"] in ("STRONG", "SOMETIMES") else None
    weak_now = [f for f in rank if feats_out[f]["status"] == "WEAKENING"]
    return {"features": feats_out, "ranking": rank, "strongest": top, "recently_weak": weak_now,
            "plain": ("Strongest feature: %s (%s). " % (top, feats_out[top]["status"]) if top else "No feature has a proven edge yet. ") + ("Recently weak: %s." % ", ".join(weak_now) if weak_now else "No feature has clearly weakened.")}


def report(cev, fev, base, step, only=None):
    ts = sorted(r[0] for r in base)
    cut = ts[int(len(ts) * IP.TRAIN_FRAC)] if ts else 0
    tr, te = [r for r in base if r[0] < cut], [r for r in base if r[0] >= cut]
    bl = {k: {"all": IP.mean_r(base, k) or 0.0, "tr": IP.mean_r(tr, k) or 0.0, "te": IP.mean_r(te, k) or 0.0} for k in (2, 3)}
    out = {"baseline_exp_r": {"LONG": round(bl[2]["all"], 3), "SHORT": round(bl[3]["all"], 3)}, "split_ts": cut}
    if only in (None, "combos"):
        out["combos"] = combos(cev, cut, bl, step)
        allc = [(RANK[c["verdict"]], c["long" if nat(k) == "LONG" else "short"].get("lift", -9.0), k, c["state"]) for k, v in out["combos"].items() for c in v["combos"] if c["adds_value"]]
        out["best_combo"] = max(allc)[3] if allc else None
        out["best_combo_verdict"] = None if not allc else ("STEADY" if max(allc)[0] == RANK["STEADY"] else "SOMETIMES (not proven)")
    if only in (None, "attribution"):
        out["attribution"] = attribution(fev, cut, bl, step)
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
        runs = Z.load_runs(con, tf, cap)
    finally:
        con.close()
    cfg, src = IP.load_cfg(d, tf)
    cev, fev, base, coins, skipped = analyse(runs, cfg, 0 if since_days is None else now - int(since_days * 86400))
    if not base:
        return dict(head, note="Not enough gap-free candles (a run needs %d+ candles)." % Z.MIN_RUN, skipped=skipped, cfg_source=src)
    return dict(head, ready=True, cfg_source=src, coins=len(coins), candles_checked=len(base), skipped=skipped, hold_candles=IP.HOLD, target_r=IP.TARGET_R, **report(cev, fev, base, TF.step(tf), only))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--tf", default="5m", choices=TF.SUPPORTED)
    ap.add_argument("--cap", type=int, default=F.MAX_COINS)
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--only", default=None, choices=("combos", "attribution"))
    ap.add_argument("--save", action="store_true", help="also write v2_sniper_combo.json in the data folder")
    a = ap.parse_args(argv)
    res = build(a.data, a.tf, a.cap, a.since_days, only=a.only)
    if a.save and res.get("ready"):
        res["saved"] = F.write_json(a.data, FILE, res)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
