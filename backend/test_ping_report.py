#!/usr/bin/env python3
"""Ping report tests: text content, honest verdicts, empty data, save fallback, API routes."""
import os, sys, tempfile, time

os.environ["OWL_DATA_DIR"] = tempfile.mkdtemp(prefix="ping_report_test_")
os.environ["OWL_DOWNLOAD_DIR"] = tempfile.mkdtemp(prefix="ping_dl_test_")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recovered_bot import ping_store as st
from recovered_bot import ping_report as pr

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f" FAIL {name}")


def trade(i, variant="A", side="LONG", pnl=-1.0, reason="sl"):
    now = time.time()
    return {"id": i, "symbol": f"C{i % 7}USDT", "variant": variant, "side": side, "pnl_pct": pnl,
            "pnl_usdt": pnl * 10, "exit_reason": reason, "opened_ts": now - 900, "exit_ts": now - 300}


# 1. no files at all -> still a report, says no data
t = pr.build_text()
check("empty: report builds", "OWL PING LAB REPORT" in t)
check("empty: says no snapshot", "No snapshot file found" in t)
check("empty: not enough data verdict", "NOT ENOUGH DATA" in t)
check("empty: has what/why/how", all(x in t for x in ("WHAT WAS BUILT", "WHERE THE IDEA CAME FROM", "WHY IT WAS BUILT", "HOW IT WORKS")))
check("rules read from code", "Colour: yellow at 3 pings, red at 5" in t)

# 2. few trades -> never claims profit
st.write_trades({"closed": [trade(1, pnl=2.0, reason="tp4"), trade(2, "B", "SHORT", -1.2)]})
st.write_state({"ts": time.time(), "health": {"build_tag": "x", "ws_state": "LIVE", "candidate_count": 40},
                "rows": [{"symbol": "AAA", "side": "BUY", "color": "red"}], "watchlist": ["AAA"],
                "bot": {"open": [], "skips_recent": [{"reason": "chased"}]},
                "score": {"signals_total": 14, "take_count": 0, "skip_count": 14, "loss_avoided": 259.9,
                          "profit_missed": 0.0, "net_effect": 259.9, "sentence": "Small sample, not reliable.",
                          "rows": [{"verdict": "SKIP", "reason": "no ping"}]},
                "lead": {"today_count": 35, "with_ping_pct": 2.9, "avg_lead_min": 54.4, "sentence": "x"}})
t = pr.build_text()
check("few trades: NOT ENOUGH DATA", "NOT ENOUGH DATA: only 2 closed" in t)
check("few trades: no profit claim", "POSITIVE after est. fees" not in t)
check("score numbers shown", "Loss avoided by skipping: 259.90" in t and "SKIP (no same-side ping): 14" in t)
check("score small sample warning", "need 30+" in t)
check("lead numbers shown", "35" in t and "54.4" in t)
check("health fresh", "fresh" in t and "1 BUY" in t)
check("skip reasons shown", "chased 1" in t and "no ping 1" in t)

# 3. many losing trades -> says NOT profitable
st.write_trades({"closed": [trade(i, ["A", "B", "C"][i % 3], pnl=-0.5) for i in range(40)]})
t = pr.build_text()
check("many losing: NOT profitable", "NOT profitable after est. fees" in t)
check("fee assumption stated", "0.08%" in t)

# 4. many winning trades -> positive, but still paper warning
st.write_trades({"closed": [trade(i, ["A", "B", "C"][i % 3], pnl=1.0, reason="tp4") for i in range(40)]})
t = pr.build_text()
check("many winning: POSITIVE", "POSITIVE after est. fees" in t and "Still paper only" in t)

# 5. stale snapshot is called stale
st.write_state({"ts": time.time() - 600, "health": {}})
check("stale snapshot flagged", "STALE" in pr.build_text())

# 6. corrupt trade rows do not crash
st.write_trades({"closed": [None, "x", {"pnl_pct": "bad"}, trade(1)]})
check("bad rows do not crash", "PING BOT RESULTS" in pr.build_text())

# 7. save into download dir
r = pr.save_to_downloads()
check("save ok", r["ok"] is True and os.path.isfile(r["path"]) and "owl_ping_report_" in r["path"])
os.environ["OWL_DOWNLOAD_DIR"] = "/nonexistent_dir_for_test"
pr_dirs = pr._download_dirs()
check("download dir list has env first", pr_dirs[0] == "/nonexistent_dir_for_test")

# 8. API routes
try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from recovered_bot.ping_api import make_router
    app = FastAPI()
    app.include_router(make_router())
    c = TestClient(app)
    os.environ["OWL_DOWNLOAD_DIR"] = tempfile.mkdtemp(prefix="ping_dl_test2_")
    a = c.get("/api/ping/report")
    check("route /report 200 text", a.status_code == 200 and "OWL PING LAB REPORT" in a.text and a.headers["content-type"].startswith("text/plain"))
    b = c.get("/api/ping/report_save")
    check("route /report_save ok", b.status_code == 200 and b.json().get("ok") is True)
except ImportError as e:
    print(f"  SKIP api route tests ({e})")

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
