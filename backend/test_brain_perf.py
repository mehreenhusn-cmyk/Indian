"""Performance numbers (smart_brain.performance): equity curve, rolling win rate, daily results. No network.
Run: cd backend && python3 test_brain_perf.py"""
import os, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smart_brain as B

ok = 0
def check(cond, msg):
    global ok
    assert cond, "FAIL: " + msg
    ok += 1

DAY = 86400
def tr(i, net, day=100, status="closed", sym="ETHUSDT"):
    ts = (day * DAY + i * 60)
    return {"id": i, "s": sym, "t": ts * 1000, "closed_at": ts + 30, "status": status, "net": net, "tg": {"side_main_pct": 10, "side_z_pct": 10}}

# 1. too few = collecting
r = B.performance([tr(i, 5.0) for i in range(3)])
check(r["status"] == "collecting" and r["equity"] == [] and "Collecting" in r["text"], "collecting")

# 2. curve is the running USDT sum (margin 100): +10, -10, +10 ... ends at +30 after 5 trades
nets = [10.0, -10.0, 10.0, 10.0, 10.0]
r = B.performance([tr(i, n) for i, n in enumerate(nets)])
check(r["status"] == "ready" and r["equity"] == [10.0, 0.0, 10.0, 20.0, 30.0], "equity %s" % r["equity"])
check(r["total"] == 30.0 and r["win_pct"] == 80 and r["max_dd"] == 10.0, "totals")
check(r["winrate"] == [], "no win-rate line under %d trades" % B.PERF_WIN)

# 3. win-rate trend: first 20 win, next 20 lose -> starts 100, ends 0
t40 = [tr(i, 5.0) for i in range(20)] + [tr(20 + i, -5.0) for i in range(20)]
r = B.performance(t40)
check(r["winrate"][0] == 100 and r["winrate"][-1] == 0 and r["win_before"] == 100 and r["win_now"] == 0, "win-rate trend")

# 4. daily results: two days, newest first, own totals
two = [tr(i, 10.0, day=100) for i in range(6)] + [tr(10 + i, -10.0, day=101) for i in range(5)]
r = B.performance(two)
check([d["n"] for d in r["days"]] == [5, 6] and r["days"][0]["pnl"] == -50.0 and r["days"][1]["pnl"] == 60.0, "days")
check(r["days"][0]["day"] > r["days"][1]["day"] and r["best_day"] == 60.0 and r["worst_day"] == -50.0, "best / worst day")

# 5. thinning keeps the last point; long lists are capped; BTC uses 1000 margin; open / skipped trades ignored
big = [tr(i, 1.0) for i in range(500)]
r = B.performance(big)
check(len(r["equity"]) == B.PERF_PTS and r["equity"][-1] == 500.0 and r["total"] == 500.0 and r["n"] == 500, "thinned, exact total")
r = B.performance([tr(i, 1.0, sym="BTCUSDT") for i in range(5)])
check(r["total"] == 50.0, "BTC margin 1000")
r = B.performance([tr(i, 5.0) for i in range(5)] + [tr(9, 5.0, status="open"), tr(10, 5.0, status="skipped_done")])
check(r["n"] == 5, "only finished bot trades")

# 6. in the view, trades untouched
snap = [dict(t) for t in t40]
v = B.build_view(rows=[], trades=t40)
check(v["perf"]["status"] == "ready" and t40 == snap, "in view, read only")
print("performance: %d checks passed" % ok)
