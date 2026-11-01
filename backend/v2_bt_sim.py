"""v2_bt_sim.py - Part 85a: BRAIN TRADER 5 of 8 (backend). The PAPER SIMULATOR: it lets the Brain (v2_bt_rules, version BT-01) look at the saved candles, decide, open pretend trades, close them and LABEL them.
Four jobs, each one call:
  replay_coin  - REPLAY: walks the past candles of ONE coin one by one (a decision at candle i sees candles 0..i only), saves every decision, runs every trade to its end. Source REPLAY, sample TRAIN (older 70%) / HOLDOUT (newest 30%).
  paper_scan   - PAPER / SHADOW: looks at the NEWEST closed candle of one coin now. The safety guard (v2_bt_guard) is asked first; a refusal is saved as a SKIP with the guard's sentence. Sample NEW. No order is ever placed.
  manage_open  - closes open PAPER / SHADOW trades with the candles that came after them (stop, target, time; the kill switch closes everything at the last close).
  labels       - what the Brain did, in counts: decisions per market state, and closed trades per market state + side + exit, net of fee, boxes never added together.
Rules: only candles of the NEWEST gap-free run of the coin are used (a gap is never bridged); entry = the close of the signal candle; stop and target in the same candle = STOP; costs = 2 x (fee + slippage) taken from the price move (raw price %, not leveraged).
A decision is saved at close_ts = the candle's open time + the step; the trade's open_ts is that same time. The same signal twice is ignored by the store (rerunning is safe).
In REPLAY the safety guard is NOT used (it works with the wall clock); one trade per coin at a time is kept by jumping past the trade. WAIT ideas are saved as decisions; resolving a WAIT (did the condition come?) is Part 85b.
Reads the market store read-only; writes ONLY to v2_brain_trader.db. No network, no order code, no trading import.
Run (Termux, optional; set OWL_DATA_DIR first):  python3 backend/v2_bt_sim.py replay --symbol XYZUSDT [--interval 5m]  |  scan --symbol XYZUSDT [--source PAPER|SHADOW]  |  manage  |  labels [--source REPLAY]"""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_exit2 as X2
import v2_bt_guard as G
import v2_bt_rules as R
import v2_bt_state as ST
import v2_bt_store as B
import v2_bt_why as W
import v2_defs as D
import v2_replay as V
import v2_scalp_ind as IND
import v2_setup_finder as SF
import v2_store as S

VERSION = "v2_bt_sim 1 (Part 85a)"
FINISHED = ("TARGET", "STOP", "TIME", "CLOSE_RULE")


def _chart_extra(ctx, i):
    import v2_bt_chart as CH                                        # late import: v2_bt_chart imports this file
    return CH.extra(ctx, i)


def load_run(data_dir, symbol, interval):
    """The NEWEST gap-free run of clean closed candles of one coin (read-only). [] when the market store or the coin is missing."""
    path = S.store_path(data_dir)
    if not os.path.isfile(path):
        return []
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    try:
        good, _bad = D.clean_candles(D.candles_from_store(con, symbol, interval, 0, 2 ** 31), interval)
    finally:
        con.close()
    runs = SF.runs(good, interval)
    return runs[-1] if runs else []


def _close_rec(side, entry, sim, run, i, step):
    """The close record of a finished simulation. mfe = best move for the trade, mae = worst move against it (both in %, mae as a positive number)."""
    j = i + sim["hold_candles"]
    seg = run[i + 1:j + 1] or [run[i]]
    hi, lo = max(c[2] for c in seg), min(c[3] for c in seg)
    mfe, mae = ((hi - entry) / entry, (entry - lo) / entry) if side == "LONG" else ((entry - lo) / entry, (hi - entry) / entry)
    return {"close_ts": run[j][0] + step, "exit_price": sim["exit_price"], "exit_reason": sim["status"], "gross_pct": sim["gross_pct"], "fee_pct": 2 * R.FEE_PCT,
            "slip_pct": 2 * R.SLIP_PCT, "mfe_pct": round(max(mfe, 0.0) * 100, 4), "mae_pct": round(max(mae, 0.0) * 100, 4), "hold_candles": sim["hold_candles"]}


def _decision_rec(source, sample, symbol, interval, run, i, step, t, d, version=R.BT_VERSION):
    return {"version": version, "source": source, "symbol": symbol, "interval": interval, "close_ts": run[i][0] + step, "side": d["side"], "decision": d["decision"], "sample": sample,
            "state": d["state"], "reason": d["reason"], "data_upto_ts": run[i][0] + step,
            "snapshot": {"tags": t, "wait_for": d["wait_for"], "wait_kind": d["wait_kind"], "max_wait_candles": d["max_wait_candles"], "entry": d["entry"], "sl": d["sl"], "tp": d["tp"]}}


def _trade_rec(source, sample, symbol, interval, run, i, step, d, version=R.BT_VERSION):
    return {"version": version, "source": source, "symbol": symbol, "interval": interval, "side": d["side"], "open_ts": run[i][0] + step, "entry": d["entry"], "sl": d["sl"], "tp": d["tp"],
            "size_usdt": R.SIZE_USDT, "sample": sample}


def replay_coin(con, data_dir, symbol, interval="5m"):
    """REPLAY of ONE coin. -> counts (decisions per kind, trades closed, net sum in USDT) or a DATA_NOT_READY note. Safe to run again: saved rows are ignored the second time."""
    run, need, step = load_run(data_dir, symbol, interval), IND.need_candles(), D.STEP[interval]
    if len(run) < need:
        return {"status": "DATA_NOT_READY", "symbol": symbol, "candles": len(run), "need": need, "why": W.why(data_dir, symbol, interval)}
    B.register_version(con, R.BT_VERSION, R.definition())
    ctx, cut, end = ST.prepare(run), V.holdout_cut([c[0] for c in run]), run[-1][0] + step
    out = {"status": "OK", "symbol": symbol, "interval": interval, "candles": len(run), "data_note": W.why(data_dir, symbol, interval)["text"], "decisions": {}, "trades_closed": 0, "net_usdt": 0.0, "unresolved": 0}
    i = need - 1
    while i < len(run):
        t = ST.tags(ctx, i)
        t.update(_chart_extra(ctx, i))
        d = R.decide(ctx, t, i)
        sample = V.sample_of(run[i][0], cut)
        hold = 0
        if d["decision"] in ("OPEN_LONG", "OPEN_SHORT"):
            sim = V.simulate(run, i, d["side"], d["sl"], d["tp"], R.MAX_HOLD, step, end)
            if sim["status"] in FINISHED:
                B.add_decision(con, _decision_rec("REPLAY", sample, symbol, interval, run, i, step, t, d))
                tid = B.open_trade(con, _trade_rec("REPLAY", sample, symbol, interval, run, i, step, d))
                if tid:
                    B.close_trade(con, tid, _close_rec(d["side"], d["entry"], sim, run, i, step))
                    out["trades_closed"] += 1
                    out["net_usdt"] += sim["net_pct"] / 100.0 * R.SIZE_USDT
                hold = sim["hold_candles"]
            else:                                              # the trade window is not over, or it runs into a gap: the end is unknown, so it is NOT counted as a result
                d = dict(d, decision="NO_OPINION", reason="The idea was %s, but how it ended is not known (the candles stop too soon)." % d["decision"])
                B.add_decision(con, _decision_rec("REPLAY", sample, symbol, interval, run, i, step, t, d))
                out["unresolved"] += 1
        else:
            B.add_decision(con, _decision_rec("REPLAY", sample, symbol, interval, run, i, step, t, d))
        out["decisions"][d["decision"]] = out["decisions"].get(d["decision"], 0) + 1
        i += max(1, hold)
    out["net_usdt"] = round(out["net_usdt"], 2)
    return out


def paper_scan(con, data_dir, symbol, interval="5m", now=None, source="PAPER", version=None):
    """The newest closed candle of ONE coin, now. -> the decision (and the guard's answer when a trade was wanted). PAPER and SHADOW only; LIVE does not exist here."""
    if source not in ("PAPER", "SHADOW"):
        raise ValueError("source must be PAPER or SHADOW")
    now = int(time.time() if now is None else now)
    version = version or R.BT_VERSION                              # Part E3: BT-02 (same entry, the Brain decides the exit) runs in SHADOW only
    if version not in (R.BT_VERSION, X2.BT2) or (version == X2.BT2 and source != "SHADOW"):
        raise ValueError("BT-02 runs in SHADOW only")
    defn = X2.definition() if version == X2.BT2 else R.definition()
    run, need, step = load_run(data_dir, symbol, interval), IND.need_candles(), D.STEP[interval]
    if len(run) < need:                                            # the Brain says WHY (Part 85b) and the report shows it
        reason = W.why(data_dir, symbol, interval, now)
        B.register_version(con, version, defn)
        ts = now // step * step
        B.add_decision(con, {"version": version, "source": source, "symbol": symbol, "interval": interval, "close_ts": ts, "side": "LONG", "decision": "NO_OPINION", "sample": "NEW",
                             "state": "DATA_NOT_READY", "reason": reason["text"], "data_upto_ts": ts, "snapshot": {"why": reason}})
        return {"status": "DATA_NOT_READY", "symbol": symbol, "candles": len(run), "need": need, "why": reason}
    B.register_version(con, version, defn)
    i = len(run) - 1
    ctx = ST.prepare(run)
    t = ST.tags(ctx, i)
    t.update(_chart_extra(ctx, i))                                 # Part 86a: chart tags saved with the decision (the rules ignore them)
    d = R.decide(ctx, t, i)
    guard = None
    if d["decision"] in ("OPEN_LONG", "OPEN_SHORT"):
        guard = G.check_entry(con, source, symbol, interval, d["side"], now, run[i][0])
        if not guard["allowed"]:
            d = dict(d, decision="SKIP", reason="Safety guard: " + " ".join(r["text"] for r in guard["reasons"]))
    new = B.add_decision(con, _decision_rec(source, "NEW", symbol, interval, run, i, step, t, d, version))
    opened = None
    if new and d["decision"] in ("OPEN_LONG", "OPEN_SHORT"):
        opened = B.open_trade(con, _trade_rec(source, "NEW", symbol, interval, run, i, step, d, version))
    return {"status": "OK", "symbol": symbol, "decision": d["decision"], "side": d["side"], "state": d["state"], "reason": d["reason"], "wait_for": d["wait_for"], "new_signal": new,
            "trade_opened": opened, "guard": guard}


def _max_hold(con, version):
    r = con.execute("SELECT definition FROM bt_version WHERE version=?", (version,)).fetchone()
    return int(json.loads(r[0]).get("max_hold", R.MAX_HOLD)) if r else R.MAX_HOLD


def manage_open(con, data_dir, now=None, source="PAPER"):
    """Closes the open trades of ONE source whose end is now known. -> counts. A trade whose candle run has a gap stays open (the guard shows it as stuck after 3 days)."""
    now, out = int(time.time() if now is None else now), {"checked": 0, "closed": 0, "still_open": 0, "unavailable": 0}
    killed = G.is_killed(con)
    for tid, symbol, interval, side, open_ts in B.open_trades(con, source):
        out["checked"] += 1
        o = con.execute("SELECT version, entry, sl, tp FROM bt_trade_open WHERE trade_id=?", (tid,)).fetchone()
        run, step = load_run(data_dir, symbol, interval), D.STEP[interval]
        idx = next((k for k in range(len(run) - 1, -1, -1) if run[k][0] + step == open_ts), None)
        if idx is None:
            out["unavailable"] += 1
            continue
        if killed:
            px, held = run[-1][4], len(run) - 1 - idx
            g = (px - o[1]) / o[1] * 100.0 * (1 if side == "LONG" else -1)
            sim = {"status": "KILL_SWITCH", "exit_price": px, "gross_pct": g, "hold_candles": held}
        else:
            if o[0] == X2.BT2:                                         # Part E3: the Brain's own exit (TSI / Z read at every candle)
                r2 = X2.brain_exit(run, ST.prepare(run), idx, side, o[1], o[2], o[3], _max_hold(con, o[0]))
                sim = dict(r2, gross_pct=0.0 if r2["exit_price"] is None else (r2["exit_price"] - o[1]) / o[1] * 100.0 * (1 if side == "LONG" else -1))
            else:
                sim = V.simulate(run, idx, side, o[2], o[3], _max_hold(con, o[0]), step, now)
        if sim["status"] in FINISHED or sim["status"] == "KILL_SWITCH":
            B.close_trade(con, tid, _close_rec(side, o[1], sim, run, idx, step))
            out["closed"] += 1
        else:
            out["still_open"] += 1
    return out


def labels(con, source="REPLAY"):
    """What the Brain did, in counts (ONE source, never mixed). Closed trades are grouped by market state at the entry + side; under 30 trades a group says 'too few to say anything'. No win rate."""
    dec = {}
    for st, kind, n in con.execute("SELECT state, decision, COUNT(*) FROM bt_decision WHERE source=? GROUP BY state, decision", (source,)):
        dec.setdefault(st or "?", {})[kind] = n
    q = ("SELECT d.state, o.side, c.exit_reason, c.net_usdt FROM bt_trade_open o JOIN bt_trade_close c ON c.trade_id=o.trade_id "
         "LEFT JOIN bt_decision d ON d.version=o.version AND d.source=o.source AND d.symbol=o.symbol AND d.interval=o.interval AND d.close_ts=o.open_ts AND d.side=o.side WHERE o.source=?")
    groups = {}
    for st, side, why, net in con.execute(q, (source,)):
        g = groups.setdefault((st or "?", side), {"state": st or "?", "side": side, "n": 0, "TARGET": 0, "STOP": 0, "TIME": 0, "KILL_SWITCH": 0, "net_usdt": 0.0})
        g["n"] += 1
        g[why] = g.get(why, 0) + 1
        g["net_usdt"] += net
    rows = sorted(groups.values(), key=lambda g: g["net_usdt"])
    for g in rows:
        g["net_usdt"] = round(g["net_usdt"], 2)
        if g["n"] < V.MIN_N:
            g["note"] = "too few to say anything (under %d trades)" % V.MIN_N
    return {"source": source, "framework": VERSION, "decisions_by_state": dec, "closed_by_state_side": rows, "total_closed": sum(g["n"] for g in rows),
            "note": "net of fee and slippage, pretend money; sources and boxes are never added together"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("job", choices=("replay", "scan", "manage", "labels"))
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="5m", choices=("3m", "5m"))
    ap.add_argument("--source", default=None, choices=("REPLAY", "PAPER", "SHADOW"))
    a = ap.parse_args(argv)
    con = B.connect(a.data)
    try:
        if a.job == "replay":
            res = replay_coin(con, a.data, a.symbol, a.interval)
        elif a.job == "scan":
            res = paper_scan(con, a.data, a.symbol, a.interval, source=a.source or "PAPER")
        elif a.job == "manage":
            res = manage_open(con, a.data, source=a.source or "PAPER")
        else:
            res = labels(con, a.source or "REPLAY")
    finally:
        con.close()
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
