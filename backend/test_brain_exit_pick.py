"""brain_exit_pick.py: learns which exit style (full TP / half TP / hold) worked. No network. Run: cd backend && python3 test_brain_exit_pick.py"""
import os, sys, tempfile
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_exit_pick as XP
import brain_own as BO
import smart_brain as B
import tag_lab as TL
ok = 0
def check(c, m):
    global ok
    assert c, "FAIL: " + m
    ok += 1
names = list(TL.EXITS)
BI, T2, HOLD = names.index(TL.BOT), names.index("close all at TP2"), names.index("NO CAP, trail 3R")
tg = {"side_main": "main chart trending", "side_z": "Z pane trending", "src": "MAIN", "order": "o", "tsi_zero": "a", "tsi_line": "b", "tsi_hist": "c",
      "z_ema": "d", "cloud": "e", "zsm": "f", "z_chop": "g", "main_chop": "h", "z_room": "i", "diverge": "j", "hour": "06-12 UTC"}
def row(i, nets, t=None):
    return ["C%d" % i, "15m", t if t is not None else 1000 + i, 1, [tg.get(k) for k in TL.DIMS], list(nets), [3] * len(names)]
def nets(bot, tp2, hold=0.0):
    n = [0.0] * len(names)
    n[BI], n[T2], n[HOLD] = bot, tp2, hold
    return n
# 1. kinds
check(XP.kind_of(TL.BOT) == "FULL" and XP.kind_of("close all at TP2") == "HALF" and XP.kind_of("close all at TP1") == "HALF", "full / half")
check(XP.kind_of("NO CAP, trail 3R") == "HOLD" and XP.kind_of("close after 12 candles") == "TIME", "hold / time")
# 2. planted world: half TP clearly better than the bot's exit among look-alikes
rows = [row(i, nets(-5.0, 10.0)) for i in range(60)]
ex, why = XP.pick(rows, tg)
check(ex == "close all at TP2" and "HALF TP" in why and "+10.0" in why, "picks the clearly better style: " + ex)
# bot's own exit best -> keeps default and says so
rows2 = [row(i, nets(10.0, -5.0)) for i in range(60)]
ex2, why2 = XP.pick(rows2, tg)
check(ex2 == TL.BOT and "no exit style was clearly better" in why2, "keeps the bot's exit")
# hold best
ex3, _ = XP.pick([row(i, nets(0.0, 1.0, 15.0)) for i in range(60)], tg)
check(ex3 == "NO CAP, trail 3R", "can choose hold")
# too few look-alikes, and only OLDER trades count
ex4, why4 = XP.pick(rows[:10], tg)
check(ex4 == TL.BOT and "Too few" in why4, "few look-alikes = default")
check(XP.pick(rows, tg, t_before=1010)[0] == TL.BOT, "only older rows count")
# a gap smaller than the margin is not enough
ex5, _ = XP.pick([row(i, nets(0.0, 2.0)) for i in range(60)], tg)
check(ex5 == TL.BOT, "small difference keeps default")
# 3. overall table
t = XP.exit_table(rows)
check(t["status"] == "ready" and len(t["table"]) == len(names) and t["table"][0]["name"] == "close all at TP2" and t["table"][0]["best"], "table sorted, best marked")
check("did best" in t["text"] and XP.exit_table(rows[:5])["status"] == "collecting", "text and collecting state")
# 4. own trades use the picked exit and show it
w = [{"s": "AAAUSDT", "f": "15m", "d": 1, "clean": 80, "div": 10, "prob": {"win_pct": 60, "n": 30}, "_plan": {"entry": 100.0, "sl": 99.0, "tps": [101, 102, 103, 104.0], "ct": 5}, "_tg": tg}]
own = {}
BO.open_from(own, w, pick_fn=lambda g: XP.pick(rows, g))
check(own["open"][0]["exit"] == "close all at TP2" and "look-alikes" in own["open"][0]["why_exit"], "own trade stores the chosen exit and why")
w2 = [{"s": "BBBUSDT", "f": "15m", "d": 1, "clean": 80, "div": 10, "prob": {"win_pct": 60, "n": 30}, "_plan": {"entry": 100.0, "sl": 99.0, "tps": [101, 102, 103, 104.0], "ct": 6}, "_tg": tg}]
BO.open_from(own, w2, pick_fn=lambda g: 1 / 0)
check(own["open"][1]["exit"] == BO.EXIT_NAME, "a failing picker falls back to the default exit")
sm = BO.summary(own)
check(sm["open"][0]["kind"] == "HALF TP" and sm["open"][1]["kind"] == "FULL TP", "summary shows the exit style")
own["closed"] = [{"s": "A", "f": "15m", "d": 1, "net": 5.0, "exit": "close all at TP2", "closed_at": 1}, {"s": "B", "f": "15m", "d": 1, "net": -3.0, "exit": TL.BOT, "closed_at": 2}]
own["open"] = []
sm = BO.summary(own)
by = {b["kind"]: b for b in sm["by_exit"]}
check(by["HALF TP"]["pnl"] == 5.0 and by["FULL TP"]["pnl"] == -3.0 and by["HALF TP"]["wins"] == 1, "results grouped by exit style")
# 5. Brain view carries the table
check(B.build_view(rows, [])["exit_pick"]["status"] == "ready" and B.build_view([], [])["exit_pick"]["status"] == "collecting", "exit_pick block in Brain view")
print("OK %d checks" % ok)
