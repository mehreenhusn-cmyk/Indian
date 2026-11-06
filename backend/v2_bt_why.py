"""v2_bt_why.py - WHY IS THE BRAIN NOT TRADING TODAY? Read only: it only reads the Brain Trader file (bt_decision, bt_trade_open, bt_trade_close) through B.open_ro. No write, no network, no order.
Owner question (6 Nov 2026): "why is the Brain not trading?" The Brain already stores one row per decision (OPEN_LONG / OPEN_SHORT / WAIT / SKIP / NO_OPINION) with its own reason text.
This groups today's rows (UTC day, same day as the Brain pages) by decision and reason and says in plain words how many were taken and what the most common reason for not taking was.
Nothing is invented: reasons are shown exactly as the Brain stored them; no rows = it says so and what to check. API: build(data_dir, source='PAPER', now=None) -> dict. Never raises."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_store as B

VERSION = "v2_bt_why 1 (E6)"
DAY = 86400
TAKEN = ("OPEN_LONG", "OPEN_SHORT")
STALE_SEC = 1200       # no decision for 20 minutes = say so


def _ago(sec):
    sec = max(0, int(sec))
    return "%d min" % (sec // 60) if sec < 3600 else "%d h %d min" % (sec // 3600, (sec % 3600) // 60)


def build(data_dir, source="PAPER", now=None):
    now = int(time.time() if now is None else now)
    a = now - now % DAY
    out = {"version": VERSION, "paper_only": True, "state": "OK", "source": source, "taken": 0, "waited": 0, "skipped": 0, "no_opinion": 0, "total": 0,
           "open_now": 0, "last_decision_sec": None, "reasons": [], "last": [], "lines": []}
    L = out["lines"]
    try:
        if source not in B.SOURCES:
            raise ValueError("source must be REPLAY, PAPER or SHADOW")
        con = B.open_ro(data_dir)
        if con is None:
            out["state"] = "no_file"
            L.append("The Brain has no data file yet, so it has not decided anything. Check that the Brain is switched on and the backend is running.")
            return out
        try:
            cnt = dict(con.execute("SELECT decision, COUNT(*) FROM bt_decision WHERE source=? AND close_ts>=? AND close_ts<? GROUP BY decision", (source, a, a + DAY)).fetchall())
            out["taken"] = sum(cnt.get(k, 0) for k in TAKEN)
            out["waited"], out["skipped"], out["no_opinion"] = cnt.get("WAIT", 0), cnt.get("SKIP", 0), cnt.get("NO_OPINION", 0)
            out["total"] = sum(cnt.values())
            out["open_now"] = con.execute("SELECT COUNT(*) FROM bt_trade_open o LEFT JOIN bt_trade_close c ON c.trade_id=o.trade_id WHERE o.source=? AND c.trade_id IS NULL", (source,)).fetchone()[0]
            last = con.execute("SELECT MAX(close_ts) FROM bt_decision WHERE source=?", (source,)).fetchone()[0]
            if last is not None:
                out["last_decision_sec"] = max(0, now - int(last))
            rs = con.execute("SELECT decision, COALESCE(reason, ''), COUNT(*) AS n FROM bt_decision WHERE source=? AND close_ts>=? AND close_ts<? AND decision NOT IN ('OPEN_LONG','OPEN_SHORT') "
                             "GROUP BY decision, reason ORDER BY n DESC LIMIT 6", (source, a, a + DAY)).fetchall()
            out["reasons"] = [{"decision": r[0], "reason": (r[1] or "no reason stored")[:160], "n": r[2]} for r in rs]
            ls = con.execute("SELECT close_ts, symbol, side, decision, COALESCE(reason, '') FROM bt_decision WHERE source=? AND decision NOT IN ('OPEN_LONG','OPEN_SHORT') "
                             "ORDER BY close_ts DESC LIMIT 5", (source,)).fetchall()
            out["last"] = [{"ts": r[0], "symbol": r[1], "side": r[2], "decision": r[3], "reason": (r[4] or "no reason stored")[:160]} for r in ls]
        finally:
            con.close()
    except Exception as e:
        out["state"] = "error"
        L.append("Could not read the Brain decisions: %s" % str(e)[:120])
        return out
    if out["total"] == 0:
        if out["last_decision_sec"] is None:
            L.append("The Brain has never stored a decision. It is probably not running. Check Brain tick in System health.")
        else:
            L.append("No decision today yet. The last one was %s ago. If this stays like that, check Brain tick in System health." % _ago(out["last_decision_sec"]))
        return out
    L.append("Today the Brain judged %d signals: %d taken, %d waited, %d skipped, %d had no opinion. %d trades are open now." % (out["total"], out["taken"], out["waited"], out["skipped"], out["no_opinion"], out["open_now"]))
    if out["reasons"]:
        r0 = out["reasons"][0]
        L.append("Most common reason for not taking a trade: %s (%d times)." % (r0["reason"], r0["n"]))
    if out["last_decision_sec"] is not None and out["last_decision_sec"] > STALE_SEC:
        L.append("The last decision was %s ago. That is long: check Brain tick in System health." % _ago(out["last_decision_sec"]))
    return out
