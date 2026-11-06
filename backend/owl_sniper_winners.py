"""owl_sniper_winners.py - WHAT DID THE SNIPER LEARN FROM THE WINNING TRADES? PAPER ONLY, READ ONLY: no network, no order code, nothing is written.
Owner question: "from my past winning trades, what is the Sniper learning? It must learn fast, so I can trust it with 10 USDT."
It takes the SAME examples the learn bridge uses (closed trades of Dual / Brain / main bot, replayed on the saved candles, labelled win / loss in R) and shows, in plain words,
how the WINNERS differed from the LOSERS on the 4 numbers the win-chance model reads (FEATS of owl_sniper_prob). Nothing is invented: a number is shown only when both groups have at least MIN_GROUP trades.
Honest limits written in every answer: this is paper data from other bots, it says what winners had in common, not that the next trade will win, and 10 USDT of real money is the owner's decision (see the graduation checklist).
API: compare(examples) -> dict (pure, no disk); build(d, limit=1500) -> compare(load_examples(d)). CLI: python3 backend/owl_sniper_winners.py [--data DIR]"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "owl_sniper_winners 1 (E4)"
PAPER_ONLY = True
MIN_GROUP = 8          # winners AND losers each need this many trades before a feature is compared
MIN_TOTAL = 30         # below this the whole answer is "too early"
MIN_GAP = 0.15         # difference of the two group means, in standard deviations, below this = "no real difference"
# feature -> (topic, what winners had when the number was HIGHER, when it was LOWER)
NAMES = {
    "z_dir": ("price stretch", "the price stretched further from its average, in the trade direction", "the price stretched less from its average"),
    "hist_dir": ("push behind the move", "a stronger push in the trade direction", "a weaker push in the trade direction"),
    "gap_pct": ("trend width", "a wider gap between the trend lines (a clearer trend)", "a narrower gap between the trend lines (a less clear trend)"),
    "vi_ratio": ("price wildness", "wilder price than normal", "calmer price than normal"),
}


def _mean(xs):
    return sum(xs) / float(len(xs))


def _sd(xs):
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / float(len(xs))) if len(xs) > 1 else 0.0


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf") else None


def compare(examples):
    """examples: [{source, feat{...}, label{win, r_net}}] -> {state, n, wins, losses, win_rate, mean_r, features[], lines[], by_source{}}. Never raises."""
    rows = []
    for e in examples or ():
        try:
            lab = e["label"]
            rows.append({"src": e.get("source"), "win": bool(lab["win"]), "r": float(lab["r_net"]), "f": e.get("feat") or {}})
        except Exception:
            continue
    n = len(rows)
    wins = [x for x in rows if x["win"]]
    loss = [x for x in rows if not x["win"]]
    out = {"version": VERSION, "paper_only": True, "state": "OK", "n": n, "wins": len(wins), "losses": len(loss),
           "win_rate": round(len(wins) / float(n), 4) if n else None, "mean_r": round(_mean([x["r"] for x in rows]), 4) if n else None,
           "features": [], "by_source": {}, "lines": []}
    for s in sorted({x["src"] for x in rows if x["src"]}):
        g = [x for x in rows if x["src"] == s]
        w = sum(1 for x in g if x["win"])
        out["by_source"][s] = {"n": len(g), "wins": w, "win_rate": round(w / float(len(g)), 4)}
    L = out["lines"]
    if n < MIN_TOTAL or len(wins) < MIN_GROUP or len(loss) < MIN_GROUP:
        out["state"] = "TOO_EARLY"
        L.append("Too early to say. Only %d past trades could be studied (%d won, %d lost). At least %d trades with at least %d winners and %d losers are needed." % (n, len(wins), len(loss), MIN_TOTAL, MIN_GROUP, MIN_GROUP))
        return out
    L.append("Studied %d past trades: %d won, %d lost (%.0f%% won, average %+.2f R after fees)." % (n, len(wins), len(loss), 100.0 * out["win_rate"], out["mean_r"]))
    for k, (name, high, low) in NAMES.items():
        a = [_num(x["f"].get(k)) for x in wins]
        b = [_num(x["f"].get(k)) for x in loss]
        a, b = [v for v in a if v is not None], [v for v in b if v is not None]
        if len(a) < MIN_GROUP or len(b) < MIN_GROUP:
            continue
        sd = _sd(a + b)
        gap = (_mean(a) - _mean(b)) / sd if sd > 0 else 0.0
        item = {"feat": k, "name": name, "winners_avg": round(_mean(a), 4), "losers_avg": round(_mean(b), 4), "gap_sd": round(gap, 3), "n_win": len(a), "n_loss": len(b)}
        strong = "clearly" if abs(gap) >= 0.4 else "slightly"
        if abs(gap) < MIN_GAP:
            item["text"] = "No clear difference in %s: winners and losers looked alike." % name
            item["verdict"] = "NONE"
        elif gap > 0:
            item["text"] = "Winners %s had %s." % (strong, high)
            item["verdict"] = "WINNERS_HIGHER"
        else:
            item["text"] = "Winners %s had %s." % (strong, low)
            item["verdict"] = "WINNERS_LOWER"
        out["features"].append(item)
    out["features"].sort(key=lambda x: -abs(x["gap_sd"]))
    real = [x for x in out["features"] if x["verdict"] != "NONE"]
    if real:
        L.append("What winners had in common: " + " ".join(x["text"] for x in real[:2]))
    else:
        L.append("The 4 numbers the Sniper reads do not separate winners from losers in this data. That means it has not found a clear pattern yet. This is an honest result, not an error.")
    L.append("This is paper data from other bots. It shows what winners shared. It does not promise the next trade wins. Real money is your decision and needs the readiness checklist to pass.")
    return out


def build(d, limit=1500):
    """From the saved files (read only). Never raises."""
    try:
        import owl_sniper_bridge_learn as BL
        ex, _ = BL.load_examples(d, limit)
        ex, dup = BL.dedupe(ex)
        out = compare(ex)
        out["duplicates_dropped"] = dup
        return out
    except Exception as e:
        return {"version": VERSION, "paper_only": True, "state": "error", "n": 0, "features": [], "by_source": {}, "lines": ["Could not study the past trades: %s" % str(e)[:120]]}


def main(argv=None):
    import owl_sniper_bridge_src as B
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=B.default_dir())
    ap.add_argument("--limit", type=int, default=1500)
    a = ap.parse_args(argv)
    print(json.dumps(build(a.data, a.limit), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
