"""brain_shadow.py - Batch 4d-1: SHADOW RECOMMENDATION RULE r1 (pure rule + evidence gate reader) and, since 4d-2, the LIVE shadow writer step().

Question: "for one Brain call on an open trade, what would the Brain have said - HOLD_OK, PROTECT_LOOKS_BETTER or NO_OPINION - using only evidence that
already existed BEFORE that candle?"   It never opens, closes, changes or rejects a trade, calls no API, reads no price feed, writes nothing.
B4d-2 step(): once per Brain cycle (called at the top of brain_learn.step) it asks the question for the newest closed candles of OPEN Dual trades and freezes each answer
  in brain_archive.db table shadow_rec (insert-only, key = trade + candle + rule version; NO_OPINION rows too). It reads dual_archive.db read-only and never touches a trade.
  Live only: a candle older than MAX_AGE_C candles, a row written more than LATE_LAG candles late, an exit row, a closed / skipped trade or an unknown row layout is never recorded.
  The scoring and the view come in later parts (not built).

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

import brain_learn as BL                      # only its row decoder and constants (no second copy of that logic); brain_learn imports this file lazily
import brain_stats as BS
import trade_archive as TA

RULE_VERSION = "r1"
EVIDENCE_VERSION = BS.STATS_VERSION          # the learn_stats copies of brain_stats (s1)
HINTS = ("EARLY HINT", "SUPPORTED")
RECS = ("HOLD_OK", "PROTECT_LOOKS_BETTER", "NO_OPINION")
MAX_AGE_C = 3                                 # B4d-2: a candle is recorded only while it is at most this many candles old (no back-fill after a stop)
_TF_MS = {"5m": 300000, "15m": 900000}


def load_gates(base=None, since=None):
    """Read-only. -> [(saved time s, finished trades, parsed copy)] oldest first. A copy that cannot be read is left out, never guessed.
    `since` (seconds) loads only what candles opened at/after it can need (same answers for them)."""
    out = []
    for t, n, js in TA.learn_snapshots(EVIDENCE_VERSION, base, since):
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


def score_recs(recs, calls):
    """PURE (B4d-3). recs = [(trade id, candle ms, rec)] (HOLD_OK / PROTECT_LOOKS_BETTER only), calls = brain_stats.load() dicts (finished trades only).
    ONE count per trade and rec type (its first recommendation). "If followed" = ROI points the trade gains by doing what the rec said instead of the other
    choice: HOLD_OK -> final - roi at the call (left), PROTECT -> roi - final (-left). Judged against the same stage baseline as brain_stats (excess), the same
    30-trade minimum, older/newer half and luck test (brain_stats._judge). dir: "right" (rec beat the baseline) or "wrong" -- only when the verdict is a hint.
    -> {rec: {n, pending, unjudged, if_followed, excess, halves, p, verdict, dir}}. Paper numbers only, nothing is traded."""
    idx = {(c["id"], c["t"]): c for c in calls}
    book = BS._Base(BS._first_per(calls, lambda c: BS._cell(c["n"], c["roi"])))
    pool = [c["left"] - b[0] for c in BS._first_per(calls, lambda c: BS._cell(c["n"], c["roi"])) for b in [book.at(c)] if b]
    out = {}
    for rec, sign in (("HOLD_OK", 1.0), ("PROTECT_LOOKS_BETTER", -1.0)):
        first = {}
        for tid, t, r in sorted(recs, key=lambda x: (x[1], x[0])):
            if r == rec:
                first.setdefault(tid, t)
        raw, ex, pending = [], [], 0
        for tid, t in sorted(first.items(), key=lambda x: x[1]):
            c = idx.get((tid, t))
            b = None if c is None else book.at(c)
            if c is None:
                pending += 1
            elif b:
                raw.append(sign * c["left"])
                ex.append(sign * (c["left"] - b[0]))
        n, h = len(ex), len(ex) // 2
        halves = [BS._r(BS._mean(ex[:h])), BS._r(BS._mean(ex[h:]))] if n >= 2 * BS.MIN_HALF else None
        m = BS._mean(ex)
        p = BS._r(BS._luck_p(pool, n, m), 3) if n >= BS.MIN_N else None
        v = BS._judge(n, halves, m, p)
        out[rec] = {"n": n, "pending": pending, "unjudged": len(first) - pending - n, "if_followed": BS._r(BS._mean(raw)), "excess": BS._r(m), "halves": halves,
                   "p": p, "verdict": v, "dir": None if v not in HINTS else ("right" if m > 0 else "wrong")}
    return out


def score(base=None):
    """Read-only. Scores the stored r1 recommendations against what really followed (call_out via brain_stats.load). Never raises."""
    try:
        calls, _info = BS.load(base)
        return {"rule": RULE_VERSION, "err": "", "score": score_recs(TA.shadow_recs(RULE_VERSION, base), calls)}
    except Exception as ex:
        return {"rule": RULE_VERSION, "score": {}, "err": "%s: %s" % (type(ex).__name__, str(ex)[:100])}


_C = {"t": 0.0, "key": None, "res": None, "base": None}          # B4d-4 cache, same pattern as brain_pattern / brain_stats


def summary(base=None, force=False):
    """B4d-4: the small block of the Brain view (key learn.shadow). Counts of what r1 said (HOLD_OK / PROTECT_LOOKS_BETTER / NO_OPINION, per candle row) and
    the paper score of the first two (score_recs). No raw rows. Recomputed at most every BS.REFRESH_S and only when the shadow rows or the call outcomes
    changed. Read-only, never raises. Paper numbers only: nothing here controls a trade."""
    now = time.time()
    try:
        same = _C["res"] is not None and _C["base"] == base
        if not force and same and now - _C["t"] < BS.REFRESH_S:
            return _C["res"]
        cnt = TA.shadow_counts(RULE_VERSION, base)
        key = (sum(cnt.values()), TA.learn_counts(BS.LEARN_VERSION, base)["outcomes"])
        if not force and same and key == _C["key"]:
            _C["t"] = now
            return _C["res"]
        sc = score(base)
        if sc["err"]:
            raise RuntimeError(sc["err"])
        seen = any(r["n"] >= BS.MIN_N for r in sc["score"].values())
        res = {"rule": RULE_VERSION, "status": "measuring" if seen else "collecting", "min_n": BS.MIN_N, "provisional": True, "err": "",
               "counts": {r: int(cnt.get(r, 0)) for r in RECS}, "score": sc["score"],
               "text": ("Shadow check: measuring. Paper numbers only, nothing here controls a trade." if seen else
                        "Shadow check: NOT ENOUGH DATA yet (a result needs %d judged trades). Paper numbers only." % BS.MIN_N)}
        json.dumps(res, allow_nan=False)                           # must be plain JSON for the app, else it is an error below
        _C.update(t=now, key=key, res=res, base=base)
        return res
    except Exception as ex:
        return {"rule": RULE_VERSION, "status": "error", "min_n": BS.MIN_N, "provisional": True, "counts": {}, "score": {},
                "err": "%s: %s" % (type(ex).__name__, str(ex)[:80]), "text": "Shadow check could not be measured. NOT ENOUGH DATA."}


def run(base=None, now_ms=None):
    """Hand run / tests: read-only. What r1 says for every state, in profit and not, from the latest copy before `now_ms`. Never raises."""
    try:
        gates = load_gates(base)
        t = time.time() * 1000.0 if now_ms is None else now_ms
        return {"copies": len(gates), "err": "", "rule": RULE_VERSION,
                "table": {s: {"in_profit": recommend(s, 1.0, t, gates)["rec"], "not_in_profit": recommend(s, -1.0, t, gates)["rec"]} for s in BS.STATES}}
    except Exception as ex:
        return {"copies": 0, "rule": RULE_VERSION, "table": {}, "err": "%s: %s" % (type(ex).__name__, str(ex)[:100])}


def _layout(con, ov):
    """The key list of an obs row layout (meta of dual_archive.db), or () when unknown / without roi."""
    try:
        m = con.execute("SELECT v FROM meta WHERE k = ?", ("obs_keys_%s" % ov,)).fetchone()
        keys = tuple(json.loads(m[0])) if m else (BL._KEYS if ov == BL._OV else ())
    except Exception:
        keys = ()
    return keys if "roi" in keys else ()


def _rows(con, now_ms):
    """Read-only. Open Dual trades -> [(id, candle open ms, call letter, roi, tf, side)] for their recent closed-candle (O) rows only."""
    if not {"trades", "obs"} <= {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}:
        return []
    out, lay = [], {}
    for tid, tf, side in con.execute("SELECT id, tf, side FROM trades WHERE status = 'open'").fetchall():
        raw = con.execute("SELECT t, k, n, tag, lag, f, v, bv FROM obs WHERE id = ? AND k = 'O' AND COALESCE(lag, 0) <= ? AND t >= ?",
                          (tid, BL.LATE_LAG, now_ms - (MAX_AGE_C + 1) * _TF_MS.get(tf, 300000))).fetchall()
        for ov in {r[6] for r in raw}:
            lay.setdefault(ov, _layout(con, ov))
            if lay[ov]:
                out += [(tid, d["t"], d["tag"], BL._num(d["roi"]), tf, side) for d in BL._decode([r for r in raw if r[6] == ov], lay[ov])[0] if d["tag"] in BS.STATES]
    return out


def step(base=None, now_ms=None):
    """B4d-2 live writer. Freezes r1's answer for the newest closed candles of open Dual trades. Idempotent (same candle = same row = ignored), never raises,
    changes no trade. -> {"seen": candles looked at, "err": text}."""
    out = {"seen": 0, "err": ""}
    try:
        con = TA.open_dual_ro(base)
        if con is None:
            return out
        try:
            rows = _rows(con, time.time() * 1000.0 if now_ms is None else now_ms)
        finally:
            con.close()
        out["seen"] = len(rows)
        if rows:
            gates, saved, recs = load_gates(base, since=min(r[1] for r in rows) / 1000.0), time.time(), []
            for tid, t, st, roi, tf, side in rows:
                r = recommend(st, roi, t, gates)
                recs.append((tid, t, RULE_VERSION, st, roi, tf, side, r["rec"], r["level"], r["lean"], r["why"], r["evidence"], r["snap_t"], r["snap_trades"], saved))
            if not TA.save_shadow_recs(recs, base):
                out["err"] = TA._S.get("arch_err") or "save failed"
    except Exception as e:
        out["err"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    return out


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))
