"""v2_bt_report.py - Part 85b: BRAIN TRADER 8 of 8 (backend, read-only). The DAILY REPORT of the Brain Trader in plain words: what it looked at, what it did, what it skipped and why, how the trades ended net of fee, which waits came, where data was missing and WHY.
One source at a time (PAPER by default; REPLAY and SHADOW are never added to it). The day is the UTC day = the app's day (5:30 AM IST to 5:30 AM IST), never India market time.
build() gives numbers AND a ready list of plain sentences ("lines", Roman Hinglish) that a screen can show as they are (no JSON look). Durations over 60 minutes are shown as hours + minutes.
Honest: no win rate, no forecast. A group of trades with under 30 closed trades says "too few to say anything"; "what the Brain learned" only names a group with 30+ closed trades (all days of that source, net of fee); otherwise it says how many more are needed.
Reads v2_brain_trader.db read-only (a read never creates it). No network, no write, no order code, no trading import. The route /api/v2/brain_report (api/v2_data.py) calls build().
Run (Termux, optional):  python3 backend/v2_bt_report.py [--source PAPER] [--day YYYY-MM-DD]  -> the report as JSON + the plain lines."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_guard as G
import v2_bt_sim as M
import v2_bt_store as B
import v2_bt_wait as WT
import v2_bt_why as W
import v2_replay as V

VERSION = "v2_bt_report 1 (Part 85b)"
DAY = 86400


def _window(day, now):
    if day:
        t = time.strptime(day, "%Y-%m-%d")                      # bad text = ValueError (the route answers 400)
        start = int(time.mktime(t[:3] + (0, 0, 0, 0, 0, 0)) - time.timezone)
    else:
        start = now - now % DAY
    return start, start + DAY


def _rows(con, sql, args=()):
    return con.execute(sql, args).fetchall()


def build(data_dir, source="PAPER", day=None, now=None):
    now = int(time.time() if now is None else now)
    if source not in B.SOURCES:
        raise ValueError("source must be REPLAY, PAPER or SHADOW")
    con = B.open_ro(data_dir)
    if con is None:
        return {"ready": False, "live": "LOCKED", "lines": ["Brain Trader ne abhi tak kuch save nahi kiya. Pehle tick ya replay chalao."], "note": "no Brain Trader file yet"}
    try:
        a, b = _window(day, now)
        dec = {k: n for k, n in _rows(con, "SELECT decision, COUNT(*) FROM bt_decision WHERE source=? AND close_ts>=? AND close_ts<? GROUP BY decision", (source, a, b))}
        skips = _rows(con, "SELECT reason, COUNT(*) c FROM bt_decision WHERE source=? AND close_ts>=? AND close_ts<? AND decision='SKIP' GROUP BY reason ORDER BY c DESC LIMIT 3", (source, a, b))
        opened = _rows(con, "SELECT COUNT(*) FROM bt_trade_open WHERE source=? AND open_ts>=? AND open_ts<?", (source, a, b))[0][0]
        cl = _rows(con, "SELECT o.symbol, o.side, c.exit_reason, c.net_usdt, (c.fee_pct+c.slip_pct)/100.0*o.size_usdt, c.hold_candles, o.interval FROM bt_trade_close c JOIN bt_trade_open o ON o.trade_id=c.trade_id "
                         "WHERE o.source=? AND c.close_ts>=? AND c.close_ts<? ORDER BY c.close_ts", (source, a, b))
        net, cost = sum(r[3] for r in cl), sum(r[4] for r in cl)
        op = [{"symbol": s, "interval": iv, "side": side, "opened": W.ist(ts), "age": W.dur(now - ts)} for _t, s, iv, side, ts in B.open_trades(con, source)]
        waits = {"CAME": 0, "DROPPED": 0, "PENDING": 0}
        for res, c in _rows(con, "SELECT COALESCE(w.result,'PENDING'), COUNT(*) FROM bt_decision d LEFT JOIN bt_wait_result w ON w.version=d.version AND w.source=d.source AND w.symbol=d.symbol AND w.interval=d.interval "
                                 "AND w.close_ts=d.close_ts AND w.side=d.side WHERE d.source=? AND d.decision='WAIT' AND d.close_ts>=? AND d.close_ts<? GROUP BY COALESCE(w.result,'PENDING')", (source, a, b)):
            waits[res] = c
        nodata = {}
        for sym, snap, ts in _rows(con, "SELECT symbol, snapshot, close_ts FROM bt_decision WHERE source=? AND state='DATA_NOT_READY' AND close_ts>=? AND close_ts<? ORDER BY close_ts", (source, a, b)):
            w = (json.loads(snap or "{}").get("why") or {})
            nodata[sym] = {"symbol": sym, "code": w.get("code", "?"), "text": w.get("text", "")}   # the newest answer per coin wins
        life = M.labels(con, source)
        guard = G.status(data_dir, now)
    finally:
        con.close()
    lines = ["Din: %s se %s tak. Source: %s (nakli paisa, koi asli order nahi)." % (W.ist(a), W.ist(b), source)]
    lines.append("Brain ne dekha: %d idea khule, %d WAIT, %d SKIP, %d bina raay (data kam)." % (dec.get("OPEN_LONG", 0) + dec.get("OPEN_SHORT", 0), dec.get("WAIT", 0), dec.get("SKIP", 0), dec.get("NO_OPINION", 0)))
    for text, c in skips:
        lines.append("Sabse zyada SKIP wajah (%d baar): %s" % (c, text))
    lines.append("Trades: %d khule, %d band. Net %+.2f USDT fee + slippage ke baad (costs %.2f USDT). %d plus mein, %d minus mein." % (opened, len(cl), net, cost, sum(1 for r in cl if r[3] > 0), sum(1 for r in cl if r[3] <= 0)))
    lines.append("WAIT ke jawab: %d aaya, %d drop hua, %d abhi baaki." % (waits["CAME"], waits["DROPPED"], waits["PENDING"]))
    lines.append("Abhi khule positions: %d." % len(op) if op else "Abhi koi position khuli nahi.")
    for v in nodata.values():
        lines.append("Data nahi (%s): %s" % (v["symbol"], v["text"]))
    learned = [g for g in life["closed_by_state_side"] if g["n"] >= V.MIN_N]
    if learned:
        for g in learned:
            lines.append("Seekha: %s %s mein %d trades, net %+.2f USDT (fee ke baad)." % (g["state"], g["side"], g["n"], g["net_usdt"]))
    else:
        lines.append("Seekhne ke liye abhi data kam hai: kul %d band trades, kisi bhi group mein %d nahi hue. Tab tak koi USE / AVOID nahi bolega." % (life["total_closed"], V.MIN_N))
    off = [c["key"] for c in guard.get("chips", []) if c["key"] == "kill_switch" and c["state"] == "TRIPPED"]
    lines.append("Safety: LIVE band hai." + (" Kill switch ON hai, naye trade nahi khulenge." if off else ""))
    return {"ready": True, "framework": VERSION, "source": source, "live": "LOCKED", "day_start": a, "day_end": b, "decisions": dec, "top_skips": [{"reason": t, "n": c} for t, c in skips],
            "trades": {"opened": opened, "closed": len(cl), "net_usdt": round(net, 2), "costs_usdt": round(cost, 2), "closed_rows": [{"symbol": r[0], "side": r[1], "exit": r[2], "net_usdt": round(r[3], 2)} for r in cl]},
            "open_positions": op, "waits": waits, "no_data": list(nodata.values()), "learned_groups": learned, "all_days": {"total_closed": life["total_closed"], "groups": life["closed_by_state_side"]},
            "safety": guard.get("chips", []), "lines": lines}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--source", default="PAPER", choices=B.SOURCES)
    ap.add_argument("--day", default=None)
    a = ap.parse_args(argv)
    r = build(a.data, a.source, a.day)
    print("\n".join(r["lines"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
