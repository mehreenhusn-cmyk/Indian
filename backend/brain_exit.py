"""Smart Brain - exit learner (SHADOW MODE ONLY).

Question it answers: "this trade is open and already in profit - hold, or is it a fine place to exit?"
It never closes, opens or changes a trade. It only writes its own opinion and later checks if the opinion was right.

How it works (plain Python, no torch, no numpy, no new library):
  state  = how far the stop has trailed (0 moves, 1 move, 2 moves ...) and how much profit the trade has right now
  memory = every finished Dual Bot trade, with how many times its stop moved and the final result
  advice = of the past trades that got this far, what did they finish with on average, compared with the profit right now?
           finish clearly better -> HOLD,  clearly worse -> EXIT IS FINE,  otherwise -> NO OPINION
Only the two indicators' trades are used. Nothing here reads or writes dual_lab_data.json.
"""
import time

MIN_PAST = 15          # past trades that reached the same stage, before any opinion
MARGIN = 3.0           # ROI points: the past finish must beat / lose to "now" by this much
MAX_STAGE = 4          # stage 4 means "4 or more stop moves"
KEEP_SHADOW = 300      # shadow opinions kept in the file
SCORE_MIN = 10         # scored opinions needed before a hit-rate is shown


def key_of(t):
    return "%s|%s|%s" % (t.get("s"), t.get("f"), t.get("t"))


def stage_of(t):
    """How many times the stop moved (0..MAX_STAGE). A moved stop means the trade made real progress."""
    return min(MAX_STAGE, len(t.get("path") or []))


def _done(t):
    return t.get("status") in ("closed", "skipped_done") and t.get("net") is not None


def memory(trades):
    """For each stage: final results of past trades that reached at least that stage. -> {stage: [nets]}"""
    mem = {s: [] for s in range(MAX_STAGE + 1)}
    for t in trades:
        if not _done(t):
            continue
        st = stage_of(t)
        for s in range(st + 1):
            mem[s].append(float(t["net"]))
    return mem


def advise(mem, stage, live):
    """-> (advice, text, n, avg_final). advice: HOLD / EXIT_OK / NONE / WAIT."""
    if live is None:
        return "WAIT", "Waiting for the first candle after the entry.", 0, None
    nets = mem.get(stage) or []
    n = len(nets)
    if n < MIN_PAST:
        return "NONE", "No opinion yet: only %d past trades got this far (needs %d)." % (n, MIN_PAST), n, None
    avg = sum(nets) / n
    if avg - live >= MARGIN:
        return "HOLD", "Past trades that got this far finished at %+.1f on average, better than %+.1f now. Holding looked better." % (avg, live), n, avg
    if live - avg >= MARGIN:
        return "EXIT_OK", "Past trades that got this far finished at %+.1f on average, worse than %+.1f now. Taking profit here looked fine." % (avg, live), n, avg
    return "NONE", "No clear edge: past trades finished near %+.1f, about the same as now (%+.1f)." % (avg, live), n, avg


def update(state, trades, now=None):
    """Updates the shadow notebook. state = {"open": {key: {...}}, "done": [scored opinions]}. Returns the same dict."""
    now = now or time.time()
    state = state if isinstance(state, dict) else {}
    opn = state.setdefault("open", {})
    done = state.setdefault("done", [])
    mem = memory(trades)
    live_keys = set()
    for t in trades:
        if t.get("status") != "open":
            continue
        k = key_of(t)
        live_keys.add(k)
        adv, text, n, avg = advise(mem, stage_of(t), t.get("live"))
        rec = opn.get(k)
        if rec is None:
            rec = opn[k] = {"s": t.get("s"), "f": t.get("f"), "d": t.get("d"), "first": now, "last_adv": "WAIT", "advice": None}
        rec.update(stage=stage_of(t), live=t.get("live"), adv=adv, text=text, n=n, avg=avg, seen=now)
        if adv in ("HOLD", "EXIT_OK") and rec["advice"] is None:
            # the first real opinion is what gets scored (no changing the answer later)
            rec["advice"] = {"adv": adv, "live": t.get("live"), "stage": stage_of(t), "t": now}
    finished = {key_of(t): t for t in trades if _done(t)}
    for k in list(opn.keys()):
        if k in live_keys:
            continue
        rec = opn.pop(k)
        a, t = rec.get("advice"), finished.get(k)
        if a and t is not None:
            final = float(t["net"])
            gain = final - float(a["live"])
            right = (gain >= 0) if a["adv"] == "HOLD" else (gain <= 0)
            done.append({"k": k, "adv": a["adv"], "at": a["live"], "final": round(final, 2), "right": bool(right), "t": now})
    del done[:-KEEP_SHADOW]
    return state


def view(state, trades):
    """What the app shows. Small and plain."""
    mem = memory(trades)
    n_past = len([t for t in trades if _done(t)])
    done = (state or {}).get("done") or []
    scored = len(done)
    right = sum(1 for d in done if d.get("right"))
    openl = []
    for k, rec in ((state or {}).get("open") or {}).items():
        openl.append({"s": rec.get("s"), "f": rec.get("f"), "d": rec.get("d"), "stage": rec.get("stage", 0), "live": rec.get("live"),
                      "adv": rec.get("adv"), "text": rec.get("text"), "n": rec.get("n", 0)})
    openl.sort(key=lambda x: (x["adv"] in ("HOLD", "EXIT_OK"), x["live"] or -999), reverse=True)
    stages = []
    for s in range(MAX_STAGE + 1):
        nets = mem[s]
        if nets:
            stages.append({"stage": s, "n": len(nets), "avg": round(sum(nets) / len(nets), 2),
                           "win": int(round(100.0 * sum(1 for x in nets if x > 0) / len(nets)))})
    if scored >= SCORE_MIN:
        pct = int(round(100.0 * right / scored))
        score = {"n": scored, "right": right, "pct": pct, "text": "Its opinion was right %d of %d times (%d%%)." % (right, scored, pct)}
    else:
        score = {"n": scored, "right": right, "pct": None, "text": "Opinions checked so far: %d (needs %d before a hit-rate is shown)." % (scored, SCORE_MIN)}
    if n_past < MIN_PAST:
        status, text = "collecting", "Collecting: %d finished trades read, needs %d." % (n_past, MIN_PAST)
    else:
        status, text = "ready", "Shadow mode: it only gives an opinion, it never closes a trade."
    return {"status": status, "text": text, "n_past": n_past, "open": openl[:8], "stages": stages, "score": score}
