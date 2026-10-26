"""brain_ready.py: the READY CHECK block (report only). No network. Run: cd backend && python3 test_brain_ready.py"""
import os, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_ready as BR
import smart_brain as B

ok = 0
def check(cond, msg):
    global ok
    assert cond, "FAIL: " + msg
    ok += 1

def row(r, k):
    return next(x for x in r["rows"] if x["key"] == k)

# 1. empty / junk view: nothing crashes, nothing is true, 7 rows
for v in (None, {}, {"trust": None, "exit": {"score": None}}):
    r = BR.ready_check(v)
    check(len(r["rows"]) == 7 and r["n_true"] == 0 and not r["skip_ok"] and not r["exit_ok"], "empty view")
    check("Not ready" in r["text"], "empty headline")

# 2. all good
good = {"trust": {"verdict": "earned", "text": "t"}, "luck": {"verdict": "solid", "text": "l"},
        "follow": {"status": "ready", "judged": 40, "need": 30, "text": "w", "stories": [{"total": 10.0}, {"total": 25.0}, {"total": 5.0}]},
        "exit": {"score": {"n": 12, "pct": 70, "text": "e"}},
        "retest": {"status": "ok", "wait": 6, "total_gain": 12.5}, "timing": {"text": "tm"},
        "own": {"stage": "learning", "n": 40, "pnl": 3.5, "next_stage": "medium", "next_in": 60}}
r = BR.ready_check(good)
check(r["n_true"] == 4 and r["skip_ok"] and r["exit_ok"] and "All 4" in r["text"], "all true")
check("Next stage (medium) in 60" in row(r, "own")["text"] and "+12.50" in row(r, "retest")["text"] and not row(r, "retest")["gate"], "info rows")

# 3. one failure blocks Brain skip but the exit check can stand alone
v = dict(good, luck={"verdict": "luck", "text": "l"})
r = BR.ready_check(v)
check(row(r, "luck")["ok"] is False and not r["skip_ok"] and r["exit_ok"] and "Check 4" in r["text"], "luck fails")
v = dict(good, luck={"verdict": "maybe", "text": "l"})
check(row(BR.ready_check(v), "luck")["ok"] is None, "maybe = still collecting")

# 4. what-if: skipping must really earn more; too few judged = None with a count
v = dict(good, follow={"status": "ready", "judged": 40, "need": 30, "text": "w", "stories": [{"total": 30.0}, {"total": 10.0}, {"total": 5.0}]})
check(row(BR.ready_check(v), "whatif")["ok"] is False, "skipping did not help")
v = dict(good, follow={"status": "collecting", "judged": 12, "need": 30})
w = row(BR.ready_check(v), "whatif")
check(w["ok"] is None and "12 of 30" in w["text"], "what-if collecting")

# 5. exit hit-rate: 60% is not enough (needs above 60), none yet = None
check(row(BR.ready_check(dict(good, exit={"score": {"n": 20, "pct": 60, "text": "e"}})), "exit")["ok"] is False, "60% fails")
check(row(BR.ready_check(dict(good, exit={"score": {"n": 3, "pct": None, "text": "e"}})), "exit")["ok"] is None, "no hit-rate yet")

# 6. lands in the Brain view
check("ready" in B.build_view(rows=[], trades=[]) and len(B.build_view(rows=[], trades=[])["ready"]["rows"]) == 7, "view hook")
print("brain_ready OK: %d checks" % ok)
