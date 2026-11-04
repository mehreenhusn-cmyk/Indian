"""owl_sniper_lessons.py - OwlSniper LESSONS MEMORY (R7). PAPER ONLY, READ ONLY: reads the long-term closed-trade archive (closed_trades_archive.jsonl) and writes ONE own file (v2_sniper_lessons.json). No network, no order code, no trade is changed.
Owner wish: "the Sniper must remember WHY a trade went wrong, and a repeated mistake must lower that setup's score; once a week it tells me what it learned in 3 lines."
Only the Sniper's OWN paper trades are read (source sniper / sniper_learn). 1R = the trade's own stop distance (leverage is forced to 1x, so the ROI% of a trade is its price move %).
EVERY closed trade gets ONE tag (first rule that fits):
  EXIT_ERROR     the trade reached +1R in its favour, then it ended at 0 or lower, or it kept less than half of its best gain  ("profit was given back")
  GOOD           profit, and it kept at least half of its best gain
  SIDEWAYS_LOSS  loss in a SIDEWAYS state and the trade never reached +0.5R  ("choppy time, no room")
  ENTRY_ERROR    loss and the trade never reached +0.3R  ("price went against it at once: bad entry")
  OTHER_LOSS     any other loss (it went a little our way, then failed)
A trade without a recorded best gain or stop distance gets UNKNOWN (counted, never guessed).
SETUP = regime | side. The last 20 trades of a setup: when more than half of them were mistakes (EXIT_ERROR / SIDEWAYS_LOSS / ENTRY_ERROR / OTHER_LOSS) and the setup has at least 5 trades, it gets a PENALTY = (mistake share - 0.5) x 0.6, so 0.30 at most. The penalty is ADVICE: score_penalty() answers it, nothing in the trader reads it yet.
WEEK: the last 7 days, the 3 mistake kinds that cost the most USDT, each as one plain sentence with the numbers. Fewer than 5 trades in the week = "not enough trades yet", no lesson is invented.
API: run(d, now=None, persist=False), load(d), save(d, st), score_penalty(d, regime, side), tag_trade(row). CLI: python3 backend/owl_sniper_lessons.py [--data DIR] [--save]"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_feed as F
import v2_pnl as P

VERSION = "owl_sniper_lessons 1 (R7)"
PAPER_ONLY = True
FILE = "v2_sniper_lessons.json"
OWN = ("sniper", "sniper_learn")
MAX_ROWS = 5000
MISTAKES = ("EXIT_ERROR", "SIDEWAYS_LOSS", "ENTRY_ERROR", "OTHER_LOSS")
KEEP_HALF, REACH_1R, REACH_HALF_R, REACH_03R = 0.5, 1.0, 0.5, 0.3
LAST_N, MIN_SETUP, MIN_WEEK = 20, 5, 5
WEEK_S = 7 * 86400
SAY = {"EXIT_ERROR": "%d trades reached +1R and then gave the profit back (cost %.2f USDT). Lesson: book part of the profit or move the stop up earlier.",
       "SIDEWAYS_LOSS": "%d trades lost in a sideways market that never gave room (cost %.2f USDT). Lesson: stay out when the market is choppy.",
       "ENTRY_ERROR": "%d trades went against the entry at once (cost %.2f USDT). Lesson: the entry was too early or on a fake signal; wait for the confirmation.",
       "OTHER_LOSS": "%d trades went a little our way and then failed (cost %.2f USDT). Lesson: check the exit and the stop of these trades."}


def _num(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def tag_trade(t):
    """One archive row of the Sniper -> (tag, info). Pure."""
    roi, pnl = _num(t.get("roi_pct")), _num(t.get("pnl_usdt"))
    entry = _num(t.get("entry_price"))
    stop = _num(t.get("signal_stop_loss")) or _num(t.get("sl_initial"))
    peak = _num(t.get("max_roi_pct"))
    if peak is None:
        peak = _num(t.get("peak_roi"))
    if roi is None or pnl is None or not entry or not stop or peak is None or entry <= 0:
        return "UNKNOWN", {}
    risk = abs(entry - stop) / entry * 100.0
    if risk <= 0:
        return "UNKNOWN", {}
    mfe_r, got_r = max(0.0, peak) / risk, roi / risk
    inv = _num(t.get("invest_usdt")) or 0.0
    info = {"mfe_r": round(mfe_r, 2), "result_r": round(got_r, 2), "left_usdt": round(max(0.0, peak - roi) * inv / 100.0, 4)}     # left_usdt = best gain minus what was kept
    kept = roi / peak if peak > 0 else 0.0
    if mfe_r >= REACH_1R and (roi <= 0 or kept < KEEP_HALF):
        return "EXIT_ERROR", info
    if pnl > 0:
        return "GOOD", info
    if str(t.get("sniper_regime") or "").upper() == "SIDEWAYS" and mfe_r < REACH_HALF_R:
        return "SIDEWAYS_LOSS", info
    if mfe_r < REACH_03R:
        return "ENTRY_ERROR", info
    return "OTHER_LOSS", info


def read_own(d):
    """The Sniper's own closed trades, oldest first. -> (rows, problem text or '')."""
    root = os.path.realpath(d)
    rows, st = P.read_jsonl(os.path.join(root, P.FILES[0][0]), [root])
    own = [t for t in rows[-MAX_ROWS:] if isinstance(t, dict) and str(t.get("source") or "").lower() in OWN]
    own.sort(key=lambda t: _num(t.get("closed_at_ts")) or 0.0)
    return own, str(st.get("status") or "")


def _setups(tagged):
    by = {}
    for t, tag, _i in tagged:
        k = "%s|%s" % (str(t.get("sniper_regime") or "?").upper(), "LONG" if str(t.get("action") or "").upper() == "BUY" else "SHORT")
        by.setdefault(k, []).append(tag)
    out = {}
    for k, tags in by.items():
        last = [x for x in tags[-LAST_N:] if x != "UNKNOWN"]
        bad = sum(1 for x in last if x in MISTAKES)
        share = bad / len(last) if last else 0.0
        pen = round((share - 0.5) * 0.6, 2) if len(last) >= MIN_SETUP and share > 0.5 else 0.0
        out[k] = {"n": len(tags), "last_n": len(last), "mistakes": bad, "mistake_share": round(share, 2), "penalty": pen}
    return out


def _week(tagged, now):
    wk = [(t, tag, i) for t, tag, i in tagged if (_num(t.get("closed_at_ts")) or 0) >= now - WEEK_S and tag != "UNKNOWN"]
    out = {"trades": len(wk), "good": sum(1 for _t, g, _i in wk if g == "GOOD"), "mistakes": sum(1 for _t, g, _i in wk if g in MISTAKES), "lessons": []}
    if len(wk) < MIN_WEEK:
        out["note"] = "Not enough Sniper trades this week: %d, %d needed. No lesson is made up." % (len(wk), MIN_WEEK)
        return out
    cost = {}
    for t, g, i in wk:
        if g in MISTAKES:
            c = cost.setdefault(g, [0, 0.0])
            c[0] += 1
            c[1] += (i.get("left_usdt") or 0.0) if g == "EXIT_ERROR" else max(0.0, -(_num(t.get("pnl_usdt")) or 0.0))     # exit error = the profit that was given back, the others = the loss
    for g, (n, usdt) in sorted(cost.items(), key=lambda kv: (-kv[1][1], -kv[1][0]))[:3]:
        out["lessons"].append({"tag": g, "n": n, "cost_usdt": round(usdt, 2), "text": SAY[g] % (n, usdt)})
    if not out["lessons"]:
        out["note"] = "No mistake this week."
    return out


def run(d, now=None, persist=False):
    """Archive -> tags -> counts, setup penalties, week lessons. Never raises."""
    now = time.time() if now is None else now
    st = {"version": VERSION, "paper_only": True, "advice_only": True, "state": "NO_TRADES_YET", "made": int(now), "reasons": [], "counts": {}, "setups": {}, "week": {}}
    try:
        rows, bad = read_own(d)
        if bad:
            st["reasons"].append("Trade archive problem: %s" % bad[:80])
        tagged = []
        for t in rows:
            tag, info = tag_trade(t)
            tagged.append((t, tag, info))
        st["trades"] = len(tagged)
        if not tagged:
            st["reasons"].append("The Sniper has no closed paper trade yet, so there is nothing to learn from.")
            return st
        st["state"] = "LEARNING"
        c = {}
        for _t, tag, _i in tagged:
            c[tag] = c.get(tag, 0) + 1
        st["counts"], st["setups"], st["week"] = c, _setups(tagged), _week(tagged, now)
        st["recent"] = [{"symbol": t.get("symbol"), "tag": tag, "closed": _num(t.get("closed_at_ts")), "pnl": _num(t.get("pnl_usdt")), **i} for t, tag, i in tagged[-8:]]
        if persist:
            save(d, st)
    except Exception as e:
        st["state"], st["reasons"] = "ERROR", ["lessons error: %s: %s" % (type(e).__name__, str(e)[:100])]
    return st


def load(d):
    return F.read_json(d, FILE)


def save(d, st):
    return F.write_json(d, FILE, st)


def score_penalty(d, regime, side):
    """0.0 .. 0.30 for a setup (regime, LONG / SHORT), 0.0 when unknown. ADVICE: no trader code reads it yet."""
    try:
        s = ((load(d) or {}).get("setups") or {}).get("%s|%s" % (str(regime or "?").upper(), str(side or "").upper()))
        return float(s["penalty"]) if s else 0.0
    except Exception:
        return 0.0


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper lessons memory (paper only, read only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.data, persist=a.save), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
