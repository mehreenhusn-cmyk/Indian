"""Part U1 archive (trade_archive.py). No network. Run: cd backend && python3 test_trade_archive.py"""
import json, os, re, sqlite3, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trade_archive as TA
ok = 0
def check(c, m):
    global ok
    assert c, "FAIL: " + m
    ok += 1
HERE = os.path.dirname(os.path.abspath(__file__))
base = tempfile.mkdtemp()

def trade(i, status="open", net=None):
    return {"id": "AAAUSDT|5m|%d" % i, "s": "AAAUSDT", "f": "5m", "t": 1000 + i, "d": 1, "src": "MAIN", "exit": "BOT exit", "mode": "EXPLORE",
            "status": status, "net": net, "tg": {"x": 1}}
def data(n_tr=3, n_rows=5, n_rt=2, first=0):
    return {"trades": [trade(first + i) for i in range(n_tr)],
            "rows": {"AAAUSDT|5m|%d" % (first + i): ["AAAUSDT", "5m", 1000 + first + i, 1, ["a", "b"], [1.5, -2.0], [3, 4]] for i in range(n_rows)},
            "rt": {"AAAUSDT|5m|%d" % (first + i): [1000 + i, 1, 2, 3, 4, 5, 6, 7] for i in range(n_rt)}}

# empty folder
s = TA.status(base)
check(s["state"] == "none" and s["trades"] == 0, "no archive yet = state none")

# first save
st = {}
d = data()
check(TA.save_dual(d, st, base) is True, "first save works")
s = TA.status(base)
check((s["trades"], s["rows"], s["rt"]) == (3, 5, 2), "counts after first save")
check(s["state"] == "safe" and "Safe" in s["text"] and s["age_s"] <= 5, "state safe and plain text")
check(s["first_t"] == 1000, "first trade time")

# same data again = no duplicates
check(TA.save_dual(d, st, base) is True, "second save works")
check(TA.status(base)["trades"] == 3 and TA.status(base)["rows"] == 5, "idempotent")

# restart of the worker (empty memory of what was saved) = still no duplicates
check(TA.save_dual(d, {}, base) is True, "save after a restart")
check(TA.status(base)["trades"] == 3 and TA.status(base)["rows"] == 5, "restart does not duplicate")

# a trade closes: the SAME row is updated
d["trades"][0].update(status="closed", net=12.5, end="TP4")
TA.save_dual(d, st, base)
con = sqlite3.connect(os.path.join(base, TA.DUAL_DB))
r = con.execute("SELECT status, net, js FROM trades WHERE id = ?", (d["trades"][0]["id"],)).fetchone()
check(r[0] == "closed" and r[1] == 12.5 and json.loads(r[2])["end"] == "TP4", "closed state saved in place")
check(con.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 3, "still 3 trades")
check(TA.status(base)["closed"] == 1, "closed counted")

# trim() throws old things away: the archive must keep them
d["trades"] = d["trades"][2:]
for k in list(d["rows"])[:4]:
    d["rows"].pop(k)
d["rt"].clear()
TA.save_dual(d, st, base)
s = TA.status(base)
check((s["trades"], s["rows"], s["rt"]) == (3, 5, 2), "nothing disappears when the bot trims")
d["rows"]["AAAUSDT|5m|9999"] = ["AAAUSDT", "5m", 9999, -1, ["c"], [1.0], [1]]
TA.save_dual(d, st, base)
check(TA.status(base)["rows"] == 6, "new rows are added")
rj = con.execute("SELECT js FROM rows WHERE k = 'AAAUSDT|5m|9999'").fetchone()[0]
check(json.loads(rj) == d["rows"]["AAAUSDT|5m|9999"], "row is stored exactly")
con.close()

# a big pass is fast enough for a phone
big = data(600, 5000, 4000, first=100000)
t0 = time.time()
check(TA.save_dual(big, {}, base), "big save")
check(time.time() - t0 < 8, "big save is fast (%.1fs)" % (time.time() - t0))
t0 = time.time()
TA.save_dual(big, st, base)
TA.save_dual(big, st, base)
check(time.time() - t0 < 8, "repeat saves are cheap")

# garbage never raises
st2 = {}
check(TA.save_dual(None, st2, base) is False and st2["arch_err"], "bad data = False, error remembered, no crash")

# Brain side
own = {"closed": [{"id": "own1", "t": 1, "s": "BBBUSDT", "f": "15m", "net": 3.0, "stage": "learning"}, {"id": "own2", "t": 2, "s": "BBBUSDT", "f": "15m", "net": -1.0, "stage": "learning"}]}
book = {"picks": {"p1": {"id": "p1", "t": 1, "s": "BBBUSDT", "f": "15m", "mode": "shadow"}}}
ex = {"done": [{"k": "BBBUSDT|15m|1", "adv": "HOLD", "t": 5}]}
check(TA.save_brain(own, ex, book, base) is True, "brain save")
s = TA.status(base)
check((s["own"], s["picks"], s["exit_shadow"]) == (2, 1, 1), "brain counts")
TA.save_brain(own, ex, book, base)
check(TA.status(base)["own"] == 2, "brain save is idempotent")
own["closed"] = []
book["picks"] = {}
ex["done"] = []
TA.save_brain(own, ex, book, base)
s = TA.status(base)
check((s["own"], s["picks"], s["exit_shadow"]) == (2, 1, 1), "Brain trimming loses nothing")
check(TA.save_brain(None, None, None, base) is True, "empty brain call is fine")

# stale detection
con = sqlite3.connect(os.path.join(base, TA.DUAL_DB))
con.execute("UPDATE meta SET v = ? WHERE k = 'last_sync'", (str(time.time() - 3 * 3600),))
con.commit(); con.close()
s = TA.status(base)
check(s["state"] == "stale" and "h ago" in s["text"], "old save = stale with plain text")

# the safety promise: no delete anywhere, hooks present, route present
src = open(os.path.join(HERE, "trade_archive.py"), encoding="utf-8").read()
check(re.search(r"\b(delete\s+from|drop\s+table|truncate|vacuum)\b", src, re.I) is None, "archive code has no delete / drop / truncate")
dl = open(os.path.join(HERE, "dual_lab.py"), encoding="utf-8").read()
check("_TA.save_dual(data, st)" in dl and dl.index("_TA.save_dual(data, st)") < dl.index("                trim(data)"), "Dual Bot saves BEFORE trim")
check("import trade_archive as _TA" in dl, "import is guarded")
sb = open(os.path.join(HERE, "smart_brain.py"), encoding="utf-8").read()
check("_TA.save_brain(own, ex, book)" in sb, "Brain hook present")
api = open(os.path.join(HERE, "api_server.py"), encoding="utf-8").read()
check('"/api/archive"' in api, "archive route present")
print("OK %d checks" % ok)
