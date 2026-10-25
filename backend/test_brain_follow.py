"""brain_follow.py: shadow 'what if the bot had listened'. No network. Run: cd backend && python3 test_brain_follow.py"""
import json, os, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_follow as F
import smart_brain as B
ok = 0
def check(c, m):
    global ok
    assert c, "FAIL: " + m
    ok += 1
def tr(i, net, v, src="MAIN"):
    return {"s": "C%d" % i, "f": "5m", "t": 1000 + i, "src": src, "status": "closed", "net": net, "tg": {"v": v}}
def fn(rows, tg, t):
    return {"verdict": tg["v"]}
# planted rule: disliked trades lose, liked trades win
tr_ = [tr(i, -10.0, "dislike") for i in range(20)] + [tr(100 + i, 8.0, "like") for i in range(20)] + [tr(200 + i, 0.0, "unsure") for i in range(5)]
v = F.build([], tr_, fn)
check(v["status"] == "ready" and v["judged"] == 45, "ready with enough judged trades")
s = {x["name"]: x for x in v["stories"]}
check(s["TAKE ALL (the bot)"]["total"] == -40.0 and s["SKIP DISLIKED"]["total"] == 160.0 and s["ONLY LIKED"]["n"] == 20, "three stories")
check(s["SKIP DISLIKED"]["drop"] <= s["TAKE ALL (the bot)"]["drop"], "smaller worst drop")
check("earned more" in v["text"] and v["dislike_avg"] == -10.0, "plain text says it would have helped")
# opposite world: disliked trades actually win -> says it would NOT have helped
bad = [tr(i, 10.0, "dislike") for i in range(20)] + [tr(100 + i, -2.0, "like") for i in range(20)]
check("NOT have helped" in F.build([], bad, fn)["text"], "honest when listening would have hurt")
check(F.build([], tr_[:10], fn)["status"] == "collecting", "too few trades = collecting")
check(F.build([], tr_ + [tr(300 + i, 1.0, "like", "Z") for i in range(5)], fn, only_src="MAIN")["judged"] == 45, "source filter")
check(F.build([], [{"status": "closed", "net": 1, "tg": {"v": "x"}, "t": 1}], lambda *a: 1 / 0)["judged"] == 0, "bad scorer never crashes")
# smart_brain view carries it; Dual Bot data untouched
path = os.path.join(os.environ["OWL_DATA_DIR"], "dual_lab_data.json")
open(path, "w").write(json.dumps({"rows": {}, "trades": []})); before = open(path, "rb").read()
vb = B.build_view([], [])
check("follow" in vb and vb["follow"]["status"] == "collecting", "follow block in Brain view")
json.dumps(vb, default=str)
check(open(path, "rb").read() == before, "dual_lab_data.json untouched")
print("OK %d checks" % ok)
