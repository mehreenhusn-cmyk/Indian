"""Smart Brain - "what if the bot had listened?" (Phase 4, step B, SHADOW ONLY).
Takes the trades the bot really finished and asks the Brain (using ONLY older memory, like the trust meter) to give each one a verdict:
like / unsure / dislike. Then it compares three paper stories on the same trades:
  TAKE ALL       - what the bot did
  SKIP DISLIKED  - the bot skips only what the Brain dislikes
  ONLY LIKED     - the bot takes only what the Brain likes
Nothing is changed in the bot. It is a report card, so you can see if listening would have helped, and how big the worst drop was."""

MIN_JUDGED = 30      # judged trades before any comparison is shown
LAST_N = 300         # newest finished trades looked at


def _dd(nets):
    peak = cum = dd = 0.0
    for x in nets:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def _story(name, nets):
    n = len(nets)
    if n == 0:
        return {"name": name, "n": 0, "total": 0.0, "avg": 0.0, "win": 0, "drop": 0.0}
    return {"name": name, "n": n, "total": round(sum(nets), 1), "avg": round(sum(nets) / n, 2),
            "win": int(round(100.0 * sum(1 for x in nets if x > 0) / n)), "drop": round(_dd(nets), 1)}


def build(rows, trades, score_fn, only_src=None):
    """score_fn(rows, tags, t_before) -> {"verdict": ...} (smart_brain.score_setup). Returns the view block, never raises on bad trades."""
    done = [t for t in trades if t.get("status") == "closed" and t.get("net") is not None and t.get("tg")]
    if only_src:
        done = [t for t in done if t.get("src") == only_src]
    done.sort(key=lambda t: t["t"])
    done = done[-LAST_N:]
    seq = []
    for t in done:
        try:
            v = score_fn(rows, t["tg"], t["t"]).get("verdict", "unsure")
        except Exception:
            continue
        seq.append((v, float(t["net"])))
    out = {"judged": len(seq), "need": MIN_JUDGED, "status": "collecting", "stories": [], "text": "", "dislike_avg": None}
    if len(seq) < MIN_JUDGED:
        out["text"] = "Collecting: %d of %d finished trades judged." % (len(seq), MIN_JUDGED)
        return out
    a = [n for _, n in seq]
    b = [n for v, n in seq if v != "dislike"]
    c = [n for v, n in seq if v == "like"]
    dis = [n for v, n in seq if v == "dislike"]
    out["stories"] = [_story("TAKE ALL (the bot)", a), _story("SKIP DISLIKED", b), _story("ONLY LIKED", c)]
    out["dislike_avg"] = round(sum(dis) / len(dis), 2) if dis else None
    out["status"] = "ready"
    sa, sb = out["stories"][0], out["stories"][1]
    if not dis:
        out["text"] = "The Brain disliked none of these trades, so nothing would have changed."
    elif sb["total"] > sa["total"] and sb["drop"] <= sa["drop"]:
        out["text"] = "Skipping what the Brain disliked would have earned more (%+.0f vs %+.0f ROI points) and the worst drop was smaller (%.0f vs %.0f)." % (sb["total"], sa["total"], sb["drop"], sa["drop"])
    elif sb["total"] > sa["total"]:
        out["text"] = "Skipping disliked trades would have earned more (%+.0f vs %+.0f) but the worst drop was not smaller. Mixed." % (sb["total"], sa["total"])
    else:
        out["text"] = "Skipping disliked trades would NOT have helped (%+.0f vs %+.0f). Not a reason to trust it yet." % (sb["total"], sa["total"])
    return out
