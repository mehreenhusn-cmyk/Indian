"""Smart Brain (smart_brain.py): scores, look-alike probability, patterns, trust meter, read-only guarantee. No network.
Run: cd backend && python3 test_smart_brain.py"""
import json, os, random, sys, tempfile, time
os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smart_brain as B
import tag_lab as TL

ok = 0
def check(cond, msg):
    global ok
    assert cond, "FAIL: " + msg
    ok += 1

def tags(**kw):
    t = {"side_main": "main chart trending", "side_z": "Z pane trending", "src": "MAIN", "order": "Z candle came first (1-2 candles before)",
         "tsi_zero": "TSI with the trade (above/below 0)", "tsi_line": "TSI on the trade side of its signal line", "tsi_hist": "histogram growing",
         "z_ema": "Z candle beyond both EMAs (with trade)", "cloud": "cloud colour with the trade", "zsm": "Z on the trade side of ZSM",
         "z_chop": "Z clean", "main_chop": "main chart clean", "z_room": "lots of room (Z far from the trade side)",
         "diverge": "price and Z agree", "hour": "06-12 UTC"}
    t.update(kw)
    return t

# 1. clean score: clean setup high, dirty setup low, always 0-100
clean = tags()
dirty = tags(side_main="main chart sideways", side_z="Z pane sideways", order="Z candle gave the OPPOSITE signal in the last 5 candles",
             tsi_zero="TSI against the trade", z_ema="Z candle against both EMAs", z_room="stretched (Z already far with the trade)",
             diverge="price and Z disagree", cloud="cloud colour against the trade", zsm="Z on the wrong side of ZSM", tsi_line="TSI on the wrong side of its signal line")
cs, ds = B.clean_score(clean), B.clean_score(dirty)
check(cs >= 90 and ds <= 15 and 0 <= ds <= 100, f"clean {cs} dirty {ds}")
check(B.clean_score(dict(clean, side_main_pct=100, side_z_pct=100)) < cs, "exact sideways % used")

# 2. divergence
check(B.divergence(clean)[0] == 0 and "agree" in B.divergence(clean)[1], "agree")
check(B.divergence(dirty)[0] >= 80 and "disagree" in B.divergence(dirty)[1], "disagree")
check("sideways" in B.divergence(tags(side_main="main chart sideways"))[1], "one pane sideways, other trending")

# 3. fake memory: rows = [sym, tf, t, d, tags, nets, bars]. Clean tags win 70%, dirty tags win 20% (planted rule)
random.seed(7)
nx = len(TL.EXITS); bi = B._bot_i()
def mkrow(i, good):
    tg = tags() if good else dirty
    tgl = [tg[k] for k in TL.DIMS]
    win = random.random() < (0.7 if good else 0.2)
    nets = [(12.0 if win else -9.0) + random.gauss(0, 1)] * nx
    bars = [random.randint(1, 5) if win else random.randint(3, 20)] * nx
    return ["C%d" % (i % 9) + "USDT", "15m", 1_000_000 + i * 900_000, 1, tgl, nets, bars]
rows = [mkrow(i, i % 2 == 0) for i in range(400)]
pr_g, pr_d = B.probability(rows, clean), B.probability(rows, dirty)
check(pr_g and pr_d, "enough look-alikes")
check(pr_g["win_pct"] >= 60 and pr_d["win_pct"] <= 35, f"planted rule found {pr_g['win_pct']} / {pr_d['win_pct']}")
check(pr_g["n"] <= B.K_NEAR and "similar old trades" in pr_g["text"], "text")

# 4. NOT enough data: 5 rows = no number
check(B.probability(rows[:5], clean) is None, "too few look-alikes = None")
sc = B.score_setup(rows[:5], clean)
check(sc["prob"] is None and "Not enough data" in sc["prob_text"], "says not enough data")

# 5. probability only uses OLDER rows
t_cut = rows[100][2]
older = [r for r in rows if r[2] < t_cut]
check(B.probability(rows, clean, t_cut) == B.probability(older, clean), "t_before ignores newer rows")

# 6. bands: clean band wins more than dirty band
bd = {b["band"][:5]: b for b in B.bands(rows)}
check(bd["Clean"]["win_pct"] > bd["Dirty"]["win_pct"] + 30, "bands show the planted edge")

# 7. hours + speed + patterns
hrs = B.hours_table(rows)
check(hrs and all("n" in h for h in hrs), "hours table")
fs = B.fast_slow(rows)
check(fs and 0 <= fs["fast_pct"] <= 100, "fast/slow")
rl, gp = B.patterns(rows)
check(len(rl) > 0 and len(gp) > 0, "stable repeat-loss and good patterns found")
check(all(x["win_pct"] <= 35 for x in rl) and all(x["win_pct"] >= 65 for x in gp), "pattern win rates")
check(B.patterns(rows[:30]) == ([], []), "no patterns from a tiny memory")

# 8. trust meter: a real edge earns trust; pure noise does not
def trades_from(rows_, n, real_edge):
    out = []
    for k in range(n):
        good = k % 2 == 0
        tg = tags() if good else dirty
        win = random.random() < ((0.7 if good else 0.2) if real_edge else 0.5)
        out.append({"id": "t%d" % k, "s": "XUSDT", "f": "15m", "d": 1, "src": "MAIN", "t": 1_000_000 + (len(rows_) + k) * 900_000,
                    "tg": tg, "status": "closed", "net": 12.0 if win else -9.0})
    return out
tr_edge = trades_from(rows, 120, True)
tv = B.trust(rows, tr_edge)
check(tv["verdict"] == "earned" and tv["picks_avg"] > tv["all_avg"], f"edge earns trust: {tv}")
noise_rows = []
for i in range(400):
    r = mkrow(i, i % 2 == 0); w = random.random() < 0.5
    r[5] = [12.0 if w else -9.0] * nx; noise_rows.append(r)
tn = B.trust(noise_rows, trades_from(noise_rows, 120, False))
check(tn["verdict"] in ("not_yet", "learning"), f"noise does not earn trust: {tn['verdict']}")
check(B.trust(rows, tr_edge[:5])["verdict"] == "learning", "few trades = learning")

# 9. read-only on Dual Bot: dual_lab_data.json is byte-for-byte the same after the Brain ran
data = {"rows": {"%d" % i: r for i, r in enumerate(rows)}, "trades": tr_edge, "seen": {}, "boot": {}, "fetched": {"AAAUSDT|15m": 1, "BBBUSDT|15m": 1}}
path = os.path.join(os.environ["OWL_DATA_DIR"], "dual_lab_data.json")
json.dump(data, open(path, "w"))
before = open(path, "rb").read()
r2, t2 = B.read_v1()
check(len(r2) == 400 and len(t2) == 120, "reader reads rows + trades")
v = B.build_view(r2, t2, [], 0)
check(open(path, "rb").read() == before, "dual_lab_data.json untouched")
check(v["status"] == "ready" and v["signals"] and v["trust"]["verdict"] == "earned" and v["bands"], "view is complete")
json.dumps(v)                                                                      # must be JSON-safe for the app
check(len(v["signals"]) <= B.SHOW_TRADES, "signal list is capped")
B._save("smart_brain_view.json", v)
st = B.status()
check(st["running"] and st["state"] == "ready" and st["enabled"], "status running")
B.set_enabled(False)
check(B.status()["state"] == "stopped" and B.ensure_running() is False, "stop switch works")
B.set_enabled(True)

# 10. opportunity scan on a fake market: lists only good setups, never raises, places nothing

# 10. opportunity scan on a fake market: only strong setups are listed, never raises, nothing is written into Dual Bot
import math
import filter_lab as FL
def candles(tf, n, seed):
    rnd = random.Random(seed)
    step = FL.TF_MS[tf]
    latest = (int(time.time() * 1000) // step) * step - step
    p, out = 100.0, []
    for k in range(n):
        o = p
        p = max(1.0, p * (1 + rnd.gauss(0, 0.004) + 0.0008 * math.sin(k / 30.0)))
        out.append({"timestamp": latest - (n - 1 - k) * step, "open": o, "high": max(o, p) * 1.001, "low": min(o, p) * 0.999, "close": p, "volume": 1.0})
    return out
fetch = lambda sym, tf, limit: candles(tf, limit, sum(map(ord, sym + tf)))[-limit:]
before = open(path, "rb").read()
found = B.scan(rows, ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"], fetch)
check(isinstance(found, list) and all(w["clean"] >= 45 and w["div"] <= 55 and (w["prob"] is None or w["prob"]["win_pct"] >= 45) and w["stage"] == "learning" for w in found), "scan in learning stage lists loose setups only")
check(B.scan(rows, ["X"], lambda *a: (_ for _ in ()).throw(RuntimeError("net down"))) == [], "a broken download never stops the scan")
check(open(path, "rb").read() == before, "scan did not touch Dual Bot data")

# 11. the Brain's own paper book: forward only, frozen, shadow until trust is earned, result = Dual Bot's own trade
book = {}
fut = max(t["t"] for t in tr_edge) + 1
new_trades = []
for k in range(40):
    good = k % 2 == 0
    new_trades.append({"id": "n%d" % k, "s": "BTCUSDT" if k == 0 else "YUSDT", "f": "15m", "d": 1, "src": "MAIN", "t": fut + k * 900_000,
                       "tg": tags() if good else dirty, "status": "closed", "net": 12.0 if good else -9.0})
alltr = tr_edge + new_trades
B.update_book(book, rows, alltr, "learning", now_ms=fut)
check(all(t["t"] >= fut for t in alltr if t["id"] in book["seen"]) and len(book["seen"]) == 40, "old trades are not judged with hindsight")
check(len(book["picks"]) == 20 and all(p["mode"] == "shadow" for p in book["picks"].values()), "clean setups picked as shadow before trust")
before_pick = json.dumps(book["picks"], sort_keys=True)
B.update_book(book, rows[:50], alltr, "earned", now_ms=fut)
check(json.dumps(book["picks"], sort_keys=True) == before_pick, "a pick never changes after it was recorded")
extra = [{"id": "z1", "s": "YUSDT", "f": "15m", "d": 1, "src": "MAIN", "t": fut + 99 * 900_000, "tg": tags(), "status": "open"}]
B.update_book(book, rows, alltr + extra, "earned", now_ms=fut)
check(book["picks"]["z1"]["mode"] == "paper" and "z1" in book["seen"], "after trust is earned new picks are paper")
sm = B.book_summary(book, alltr + extra)
check(sm["picks"]["closed"] == 20 and sm["picks"]["wins"] == 20 and sm["all"]["closed"] == 40, "picks vs all signals")
check(sm["picks"]["pnl"] > sm["all"]["pnl"] and sm["picks"]["avg"] > sm["all"]["avg"], "picks beat take-everything on the planted edge")
check(abs(sm["picks"]["pnl"] - (19 * 12.0 * 100 / 100 + 12.0 * 1000 / 100)) < 1e-6, "BTC uses its own 1000 margin, others 100")
check(B.update_book({}, rows[:5], alltr, "earned", now_ms=fut)["picks"] == {}, "no pick without enough look-alikes")
vb = B.build_view(r2, alltr, [], 0, book=book)
check(vb["book"]["picks"]["n"] >= 20 and len(vb["book"]["recent"]) <= 10, "book is in the view")
json.dumps(vb)

# 12. Part 1: the Brain says what it thinks (verdict per setup, one summary on top, per-trade badge map)
sg = B.score_setup(rows, clean)
sd = B.score_setup(rows, dirty)
check(sg["verdict"] == "like" and "Likes it" in sg["verdict_text"], "clean setup with a good record is liked")
check(sd["verdict"] == "dislike" and sd["verdict_text"], "dirty setup is disliked, with a reason")
check(B.score_setup(rows[:5], clean)["verdict"] == "unsure", "too few look-alikes = unsure, not a made-up opinion")
check(B.verdict_of(sg)[0] == ("like" if B.is_pick(sg) else "unsure"), "verdict follows the same rule as the paper-book pick")
vn = B.build_view(r2, t2, [], 0, scan_coins=["AAAUSDT", "BBBUSDT"])
nw = vn["now"]
check(nw["mood"] in ("like", "unsure", "dislike", "idle") and nw["headline"], "summary headline")
check(nw["learning"]["scan_n"] == 2 and nw["learning"]["scan_list"] == ["AAA", "BBB"], "scan coins shown")
check(nw["learning"]["rows"] == 400 and nw["learning"]["need_rows"] == 4 * B.MIN_GROUP and nw["learning"]["next"], "learning block")
check(len(nw["guide"]) == 3, "score colour guide")
live = [x for x in vn["signals"] if x.get("status") in ("open", "skipped")]
if len(live) > 1:
    check(nw["best"] is not None and nw["worst"] is not None and nw["best"]["clean"] >= nw["worst"]["clean"], "best is not worse than worst")
check(len(vn["by_key"]) == len(vn["signals"]) and all(set(v_) == {"clean", "div", "verdict", "text"} for v_ in vn["by_key"].values()), "badge map per trade (coin|timeframe|signal time)")
x0 = vn["signals"][0]
check(vn["by_key"]["%s|%s|%s" % (x0["s"], x0["f"], x0["t"])]["clean"] == x0["clean"], "badge key matches the Dual Bot row fields")
vc = B.build_view(rows[:10], [], [], 0)
check(vc["now"]["mood"] == "collecting" and "Still collecting" in vc["now"]["headline"] and vc["now"]["best"] is None, "collecting state, no opinions")
check(vc["now"]["learning"]["next"].startswith("Next:"), "says what is missing")
th = B.thin_spots(rows[:30] + [dict_row for dict_row in []])
check(isinstance(th, list) and len(th) <= 4, "thin spots capped")
json.dumps(vn); json.dumps(vc)
check(open(path, "rb").read() == before, "dual_lab_data.json still untouched after the new summary")
check(B.build_view([], [])["now"]["mood"] == "collecting", "stopped view still builds")


# 13. Part 3: luck test, risk numbers, worst case, rolling memory
lk = B.luck_test(rows, tr_edge)
check(lk["verdict"] == "solid" and lk["p"] <= 0.05, f"a planted edge is hard to explain by luck: {lk}")
lk_n = B.luck_test(noise_rows, trades_from(noise_rows, 120, False))
check(lk_n["verdict"] in ("maybe", "luck", "learning") and lk_n["verdict"] != "solid", f"pure noise is not called solid: {lk_n['verdict']}")
check(B.luck_test(rows, tr_edge[:5])["verdict"] == "learning" and B.luck_test(rows, tr_edge[:5])["p"] is None, "too few trades = no luck verdict")
check(B.luck_test(rows, tr_edge) == lk, "luck test gives the same answer twice (fixed seed)")
rk = B.risk_stats([10, -5, 10, -20, 10, 10, -5, 10, 10, 10])
check(rk["max_dd"] == 20 and rk["total"] == 40 and rk["cvar5"] == -20 and rk["sharpe"] > 0 and rk["sortino"] > 0, f"risk numbers: {rk}")
check(B.risk_stats([5] * 4) is None, "risk numbers need enough trades")
check(B.risk_stats([5] * 12)["sharpe"] is None and B.risk_stats([5] * 12)["max_dd"] == 0, "no losses: no division by zero")
wc = B.worst_case([10, -5, 10, -20, 10, 10, -5, 10, 10, 10])
check(wc["p95"] >= wc["median"] >= 0 and wc["p95"] >= 20 and "95 of 100" in wc["text"], f"worst case: {wc}")
check(B.worst_case([1, 2]) is None, "worst case needs enough trades")
rv = B.risk_view(book, alltr)
check(rv["picks"] and rv["picks"]["n"] == 20 and rv["all"]["n"] == 40 and rv["worst"], f"risk view {rv}")
check(rv["picks"]["total"] > rv["all"]["total"], "picks earned more than all signals on the planted edge")
check(B.risk_view({"since": fut, "picks": {}}, alltr)["picks"] is None, "no picks = no risk numbers, says why")
# rolling memory: newer look-alikes count more. Old rows say clean wins, the NEWEST rows say clean loses.
old_rows = [mkrow(i, True) for i in range(300)]
for r in old_rows:
    r[5] = [12.0] * nx
new_rows = [mkrow(300 + i, True) for i in range(100)]
for r in new_rows:
    r[5] = [-9.0] * nx
mixed = old_rows + new_rows
prm = B.probability(mixed, clean)
check(prm and prm["win_pct"] < 75, f"rolling memory leans to the newer trades ({prm['win_pct']}% instead of the plain 75%)")
check(B.probability(rows, clean, t_cut) == B.probability(older, clean), "rolling weights still ignore newer rows")
dr = B.recent_vs_old(mixed)
check(dr and dr["recent_win"] == 0 and dr["old_win"] == 100, f"recent vs old: {dr}")
check(B.recent_vs_old(rows[:30]) is None, "no drift line from a tiny memory")
vr = B.build_view(r2, alltr, [], 0, book=book)
check(vr["luck"] and vr["risk"]["picks"] and "drift" in vr, "luck, risk and drift are in the view")
json.dumps(vr)
check(open(path, "rb").read() == before, "dual_lab_data.json still untouched after Part 3")


# 12. Part 1 of auto-learning: stages, today's coins, lessons from own trades, daily limit
import brain_own as BO
check(BO.stage_for(0)[0] == "learning" and BO.stage_for(99)[0] == "learning" and BO.stage_for(100)[0] == "medium" and BO.stage_for(300)[0] == "quality", "stages follow judged own trades")
check(BO.stage_for(0)[1:] == (45, 45, 55) and BO.stage_for(300)[1:] == (60, 55, 43), "loose at first, strict later")
check(BO.next_stage(40) == ("medium", 60) and BO.next_stage(500) == (None, 0), "next stage counter")
st_dead = {"t": 0.0, "c": []}
import filter_lab as _FL
_keep = _FL.default_coins
_FL.default_coins = lambda log=None: (_ for _ in ()).throw(RuntimeError("binance down"))
check(B.today_coins(["OLD1"], now=5e9, state=st_dead) == ["OLD1"], "Binance down: falls back to old coins, never raises")
_FL.default_coins = lambda log=None: ["TODAY1USDT", "TODAY2USDT"]
check(B.today_coins(["OLD1"], now=6e9, state=st_dead) == ["TODAY1USDT", "TODAY2USDT"], "today's coins replace the old ones")
_FL.default_coins = lambda log=None: (_ for _ in ()).throw(RuntimeError("binance down"))
check(B.today_coins(["OLD1"], now=6e9 + 4000, state=st_dead) == ["TODAY1USDT", "TODAY2USDT"], "a failed refresh keeps today's last good list")
_FL.default_coins = _keep

def own_trade(i, net, tg):
    return {"id": "x%d" % i, "s": "AAAUSDT", "f": "15m", "d": 1, "net": net, "closed_at": 1000 + i, "tg": tg, "t": 1000 + i}
bad_tg, good_tg = clean, dict(clean, side_main="main chart sideways")
own_t = {"closed": [own_trade(i, -5.0, bad_tg) for i in range(4)] + [own_trade(10 + i, 8.0, good_tg) for i in range(4)]}
les = B.lessons(own_t)
check(B.lesson_for(les, bad_tg)[0] == "burnt" and B.lesson_for(les, good_tg)[0] == "worked", "burnt and worked lessons")
check(B.lesson_for(les, dirty)[0] is None, "no lesson for a mix it never traded")
check(B.lesson_for(B.lessons({"closed": [own_trade(0, -5.0, bad_tg), own_trade(1, -5.0, bad_tg)]}), bad_tg)[0] is None, "2 trades are too few for a lesson")
# recent counts more: old losses, newest wins -> not burnt any more
mix = {"closed": [own_trade(i, -5.0, bad_tg) for i in range(6)] + [own_trade(100 + i, 9.0, bad_tg) for i in range(60)]}
check(B.lesson_for(B.lessons(mix), bad_tg)[0] == "worked", "newest results weigh more than old mistakes")
# a burnt mix is dropped by the scan
orig_lf = B.lesson_for
B.lesson_for = lambda l, t: ("burnt", "x")
check(B.scan(rows, ["AAAUSDT", "BBBUSDT"], fetch, own_t) == [], "scan drops a burnt setup")
B.lesson_for = orig_lf

# own book: stage + lesson saved on the trade, daily limit, summary shows the stage
now_ms = 1_700_000_000_000
def wi(k):
    return {"s": "C%dUSDT" % k, "f": "15m", "d": 1, "clean": 50, "div": 20, "prob": None, "stage": "learning", "lesson": "l",
            "_plan": {"entry": 1.0, "sl": 0.9, "tps": [1.1], "ct": now_ms + k}, "_tg": clean}
book_o = {}
n_open = BO.open_from(book_o, [wi(k) for k in range(5)], now_ms=now_ms)
check(n_open == 5 and book_o["open"][0]["stage"] == "learning" and book_o["open"][0]["lesson"] == "l", "own trade keeps stage and lesson")
BO.MAX_OPEN_KEEP, BO.MAX_DAY, BO.MAX_OPEN = BO.MAX_OPEN, 6, 99
n2 = BO.open_from(book_o, [wi(k) for k in range(5, 12)], now_ms=now_ms + 1000)
check(n2 == 1 and len(book_o["open"]) == 6, "daily limit of new own trades")
n3 = BO.open_from(book_o, [wi(k) for k in range(12, 14)], now_ms=now_ms + 86_400_000)
check(n3 == 2, "a new trading day starts the count again")
BO.MAX_DAY, BO.MAX_OPEN = 40, BO.MAX_OPEN_KEEP
sm = BO.summary(dict(book_o, closed=[]))
check(sm["stage"] == "learning" and sm["next_stage"] == "medium" and sm["next_in"] == 100, "summary shows stage and what is left")


# 13. retest report: two numbers apart, split by market, read only
import dual_lab as DL
check(B.retest_report({})["status"] == "collecting", "retest: too few signals -> collecting")
def rt_data(side_word):
    d = {"rt": {}, "rows": {}}
    for i in range(30):
        key = "AAA|5m|%d" % i
        tgl = [side_word if n in ("side_main", "side_z") else "x" for n in TL.DIMS]
        d["rows"][key] = ["AAA", "5m", i, 1, tgl, [0] * nx, [1] * nx]
        # 10 signals came back at candle 2 (signal -10, retest +5), 20 never came back (signal -4)
        d["rt"][key] = [i, 1, "MAIN", 1, 1, -10.0, 5.0, 2] if i < 10 else [i, 1, "MAIN", 1, 1, -4.0, None, None]
    return d
rep = B.retest_report(rt_data("main chart sideways"))
k100 = DL.MARGIN / 100.0
check(rep["status"] == "ok" and rep["entered"] == 10 and rep["missed"] == 20, "retest: came back vs never came back")
check(abs(rep["entered_gain"] - 150 * k100) < 0.01 and abs(rep["avoided"] - 80 * k100) < 0.01, "retest: the two numbers are kept apart")
check(abs(rep["total_gain"] - (rep["entered_gain"] + rep["avoided"])) < 0.02, "retest: the two numbers add up to the total")
check(any(g["key"] == "sideways" and g["ready"] for g in rep["groups"]) and not any(g["key"] == "trending" and g["ready"] for g in rep["groups"]), "retest: sideways / trending split")
json.dumps(rep)
check(open(path, "rb").read() == before, "retest report did not touch Dual Bot data")

print("OK %d checks" % ok)
