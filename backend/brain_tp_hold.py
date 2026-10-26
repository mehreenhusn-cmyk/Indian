"""brain_tp_hold.py - Part D1: which TP / exit style fits which setup mix, and how long trades are held. REPORT ONLY.

Dual Bot's memory keeps, for every old setup (rows), what each of the 9 exit rules would have earned (rows[5], ROI points, fee inside) and
how many candles that trade lasted (rows[6]). Setup mix = the Timing Sync group of Part B1 (same candle / Z first / Main first / Z only ...).
For each mix: best exit vs the bot's own exit, how long winners and losers last (minutes), how many winners finish fast, and whether the
older and the newer half of the mix agree. Newest setups weigh more (same rolling memory as the rest of the Brain). BTC left out.
Reads only; nothing is skipped or changed. Replay numbers have no slippage: a hint, not advice. No network.
Test: cd backend && python3 test_brain_tp_hold.py
"""
MIN_MIX = 30         # old setups a mix needs before it gets a verdict
MARGIN = 3.0         # ROI points an exit must beat the bot's exit by to be called clearly better
FAST = 6             # a winner is "fast" if it ends within this many candles


def _med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def _hold(items, j):
    """How long (minutes) winners and losers of exit j lasted, and the share of winners that ended within FAST candles."""
    import tag_lab as TL
    mins = lambda r: int(r[6][j]) * TL.TF_MIN.get(r[1], 15)
    win = [r for r in items if r[5][j] > 0]
    los = [r for r in items if r[5][j] <= 0]
    return {"win_min": _med([mins(r) for r in win]), "loss_min": _med([mins(r) for r in los]), "wins": len(win),
            "fast_pct": int(round(100.0 * sum(1 for r in win if int(r[6][j]) <= FAST) / len(win))) if win else None}


def mix_report(items, names, bi, roll):
    """items: old setups of one mix, oldest first."""
    import brain_exit_pick as XP
    n = len(items)
    w = [0.5 ** ((n - 1 - k) / float(roll)) for k in range(n)]
    ws = sum(w)
    avg = [sum(a * float(r[5][j]) for a, r in zip(w, items)) / ws for j in range(len(names))]
    best = max(range(len(names)), key=lambda j: avg[j])
    out = {"n": n, "best": names[best], "best_kind": XP.KIND_WORD[XP.kind_of(names[best])], "best_avg": round(avg[best], 2),
           "bot_avg": round(avg[bi], 2), "gain": round(avg[best] - avg[bi], 2), "clearly": best != bi and avg[best] - avg[bi] >= MARGIN,
           "hold": _hold(items, best), "hold_bot": _hold(items, bi), "steady": None}
    if best != bi and n >= 2 * MIN_MIX:           # does the gain over the bot's exit show in BOTH halves?
        h = n // 2
        g = lambda xs: sum(float(r[5][best]) - float(r[5][bi]) for r in xs) / len(xs)
        out["steady"] = g(items[:h]) > 0 and g(items[h:]) > 0
    return out


def report(rows):
    import dual_lab
    import smart_brain as B
    import tag_lab as TL
    import brain_lessons as BL
    names = list(TL.EXITS)
    bi = names.index(TL.BOT)
    rs = sorted((r for r in rows if r[0] != dual_lab.BTC_SYM and len(r) >= 7), key=lambda r: r[2])
    out = {"status": "collecting", "n": len(rs), "need": MIN_MIX, "all": None, "mixes": [], "lines": [],
           "text": "Collecting: %d old setups read, the exit and hold report needs %d." % (len(rs), MIN_MIX)}
    if len(rs) < MIN_MIX:
        return out
    out["status"] = "ready"
    a = mix_report(rs, names, bi, B.ROLL_HALF)
    out["all"] = a
    for key, name in BL.GROUPS:
        its = [r for r in rs if BL.classify({"tg": dict(zip(TL.DIMS, r[4]))}) == key]
        if len(its) >= MIN_MIX:
            m = mix_report(its, names, bi, B.ROLL_HALF)
            m.update(key=key, name=name)
            out["mixes"].append(m)
    out["mixes"].sort(key=lambda m: -m["n"])
    out["text"] = ("Over all %d old setups the bot's own exit did best." % a["n"]) if a["best"] == names[bi] else \
        "Over all %d old setups '%s' (%s) did best: %+.1f%% per setup against %+.1f%% for the bot's exit." % (a["n"], a["best"], a["best_kind"], a["best_avg"], a["bot_avg"])
    h = a["hold_bot"]
    if h["win_min"] is not None and h["loss_min"] is not None:
        out["lines"].append("With the bot's exit, winners last a median of %d min and losers %d min. %d%% of winners finish within %d candles." % (
            h["win_min"], h["loss_min"], h["fast_pct"], FAST))
    better = [m for m in out["mixes"] if m["clearly"]]
    for m in sorted(better, key=lambda m: -m["gain"])[:3]:
        out["lines"].append("%s: '%s' (%s) earned %+.1f%% per setup, %+.1f%% more than the bot's exit.%s" % (
            m["name"], m["best"], m["best_kind"], m["best_avg"], m["gain"], " Careful: the older and the newer half disagree." if m["steady"] is False else ""))
    if out["mixes"] and not better:
        out["lines"].append("No setup mix has an exit that clearly beats the bot's own exit (needs +%.0f points). Keep the bot's exit for now." % MARGIN)
    out["lines"].append("Replay numbers: stops and targets fill at the exact price, so real trades will earn a bit less. Report only: nothing is changed.")
    return out
