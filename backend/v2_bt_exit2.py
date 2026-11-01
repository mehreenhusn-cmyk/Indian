"""v2_bt_exit2.py - Part E3 / E4: BT-02 = the SAME entry as BT-01, but the Brain decides the EXIT itself, candle by candle, from what it SEES (TSI, TSI signal line, Z). Backend, read-only logic, no network, no write, no trading import.
Owner wish (1 Nov 2026): "the Brain should read the market and decide when to book profit, when to trail, will it go to TP2 or not, not fixed conditions from me".
What the Brain does at EVERY closed candle of an open trade (it never looks at a later candle):
  PROTECT  the trade has gained one full stop distance -> the stop moves to the entry price (no loss any more, only fee).
  CLOSE    the trade is in profit and TSI crosses its signal line AGAINST the trade -> close at this candle close (the move is tiring, take the profit).
  TP1      the price touches the first target (1.5 x stop distance): the Brain LOOKS at this candle close. TSI on the trade's side of its signal AND Z on the trade's side AND the candle closed beyond TP1 -> it RUNS:
           the stop moves to TP1 (the TP1 profit is locked) and the target becomes TP2 (2.5 x stop distance). If it does not see strength, it takes TP1 at once.
  TIME     24 candles, like BT-01.
So the Brain decides WHEN to close, WHETHER to trail and WHETHER to go for TP2 by reading the indicators on the day; the only fixed numbers are the starting distances below (NV = not validated). They are tested in the Exit Study (BRAIN row) before anything moves to PAPER.
Honest limits: inside one candle the stop is checked first; a stop that moved is assumed filled at its price (no gap); the owner's OK is needed to move BT-02 from SHADOW to PAPER. LIVE is locked.
Functions: brain_exit() replays one trade candle by candle (used by the Exit Study, the SHADOW manager and the labels); label() = the word for an OPEN trade (HOLD / PROTECT / CLOSE) + the Brain's own sentence.
Run: not a program, it is imported by v2_bt_sim.py, v2_bt_exitlab.py and v2_bt_detail.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_rules as R

VERSION = "v2_bt_exit2 1 (Parts E3 / E4)"
BT2 = "BT-02"
PROTECT_R, TP2_R = 1.0, 2.5                                           # in stop distances from the entry (NV)


def definition():
    """The full text of BT-02 (saved once in the store). The entry part is the BT-01 text, so the two versions differ ONLY in the exit."""
    d = dict(R.definition())
    d["exit"] = ("BRAIN EXIT: read TSI / signal / Z at every candle close. Gain of 1 stop distance -> stop to entry. In profit and TSI crosses against -> close. TP1 touched: run to TP2 (%.1f x stop) with the stop at TP1 only if TSI and Z "
                 "agree and the candle closed beyond TP1, else take TP1. Time exit 24 candles." % TP2_R)
    d["target"] = "TP1 %.1f x stop distance, TP2 %.1f x stop distance (the Brain decides at TP1)" % (R.TARGET_R, TP2_R)
    d["entry_rule_of"] = R.BT_VERSION
    return d


def _agree(ctx, j, long_):
    """Does what the Brain sees at candle j stand on the trade's side? TSI vs its signal line AND Z."""
    ind = ctx["ind"]
    t, s, z = ind["tsi"][j], ind["tsi_signal"][j], ind["z"][j]
    if t is None or s is None or z is None:
        return False
    return (t > s and z > 0) if long_ else (t < s and z < 0)


def _turned(ctx, j, long_):
    h, h0 = ctx["ind"]["hist"][j], ctx["ind"]["hist"][j - 1]
    if h is None or h0 is None:
        return False
    return (h < 0 <= h0) if long_ else (h > 0 >= h0)


def brain_exit(run, ctx, i, side, entry, sl, tp, hold):
    """Replay ONE trade from the signal candle i, candle by candle. -> {status, exit_price, hold_candles, best_pct, mode, note}.
    status = TARGET / STOP / CLOSE_RULE / TIME when finished, PENDING when the candles so far did not end it (the trade is still open). mode = NORMAL / PROTECTED / RUNNING (what the stop does now)."""
    long_ = side == "LONG"
    sg = 1.0 if long_ else -1.0
    risk = abs(entry - sl)
    tp2 = entry + sg * TP2_R * risk
    stop, mode, best, note = sl, "NORMAL", entry, "Nothing special yet."
    last = min(i + hold, len(run) - 1)

    def done(status, px, j):
        b = max(best, run[j][2]) if long_ else min(best, run[j][3])
        return {"status": status, "exit_price": px, "hold_candles": j - i, "best_pct": sg * (b - entry) / entry * 100.0, "mode": mode, "note": note}

    for j in range(i + 1, last + 1):
        hi, lo, cl = run[j][2], run[j][3], run[j][4]
        if (long_ and lo <= stop) or (not long_ and hi >= stop):
            note = "Stopped at the %s." % ("stop" if mode == "NORMAL" else "protected stop (profit kept)")
            return done("STOP" if mode == "NORMAL" else "CLOSE_RULE", stop, j)
        if mode == "RUNNING":
            if (long_ and hi >= tp2) or (not long_ and lo <= tp2):
                note = "Ran to TP2."
                return done("TARGET", tp2, j)
        elif (long_ and hi >= tp) or (not long_ and lo <= tp):
            if _agree(ctx, j, long_) and sg * (cl - tp) >= 0:
                mode, stop, note = "RUNNING", tp, "TP1 touched, TSI and Z still agree: running to TP2, stop moved to TP1."
            else:
                note = "TP1 touched and the Brain did not see strength: took TP1."
                return done("TARGET", tp, j)
        best = max(best, hi) if long_ else min(best, lo)
        if mode == "NORMAL" and sg * (best - entry) >= PROTECT_R * risk:
            mode, stop, note = "PROTECTED", entry, "Gained one stop distance: stop moved to the entry price."
        if sg * (cl - entry) > 0 and _turned(ctx, j, long_):
            note = "In profit and TSI turned against the trade: closed at the candle close."
            return done("CLOSE_RULE", cl, j)
    if i + hold <= len(run) - 1:
        note = "Time limit reached."
        return done("TIME", run[i + hold][4], i + hold)
    return {"status": "PENDING", "exit_price": None, "hold_candles": last - i, "best_pct": None, "mode": mode, "note": note}


def label(run, ctx, i, side, entry, sl, tp, hold):
    """The word for an OPEN trade, from the same replay: CLOSE (the Brain has just decided to close), PROTECT (the stop was moved to lock profit), else HOLD. -> (word, sentence)."""
    r = brain_exit(run, ctx, i, side, entry, sl, tp, hold)
    if r["status"] != "PENDING":
        return "CLOSE", "The Brain's own decision: %s It closes at the next check." % r["note"]
    if r["mode"] != "NORMAL":
        return "PROTECT", "The Brain's own decision: %s" % r["note"]
    return "HOLD", "The Brain reads TSI and Z at every candle and sees no reason to act yet."
