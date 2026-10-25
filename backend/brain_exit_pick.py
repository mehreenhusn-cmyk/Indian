"""Smart Brain - learns WHICH EXIT STYLE works (full TP / half TP / hold). Paper only, advice for the Brain's own pretend trades.

Dual Bot's memory already holds, for every old setup, what each exit style would have earned (rows[5]). This module reads that,
nothing is invented:
  table = how every exit style did over ALL old setups (newest count more, same rolling memory as the rest of the Brain)
  pick  = for ONE new setup: among its look-alike old setups, which style earned the most. It only leaves the bot's own exit
          (full TP) when another style is clearly better (MARGIN ROI points) - otherwise it says so and keeps the default.
Reads only. Never writes dual_lab_data.json, never touches the main bot.
"""

MARGIN = 3.0        # ROI points a style must beat the bot's exit by, among look-alikes
MIN_ALL = 30        # old setups needed before the overall table is shown
KIND_WORD = {"FULL": "FULL TP", "HALF": "HALF TP", "HOLD": "HOLD", "TIME": "TIME EXIT"}


def kind_of(name):
    """FULL = wait for TP4 (the bot's way), HALF = close early at TP1 / TP2, HOLD = no cap, let it run (trail / opposite signal), TIME = fixed candles."""
    import tag_lab as TL
    rule = TL.EXITS.get(name) or {}
    if rule.get("hold"):
        return "TIME"
    cap = rule.get("cap")
    if cap is None:
        return "HOLD"
    return "FULL" if cap >= 4 else "HALF"


def _weights(n, roll):
    return [0.5 ** ((n - 1 - k) / float(roll)) for k in range(n)]


def exit_table(rows):
    """-> {status, text, table:[{name, kind, n, win, avg, best}]}; table is empty until MIN_ALL old setups exist."""
    import smart_brain as B
    import tag_lab as TL
    names = list(TL.EXITS)
    if len(rows) < MIN_ALL:
        return {"status": "collecting", "table": [], "text": "Collecting: %d old setups read, %d needed before exit styles can be compared." % (len(rows), MIN_ALL)}
    w = _weights(len(rows), B.ROLL_HALF)
    ws = sum(w)
    out = []
    for k, name in enumerate(names):
        nets = [float(r[5][k]) for r in rows]
        out.append({"name": name, "kind": kind_of(name), "n": len(nets), "win": int(round(100.0 * sum(1 for x in nets if x > 0) / len(nets))),
                    "avg": round(sum(a * b for a, b in zip(w, nets)) / ws, 2), "best": False})
    top = max(out, key=lambda x: x["avg"])
    top["best"] = True
    bot = next(x for x in out if x["name"] == TL.BOT)
    if top["name"] == TL.BOT:
        text = "Over all old setups the bot's own exit (%s) did best: average %+.1f%% of margin." % (KIND_WORD[top["kind"]], top["avg"])
    else:
        text = "Over all old setups '%s' (%s) did best: average %+.1f%% against %+.1f%% for the bot's exit." % (top["name"], KIND_WORD[top["kind"]], top["avg"], bot["avg"])
    return {"status": "ready", "table": sorted(out, key=lambda x: -x["avg"]), "text": text}


def pick(rows, tg, t_before=None):
    """The exit style for ONE new setup. -> (exit_name, plain reason). Falls back to the bot's exit when the look-alikes are too few or no style is clearly better."""
    import smart_brain as B
    import tag_lab as TL
    default = TL.BOT
    use, tl = B._use_dims(), B._tg_list(tg)
    elig = [r for r in rows if t_before is None or r[2] < t_before]
    scored = []
    for pos, r in enumerate(elig):
        if sum(1 for k in use if r[4][k] == tl[k]) >= B.MIN_SIM:
            scored.append((sum(1 for k in use if r[4][k] == tl[k]), pos, r))
    if len(scored) < B.MIN_N:
        return default, "Too few look-alike old trades yet, so it uses the bot's own exit (full TP)."
    scored.sort(key=lambda x: (-x[0], -x[1]))
    near = scored[:B.K_NEAR]
    w = [0.5 ** ((len(elig) - 1 - pos) / float(B.ROLL_HALF)) for _, pos, _r in near]
    ws = sum(w)
    names = list(TL.EXITS)
    avg = {name: sum(a * float(r[5][k]) for a, (_s, _p, r) in zip(w, near)) / ws for k, name in enumerate(names)}
    best = max(avg, key=avg.get)
    if best != default and avg[best] - avg[default] >= MARGIN:
        return best, "Among %d look-alikes '%s' (%s) earned %+.1f%% on average, better than %+.1f%% for the bot's exit." % (
            len(near), best, KIND_WORD[kind_of(best)], avg[best], avg[default])
    return default, "Among %d look-alikes no exit style was clearly better than the bot's own (full TP), so it keeps that." % len(near)
