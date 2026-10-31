"""v2_bt_health.py - Part 90a: BRAIN HEALTH (backend, read-only). One answer for the Brain Health screen (mock screen 1): is the Brain's learning pipeline healthy, and what is still missing?
Parts of the answer (nothing new is measured here, every number comes from a file that already exists):
  pipeline    SIGNAL > PAPER TRADE > OUTCOME > HOLDOUT TEST > GRADUATION GATE   each step done / not yet (a step is 'done' only with evidence)
  coverage    closed PAPER trades per market state (TREND / SIDEWAYS / CONSOLIDATION / BREAKOUT) on ONE timeframe, each against the 30-trade rule
  safety      the chips of v2_bt_guard.status (kill switch, daily loss cap, max open ...) + the auto-runner (last 5-minute tick from v2_bt_auto_status.json)
  graduation  PAPER / SHADOW / LIVE. LIVE is ALWAYS OFF here: it needs the owner's own OK, no check in this file can switch it on
  missing     plain lines: what to collect next (states under 30 trades, shadow with no trades, auto-runner silent)
  headline    one honest sentence. Never 'master trader'; all checks green still says: live stays locked until the owner says OK
Holdout = the playbook rows with a USE / AVOID verdict: CONFIRMS (newest trades agree), AGAINST (they disagree), NOT ENOUGH YET (under 10 newest trades). The step 'HOLDOUT TEST' is done only when something CONFIRMS and nothing is AGAINST.
Reads v2_brain_trader.db read-only and the auto-runner status file. No network, no write, no trading import. Starting limits (30 trades, 15 minutes) are NV, not validated.
Run (Termux, optional):  python3 backend/v2_bt_health.py [--data DIR] [--source PAPER] [--interval 5m]  -> the plain lines."""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_auto as AU
import v2_bt_guard as G
import v2_bt_playbook as PB
import v2_bt_review as RV
import v2_bt_store as B

VERSION = "v2_bt_health 1 (Part 90a)"
NEED = RV.MIN_N                                       # 30 closed trades per state (same rule as the playbook)
TICK_OK_SEC = 15 * 60                                 # the auto-runner ticks every 5 minutes; 15 minutes of silence = not running (NV)
STEPS = (("signal", "SIGNAL", "Find opportunities"), ("paper", "PAPER TRADE", "Practice safely"), ("outcome", "OUTCOME", "Measure results"),
         ("holdout", "HOLDOUT TEST", "Prove consistency"), ("gate", "GRADUATION GATE", "Unlock live trading"))
LABELS = {"TREND": "Trending", "SIDEWAYS": "Sideways", "CONSOLIDATION": "Consolidation", "BREAKOUT": "Breakout"}
SAFE_TITLES = {"no_lookahead": "No look-ahead", "data_quality": "Data quality", "stale_data_pause": "Stale-data pause", "kill_switch": "Kill switch", "daily_loss_cap": "Daily loss cap",
               "max_open_trades": "Max open trades", "reconciliation": "Reconciliation", "decision_version": "Decision version"}


def holdout_summary(trades):
    """How many USE / AVOID rows are CONFIRMED / AGAINST / still waiting for 10 newest trades."""
    blocks, _ = PB.playbook(trades)
    out = {"confirms": 0, "against": 0, "waiting": 0}
    for b in blocks:
        for r in b["use"] + b["avoid"]:
            st = (r.get("holdout") or {}).get("status")
            out["confirms" if st == "CONFIRMS" else "against" if st == "AGAINST" else "waiting"] += 1
    return out


def coverage(trades, interval):
    xs = PB.pick(trades, interval)
    rows = []
    for g in PB.STATE_GROUPS:
        n = len(PB.pick(trades, interval, g))
        rows.append({"key": g, "label": LABELS[g], "n": n, "need": NEED, "enough": n >= NEED})
    return {"interval": interval, "total": len(xs), "states": rows, "rule": "A state needs %d closed paper trades before the Brain may call it good or bad." % NEED}


def runner(data_dir, now):
    st = AU.read_status(data_dir)
    ts = (st.get("last_tick") or {}).get("ts")
    if not ts:
        return {"state": "NOT_RUNNING", "note": "No tick saved yet. Restart the backend, the first tick comes in about 5 minutes.", "age_sec": None}
    age = int(now - ts)
    ok = age <= TICK_OK_SEC
    return {"state": "RUNNING" if ok else "STALE", "age_sec": age, "tick_errors": st.get("tick_errors", 0), "last_error": (st.get("last_error") or {}).get("name"),
            "note": "Last tick %d min ago." % (age // 60) if ok else "Last tick %d min ago: the auto-runner looks stopped." % (age // 60)}


def graduation(per, hold):
    paper, shadow = per["PAPER"]["closed"], per["SHADOW"]["closed"]
    no_hold = hold["confirms"] == 0 or hold["against"] > 0
    g = [{"key": "paper", "label": "PAPER", "state": "PASS" if paper >= NEED else "WAIT", "note": "Min samples met" if paper >= NEED else "%d of %d closed paper trades" % (paper, NEED)}]
    if shadow < NEED:
        g.append({"key": "shadow", "label": "SHADOW", "state": "PENDING", "note": "%d of %d closed shadow trades" % (shadow, NEED)})
    else:
        g.append({"key": "shadow", "label": "SHADOW", "state": "PENDING" if no_hold else "PASS", "note": "Needs holdout evidence" if no_hold else "Holdout confirms"})
    g.append({"key": "live", "label": "LIVE", "state": "OFF", "note": "Locked until all criteria pass, then only with your own OK"})
    return g


def headline(grad, hold):
    ok = grad[0]["state"] == "PASS" and grad[1]["state"] == "PASS"
    if ok:
        return {"verdict": "CHECKS PASS", "title": "Checks pass. Live stays locked until you say OK.", "text": "This is not a promise of profit. A tiny live test needs your own OK and a daily loss cap."}
    why = "needs more paper trades" if grad[0]["state"] != "PASS" else "needs holdout evidence"
    return {"verdict": "NOT READY", "title": "Not a master trader yet - %s." % why,
            "text": "The model has not passed holdout testing. Live trading is disabled to prevent false confidence. Add more data and complete the evaluation."}


def missing(cov, per, run):
    xs = ["%s on %s: %d of %d closed trades (needs %d more)" % (s["label"], cov["interval"], s["n"], NEED, NEED - s["n"]) for s in cov["states"] if not s["enough"]]
    if per["SHADOW"]["closed"] < NEED:
        xs.append("SHADOW: %d of %d closed trades" % (per["SHADOW"]["closed"], NEED))
    if run["state"] != "RUNNING":
        xs.insert(0, "Auto-runner: " + run["note"])
    return xs


def build(data_dir, source="PAPER", now=None, interval="5m"):
    if source not in B.SOURCES:
        raise ValueError("source must be REPLAY, PAPER or SHADOW")
    if interval not in PB.INTERVALS:
        raise ValueError("interval must be 5m or 15m")
    now = int(time.time() if now is None else now)
    con = B.open_ro(data_dir)
    if con is None:
        return {"ready": False, "framework": VERSION, "note": "No Brain Trader file yet: nothing has been saved. Run the Brain tick first.", "live": "LOCKED"}
    try:
        trades = RV.closed_trades(con, source)
    finally:
        con.close()
    per = B.status(data_dir)["per_source"]
    hold = holdout_summary(PB.pick(trades, interval))
    cov, run = coverage(trades, interval), runner(data_dir, now)
    grad = graduation(per, hold)
    done = {"signal": per[source]["decisions"] > 0, "paper": per[source]["opened"] > 0, "outcome": per[source]["closed"] > 0,
            "holdout": hold["confirms"] > 0 and hold["against"] == 0, "gate": all(x["state"] == "PASS" for x in grad[:2])}
    steps = [{"key": k, "title": t, "sub": s, "done": done[k]} for k, t, s in STEPS]
    safety = G.status(data_dir, now)
    miss = missing(cov, per, run)
    return {"ready": True, "framework": VERSION, "source": source, "live": "LOCKED", "pipeline": steps, "coverage": cov, "holdout": hold, "safety": safety, "runner": run,
            "graduation": grad, "headline": headline(grad, hold), "missing": miss[:8],
            "missing_summary": ("%d thing(s) to collect. First: %s" % (len(miss), miss[0])) if miss else "Nothing is missing right now.",
            "note": "Read-only. Every number comes from the saved Brain Trader files. Starting limits (30 trades, 15 minutes) are not validated. Nothing here trades."}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--source", default="PAPER")
    ap.add_argument("--interval", default="5m")
    a = ap.parse_args(argv)
    r = build(a.data, a.source, None, a.interval)
    if not r["ready"]:
        print(r["note"])
        return 0
    print(r["headline"]["title"])
    print("pipeline:", " > ".join("%s%s" % (s["title"], "" if s["done"] else " (not yet)") for s in r["pipeline"]))
    print("coverage:", ", ".join("%s %d/%d" % (s["label"], s["n"], NEED) for s in r["coverage"]["states"]))
    print("runner:", r["runner"]["state"], "-", r["runner"]["note"])
    for m in r["missing"]:
        print(" missing:", m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
