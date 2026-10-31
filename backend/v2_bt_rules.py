"""v2_bt_rules.py - Part 85a: BRAIN TRADER 4 of 8 (backend). The THINKING of the Brain: version BT-01 and ONE function decide() = what to do on ONE closed candle, with a plain reason.
It uses only the tags of Part 84b (the owner's 2 indicators: EMA50 + SD bands, TSI + Z + Z-SMA). No new indicator, no network, no order code, no write: it only ANSWERS.
Answers: OPEN_LONG / OPEN_SHORT (a trade idea with stop and target), WAIT (not now: it says WHAT it waits for and for how many candles; if it does not come the idea is dropped), SKIP (no trade, with the reason), NO_OPINION (not enough candles).
Side of a SKIP / WAIT / NO_OPINION = the side the market leans to (price above the SD middle = LONG, below = SHORT). It is a label for the ledger, not a direction advice.
BT-01 RULES (all STARTING values, NV = not validated, in the constants; a change needs a NEW version name BT-02, the old rows are never rewritten):
 BREAKOUT / BREAKDOWN : TSI and Z agree with the move and volume is not LOW -> open with the move; else WAIT 6 candles.
 TRENDING_UP / DOWN   : open only on a PULLBACK (price between the SD middle and 1 SD on the trend side) with TSI and Z agreeing; else WAIT 12 candles for that pullback.
 CONSOLIDATION        : WAIT 12 candles for a break out of the squeeze (no trade inside it).
 SIDEWAYS, TRANSITION, PUMP, DUMP : SKIP (the owner's own paper bot lost most of its money in sideways: Part 84b finding; pump / dump = the move is already done).
 STOP = 1.0 SD of the last 200 closes away from the entry, TARGET = 1.5 x the stop distance, time exit after 24 candles. Stop distance must be 0.3 to 2.0 % of the price (below it the fee eats the idea), else SKIP.
Run (Termux, optional):  python3 backend/v2_bt_rules.py   -> prints the version definition."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "v2_bt_rules 1 (Part 85a)"
BT_VERSION = "BT-01"
FEE_PCT = 0.05                      # per side, % of price (NV, same as the replay engine)
SLIP_PCT = 0.02                     # per side, % of price (NV)
SIZE_USDT = 100.0                   # pretend money per trade (NV); the guard limit is 1,000 USDT capital
STOP_SD, TARGET_R, MAX_HOLD = 1.0, 1.5, 24
RISK_MIN_PCT, RISK_MAX_PCT = 0.3, 2.0
WAIT_BREAK, WAIT_PULL, WAIT_SQUEEZE = 6, 12, 12


def definition():
    """The full text of BT-01 (what register_version saves). Every field the store needs is here."""
    return {"indicators": ["ema50", "sd_band", "tsi", "z", "z_sma"],
            "entry": "BREAKOUT/BREAKDOWN with TSI+Z agreeing and volume not LOW; TRENDING pullback to the SD middle..1 SD with TSI+Z agreeing; WAIT for squeeze break; SKIP sideways/transition/pump/dump",
            "stop": "%.1f SD of the last 200 closes from the entry" % STOP_SD, "target": "%.1f x stop distance" % TARGET_R, "max_hold": MAX_HOLD,
            "fee_pct": FEE_PCT, "slippage_pct": SLIP_PCT, "size_usdt": SIZE_USDT,
            "wait": {"breakout": WAIT_BREAK, "pullback": WAIT_PULL, "squeeze": WAIT_SQUEEZE}, "risk_pct_range": [RISK_MIN_PCT, RISK_MAX_PCT]}


def _lean(t):
    u = t.get("sd_units")
    return "SHORT" if u is not None and u < 0 else "LONG"


def _out(t, decision, side, reason, wait_for=None, wait_n=None, entry=None, sl=None, tp=None, kind=None):
    return {"decision": decision, "side": side, "state": t.get("market_state"), "reason": reason, "wait_for": wait_for, "max_wait_candles": wait_n,
            "entry": entry, "sl": sl, "tp": tp, "wait_kind": kind}


def _levels(ctx, t, i, side):
    """Entry = the close of the signal candle; stop 1 SD away, target 1.5 x that. -> (entry, sl, tp, risk_pct) or None when the SD is missing."""
    sd, px = ctx["ind"]["sd_std"][i], ctx["ind"]["close"][i]
    if not sd or px <= 0:
        return None
    risk = STOP_SD * sd
    sl, tp = (px - risk, px + TARGET_R * risk) if side == "LONG" else (px + risk, px - TARGET_R * risk)
    return px, sl, tp, risk / px * 100.0


def _open(ctx, t, i, side, why):
    lv = _levels(ctx, t, i, side)
    if lv is None or lv[1] <= 0 or lv[2] <= 0:
        return _out(t, "NO_OPINION", side, "The SD width is missing, so no stop can be set.")
    px, sl, tp, rp = lv
    if not RISK_MIN_PCT <= rp <= RISK_MAX_PCT:
        return _out(t, "SKIP", side, "Stop distance is %.2f%% of the price; the allowed range is %.1f to %.1f%%. The fee would eat the idea or the stop is too wide." % (rp, RISK_MIN_PCT, RISK_MAX_PCT))
    return _out(t, "OPEN_LONG" if side == "LONG" else "OPEN_SHORT", side, why, entry=px, sl=sl, tp=tp)


def decide(ctx, t, i):
    """ctx = v2_bt_state.prepare(run), t = v2_bt_state.tags(ctx, i), i = the closed candle. Uses only candles 0..i (the tags are causal). -> dict, see the file header."""
    ms, side = t.get("market_state"), _lean(t)
    if ms == "DATA_NOT_READY" or not t.get("ready"):
        return _out(t, "NO_OPINION", side, "Not enough candles yet (about 399 of one gap-free run are needed).")
    agree, vol = t.get("agreement"), t.get("volume_tag")
    if ms in ("BREAKOUT", "BREAKDOWN"):
        side = "LONG" if ms == "BREAKOUT" else "SHORT"
        want = "AGREE_UP" if side == "LONG" else "AGREE_DOWN"
        if agree == want and vol != "LOW":
            return _open(ctx, t, i, side, "%s: price left the squeeze, TSI and Z agree with the move, volume is %s." % (ms, vol or "not known"))
        return _out(t, "WAIT", side, "%s, but TSI and Z do not both agree, or volume is low." % ms, "TSI and Z both %s and volume not LOW" % want.replace("AGREE_", "").lower(), WAIT_BREAK, kind="SAME_SIDE")
    if ms in ("TRENDING_UP", "TRENDING_DOWN"):
        side = "LONG" if ms == "TRENDING_UP" else "SHORT"
        u, want = t.get("sd_units"), "AGREE_UP" if side == "LONG" else "AGREE_DOWN"
        near = u is not None and ((0 <= u <= 1.0) if side == "LONG" else (-1.0 <= u <= 0))
        if near and agree == want:
            return _open(ctx, t, i, side, "%s: price pulled back to the SD middle side (%.2f SD) and TSI and Z agree with the trend." % (ms, u))
        return _out(t, "WAIT", side, "%s, but this is not a pullback yet (price at %s SD, TSI/Z %s)." % (ms, u, (agree or "unknown").lower()),
                    "price back between the SD middle and 1 SD on the trend side, TSI and Z agreeing", WAIT_PULL, kind="SAME_SIDE")
    if ms == "CONSOLIDATION":
        return _out(t, "WAIT", side, "Squeeze: the SD bands are tight and the EMA50 is flat. No trade inside a squeeze.", "a close outside +1 / -1 SD with the SD width growing", WAIT_SQUEEZE, kind="ANY_SIDE")
    why = {"SIDEWAYS": "Sideways market. In the owner's own paper data this kind of market lost the most money.", "TRANSITION": "The market state is mixed (neither trend nor squeeze). No clear idea.",
           "PUMP": "Pump: the big move is already done. The Brain does not chase it.", "DUMP": "Dump: the big move is already done. The Brain does not chase it."}
    return _out(t, "SKIP", side, why.get(ms, "No rule for this market state."))


def main(argv=None):
    print(json.dumps({"version": VERSION, "brain_version": BT_VERSION, "definition": definition()}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
