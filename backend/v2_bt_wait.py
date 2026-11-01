"""v2_bt_wait.py - Part 85b: BRAIN TRADER 7 of 8 (backend). Two jobs: (1) answer the WAIT ideas, (2) one tick that runs the whole Brain over the coins the collector follows.
WAIT RESULT: a WAIT decision says "not now, I wait for X, at most N candles". Later, with the candles that came after it, this file checks (using the SAME rules as the decision, nothing new): did the condition come inside N candles?
  CAME     = at a later candle (1..N) the rules said OPEN (same side as the lean for BREAKOUT / TREND waits, either side for a squeeze wait). The idea was NOT traded at that moment by this file; the scan / replay trades it when it sees that candle.
  DROPPED  = N candles passed and it did not come: the idea is dead. PENDING = the N candles are not over yet (no row is written). A run that ends in a hole is never judged (stays PENDING, never DROPPED by guess).
Results go to the append-only table bt_wait_result; a WAIT is answered once. This is an after-the-fact check, it never feeds a decision at the candle where the WAIT was made (no look-ahead into a decision).
TICK (the job the later route / scheduler runs): manage open trades -> scan every followed coin (PAPER or SHADOW, the guard asked first; a coin without data is saved as NO_OPINION with the REASON from v2_bt_why) -> answer finished WAITs.
Only the coins of the collector's list (v2_candles.pick_symbols, max 40) and the intervals 5m / 3m given. Reads the market store read-only, writes only v2_brain_trader.db. No network, no order code, no trading import.
Run (Termux, optional):  python3 backend/v2_bt_wait.py waits [--source REPLAY]   -> answer the WAITs of that source and print counts   |   python3 backend/v2_bt_wait.py tick [--source PAPER] [--interval 5m]"""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_rules as R
import v2_bt_sim as M
import v2_bt_state as ST
import v2_bt_store as B
import v2_candles as K
import v2_defs as D
import v2_replay as V
import v2_store as S

VERSION = "v2_bt_wait 1 (Part 85b)"


def _is_open(d, side, kind):
    return d["decision"] in ("OPEN_LONG", "OPEN_SHORT") and (kind == "ANY_SIDE" or d["side"] == side)


def resolve_waits(con, data_dir, source="REPLAY", now=None):
    """Answers every WAIT of ONE source that can be answered now. -> counts {CAME, DROPPED, PENDING, UNAVAILABLE}. Safe to run again (an answered WAIT is never answered twice)."""
    now, out = int(time.time() if now is None else now), {"CAME": 0, "DROPPED": 0, "PENDING": 0, "UNAVAILABLE": 0}
    rows = con.execute("SELECT d.version, d.symbol, d.interval, d.close_ts, d.side, d.snapshot FROM bt_decision d LEFT JOIN bt_wait_result w ON w.version=d.version AND w.source=d.source "
                       "AND w.symbol=d.symbol AND w.interval=d.interval AND w.close_ts=d.close_ts AND w.side=d.side WHERE d.source=? AND d.decision='WAIT' AND w.close_ts IS NULL "
                       "ORDER BY d.symbol, d.interval, d.close_ts", (source,)).fetchall()
    cache = {}
    for ver, sym, iv, close_ts, side, snap in rows:
        step = D.STEP[iv]
        if (sym, iv) not in cache:
            run = M.load_run(data_dir, sym, iv)
            cache[(sym, iv)] = (run, ST.prepare(run) if len(run) >= 2 else None, {})
        run, ctx, seen = cache[(sym, iv)]
        idx = next((k for k in range(len(run) - 1, -1, -1) if run[k][0] + step == close_ts), None)
        if idx is None or ctx is None:
            out["UNAVAILABLE"] += 1
            continue
        info = json.loads(snap or "{}")
        n, kind = int(info.get("max_wait_candles") or R.WAIT_PULL), info.get("wait_kind") or "SAME_SIDE"
        came, last = None, min(idx + n, len(run) - 1)
        for j in range(idx + 1, last + 1):
            if j not in seen:
                seen[j] = R.decide(ctx, ST.tags(ctx, j), j)
            if _is_open(seen[j], side, kind):
                came = j
                break
        if came is None and idx + n >= len(run):               # the window is not over (or ends in a hole): no answer yet
            out["PENDING"] += 1
            continue
        res = "CAME" if came is not None else "DROPPED"
        con.execute("INSERT OR IGNORE INTO bt_wait_result VALUES (?,?,?,?,?,?,?,?,?,?)", (ver, source, sym, iv, close_ts, side, res, None if came is None else run[came][0] + step,
                                                                                         (came - idx) if came is not None else n, now))
        out[res] += 1
    con.commit()
    return out


def wait_summary(con, source):
    """Counts only (no rate): per market state how many WAITs came, were dropped, or are still open."""
    per = {}
    for st, res, c in con.execute("SELECT d.state, COALESCE(w.result,'PENDING'), COUNT(*) FROM bt_decision d LEFT JOIN bt_wait_result w ON w.version=d.version AND w.source=d.source AND w.symbol=d.symbol "
                                  "AND w.interval=d.interval AND w.close_ts=d.close_ts AND w.side=d.side WHERE d.source=? AND d.decision='WAIT' GROUP BY d.state, COALESCE(w.result,'PENDING')", (source,)):
        per.setdefault(st or "?", {"CAME": 0, "DROPPED": 0, "PENDING": 0})[res] += c
    return {"source": source, "by_state": per, "note": "counts only; under %d answered waits nothing can be said about a state" % V.MIN_N}


def followed(data_dir, now):
    """The coins the collector follows right now (its own list), [] when the market store is not there."""
    path = S.store_path(data_dir)
    if not os.path.isfile(path):
        return []
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    try:
        return K.pick_symbols(con, now)
    finally:
        con.close()


def tick(con, data_dir, now=None, source="PAPER", interval="5m", version=None):
    """ONE round of the Brain: close finished trades, look at every followed coin, answer finished waits. -> a short summary; per coin the decision or the REASON why it had no data."""
    now = int(time.time() if now is None else now)
    out = {"time": now, "source": source, "interval": interval, "managed": M.manage_open(con, data_dir, now, source), "coins": [], "no_data": []}
    for sym in followed(data_dir, now):
        try:
            r = M.paper_scan(con, data_dir, sym, interval, now, source, version)
        except (sqlite3.Error, ValueError, KeyError) as e:        # one coin never stops the round
            out["no_data"].append({"symbol": sym, "code": "ERROR", "text": "Is coin par Brain mein error aaya (%s)." % type(e).__name__})
            continue
        if r["status"] == "DATA_NOT_READY":
            out["no_data"].append({"symbol": sym, "code": r["why"]["code"], "text": r["why"]["text"]})
        else:
            out["coins"].append({"symbol": sym, "decision": r["decision"], "state": r["state"], "trade_opened": r["trade_opened"]})
    out["waits"] = resolve_waits(con, data_dir, source, now) if version in (None, "BT-03") else {}   # WAIT answers belong to BT-01 and to the BT-03 manager (same entry rule)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("job", choices=("waits", "tick"))
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--source", default="PAPER", choices=("REPLAY", "PAPER", "SHADOW"))
    ap.add_argument("--interval", default="5m", choices=("3m", "5m"))
    a = ap.parse_args(argv)
    con = B.connect(a.data)
    try:
        if a.job == "waits":
            res = {"answered_now": resolve_waits(con, a.data, a.source), "summary": wait_summary(con, a.source)}
        else:
            if a.source == "REPLAY":
                print("tick works on PAPER or SHADOW only")
                return 1
            res = tick(con, a.data, source=a.source, interval=a.interval)
    finally:
        con.close()
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
