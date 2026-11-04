"""v2_testresults_src3.py - R11 / WHERE IS THE MONEY LOST: ENTRY, EXIT OR SIDEWAYS? PAPER ONLY, READ ONLY. Family "loss" in the TestResult shape (v2_testresults.simple) + one small object `loss_source` for the Lab card.
Owner question: "is it the entry, the exit, or the sideways market that costs me?" The SAME replayed old trades the booking learner (R4) and the entry learner (R5) use (Dual / Brain / Main, same signal once, newest 30 days, 1R = the trade's own stop, after fees) get ONE tag each,
  with the SAME words as the Sniper's lessons memory (R7, which does it for the Sniper's own paper trades in USDT):
    EXIT      the trade reached +1R, then ended at 0 or lower or kept less than half of its best gain.   Cost = best gain minus what was kept (profit given back).
    SIDEWAYS  a loss in a SIDEWAYS state and the trade never reached +0.5R ("choppy time, no room").     Cost = the loss.
    ENTRY     a loss and the trade never reached +0.3R ("the price went against it at once").            Cost = the loss.
    OTHER     any other loss (it went a little our way, then failed).                                    Cost = the loss.
    GOOD      a profit that kept at least half of its best gain (no cost).
  Result rows: one per bucket (verdict DIAGNOSIS_ONLY: the tags are hindsight, never EDGE, never an advice) + two FIX rows that only READ the learners' saved files (R4 v2_sniper_exitlearn.json, R5 v2_sniper_entrylearn.json): is there a better exit / a better entry on UNSEEN days?
    Fix verdicts: LEARNED_EXIT / LEARNED_ENTRY (the learner's own unseen-days test: t-value and more than half of the test days) = EDGE; the best of ALL rules at least +0.02 R above the default but no live-capable pick = DIAGNOSIS_ONLY; otherwise NO_EDGE; under 30 unseen trades / not enough days = NOT_ENOUGH_DATA.
  Fewer than 30 old trades with candles = NOT_ENOUGH_DATA, no answer is made up. use_in_sniper is always false. Nothing here changes a trade.
refresh(d, now) = the heavy replay (slow loop only), writes ONLY v2_lab_loss.json. collect(d, now) / loss_source(d, now) = cheap reads. Never raise. No network, no order code."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_feed as F
import v2_testresults as T

VERSION = "v2_testresults_src3 1 (R11)"
FILE, EXIT_FILE, ENTRY_FILE = "v2_lab_loss.json", "v2_sniper_exitlearn.json", "v2_sniper_entrylearn.json"
SINCE_DAYS, MIN_N, MIN_TEST, MIN_GAIN = 30, 30, 30, 0.02       # MIN_TEST / MIN_GAIN = the same limits as the learners (owl_sniper_exitlearn.py)
LABELS = {"EXIT": "Exit", "SIDEWAYS": "Sideways", "ENTRY": "Entry", "OTHER": "Other loss"}
WHAT = {"EXIT": "profit given back after it was +1R", "SIDEWAYS": "losses in a sideways market with no room", "ENTRY": "price went against it at once", "OTHER": "went a little our way, then failed"}
CAV = "Hindsight tags on replayed old trades (Dual / Brain / Main), in R after fees. A diagnosis of the past, not a rule and not a promise."


def tag(r, mfe, regime):
    """-> (tag, cost in R). Same rule order as owl_sniper_lessons.tag_trade."""
    if mfe >= 1.0 and (r <= 0 or r < 0.5 * mfe):
        return "EXIT", mfe - max(r, 0.0)
    if r > 0:
        return "GOOD", 0.0
    if regime == "SIDEWAYS" and mfe < 0.5:
        return "SIDEWAYS", -r
    if mfe < 0.3:
        return "ENTRY", -r
    return "OTHER", -r


def split(items, now=None):
    """items = [{r, mfe, regime}] -> the loss_source dict. Pure."""
    now = int(time.time() if now is None else now)
    b = {k: [0, 0.0] for k in LABELS}
    good = 0
    for i in items:
        t, c = tag(i["r"], i["mfe"], i.get("regime"))
        if t == "GOOD":
            good += 1
        else:
            b[t][0] += 1
            b[t][1] += c
    n, total = len(items), sum(v[1] for v in b.values())
    ls = {"version": VERSION, "made": now, "state": "OK" if n >= MIN_N else "NOT_ENOUGH_DATA", "n": n, "need_n": MIN_N, "good": good, "total_cost_r": round(total, 2), "days": SINCE_DAYS, "buckets": []}
    for k, (cnt, cost) in sorted(b.items(), key=lambda kv: -kv[1][1]):
        ls["buckets"].append({"key": k, "label": LABELS[k], "what": WHAT[k], "n": cnt, "cost_r": round(cost, 2), "share_pct": round(100.0 * cost / total, 1) if total > 0 else 0.0})
    top = ls["buckets"][0] if ls["buckets"] else None
    if ls["state"] != "OK":
        ls["line"] = "Only %d old trades with candles, %d needed: no answer yet." % (n, MIN_N)
    elif top and total > 0:
        ls["biggest"] = top["key"]
        ls["line"] = "Biggest leak: %s, %.0f%% of the R it cost (%d trades, %.1f R)." % (top["label"], top["share_pct"], top["n"], top["cost_r"])
    else:
        ls["line"] = "No trade cost any R in this window."
    return ls


def build(d, now):
    """The heavy replay: the same examples as R4 / R5 (feedall, read only) -> tags. Raises on a broken source; refresh() catches it."""
    import owl_sniper_bridge_learn as BL
    import owl_sniper_feedall as FA
    ex, _x = BL.load_examples(d, 0, SINCE_DAYS, FA.B.SOURCES, now)
    merged, _n = FA.merge(ex)
    items = []
    for e in merged:
        lb = e.get("label") or {}
        if T.num(lb.get("r_net")) and T.num(lb.get("mfe_r")):
            items.append({"r": float(lb["r_net"]), "mfe": float(lb["mfe_r"]), "regime": str(e.get("regime") or "").upper()})
    return split(items, now)


def refresh(d, now=None):
    now = int(time.time() if now is None else now)
    try:
        ok = F.write_json(d, FILE, build(d, now))
        return {"loss": "saved" if ok else "not saved (folder not writable)"}
    except Exception as e:
        return {"loss": "error: %s: %s" % (type(e).__name__, str(e)[:80])}


def _exit_fix(st, ago, src="v2_sniper_exitlearn.json"):
    if not isinstance(st, dict):
        return T.simple("loss", "exit_fix", "Better exit?", "NOT_ENOUGH_DATA", "", "Better exit: the booking learner has not run yet", "The booking learner (R4) has not saved a result yet.", 0, MIN_TEST, caveat=CAV, ago=ago, source=src)
    ago = int(time.time() - st["made"]) if T.num(st.get("made")) else -1          # the age of the learner's own file
    c, why = st.get("compare") or {}, " ".join(str(x) for x in (st.get("reasons") or [])[:2])
    n = int(c.get("test_trades") or 0)
    d0, live, anyr = c.get("default_mean_r"), c.get("live_choice_mean_r"), c.get("any_choice_mean_r")
    gain_any = anyr - d0 if T.num(anyr) and T.num(d0) else None
    if st.get("state") == "LEARNED_EXIT":
        v, head = "EDGE", "A learned profit line beats the fixed 2R on unseen days"
    elif not c or n < MIN_TEST:
        v, head = "NOT_ENOUGH_DATA", "Better exit: not enough unseen trades yet"
    elif T.num(gain_any) and gain_any >= MIN_GAIN:
        v, head = "DIAGNOSIS_ONLY", "Break-even / trail / time rules look better, but need an exit engine"
    else:
        v, head = "NO_EDGE", "No exit rule clearly beats the fixed 2R"
    return T.simple("loss", "exit_fix", "Better exit?", v, "", head, why, n, MIN_TEST, context="unseen days", exp_r=live, lift_r=(live - d0) if T.num(live) and T.num(d0) else None, caveat="Judged on unseen days after fees (owl_sniper_exitlearn). Not a promise.", ago=ago, source=src)


def _entry_fix(st, ago, src="v2_sniper_entrylearn.json"):
    if not isinstance(st, dict):
        return T.simple("loss", "entry_fix", "Better entry?", "NOT_ENOUGH_DATA", "", "Better entry: the entry learner has not run yet", "The entry learner (R5) has not saved a result yet.", 0, MIN_TEST, caveat=CAV, ago=ago, source=src)
    ago = int(time.time() - st["made"]) if T.num(st.get("made")) else -1
    c, why = st.get("compare") or {}, " ".join(str(x) for x in (st.get("reasons") or [])[:2])
    n = int(c.get("test_signals") or 0)
    now_r, got = c.get("now_mean_r"), c.get("learned_mean_r")
    if st.get("state") == "LEARNED_ENTRY":
        v, head = "EDGE", "A learned entry beats entering at the signal on unseen days"
    elif not c or n < MIN_TEST:
        v, head = "NOT_ENOUGH_DATA", "Better entry: not enough unseen signals yet"
    else:
        v, head = "NO_EDGE", "No entry style clearly beats entering at the signal"
    return T.simple("loss", "entry_fix", "Better entry?", v, "", head, why + (" Advice only: no wait / limit engine in the paper trader yet." if v == "EDGE" else ""), n, MIN_TEST, context="unseen days", exp_r=got,
                    lift_r=(got - now_r) if T.num(got) and T.num(now_r) else None, caveat="Judged on unseen days after fees (owl_sniper_entrylearn). Advice only.", ago=ago, source=src)


def _rows(ls, ago, src=FILE):
    out = []
    for b in ls.get("buckets") or []:
        ok = ls.get("state") == "OK"
        v = "DIAGNOSIS_ONLY" if ok and b["n"] > 0 else ("NOT_ENOUGH_DATA" if not ok else "NO_EDGE")
        head = "%s: %d trades cost %.1f R (%.0f%%)" % (b["label"], b["n"], b["cost_r"], b["share_pct"]) if ok else "%s: not enough trades yet" % b["label"]
        out.append(T.simple("loss", "bucket|%s" % b["key"], "Money lost: %s" % b["label"], v, "", head, "%s. Cost counted in R after fees, 1R = the trade's own stop. %s" % (b["what"].capitalize(), ls.get("line", "")), ls.get("n"), MIN_N,
                            context="old trades, %d days" % SINCE_DAYS, caveat=CAV, ago=ago, source=src))
    return out


def loss_source(d, now=None):
    """The object for the Lab card: tags + the two fix rows (short form). Never raises."""
    now = time.time() if now is None else now
    try:
        ls = F.read_json(d, FILE)
        if not isinstance(ls, dict):
            ls = {"state": "NOT_RUN_YET", "n": 0, "need_n": MIN_N, "buckets": [], "line": "The first run has not finished yet (the slow loop makes it by itself)."}
        ago = int(now - ls["made"]) if T.num(ls.get("made")) else -1
        fx = {"exit": _exit_fix(F.read_json(d, EXIT_FILE), ago), "entry": _entry_fix(F.read_json(d, ENTRY_FILE), ago)}
        return dict(ls, fix={k: {"verdict": v["verdict"], "headline": v["headline"], "detail": v["detail"], "lift_r": v["lift_r"]} for k, v in fx.items()}, updated_ago_sec=ago)
    except Exception as e:
        return {"state": "ERROR", "n": 0, "buckets": [], "line": "%s: %s" % (type(e).__name__, str(e)[:80])}


def collect(d, now=None):
    """-> (TestResults, meta {loss: ...}). Never raises."""
    now = time.time() if now is None else now
    try:
        ls = loss_source(d, now)
        ago = ls.get("updated_ago_sec", -1)
        rows = (_rows(ls, ago) if ls.get("state") in ("OK", "NOT_ENOUGH_DATA") else []) + [_exit_fix(F.read_json(d, EXIT_FILE), ago), _entry_fix(F.read_json(d, ENTRY_FILE), ago)]
        st = ls.get("state")
        return rows, {"loss": {"state": "OK" if st in ("OK", "NOT_ENOUGH_DATA") else st, "tests": len(rows), "age_sec": ago if ago >= 0 else None}}
    except Exception as e:
        return [], {"loss": {"state": "ERROR", "why": "%s: %s" % (type(e).__name__, str(e)[:100])}}
