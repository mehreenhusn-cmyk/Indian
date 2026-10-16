"""Phase 2-4 logic test on FAKE lab rows (no network, no bot). Run: python3 test/test_ai_phase234.py"""
import os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_exit_study as X, ai_wait_study as W, ai_advice as A, ai_shadow_lab as L, ai_ind_features as F, ai_rowcache as RC

random.seed(7)
rows = []
now = 1_700_000_000_000
for i in range(400):
    side = random.random() < 0.3                     # 30% sideways
    both = (not side) and random.random() < 0.5
    lab = {"move": "sideways (small range, flat EMA)" if side else "trending WITH trade",
           "z_tsi": "Z and TSI both WITH trade" if both else "Z WITH but TSI AGAINST"}
    # fake truth: sideways = TP1 small win then reversal (T1 good, T4 bad); confirmed = T4 great
    if side:
        o = {"T1": [1.5, "TP", 3], "T2": [-1.5, "SL", 9], "T3": [-1.5, "SL", 9], "T4": [-1.5, "SL", 9], "T4n": [-1.5, "SL", 9]}
    elif both:
        o = {k: [1.2 if k not in ("T1",) else 0.3, "TP", 5] for k in ("T1", "T2", "T3", "T4", "T4n")}
    else:
        o = {"T1": [0.2, "TP", 3], "T2": [-0.4, "SL", 9], "T3": [-0.4, "SL", 9], "T4": [-0.4, "SL", 9], "T4n": [-0.4, "SL", 9]}
    rows.append({"k": f"S{i % 4}|3m|{i}|B", "s": f"COIN{i % 4}", "tf": "3m", "a": "BUY", "t": now + i * 180_000,
                 "ind": {"x": 1}, "ctx": lab, "o": o})
rows.append({"k": "open", "s": "X", "tf": "3m", "a": "BUY", "t": now, "ind": {"x": 1}, "ctx": {},
             "o": {k: [0, "OPEN", 1] for k in ("T1", "T2", "T3", "T4", "T4n")}})
L._ensure_loaded = lambda: None
RC.set_source(lambda: rows)
F.labels = lambda a, ind, ctx, sig=None: dict(ctx)
X._cfg = lambda n, d: {"leverage": 1, "fee_roi_pct": 0.0, "timeframe": "3m"}.get(n, d)

x = X.build("3m")
assert x["signals"] == 400, x["signals"]            # OPEN row ignored
sc = {s["label"]: s for s in x["scenarios"]}
side = sc["sideways (small range, flat EMA)"]
assert side["best"] == "T1" and side["verdict"] == "CLEAR", side     # AI finds: sideways -> close at TP1
trend = sc["trending WITH trade"]
assert trend["best"] in ("T4", "T4n", "T2", "T3") or trend["verdict"] == "SAME", trend
print("exit study ok:", x["headline"])

w = W.build("3m")
assert w["verdict"] == "CLEAR", w
assert w["confirm"]["keep_avg"] > w["confirm"]["bot_avg"]
assert w["coins"] and w["coins"][0]["sl"] >= 3
print("wait study ok:", w["headline"])

# too few data must never say CLEAR
rows[:] = rows[:40]
RC.reset(); X._out_cache.clear()
assert X.build("3m")["status"] == "TOO_FEW" and W.build("3m")["verdict"] == "TOO_FEW"
print("too-few guard ok")

# advice badge
assert A._badge({"move": "sideways (small range, flat EMA)", "z_tsi": "Z WITH but TSI AGAINST"})[0] == "skip"
assert A._badge({"move": "trending WITH trade", "z_tsi": "Z and TSI both WITH trade"})[0] == "ok"
assert A._badge({"move": "trending WITH trade", "z_tsi": "Z AGAINST but TSI WITH"})[0] == "warn"
rows[:] = [{"k": "a", "s": "COIN1", "tf": "3m", "a": "SELL", "t": now, "ind": {"x": 1},
            "ctx": {"move": "sideways (small range, flat EMA)", "z_tsi": "Z WITH but TSI AGAINST"},
            "o": {k: [0.1, "TP", 2] for k in ("T1", "T2", "T3", "T4", "T4n")}}]
RC.reset()
b = A.for_positions([{"id": 5, "symbol": "COIN1", "side": "SELL", "timeframe": "3m", "opened_at_ts": now / 1000 + 30},
                     {"id": 6, "symbol": "NOPE", "side": "BUY", "opened_at_ts": now / 1000}])
assert b["5"]["level"] == "skip" and "6" not in b, b
print("advice ok:", b["5"]["text"])
print("ALL PASS")
