"""brain_stats.py - Batch 4b-2a: WHAT HAPPENED AFTER EACH BRAIN STATE (measurement only, no advice, nothing is decided).

Reads the facts of B4b-1 (tables journey + call_out of brain_archive.db, opened READ-ONLY) and answers, per provisional state letter
(S strong, T stable, W weakening, R reversed):  "after the Brain said this, was holding better or worse than leaving right then, compared with
what usually happens at the same stage of a trade?"   It never opens, closes, changes or rejects a trade, calls no API, reads no price feed.

How one number is made (all ROI points = % of margin, NET, fee in):
  left   = final result - ROI at the call = what the rest of the trade added (+) or took (-) compared with leaving right there.
  avail  = best ROI later - ROI at the call (never below 0) = profit that was still on the table.
  back   = best ROI from here on (or the ROI now) - final result = profit given back after the call.
  one observation = the FIRST call of a state inside a trade (a long trade must not count as many pieces of evidence: trades are counted, not candles).
  baseline = average `left` of OTHER finished trades at the same stage: same candle count and same ROI band (first call of the trade in that
             cell, ANY state). If that cell has too few earlier trades: same age bucket + ROI band, then all stages together. The cells are only
             there to make the comparison fair, they are not trading rules. excess = left - baseline.
             Why exact candle count first: with coarse buckets a state that mostly happens late in a bucket looks like an effect when the trade
             simply drifts with time (test_brain_stats.py plants such a drift; the coarse version called luck SUPPORTED in 1 of 5 states).
WALK-FORWARD (one rule): an observation is compared only with trades whose exit candle had already CLOSED before the candle of the call.
  A trade's later result can never change the baseline that older observations were judged with (test_brain_stats.py poisons the future to prove it).
  Observations without enough earlier trades in their cell (MIN_CELL) are not judged yet; they are counted in `unjudged`.
SMALL SAMPLES: fewer than MIN_N judged trades = "NOT ENOUGH DATA". Small groups are also pulled toward 0 (shrunk = sum / (n + PRIOR_K)).
  A hint needs the OLDER half and the NEWER half to point the same way and a luck test (random draws of the same size from all judged
  observations) to say p <= P_HINT. SUPPORTED additionally needs FULL_N judged trades and p <= P_OK.
  Caution (also in the text): trades opened in the same market move are not independent, so even SUPPORTED is a strong hint, not a proof; B4c tests it again.
Quality filter: journeys flagged late / layout / bad_rows / net_diff are left out (their first call is not the real first call, or the numbers disagree).
Run by hand: cd backend && python3 brain_stats.py
"""
import bisect
import json
import random
import sys

import trade_archive as TA

STATS_VERSION = "s1"
LEARN_VERSION = "j1"                  # the journey layout this reads (brain_learn.LEARN_VERSION)
STATES = ("S", "T", "W", "R")
NAMES = {"S": "STRONG", "T": "STABLE", "W": "WEAKENING", "R": "REVERSED"}
MIN_N = 30                            # judged trades a state needs before it is more than NOT ENOUGH DATA (same as the edge scorecard)
FULL_N = 100                          # judged trades needed for SUPPORTED (same as the trust meter)
PRIOR_K = 20                          # shrink strength: 20 imaginary average trades are added
MIN_CELL = 10                         # earlier trades a cell needs before it is the baseline (else the next coarser cell, else not judged)
MIN_HALF = 10                         # judged trades each half needs before the older / newer check counts
P_HINT, P_OK = 0.20, 0.05
RUNS = 500                            # random draws in the luck test
AGE_MAX = 12                          # fine cell: the exact candle count 1..11, and 12+ together   (fairness cells only)
AGE_EDGES = (3, 6, 12)                # coarse cell: 1-2, 3-5, 6-11, 12+   (used only when the fine cell has too few earlier trades)
ROI_EDGES = (-5.0, 0.0, 5.0, 15.0)    # ROI points at the call: below -5, -5..0, 0..5, 5..15, 15+   (fairness cells only)
BAD_FLAGS = ("late", "layout", "bad_rows", "net_diff")


def _tf_ms(tf):
    try:
        t = str(tf)
        return int(t[:-1]) * {"m": 60000, "h": 3600000, "d": 86400000}[t[-1]]
    except Exception:
        return 0


def _cell(n, roi):
    return min(int(n), AGE_MAX), bisect.bisect_right(ROI_EDGES, roi)


def _cell2(n, roi):
    return "c", bisect.bisect_right(AGE_EDGES, n), bisect.bisect_right(ROI_EDGES, roi)


def load(base=None, v=LEARN_VERSION):
    """-> (calls, info). calls = dicts {id, t, n, st, roi, fin, mx, mn, left, d, tf, sym, xc}; xc = close time (ms) of the trade's exit candle.
    Reads only. A missing archive gives no calls. Raises on a real problem (the caller reports it)."""
    info = {"trades": 0, "left_out": 0}
    con = TA.open_brain_ro(base)
    if con is None:
        return [], info
    try:
        qs = ("SELECT c.id, c.t, c.n, c.st, c.roi, c.fin, c.max_after, c.min_after, c.bars_left, j.d, j.tf, j.sym, j.flags "
              "FROM call_out c JOIN journey j ON j.id = c.id AND j.v = c.v WHERE c.v = ? ORDER BY c.id, c.t")
        out, seen = [], set()
        for tid, t, n, st, roi, fin, mx, mn, bl, d, tf, sym, flags in con.execute(qs, (v,)):
            if any(b in (flags or "") for b in BAD_FLAGS) or None in (t, n, st, roi, fin, mx, mn, bl):
                info["left_out"] += 1
                continue
            ms = _tf_ms(tf)
            if not ms:
                info["left_out"] += 1
                continue
            seen.add(tid)
            out.append({"id": tid, "t": int(t), "n": int(n), "st": st, "roi": float(roi), "fin": float(fin), "mx": float(mx), "mn": float(mn),
                        "left": float(fin) - float(roi), "d": d, "tf": tf, "sym": sym, "xc": int(t) + int(bl) * ms + ms})
        info["trades"] = len(seen)
        return out, info
    finally:
        con.close()


def _first_per(calls, key):
    """First call of every trade for every key(call) value -> list of calls (calls must be oldest first inside a trade)."""
    seen, out = set(), []
    for c in sorted(calls, key=lambda c: (c["id"], c["t"])):
        k = (c["id"], key(c))
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


class _Base:
    """Baseline book. Three levels, finest first: same candle count + ROI band, same age bucket + ROI band, all stages. Each level keeps the finished
    trades' `left` sorted by the time their exit candle closed, with running sums. Every level has its own 'first call of a trade in a cell' list."""

    def __init__(self, fine_obs, coarse_obs=None):
        coarse_obs = fine_obs if coarse_obs is None else coarse_obs
        self.fine, self.coarse, self.allc = {}, {}, ([], [0.0])
        for obs, book, cell in ((fine_obs, self.fine, _cell), (coarse_obs, self.coarse, _cell2)):
            for c in sorted(obs, key=lambda c: c["xc"]):
                for xs, cum in (book.setdefault(cell(c["n"], c["roi"]), ([], [0.0])), ) + ((self.allc,) if book is self.coarse else ()):
                    xs.append(c["xc"])
                    cum.append(cum[-1] + c["left"])

    def at(self, c):
        """Baseline for call c from trades that finished BEFORE c's candle opened. -> (mean, how many) or None when not enough earlier trades."""
        for xs, cum in (self.fine.get(_cell(c["n"], c["roi"]), ([], [0.0])), self.coarse.get(_cell2(c["n"], c["roi"]), ([], [0.0])), self.allc):
            k = bisect.bisect_right(xs, c["t"])               # exit candle closed at or before the call candle opened
            if k >= MIN_CELL:
                return cum[k] / k, k
        return None


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _r(x, nd=1):
    return None if x is None else round(float(x), nd)


def _luck_p(pool, n, obs_mean, runs=RUNS):
    """Two-sided: how often do n random judged observations average at least as far from 0 as this state?"""
    if n < 1 or len(pool) < n:
        return None
    rnd = random.Random(7)
    hit = sum(1 for _ in range(runs) if abs(sum(rnd.sample(pool, n)) / n) >= abs(obs_mean) - 1e-12)
    return (hit + 1.0) / (runs + 1.0)


def judged(calls, state, book=None):
    """PURE. The first call of `state` in each trade, judged against the baseline of trades that had finished before it.
    -> ([(call, excess, baseline)] oldest first, how many observations there were in all). Calls without a baseline yet are not in the list."""
    if book is None:
        book = _Base(_first_per(calls, lambda c: _cell(c["n"], c["roi"])), _first_per(calls, lambda c: _cell2(c["n"], c["roi"])))
    obs = sorted((c for c in _first_per(calls, lambda c: c["st"]) if c["st"] == state), key=lambda c: c["t"])
    rows = []
    for c in obs:
        b = book.at(c)
        if b:
            rows.append((c, c["left"] - b[0], b[0]))
    return rows, len(obs)


def compute(calls, keep=None):
    """PURE. calls from load(). keep = optional filter on one call (for slices). -> {"states": {letter: result}, "trades": n, "judged_calls": n, ...}
    result keys: n (judged trades), unjudged, left (mean), base (mean baseline), excess (mean left - baseline), shrunk, avail, back, win,
    halves [older, newer] mean excess, p, verdict, lean ('hold' / 'exit_now' / None), text."""
    calls = [c for c in calls if keep is None or keep(c)]
    fine = _first_per(calls, lambda c: _cell(c["n"], c["roi"]))
    book = _Base(fine, _first_per(calls, lambda c: _cell2(c["n"], c["roi"])))
    judged_pool = []
    for c in fine:
        b = book.at(c)
        if b:
            judged_pool.append(c["left"] - b[0])
    res = {}
    for s in STATES:
        rows, obs_n = judged(calls, s, book)
        obs = range(obs_n)
        n = len(rows)
        r = {"state": s, "name": NAMES[s], "n": n, "unjudged": len(obs) - n, "left": None, "base": None, "excess": None, "shrunk": None,
             "avail": None, "back": None, "win": None, "halves": None, "p": None, "lean": None}
        if n:
            ex = [e for _c, e, _b in rows]
            r.update(left=_r(_mean([c["left"] for c, _e, _b in rows])), base=_r(_mean([b for _c, _e, b in rows])), excess=_r(_mean(ex)),
                     shrunk=_r(sum(ex) / (n + PRIOR_K)), avail=_r(_mean([max(0.0, c["mx"] - c["roi"]) for c, _e, _b in rows])),
                     back=_r(_mean([max(c["mx"], c["roi"]) - c["fin"] for c, _e, _b in rows])),
                     win=int(round(100.0 * sum(1 for c, _e, _b in rows if c["fin"] > 0) / n)))
        if n >= 2 * MIN_HALF:
            h = n // 2
            r["halves"] = [_r(_mean(ex[:h])), _r(_mean(ex[h:]))]
        if n >= MIN_N:
            r["p"] = _r(_luck_p(judged_pool, n, _mean(ex)), 3)
        agree = bool(r["halves"]) and r["halves"][0] * r["halves"][1] > 0 and (r["halves"][0] > 0) == (r["excess"] > 0)
        if n < MIN_N:
            r["verdict"] = "NOT ENOUGH DATA"
        elif not agree or r["p"] is None or r["p"] > P_HINT:
            r["verdict"] = "NO CLEAR PATTERN"
        elif n < FULL_N or r["p"] > P_OK:
            r["verdict"] = "EARLY HINT"
        else:
            r["verdict"] = "SUPPORTED"
        if r["verdict"] in ("EARLY HINT", "SUPPORTED") and r["excess"]:
            r["lean"] = "hold" if r["excess"] > 0 else "exit_now"
        r["text"] = _text(r)
        res[s] = r
    return {"version": STATS_VERSION, "states": res, "trades": len({c["id"] for c in calls}), "judged_calls": len(judged_pool),
            "provisional": True}


def _text(r):
    if r["verdict"] == "NOT ENOUGH DATA":
        return "%s: NOT ENOUGH DATA (%d of %d trades judged)." % (r["name"], r["n"], MIN_N)
    way = "better" if r["excess"] > 0 else "worse"
    base = "%s: %d trades. After this call, holding ended %.1f points %s than leaving right then, %.1f %s than usual at the same stage." % (
        r["name"], r["n"], abs(r["left"]), "better" if r["left"] > 0 else "worse", abs(r["excess"]), way)
    if r["verdict"] == "NO CLEAR PATTERN":
        return base + " No clear pattern: it could be luck, or older and newer trades disagree."
    if r["verdict"] == "EARLY HINT":
        return base + " Early hint only, not advice."
    return base + " Supported by the numbers so far, but trades in the same market move are not independent. Not advice yet."


def run(base=None):
    """load + compute on the archive. Never raises. -> result dict (with `err` when something went wrong)."""
    try:
        calls, info = load(base)
        out = compute(calls)
        out.update(left_out=info["left_out"], err="")
        return out
    except Exception as ex:
        return {"version": STATS_VERSION, "states": {}, "trades": 0, "judged_calls": 0, "provisional": True,
                "err": "%s: %s" % (type(ex).__name__, str(ex)[:100])}


if __name__ == "__main__":
    o = run()
    print(json.dumps({k: v for k, v in o.items() if k != "states"}, indent=1))
    for s in STATES:
        if s in o.get("states", {}):
            print(o["states"][s]["text"])
