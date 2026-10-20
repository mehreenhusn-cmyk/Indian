"""AI Pick: proven situations -> TAKE / SKIP / WATCH. Run: python3 test/test_ai_pick.py"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from recovered_bot import ai_pick as P, ai_desk as D, ai_exit_study as X

LIVE = X.LIVE
def row(a, lab, v):
    return {"a": a, "lab": lab, "v": {LIVE: v}}

def wob(i, base):                      # a little spread around `base`, deterministic
    return base + ((i % 5) - 2) * 0.5

# --- counting: strong + stable edge -> TAKING
rows = []
for i in range(60):
    rows.append(row("BUY", {"sd_zone": "Zone A", "tsi_4zone": "TSI up"}, wob(i, 3.0)))
for i in range(60):
    rows.append(row("BUY", {"sd_zone": "Zone B", "tsi_4zone": "TSI down"}, wob(i, -3.0)))
for i in range(12):                    # few signals: never judged
    rows.append(row("BUY", {"sd_zone": "Zone C"}, 8.0))
for i in range(80):                    # older half good, newer half bad: not TAKING
    rows.append(row("BUY", {"sd_zone": "Zone D"}, wob(i, 4.0 if i < 40 else -2.0)))
book = P._count("3m", rows)
g = lambda t: book["BUY|" + t]
assert g("Zone A")["status"] == "TAKING", g("Zone A")
assert g("Zone B")["status"] == "AVOID", g("Zone B")
assert g("Zone C")["status"] == "WATCHING" and "Only 12" in g("Zone C")["why"]
assert g("Zone D")["status"] != "TAKING", g("Zone D")
print("counting ok")

# --- one lonely lucky run does not pass the floor even with a huge average
assert P._stats([20.0] * 5)["n"] == 5 and P._raw_status(P._stats([20.0] * 5))[0] == "WATCHING"
# --- big edge needs few signals, small edge needs many
big = [wob(i, 5.0) for i in range(30)]
small = [5.0 if i % 2 else -4.3 for i in range(30)]       # avg +0.35 but very noisy
assert P._raw_status(P._stats(big))[0] == "TAKING"
assert P._raw_status(P._stats(small))[0] != "TAKING"
print("evidence ok")

# --- live break-even from the bot's own results
r = [row("BUY", {}, 30.0)] + [row("BUY", {}, -6.0) for _ in range(6)]
be = P._break_even(r)
assert abs(be["be"] - 16.7) < 0.1 and be["n"] == 7, be
print("break-even ok")

# --- decision
cellA = {"side": "BUY", "text": "Zone A", "kind": "SD level", "combo": False, "n": 60, "avg": 3.0, "wr": 70.0, "z": 5.0, "old": 3, "new": 3, "status": "TAKING", "why": ""}
cellA2 = dict(cellA, text="TSI up", kind="TSI vs signal")
cellB = dict(cellA, text="Zone B", avg=-3.0, status="AVOID")
cellW = dict(cellA, text="Zone D", avg=0.5, status="WATCHING", z=1.0)
bk = {"BUY|Zone A": cellA, "BUY|TSI up": cellA2, "BUY|Zone B": cellB, "BUY|Zone D": cellW}
lab = lambda **k: k
assert P.decide("BUY", lab(sd_zone="Zone A", tsi_4zone="TSI up"), bk)["call"] == "TAKE"
d = P.decide("BUY", lab(sd_zone="Zone A"), bk)
assert d["call"] == "WATCH" and "second one" in d["why"], d
assert P.decide("BUY", lab(sd_zone="Zone B", tsi_4zone="TSI up"), bk)["call"] == "SKIP"          # one proven loser beats two winners
d = P.decide("BUY", lab(sd_zone="Zone D"), bk)
assert d["call"] == "WATCH" and "Closest" in d["why"], d
assert P.decide("BUY", lab(sd_zone="never seen"), bk)["call"] == "WATCH"
assert P.decide("SELL", lab(sd_zone="Zone A", tsi_4zone="TSI up"), bk)["call"] == "WATCH"       # BUY and SELL are counted apart
comboA = dict(cellA, combo=True)
assert P.decide("BUY", lab(sd_zone="Zone A"), {"BUY|Zone A": comboA})["call"] == "TAKE"          # one taking COMBO is enough
print("decision ok")

# --- memory: TAKING -> STOPPED is remembered and logged
P._state["was"].clear(); P._state["log"].clear()
b1 = {"BUY|Zone A": dict(cellA)}
P._apply_memory(b1, 1000.0)
assert b1["BUY|Zone A"]["status"] == "TAKING" and any("Started taking" in x["text"] for x in P._state["log"])
b2 = {"BUY|Zone A": dict(cellA, status="WATCHING", avg=0.1, n=40)}
P._apply_memory(b2, 2000.0)
assert b2["BUY|Zone A"]["status"] == "STOPPED" and any("Stopped taking" in x["text"] for x in P._state["log"])
b3 = {"BUY|Zone A": dict(cellA)}
P._apply_memory(b3, 3000.0)
assert b3["BUY|Zone A"]["status"] == "TAKING"                                                 # it can come back
print("memory ok")

# --- scoreboard splits the coach trades by the AI's call
closed = [{"bot_id": 1, "pnl": 5.0, "bot_pnl": 4.0}, {"bot_id": 2, "pnl": -6.0, "bot_pnl": -6.0},
          {"bot_id": 3, "pnl": -1.0, "bot_pnl": -5.0}, {"bot_id": 4, "pnl": 2.0, "bot_pnl": None}, {"bot_id": 9, "pnl": 1.0, "bot_pnl": 1.0}]
decs = [{"bot_id": 1, "call": "TAKE"}, {"bot_id": 2, "call": "SKIP"}, {"bot_id": 3, "call": "WATCH"}, {"bot_id": 4, "call": "TAKE"}]
sb = P.scoreboard(closed, decs)
assert sb["all"]["n"] == 3 and sb["take"]["n"] == 1 and sb["stayed_out"]["n"] == 2, sb      # trade 4 (bot still open) and 9 (no decision) not counted
assert sb["saved"] == 11.0 and sb["take"]["ai_pnl"] == 5.0 and sb["pick_vs_all"] == 5.0 - (5.0 - 6.0 - 1.0), sb
print("scoreboard ok")

# --- tick: a new bot signal gets a decision; no labels for GRACE_S -> WATCH (no data)
P._state.update(dec=[], pending={}, log=[], since=time.time()); P._loaded = True
now = time.time()
bots = [{"id": 101, "symbol": "AAAUSDT", "action": "BUY", "timeframe": "3m", "opened_at_ts": now - 20},
        {"id": 102, "symbol": "BBBUSDT", "action": "SELL", "timeframe": "3m", "opened_at_ts": now - 20},
        {"id": 103, "symbol": "OLDUSDT", "action": "BUY", "timeframe": "3m", "opened_at_ts": now - 5000}]
D._bot_open = lambda: bots
D._labels_for = lambda sym, side, tf, ms: {"sd_zone": "Zone A", "tsi_4zone": "TSI up"} if sym == "AAAUSDT" else None
P._book = lambda tf, force=False: {"book": bk, "be": {}, "t": time.time(), "n": 10}
P._cfg = lambda name, default: default
P._tick()
calls = {d["bot_id"]: d["call"] for d in P._state["dec"]}
assert calls == {"101": "TAKE"}, calls                 # 102 waits for labels, 103 is too old and ignored
assert "102" in P._state["pending"] and "103" not in P._state["pending"]
P._state["pending"]["102"]["first"] = time.time() - P.GRACE_S - 5
P._tick()
d102 = [d for d in P._state["dec"] if d["bot_id"] == "102"][0]
assert d102["call"] == "WATCH" and d102["no_data"] is True, d102
n0 = len(P._state["dec"]); P._tick(); assert len(P._state["dec"]) == n0              # never decided twice
print("tick ok")
print("ALL PASS")
