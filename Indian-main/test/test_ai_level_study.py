"""ai_level_study on FAKE candles (no network). Run: python3 test/test_ai_level_study.py"""
import os, sys, random, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_level_study as L

def series(kind, n=800, seed=5):
    random.seed(seed); px = 100.0; out = []
    for i in range(n):
        px += (-0.05 * (px - 100) if kind == "revert" else 0.0) + random.gauss(0, 0.6)
        out.append({"timestamp": 1_700_000_000_000 + i * 180000, "open": px, "high": px + 0.3, "low": px - 0.3, "close": px})
    return out

# 1) events found; every row well-formed; no event without a full HORIZON after it (no look-ahead into nothing)
c = series("revert"); rows = L.scan(c)
assert len(rows) > 50 and all(len(r) == 6 and 0 <= r[1] <= 7 and r[2] in (0, 1, 2) for r in rows)
assert max(r[0] for r in rows) <= c[-1 - L.HORIZON]["timestamp"]
# 2) incremental: scanning again after the newest event adds nothing (dedupe)
assert L.scan(c, after_ms=max(r[0] for r in rows)) == []
# 3) a mean-reverting market bounces from -2SD more than 50%, a random walk does not clearly (the study must tell them apart)
def rate(rows, lv):
    rs = [r for r in rows if r[1] == lv]; g = sum(r[2] == 1 for r in rs); b = sum(r[2] == 0 for r in rs)
    return g / max(1, g + b), len(rs)
rr = []
for sd in range(6): rr += L.scan(series("revert", seed=sd))
rw = []
for sd in range(6): rw += L.scan(series("walk", seed=sd))
a, na = rate(rr, 1); b, nb = rate(rw, 1)
assert a > 0.6 and a > b + 0.1, (a, na, b, nb)
print("revert vs walk ok", round(a, 2), round(b, 2))
# 4) verdicts: too few = COLLECTING, honest old+new rule
assert L._verdict([[i, 1, 1, 0, 0, 0] for i in range(10)])[0] == "COLLECTING"
good = [[i, 1, 1 if i % 5 else 0, 0, 0, 0] for i in range(60)]          # 80% in old AND new
assert L._verdict(good)[0] == "GOOD"
mixed = [[i, 1, 1 if i < 36 else 0, 0, 0, 0] for i in range(60)]       # good only in the old part
assert L._verdict(mixed)[0] != "GOOD"
bad = [[i, 1, 0 if i % 5 else 1, 0, 0, 0] for i in range(60)]
assert L._verdict(bad)[0] == "BAD"
# 5) screen data: 0 events and too few events both say 'jama ho raha hai'
assert "jama" in L.build_from([])["headline"]
few = L.build_from(rows[:20]); assert few["status"] == "COLLECTING" and "jama" in few["headline"] and few["situations"] == []
full = L.build_from(rr); assert full["status"] == "OK" and len(full["levels"]) == 8
# 6) storage round trip + build() never raises
d = tempfile.mkdtemp(); L.init(d); L._save(rows[:30]); L.init(d)
assert len(L._rows) == 30 and L.build()["n"] == 30
L._rows = None
assert L.build()["status"] in ("COLLECTING", "ERROR", "OK")
print("ALL PASS")
