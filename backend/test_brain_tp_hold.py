"""brain_tp_hold.py: best exit + hold time per setup mix (report only). No network. Run: cd backend && python3 test_brain_tp_hold.py"""
import os, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_tp_hold as TH
import smart_brain as B
import tag_lab as TL

ok = 0
def check(cond, msg):
    global ok
    assert cond, "FAIL: " + msg
    ok += 1

names = list(TL.EXITS)
bi = names.index(TL.BOT)
TP1 = names.index("close all at TP1")
ORD = {"same": "both on the same candle", "monly": "Z candle gave nothing in the last 5 candles"}
SRC = {"same": "BOTH", "monly": "MAIN"}
n_id = [0]

def row(mix, nets, bars, tf="15m", sym="ETHUSDT"):
    n_id[0] += 1
    tags = ["x"] * len(TL.DIMS)
    tags[TL.DIMS.index("src")], tags[TL.DIMS.index("order")] = SRC[mix], ORD[mix]
    return [sym, tf, 1000 + n_id[0], 1, tags, nets, bars]

def nets(best_i, best_v, bot_v):
    v = [0.0] * len(names)
    v[best_i], v[bi] = best_v, bot_v
    return v

# 1. too few old setups = collecting
r = TH.report([row("same", nets(TP1, 10, 0), [4] * 9) for _ in range(10)])
check(r["status"] == "collecting" and "Collecting" in r["text"] and r["mixes"] == [], "collecting")

# 2. planted: in 'same' TP1 beats the bot by 10 points; in 'monly' the bot's exit is best. BTC ignored.
rows = ([row("same", nets(TP1, 10, 0), [4] * 9) for _ in range(70)] + [row("monly", nets(TP1, -1, 5), [6] * 9) for _ in range(40)]
        + [row("same", nets(TP1, 99, 0), [1] * 9, sym="BTCUSDT") for _ in range(20)])
r = TH.report(rows)
mx = {m["key"]: m for m in r["mixes"]}
check(r["status"] == "ready" and r["n"] == 110, "BTC left out: %s" % r["n"])
check(mx["same"]["best"] == "close all at TP1" and mx["same"]["clearly"] and mx["same"]["gain"] == 10.0, "same: TP1 clearly better")
check(mx["monly"]["best"] == TL.BOT and not mx["monly"]["clearly"] and mx["monly"]["gain"] == 0.0, "monly: bot exit best")
check(mx["same"]["steady"] is True, "gain in both halves")
check(any("same candle" in x.lower() and "more than the bot" in x for x in r["lines"]) or any("Same candle" in x for x in r["lines"]), "line names the mix")

# 3. hold time in minutes: 15m candles x bars. winners 4 candles = 60 min, losers 2 candles = 30 min
rows = [row("same", nets(TP1, 10, 5), [4] * 9) for _ in range(20)] + [row("same", nets(TP1, -3, -3), [2] * 9) for _ in range(20)]
h = TH.report(rows)["all"]["hold_bot"]
check(h["win_min"] == 60 and h["loss_min"] == 30, "minutes: %s" % h)
check(h["fast_pct"] == 100, "all winners end within 6 candles")
h5 = TH.report([row("same", nets(TP1, 10, 5), [4] * 9, tf="5m") for _ in range(40)])["all"]["hold_bot"]
check(h5["win_min"] == 20, "5m candles = 5 min each")

# 4. halves disagree: older half gain +10, newer half gain -2 (still a positive average, not trusted)
rows = [row("same", nets(TP1, 10, 0), [4] * 9) for _ in range(40)] + [row("same", nets(TP1, -2, 0), [4] * 9) for _ in range(40)]
m = TH.report(rows)["mixes"][0]
check(m["steady"] is False, "halves disagree")
check(any("older and the newer half disagree" in x for x in TH.report(rows)["lines"]) or not m["clearly"], "warns or not clear")

# 5. no mix beats the bot -> says keep it; junk rows never crash; view hook
r = TH.report([row("same", nets(TP1, 0, 3), [4] * 9) for _ in range(40)])
check(any("No setup mix has an exit" in x for x in r["lines"]), "keep the bot's exit")
check(B._tphold_view([["bad"]])["status"] in ("collecting", "error"), "junk rows no crash")
check(B._tphold_view(rows)["status"] == "ready", "view hook")
check("tp_hold" in B.build_view(rows=[], trades=[]), "in build_view")
print("brain_tp_hold OK: %d checks" % ok)
