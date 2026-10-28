"""brain_shadow.py - Batch 4d-1: SHADOW RECOMMENDATION RULE r1 (pure rule + evidence gate reader; nothing stored, nothing connected, nothing decided).

Question: "for one Brain call on an open trade, what would the Brain have said - HOLD_OK, PROTECT_LOOKS_BETTER or NO_OPINION - using only evidence that
already existed BEFORE that candle?"   It never opens, closes, changes or rejects a trade, calls no API, reads no price feed, writes nothing.
This part only answers the question for ONE call. The live writer, the frozen table, the scoring and the view come in later parts (not built).

RULE r1 (locked; a change needs a new RULE_VERSION and old rows would stay as they are):
  evidence = the result of the call's state (S / T / W / R) in slice "all" inside the latest learn_stats copy (brain_stats, version s1) that was
             saved BEFORE the call's candle opened. Those copies are frozen (insert-only) and were made from trades that had finished before they were saved.
  HOLD_OK               evidence verdict is EARLY HINT or SUPPORTED and its lean is "hold"
  PROTECT_LOOKS_BETTER  evidence verdict is EARLY HINT or SUPPORTED, its lean is "exit_now" AND the trade is in profit now (roi > 0; nothing to protect otherwise)
  NO_OPINION            everything else (no copy yet, state not in the copy = under 30 trades, no clear pattern, wrong lean, not in profit, roi unknown)
  confidence            only the evidence level (EARLY HINT / SUPPORTED) is passed on. No percentage is made up.
Look-ahead: recommend() takes ONLY the call's state letter, its ROI at that candle and the candle's open time. A final result, MFE, later candles or
  later verdicts cannot reach it. A copy saved at or after the candle opened is never used (strictly before). Slices are not used in r1 (less room to fish).
Run by hand: cd backend && python3 brain_shadow.py      (shows what r1 says today for each state, in profit and not)
"""
import bisect
import json
import time

import brain_stats as BS
import trade_archive as TA

RULE_VERSION = "r1"
EVIDENCE_VERSION = BS.STATS_VERSION          # the learn_stats copies of brain_stats (s1)
HINTS = ("EARLY HINT", "SUPPORTED")
RECS = ("HOLD_OK", "PROTECT_LOOKS_BETTER", "NO_OPINION")


def load_gates(base=None):
    """Read-only. -> [(saved time s, finished trades, parsed copy)] oldest first. A copy that cannot be read is left out, never guessed."""
    out = []
    for t, n, js in TA.learn_snapshots(EVIDENCE_VERSION, base):
        try:
            g = json.loads(js)
            if isinstance(g, dict) and isinstance(g.get("res"), list):
                out.append((t, n, g))
        except Exception:
            continue
    return out


def gate_at(gates, t_ms):
    """PURE. The latest copy saved strictly BEFORE the candle that opened at t_ms (ms) -> (saved time, trades, copy) or None."""
    k = bisect.bisect_left([g[0] for g in gates], float(t_ms) / 1000.0) - 1
    return gates[k] if k >= 0 else None


def _out(rec, why, gate=None, level=None, lean=None):
    return {"rec": rec, "why": why, "level": level, "lean": lean, "rule": RULE_VERSION, "evidence": EVIDENCE_VERSION,
            "snap_t": None if gate is None else gate[0], "snap_trades": None if gate is None else gate[1],
            "text": "%s (shadow only, not advice): %s." % (rec.replace("_", " ").capitalize(), why)}


def decide(st, roi, gate):
    """PURE. Rule r1 for one call: state letter, ROI at that candle (None = unknown) and the gate copy (or None). -> dict (always the same keys)."""
    if gate is None:
        return _out("NO_OPINION", "no evidence copy existed yet")
    r = next((x for x in gate[2]["res"] if x.get("state") == st and x.get("slice") == "all"), None)
    if r is None:
        return _out("NO_OPINION", "this state had under %d trades in the evidence" % BS.MIN_N, gate)
    v, lean = r.get("verdict"), r.get("lean")
    if v not in HINTS:
        return _out("NO_OPINION", "evidence verdict is %s" % v, gate, v, lean)
    if lean == "hold":
        return _out("HOLD_OK", "earlier trades that got this call did better by holding (%s)" % v.lower(), gate, v, lean)
    if lean == "exit_now":
        if roi is not None and roi > 0:
            return _out("PROTECT_LOOKS_BETTER", "earlier trades that got this call did better by leaving, and this trade is in profit (%s)" % v.lower(), gate, v, lean)
        return _out("NO_OPINION", "leaving looked better in the evidence, but this trade is not in profit", gate, v, lean)
    return _out("NO_OPINION", "evidence has no lean", gate, v, lean)


def recommend(st, roi, t_ms, gates):
    """PURE. THE entry point: only the call's state, its ROI and its candle open time go in (nothing about how the trade ended can). -> decide() dict."""
    return decide(st, roi, gate_at(gates, t_ms))


def run(base=None, now_ms=None):
    """Hand run / tests: read-only. What r1 says for every state, in profit and not, from the latest copy before `now_ms`. Never raises."""
    try:
        gates = load_gates(base)
        t = time.time() * 1000.0 if now_ms is None else now_ms
        return {"copies": len(gates), "err": "", "rule": RULE_VERSION,
                "table": {s: {"in_profit": recommend(s, 1.0, t, gates)["rec"], "not_in_profit": recommend(s, -1.0, t, gates)["rec"]} for s in BS.STATES}}
    except Exception as ex:
        return {"copies": 0, "rule": RULE_VERSION, "table": {}, "err": "%s: %s" % (type(ex).__name__, str(ex)[:100])}


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))
