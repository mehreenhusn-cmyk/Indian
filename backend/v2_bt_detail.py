"""v2_bt_detail.py - Part 87 (backend, read-only): the data of the SIGNAL DETAIL screen (87a) and the ACTIVE PAPER TRADE screen (87b).
signal(): one coin NOW: the Brain's answer with entry / stop / target, WHAT THE BRAIN SAW (the chart sentences of Part 86a), WHY NOT EARLIER (its older saved answers for this coin), EVIDENCE FROM SIMILAR TRADES (closed paper trades of the same
market state + side, net of fee; under 30 trades = NOT ENOUGH DATA, no win rate), a DATA TO BRAIN panel (how many candles of the gap-free run it has, from when to when) and a small chart (last 100 candles + EMA50 + SD middle + 2 SD bands).
trade(): the open PAPER trade of a coin: entry, now, unrealized net (after fee + slippage), best point so far (MFE), worst (MAE), give-back, candles held and left, distance to stop and target, a plain WATCH label and 'why I am still in' sentences.
WATCH labels are words for the screen, never an order and never changed in the store: HOLD (nothing special), PROTECT (gave back half of a real gain, or TSI + histogram turned against the trade), CLOSE SOON (2 or fewer candles of hold time left).
Starting limits are NV (not validated). Nothing is saved, no network, no order code, LIVE does not exist. Run (Termux, optional):  python3 backend/v2_bt_detail.py signal|trade --symbol XYZUSDT [--interval 5m] -> JSON."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_botcmp as BC
import v2_bt_chart as CH
import v2_bt_exit2 as X2
import v2_bt_rules as R
import v2_bt_sim as M
import v2_bt_state as ST
import v2_bt_store as B
import v2_bt_why as W
import v2_defs as D
import v2_replay as V
import v2_scalp_ind as IND

VERSION = "v2_bt_detail 1 (Part 87)"
CHART_N, GIVEBACK, MIN_MFE_PCT, CLOSE_LEFT = 100, 0.5, 0.3, 2


def _r(x, d=4):
    return None if x is None else round(float(x), d)


def chart_payload(run, ctx, step, n=CHART_N):
    """The last n candles + the lines drawn on the owner's main chart. Arrays have the same length; None = not enough candles yet."""
    ind, a = ctx["ind"], max(0, len(run) - n)
    up2 = lambda k: None if ind["sd_mean"][k] is None or ind["sd_std"][k] is None else ind["sd_mean"][k] + 2 * ind["sd_std"][k]
    lo2 = lambda k: None if ind["sd_mean"][k] is None or ind["sd_std"][k] is None else ind["sd_mean"][k] - 2 * ind["sd_std"][k]
    rg = range(a, len(run))
    return {"step": step, "candles": [[int(run[k][0]), run[k][1], run[k][2], run[k][3], run[k][4]] for k in rg], "ema50": [_r(ind["ema50"][k], 8) for k in rg], "mid": [_r(ind["sd_mean"][k], 8) for k in rg],
            "up2": [_r(up2(k), 8) for k in rg], "lo2": [_r(lo2(k), 8) for k in rg]}


def _evidence(con, source, state, side):
    lab = M.labels(con, source)
    g = next((x for x in lab["closed_by_state_side"] if x["state"] == state and x["side"] == side), None)
    n = g["n"] if g else 0
    ok = n >= V.MIN_N
    text = ("%d closed paper trades in %s %s, net %+.2f USDT after fee." % (n, state, side, g["net_usdt"])) if ok else \
           ("NOT ENOUGH DATA: %d closed paper trades in %s %s (need %d). Brain does not say USE or AVOID yet." % (n, state, side, V.MIN_N))
    return {"label": "EVIDENCE" if ok else "NOT ENOUGH DATA", "n": n, "need": V.MIN_N, "net_usdt": g["net_usdt"] if g else None, "text": text, "all_closed": lab["total_closed"]}


def _older(con, source, symbol, interval, k=3):
    rows = con.execute("SELECT close_ts, decision, state, reason FROM bt_decision WHERE source=? AND symbol=? AND interval=? ORDER BY close_ts DESC LIMIT ?", (source, symbol, interval, k + 1)).fetchall()
    return [{"time": W.ist(ts), "decision": d, "state": s, "reason": r} for ts, d, s, r in rows[1:]]


def signal(data_dir, symbol, interval="5m", source="PAPER", now=None):
    now = int(time.time() if now is None else now)
    run, need, step = M.load_run(data_dir, symbol, interval), IND.need_candles(), D.STEP[interval]
    if len(run) < need:
        w = W.why(data_dir, symbol, interval, now)
        return {"ready": False, "symbol": symbol, "interval": interval, "why": w, "lines": [w["text"]], "data": {"candles": len(run), "need": need}}
    i = len(run) - 1
    ctx = ST.prepare(run)
    t = ST.tags(ctx, i)
    x = CH.extra(ctx, i)
    d = R.decide(ctx, t, i)
    con, older, ev = B.open_ro(data_dir), [], {"label": "NOT ENOUGH DATA", "n": 0, "need": V.MIN_N, "net_usdt": None, "text": "No Brain Trader file yet.", "all_closed": 0}
    if con is not None:
        try:
            older, ev = _older(con, source, symbol, interval), _evidence(con, source, t["market_state"], d["side"])
        finally:
            con.close()
    lv = None if d["entry"] is None else {"entry": d["entry"], "sl": d["sl"], "tp": d["tp"], "risk_pct": _r(abs(d["entry"] - d["sl"]) / d["entry"] * 100.0, 3), "reward_to_risk": R.TARGET_R, "note": "BT-01 has ONE target (1.5 x the stop distance), no TP2."}
    return {"ready": True, "symbol": symbol, "interval": interval, "source": source, "candle_end": W.ist(run[i][0] + step), "state": t["market_state"], "tags": t, "chart_tags": x,
            "brain": {"decision": d["decision"], "side": d["side"], "reason": d["reason"], "wait_for": d["wait_for"], "max_wait_candles": d["max_wait_candles"]}, "levels": lv,
            "saw": CH.lines_for(t, x), "why_not_earlier": older, "evidence": ev, "bot": BC.build(data_dir, symbol, d["entry"], d["side"] if d["entry"] else None, now),
            "data": {"candles": len(run), "need": need, "from": W.ist(run[0][0]), "to": W.ist(run[i][0]), "note": "ONE gap-free run of closed candles. A gap would start a new run and the Brain would say DATA_NOT_READY with the reason."},
            "chart": chart_payload(run, ctx, step), "paper_note": "Read-only. Paper trades open by themselves when the rule says OPEN; there is no ENTER button and LIVE is locked."}


def trade(data_dir, symbol, interval="5m", source="PAPER", now=None):
    now = int(time.time() if now is None else now)
    con = B.open_ro(data_dir)
    if con is None:
        return {"ready": True, "open": False, "symbol": symbol, "interval": interval, "note": "No Brain Trader file yet."}
    try:
        mine = [x for x in B.open_trades(con, source) if x[1] == symbol and x[2] == interval]
        if not mine:
            last = con.execute("SELECT o.side, c.exit_reason, c.net_usdt, c.hold_candles FROM bt_trade_close c JOIN bt_trade_open o ON o.trade_id=c.trade_id WHERE o.source=? AND o.symbol=? AND o.interval=? ORDER BY c.close_ts DESC LIMIT 1", (source, symbol, interval)).fetchone()
            return {"ready": True, "open": False, "symbol": symbol, "interval": interval, "note": "No open paper trade in this coin.",
                    "last_closed": None if not last else {"side": last[0], "exit": last[1], "net_usdt": round(last[2], 2), "held": last[3]}}
        tid, _s, _i, side, open_ts = mine[-1]
        o = con.execute("SELECT version, entry, sl, tp, size_usdt FROM bt_trade_open WHERE trade_id=?", (tid,)).fetchone()
        max_hold = M._max_hold(con, o[0])
    finally:
        con.close()
    run, step = M.load_run(data_dir, symbol, interval), D.STEP[interval]
    idx = next((k for k in range(len(run) - 1, -1, -1) if run[k][0] + step == open_ts), None)
    if idx is None:
        return {"ready": False, "open": True, "symbol": symbol, "interval": interval, "lines": ["The candles of this trade are not in the newest gap-free run (a gap). The trade stays open and is checked again later."]}
    ent, sl, tp, sz = o[1], o[2], o[3], o[4]
    sg = 1 if side == "LONG" else -1
    px, held = run[-1][4], len(run) - 1 - idx
    after = run[idx + 1:] or run[-1:]
    best = max(x[2] for x in after) if side == "LONG" else min(x[3] for x in after)
    worst = min(x[3] for x in after) if side == "LONG" else max(x[2] for x in after)
    g, mfe, mae = (px - ent) / ent * 100.0 * sg, (best - ent) / ent * 100.0 * sg, (worst - ent) / ent * 100.0 * sg
    cost = 2 * (R.FEE_PCT + R.SLIP_PCT)
    net_pct = g - cost
    ctx = ST.prepare(run)
    t, x = ST.tags(ctx, len(run) - 1), CH.extra(ctx, len(run) - 1)
    against = x["tsi_vs_signal"] == ("BELOW" if side == "LONG" else "ABOVE") and x["storm"] == ("RED_BUILDING" if side == "LONG" else "GREEN_BUILDING")
    gave = mfe >= MIN_MFE_PCT and (mfe - g) >= GIVEBACK * mfe
    left = max_hold - held
    watch = "CLOSE SOON" if left <= CLOSE_LEFT else "PROTECT" if gave or against else "HOLD"
    why = []
    if o[0] in (X2.BT2, X2.BT3):                                          # Part E4 / M5: a BT-02 / BT-03 trade gets the Brain's OWN word (HOLD / PROTECT / CLOSE) from the same exit rule that closes it
        watch, own = X2.label(run, ctx, idx, side, ent, sl, tp, max_hold, o[0] == X2.BT3)
        why.append(own)
    if gave:
        why.append("Trade went %+.2f%% at best and gave back %.2f%% of it." % (mfe, mfe - g))
    why += CH.lines_for(t, x)
    why.append("Stop is %.2f%% away, target %.2f%% away, %d candles of hold time left." % (abs(px - sl) / px * 100.0, abs(tp - px) / px * 100.0, left))
    return {"ready": True, "open": True, "symbol": symbol, "interval": interval, "source": source, "trade_id": tid, "side": side, "opened": W.ist(open_ts), "entry": ent, "sl": sl, "tp": tp, "now": px, "size_usdt": sz,
            "unrealized_net_usdt": round(net_pct / 100.0 * sz, 2), "unrealized_net_pct": _r(net_pct, 3), "mfe_pct": _r(mfe, 3), "mae_pct": _r(mae, 3), "giveback_pct": _r(max(0.0, mfe - g), 3), "held": held, "left": left,
            "watch": watch, "why": why, "tags": t, "chart_tags": x, "chart": chart_payload(run, ctx, step), "version": o[0], "paper_note": "PAPER / SHADOW ONLY (pretend money). The WATCH label is a word, not an order."}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("job", choices=("signal", "trade"))
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--interval", default="5m", choices=("3m", "5m"))
    a = ap.parse_args(argv)
    r = (signal if a.job == "signal" else trade)(a.data, a.symbol, a.interval)
    r.pop("chart", None)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
