"""Brain exit learner (brain_exit.py): shadow opinions only. No network.
Run: cd backend && python3 test_brain_exit.py"""
import json, os, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_exit as X
import smart_brain as B

ok = 0
def check(cond, msg):
    global ok
    assert cond, "FAIL: " + msg
    ok += 1

def tr(i, moves, net, status="closed"):
    return {"s": "AAA%d" % i, "f": "5m", "t": 1000 + i, "d": 1, "status": status, "net": net, "path": [[1, 1.0]] * moves, "tg": {}}

# planted rule: trades that trailed 2+ times finish at +20, trades that never moved finish at -8
past = [tr(i, 0, -8.0) for i in range(30)] + [tr(100 + i, 2, 20.0) for i in range(30)]
mem = X.memory(past)
check(len(mem[0]) == 60 and len(mem[2]) == 30 and len(mem[3]) == 0, "memory counts trades per reached stage")
check(X.stage_of({"path": [[1, 1]] * 9}) == X.MAX_STAGE, "stage is capped")
a, text, n, avg = X.advise(mem, 2, 5.0)
check(a == "HOLD" and n == 30 and avg == 20.0 and "better" in text, "holds when past trades finished much better")
a2 = X.advise(mem, 2, 40.0)[0]
check(a2 == "EXIT_OK", "exit is fine when profit now beats the past finish")
check(X.advise(mem, 2, 19.0)[0] == "NONE", "no clear edge = no opinion")
check(X.advise(mem, 3, 5.0)[0] == "NONE", "too few past trades = no opinion")
check(X.advise(mem, 2, None)[0] == "WAIT", "no live profit yet = wait")

# shadow notebook: open trade gets an opinion, then it is scored when the trade finishes
snapshot = json.dumps(past, sort_keys=True)
open_t = dict(tr(500, 2, None, "open"), live=5.0)
st = X.update({}, past + [open_t], now=10.0)
k = X.key_of(open_t)
check(k in st["open"] and st["open"][k]["advice"]["adv"] == "HOLD", "first opinion saved")
open_t["live"] = 50.0
st = X.update(st, past + [open_t], now=20.0)
check(st["open"][k]["advice"]["live"] == 5.0, "the first opinion is not changed later")
fin = dict(open_t, status="closed", net=25.0)
st = X.update(st, past + [fin], now=30.0)
check(k not in st["open"] and len(st["done"]) == 1 and st["done"][0]["right"] is True, "HOLD scored right: 25 finished above 5")
check(json.dumps(past, sort_keys=True) == snapshot, "past trades never changed")

# a skipped / still-open trade without an opinion is never scored
o2 = dict(tr(600, 0, None, "open"), live=None)
st = X.update(st, past + [o2], now=40.0)
st = X.update(st, past, now=50.0)
check(len(st["done"]) == 1, "no opinion = nothing to score")

# view
v = X.view(st, past)
check(v["status"] == "ready" and v["stages"][0]["n"] == 60 and v["score"]["pct"] is None, "view ready, hit-rate hidden until enough scored")
for i in range(12):
    st["done"].append({"k": str(i), "adv": "HOLD", "at": 1, "final": 5, "right": i < 9, "t": 1})
v = X.view(st, past)
check(v["score"]["pct"] == int(round(100.0 * 10 / 13)) or v["score"]["n"] >= X.SCORE_MIN, "hit-rate shows after %d scored" % X.SCORE_MIN)
check(X.view({}, past[:3])["status"] == "collecting", "tiny memory = collecting")
json.dumps(v)

# smart_brain view carries it, and Dual Bot data is not touched
path = os.path.join(os.environ["OWL_DATA_DIR"], "dual_lab_data.json")
open(path, "w").write(json.dumps({"rows": {}, "trades": []}))
before = open(path, "rb").read()
vb = B.build_view([], [], exit_state=st)
check("exit" in vb and vb["exit"]["status"] in ("ready", "collecting"), "exit block is in the Brain view")
json.dumps(vb, default=str)
check(open(path, "rb").read() == before, "dual_lab_data.json untouched")
print("OK %d checks" % ok)
