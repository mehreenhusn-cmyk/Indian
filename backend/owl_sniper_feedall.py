"""owl_sniper_feedall.py - OwlSniper FEED EVERYTHING, part 1 of 2 (R2). READ ONLY, PAPER ONLY: reads saved files only, writes nothing, no network, no order code.
Owner wish: ALL old trades + ALL backtest / study results go to the Sniper in ONE table, so it needs less time to learn.
  EXAMPLES  = closed trades of Dual, Brain and Main bot, replayed on saved candles (no look-ahead) and labelled the same way for every bot (owl_sniper_bridge_learn.load_examples).
              The SAME signal (coin, interval, side, signal candle) taken by two bots counts ONCE; every bot that had it stays in `sources`. Books are never added together.
  KNOWLEDGE = EVERY backtest / study verdict (owl_sniper_prior_src.collect: all families, not only SD levels), each with its source tag. These are hints, not trades: they never count as examples.
  WIDE      = each example also gets the wide number list of owl_sniper_feedall_feat (20 numbers instead of 4).
Honest: nothing is guessed. Trades whose candles are missing are counted in `skipped` with the reason (see owl_sniper_hist.py for which can still be downloaded).
API: build(d, limit=0, since_days=None, now=None, knowledge=True) -> dict, summary(res), table(res) (flat rows for the app). CLI: python3 backend/owl_sniper_feedall.py [--data DIR] [--since-days N] [--limit N] [--json]"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_bridge_learn as BL
import owl_sniper_bridge_src as B
import owl_sniper_feedall_feat as W
import owl_sniper_tf as TF

VERSION = "owl_sniper_feedall 1 (R2)"
PAPER_ONLY = True


def merge(examples):
    """Same signal from several bots -> ONE example. The first source in the order dual, brain, main stays; `sources` lists all. -> (examples, n_merged)."""
    rank, keep, out = {s: i for i, s in enumerate(B.SOURCES)}, {}, []
    for e in sorted(examples, key=lambda x: (rank.get(x["source"], 9), x["entry_ts"])):
        k = (e["symbol"], e["tf"], e["side"], round(e["entry_ts"] / TF.step(e["tf"])))
        if k in keep:
            if e["source"] not in keep[k]["sources"]:
                keep[k]["sources"].append(e["source"])
            continue
        e = dict(e, sources=[e["source"]])
        keep[k] = e
        out.append(e)
    out.sort(key=lambda x: x["entry_ts"])
    return out, len(examples) - len(out)


def _knowledge(d, now):
    """All prior verdicts with their source tag. Never raises: a failing source is reported, not hidden."""
    try:
        import owl_sniper_prior_src as P
        got = P.collect(d, now=now)
        return {"rows": got["rows"], "counts": got["counts"], "sources": got["sources"]}
    except Exception as e:
        return {"rows": [], "counts": {}, "sources": {"error": {"state": "error", "rows": 0, "note": "%s: %s" % (type(e).__name__, str(e)[:80])}}}


def build(d, limit=0, since_days=None, now=None, knowledge=True):
    """Everything in one dict. Never raises for missing data (empty lists + reasons)."""
    t0 = time.time()
    now = time.time() if now is None else now
    out = {"version": VERSION, "paper_only": True, "examples": [], "knowledge": {"rows": [], "counts": {}, "sources": {}}, "counts": {}, "skipped": {}, "seconds": 0.0}
    try:
        ex, x = BL.load_examples(d, limit, since_days, B.SOURCES, now)
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:100])
        return out
    merged, n_merged = merge(ex)
    miss_total = 0
    for e in merged:
        e["wide"], m = W.wide_vec(e)
        e["wide_missing"] = m
        miss_total += m
    if knowledge:
        out["knowledge"] = _knowledge(d, now)
    rp, lb = x["rp"], x["lb"]
    by = {s: {"records": 0, "examples": 0} for s in B.SOURCES}
    for r in x["recs"]:
        by[r["source"]]["records"] += 1
    for e in ex:
        by[e["source"]]["examples"] += 1
    days = len({int(e["entry_ts"] // 86400) for e in merged})
    out.update({"examples": merged, "skipped": {"replay": rp["skipped"], "label": lb["skipped"]},
                "counts": {"records": len(x["recs"]), "examples_raw": len(ex), "examples": len(merged), "merged_same_signal": n_merged, "days": days,
                           "knowledge_rows": len(out["knowledge"]["rows"]), "wide_numbers": len(W.WIDE_FEATS), "wide_missing_total": miss_total, "by_source": by}})
    out["seconds"] = round(time.time() - t0, 2)
    return out


def table(res):
    """Flat rows for the app (one line per example, small): when, bot(s), coin, side, regime, result in R. No raw feature dumps."""
    return [{"ts": e["entry_ts"], "sources": e.get("sources"), "symbol": e["symbol"], "tf": e["tf"], "side": e["side"], "regime": e.get("regime"),
             "r_net": e["label"].get("r_net"), "win": bool(e["label"].get("win"))} for e in res.get("examples", [])]


def summary(res):
    c = res.get("counts") or {}
    lines = ["%s | examples %s (raw %s, same-signal merged %s) over %s days | knowledge rows %s | %s numbers per example | %ss" % (
        res.get("version"), c.get("examples"), c.get("examples_raw"), c.get("merged_same_signal"), c.get("days"), c.get("knowledge_rows"), c.get("wide_numbers"), res.get("seconds"))]
    for s, b in (c.get("by_source") or {}).items():
        lines.append("  %-6s records %s -> examples %s" % (s, b["records"], b["examples"]))
    for k, v in (res.get("skipped") or {}).get("replay", {}).items():
        lines.append("  skipped (replay) %-18s %s" % (k, v))
    for k, v in (res.get("skipped") or {}).get("label", {}).items():
        lines.append("  skipped (label)  %-18s %s" % (k, v))
    for k, v in (res.get("knowledge") or {}).get("sources", {}).items():
        lines.append("  knowledge %-6s %s %s" % (k, v.get("state"), v.get("note", "")))
    if res.get("error"):
        lines.append("  ERROR " + res["error"])
    return "\n".join(lines)


def _default_dir():
    for k in ("OWL_DATA_DIR",):
        if os.environ.get(k):
            return os.environ[k]
    return os.path.expanduser("~/storage/shared/owl_data")


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper feed-everything table (read only)")
    ap.add_argument("--data", default=_default_dir())
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = build(a.data, a.limit, a.since_days)
    if a.json:
        slim = dict(res, examples=len(res["examples"]), knowledge={"counts": res["knowledge"]["counts"], "sources": res["knowledge"]["sources"]})
        print(json.dumps(slim, indent=1))
    else:
        print(summary(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
