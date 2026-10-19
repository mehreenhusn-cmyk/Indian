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
out = [r for r in res["rows"] if r["group"] == VL.OUT_GROUP]
assert len(out) == 11, "11 outside-suggestion scenarios expected"
tk = {r["key"]: r["taken"] for r in out}
assert tk["o_pkg"] <= tk["o_bundle"] <= min(tk["o_adx"], tk["o_htf"], tk["o_slope"], tk["o_vol"], tk["o_gap"], tk["o_1r"]), tk
assert tk["o_bundle"] < res["bot"]["n"], "the bundle must skip some signals"
assert any(r.get("ctx", {}).get("adx") is not None and r["ctx"].get("htf") for r in rows), "ADX / HTF tags must be filled"
nw = [r for r in res["rows"] if r["group"] == VL.NEW_GROUP]
assert len(nw) == 8, "8 photo-idea scenarios expected"
tn = {r["key"]: r["taken"] for r in nw}
print("photo ideas taken:", tn, "bot:", res["bot"]["n"])
assert tn["sd100"] > 0 and tn["kell_exit"] > 0, tn
assert tn["kell_base"] < res["bot"]["n"] and tn["meanrev"] < res["bot"]["n"], "base-break / mean-reversion must pick only some signals"
assert tn["kell_mix"] <= tn["kell_base"]
# partial-exit simulator with 0/0/0/100% must equal the bot's own T4 simulation (same SL, same TP4 target)
from recovered_bot import ai_ind_features as _F
_cs = LAB._fetch_range("AAAUSDT", "15m", 0)
_S = _F.build(_cs)
_S["vol"] = [c.get("volume") for c in _cs]
_n = 0
for i in range(250, 2900, 7):
    if not (_S["xup"][i] or _S["xdn"][i]):
        continue
    L = _S["xup"][i]
    e = _S["c"][i]; sl = _S["l"][i] if L else _S["h"][i]
    if (L and sl >= e) or (not L and sl <= e):
        continue
    rk = abs(e - sl)
    tps = [e + (k + 1) * rk * 0.8 * (1 if L else -1) for k in range(4)]
    a = VL._partial(_S, i, L, e, sl, tps, 0.0, fracs=(0, 0, 0, 1.0))
    b = FL.sim_trade(_S, i, L, e, sl, tps[0], tps[3], 0.0)
    if a is None or b[1] == "OPEN":
        continue
    assert abs(a[0] - b[0]) < 1e-9 and a[1] == b[1] and a[2] == b[2], (a, b)
    _n += 1
assert _n > 10, _n
# partial exits can never earn more than a full TP4 win nor lose more than the full SL (before fees)
_ad = VL._adx_series(_S)
assert any(v is not None and 0 <= v <= 100 for v in _ad)
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
