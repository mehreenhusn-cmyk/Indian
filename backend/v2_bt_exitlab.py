"""v2_bt_exitlab.py - Part E1: EXIT STUDY (backend, read-only). The owner's question: "can the Brain close a trade by the indicator so profit is not given back?"
The SAME closed trades (same entry, same stop, same target, same 24-candle time limit) are replayed on the saved candles with 5 exit rules, for ONE source (PAPER / SHADOW / REPLAY, never added):
  CURRENT    stop, target, time only (what BT-01 does now; recomputed here so the 4 rules are compared on equal terms)
  TSI_TURN   like CURRENT, plus: if the trade is in profit at a candle close and TSI crosses its signal line AGAINST the trade, close at that close
  GIVEBACK   like CURRENT, plus: after the trade has made at least half of its stop distance, close when HALF of the best gain is given back (exit assumed at that level)
  BREAKEVEN  like CURRENT, plus: after the price has moved one full stop distance for the trade, the stop moves to the entry price
  BRAIN      Part E3: the Brain's OWN exit (v2_bt_exit2.py = BT-02): it reads TSI / Z at every candle, protects, closes and decides at TP1 whether to run to TP2
Per rule: trades, net (USDT, after fee + slippage), average, GIVE-BACK (best open gain minus the gain at exit, summed), WORST DIP (biggest fall of the running net), net of the OLDER and the NEWER half.
Verdict against CURRENT: 30+ trades needed for any word, 60+ for BETTER / WORSE. BETTER = better net in BOTH halves; WORSE = worse in both; else NOT CLEAR. Luck can explain a lot. Nothing is applied: BT-01 stays frozen, LIVE stays locked.
Honest limits: inside one candle the order of high and low is unknown (stop is checked first, like the simulator); a trade whose candles are missing or too short is skipped and counted; only the newest 400 closed trades are used (speed).
Reads v2_brain_trader.db and the market store read-only. No network, no write, no trading import. The route /api/v2/brain_exits (api/v2_data.py) calls build().
Run (Termux, optional):  python3 backend/v2_bt_exitlab.py [--data DIR] [--source REPLAY]  -> the plain lines."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_exit2 as X2
import v2_bt_rules as R
import v2_bt_sim as SIM
import v2_bt_state as ST
import v2_bt_store as B
import v2_defs as D
import v2_replay as V

VERSION = "v2_bt_exitlab 1 (Part E1)"
MAX_TRADES, MIN_N, VERDICT_N = 400, 30, 60
RULES = (("CURRENT", "Current exit", "Stop, target or time. This is what BT-01 does now."),
         ("TSI_TURN", "TSI turns against", "If in profit and TSI crosses its signal line against the trade, close at that candle close."),
         ("GIVEBACK", "Half of the gain given back", "After half a stop distance of gain, close when half of the best gain is lost."),
         ("BREAKEVEN", "Break-even stop", "After one full stop distance of gain, move the stop to the entry price."),
         ("BRAIN", "Brain decides (BT-02)", "The Brain reads TSI and Z each candle: protects, closes, and at TP1 decides alone whether to run to TP2."))


def _trades(con, source):
    q = ("SELECT o.symbol, o.interval, o.side, o.open_ts, o.entry, o.sl, o.tp, o.size_usdt, c.close_ts FROM bt_trade_open o JOIN bt_trade_close c ON c.trade_id=o.trade_id "
         "WHERE o.source=? ORDER BY c.close_ts DESC, c.trade_id DESC LIMIT ?")
    rows = con.execute(q, (source, MAX_TRADES)).fetchall()
    return rows[::-1]                                                  # oldest first


def one(run, ctx, i, side, entry, sl, tp, rule, hold):
    """Replay ONE trade from the signal candle i with ONE rule. -> (exit_price, held_candles, best_gain_pct) or None when the candles are too short."""
    if i + hold >= len(run):
        return None
    if rule == "BRAIN":
        r = X2.brain_exit(run, ctx, i, side, entry, sl, tp, hold)
        return None if r["status"] == "PENDING" else (r["exit_price"], r["hold_candles"], r["best_pct"])
    long_ = side == "LONG"
    sgn = 1.0 if long_ else -1.0
    risk = abs(entry - sl)
    best = entry                                                       # best price for the trade so far (candles before the current one)
    be = False
    hist = ctx["ind"]["hist"]
    ex, held = None, hold
    for j in range(i + 1, i + hold + 1):
        hi, lo, cl = run[j][2], run[j][3], run[j][4]
        stop = entry if (rule == "BREAKEVEN" and be) else sl
        if rule == "GIVEBACK" and sgn * (best - entry) >= 0.5 * risk:
            lvl = best - sgn * 0.5 * abs(best - entry)
            if (long_ and lo <= lvl) or (not long_ and hi >= lvl):
                ex, held = lvl, j - i
                break
        if (long_ and lo <= stop) or (not long_ and hi >= stop):
            ex, held = stop, j - i
            break
        if (long_ and hi >= tp) or (not long_ and lo <= tp):
            ex, held = tp, j - i
            break
        best = max(best, hi) if long_ else min(best, lo)
        if rule == "BREAKEVEN" and sgn * (best - entry) >= risk:
            be = True
        if rule == "TSI_TURN" and sgn * (cl - entry) > 0 and hist[j] is not None and hist[j - 1] is not None:
            if (long_ and hist[j] < 0 <= hist[j - 1]) or (not long_ and hist[j] > 0 >= hist[j - 1]):
                ex, held = cl, j - i
                break
    if ex is None:
        ex = run[i + hold][4]
    best = max(best, run[i + held][2]) if long_ else min(best, run[i + held][3])
    return ex, held, sgn * (best - entry) / entry * 100.0


def stats(rows, base=None):
    """rows = [(trade number, net_usdt, giveback_usdt)] oldest first -> the numbers of ONE rule (+ the verdict against base when given)."""
    n = len(rows)
    net = sum(r[1] for r in rows)
    run, peak, dip = 0.0, 0.0, 0.0
    for r in rows:
        run += r[1]
        peak = max(peak, run)
        dip = max(dip, peak - run)
    half = n // 2
    out = {"trades": n, "net_usdt": round(net, 2), "avg_usdt": round(net / n, 3) if n else None, "giveback_usdt": round(sum(r[2] for r in rows), 2), "worst_dip_usdt": round(dip, 2),
           "older_net": round(sum(r[1] for r in rows[:half]), 2), "newer_net": round(sum(r[1] for r in rows[half:]), 2)}
    out["verdict"], out["text"] = _verdict(out, base)
    return out


def _verdict(s, base):
    n = s["trades"]
    if base is None:
        return "BASE", "The reference: %d trades, net %+.2f USDT, %.2f USDT of open gain was given back." % (n, s["net_usdt"], s["giveback_usdt"])
    if n < MIN_N:
        return "NOT ENOUGH DATA", "Only %d trades. At least %d are needed before this rule may be judged." % (n, MIN_N)
    up = s["older_net"] > base["older_net"] and s["newer_net"] > base["newer_net"]
    down = s["older_net"] < base["older_net"] and s["newer_net"] < base["newer_net"]
    facts = "Net %+.2f against %+.2f for the current exit; give-back %.2f against %.2f; worst dip %.2f against %.2f." % (s["net_usdt"], base["net_usdt"], s["giveback_usdt"], base["giveback_usdt"], s["worst_dip_usdt"], base["worst_dip_usdt"])
    if n < VERDICT_N:
        return "EARLY HINT", "%s Early hint only (%d trades): luck can explain this; %d trades are needed for a real answer." % (facts, n, VERDICT_N)
    w = "BETTER" if up else "WORSE" if down else "NOT CLEAR"
    return w, "%s %s Luck can still explain part of it." % (facts, "Better in both halves." if up else "Worse in both halves." if down else "The two halves do not agree.")


def build(data_dir, source="REPLAY", now=None):
    if source not in B.SOURCES:
        raise ValueError("source must be REPLAY, PAPER or SHADOW")
    con = B.open_ro(data_dir)
    if con is None:
        return {"ready": False, "framework": VERSION, "source": source, "live": "LOCKED", "note": "No Brain Trader file yet: nothing has been saved. Run the Brain tick first."}
    try:
        trades = _trades(con, source)
    finally:
        con.close()
    runs, rows, skipped = {}, {k: [] for k, _n, _t in RULES}, 0
    for sym, iv, side, open_ts, entry, sl, tp, size, _close in trades:
        if iv not in D.STEP:
            skipped += 1
            continue
        key = (sym, iv)
        if key not in runs:
            run = SIM.load_run(data_dir, sym, iv)
            runs[key] = (run, ST.prepare(run) if len(run) >= 2 else None, {c[0]: k for k, c in enumerate(run)})
        run, ctx, pos = runs[key]
        i = pos.get(open_ts - D.STEP[iv])
        if i is None or ctx is None:
            skipped += 1
            continue
        res = {k: one(run, ctx, i, side, entry, sl, tp, k, R.MAX_HOLD) for k, _n, _t in RULES}
        if any(v is None for v in res.values()):
            skipped += 1
            continue
        for k, (ex, _held, best_pct) in res.items():
            gross = (ex - entry) / entry * 100.0 * (1 if side == "LONG" else -1)
            gb = max(best_pct - gross, 0.0) / 100.0 * size
            rows[k].append((len(rows[k]), (gross - V.cost_pct()) / 100.0 * size, gb))
    base = stats(rows["CURRENT"])
    out = []
    for k, name, plain in RULES:
        s = base if k == "CURRENT" else stats(rows[k], base)
        out.append(dict(s, key=k, name=name, plain=plain))
    good = [r for r in out if r["verdict"] == "BETTER"]
    best = max(good, key=lambda r: r["net_usdt"])["key"] if good else None
    return {"ready": True, "framework": VERSION, "source": source, "live": "LOCKED", "used": base["trades"], "skipped": skipped, "rules": out, "best": best,
            "note": "The same closed trades replayed on saved candles with other exits, net of fee + slippage. Nothing is applied: BT-01 stays frozen and LIVE is locked. Inside one candle the stop is checked first."}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--source", default="REPLAY", choices=B.SOURCES)
    a = ap.parse_args(argv)
    r = build(a.data, a.source)
    if not r["ready"]:
        print(r["note"])
        return 0
    print("%s: %d trades used, %d skipped" % (r["source"], r["used"], r["skipped"]))
    for x in r["rules"]:
        print(" %-10s %-16s %s" % (x["key"], x["verdict"], x["text"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
