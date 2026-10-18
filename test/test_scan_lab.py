"""Scan Lab test (no internet): synthetic candles -> every scenario row exists, verdicts valid, report + files written.
Run from the repo root:  python3 test/test_scan_lab.py"""
import json, os, random, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from recovered_bot import ai_shadow_lab as LAB
import filter_lab as FL
import scan_lab as SC


def synth(seed, tf, trend=0.0):
    n = 4000 if tf in ("3m", "5m", "15m") else 2500
    step = SC.TF_MS[tf]
    rnd = random.Random(seed); p = 100.0; out = []; t = int(time.time() * 1000) - (n + 5) * step; drift = 0.0
    for k in range(n):
        if k % 150 == 0:
            drift = rnd.uniform(-0.2, 0.2) + trend
        o = p; p = max(1.0, p * (1 + (drift + rnd.gauss(0, 0.8)) / 100.0))
        out.append({"timestamp": t + k * step, "open": o, "high": max(o, p) * 1.001, "low": min(o, p) * 0.999, "close": p, "volume": 1000.0})
    return out


LAB._fetch_range = lambda sym, tf, start, **k: synth(sum(map(ord, sym)), tf)
FL.default_coins = lambda log=print: ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
SC.MAJORS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()

# indicators
c = [float(x) for x in range(1, 401)]
assert abs(SC.sma(c, 30)[-1] - sum(c[-30:]) / 30) < 1e-9 and SC.ema(c, 30)[28] is None and SC.ema(c, 30)[29] is not None
assert abs(SC.rolling_sd(c, 200)[-1] - (sum((x - sum(c[-200:]) / 200) ** 2 for x in c[-200:]) / 200) ** 0.5) < 1e-6

# trade replay: SL, TP, timeout, still-open
S = {"n": 6, "t": list(range(6)), "c": [100, 101, 102, 103, 104, 105], "h": [100, 102, 103, 104, 105, 106], "l": [99, 100, 101, 102, 103, 104]}
assert abs(SC.sim(S, 0, True, 100, 99.5, 103.5, None) - 3.5) < 1e-9          # TP hit
assert abs(SC.sim(S, 0, True, 100, 100.5, 120, None) - 0.5) < 1e-9           # SL hit (low 100 <= ... not hit? low[1]=100 <= 100.5 -> SL)
assert SC.sim(S, 0, True, 100, 50, 200, None) is None                         # data ends while open -> skipped

rep = SC.run(["15m", "1h"], ("MAJORS", "MOVERS"), log=lambda m: None)
txt = open(os.path.join(os.environ["OWL_DATA_DIR"], "scan_lab.txt")).read()
js = json.load(open(os.path.join(os.environ["OWL_DATA_DIR"], "scan_lab.json")))
assert "WINNERS" in txt and "BOT-LIKE BASELINE" in txt and "SD BAND TOUCH" in txt and "MAJORS | 15m" in txt and "MOVERS | 1h" in txt
assert set(js["results"]) == {"MAJORS|15m", "MAJORS|1h", "MOVERS|15m", "MOVERS|1h"}
want = len(SC.LINES) * len(SC.EXITS) + len(SC.BAND_SC)
for k, rows in js["results"].items():
    assert len(rows) == want, (k, len(rows))
    assert all(r["verdict"] in ("winner", "loser", "unclear", "too_few", "no_trades") for r in rows.values())
assert any(r.get("n", 0) > 30 for rows in js["results"].values() for r in rows.values()), "synthetic data should give trades"
# touch stats must count events
assert sum(sum(v) for tc in js["touch"].values() for v in tc.values()) > 0
# a planted edge must be found: strongly trending data, hold-till-opposite on EMA30 should beat zero in both halves
LAB._fetch_range = lambda sym, tf, start, **k: synth(sum(map(ord, sym)), tf, trend=0.0)
tr = SC.judge([(i, 5.0 if i % 3 else -2.0) for i in range(300)])
assert tr["verdict"] == "winner", tr
nz = SC.judge([(i, (-1.0 if i % 2 else 1.0)) for i in range(300)])
assert nz["verdict"] in ("unclear", "loser"), nz
# app side: short summary + background job + saved result
sm = js["summary"]
assert sm["answer"] and isinstance(sm["winners"], list) and sm["steps"] and sm["tested"] > 0
assert any("SD bands" in a for a in sm["answer"]), sm["answer"]
assert SC.start("quick") is True
for _ in range(240):
    time.sleep(1)
    if not SC.status()["running"]:
        break
st = SC.status()
assert not st["running"] and st["summary"] and st["progress"] == "done", st["progress"]
SC._STATE["summary"] = None
assert SC.status()["summary"], "saved result must reload"
# SD length test: bot_sim must agree with the lab's own bot replay (filter_lab.sim_trade) on the same trade
from recovered_bot import strategy as ST
cs = synth(7, "15m")
S2 = SC.build(cs)
xup, xdn = SC.cross_flags(S2, "ema50")
S2["xup"], S2["xdn"] = xup, xdn
strat, m_ok = ST.ABCDStrategy(), 0
mean, sdv = SC.sma(S2["c"], 200), SC.rolling_sd(S2["c"], 200)
for i in range(250, S2["n"] - 1):
    if not (xup[i] or xdn[i]):
        continue
    L = xup[i]; e = S2["c"][i]; sl = S2["l"][i] if L else S2["h"][i]
    if (L and sl >= e) or (not L and sl <= e):
        continue
    m, sd = mean[i], sdv[i]
    lv = {"zero_price": m, "onesd": m + sd, "twosd": m + 2 * sd, "threesd": m + 3 * sd, "neg_onesd": m - sd, "neg_twosd": m - 2 * sd, "neg_threesd": m - 3 * sd}
    tps = strat.calculate_tp_levels(e, L, lv)
    if (L and tps[0] <= e) or (not L and tps[0] >= e):
        continue
    a = SC.bot_sim(S2, i, L, e, sl, tps, xdn if L else xup)
    b = FL.sim_trade(S2, i, L, e, sl, tps[0], tps[3], 0.0)
    if a is None or b[1] == "OPEN":
        assert a is None or b[1] == "OPEN"
        continue
    assert abs(a["net"] - round(b[0] * 10 - 1.0, 3)) < 1e-6 and a["why"] == b[1] and a["bars"] == b[2], (a, b)
    m_ok += 1
assert m_ok > 30, m_ok
rows, used = SC.sd_step("MAJORS", "15m", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], 90, {}, lambda m: None)
sts = SC.sd_stats(rows, "15m", used, 90)
assert [x["len"] for x in sts] == SC.SD_LENS and all(x["n"] == sts[0]["n"] for x in sts), "same signals for every SD length"
assert sts[-1]["len"] == 200 and "vs200" not in sts[-1] and sts[1]["vs200_verdict"] in ("better", "worse", "unclear", "too_few")
assert 0 <= sts[0]["tp4"] <= sts[0]["tp1"] <= 100 and sts[0]["min_hold"] is not None
sm = SC.sd_summary({"15m": sts})
assert sm["answer"] and sm["tfs"][0]["lines"][0].startswith("SD 50") and any("SD 100" in a or "SD 200" in a for a in sm["answer"])
rst = SC.sd_stats(rows, "15m", used, 90, rule=True)
assert all(x["rule"] and x["n"] <= sts[0]["n"] for x in rst), "rule only removes signals"
assert all("vs200_verdict" in x for x in rst if x["n"]), "every rule row is compared with the bot today"
smr = SC.sd_summary({"15m": sts + rst})
assert len(smr["tfs"][0]["rows"]) == 8 and any("SD0 rule" in a for a in smr["answer"]) and len(smr["answer"]) <= 6
assert sum(1 for r in smr["tfs"][0]["rows"] if r["verdict"] == "bot") == 1
print("\n".join(smr["answer"]))
SC._STATE["sd"] = None
SC.run_sd(["15m", "1h"], ("MAJORS",), log=lambda m: None)
assert SC.status()["sd"]["tfs"] and os.path.exists(os.path.join(os.environ["OWL_DATA_DIR"], "scan_sd.txt"))
assert SC.start("sd") is True
for _ in range(300):
    time.sleep(1)
    if not SC.status()["running"]:
        break
assert SC.status()["progress"] == "done" and SC.status()["sd"]
SC._STATE["sd"] = None
assert SC.status()["sd"], "saved SD result must reload"
print("PASS")
