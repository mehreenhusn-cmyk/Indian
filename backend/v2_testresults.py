"""v2_testresults.py - R9 / Lab backend A: ONE TestResult shape + ONE set of verdict rules for the four indicator studies (Z-SMA, SD bands, pairs, combos). PURE functions: no file, no network, no trading import.
The four study files (owl_sniper_zsma / sdbands / ind_pairs / combo) all judge a state with the same Part 23 rule and each speaks its own words (STEADY, SOMETIMES, NO_PAY, NOT_ENOUGH_DATA). The app needs ONE word set, the same as the verdict cards of v2_verdicts.py:
  EDGE / DIAGNOSIS_ONLY / LOSING / NO_EDGE / NOT_ENOUGH_DATA.
TestResult = {id, family, title, side, context, verdict, headline (12 words max), detail, n, have_n, need_n, win_pct, exp_r, lift_r, lift_train, lift_test, coins_beat_pct, use_in_sniper, caveat, reason_missing, next_action, updated_ago_sec (-1 = unknown), source}
VERDICT RULES (one place, here):
  STEADY (both halves, most coins, lift above 2 x standard error)  -> EDGE
  SOMETIMES (looked good, not proven)                               -> DIAGNOSIS_ONLY (never used by the Sniper)
  NO_PAY and the old half AND the new half are both below a random candle and the expected R is negative -> LOSING
  NO_PAY (anything else)                                            -> NO_EDGE
  NOT_ENOUGH_DATA (under 30 independent cases, or under 15 in a half) -> NOT_ENOUGH_DATA, says have_n of need_n, what is missing and what to do.
  COMBOS only: a combo is EDGE only when it also adds value over the plain kind (adds_value); a STEADY combo that does not beat the plain kind is DIAGNOSIS_ONLY.
Nothing here is a profit promise: every number is measured on candles the rule never saw, after fees, in R."""
import re

VERSION = "v2_testresults 4 (R9 to R12)"
VERDICTS = ("EDGE", "DIAGNOSIS_ONLY", "LOSING", "NO_EDGE", "NOT_ENOUGH_DATA")
ORDER = {v: i for i, v in enumerate(VERDICTS)}
FAMILIES_A = ("zsma", "sd_bands", "pairs", "combos")                              # R9: the four indicator studies (v2_testresults_src.py)
FAMILIES_B = ("brain", "exit", "dual", "ignored", "wick", "regime", "scalp", "loss", "exitrule")      # R10 + R11 + R12 (loss = where the money is lost, exitrule = 9 exit rules x market state): Brain, exit / hold, Dual split, skipped signals, stop-wick, regime, scalp (v2_testresults_src2.py / _src2b.py)
FAMILIES = FAMILIES_A + FAMILIES_B
NEED_N, MAX_WORDS = 30, 12
CAVEAT = "Paper replay of saved candles: +2R / -1R, 30 candles, fees in. Not a promise."


def num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


def clean(t):
    """The text 'None' never reaches the app."""
    return re.sub(r"\bNone\b", "n/a", t) if isinstance(t, str) else t


def words(t, n=MAX_WORDS):
    w = clean(str(t or "")).split()
    return " ".join(w[:n]) + ("" if len(w) <= n else "...")


def pick_side(block, natural=None):
    """-> (side, judged dict). The side the study picked as best; else its natural side; else the side with the higher expected R."""
    lo, sh = block.get("long") or {}, block.get("short") or {}
    best = block.get("best")
    if best in ("LONG", "SHORT"):
        return best, (lo if best == "LONG" else sh)
    if natural in ("LONG", "SHORT"):
        return natural, (lo if natural == "LONG" else sh)
    a, b = lo.get("exp_r"), sh.get("exp_r")
    if num(a) and num(b) and b > a:
        return "SHORT", sh
    return "LONG", lo


def verdict_of(mod_verdict, j, avoid=False, adds_value=True):
    """(verdict, why). mod_verdict = the study's own word, j = the judged dict of the chosen side."""
    if mod_verdict == "STEADY":
        return ("EDGE", "steady") if adds_value else ("DIAGNOSIS_ONLY", "works, but not better than the plain setup")
    if mod_verdict == "SOMETIMES":
        return "DIAGNOSIS_ONLY", "looked good, not proven"
    if mod_verdict == "NO_PAY":
        both_below = num(j.get("lift_train")) and num(j.get("lift_test")) and j["lift_train"] < 0 and j["lift_test"] < 0
        if avoid or (both_below and num(j.get("exp_r")) and j["exp_r"] < 0):
            return "LOSING", "below a random candle in both halves"
        return "NO_EDGE", "no clear gap to a random candle"
    return "NOT_ENOUGH_DATA", "too few independent cases"


def headline(v, title, side, j):
    ex = j.get("exp_r")
    e = "" if not num(ex) else " %+.2fR" % ex
    return words({"EDGE": "%s %s pays in both halves%s" % (title, side, e), "DIAGNOSIS_ONLY": "%s %s looks good, not proven%s" % (title, side, e),
                  "LOSING": "%s: both halves lose%s" % (title, e), "NO_EDGE": "%s: no edge over a random candle" % title,
                  "NOT_ENOUGH_DATA": "%s: not enough cases yet" % title}[v])


def make(family, state_id, title, block, natural=None, adds_value=True, context=None, made=None, now=None, source=""):
    """One TestResult from one judged state block of a study file."""
    side, j = pick_side(block, natural)
    v, why = verdict_of(block.get("verdict"), j, bool(block.get("avoid")), adds_value)
    n = int(j.get("n_independent") or 0)
    r = {"id": "%s:%s" % (family, state_id), "family": family, "title": title, "side": side, "context": context or "", "verdict": v,
         "headline": headline(v, title, side, j), "detail": clean(block.get("plain") or why), "n": n, "have_n": n, "need_n": NEED_N,
         "win_pct": j.get("win_pct"), "exp_r": j.get("exp_r"), "lift_r": j.get("lift"), "lift_train": j.get("lift_train"), "lift_test": j.get("lift_test"),
         "coins_beat_pct": j.get("coins_beat_baseline_pct"), "use_in_sniper": v == "EDGE", "caveat": CAVEAT, "reason_missing": "", "next_action": "",
         "updated_ago_sec": int(now - made) if num(now) and num(made) else -1, "source": source}
    if v == "NOT_ENOUGH_DATA":
        r["reason_missing"] = "Only %d independent cases of %d needed (and 15 in each half)." % (n, NEED_N)
        r["next_action"] = "Wait: the saved candles grow by themselves."
    return r


def _fin(x, nd=3):
    """A number the saved JSON may hold (no NaN / inf), else None."""
    return round(float(x), nd) if num(x) and abs(x) != float("inf") else None


def simple(family, rid, title, verdict, side, head, detail, n, need_n=NEED_N, context="", exp_r=None, win_pct=None, lift_r=None, caveat=CAVEAT,
           reason_missing="", next_action="", ago=-1, source=""):
    """R10: a TestResult for a study that has no long / short block (Brain, exit, Dual split, skipped signals, wick, regime, scalp). Same keys as make().
    use_in_sniper is ALWAYS False here: no R10 study is wired into the Sniper (the owner decides, R24)."""
    n = int(n or 0)
    r = {"id": "%s:%s" % (family, rid), "family": family, "title": clean(title), "side": side or "", "context": context or "", "verdict": verdict, "headline": words(head),
         "detail": clean(detail or ""), "n": n, "have_n": n, "need_n": int(need_n or NEED_N), "win_pct": _fin(win_pct, 1), "exp_r": _fin(exp_r), "lift_r": _fin(lift_r), "lift_train": None,
         "lift_test": None, "coins_beat_pct": None, "use_in_sniper": False, "caveat": caveat, "reason_missing": reason_missing, "next_action": next_action,
         "updated_ago_sec": int(ago) if num(ago) else -1, "source": source}
    if verdict == "NOT_ENOUGH_DATA":
        r["reason_missing"] = reason_missing or "Only %d of %d needed." % (n, r["need_n"])
        r["next_action"] = next_action or "Wait: the saved data grows by itself."
    return r


def sort_results(rs):
    """EDGE first, then by lift (best first)."""
    return sorted(rs, key=lambda r: (ORDER[r["verdict"]], -(r["lift_r"] if num(r.get("lift_r")) else -9.0), r["id"]))


def summary(rs):
    by_v, by_f = {v: 0 for v in VERDICTS}, {f: {v: 0 for v in VERDICTS} for f in FAMILIES}
    for r in rs:
        by_v[r["verdict"]] += 1
        by_f.setdefault(r["family"], {v: 0 for v in VERDICTS})[r["verdict"]] += 1
    line = "%d tests: %d EDGE, %d not proven, %d losing, %d no edge, %d waiting for data." % (len(rs), by_v["EDGE"], by_v["DIAGNOSIS_ONLY"], by_v["LOSING"], by_v["NO_EDGE"], by_v["NOT_ENOUGH_DATA"])
    return {"total": len(rs), "by_verdict": by_v, "by_family": by_f, "line": line}
