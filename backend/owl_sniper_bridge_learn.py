"""owl_sniper_bridge_learn.py - OwlSniper LEARN BRIDGE, the learner (Part 9 / FILE 12, second half). READ ONLY: nothing is written, no network, no order code.
It joins the three steps (src -> replay -> label) and lets the win-chance model of owl_sniper_prob.py learn from WINS AND LOSSES of Dual Bot, Brain and the main bot (every loss teaches "do not take this", every win "take this").
Why a new file: owl_sniper_prob.py is 273 lines after its small edit (net unit R + learn_bridge) and the limit is 300, so the data handling sits here.
Rules (nothing is guessed):
  1. Same signal from two bots (same coin, interval, side and candle) is counted ONCE (order dual, brain, main): two bots on one signal are not two proofs.
  2. TIME split, never random: the newest TEST_FRAC (30%) of the whole days = TEST. A TRAIN trade whose result came after the TEST start is dropped (embargo), so no TRAIN label can see TEST candles.
  3. Fewer than MIN_DAYS whole days = NOT_ENOUGH_DATA. Fewer than 30 TRAIN trades or all the same result = no model (owl_sniper_prob says so in plain words).
  4. Results are in R (price move / the trade's own stop, after fee + slippage), NOT in USDT. Sources are shown apart on the TEST days (leverage, size and exit differ), never one total.
  5. The result is a BRIDGE model: floor_verified stays False and real_gate False. It can feed LEARN (paper) only. The REAL 85% gate still needs the Sniper's own TEST proof (FLOOR 0.85 is not touched).
Answer of build(): state (OK / NOT_ENOUGH_DATA / NO_EXAMPLES), counts per source at every step, skipped reasons, split, learn (the prob result without the weights' noise), per_source TEST table, lines (plain English).
Run (Termux, optional):  python3 backend/owl_sniper_bridge_learn.py [--data DIR] [--since-days N] [--limit N] [--sources dual,brain,main]  -> JSON.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_bridge_label as LB
import owl_sniper_bridge_replay as RP
import owl_sniper_bridge_src as B
import owl_sniper_engine_c1 as C
import owl_sniper_prob as P
import owl_sniper_tf as TF

VERSION = "owl_sniper_bridge_learn 1 (Part 9)"
TEST_FRAC, MIN_DAYS = C.TEST_FRAC, C.MIN_DAYS


def dedupe(examples):
    """One example per (coin, interval, side, signal candle). The first of the order dual, brain, main stays. -> (examples, n_dropped)."""
    rank, seen, out = {s: i for i, s in enumerate(B.SOURCES)}, set(), []
    for e in sorted(examples, key=lambda x: (rank.get(x["source"], 9), x["entry_ts"])):
        k = (e["symbol"], e["tf"], e["side"], round(e["entry_ts"] / TF.step(e["tf"])))
        if k not in seen:
            seen.add(k)
            out.append(e)
    out.sort(key=lambda x: x["entry_ts"])
    return out, len(examples) - len(out)


def to_trades(examples, taken_only=False):
    """Examples (row + label, from owl_sniper_bridge_label.join) -> the trade shape of owl_sniper_prob: feat, win, net_r."""
    return [{"uid": e["uid"], "source": e["source"], "entry_ts": e["entry_ts"], "feat": e["feat"], "win": bool(e["label"]["win"]), "net_r": e["label"]["r_net"],
             "secs": e["label"]["secs_to_result"] or 0} for e in examples if not taken_only or e["label"].get("taken", True)]


def split(trades):
    """-> (train, test, cut_ts, days). TEST = the newest whole days (about TEST_FRAC of the trades); TRAIN keeps only trades that were finished before the TEST start."""
    ts = sorted(trades, key=lambda t: t["entry_ts"])
    days = len({C.day_of(t["entry_ts"]) for t in ts})
    if len(ts) < 2 or days < MIN_DAYS:
        return ts, [], None, days
    cut = C.day_of(ts[int(len(ts) * (1.0 - TEST_FRAC))]["entry_ts"]) * 86400
    return [t for t in ts if t["entry_ts"] + t["secs"] < cut], [t for t in ts if t["entry_ts"] >= cut], cut, days


def per_source(model, test):
    """TEST days, each source apart: n, win rate, mean R, and the mean win chance the model gave (a model that is fair gives about the real win rate)."""
    out = {}
    for s in B.SOURCES:
        ts = [t for t in test if t["source"] == s]
        if ts:
            w = sum(1 for t in ts if t["win"])
            out[s] = {"n": len(ts), "wins": w, "losses": len(ts) - w, "win_rate": round(w / float(len(ts)), 4), "mean_r": round(sum(t["net_r"] for t in ts) / len(ts), 4),
                      "model_mean": round(sum(P.predict(model, t["feat"]) for t in ts) / len(ts), 4) if model else None}
    return out


def learn_from_examples(examples, floor=0.85, taken_only=False, keep_model=False):
    """Pure (no disk): examples -> {state, split, learn, per_source, lines}. The model is a bridge model (see the rules above). keep_model=True keeps the weights in out["learn"]["model"] (for a later LEARN gate); the route never sends them."""
    ex, dup = dedupe(examples)
    trades = to_trades(ex, taken_only)
    train, test, cut, days = split(trades)
    out = {"version": VERSION, "state": "OK", "examples": len(examples), "duplicates_dropped": dup, "used": len(trades), "days": days, "min_days": MIN_DAYS,
           "split": {"train": len(train), "test": len(test), "test_from_ts": cut, "embargo_dropped": len(trades) - len(train) - len(test) if cut else 0}, "learn": None, "per_source": {}, "lines": []}
    L = out["lines"]
    if not trades:
        out["state"] = "NO_EXAMPLES"
        L.append("No bridge examples yet: no closed trade of Dual / Brain / main bot could be matched with saved candles. Check the candle history (v2_candles_deep.py).")
        return out
    if cut is None:
        out["state"] = "NOT_ENOUGH_DATA"
        L.append("NOT ENOUGH DATA: %d trades on %d whole days (need %d days to keep newest days unseen for the check). No bridge model is learned." % (len(trades), days, MIN_DAYS))
        return out
    res = P.learn_bridge(train, test, floor)
    out["per_source"] = per_source(res["model"], test)
    out["learn"] = res if keep_model else {k: v for k, v in res.items() if k != "model"}
    L.append("Bridge learning (paper / LEARN only): %d trades used (%d same-signal duplicates dropped), TRAIN %d, TEST %d unseen days, results in R after fees." % (len(trades), dup, len(train), len(test)))
    for ln in res["lines"]:                                   # the prob lines talk about the REAL gate; here the model is only a bridge model
        ln = ln.replace(" No signal can pass.", "").replace(" The floor is never lowered.", "")
        L.append(("BRIDGE RESULT: the 85%% level %s on these TEST days (R, other bots' trades). This does not change the REAL gate." % ("was reached" if res["bridge_floor_ok"] else "was not reached")) if ln.startswith("RESULT:") else ln)
    for s, v in out["per_source"].items():
        L.append("TEST %s: %d trades, %d won, %d lost (%.0f%%), mean %+.2f R." % (s, v["n"], v["wins"], v["losses"], 100.0 * v["win_rate"], v["mean_r"]))
    L.append("This is a bridge model: it never opens the REAL gate (85% floor needs the Sniper's own TEST days).")
    if not res["ok"]:
        out["state"] = "NOT_ENOUGH_DATA"
    return out


def load_examples(d, limit=0, since_days=None, sources=B.SOURCES, now=None):
    """src -> replay -> label -> join. Read only. -> (examples, parts). Part 10 (Risk Box) reads the examples; build() below reads the counts."""
    since = (time.time() if now is None else now) - since_days * 86400 if since_days else None
    got = B.collect(d, sources, since)
    recs = got["records"][-limit:] if limit > 0 else got["records"]
    rp = RP.replay(d, recs)
    lb = LB.label_all(d, recs, rp["rows"], now)
    return LB.join(rp["rows"], lb["labels"]), {"got": got, "recs": recs, "rp": rp, "lb": lb}


def build(d, limit=0, since_days=None, sources=B.SOURCES, now=None, floor=0.85):
    """Everything from the saved files: src -> replay -> label -> join -> learn. Never raises; read only. -> dict for the route and the CLI."""
    t0 = time.time()
    ex, x = load_examples(d, limit, since_days, sources, now)
    recs, rp, lb = x["recs"], x["rp"], x["lb"]
    out = learn_from_examples(ex, floor)
    srcs = {}
    for s in sources:
        n = lambda xs: sum(1 for x in xs if x["source"] == s)
        srcs[s] = {"records": n(recs), "rows": n(rp["rows"]), "labels": n(lb["labels"]), "examples": n(ex)}
    out.update({"records": len(recs), "by_source": srcs, "replay_skipped": rp["skipped"], "label_skipped": lb["skipped"], "src_info": x["got"]["by_source"], "limit": limit, "seconds": round(time.time() - t0, 2)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper bridge learner: wins AND losses of Dual / Brain / main bot -> bridge win-chance model (read only)")
    ap.add_argument("--data", default=B.default_dir())
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sources", default=",".join(B.SOURCES))
    a = ap.parse_args(argv)
    res = build(a.data, a.limit, a.since_days, tuple(s for s in a.sources.split(",") if s in B.SOURCES))
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
