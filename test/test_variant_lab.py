"""Strategy Lab test (no internet): synthetic candles -> every scenario gets a row, the table has the bot line, the job saves + reloads.
Run from the repo root:  python3 test/test_variant_lab.py"""
import os, random, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from recovered_bot import ai_shadow_lab as LAB
import filter_lab as FL
import variant_lab as VL


def synth(seed, n=3000, tf_ms=900000):
    rnd = random.Random(seed); p = 100.0; out = []; t = int(time.time() * 1000) - n * tf_ms - 10 * tf_ms; drift = 0.0
    for k in range(n):
        if k % 120 == 0:
            drift = rnd.uniform(-0.15, 0.15)
        o = p; p = max(1.0, p * (1 + (drift + rnd.gauss(0, 0.9)) / 100.0))
        out.append({"timestamp": t + k * tf_ms, "open": o, "high": max(o, p) * 1.001, "low": min(o, p) * 0.999, "close": p, "volume": 1000.0,
                    "tbv": 1000.0 * min(0.95, max(0.05, 0.5 + (p - o) / o * 25 + rnd.gauss(0, 0.1)))})
    return out


LAB._fetch_range = lambda sym, tf, start, **k: synth(sum(map(ord, sym)), 3000, FL.TF_MS[tf])
FL.default_coins = lambda log=print: ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"]
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()

FL.EXTRA_ENRICH = VL.enrich
rows = FL.collect("15m", 20, FL.default_coins(), 10.0, 1.0, log=lambda m: None)
res = VL.analyse(rows)
assert res["ok"] and len(res["rows"]) == len(VL.SCENARIOS), "every scenario must have a row"
assert all(r["verdict"] in ("better", "worse", "unclear", "not_enough") for r in res["rows"])
assert res["answer"] and res["answer"][0].startswith("Bot today")
cv = [r for r in res["rows"] if r["group"] == "CVD (order flow)"]
assert len(cv) == 6, "6 CVD scenarios expected"
assert any(r["taken"] < res["bot"]["n"] for r in cv), "a CVD gate must skip some signals"
assert all(r["group"] in VL.GROUP_ORDER for r in res["rows"])
assert any((r.get("cvd") or {}).get("s3") is not None for r in rows), "CVD tags must be filled when tbv exists"
# CVD patch must keep the real reader intact after use
from recovered_bot import ai_shadow_lab as _L
_o = _L._to_candles
_rs = VL._patch_candles()
_raw = [[1000, "1", "2", "0.5", "1.5", "10", 1999, "0", 5, "7"]]
_c = _L._to_candles(_raw, 10**13)
assert _c and _c[0]["tbv"] == 7.0
_rs()
assert _L._to_candles is _o
# no tbv at all -> scenarios still run (gates keep every signal)
for r in rows:
    r.pop("cvd", None)
assert VL.analyse(rows)["ok"]
tiny = VL.analyse(rows[:10])
assert tiny["ok"] is False and tiny["answer"]
assert VL.start(20) is True
for _ in range(180):
    time.sleep(1)
    if not VL.status()["running"]:
        break
st = VL.status()
assert not st["running"] and all(v["state"] == "done" for v in st["tfs"].values()), st["progress"]
VL._STATE["tfs"] = {}
assert all(v["state"] == "done" for v in VL.status()["tfs"].values()), "saved result must reload"
print("PASS")
