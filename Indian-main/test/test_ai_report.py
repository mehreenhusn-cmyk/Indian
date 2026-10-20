"""ai_report leakage summary + save-to-Downloads, filter_lab run-all. Run: python3 test/test_ai_report.py"""
import os, sys, time, random, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import filter_lab as FL
from recovered_bot import ai_report as R

rnd = random.Random(2)
def trade(i):
    hold = rnd.choice([2, 4, 8, 20, 45, 90])
    win = rnd.random() < (0.55 if hold > 30 else 0.2)
    pnl = rnd.uniform(1, 6) if win else -rnd.uniform(2, 7)
    t = {"opened_at_ts": 1000 + i * 100, "closed_at_ts": 1000 + i * 100 + hold * 60, "timeframe": rnd.choice(["3m", "5m", "15m"]),
         "entry_zone": rnd.choice(["z1", "z2"]), "fee_usdt": 1.0, "peak_roi_pct": 3 if rnd.random() < 0.8 else 0,
         "tp_hit_levels": rnd.choice([0, 1, [1, 2]]), "clean_exit_reason": rnd.choice(["SL", "TP", "REV"])}
    return {"t": t, "act": rnd.choice(["BUY", "SELL"]), "roi": pnl * 10, "pnl": pnl, "ts": i}
rows = [trade(i) for i in range(200)]
txt = R.leak_text(rows)
for must in ("LEAKAGE SUMMARY", "WITHOUT fees", "were in profit first", "BY HOLD TIME", "1) under 5 min", "BIGGEST LEAKS", "BY EXIT REASON"):
    assert must in txt, must
assert "too few" in R.leak_text(rows[:5])
print(txt[:700])

# save: into a writable Download dir
d = tempfile.mkdtemp()
os.environ["OWL_DOWNLOAD_DIR"] = d
r = R.save_to_downloads("hello report")
assert r["ok"] and os.path.isfile(r["path"]) and open(r["path"]).read() == "hello report", r
# save: no Download folder reachable -> not ok, hint, copy kept next to the data
os.environ["OWL_DOWNLOAD_DIR"] = "/nonexistent/x"
R._download_dirs = lambda: ["/nonexistent/x"]
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
r = R.save_to_downloads("hello report")
assert not r["ok"] and "termux-setup-storage" in r["hint"] and os.path.isfile(r["path"]), r
print("save: ok")

# whole report builds even with no trade data
t = R.build_text()
assert "LEAKAGE SUMMARY" in t and "READ ME FIRST" in t
print("build_text:", len(t), "chars")

# run-all: three timeframes one after the other, status JSON, no second start while running
calls = []
FL.default_coins = lambda log=print: ["AAAUSDT"]
def fake_collect(tf, days, coins, lev, fee, log=print):
    calls.append(tf); time.sleep(0.3)
    return [{"a": "BUY", "s": "X", "tf": tf, "t": i * 300000, "e": 100.0, "sl": 99.0, "tp": [101, 102, 103, 104], "ind": {}, "sig": {}, "net": random.gauss(0, 5)} for i in range(60)]
FL.collect = fake_collect
assert FL.start_all(7) is True and FL.start_all(7) is False
assert FL.status_all()["running"]
for _ in range(50):
    if not FL.status_all()["running"]:
        break
    time.sleep(0.2)
st = FL.status_all()
assert calls == ["3m", "5m", "15m"] and not st["running"] and all(v["state"] == "done" for v in st["tfs"].values()), (calls, st)
print("run-all: ok", st["tfs"]["15m"])
print("PASS")
