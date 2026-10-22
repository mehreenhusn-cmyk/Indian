"""Test the read-only link between live bot signals and the ping tracker.
Run: cd backend && python test_ping_bridge.py
"""
import json, os, sqlite3, sys, tempfile, time

from recovered_bot.ping_engine import PingEngine
from recovered_bot.ping_radar import PingRadar
from recovered_bot.ping_tracker import PingTracker
from recovered_bot.ping_signal_bridge import SignalBridge

fails = 0
def ok(name, cond):
    global fails
    print(("  OK  " if cond else "  FAIL ") + name)
    if not cond: fails += 1

d = tempfile.mkdtemp()
con = sqlite3.connect(os.path.join(d, "owl.db"))
con.execute("CREATE TABLE signals (id INTEGER PRIMARY KEY, signal_no INT, symbol TEXT, action TEXT, recorded_at REAL, opened INT, bot TEXT)")
con.commit()

# engine with a red BUY ping on AAAUSDT
eng = PingEngine(); rad = PingRadar()
t0 = int(time.time() * 1000) - 20 * 60000
for i in range(6):
    eng.on_closed_candle("AAAUSDT", 100000, 50000, 1.0, t0 + i * 60000)
for i in range(6, 12):
    eng.on_closed_candle("AAAUSDT", 600000, 560000, 1.0, t0 + i * 60000)

store = {}
tr = PingTracker(eng, rad, lambda x: store.update(x), lambda: dict(store))
br = SignalBridge(tr, d)
now = time.time()
con.execute("INSERT INTO signals VALUES (1,101,'AAAUSDT','BUY',?,1,'b1')", (now + 1,))
con.execute("INSERT INTO signals VALUES (2,102,'ZZZUSDT','BUY',?,1,'b1')", (now + 2,))
con.execute("INSERT INTO signals VALUES (3,103,'AAAUSDT','BUY',?,1,'b2')", (now + 3,))
con.commit()
ok("two Bot 1 signals picked up, Bot 2 ignored", br.poll() == 2)
ok("same signals not added twice", br.poll() == 0)
v = {r["symbol"]: r["verdict"] for r in tr.signal_rows}
ok("coin with red ping -> TAKE", v.get("AAAUSDT") == "TAKE")
ok("coin without ping -> SKIP", v.get("ZZZUSDT") == "SKIP")

# closed trades arrive in the archive
with open(os.path.join(d, "closed_trades_archive.jsonl"), "w") as f:
    f.write(json.dumps({"symbol": "AAAUSDT", "signal_no": 101, "opened_at_ts": now + 5, "pnl_usdt": 12.5}) + "\n")
    f.write(json.dumps({"symbol": "ZZZUSDT", "signal_no": 102, "opened_at_ts": now + 6, "pnl_usdt": -8.0}) + "\n")
ok("results matched", br.match_results(now=now + 1000) == 2)
s = tr.score_snapshot()
ok("loss avoided counted from skipped losing trade", s["loss_avoided"] == 8.0)
ok("take pnl counted", s["take_pnl_sum"] == 12.5)
br2 = SignalBridge(tr, os.path.join(d, "missing"))
ok("missing db does not crash", br2.poll() == 0 and br2.status == "NO_DB")
print("\nALL PASSED" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
