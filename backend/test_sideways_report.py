"""Sideways report (smart_brain.sideways_report): groups, USDT, story, steady check, report-only. No network.
Run: cd backend && python3 test_sideways_report.py"""
import os, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smart_brain as B

ok = 0
def check(cond, msg):
    global ok
    assert cond, "FAIL: " + msg
    ok += 1

def tr(i, side, net, status="closed", sym="ETHUSDT"):
    return {"id": i, "s": sym, "t": 1000 + i, "status": status, "net": net, "tg": {"side_main_pct": side, "side_z_pct": side}}

# 1. groups by exact sideways %
check(B.side_group({"side_main_pct": 10, "side_z_pct": 20}) == "trending", "trending")
check(B.side_group({"side_main_pct": 50, "side_z_pct": 50}) == "mixed", "mixed")
check(B.side_group({"side_main_pct": 90, "side_z_pct": 80}) == "sideways", "sideways")
check(B.side_group({"side_main": "main chart sideways", "side_z": "Z pane sideways"}) == "sideways", "tag words still work")

# 2. too few sideways trades = collecting, no verdict
few = [tr(i, 10, 5.0) for i in range(40)] + [tr(100 + i, 90, -5.0) for i in range(5)]
r = B.sideways_report(few)
check(r["status"] == "collecting" and "Collecting" in r["text"] and r["cost"] is None, "collecting")

# 3. sideways loses: planted. 40 trending +10 ROI, 40 sideways -10 ROI (margin 100 -> +-10 USDT each)
lose = [tr(i, 10, 10.0) for i in range(40)] + [tr(100 + i, 90, -10.0) for i in range(40)]
r = B.sideways_report(lose)
g = {x["key"]: x for x in r["groups"]}
check(r["status"] == "ready", "ready")
check(g["trending"]["n"] == 40 and g["trending"]["pnl"] == 400.0 and g["trending"]["win_pct"] == 100, "trending numbers")
check(g["sideways"]["n"] == 40 and g["sideways"]["pnl"] == -400.0 and g["sideways"]["win_pct"] == 0, "sideways numbers")
check(r["cost"] == 400.0 and "cost you 400.00 USDT" in r["text"], "cost text")
check(r["total"] == 0.0 and "+400.00 USDT instead of +0.00" in r["story"] and "only a report" in r["story"], "story")
check(r["steady"] is True and "agree" in r["story"], "both halves agree")
check(any(c["cut"] == 70 and c["n"] == 40 and c["pnl"] == -400.0 for c in r["cuts"]), "cut table")

# 4. sideways does not lose: no cost, says so
win = [tr(i, 90, 6.0) for i in range(35)]
r = B.sideways_report(win)
check(r["cost"] is None and "did not lose" in r["text"], "not a problem")

# 5. halves disagree = careful warning
mix = [tr(i, 90, -10.0) for i in range(20)] + [tr(100 + i, 90, 3.0) for i in range(20)] + [tr(200 + i, 90, 3.0) for i in range(1)]
r = B.sideways_report(mix)
check(r["status"] == "ready" and r["steady"] is False and "Careful" in r["story"], "halves disagree")

# 6. only finished bot trades count; BTC uses its own margin; bad rows do not crash
btc = [tr(i, 90, -10.0, sym="BTCUSDT") for i in range(30)]
r = B.sideways_report(btc)
check(r["groups"][2]["pnl"] == -3000.0, "BTC margin 1000")
odd = [tr(1, 90, 5.0, status="open"), tr(2, 90, 5.0, status="skipped_done"), {"s": "X", "t": 1, "status": "closed", "net": None, "tg": {}}]
check(B.sideways_report(odd)["done"] == 0 and B.sideways_report([])["status"] == "collecting", "ignored rows")

# 7. wired into the view, and read-only (does not change the trades it was given)
snap = [dict(t) for t in lose]
v = B.build_view(rows=[], trades=lose)
check(v["sideways"]["status"] == "ready" and lose == snap, "in view, trades untouched")
print("sideways report: %d checks passed" % ok)
