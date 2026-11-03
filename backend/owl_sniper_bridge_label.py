"""owl_sniper_bridge_label.py - OwlSniper LEARN BRIDGE, step 3 of 3 (Part 8 / FILE 11). READ ONLY: the market store is opened read-only, nothing is written, no network, no order code.
Step 1 (owl_sniper_bridge_src.py) = one flat record per closed trade. Step 2 (owl_sniper_bridge_replay.py) = the feature row at the signal candle (no look-ahead).
This step puts the LABELS: it looks at the candles AFTER the entry and says what the trade really did. It is the ONLY place of the bridge that looks forward, and it never feeds anything back into a feature row.
The label does NOT use the bot's own exit and NEVER net_roi / pnl_usdt (bots differ in leverage, size and exit). Every source is judged the same way, in price % and in R:
  1R = the trade's own stop distance in % of entry (record.stop_pct). If the bot saved no stop, the Sniper's own stop line on that candle is used (risk_src = "sniper_line"). No stop at all = skipped.
  Walk the candles from the first one that opens at or after entry_ts, at most HOLD (the engine's MAX_HOLD = 30) candles. Stop = entry -+ 1R, target = entry +- TARGET_R x 1R (2R).
  If one candle touches both the stop and a target, the STOP counts first (the bad case, same rule as owl_sniper_barriers). No touch within HOLD = TIME: closed at the close of the last candle.
  r_net = gross R minus the round trip cost (fee + slippage of owl_sniper_engine_c1.cost_pct) divided by 1R. win = r_net > 0.
A label: uid, source, symbol, tf, side, entry_ts, risk_pct, risk_src, result (STOP / TARGET / TIME), win, r_gross, r_net, hit_1r, hit_2r (before the stop), mfe_r, mae_r, mfe_pct, mae_pct (best / worst price move up to the result candle, in price % and in R; mae is a positive number),
  bars (candles until the result, the result candle counts as 1), secs_to_result (until the END of the result candle: a touch inside a candle is not timed finer), bars_to_mfe, bars_seen, taken.
Skipped and counted by reason (nothing is guessed): tf_unknown, tf_not_supported, no_store, no_candles, no_stop, bad_stop, candle_gap (first candle after the entry is more than 1 candle away), too_recent (not enough time has passed to know), incomplete (candles end or have a hole before any result), bad_candles.
Run (Termux, optional):  python3 backend/owl_sniper_bridge_label.py [--data DIR] [--since-days N] [--limit N] [--sources dual,brain,main] [--sample N]  -> JSON summary.
Part 9 (FILE 12) joins rows + labels with join() and teaches the win-chance model from wins AND losses."""
import argparse
import bisect
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_bridge_replay as RP
import owl_sniper_bridge_src as B
import owl_sniper_engine_c1 as C
import owl_sniper_feed as F
import owl_sniper_tf as TF
import v2_defs as D
import v2_setup_finder as SF

VERSION = "owl_sniper_bridge_label 1 (Part 8)"
HOLD = C.MAX_HOLD          # candles looked at after the entry (same as the Sniper's own time barrier)
TARGET_R = 2.0             # the profit line, in units of 1R
MIN_RISK, MAX_RISK = 0.02, 25.0   # % of entry; outside this the stop is damaged data, not a real stop
MAX_START_STEPS = 1.0      # the first candle after the entry may open at most this many candles later than entry_ts


def risk_of(rec, row):
    """-> (risk_pct, source) or (None, reason). The trade's own stop first, the Sniper's own stop line as the second choice."""
    v, src = rec.get("stop_pct"), "trade"
    if not v and row:
        v, src = (row.get("extra") or {}).get("stop_line_pct"), "sniper_line"
    if not v:
        return None, "no_stop"
    return (float(v), src) if MIN_RISK <= float(v) <= MAX_RISK else (None, "bad_stop")


def label_one(rec, risk_pct, risk_src, fut, step, hold=HOLD, target_r=TARGET_R):
    """The label of ONE trade from its forward candles (open_ts, o, h, l, c, v), gap-free, oldest first, fut[0] = first candle after the entry. -> (label, None) or (None, 'incomplete')."""
    e, d = rec["entry_price"], 1.0 if rec["side"] == "LONG" else -1.0
    stop, tgt = e * (1.0 - d * risk_pct / 100.0), e * (1.0 + d * target_r * risk_pct / 100.0)
    best = worst = 0.0          # best / worst move in price %, from the entry price
    k_best, hit1, result, k_end, px = 0, False, None, None, None
    for k, cd in enumerate(fut[:hold]):
        hi, lo = (cd[2], cd[3]) if d > 0 else (cd[3], cd[2])           # hi = the favourable extreme of this candle, lo = the adverse extreme
        adv = d * (lo / e - 1.0) * 100.0
        fav = d * (hi / e - 1.0) * 100.0
        if adv <= -risk_pct:                                           # the stop is touched first (also when the same candle touches a target)
            worst, result, k_end, px = min(worst, -risk_pct), "STOP", k, stop
            break
        worst = min(worst, adv)
        if fav > best:
            best, k_best = fav, k
        hit1 = hit1 or fav >= risk_pct
        if fav >= target_r * risk_pct:
            result, k_end, px = "TARGET", k, tgt
            break
    if result is None:
        if len(fut) < hold:
            return None, "incomplete"
        result, k_end, px = "TIME", hold - 1, fut[hold - 1][4]
    gross = d * (px / e - 1.0) * 100.0 / risk_pct
    net = gross - C.cost_pct() / risk_pct
    return {"uid": rec["uid"], "source": rec["source"], "symbol": rec["symbol"], "tf": rec["tf"], "side": rec["side"], "entry_ts": rec["entry_ts"],
            "risk_pct": round(risk_pct, 4), "risk_src": risk_src, "result": result, "win": net > 0, "r_gross": round(gross, 4), "r_net": round(net, 4),
            "hit_1r": hit1, "hit_2r": result == "TARGET", "mfe_r": round(best / risk_pct, 4), "mae_r": round(-worst / risk_pct, 4),
            "mfe_pct": round(best, 4), "mae_pct": round(-worst, 4), "bars": k_end + 1, "secs_to_result": round(fut[k_end][0] + step - rec["entry_ts"], 3),
            "bars_to_mfe": k_best + 1, "bars_seen": min(len(fut), hold), "taken": rec.get("taken", True)}, None


def _group(con, sym, tf, items, now, hold, bump, out):
    """All trades of ONE coin + interval: the candles are read once, every trade takes its own forward window."""
    step = TF.step(tf)
    t_lo, t_hi = min(r["entry_ts"] for r, _k, _s in items), max(r["entry_ts"] for r, _k, _s in items)
    raw = D.candles_from_store(con, sym, TF.base(tf), t_lo - TF.step(TF.base(tf)), t_hi + (hold + 2) * step)
    good, _bad = D.clean_candles(raw, TF.base(tf))
    runs = [x for x in (TF.aggregate(r, tf) for r in SF.runs(good, TF.base(tf))) if x]
    if not runs:
        for r, _k, _s in items:
            bump(r, "no_candles")
        return
    for r, risk, src in items:
        e_ts, fut = r["entry_ts"], None
        for run in runs:                                              # the run that holds the first candle at or after the entry
            stamps = [c[0] for c in run]
            j = bisect.bisect_left(stamps, e_ts - 1e-6)
            if j < len(run):
                if run[j][0] - e_ts > MAX_START_STEPS * step + 1e-6:
                    break
                fut = run[j:j + hold]
                break
        if fut is None:
            bump(r, "candle_gap" if any(run[0][0] > e_ts for run in runs) else "no_candles")
            continue
        lab, why = label_one(r, risk, src, fut, step, hold)
        if lab is None:
            bump(r, "too_recent" if now - e_ts < (hold + 1) * step else why)
        else:
            out.append(lab)


def label_all(d, records, rows=None, now=None, hold=HOLD):
    """Bridge records (+ optional replay rows, used only for the stop fallback) -> {labels (oldest first), skipped {reason: n}, by_source {name: {records, labels, skipped}}}. Never raises."""
    now = time.time() if now is None else now
    by = {}
    out = {"version": VERSION, "labels": [], "skipped": {}, "by_source": by}
    rmap = {x["uid"]: x for x in rows or []}

    def bump(r, why):
        b = by.setdefault(r["source"], {"records": 0, "labels": 0, "skipped": {}})
        b["skipped"][why] = b["skipped"].get(why, 0) + 1
        out["skipped"][why] = out["skipped"].get(why, 0) + 1

    groups = {}
    for r in records:
        by.setdefault(r["source"], {"records": 0, "labels": 0, "skipped": {}})["records"] += 1
        if not r.get("tf"):
            bump(r, "tf_unknown")
        elif r["tf"] not in TF.SUPPORTED:
            bump(r, "tf_not_supported")
        else:
            risk, src = risk_of(r, rmap.get(r["uid"]))
            if risk is None:
                bump(r, src)
            else:
                groups.setdefault((r["symbol"], r["tf"]), []).append((r, risk, src))
    con = None
    try:
        con = F.open_ro(d) if groups else None
        for (sym, tf), items in groups.items():
            if con is None:
                for r, _k, _s in items:
                    bump(r, "no_store")
                continue
            try:
                _group(con, sym, tf, items, now, hold, bump, out["labels"])
            except Exception:                                         # one bad coin never stops the others
                for r, _k, _s in items:
                    bump(r, "bad_candles")
    finally:
        if con is not None:
            con.close()
    out["labels"].sort(key=lambda x: x["entry_ts"])
    for x in out["labels"]:
        by[x["source"]]["labels"] += 1
    return out


def join(rows, labels):
    """Feature rows + labels by uid -> examples (what the learner of Part 9 reads). Rows without a label, or labels without a row, are left out. Oldest first."""
    lab = {x["uid"]: x for x in labels}
    return [dict(r, label=lab[r["uid"]]) for r in rows if r["uid"] in lab]


def summary(res):
    """Small printable view. Sources stay apart; wins / losses / mean r_net are per source, never one total."""
    per = {}
    for name, info in res["by_source"].items():
        ls = [x for x in res["labels"] if x["source"] == name]
        n, w = len(ls), sum(1 for x in ls if x["win"])
        per[name] = dict(info, wins=w, losses=n - w, win_pct=round(100.0 * w / n, 2) if n else None, mean_r_net=round(sum(x["r_net"] for x in ls) / n, 4) if n else None,
                         results={k: sum(1 for x in ls if x["result"] == k) for k in ("STOP", "TARGET", "TIME")}, from_trade_stop=sum(1 for x in ls if x["risk_src"] == "trade"))
    return {"version": res["version"], "labels": len(res["labels"]), "skipped": res["skipped"], "by_source": per,
            "note": "READ ONLY. Same rule for every source: stop = 1R (the trade's own stop), target = %gR, %d candles, stop first when both are touched, after fee + slippage. win_pct is NOT the bot's own win rate." % (TARGET_R, HOLD)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper bridge step 3: labels (win / loss, R, MAE, MFE, time) from the candles after each entry (read only)")
    ap.add_argument("--data", default=B.default_dir())
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--limit", type=int, default=0, help="only the newest N records (keeps the phone light)")
    ap.add_argument("--sources", default=",".join(B.SOURCES))
    ap.add_argument("--sample", type=int, default=0)
    a = ap.parse_args(argv)
    srcs = tuple(s for s in a.sources.split(",") if s in B.SOURCES)
    got = B.collect(a.data, srcs, time.time() - a.since_days * 86400 if a.since_days else None)
    recs = got["records"][-a.limit:] if a.limit > 0 else got["records"]
    rows = RP.replay(a.data, recs)["rows"]
    res = label_all(a.data, recs, rows)
    out = summary(res)
    out["rows_with_label"] = len(join(rows, res["labels"]))
    if a.sample > 0:
        out["sample"] = res["labels"][-a.sample:]
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
