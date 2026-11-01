"""v2_bt_ready.py - Part N2: BRAIN READY? (backend, read-only). ONE plain answer: what does the Brain do by itself, and is it ready for more than paper trading?
Nothing new is measured: it reads the Brain Health answer (v2_bt_health), the Simple Results answer (v2_bt_verdict) and the auto-runner switches.
What the Brain does by itself (PAPER, pretend money): looks at every followed coin every 5 minutes, opens a paper trade when the rules say so and the safety guard agrees, and manages it (BT-03: trailing stop, early cut, hold / close) while the manager switch is ON.
Checks (each yes / no with one plain line): auto-runner running, 30+ closed trades, 7+ days of trading, verdict PROFIT, holdout confirms, 2+ market states with 30+ trades, data quality PASS, kill switch not tripped.
Answer word: NOT RUNNING (runner silent), CHECKS PASS (all yes: live STILL needs the owner's own OK), NOT YET (anything else, with the first missing line).
Starting limits (30 trades, 7 days, 2 states) are NV, not validated. LIVE is ALWAYS LOCKED here. Reads v2_brain_trader.db read-only and two switch files. No network, no write, no trading import.
Run (Termux, optional):  python3 backend/v2_bt_ready.py [--data DIR] [--source PAPER]  -> the plain lines."""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_auto as AU
import v2_bt_health as HE
import v2_bt_review as RV
import v2_bt_store as B
import v2_bt_verdict as VD

VERSION = "v2_bt_ready 1 (Part N2)"
DAY = 86400
NEED_TRADES, NEED_DAYS, NEED_STATES = 30, 7, 2


def _flag(data_dir, name):
    p = AU._p(data_dir, name)
    try:
        if os.path.islink(p) or not os.path.isfile(p):
            return False
        with open(p, "r", encoding="utf-8") as f:
            return f.read(10).strip().lower() in ("1", "on", "true", "yes")
    except OSError:
        return False


def _chip(h, key):
    for c in (h.get("safety") or {}).get("chips") or []:
        if c.get("key") == key:
            return c.get("state")
    return None


def _days(data_dir, source, now):
    con = B.open_ro(data_dir)
    if con is None:
        return 0
    try:
        ts = [t["ts"] for t in RV.closed_trades(con, source)]
    finally:
        con.close()
    return int((now - min(ts)) // DAY) + 1 if ts else 0


def _checks(h, v, days):
    n, run, hold = v["numbers"], h["runner"], h["holdout"]
    states = sum(1 for s in h["coverage"]["states"] if s["enough"])
    dq = _chip(h, "data_quality")
    return [
        ("runner", "Brain is running", run["state"] == "RUNNING", run["note"]),
        ("trades", "30+ closed paper trades", n["trades"] >= NEED_TRADES, "%d of %d closed trades" % (n["trades"], NEED_TRADES)),
        ("days", "7+ days of trading", days >= NEED_DAYS, "%d of %d days" % (days, NEED_DAYS)),
        ("profit", "Result is PROFIT", v["verdict"]["word"] == "PROFIT", "Verdict now: %s" % v["verdict"]["word"]),
        ("holdout", "Newest trades confirm the rules", hold["confirms"] > 0 and hold["against"] == 0, "%d confirm, %d against" % (hold["confirms"], hold["against"])),
        ("states", "2+ market states with 30+ trades", states >= NEED_STATES, "%d of 4 states have enough trades" % states),
        ("data", "Data quality is PASS", dq == "PASS", "Data quality: %s" % (dq or "NOT_CHECKED")),
        ("kill", "Kill switch is not tripped", _chip(h, "kill_switch") != "TRIPPED", "Kill switch: %s" % (_chip(h, "kill_switch") or "?")),
    ]


def build(data_dir, source="PAPER", now=None):
    if source not in ("PAPER", "SHADOW"):
        raise ValueError("source must be PAPER or SHADOW")
    now = int(time.time() if now is None else now)
    h = HE.build(data_dir, source, now, "5m")
    if not h.get("ready"):
        return {"ready": False, "framework": VERSION, "live": "LOCKED", "note": h.get("note") or "No Brain Trader file yet. Restart the backend; the first tick comes in about 5 minutes."}
    v = VD.build(data_dir, source, now)
    days = _days(data_dir, source, now)
    cs = _checks(h, v, days)
    ok = [c for c in cs if c[3] is not None and c[2]]
    first = next((c for c in cs if not c[2]), None)
    if not cs[0][2]:
        word, text = "NOT RUNNING", "The Brain is not ticking. Restart the backend and wait about 5 minutes."
    elif first is None:
        word, text = "CHECKS PASS", "All checks pass. This is not a promise of profit. Live stays locked until you say OK."
    else:
        word, text = "NOT YET", "%d of %d checks pass. First thing missing: %s (%s)." % (len(ok), len(cs), first[1], first[3])
    per = B.status(data_dir)["per_source"][source]
    n = v["numbers"]
    return {"ready": True, "framework": VERSION, "source": source, "live": "LOCKED", "verdict": {"word": word, "text": text},
            "brain": {"auto": AU.is_enabled(data_dir), "manager": _flag(data_dir, AU.MGR_FLAG), "open": max(0, per["opened"] - per["closed"]), "decisions": per["decisions"],
                      "trades": n["trades"], "wins": n["wins"], "losses": n["losses"], "net_usdt": n["net_usdt"], "days": days},
            "checks": [{"key": k, "label": lab, "ok": good, "note": note} for k, lab, good, note in cs], "passed": len(ok), "total": len(cs),
            "note": "Read-only. Pretend money only. Starting limits (30 trades, 7 days, 2 states) are not validated. Live trading needs your own OK and is locked."}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--source", default="PAPER", choices=("PAPER", "SHADOW"))
    a = ap.parse_args(argv)
    r = build(a.data, a.source)
    if not r["ready"]:
        print(r["note"])
        return 0
    print("%s: %s" % (r["verdict"]["word"], r["verdict"]["text"]))
    b = r["brain"]
    print("auto %s, manager %s, open %d, trades %d (%d win / %d loss), net %+.2f USDT, %d days" % ("ON" if b["auto"] else "OFF", "ON" if b["manager"] else "OFF", b["open"], b["trades"], b["wins"], b["losses"], b["net_usdt"], b["days"]))
    for c in r["checks"]:
        print(" [%s] %s - %s" % ("x" if c["ok"] else " ", c["label"], c["note"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
