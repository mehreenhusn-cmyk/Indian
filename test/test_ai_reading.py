"""Indicator Reading logic test on FAKE lab rows (no network, no bot). Run: python3 test/test_ai_reading.py"""
import os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_reading as R, ai_exit_study as X, ai_shadow_lab as L, ai_ind_features as F, ai_rowcache as RC

random.seed(11)
rows = []
now = 1_700_000_000_000
T = ("T1", "T2", "T3", "T4", "T4n")
for i in range(500):
    ztsi_bad = random.random() < 0.35                 # 35%: Z and TSI both AGAINST the trade
    zone = random.choice(("SD +1..+2", "SD 0..+1", "SD above +2"))
    lab = {"z_tsi": "Z and TSI both AGAINST trade" if ztsi_bad else "Z and TSI both WITH trade",
           "sd_zone": zone, "tsi_vs_sig": "TSI below signal" if ztsi_bad else "TSI above signal",
           "z_zone": "Z -1..+1s", "tsi_pos": "TSI 0..+30"}
    if ztsi_bad:          # fake truth: loses at TP4 hold, but a small TP1 scalp is positive
        o = {"T1": [1.0, "TP", 3], "T2": [-2.0, "SL", 9], "T3": [-2.0, "SL", 9], "T4": [-2.0, "SL", 9], "T4n": [-2.0, "SL", 9]}
    else:                 # confirmed: hold to TP4 pays
        o = {k: [3.0 if k != "T1" else 1.0, "TP", 5] for k in T}
    rows.append({"k": f"S{i}|3m|{i}|B", "s": f"COIN{i % 5}", "tf": "3m", "a": "BUY", "t": now + i * 180_000,
                 "ind": {"x": 1}, "ctx": lab, "o": o})
L._ensure_loaded = lambda: None
RC.set_source(lambda: rows)
F.labels = lambda a, ind, ctx, sig=None: dict(ctx)
X._cfg = lambda n, d: {"leverage": 1, "fee_roi_pct": 0.0, "timeframe": "3m"}.get(n, d)

out = R.build("3m")
assert out["status"] == "OK" and out["signals"] == 500, out
facts = {f["label"]: f for g in out["indicators"] for f in g["facts"]}
bad = facts["Z and TSI both AGAINST trade"]
good = facts["Z and TSI both WITH trade"]
assert bad["verdict"] == "AVOID" and bad["tier"] == "PAKKA", bad
assert good["verdict"] == "GOOD", good
assert bad["exit"]["best"] == "T1", bad["exit"]                 # AI finds: scalp (TP1 pe band) is the better exit there
assert any(h["label"] == "Z and TSI both AGAINST trade" for h in out["habits"]), out["habits"]   # bad AND common
assert out["avoid"] and out["best"], (out["avoid"], out["best"])
assert out["levels"]["rows"] and out["levels"]["cols"], out["levels"]
# a fact with no real effect must stay NORMAL, not GOOD/AVOID
assert facts["Z -1..+1s"]["verdict"] == "NORMAL", facts["Z -1..+1s"]
# too few signals: no verdicts, honest headline
RC.set_source(lambda: rows[:10]); R._out_cache.clear()
few = R.build("3m")
assert few["indicators"] == [] and "kam se kam" in few["headline"], few
print("reading ok:", out["headline"])
print("ALL PASS")
