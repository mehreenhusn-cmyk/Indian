"""v2_testresults_src2.py - R10 / Lab backend B (1 of 2): PURE converters. Each function takes the report a study already makes and returns TestResults (shape + words: v2_testresults.simple / make). No file, no network, no trading import.
  brain    <- learn.stats of smart_brain_view.json (brain_stats: what happened after each Brain state, per state and per slice) + edge.score (brain_edge: did WEAKENING / REVERSED trades end worse?)
  exit     <- tp_hold of smart_brain_view.json (brain_tp_hold: best exit per setup mix + how long winners / losers last)
  dual     <- timing of smart_brain_view.json (brain_lessons: Dual trades split by who fired first: MAIN / Z / BOTH)
  ignored  <- learn.skip of smart_brain_view.json (brain_skip: skipped signals vs taken trades)
  wick     <- v2_wickstudy.build_forward (stop-wick candles: what the price did after, against ordinary candles)
  regime   <- owl_sniper_regime.build (SD band holds per volatility regime and lookback)
  scalp    <- owl_sniper_scalp.build (SCALP / SHORT_SWING / SWING label + 'close at +0.6R' check per timeframe x side)
VERDICT RULES (same five words as R9; the study's own luck test is kept, never made weaker):
  brain / ignored: SUPPORTED -> EDGE, EARLY HINT -> DIAGNOSIS_ONLY, NO CLEAR PATTERN -> NO_EDGE, NOT ENOUGH DATA -> NOT_ENOUGH_DATA. Ignored: skipped signals that did clearly BETTER than the taken ones = LOSING (the skip rule costs money).
  exit / edge-score / dual: these have NO luck test, so they never reach EDGE: a clear gain (exit) or a steady positive result (dual) = DIAGNOSIS_ONLY; a steady negative Dual group = LOSING; the rest = NO_EDGE; under 30 cases = NOT_ENOUGH_DATA.
  wick: replay of candles without fees, so never EDGE or LOSING: 100+ cases and a gap of 0.20 points to ordinary candles (the same limits as v2_verdicts.py) = DIAGNOSIS_ONLY, else NO_EDGE.
  regime: the Part 23 verdict of the study through v2_testresults.make (default lookback, plus the best seen one when it is another number). scalp: close at +0.6R beats waiting = DIAGNOSIS_ONLY (no unseen-days split here; R6a modes does that), closing loses even at its best = LOSING.
Units are kept honest: Brain / exit / ignored numbers are ROI points of margin net of fee, Dual is USDT, only regime / scalp are R. Nothing here is a profit promise and nothing is applied to a trade."""
import v2_testresults as T

VERSION = "v2_testresults_src2 1 (R10)"
MIN_N = 30                                    # cases before a group may leave NOT_ENOUGH_DATA (the same 30 as R9)
WICK_N, MIN_BASE, CLEAR_GAP = 100, 30, 0.20   # the same limits as v2_verdicts.py for descriptive replays
BRAIN_V = {"SUPPORTED": "EDGE", "EARLY HINT": "DIAGNOSIS_ONLY", "NO CLEAR PATTERN": "NO_EDGE", "NOT ENOUGH DATA": "NOT_ENOUGH_DATA"}
WHO_FIRST = {"same": "BOTH", "z12": "Z", "z35": "Z", "zonly": "Z", "m12": "MAIN", "m35": "MAIN", "monly": "MAIN", "opp": "OPPOSITE"}
CAV_BRAIN = "ROI points of the Dual trades, net of fee, luck-tested. Measurement only: nothing is applied."
CAV_EXIT = "Replay of old setups: stops and targets fill at the exact price, no slippage, no luck test. A hint, not advice."
CAV_DUAL = "USDT of finished Dual trades, no luck test. The groups are compared by hindsight: a hint, not a rule."
CAV_REPLAY = "Replay of saved candles, no fees, nothing proven."


def _n(x):
    return int(x) if T.num(x) else 0


def _f(x, nd=2, sign=True):
    return "n/a" if not T.num(x) else (("%+." if sign else "%.") + str(nd) + "f") % x


def _wait(family, rid, title, n, need, why, ago, src, caveat):
    """One NOT_ENOUGH_DATA row for a whole study that has nothing to say yet."""
    return T.simple(family, rid, title, "NOT_ENOUGH_DATA", "", "%s: not enough cases yet" % title, why, n, need, caveat=caveat, ago=ago, source=src)


def _state_row(r, st, ago, src, slice_name=None):
    """brain_stats: one state (S / T / W / R) of one slice."""
    v = BRAIN_V.get(r.get("verdict"), "NOT_ENOUGH_DATA")
    nm = str(r.get("name") or r.get("state") or "state")
    title = "Brain %s%s" % (nm.lower(), "" if not slice_name else " (%s)" % slice_name)
    lean = r.get("lean")
    h = r.get("halves") or [None, None]
    det = "%s Excess %s ROI pts per trade (older half %s, newer half %s), luck p %s." % (str(r.get("text") or "").strip(), _f(r.get("excess")), _f(h[0] if len(h) > 0 else None), _f(h[1] if len(h) > 1 else None), _f(r.get("p_adj"), 3, False))
    head = {"EDGE": "%s: %s" % (title, "holding beat leaving" if lean == "hold" else "leaving beat holding"), "DIAGNOSIS_ONLY": "%s: early hint, not proven" % title,
            "NO_EDGE": "%s: no clear effect on the result" % title, "NOT_ENOUGH_DATA": "%s: not enough cases yet" % title}[v]
    return T.simple("brain", "%s|%s" % (slice_name or "all", r.get("state")), title, v, "HOLD" if lean == "hold" else ("EXIT" if lean == "exit_now" else ""), head, det,
                    r.get("n"), st.get("min_n") or MIN_N, context=slice_name or "all trades", caveat=CAV_BRAIN, ago=ago, source=src)


def from_brain_stats(st, ago=-1, src="smart_brain_view.json (learn.stats)"):
    if not isinstance(st, dict) or st.get("status") in (None, "error"):
        return [_wait("brain", "stats", "Brain states", 0, MIN_N, "The Brain statistics are not available yet (%s)." % str((st or {}).get("err") or "no data"), ago, src, CAV_BRAIN)]
    out = [_state_row(r, st, ago, src) for r in st.get("overall") or [] if isinstance(r, dict) and (_n(r.get("n")) or _n(r.get("unjudged")))]
    sl = sorted((r for r in st.get("slices") or [] if isinstance(r, dict)), key=lambda r: -_n(r.get("n")))[:24]      # slices only appear at MIN_N trades; the biggest 24 are enough for a card list
    out += [_state_row(r, st, ago, src, str(r.get("slice"))) for r in sl]
    return out or [_wait("brain", "stats", "Brain states", 0, st.get("min_n") or MIN_N, "No Brain state has a finished trade to judge yet.", ago, src, CAV_BRAIN)]


def from_brain_edge(edge, ago=-1, src="smart_brain_view.json (edge.score)"):
    """brain_edge scorecard: did trades that showed WEAKENING / REVERSED end worse than the others? Never EDGE (provisional labels, no luck test)."""
    sc = (edge or {}).get("score") if isinstance(edge, dict) else None
    if not isinstance(sc, dict) or sc.get("status") != "ready":
        n, need = _n((sc or {}).get("n")), _n((sc or {}).get("need")) or MIN_N
        return [_wait("brain", "edge_warning", "Brain edge warning", n, need, str((sc or {}).get("text") or "No finished trade with an edge history yet."), ago, src, CAV_BRAIN)]
    g = {x.get("key"): x for x in sc.get("groups") or [] if isinstance(x, dict)}
    a, b = g.get("weak_or_reversed") or {}, g.get("never_weak") or {}
    worse = T.num(a.get("avg_net")) and T.num(b.get("avg_net")) and a["avg_net"] < b["avg_net"]
    head = ("Weak-edge trades ended %s vs %s, a hint" % (_f(a.get("avg_net"), 1), _f(b.get("avg_net"), 1))) if worse else "Edge warnings did not predict a worse end"
    return [T.simple("brain", "edge_warning", "Brain edge warning", "DIAGNOSIS_ONLY" if worse else "NO_EDGE", "", head, str(sc.get("text") or ""), _n(sc.get("n")), _n(sc.get("need")) or MIN_N,
                     context="open trade edge", caveat=CAV_BRAIN + " Longer trades have more chances to show a warning.", ago=ago, source=src)]


def from_ignored(sk, ago=-1, src="smart_brain_view.json (learn.skip)"):
    if not isinstance(sk, dict) or sk.get("status") == "error" or sk.get("verdict") is None:
        return [_wait("ignored", "skipped", "Skipped signals", 0, MIN_N, "The skipped-signal check is not available yet (%s)." % str((sk or {}).get("err") or "no data"), ago, src, CAV_BRAIN)]
    v, diff, n = BRAIN_V.get(sk.get("verdict"), "NOT_ENOUGH_DATA"), sk.get("diff"), _n(sk.get("skipped_done"))
    if v == "EDGE" and T.num(diff) and diff > 0:
        v = "LOSING"                                         # SUPPORTED and the skipped signals did BETTER: the skip rule throws away money
    head = {"EDGE": "Skipped signals did worse: the skip rule helps", "LOSING": "Skipped signals did better: the skip rule costs", "DIAGNOSIS_ONLY": "Skipped signals differ from taken ones, early hint",
            "NO_EDGE": "Skipped signals did about the same as taken ones", "NOT_ENOUGH_DATA": "Skipped signals: not enough cases yet"}[v]
    det = "%s Mean skipped %s vs taken %s ROI pts net of fee; total if all were taken %s. %d skipped signals still open." % (str(sk.get("text") or "").strip(), _f(sk.get("mean_skip")), _f(sk.get("mean_taken")),
                                                                                                                         _f(sk.get("total_if_taken")), _n(sk.get("skipped_open")))
    return [T.simple("ignored", "skipped", "Skipped signals vs taken", v, "SKIPPED", head, det, n, sk.get("min_n") or MIN_N, context="what-if trades", caveat=CAV_BRAIN, ago=ago, source=src)]


def from_exit(tp, ago=-1, src="smart_brain_view.json (tp_hold)"):
    if not isinstance(tp, dict) or tp.get("status") != "ready":
        return [_wait("exit", "tp_hold", "Exit and hold", _n((tp or {}).get("n")), _n((tp or {}).get("need")) or MIN_N, str((tp or {}).get("text") or "The exit and hold report is not made yet."), ago, src, CAV_EXIT)]
    out = []
    for key, name, m in [("all", "all setups", tp.get("all"))] + [(x.get("key"), x.get("name"), x) for x in tp.get("mixes") or [] if isinstance(x, dict)]:
        if not isinstance(m, dict):
            continue
        clear, steady, bot_best = bool(m.get("clearly")), m.get("steady"), m.get("gain") == 0
        v = "DIAGNOSIS_ONLY" if clear and steady is not False else "NO_EDGE"
        title = "Exit, %s" % name
        head = ("%s: %s beats the bot's exit" % (title, m.get("best"))) if v == "DIAGNOSIS_ONLY" else ("%s: halves disagree, no clear exit" % title if clear else "%s: the bot's own exit is fine" % title)
        h = m.get("hold") or {}
        det = "'%s' (%s) earned %s%% per setup vs %s%% for the bot's exit (gain %s). With it winners last a median of %s min and losers %s min; %s%% of winners finish fast. Older and newer half agree: %s." % (
            m.get("best"), m.get("best_kind"), _f(m.get("best_avg"), 1), _f(m.get("bot_avg"), 1), _f(m.get("gain"), 1), h.get("win_min", "n/a"), h.get("loss_min", "n/a"), h.get("fast_pct", "n/a"),
            "unknown (too few)" if steady is None else ("yes" if steady else "no"))
        out.append(T.simple("exit", str(key), title, v, "", head, det, m.get("n"), MIN_N, context=name, caveat=CAV_EXIT, ago=ago, source=src))
        if bot_best and v == "NO_EDGE":
            out[-1]["detail"] = "The bot's own exit did best. " + out[-1]["detail"]
    return out


def _dual_verdict(n, avg, steady):
    if n < MIN_N:
        return "NOT_ENOUGH_DATA"
    if steady and T.num(avg) and avg > 0:
        return "DIAGNOSIS_ONLY"
    if steady and T.num(avg) and avg < 0:
        return "LOSING"
    return "NO_EDGE"


def _dual_row(rid, title, g, who, ago, src):
    n, avg, steady = _n(g.get("n")), g.get("avg"), g.get("steady")
    v = _dual_verdict(n, avg, steady)
    head = {"DIAGNOSIS_ONLY": "%s: pays %s USDT per trade" % (title, _f(avg)), "LOSING": "%s: loses %s USDT per trade" % (title, _f(avg, 2, False)),
            "NO_EDGE": "%s: no steady result" % title, "NOT_ENOUGH_DATA": "%s: not enough trades yet" % title}[v]
    det = "%d trades, win %s%%, %s USDT per trade, %s USDT in all. Older and newer half point the same way: %s." % (n, g.get("win_pct", "n/a"), _f(avg), _f(g.get("pnl")), "unknown (too few)" if steady is None else ("yes" if steady else "no"))
    return T.simple("dual", rid, title, v, "", head, det, n, MIN_N, context="first: %s" % who, caveat=CAV_DUAL, ago=ago, source=src)


def from_dual(tm, ago=-1, src="smart_brain_view.json (timing)"):
    """Dual trades split by which indicator fired first: MAIN / Z / BOTH (and OPPOSITE). Alt coins only (BTC is in the BTC Lab)."""
    if not isinstance(tm, dict) or tm.get("status") != "ready":
        return [_wait("dual", "timing", "Dual MAIN / Z / BOTH", _n((tm or {}).get("done")), _n((tm or {}).get("need")) or MIN_N, str((tm or {}).get("text") or "The timing report is not made yet."), ago, src, CAV_DUAL)]
    out = [_dual_row(str(g.get("key")), str(g.get("name") or g.get("key")), g, WHO_FIRST.get(g.get("key"), "?"), ago, src) for g in tm.get("groups") or [] if isinstance(g, dict) and _n(g.get("n"))]
    d = tm.get("deep")
    if isinstance(d, dict) and _n(d.get("n")):
        out.append(_dual_row("deep", "Deep clean setup", d, "BOTH or close", ago, src))
    return out or [_wait("dual", "timing", "Dual MAIN / Z / BOTH", 0, MIN_N, "No timing group has a finished trade yet.", ago, src, CAV_DUAL)]


def from_wick(rep, ago=-1, src="v2_wickstudy.build_forward"):
    base, out = (rep or {}).get("baseline") or {}, []
    for t in (rep or {}).get("types") or []:
        up = t.get("reversal_side") == "UP"
        nm = str(t.get("type") or "stop wick").replace("_", " ").lower()
        for h, c in (t.get("horizons") or {}).items():
            n = _n(c.get("n"))
            if not n:
                continue
            b = base.get(h) or {}
            m, bm = c.get("median_end_pct"), b.get("median_end_pct")
            gap = (m - bm) * (1 if up else -1) if T.num(m) and T.num(bm) else None          # positive = the price moved AWAY from the sweep (a reversal) more than an ordinary candle
            ok = n >= WICK_N and _n(b.get("n")) >= MIN_BASE and gap is not None
            v = "NOT_ENOUGH_DATA" if not ok else ("DIAGNOSIS_ONLY" if abs(gap) >= CLEAR_GAP else "NO_EDGE")
            if v == "DIAGNOSIS_ONLY":
                head = "%s after %s: %s by %.2f pts" % (nm, h, "reverses more" if gap > 0 else "keeps going more", abs(gap))
            else:
                head = "%s after %s: %s" % (nm, h, "same as ordinary candles" if v == "NO_EDGE" else "not enough cases yet")
            tip = c.get("tip_retaken_share")
            det = "Median end %s%% vs %s%% for ordinary candles (%d cases). The wick tip was taken again in %s%% of finished windows. Gap towards the reversal side: %s pts." % (
                _f(m), _f(bm), n, "n/a" if not T.num(tip) else "%.0f" % (100 * tip), _f(gap))
            out.append(T.simple("wick", "%s|%s" % (t.get("type"), h), "%s (%s)" % (nm.capitalize(), h), v, "LONG" if up else "SHORT", head, det, n, WICK_N, context=h, caveat=CAV_REPLAY, ago=ago, source=src))
    return out


def from_regime(rep, ago=-1, made=None, now=None, src="owl_sniper_regime.build"):
    """SD band HELD touches per volatility regime: the default lookback and, when it is another number, the best one seen."""
    default, rec, table, out = (rep or {}).get("default_lookback"), (rep or {}).get("recommended") or {}, (rep or {}).get("lookbacks") or {}, []
    for rg in (rep or {}).get("regimes") or {}:
        r = rec.get(rg) or {}
        best = r.get("best_seen")
        for L in [default] + ([best] if best and best != default else []):
            b = (table.get(str(L)) or {}).get(rg)
            if not isinstance(b, dict) or not _n(b.get("n")):
                continue
            blk = {"verdict": b.get("verdict"), "avoid": b.get("avoid"), "long": b, "best": "LONG", "plain": r.get("note")}
            x = T.make("regime", "%s|%s" % (rg, L), "SD band, %s vol, lookback %s" % (rg.lower(), L), blk, "LONG", context=rg, made=made, now=now, source=src)
            x["side"], x["use_in_sniper"], x["headline"] = "BOTH", False, x["headline"].replace(" LONG", "")          # support = LONG and resistance = SHORT pooled; advice only (R6b confirms a lookback after two weekly runs)
            out.append(x)
    return out


def from_scalp(rep, ago=-1, src="owl_sniper_scalp.build"):
    out = []
    for key, f in (rep or {}).get("families", {}).items():
        n = _n(f.get("n"))
        if not n:
            continue
        p = key.split("|")
        side, tf, rg = (p[1] if len(p) > 1 else ""), p[0], (p[2] if len(p) > 2 else "all regimes")
        sc = f.get("scalp") or {}
        title = "Scalp %s %s, %s" % (tf, side.lower(), rg.lower())
        if f.get("state") != "OK" or sc.get("state") in (None, "NOT_ENOUGH_DATA"):
            out.append(T.simple("scalp", key, title, "NOT_ENOUGH_DATA", side, "%s: not enough trades yet" % title, str(f.get("line") or ""), n, _n(sc.get("min_n")) or MIN_N, context="%s %s" % (tf, rg), caveat=CAV_REPLAY, ago=ago, source=src))
            continue
        v = "LOSING" if sc.get("scalp_possible") == "NO" else ("DIAGNOSIS_ONLY" if sc.get("state") == "SCALP_BETTER" else "NO_EDGE")
        head = {"LOSING": "%s: closing at +0.6R loses" % title, "DIAGNOSIS_ONLY": "%s: a quick scalp beat waiting" % title,
                "NO_EDGE": "%s: %s" % (title, "waiting beat the scalp" if sc.get("state") == "HOLD_BETTER" else "scalp and waiting about equal")}[v]
        det = "%s %s" % (str(f.get("line") or "").strip(), " ".join(str(x) for x in (sc.get("lines") or [])[:2]))
        out.append(T.simple("scalp", key, title, v, side, head, det[:420], _n(sc.get("n")) or n, _n(sc.get("min_n")) or MIN_N, context="%s %s, label %s" % (tf, rg, f.get("label")), exp_r=sc.get("scalp_r"), lift_r=sc.get("gain_r"),
                            caveat="Closing at +0.6R within 45 min, fees in, on finished trades. No unseen-days split here (R6a modes has it). Not a promise.", ago=ago, source=src))
    out.sort(key=lambda r: (r["verdict"] == "NOT_ENOUGH_DATA", -r["n"]))
    return out[:24]
