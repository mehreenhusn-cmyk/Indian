"""v2_bt_zonestudy.py - Part 89a: BRAIN TRADER SD-ZONE STUDY (backend). Question: when price ARRIVES in an SD zone (in a market state), what did it do next, and would the BT-01 trade from there have made money?
Data: the saved candles of the coins the collector follows (newest gap-free run of each coin, closed candles only). Tags = Part 84b (v2_bt_state, causal: candle i sees candles 0..i only). No new indicator.
ARRIVAL = the first candle of a stretch where the pair (SD zone, market state) changed. Only arrivals are counted, so 20 candles in a row inside one zone are ONE case, not 20.
Per group (SD zone x market state x side, plus every zone over all states) the study says:
  forward move after 3 / 6 / 12 / 24 candles (median, in R = stop units: 1 R = 1 SD of the last 200 closes = the BT-01 stop; for SHORT the sign is turned so + is good),
  the HYPOTHETICAL BT-01 trade from that candle (entry = the close, stop 1 R, target 1.5 R, 24 candles max, stop and target in one candle = STOP, cost = 2 x (fee + slippage) taken in R; candles whose stop is outside 0.3-2.0 % are left out like BT-01 does) = mean net R,
  the BASELINE = the same hypothetical trade from ordinary ready candles (every 6th candle, any zone / state) = what 'no idea at all' gives, TRAIN (older 70 % of each coin's time) and HOLDOUT (newest 30 %) apart, and how many coins the group came from.
ONE word: USE / AVOID need 30+ cases, 10+ in TRAIN and in HOLDOUT, 3+ coins, mean net R above / below 0 in BOTH TRAIN and HOLDOUT (USE must also beat the baseline); disagreement = MIXED; else NOT ENOUGH DATA. No win rate, no forecast.
HONEST LIMITS (said on the screen): the coins are the collector's top gainers / losers list, so they are NOT a random sample of the market; the hypothetical trade ignores that the Brain may not have opened it (it is the zone's own evidence, not the Brain's result);
many groups are checked at once so a few look good by luck. Only NEW paper trades after a rule is frozen can prove anything. Nothing here changes BT-01, the live bot or any rule; a change needs a new version BT-02 and the owner's OK.
Writes ONLY its own cache file v2_bt_zonestudy_<interval>.json in the data folder (atomic); reads the market store read-only; the route only reads that file. No network, no order code, no trading import.
Run (Termux, optional; set OWL_DATA_DIR first):  python3 backend/v2_bt_zonestudy.py run [--interval 5m]   (works out + saves)  |  report [--interval 5m]  (prints the plain lines)"""
import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_rules as R
import v2_bt_state as ST
import v2_bt_wait as W
import v2_bt_sim as M
import v2_replay as V
import v2_scalp_ind as IND

VERSION = "v2_bt_zonestudy 1 (Part 89a)"
HORIZONS, MAXH, BASE_STEP, MIN_N, MIN_SPLIT, MIN_COINS, SHOW = (3, 6, 12, 24), 24, 6, 30, 10, 3, 60
SIDES = ("LONG", "SHORT")
LIMIT = ("The coins are the collector's top gainers / losers, not a random sample of the market. This is the zone's own evidence, not the Brain's real result. Many groups are checked at once, so a few look good by luck. "
         "Only new paper trades after a rule is frozen can prove anything. BT-01 is not changed; a change needs BT-02 and your OK.")


def cache_path(data_dir, interval):
    if interval not in ("3m", "5m"):
        raise ValueError("interval must be 3m or 5m")
    return os.path.join(data_dir, "v2_bt_zonestudy_%s.json" % interval)


def _hyp(run, i, side, sd):
    """Hypothetical BT-01 trade from the close of candle i -> net R after cost, or None when the stop is outside the 0.3-2.0 % band. Needs candles up to i + MAXH."""
    e = float(run[i][4])
    if e <= 0 or sd <= 0 or not (R.RISK_MIN_PCT <= sd / e * 100.0 <= R.RISK_MAX_PCT):
        return None
    lg = side == "LONG"
    stop, tgt = (e - R.STOP_SD * sd, e + R.TARGET_R * R.STOP_SD * sd) if lg else (e + R.STOP_SD * sd, e - R.TARGET_R * R.STOP_SD * sd)
    r = None
    for j in range(i + 1, i + MAXH + 1):
        hi, lo = float(run[j][2]), float(run[j][3])
        if (lo <= stop) if lg else (hi >= stop):
            r = -1.0
            break
        if (hi >= tgt) if lg else (lo <= tgt):
            r = R.TARGET_R
            break
    if r is None:
        r = (float(run[i + MAXH][4]) - e) / sd * (1.0 if lg else -1.0)
    return r - V.cost_pct() / 100.0 * e / sd


def study_coin(run, interval="5m"):
    """ONE coin -> {'cases': [...], 'base': [...]}. A case = an ARRIVAL; a base row = an ordinary ready candle (every BASE_STEP-th). Each row: zone, state, sample, per side fwd (signed R at the horizons) and net R."""
    need = IND.need_candles()
    if len(run) < need + MAXH + 1:
        return None
    ctx = ST.prepare(run)
    cut = V.holdout_cut([c[0] for c in run])
    cases, base, prev, k = [], [], None, 0
    for i in range(need - 1, len(run) - MAXH):
        t = ST.tags(ctx, i)
        if not t["ready"]:
            prev = None
            continue
        key = (t["sd_zone"], t["market_state"])
        sd = ctx["ind"]["sd_std"][i]
        row = None
        if (key != prev or k % BASE_STEP == 0) and sd:
            c0, row = float(run[i][4]), {"zone": key[0], "state": key[1], "sample": V.sample_of(run[i][0], cut), "side": {}}
            for sde in SIDES:
                n = _hyp(run, i, sde, sd)
                if n is not None:
                    sg = 1.0 if sde == "LONG" else -1.0
                    row["side"][sde] = {"net": n, "fwd": {h: sg * (float(run[i + h][4]) - c0) / sd for h in HORIZONS}}
        if row and row["side"]:
            if key != prev:
                cases.append(row)
            if k % BASE_STEP == 0:
                base.append(row)
        prev, k = key, k + 1
    return {"cases": cases, "base": base}


def _mean(xs):
    return round(sum(xs) / len(xs), 3) if xs else None


def _verdict(n, tr, ho, coins, edge):
    if n < MIN_N or len(tr) < MIN_SPLIT or len(ho) < MIN_SPLIT or coins < MIN_COINS:
        return "NOT ENOUGH DATA"
    a, b = sum(tr) / len(tr), sum(ho) / len(ho)
    if a > 0 and b > 0:
        return "USE" if edge is not None and edge > 0 else "MIXED"
    return "AVOID" if a < 0 and b < 0 else "MIXED"


def summarize(per_coin):
    """per_coin = {symbol: study_coin result} -> baseline per side + rows."""
    base = {s: {"TRAIN": [], "HOLDOUT": []} for s in SIDES}
    groups = {}
    for sym, r in per_coin.items():
        for row in r["base"]:
            for s, d in row["side"].items():
                base[s][row["sample"]].append(d["net"])
        for row in r["cases"]:
            for key in ((row["zone"], row["state"]), (row["zone"], "ALL")):
                for s, d in row["side"].items():
                    groups.setdefault(key + (s,), []).append((row["sample"], d, sym))
    bl = {s: {"n": len(base[s]["TRAIN"]) + len(base[s]["HOLDOUT"]), "mean_net_r": _mean(base[s]["TRAIN"] + base[s]["HOLDOUT"]), "train": _mean(base[s]["TRAIN"]), "holdout": _mean(base[s]["HOLDOUT"])} for s in SIDES}
    rows = []
    for (zone, state, side), xs in groups.items():
        tr = [d["net"] for sm, d, _ in xs if sm == "TRAIN"]
        ho = [d["net"] for sm, d, _ in xs if sm == "HOLDOUT"]
        allr = tr + ho
        coins = len(set(s for _, _, s in xs))
        mean = _mean(allr)
        b = bl[side]["mean_net_r"]
        edge = None if b is None or mean is None else round(mean - b, 3)
        rows.append({"zone": zone, "state": state, "side": side, "n": len(allr), "coins": coins, "n_train": len(tr), "n_holdout": len(ho), "mean_net_r": mean, "train_net_r": _mean(tr), "holdout_net_r": _mean(ho), "edge_vs_baseline_r": edge,
                     "fwd_median_r": {str(h): round(statistics.median([d["fwd"][h] for _, d, _ in xs]), 3) for h in HORIZONS}, "verdict": _verdict(len(allr), tr, ho, coins, edge)})
    rows.sort(key=lambda r: (r["state"] != "ALL", -r["n"]))
    keep = [r for r in rows if r["state"] == "ALL"] + [r for r in rows if r["state"] != "ALL" and r["n"] >= MIN_SPLIT][:SHOW]
    return bl, keep, len(rows)


def run_study(data_dir, interval="5m", now=None):
    now = int(time.time() if now is None else now)
    per, used, skipped = {}, [], []
    for sym in W.followed(data_dir, now):
        try:
            r = study_coin(M.load_run(data_dir, sym, interval), interval)
        except Exception as e:                                     # one coin never stops the study
            r = None
            skipped.append({"symbol": sym, "why": "error %s" % type(e).__name__})
            continue
        if r is None:
            skipped.append({"symbol": sym, "why": "too few gap-free candles (need %d)" % (IND.need_candles() + MAXH + 1)})
            continue
        per[sym] = r
        used.append(sym)
    bl, rows, total = summarize(per)
    out = {"framework": VERSION, "interval": interval, "made_ts": now, "coins": used, "skipped": skipped, "cases": sum(len(r["cases"]) for r in per.values()), "groups_checked": total,
           "baseline": bl, "rows": rows, "horizons": list(HORIZONS), "limit": LIMIT}
    p = cache_path(data_dir, interval)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f)
    os.replace(tmp, p)
    return out


def _na(x):
    """A missing number prints n/a, never the word None (Round 4)."""
    return "n/a" if x is None else x


def lines_of(out):
    ln = ["Zone study on %d coins, %d arrivals, %d groups checked. Baseline (any ready candle, BT-01 trade) LONG %s R, SHORT %s R net per trade." % (len(out["coins"]), out["cases"], out["groups_checked"], _na(out["baseline"]["LONG"]["mean_net_r"]), _na(out["baseline"]["SHORT"]["mean_net_r"]))]
    for v in ("USE", "AVOID"):
        for r in [x for x in out["rows"] if x["verdict"] == v][:3]:
            ln.append("%s candidate: %s side, arrival in SD zone %s, %s: %d cases from %d coins, mean net %+.2f R (TRAIN %+.2f, HOLDOUT %+.2f)." % (v, r["side"], r["zone"], "all market states" if r["state"] == "ALL" else r["state"], r["n"], r["coins"], r["mean_net_r"], r["train_net_r"], r["holdout_net_r"]))
    if not any(x["verdict"] in ("USE", "AVOID") for x in out["rows"]):
        ln.append("No zone has a USE or AVOID word yet (30+ cases, 10+ in TRAIN and in HOLDOUT, 3+ coins, same sign in both). The Brain keeps collecting.")
    if out["skipped"]:
        ln.append("%d coin(s) left out: %s." % (len(out["skipped"]), ", ".join("%s (%s)" % (s["symbol"], s["why"]) for s in out["skipped"][:3])))
    return ln


def build(data_dir, interval="5m", now=None):
    p = cache_path(data_dir, interval)
    if not os.path.isfile(p):
        return {"ready": False, "interval": interval, "lines": ["The zone study has not been run yet. In Termux: cd ~/owl_code/backend && export OWL_DATA_DIR=$(cat ~/.owl_data_dir) && python3 v2_bt_zonestudy.py run"], "note": "not run yet"}
    try:
        with open(p) as f:
            out = json.load(f)
    except (OSError, ValueError):
        return {"ready": False, "interval": interval, "lines": ["The saved zone study could not be read. Run it again."], "note": "unreadable"}
    now = int(time.time() if now is None else now)
    out.update({"ready": True, "age_hours": round((now - out.get("made_ts", now)) / 3600.0, 1), "lines": lines_of(out)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "report"))
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--interval", default="5m", choices=("3m", "5m"))
    a = ap.parse_args(argv)
    if a.cmd == "run":
        run_study(a.data, a.interval)
    print("\n".join(build(a.data, a.interval)["lines"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
