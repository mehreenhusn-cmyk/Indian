"""v2_verdict_studies_a.py - Round 5: SIX MORE VERDICT CARDS (Tag Lab, Scalp Lab, Radar, Pump / Dump, Exit Study, Day Compare), one register() call each.
Loaded by one guarded import at the bottom of v2_verdicts.py. Same card rules as v2_verdicts.py (see its header): EDGE needs 100+ cases and the same sign in both halves;
descriptive replays (Scalp Lab, Pump / Dump, Radar) are NEVER EDGE; a card that cannot decide says what is missing, have_n of need_n, when, and what to do.
Read-only: saved files, the store opened mode=ro by v2_verdicts, the Brain file opened read-only by the study modules. No network, no write, no trading import."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_compare as CP
import v2_bt_exitlab as XL
import v2_radar_outcomes as RO
import v2_scalp_pump as SP
import v2_scalp_store as SS
import v2_verdicts as VD

MIN_N, MIN_BRAIN, HINT_N = VD.MIN_N, VD.MIN_PLAYBOOK, 60
CAV_REPLAY = "hypothetical replay of saved candles, nothing proven"
NO_STORE = "The candle store does not exist."
NO_STORE_ACT = "run: python3 backend/v2_candles.py --on"


def _no_store(title):
    return VD.nod("%s: no market store yet" % title, NO_STORE, 0, MIN_N, NO_STORE_ACT)


def _tag_files(data_dir):
    """tag_lab_<tf>.json files the Tag Lab saved, newest first (own files only, never a path outside the data folder)."""
    out = []
    try:
        for name in os.listdir(data_dir):
            if name.startswith("tag_lab_") and name.endswith(".json"):
                p = os.path.join(data_dir, name)
                if os.path.isfile(p) and not os.path.islink(p):
                    out.append((os.path.getmtime(p), p))
    except OSError:
        return []
    return [p for _m, p in sorted(out, reverse=True)]


def c_tag_lab(x):
    best = None
    for p in _tag_files(x["dir"]):
        d = VD._load_json(p)
        if d and (best is None or VD._i(d.get("entries")) > VD._i(best.get("entries"))):
            best = d
    if best is None:
        return VD.nod("Tag Lab has not been run", "No saved tag_lab_<timeframe>.json file in the data folder.", 0, MIN_N, "open Study Lab > Tag Lab and start a run")
    n, good = VD._i(best.get("entries")), best.get("good") or []
    tf, days = best.get("tf", "n/a"), best.get("days", "n/a")
    luck = best.get("luck_counts")
    luck_max = max([VD._i(v) for v in luck]) if isinstance(luck, list) and luck else 0
    ago = VD._ago(x["now"], best.get("made"))
    if n < MIN_N:
        return dict(VD.nod("Tag Lab has only %d entries" % n, "The last run (%s, %s days) found %d entries; %d are needed." % (tf, days, n, MIN_N), n, MIN_N, "run Tag Lab again with more days", n=n), updated_ago_sec=ago)
    cav = "%d tag combinations tried at once; luck alone passed %d of them in the worst shuffle" % (VD._i(best.get("combos_tried")), luck_max)
    base = {"n": n, "need_n": MIN_N, "have_n": n, "caveat": cav, "updated_ago_sec": ago}
    if not good:
        return dict(base, verdict="NO_EDGE", headline="No tag combination is positive in both halves", detail="Run %s over %s days: %d entries, %d combinations tried, none positive in the older and the newer half." % (tf, days, n, VD._i(best.get("combos_tried"))))
    top = good[0]
    pos = VD._i(top.get("n")) >= MIN_N and VD._num(top.get("old_avg")) and VD._num(top.get("new_avg")) and top["old_avg"] > 0 and top["new_avg"] > 0
    txt = "Top combination: %d trades, older half avg %s, newer half avg %s, win %s%%. %d combination(s) passed; luck alone passes up to %d." % (
        VD._i(top.get("n")), VD.fmt(top.get("old_avg"), 3, True), VD.fmt(top.get("new_avg"), 3, True), VD.fmt(top.get("win_pct"), 1), len(good), luck_max)
    if pos and len(good) > luck_max:
        return dict(base, verdict="EDGE", headline="Tag Lab: %d combination(s) beat luck" % len(good), detail=txt)
    return dict(base, verdict="DIAGNOSIS_ONLY", headline="Tag Lab: candidate found, luck not ruled out", detail=txt)


def c_scalp_lab(x):
    d = SS.status(x["dir"])
    if not d.get("ready"):
        return VD.nod("Scalp Lab has no records", str(d.get("note") or "no Scalp Lab file yet"), 0, MIN_N, "run the Scalp Lab runner once")
    cats = d.get("categories") or []
    top = max(cats, key=lambda c: VD._i(c.get("records")), default=None)
    have = VD._i(top.get("records")) if top else 0                    # categories are never added together
    if have < MIN_N:
        return VD.nod("Scalp Lab has too few records", "The biggest category has %d finished records; %d are needed." % (have, MIN_N), have, MIN_N, "let the Scalp Lab runner collect more days", n=have)
    return {"verdict": "DIAGNOSIS_ONLY", "headline": "Scalp Lab: %d categories saved, replay only" % len(cats), "n": have, "need_n": MIN_N, "have_n": have, "caveat": CAV_REPLAY,
            "detail": "Biggest category: %s v%s with %d records. Each category has its own ledger; counts are never added. Records are replays, not proof." % (top.get("category", "n/a"), top.get("version", "n/a"), have)}


def _cells(rep):
    for mode, m in (rep.get("modes") or {}).items():
        for side, s in (m.get("sides") or {}).items():
            yield mode, side, s.get("TRAIN") or {}, s.get("HOLDOUT") or {}, s.get("baseline") or {}


def c_pump(x):
    if not x["con"]:
        return _no_store("Pump / Dump")
    rep = SP.build(x["con"], x["now"], VD.DAYS)
    cells = list(_cells(rep))
    have = max([VD._i(t.get("n")) + VD._i(h.get("n")) for _m, _s, t, h, _b in cells], default=0)
    if have < MIN_N:
        return VD.nod("Pump / Dump has too few trades", "The biggest group has %d finished replay trades in %d days; %d are needed." % (have, VD.DAYS, MIN_N), have, MIN_N,
                      "run: python3 backend/v2_candles_deep.py --plan, then wait for more candles", n=VD._i(rep.get("signals")))
    ahead = []
    for mode, side, t, h, b in cells:
        tm, hm, bm = t.get("median_net_pct"), h.get("median_net_pct"), b.get("median_net_pct")
        if all(VD._num(v) for v in (tm, hm, bm)) and tm > bm and hm > bm:
            ahead.append((hm - bm, mode, side, tm, hm, bm))
    base = {"n": VD._i(rep.get("signals")), "need_n": MIN_N, "have_n": have, "caveat": CAV_REPLAY + "; fees and slippage taken off", "updated_ago_sec": 0}
    if not ahead:
        return dict(base, verdict="NO_EDGE", headline="Pump / Dump: nothing beats ordinary candles", detail="No FOLLOW or FADE side is above the ordinary-candle median in both TRAIN and HOLDOUT (last %d days, %d signals)." % (VD.DAYS, base["n"]))
    ahead.sort(reverse=True)
    _g, mode, side, tm, hm, bm = ahead[0]
    return dict(base, verdict="DIAGNOSIS_ONLY", headline="Pump / Dump: %s %s looks better, unproven" % (mode, side), detail="%s %s: median net TRAIN %s%%, HOLDOUT %s%%, ordinary candles %s%%. %d side(s) are ahead in both halves. Replay only." % (
        mode, side, VD.fmt(tm, 2, True), VD.fmt(hm, 2, True), VD.fmt(bm, 2, True), len(ahead)))


def c_radar(x):
    if not x["con"]:
        return _no_store("Radar")
    rep = RO.build(x["con"], x["now"], None, 7)
    days = rep.get("days") or []
    ok = [d for d in days if d.get("status") == "OK"]
    new = sum(VD._i((d.get("episodes") or {}).get("new_episodes")) for d in ok)
    if new < MIN_N:
        return VD.nod("Radar has %d new episodes" % new, "%d of %d saved day(s) have a cohort; %d new episodes counted, %d are needed." % (len(ok), len(days), new, MIN_N), new, MIN_N,
                      "let the daily 00:00 UTC cohort be saved for more days", n=new)
    return {"verdict": "DIAGNOSIS_ONLY", "headline": "Radar: %d new episodes, description only" % new, "n": new, "need_n": MIN_N, "have_n": new, "caveat": "describes what saved prices did after the cohort; no win rate, no forecast",
            "detail": "%d day(s) with a saved cohort, %d new episodes (same coin and side on consecutive days counts once). Classes show what happened after 1 / 2 / 3 / 7 days; they do not predict." % (len(ok), new), "updated_ago_sec": 0}


def c_exits(x):
    best, note = None, ""
    for src in ("PAPER", "REPLAY"):
        r = XL.build(x["dir"], src, x["now"])
        if r.get("ready") and (best is None or VD._i(r.get("used")) > VD._i(best.get("used"))):
            best = r
        note = note or str(r.get("note") or "")
    if best is None:
        return VD.nod("Exit Study has no trades", note or "No Brain Trader file yet.", 0, MIN_N, "restart the backend; the first Brain tick comes in about 5 minutes")
    used, rules = VD._i(best.get("used")), best.get("rules") or []
    if used < MIN_N:
        return VD.nod("Exit Study has %d trades" % used, "%s source: %d closed trades replayed; %d are needed." % (best.get("source", "n/a"), used, MIN_N), used, MIN_N, "let the Brain close more paper trades", n=used)
    cav = "same closed trades replayed with other exits on saved candles, net of fee; nothing is applied, luck can explain part"
    base = {"n": used, "need_n": HINT_N, "have_n": used, "caveat": cav, "updated_ago_sec": 0}
    better = [r for r in rules if r.get("verdict") == "BETTER"]
    cur = next((r for r in rules if r.get("key") == "CURRENT"), {})
    if better:
        b = max(better, key=lambda r: VD._num(r.get("net_usdt")) and r["net_usdt"] or 0)
        return dict(base, verdict="EDGE", headline="Exit rule %s beats the current exit" % b.get("key", "n/a"), detail="%s Net %s vs %s USDT for the current exit, better in both halves (%d trades). Not applied." % (
            b.get("name", b.get("key", "n/a")), VD.fmt(b.get("net_usdt"), 2, True), VD.fmt(cur.get("net_usdt"), 2, True), used))
    if used < HINT_N:
        return dict(VD.nod("Exit Study: early hint only", "%d trades; %d are needed before any exit rule may be called better or worse." % (used, HINT_N), used, HINT_N, "let the Brain close more paper trades", n=used), caveat=cav)
    return dict(base, verdict="NO_EDGE", headline="No exit rule clearly beats the current exit", detail="%d trades replayed with %d exit rules; none is better in both halves. Current exit net %s USDT." % (used, len(rules), VD.fmt(cur.get("net_usdt"), 2, True)))


def c_daycmp(x):
    r = CP.build(x["dir"], "PAPER", None, x["now"])
    if not r.get("ready"):
        return VD.nod("Day Compare has no Brain file", "No Brain Trader file yet: nothing was compared.", 0, MIN_BRAIN, "restart the backend; the first Brain tick comes in about 5 minutes")
    cal = r.get("calendar") or []
    n = sum(VD._i(d.get("brain_trades")) for d in cal)
    bnet, onet = sum(d.get("brain_usdt") or 0 for d in cal), sum(d.get("bot_usdt") or 0 for d in cal)
    if n < MIN_BRAIN:
        return VD.nod("Brain has %d paper trades in %d days" % (n, CP.CAL_DAYS), "Brain %s USDT vs Current Bot %s USDT; the Brain needs %d closed trades before a comparison means anything." % (VD.fmt(bnet, 2, True), VD.fmt(onet, 2, True), MIN_BRAIN), n, MIN_BRAIN,
                      "let the Brain keep trading on paper", n=n)
    half = len(cal) // 2                                               # calendar is newest first
    new, old = sum(d.get("brain_usdt") or 0 for d in cal[:half]), sum(d.get("brain_usdt") or 0 for d in cal[half:])
    base = {"n": n, "need_n": MIN_N, "have_n": n, "caveat": "Brain and Current Bot are different trades, never added; Take-All is a simulation", "updated_ago_sec": 0}
    txt = "Brain %s USDT (%d trades) vs Current Bot %s USDT over %d days. Brain older half %s, newer half %s." % (VD.fmt(bnet, 2, True), n, VD.fmt(onet, 2, True), CP.CAL_DAYS, VD.fmt(old, 2, True), VD.fmt(new, 2, True))
    if n < MIN_N:
        return dict(base, verdict="DIAGNOSIS_ONLY", headline="Brain %s vs Bot %s, early look" % (VD.fmt(bnet, 1, True), VD.fmt(onet, 1, True)), detail=txt + " Under %d trades: a look, not a verdict." % MIN_N)
    if bnet < 0:
        return dict(base, verdict="LOSING", headline="Brain lost %s USDT in %d days" % (VD.fmt(-bnet), CP.CAL_DAYS), detail=txt)
    if old > 0 and new > 0:
        return dict(base, verdict="EDGE", headline="Brain made %s USDT in %d days" % (VD.fmt(bnet), CP.CAL_DAYS), detail=txt)
    return dict(base, verdict="NO_EDGE", headline="Brain has no steady profit yet", detail=txt)


for _id, _title, _fn in (("tag_lab", "Tag Lab", c_tag_lab), ("scalp_lab", "Scalp Lab", c_scalp_lab), ("radar", "Radar outcomes", c_radar), ("pump_dump", "Pump / Dump study", c_pump),
                         ("exit_study", "Exit Study", c_exits), ("day_compare", "Day Compare", c_daycmp)):
    VD.register(_id, _title, _fn)
