"""v2_bt_limits.py - Part 89b: BRAIN TRADER SQUEEZE STUDY + STARTING-LIMITS STUDY (backend). Two questions on the owner's saved candles, same honest style as Part 89a:
(1) SQUEEZE: after a squeeze (state CONSOLIDATION, 3+ candles in a row) ENDS, what did the break do? Per break side (UP / DOWN) and per group (squeeze length, the market state the squeeze ended in, volume tag): forward move after 3 / 6 / 12 / 24 candles
    (median, in R = SD units, + is good for the break side), how often a close went BACK across the SD middle within 6 candles (a failed break), the HYPOTHETICAL BT-01 trade from that candle (mean net R, TRAIN and HOLDOUT apart) and the BASELINE (ordinary candles, every 6th).
(2) LIMITS: the BT-01 starting values (stop 1.0 SD, target 1.5 R, 24 candles, stop distance 0.3-2.0 % of price) are NV (not validated). Every candle where BT-01 says OPEN right away is replayed with other values side by side:
    stop 0.75 / 1.0 / 1.25 / 1.5 SD x target 1.0 / 1.5 / 2.0 / 3.0 R x hold 12 / 24 / 48 candles, plus 4 other stop-distance bands. Same entries for every row; money = net % of the entry price per trade (fee + slippage taken), so rows with different stops are comparable.
    A row says BETTER CANDIDATE only when, on the entries both rules took: 30+ trades, 10+ in TRAIN and in HOLDOUT, 3+ coins, better than BT-01 in BOTH TRAIN and HOLDOUT, and the gain is at least 0.03 percentage points of price per trade. A BETTER CANDIDATE is only an idea for a future BT-02.
HONEST LIMITS (said on the screen): the coins are the collector's top gainers / losers (not a random sample); trades that BT-01 opens only AFTER a wait are not replayed (only the ones it opens at once, one entry per 24 candles per coin); 50+ rows are checked at once so a few look good by luck.
Nothing here changes BT-01, the live bot or any rule: a change needs a new version BT-02 AND the owner's OK. No win rate, no forecast.
Writes ONLY its own cache file v2_bt_limits_<interval>.json in the data folder (atomic); reads the market store read-only; the route only reads that file. No network, no order code, no trading import.
Run (Termux, optional; set OWL_DATA_DIR first):  python3 backend/v2_bt_limits.py run [--interval 5m]  |  report [--interval 5m]. The Part 89a-auto runner also runs it every 6 hours by itself."""
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
import v2_bt_zonestudy as ZS
import v2_replay as V
import v2_scalp_ind as IND

VERSION = "v2_bt_limits 1 (Part 89b)"
STOPS, TARGETS, HOLDS = (0.75, 1.0, 1.25, 1.5), (1.0, 1.5, 2.0, 3.0), (12, 24, 48)
BANDS = ((0.3, 2.0), (0.2, 2.0), (0.3, 3.0), (0.5, 2.0), (0.3, 1.5))
REF, REF_BAND = (R.STOP_SD, R.TARGET_R, R.MAX_HOLD), (R.RISK_MIN_PCT, R.RISK_MAX_PCT)
MAXH, SQ_MIN, BACK, MIN_GAIN, SHOW = max(HOLDS), 3, 6, 0.03, 40
LIMIT = ("The coins are the collector's top gainers / losers, not a random sample of the market. Only the trades BT-01 opens at once are replayed (not the ones it opens after a wait), one entry per 24 candles per coin. "
         "Many rows are checked at once, so a few look good by luck. BETTER CANDIDATE is only an idea for a future BT-02. Nothing is applied: BT-01 stays as it is until a new version is made with your OK.")


def cache_path(data_dir, interval):
    if interval not in ("3m", "5m"):
        raise ValueError("interval must be 3m or 5m")
    return os.path.join(data_dir, "v2_bt_limits_%s.json" % interval)


def _len_bucket(n):
    return "SHORT" if n < 12 else "MEDIUM" if n < 24 else "LONG"


def _squeeze_end(run, ctx, t, i, n, sd, cut):
    """A squeeze of n candles ended at candle i -> one row (break side from the SD position of the close), or None."""
    u = t.get("sd_units")
    if not u or not sd:
        return None
    side, sg = ("LONG", 1.0) if u > 0 else ("SHORT", -1.0)
    c0, mean = float(run[i][4]), ctx["ind"]["sd_mean"]
    back = any(mean[i + j] is not None and sg * (float(run[i + j][4]) - mean[i + j]) < 0 for j in range(1, BACK + 1))
    return {"dir": "UP" if u > 0 else "DOWN", "len": _len_bucket(n), "end": t["market_state"], "vol": t.get("volume_tag") or "NA", "sample": V.sample_of(run[i][0], cut), "back": back,
            "fwd": {h: sg * (float(run[i + h][4]) - c0) / sd for h in ZS.HORIZONS}, "net": ZS._hyp(run, i, side, sd)}


def _replay(run, i, side, sd):
    """ONE entry (close of candle i) replayed with every stop x target x hold -> {(stop, target, hold): (net % of price, 'S' stop / 'T' target / 'H' time)}. Stop and target in the same candle = STOP. Needs candles up to i + MAXH."""
    e, lg, cost, sg, out = float(run[i][4]), side == "LONG", V.cost_pct(), 1.0 if side == "LONG" else -1.0, {}
    for s in STOPS:
        for tg in TARGETS:
            stop, tgt = (e - s * sd, e + tg * s * sd) if lg else (e + s * sd, e - tg * s * sd)
            ev = None
            for j in range(1, MAXH + 1):
                hi, lo = float(run[i + j][2]), float(run[i + j][3])
                if (lo <= stop) if lg else (hi >= stop):
                    ev = (j, -s * sd / e * 100.0, "S")
                    break
                if (hi >= tgt) if lg else (lo <= tgt):
                    ev = (j, tg * s * sd / e * 100.0, "T")
                    break
            for h in HOLDS:
                if ev and ev[0] <= h:
                    out[(s, tg, h)] = (ev[1] - cost, ev[2])
                else:
                    out[(s, tg, h)] = (sg * (float(run[i + h][4]) - e) / e * 100.0 - cost, "H")
    return out


def study_coin(run):
    """ONE coin -> {'ends': squeeze ends, 'base': ordinary candles, 'entries': BT-01 immediate entries with their replays} or None (too few candles)."""
    need = IND.need_candles()
    if len(run) < need + MAXH + 1:
        return None
    ctx = ST.prepare(run)
    cut = V.holdout_cut([c[0] for c in run])
    ends, base, entries, n, skip, k = [], [], [], 0, -1, 0
    for i in range(need - 1, len(run) - ZS.MAXH):
        t = ST.tags(ctx, i)
        if not t["ready"]:
            n = 0
            continue
        sd, sample = ctx["ind"]["sd_std"][i], V.sample_of(run[i][0], cut)
        if t["market_state"] == "CONSOLIDATION":
            n += 1
        else:
            if n >= SQ_MIN:
                row = _squeeze_end(run, ctx, t, i, n, sd, cut)
                if row:
                    ends.append(row)
            n = 0
        if k % ZS.BASE_STEP == 0 and sd:
            base.append({"sample": sample, "net": {s: ZS._hyp(run, i, s, sd) for s in ZS.SIDES}})
        k += 1
        if i > skip and i + MAXH < len(run) and sd and sd / float(run[i][4]) < 0.5:
            d = R.decide(ctx, t, i)
            if d["decision"] in ("OPEN_LONG", "OPEN_SHORT"):
                entries.append({"sample": sample, "sdp": sd / float(run[i][4]) * 100.0, "res": _replay(run, i, d["side"], sd)})
                skip = i + ZS.MAXH
    return {"ends": ends, "base": base, "entries": entries}


def _mean(xs, d=3):
    return round(sum(xs) / len(xs), d) if xs else None


def summarize_squeeze(per):
    bl = {s: {"TRAIN": [], "HOLDOUT": []} for s in ZS.SIDES}
    groups = {}
    for sym, r in per.items():
        for b in r["base"]:
            for s, v in b["net"].items():
                if v is not None:
                    bl[s][b["sample"]].append(v)
        for e in r["ends"]:
            for lab in ("ALL", "len:" + e["len"], "end:" + e["end"], "vol:" + e["vol"]):
                groups.setdefault((e["dir"], lab), []).append((e, sym))
    base = {s: {"n": len(bl[s]["TRAIN"]) + len(bl[s]["HOLDOUT"]), "mean_net_r": _mean(bl[s]["TRAIN"] + bl[s]["HOLDOUT"]), "train": _mean(bl[s]["TRAIN"]), "holdout": _mean(bl[s]["HOLDOUT"])} for s in ZS.SIDES}
    rows = []
    for (dr, lab), xs in groups.items():
        tr = [e["net"] for e, _ in xs if e["sample"] == "TRAIN" and e["net"] is not None]
        ho = [e["net"] for e, _ in xs if e["sample"] == "HOLDOUT" and e["net"] is not None]
        coins, mean = len(set(s for _, s in xs)), _mean(tr + ho)
        b = base["LONG" if dr == "UP" else "SHORT"]["mean_net_r"]
        edge = None if mean is None or b is None else round(mean - b, 3)
        rows.append({"dir": dr, "group": lab, "n": len(xs), "coins": coins, "n_train": len(tr), "n_holdout": len(ho), "went_back": sum(1 for e, _ in xs if e["back"]), "mean_net_r": mean, "train_net_r": _mean(tr), "holdout_net_r": _mean(ho),
                     "edge_vs_baseline_r": edge, "fwd_median_r": {str(h): round(statistics.median([e["fwd"][h] for e, _ in xs]), 3) for h in ZS.HORIZONS}, "verdict": ZS._verdict(len(tr) + len(ho), tr, ho, coins, edge)})
    rows.sort(key=lambda r: (r["group"] != "ALL", -r["n"]))
    return base, [r for r in rows if r["group"] == "ALL" or r["n"] >= ZS.MIN_SPLIT][:SHOW], len(rows)


def _val(e, key, band):
    v = e["res"].get(key)
    return v if v is not None and band[0] <= key[0] * e["sdp"] <= band[1] else None


def _lverdict(n, dtr, dho, coins, gain):
    if n < ZS.MIN_N or len(dtr) < ZS.MIN_SPLIT or len(dho) < ZS.MIN_SPLIT or coins < ZS.MIN_COINS:
        return "NOT ENOUGH DATA"
    a, b = sum(dtr) / len(dtr), sum(dho) / len(dho)
    if a > 0 and b > 0:
        return "BETTER CANDIDATE" if gain >= MIN_GAIN else "NO CLEAR GAIN"
    return "WORSE" if a < 0 and b < 0 else "MIXED"


def _limit_row(entries, key, band, kind):
    own = [(e, c, _val(e, key, band)) for e, c in entries]
    own = [(e, c, v) for e, c, v in own if v is not None]
    com = [(e, c, v[0] - _val(e, REF, REF_BAND)[0]) for e, c, v in own if _val(e, REF, REF_BAND) is not None]
    dtr, dho = [d for e, c, d in com if e["sample"] == "TRAIN"], [d for e, c, d in com if e["sample"] == "HOLDOUT"]
    m, gain = _mean([v[0] for _, _, v in own]), _mean([d for _, _, d in com]) or 0.0
    return {"kind": kind, "stop_sd": key[0], "target_r": key[1], "hold": key[2], "band": list(band), "n": len(own), "n_common": len(com), "coins": len(set(c for _, c, _ in com)), "mean_net_pct": m,
            "usdt_per_trade": None if m is None else round(m * R.SIZE_USDT / 100.0, 3), "diff_pct": gain, "train_diff": _mean(dtr), "holdout_diff": _mean(dho),
            "exits": {x: sum(1 for _, _, v in own if v[1] == x) for x in "STH"}, "verdict": "REFERENCE" if kind == "ref" else _lverdict(len(com), dtr, dho, len(set(c for _, c, _ in com)), gain)}


def summarize_limits(per):
    entries = [(e, sym) for sym, r in per.items() for e in r["entries"]]
    rows = [_limit_row(entries, REF, REF_BAND, "ref")]
    rows += [_limit_row(entries, (s, t, h), REF_BAND, "limits") for s in STOPS for t in TARGETS for h in HOLDS if (s, t, h) != REF]
    rows += [_limit_row(entries, REF, b, "band") for b in BANDS if b != REF_BAND]
    rows.sort(key=lambda r: (r["kind"] != "ref", r["verdict"] != "BETTER CANDIDATE", -(r["diff_pct"] or 0)))
    return rows, len(entries)


def run_study(data_dir, interval="5m", now=None):
    now = int(time.time() if now is None else now)
    per, skipped = {}, []
    for sym in W.followed(data_dir, now):
        try:
            r = study_coin(M.load_run(data_dir, sym, interval))
        except Exception as e:                                     # one coin never stops the study
            skipped.append({"symbol": sym, "why": "error %s" % type(e).__name__})
            continue
        if r is None:
            skipped.append({"symbol": sym, "why": "too few gap-free candles (need %d)" % (IND.need_candles() + MAXH + 1)})
        else:
            per[sym] = r
    base, srows, sgroups = summarize_squeeze(per)
    lrows, n_ent = summarize_limits(per)
    out = {"framework": VERSION, "interval": interval, "made_ts": now, "coins": sorted(per), "skipped": skipped, "squeeze_ends": sum(len(r["ends"]) for r in per.values()), "squeeze_groups_checked": sgroups,
           "baseline": base, "squeeze_rows": srows, "entries": n_ent, "limit_rows": lrows, "limit_rows_checked": len(lrows) - 1, "reference": {"stop_sd": REF[0], "target_r": REF[1], "hold": REF[2], "band": list(REF_BAND), "version": R.BT_VERSION},
           "horizons": list(ZS.HORIZONS), "limit": LIMIT}
    p = cache_path(data_dir, interval)
    with open(p + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(p + ".tmp", p)
    return out


def lines_of(out):
    ln = ["Squeeze study on %d coins: %d squeeze ends, %d groups checked. Baseline (any ready candle) LONG %s R, SHORT %s R net per trade." % (len(out["coins"]), out["squeeze_ends"], out["squeeze_groups_checked"], out["baseline"]["LONG"]["mean_net_r"], out["baseline"]["SHORT"]["mean_net_r"])]
    for r in [x for x in out["squeeze_rows"] if x["verdict"] in ("USE", "AVOID")][:3]:
        ln.append("%s candidate: squeeze break %s, %s: %d cases from %d coins, mean net %+.2f R (TRAIN %+.2f, HOLDOUT %+.2f), %d went back inside 6 candles." % (r["verdict"], r["dir"], r["group"], r["n"], r["coins"], r["mean_net_r"], r["train_net_r"], r["holdout_net_r"], r["went_back"]))
    if not any(x["verdict"] in ("USE", "AVOID") for x in out["squeeze_rows"]):
        ln.append("No squeeze group has a USE or AVOID word yet (30+ cases, 10+ in TRAIN and in HOLDOUT, 3+ coins, same sign in both). The Brain keeps collecting.")
    ref = out["limit_rows"][0]
    ln.append("Limits study: %d BT-01 entries replayed. BT-01 now (stop %.2f SD, target %.1f R, %d candles): %s%% of price per trade after cost (%s USDT per 100 USDT trade)." % (out["entries"], ref["stop_sd"], ref["target_r"], ref["hold"], ref["mean_net_pct"], ref["usdt_per_trade"]))
    better = [x for x in out["limit_rows"] if x["verdict"] == "BETTER CANDIDATE"][:3]
    for r in better:
        ln.append("BT-02 idea (not applied): %s stop %.2f SD, target %.1f R, %d candles, band %.1f-%.1f%%: %+.3f points of price per trade better than BT-01 on %d common trades (TRAIN %+.3f, HOLDOUT %+.3f)." % (r["kind"], r["stop_sd"], r["target_r"], r["hold"], r["band"][0], r["band"][1], r["diff_pct"], r["n_common"], r["train_diff"], r["holdout_diff"]))
    if not better:
        ln.append("No other limit beats BT-01 yet in both TRAIN and HOLDOUT with enough trades. BT-01 stays.")
    ln.append("%d limit rows were checked at once, so a few look good by luck. Nothing is applied without your OK." % out["limit_rows_checked"])
    if out["skipped"]:
        ln.append("%d coin(s) left out: %s." % (len(out["skipped"]), ", ".join("%s (%s)" % (s["symbol"], s["why"]) for s in out["skipped"][:3])))
    return ln


def build(data_dir, interval="5m", now=None):
    p = cache_path(data_dir, interval)
    if not os.path.isfile(p):
        return {"ready": False, "interval": interval, "lines": ["The squeeze and limits study has not been run yet. It runs by itself every 6 hours once the Brain auto-runner is on."], "note": "not run yet"}
    try:
        with open(p) as f:
            out = json.load(f)
    except (OSError, ValueError):
        return {"ready": False, "interval": interval, "lines": ["The saved study could not be read. It will be made again by itself."], "note": "unreadable"}
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
