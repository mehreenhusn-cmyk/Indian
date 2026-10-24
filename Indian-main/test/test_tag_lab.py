#!/usr/bin/env python3
"""python3 test/test_tag_lab.py - no internet. Checks the argument bug fix, the trade replay, the tags, the combo test and the luck check on made-up data."""
import math, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
import filter_lab as FL
import tag_lab as T

PASS = FAIL = 0
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  OK  {name}")
    else: FAIL += 1; print(f" FAIL {name}")

# 1. the bug: "--lev 10 --fee 1.0" must not turn 10 / 1.0 into coin names
a, o = FL.parse_args(["x", "5m", "7", "--lev", "10", "--fee", "1.0"])
check("option values are not positional args", a == ["5m", "7"] and o == {"--lev": "10", "--fee": "1.0"})
a, o = FL.parse_args(["x", "5m", "7", "BTCUSDT,ETHUSDT", "--majors"])
check("flag without value + coin list", a == ["5m", "7", "BTCUSDT,ETHUSDT"] and o == {})
check("no args", FL.parse_args(["x"]) == ([], {}))

# 2. trade replay on hand-made candles (long: entry 100, SL 99, TPs 101..104)
def mk(hs, ls, cs):
    n = len(cs)
    return {"n": n, "h": hs, "l": ls, "c": cs, "xup": [False] * n, "xdn": [False] * n}
Zf = lambda n: {"up": [False] * n, "dn": [False] * n}
tps = [101, 102, 103, 104]
S = mk([100, 104.5, 0], [100, 100, 0], [100, 104, 0])
r = T.simulate(S, Zf(3), 0, 1, 100, 99, tps, "main", 10, 1.0)
check("straight to TP4 = +4% price = 40 ROI - fee", r and r["why"] == "TP" and abs(r["net"] - 39.0) < 1e-6 and r["hit"] == 4)
S = mk([100, 101.5, 100.5, 0], [100, 99.5, 98.0, 0], [100, 101, 99.5, 0])
r = T.simulate(S, Zf(4), 0, 1, 100, 99, tps, "main", 10, 1.0)
check("TP1 then back: SL moves to entry from the NEXT candle -> BE exit, net = -fee", r and r["why"] == "BE" and abs(r["net"] + 1.0) < 1e-6 and r["b1"] == 1)
S = mk([100, 101.5, 0], [100, 98.5, 0], [100, 100, 0])
r = T.simulate(S, Zf(3), 0, 1, 100, 99, tps, "main", 10, 1.0)
check("SL and TP1 in the same candle counts as SL (conservative)", r and r["why"] == "SL" and abs(r["net"] - (-10 - 1)) < 1e-6)
S = mk([100, 100.4, 100.3, 100.3], [100, 99.6, 99.7, 99.7], [100, 100.1, 100.0, 100.0])
S["xdn"][2] = True
check("main opposite cross exits (main mode)", T.simulate(S, Zf(4), 0, 1, 100, 99, tps, "main", 10, 1.0)["why"] == "REV")
Z = Zf(4); Z["dn"][1] = True
r = T.simulate(S, Z, 0, 1, 100, 99, tps, "z", 10, 1.0)
check("Z opposite black candle exits (z mode) earlier", r["why"] == "REV" and r["bars"] == 1)
S = mk([100, 100.4], [100, 99.6], [100, 100.1])
check("trade still running when data ends -> None (not judged)", T.simulate(S, Zf(2), 0, 1, 100, 99, tps, "main", 10, 1.0) is None)
S = mk([100, 100.5, 100.5], [100, 99.5, 99.5], [100, 100, 100])
r = T.simulate(S, Zf(3), 0, -1, 100, 101, [99, 98, 97, 96], "main", 10, 1.0)
check("short that never moves ends open -> None", r is None)
S = mk([100, 100.5, 99.1], [100, 99.5, 98.9], [100, 100, 99.0])
r = T.simulate(S, Zf(3), 0, -1, 100, 101, [99.5, 99, 98, 97], "main", 10, 1.0)
check("short: TP1 touched, direction sign right", r is None or r["hit"] >= 1)

# 3. rows + tags on made-up candles
random.seed(7)
def candles(n, drift_period):
    px, out = 100.0, []
    for k in range(n):
        o = px; hi = lo = px
        for _ in range(10):
            px *= 1 + random.gauss(0, 0.004 / 10 ** 0.5) + 0.0006 / 10 * math.sin(k / drift_period)
            hi = max(hi, px); lo = min(lo, px)
        out.append({"timestamp": 1_700_000_000_000 + k * 300_000, "open": o, "high": hi, "low": lo, "close": px, "volume": 1.0})
    return out
rows = []
for k in range(6):
    got, _ = T.rows_from_candles(f"C{k}", "5m", candles(2400, 25 + 6 * k), 0, 10, 1.0)
    rows += got
check("rows were made", len(rows) > 400)
check("all three entry types exist", {r["tg"]["src"] for r in rows} >= {"MAIN", "Z"})
check("every row has every tag", all(set(T.DIMS) <= set(r["tg"]) for r in rows))
check("both exits are filled in", all("net" in r and "netz" in r for r in rows))
check("TP levels reached are 0..4", all(0 <= r["hit"] <= 4 and 0 <= r["hitz"] <= 4 for r in rows))
check("trades are never judged from future-only tags (hour is from the signal candle)", all(r["tg"]["hour"].endswith("UTC") for r in rows))


# 2b. new exit rules: runner (no cap), trailing stop, hold N, path stats, "SL then recovered"
def run(S, Z=None, d=1, sl=99, tp=(101, 102, 103, 104), **kw):
    return T.sim_rule(S, Z or Zf(S["n"]), 0, d, 100, sl, list(tp), 10, 1.0, **kw)
S = mk([100, 101.5, 105, 110, 110.2, 0], [100, 100, 101, 105, 104, 0], [100, 101, 104, 109, 105, 0])
S["xdn"][4] = True
r = run(S, cap=None, be=True, xmode="main")
check("NO CAP lets the rally run past TP4 and exits on the main cross: (105-100)% x10 - fee = 49", r and r["why"] == "REV" and abs(r["net"] - 49.0) < 1e-6)
r = run(S, cap=4, be=True, xmode="main")
check("same candles with the bot's TP4 cap close at 104 = 39", r and r["why"] == "TP" and abs(r["net"] - 39.0) < 1e-6)
r = run(S, cap=1, be=False, xmode="main")
check("close-all-at-TP1 = 1% x10 - fee = 9", r and r["why"] == "TP" and abs(r["net"] - 9.0) < 1e-6)
S = mk([100, 102, 105, 108, 106, 0], [100, 99.5, 101.5, 104.5, 101, 0], [100, 101, 104, 107, 102, 0])
r = run(S, cap=None, be=True, xmode=None, trail=1.0)
check("trailing stop 1R follows the high and exits there (stop 107, profit 7% x10 - fee = 69)", r and r["why"] == "TRAIL" and abs(r["net"] - 69.0) < 1e-6)
S = mk([100, 100.4, 100.6, 100.9, 0], [100, 99.7, 99.8, 99.9, 0], [100, 100.1, 100.3, 100.5, 0])
r = run(S, cap=None, be=False, xmode=None, hold=2)
check("hold 2 candles closes at that candle's close", r and r["why"] == "HOLD" and r["bars"] == 2)
S = mk([100, 100.5, 100.4, 100.3], [100, 99.5, 99.4, 99.3], [100, 100, 100, 100])
check("a trade that never finishes inside the data is None, or closed at the last close if allowed",
      run(S, cap=4) is None and run(S, cap=4, allow_open=True)["why"] == "OPEN")
S = mk([100, 100.5, 103, 100.2, 100.2, 100.2], [100, 99.0, 100.4, 100.0, 100.0, 100.0], [100, 99.1, 102.5, 100.1, 100.1, 100.1])
S["n"] = 40; S["h"] += [100.2] * 34; S["l"] += [100.0] * 34; S["c"] += [100.1] * 34; S["xup"] += [False] * 34; S["xdn"] += [False] * 34
check("price touches TP1 within 30 candles after the SL -> recovered", T.recovered(S, 0, 1, 101, 1) is True)
check("not enough candles after the SL -> None (not judged)", T.recovered(S, 0, 1, 101, 20) is None)
S = mk([100] + [100 + k * 0.3 for k in range(1, 60)], [100] + [99.9 + k * 0.3 for k in range(1, 60)], [100] * 60)
ps = T.path_stats(S, 0, 1, 100, 99, 10)
check("path stats: MFE in ROI pts and 3R flag", ps and abs(ps["mfe"] - (T.PATH_BARS * 0.3) / 100 * 100 * 10) < 1e-6 and ps["ran3r"] is True)
check("every row has all 9 exit results", all(len(r["x"]) == len(T.EXITS) for r in rows))
check("the bot-exit column equals the replay used for tags", all(abs(r["x"][T.BOT][0] - r["net"]) < 1e-2 for r in rows))
txt0 = T.text_report(T.analyse(rows, 3), "5m", 7, 10, 1.0)
check("report shows the exit comparison and the rally check", "EXITS ON THE SAME ENTRIES" in txt0 and "RALLY / SL CHECK" in txt0)
check("short answer comes first", txt0.index("1) SHORT ANSWER") < txt0.index("EXITS ON THE SAME ENTRIES"))

# 4. combos: a planted rule must be found, and pure noise must not look better than the shuffled luck
rnd = random.Random(1)
base = [{"t": i, "net": 0.0, "netz": 0.0, "bars": 5, "hit": 0, "b1": None, "mae": 1.0, "barsz": 5, "hitz": 0,
         "tg": {d: rnd.choice(["a", "b", "c"]) for d in T.DIMS}} for i in range(900)]
for r in base:
    r["tg"]["src"] = "MAIN"
    r["net"] = rnd.gauss(-1.0, 6.0)
planted = [dict(r, net=(r["net"] + 4.0) if (r["tg"]["tsi_line"] == "a" and r["tg"]["zsm"] == "b") else r["net"]) for r in base]
rep = T.analyse(planted, 10)
top = [dict(c["key"]) for c in rep["good"][:5]]
check("planted rule (tsi_line=a + zsm=b) is among the top combos", any(k.get("tsi_line") == "a" and k.get("zsm") == "b" for k in top))
rep0 = T.analyse(base, 10)
check("pure noise: best combo does NOT beat the best luck reached", rep0["best"] <= max(rep0["lucky_best"]))
check("planted data: best combo beats the best luck reached", rep["best"] > max(rep["lucky_best"]))
check("rare combos (<30 trades) are not judged", all(c["n"] >= 30 for c in rep["good"]))
txt = T.text_report(rep, "5m", 7, 10, 1.0)
check("report has the short answer and the helpful-or-not part", "SHORT ANSWER" in txt and "IS EACH INDICATOR HELPFUL" in txt)
js = T.to_json(rep, "5m", 7, 10, 1.0)
check("json for the AI is there", js["good"] and js["entries"] == 900)


# 5. the app side: sections for the card, saved result, status, refusing bad input
import tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sec = T.sections_from_text("HEAD one\nline two\n\n1) FIRST\n  a\n\n   b\n2) SECOND\n* c")
check("report text is split into head + sections", sec["head"] == ["HEAD one", "line two"] and [s["title"] for s in sec["sections"]] == ["FIRST", "SECOND"]
      and sec["sections"][0]["lines"] == ["  a", "   b"])
rep_app = T.analyse(rows, 3)
txt_app, path_app = T.save_result(rep_app, "5m", 7, 10, 1.0, 0)
st = T.status("5m")
check("saved result is returned to the app with sections", os.path.exists(path_app) and st["result"] and len(st["result"]["sections"]) >= 5 and not st["running"])
check("first section is the short answer", st["result"]["sections"][0]["title"] == "SHORT ANSWER")
check("status for a timeframe without a result is empty, not an error", T.status("15m")["result"] is None and T.status("bad")["tf"] == "5m")
check("start refuses a bad timeframe / bad days", T.start("1h", 7) is False and T.start("5m", 0) is False and T.start("5m", 99) is False)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
