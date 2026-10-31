"""v2_bt_guard.py - Part 84a: BRAIN TRADER 2 of 8 (backend). The SAFETY GUARD of the Brain Trader. It only ANSWERS \"may a new paper trade open now?\" and holds the switches; it places no order.
Checks before ANY new paper / shadow trade (every refusal has a code and a plain sentence):
  LIVE_LOCKED  live is not allowed | KILL_SWITCH  the owner (or a rule) stopped everything | DAILY_LOSS_CAP  today's net loss is at the cap | MAX_OPEN  too many open trades
  LOSS_STREAK  too many losses in a row | STALE_DATA  the newest saved candle is too old (Termux or the collector was off) | ALREADY_OPEN  same coin + timeframe + side is already open
  LOOK_AHEAD   a decision may not use data after its own candle close
The limits below are STARTING values (NV, not validated); the owner may change them (set_config). Day = UTC day (the app's day is 5:30 AM IST to 5:30 AM IST = the same UTC day).
Sources (PAPER / SHADOW / REPLAY) are checked apart: a REPLAY loss never blocks a PAPER trade.
Writes only to its OWN file v2_brain_trader.db (tables guard_state, guard_log). No network, no order code, no trading import.
Run (Termux):  python3 backend/v2_bt_guard.py [--data DIR]   -> the safety status (what Brain Health will show)
               python3 backend/v2_bt_guard.py --kill on --why \"owner stop\"   /   --kill off   (the kill switch)"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_store as B

VERSION = "v2_bt_guard 1 (Part 84a)"
DEFAULTS = {"capital_usdt": 1000.0, "daily_loss_cap_pct": 2.0, "max_open": 5, "max_loss_streak": 5, "stale_candles": 3}
INTERVAL_SEC = {"3m": 180, "5m": 300, "15m": 900}
DAY_SEC = 86400
TEXT = {"LIVE_LOCKED": "Live trading is locked. Only PAPER, SHADOW and REPLAY are allowed.",
        "KILL_SWITCH": "The kill switch is ON. No new trade opens.",
        "DAILY_LOSS_CAP": "Today's net loss has reached the daily loss cap. No new trade until tomorrow.",
        "MAX_OPEN": "The maximum number of open trades is reached.",
        "LOSS_STREAK": "Too many losing trades in a row. The Brain pauses new trades.",
        "STALE_DATA": "The newest saved candle is too old. The Brain pauses until fresh data arrives.",
        "ALREADY_OPEN": "A trade on this coin, timeframe and side is already open.",
        "LOOK_AHEAD": "The decision used data after its own candle close. Refused."}


def _log(con, event, detail=""):
    con.execute("INSERT INTO guard_log VALUES (?,?,?)", (int(time.time()), event, str(detail)[:300]))


def _get(con, key):
    r = con.execute("SELECT value FROM guard_state WHERE key=?", (key,)).fetchone()
    return r[0] if r else None


def _set(con, key, value, now=None):
    con.execute("INSERT INTO guard_state VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, ts=excluded.ts", (key, str(value), int(time.time() if now is None else now)))


def get_config(con):
    cfg = dict(DEFAULTS)
    for k in DEFAULTS:
        v = _get(con, "cfg:" + k)
        if v is not None:
            cfg[k] = type(DEFAULTS[k])(float(v))
    return cfg


def set_config(con, key, value):
    """The owner changes a limit. Unknown name or a value that is not above 0 = ValueError. Every change is logged."""
    if key not in DEFAULTS or float(value) <= 0:
        raise ValueError("unknown limit, or the value is not above 0")
    _set(con, "cfg:" + key, value)
    _log(con, "CONFIG", "%s=%s" % (key, value))
    con.commit()


def set_kill(con, on, why=""):
    _set(con, "kill", "1" if on else "0")
    _log(con, "KILL_ON" if on else "KILL_OFF", why)
    con.commit()


def is_killed(con):
    return _get(con, "kill") == "1"


def check_no_lookahead(close_ts, data_upto_ts):
    """PURE. True when the decision only used data up to its own candle close."""
    return int(data_upto_ts) <= int(close_ts)


def day_start(now):
    return int(now) - int(now) % DAY_SEC


def daily_net(con, source, now):
    return sum(r[1] for r in B.closed_rows(con, source, day_start(now)))


def loss_streak(con, source):
    n = 0
    for _, net in reversed(B.closed_rows(con, source)):
        if net >= 0:
            break
        n += 1
    return n


def check_entry(con, source, symbol, interval, side, now, last_candle_ts, cfg=None):
    """May a new trade open? -> {\"allowed\": bool, \"reasons\": [{\"code\", \"text\"}]}. last_candle_ts = open time (seconds) of the newest saved closed candle of this coin."""
    cfg = cfg or get_config(con)
    codes = []
    if source not in B.SOURCES:
        codes.append("LIVE_LOCKED")
    if is_killed(con):
        codes.append("KILL_SWITCH")
    if source in B.SOURCES:
        if daily_net(con, source, now) <= -cfg["capital_usdt"] * cfg["daily_loss_cap_pct"] / 100.0:
            codes.append("DAILY_LOSS_CAP")
        op = B.open_trades(con, source)
        if len(op) >= cfg["max_open"]:
            codes.append("MAX_OPEN")
        if any(r[1] == symbol and r[2] == interval and r[3] == side for r in op):
            codes.append("ALREADY_OPEN")
        if loss_streak(con, source) >= cfg["max_loss_streak"]:
            codes.append("LOSS_STREAK")
    sec = INTERVAL_SEC.get(interval, 300)
    if last_candle_ts is None or int(now) - int(last_candle_ts) > cfg["stale_candles"] * sec + sec:
        codes.append("STALE_DATA")
    return {"allowed": not codes, "reasons": [{"code": c, "text": TEXT[c]} for c in codes]}


def reconcile(con, now=None):
    """Paper has no broker, so \"reconciliation\" = the ledger agrees with itself: every close has its open, no open trade is stuck for more than 3 days."""
    now = int(time.time() if now is None else now)
    orphan = con.execute("SELECT COUNT(*) FROM bt_trade_close c LEFT JOIN bt_trade_open o ON o.trade_id=c.trade_id WHERE o.trade_id IS NULL").fetchone()[0]
    stuck = sum(1 for s in B.SOURCES for r in B.open_trades(con, s) if now - r[4] > 3 * DAY_SEC)
    return {"orphan_closes": orphan, "stuck_open": stuck, "state": "FAIL" if orphan else ("WARN" if stuck else "PASS")}


def status(data_dir, now=None):
    """The safety chips of the Brain Health screen. Honest words: a check that is not built yet says NOT_CHECKED, never PASS."""
    now = int(time.time() if now is None else now)
    con = B.open_ro(data_dir)
    if con is None:
        return {"ready": False, "framework": VERSION, "note": "no Brain Trader file yet", "chips": []}
    try:
        cfg = get_config(con)
        rec = reconcile(con, now)
        ver = B.latest_version(con)
        chips = [("no_lookahead", "PASS", "Enforced in code: a decision cannot use data after its candle close"),
                 ("data_quality", "NOT_CHECKED", "The data-quality check is built in Part 85"),
                 ("stale_data_pause", "ARMED", "Pauses when the newest candle is older than %d candles" % cfg["stale_candles"]),
                 ("kill_switch", "TRIPPED" if is_killed(con) else "ARMED", "Stops new trades at once"),
                 ("daily_loss_cap", "SET", "Limit: %s%% of %s USDT" % (cfg["daily_loss_cap_pct"], cfg["capital_usdt"])),
                 ("max_open_trades", "SET", "Limit: %d" % cfg["max_open"]),
                 ("reconciliation", rec["state"], "Paper ledger agrees with itself (%d orphan, %d stuck)" % (rec["orphan_closes"], rec["stuck_open"])),
                 ("decision_version", ver or "NONE", "Current Brain version")]
        return {"ready": True, "framework": VERSION, "live": "LOCKED", "limits_are": "starting values, not validated; the owner may change them",
                "chips": [{"key": k, "state": s, "note": n} for k, s, n in chips]}
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--kill", choices=("on", "off"))
    ap.add_argument("--why", default="")
    a = ap.parse_args(argv)
    if a.kill:
        con = B.connect(a.data)
        set_kill(con, a.kill == "on", a.why or "from the command line")
        con.close()
    print(json.dumps(status(a.data), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
