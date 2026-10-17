"""filter_lab: noise must not be called CONFIRMED, a planted bad group must be. Run: python3 test/test_filter_lab.py"""
import os, sys, random
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import filter_lab as FL

def mk(i, bad, rnd, planted):
    net = rnd.gauss(0.0, 8.0) - (6.0 if (planted and bad) else 0.0)
    return {"a": "BUY", "s": "X", "tf": "5m", "t": i * 300000, "e": 100.0, "sl": 99.0, "tp": [101.0, 102, 103, 104],
            "ind": {"z": 0.5, "dif": -1.0 if bad else 1.0, "tsi": 5, "zd3": 0.1}, "sig": {"cross_n": 1, "zone": "z"}, "net": net}

def run(planted, seed):
    rnd = random.Random(seed)
    rows = [mk(i, rnd.random() < 0.4, rnd, planted) for i in range(600)]
    old, new = FL.split_rows(rows)
    return FL.judge(old, new, FL._g_tsi_line)["verdict"]

noise = [run(False, s) for s in range(60)]
false_pos = sum(v.startswith("CONFIRMED") for v in noise)
planted = [run(True, s) for s in range(30)]
found = sum(v.startswith("CONFIRMED") for v in planted)
print(f"noise: {false_pos}/60 false CONFIRMED | planted: {found}/30 found")
assert false_pos <= 3, false_pos
assert found >= 25, found
print("PASS")
