"""v2_verdict_studies_b.py - Round 6: FOUR MORE VERDICT CARDS about the Brain itself (Brain Health, Ready check, Learning Progress, Knowledge Ledger), one register() call each.
Loaded by the guarded import loop at the bottom of v2_verdicts.py. Same card rules as v2_verdicts.py: these four describe READINESS and LEARNING, never a proven edge,
so none of them gives EDGE (LOSING only with 100+ closed trades and a negative net). A card that cannot decide says what is missing, have_n of need_n, when, and what to do.
Read-only: the Brain file and the ledger file are opened read-only by their own modules. No network, no write, no trading import."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_health as HE
import v2_bt_progress as PG
import v2_bt_ready as RD
import v2_bt_store as B
import v2_ledger as LG
import v2_verdicts as VD

NEED_BRAIN, TREND_N = VD.MIN_PLAYBOOK, 60
WAIT_ACT = "let the Brain keep trading on paper"
NO_FILE_ACT = "restart the backend; the first Brain tick comes in about 5 minutes"
GOOD_STATUS = ("Promising (unvalidated)", "Validated in limited conditions", "Approved for controlled/paper test")


def c_brain_health(x):
    h = HE.build(x["dir"], "PAPER", x["now"], "5m")
    if not h.get("ready"):
        return VD.nod("Brain Health: no Brain file", str(h.get("note") or "No Brain Trader file yet."), 0, HE.NEED, NO_FILE_ACT)
    closed = VD._i(B.status(x["dir"])["per_source"]["PAPER"]["closed"])
    hold = h.get("holdout") or {}
    run = (h.get("runner") or {}).get("state", "n/a")
    if closed < HE.NEED:
        return VD.nod("Brain Health: %d of %d paper trades" % (closed, HE.NEED), str(h.get("missing_summary") or "The Brain needs more closed paper trades."), closed, HE.NEED, WAIT_ACT, n=closed)
    word = (h.get("headline") or {}).get("verdict", "n/a")
    return {"verdict": "DIAGNOSIS_ONLY", "headline": "Brain Health: %s" % word.lower(), "n": closed, "need_n": HE.NEED, "have_n": closed, "updated_ago_sec": 0,
            "caveat": "a readiness check, not a profit result; live stays locked",
            "detail": "%d closed paper trades. Holdout: %d confirm, %d against. Auto-runner: %s. %s" % (closed, VD._i(hold.get("confirms")), VD._i(hold.get("against")), run.lower(), h.get("missing_summary", ""))}


def c_ready(x):
    r = RD.build(x["dir"], "PAPER", x["now"])
    if not r.get("ready"):
        return VD.nod("Brain Ready: no Brain file", str(r.get("note") or "No Brain Trader file yet."), 0, 1, NO_FILE_ACT)
    passed, total = VD._i(r.get("passed")), VD._i(r.get("total"))
    word, text = (r.get("verdict") or {}).get("word", "n/a"), str((r.get("verdict") or {}).get("text") or "")
    if word == "CHECKS PASS":
        return {"verdict": "DIAGNOSIS_ONLY", "headline": "All %d readiness checks pass" % total, "n": total, "need_n": total, "have_n": passed, "updated_ago_sec": 0,
                "caveat": "not a promise of profit; live stays locked until you say OK", "detail": text}
    failed = [c.get("label", "n/a") for c in r.get("checks") or [] if not c.get("ok")]
    return VD.nod("Brain Ready: %d of %d checks true" % (passed, total), text or "Some checks are still false.", passed, total, "next check to fix: %s" % (failed[0] if failed else "open Brain Ready"),
                  eta="unknown (depends on new paper trades)", n=VD._i((r.get("brain") or {}).get("trades")))


def c_progress(x):
    p = PG.build(x["dir"], "PAPER", x["now"])
    if not p.get("ready"):
        return VD.nod("Learning Progress: no Brain file", str(p.get("note") or "No Brain Trader file yet."), 0, NEED_BRAIN, NO_FILE_ACT)
    n, tr = VD._i(p.get("all_closed")), p.get("trend") or {}
    old, new = tr.get("older") or {}, tr.get("newer") or {}
    if n < NEED_BRAIN:
        return VD.nod("Learning Progress: %d closed trades" % n, "The Brain has %d closed paper trades; %d are needed before it may say better or worse." % (n, NEED_BRAIN), n, NEED_BRAIN, WAIT_ACT, n=n)
    net = (old.get("net_usdt") or 0) + (new.get("net_usdt") or 0)
    txt = "Older half %s USDT per trade, newer half %s USDT per trade (%s per 10 losing, then %s). %d mistake group(s), %d fixed." % (
        VD.fmt(old.get("avg_usdt"), 3, True), VD.fmt(new.get("avg_usdt"), 3, True), VD.fmt(old.get("loss_per_10"), 1), VD.fmt(new.get("loss_per_10"), 1), len(p.get("mistakes") or []), len(p.get("fixed") or []))
    base = {"n": n, "need_n": TREND_N, "have_n": n, "updated_ago_sec": 0, "caveat": "closed paper trades net of fee; halves compared, luck can explain part", "detail": txt}
    word = tr.get("word")
    if n >= VD.MIN_N and net < 0:
        return dict(base, verdict="LOSING", headline="Brain lost %s USDT over %d paper trades" % (VD.fmt(-net), n))
    if n < TREND_N:
        return dict(base, verdict="DIAGNOSIS_ONLY", headline="Learning Progress: early hint only")
    if word == "IMPROVING":
        return dict(base, verdict="DIAGNOSIS_ONLY", headline="Brain looks better lately, luck not ruled out")
    return dict(base, verdict="NO_EDGE", headline="Brain: no clear improvement yet" if word != "WORSE" else "Brain: newer trades are worse")


def c_ledger(x):
    try:
        rows = LG.latest(x["dir"], ro=True)
    except FileNotFoundError:
        return VD.nod("Knowledge Ledger has no file", "No %s in the data folder: no finding was saved yet." % LG.DB_NAME, 0, 1, "save a first finding in the Ledger screen")
    if not rows:
        return VD.nod("Knowledge Ledger is empty", "The ledger file exists but holds no finding.", 0, 1, "save a first finding in the Ledger screen")
    good = [r for r in rows if r.get("status") in GOOD_STATUS]
    rej = sum(1 for r in rows if r.get("status") == "Rejected")
    try:
        new = len(LG.changes_since_review(x["dir"], ro=True).get("changes") or [])
    except Exception:
        new = 0
    top = good[0] if good else {}
    return {"verdict": "DIAGNOSIS_ONLY", "headline": "Ledger: %d findings, %d promising, %d rejected" % (len(rows), len(good), rej), "n": len(rows), "need_n": 1, "have_n": len(rows), "updated_ago_sec": -1,
            "caveat": "your own notes: a status is a label, not a result", "detail": "%d change(s) since the last review. %s" % (new, ("First promising: %s (%s of %s)." % (top.get("name", "n/a"), top.get("sample_size", "n/a"), top.get("denominator", "n/a"))) if good else "No finding is marked promising yet.")}


for _id, _title, _fn in (("brain_health", "Brain Health", c_brain_health), ("brain_ready", "Brain Ready check", c_ready), ("learning_progress", "Learning Progress", c_progress), ("knowledge_ledger", "Knowledge Ledger", c_ledger)):
    VD.register(_id, _title, _fn)
