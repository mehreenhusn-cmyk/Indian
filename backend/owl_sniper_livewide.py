"""owl_sniper_livewide.py - OwlSniper LIVE 20-NUMBER SCORING (R3d). PAPER ONLY. PURE: no file write, no network, no order code. Does not change any indicator maths.
Why: the autopilot learns from 20 numbers (owl_sniper_feedall_feat.WIDE_FEATS), but a live card only carried the old 4. So LEARNED could never score a live signal.
What: the live scan (owl_sniper_live.scan_live) already holds the feature series S of the newest candle. wide_for_card() builds the SAME row the replay builds for old trades (owl_sniper_bridge_replay.make_row, no candle after the signal is read)
      and turns it into the same 20 numbers (wide_vec). verdict() lets the autopilot model (LEARNED state) say take / skip for one live card.
Honest: a card with a missing number gets 0.0 for it and the count is kept in card["wide_missing"] (never hidden). No model / no state / EXPLORE = verdict() returns None and the old rules stay.
API: wide_for_card(S, run, symbol, side, interval) -> {wide, missing, regime} | None ; verdict(d, card) -> {take, why, p} | None"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_bridge_replay as RP
import owl_sniper_ctx as CX
import owl_sniper_feedall_feat as W

VERSION = "owl_sniper_livewide 2 (R30)"


def wide_for_card(S, run, symbol, side, interval, con=None):
    """Live feature series S + its candles (open_ts, o, h, l, c, v) -> the 20 numbers of the newest candle. None when the row is not ready (warm-up) or anything is odd. Never raises."""
    try:
        i = S["n"] - 1
        rec = {"uid": "live-%s-%s" % (symbol, run[i][0]), "source": "live", "symbol": symbol, "tf": interval, "side": side, "entry_ts": run[i][0]}
        row = RP.make_row(rec, S, [c[5] for c in run[:i + 1]], i, 0.0)
        if row is None:
            return None
        row["btc"] = CX.live(con, interval, run[i][0])          # R30: BTC + session numbers of the signal candle (con = the live scan's read-only connection)
        wide, missing = W.wide_vec(row)
        return {"wide": wide, "missing": missing, "regime": row.get("regime")}
    except Exception:
        return None


def verdict(d, card):
    """LEARNED state only: the autopilot model scores the live card. -> {take, why, p} or None (= no opinion: not LEARNED, no model, or the card has no 20 numbers). Never raises."""
    try:
        import owl_sniper_autopilot as AP
        w = card.get("wide")
        st = AP.load(d)
        if not w or len(w) != len(W.WIDE_FEATS) or not st or st.get("state") != "LEARNED" or not st.get("model"):
            return None
        r = AP.decide(st, w)
        return {"take": bool(r["take"]), "why": r["why"], "p": r["p"]}
    except Exception:
        return None
