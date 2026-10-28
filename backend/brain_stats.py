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
             cell, ANY state). The cells are only there to make the comparison fair, they are not trading rules. excess = left - baseline.
             NO coarser fallback: a call whose cell has fewer than MIN_CELL earlier trades is not judged yet. Coarser cells (age buckets, or all
             stages together) mix different stages, and a state that mostly happens late in a bucket then looks like an effect when the trade simply
             drifts with time: the first version did that (luck called SUPPORTED in 13 of 64 states), then the coarse fallback of the second version
             still gave 9 false early hints in 220 results of thin slices. Exact cells give 0 (test_brain_stats.py keeps that drift).
WALK-FORWARD (one rule): an observation is compared only with trades whose exit candle had already CLOSED before the candle of the call.
  A trade's later result can never change the baseline that older observations were judged with (test_brain_stats.py poisons the future to prove it).
  Observations without enough earlier trades in their cell (MIN_CELL) are not judged yet; they are counted in `unjudged`.
SMALL SAMPLES: fewer than MIN_N judged trades = "NOT ENOUGH DATA". Small groups are also pulled toward 0 (shrunk = sum / (n + PRIOR_K)).
  A hint needs the OLDER half and the NEWER half to point the same way and a luck test (random draws of the same size from all judged
  observations) to say p <= P_HINT. SUPPORTED additionally needs FULL_N judged trades and p <= P_OK.
  Caution (also in the text): trades opened in the same market move are not independent, so even SUPPORTED is a strong hint, not a proof; B4c tests it again.
Quality filter: journeys flagged late / layout / bad_rows / net_diff are left out (their first call is not the real first call, or the numbers disagree).

B4b-2b adds (still measurement only):
  SLICES   the same numbers for BUY / SELL, each timeframe, each regime (trending / mixed / sideways = the main-chart sideways % at the call candle,
           read read-only from the B4a obs rows; same 34 / 67 edges as tag_lab's words) and every BUY/SELL x timeframe x regime combination.
           Each slice has its own baseline. Because many slices are checked at once, luck gets less forgiving: the luck-test p is multiplied by the
           number of (slice, state) results that had enough data in this run (p_adj), so one lucky slice cannot pass.
  LEDGER   one frozen row per mistake (table `mistake`, INSERT OR IGNORE): STRONG / STABLE but the trade lost; WEAKENING / REVERSED but the trade
           still ended in profit and holding beat leaving. Counts are facts; "more mistakes than usual" gets a verdict only by the same rules
           (30 trades, older / newer half, luck test against the usual rate), so one bad week is not a lesson.
  SUMMARY  summary() is what the Brain view (key `learn`) shows. refresh() recomputes at most every REFRESH_S and only when journeys changed,
           adds new mistakes and, every SNAP_EVERY finished trades, one frozen copy of the numbers (table `learn_stats`). Nothing is ever rewritten.
Run by hand: cd backend && python3 brain_stats.py
"""
import bisect
import json
import random
import sys
import time

import trade_archive as TA

STATS_VERSION = "s1"
LEARN_VERSION = "j1"                  # the journey layout this reads (brain_learn.LEARN_VERSION)
STATES = ("S", "T", "W", "R")
NAMES = {"S": "STRONG", "T": "STABLE", "W": "WEAKENING", "R": "REVERSED"}
MIN_N = 30                            # judged trades a state needs before it is more than NOT ENOUGH DATA (same as the edge scorecard)
FULL_N = 100                          # judged trades needed for SUPPORTED (same as the trust meter)
PRIOR_K = 20                          # shrink strength: 20 imaginary average trades are added
MIN_CELL = 10                         # earlier trades a cell needs before it is the baseline (else the call is not judged yet)
MIN_HALF = 10                         # judged trades each half needs before the older / newer check counts
P_HINT, P_OK = 0.20, 0.05
RUNS = 500                            # random draws in the luck test
AGE_MAX = 12                          # cell = the exact candle count 1..11 (12+ together) x the ROI band   (fairness cells only)
ROI_EDGES = (-5.0, 0.0, 5.0, 15.0)    # ROI points at the call: below -5, -5..0, 0..5, 5..15, 15+   (fairness cells only)
BAD_FLAGS = ("late", "layout", "bad_rows", "net_diff")
REG_EDGES = (34, 67)                  # sideways % of the main chart: below 34 trending, 34-66 mixed, 67+ sideways (same words as tag_lab)
REG_NAMES = ("trending", "mixed", "sideways")
REFRESH_S = 600                       # the heavy recompute runs at most this often (seconds)
SNAP_EVERY = 10                       # one frozen copy of the numbers per this many new finished trades
_C = {"t": 0.0, "key": None, "res": None, "err": "", "base": None}


def _tf_ms(tf):
    try:
        t = str(tf)
        return int(t[:-1]) * {"m": 60000, "h": 3600000, "d": 86400000}[t[-1]]
    except Exception:
        return 0


def _cell(n, roi):
    return min(int(n), AGE_MAX), bisect.bisect_right(ROI_EDGES, roi)


def load(base=None, v=LEARN_VERSION):
    """-> (calls, info). calls = dicts {id, t, n, st, roi, fin, mx, mn, left, d, tf, sym, xc}; xc = close time (ms) of the trade's exit candle.
    Reads only. A missing archive gives no calls. Raises on a real problem (the caller reports it)."""
    info = {"trades": 0, "left_out": 0, "no_regime": 0}
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
    finally:
        con.close()
    sm = _regimes(base, seen)
    for c in out:
        c["sm"] = sm.get((c["id"], c["t"]))
        c["reg"] = None if c["sm"] is None else bisect.bisect_right(REG_EDGES, c["sm"])
        info["no_regime"] += c["reg"] is None
    return out, info


def features(base, ids, keys):
    """{(trade id, call candle time): [value of each key in `keys`, None when missing]} from the B4a obs rows (kind O) of those trades.
    Read-only, optional: a missing obs table, key or row gives {} / None, never a guess. Used for the regime here and by brain_look (B4c-1)."""
    out, ids = {}, list(ids)
    try:
        con = TA.open_dual_ro(base)
        if con is None or not ids:
            return out
        try:
            lay = {}
            for i in range(0, len(ids), 400):
                part = ids[i:i + 400]
                for tid, t, v, f in con.execute("SELECT id, t, v, f FROM obs WHERE k = 'O' AND id IN (%s)" % ",".join("?" * len(part)), part):
                    if v not in lay:
                        m = con.execute("SELECT v FROM meta WHERE k = ?", ("obs_keys_%s" % v,)).fetchone()
                        have = json.loads(m[0]) if m else []
                        lay[v] = [have.index(k) if k in have else None for k in keys]
                    try:
                        row = json.loads(f)
                        vals = [None if i is None or row[i] is None else float(row[i]) for i in lay[v]]
                    except Exception:
                        vals = [None] * len(keys)
                    if any(x is not None for x in vals):
                        out[(tid, int(t))] = vals
        finally:
            con.close()
    except Exception:
        return {}
    return out


def _regimes(base, ids):
    """{(trade id, call candle time): main sideways %} (the `sm` number of features())."""
    return {k: v[0] for k, v in features(base, ids, ("sm",)).items() if v[0] is not None}


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
    """Baseline book: for each cell (exact candle count + ROI band) the finished trades' `left`, sorted by the time their exit candle closed, with
    running sums. There is NO coarser fallback: a call whose cell has fewer than MIN_CELL earlier trades is simply not judged yet (a coarser cell
    mixes different stages and made luck look like an effect, see the module text)."""

    def __init__(self, fine_obs):
        self.fine = {}
        for c in sorted(fine_obs, key=lambda c: c["xc"]):
            xs, cum = self.fine.setdefault(_cell(c["n"], c["roi"]), ([], [0.0]))
            xs.append(c["xc"])
            cum.append(cum[-1] + c["left"])

    def at(self, c):
        """Baseline for call c from trades that finished BEFORE c's candle opened. -> (mean, how many) or None when its cell has too few earlier trades."""
        xs, cum = self.fine.get(_cell(c["n"], c["roi"]), ([], [0.0]))
        k = bisect.bisect_right(xs, c["t"])                   # exit candle closed at or before the call candle opened
        return (cum[k] / k, k) if k >= MIN_CELL else None


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
        book = _Base(_first_per(calls, lambda c: _cell(c["n"], c["roi"])))
    obs = sorted((c for c in _first_per(calls, lambda c: c["st"]) if c["st"] == state), key=lambda c: c["t"])
    rows = []
    for c in obs:
        b = book.at(c)
        if b:
            rows.append((c, c["left"] - b[0], b[0]))
    return rows, len(obs)


def _judge(n, halves, mean, p, ptests=1):
    """The ONE verdict rule (stats and ledger): NOT ENOUGH DATA under MIN_N; NO CLEAR PATTERN unless the older and newer half point the same
    way and the luck-test p (times the number of things tested at once) is small; EARLY HINT; SUPPORTED needs FULL_N trades and a small p."""
    if n < MIN_N:
        return "NOT ENOUGH DATA"
    pa = None if p is None else min(1.0, p * max(1, ptests))
    agree = bool(halves) and halves[0] * halves[1] > 0 and (halves[0] > 0) == (mean > 0)
    if not agree or pa is None or pa > P_HINT:
        return "NO CLEAR PATTERN"
    return "EARLY HINT" if n < FULL_N or pa > P_OK else "SUPPORTED"


def _finish(r, ptests=1):
    """Fill verdict, lean and text of one result r (a state of one slice) for `ptests` things tested at once."""
    r["tests"] = ptests
    r["p_adj"] = None if r["p"] is None else _r(min(1.0, r["p"] * max(1, ptests)), 3)
    r["verdict"] = _judge(r["n"], r["halves"], r["excess"], r["p"], ptests)
    r["lean"] = None
    if r["verdict"] in ("EARLY HINT", "SUPPORTED") and r["excess"]:
        r["lean"] = "hold" if r["excess"] > 0 else "exit_now"
    r["text"] = _text(r)


def compute(calls, keep=None):
    """PURE. calls from load(). keep = optional filter on one call (for slices). -> {"states": {letter: result}, "trades": n, "judged_calls": n, ...}
    result keys: n (judged trades), unjudged, left (mean), base (mean baseline), excess (mean left - baseline), shrunk, avail, back, win,
    halves [older, newer] mean excess, p, verdict, lean ('hold' / 'exit_now' / None), text."""
    calls = [c for c in calls if keep is None or keep(c)]
    fine = _first_per(calls, lambda c: _cell(c["n"], c["roi"]))
    book = _Base(fine)
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
        _finish(r, 1)
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
    strict = " (strict luck test: %d results were checked at once)" % r["tests"] if r.get("tests", 1) > 1 else ""
    if r["verdict"] == "EARLY HINT":
        return base + " Early hint only, not advice" + strict + "."
    return base + " Supported by the numbers so far, but trades in the same market move are not independent. Not advice yet" + strict + "."


def _groups(calls):
    """(name, kind, filter) for: all, BUY, SELL, each timeframe, each regime, and every BUY/SELL x timeframe x regime combination."""
    tfs = sorted({c["tf"] for c in calls})
    sides = ((1, "BUY"), (-1, "SELL"))
    g = [("all", "all", lambda c: True)]
    g += [("side:" + nm, "side", lambda c, d=d: c["d"] == d) for d, nm in sides]
    g += [("tf:" + tf, "tf", lambda c, tf=tf: c["tf"] == tf) for tf in tfs]
    g += [("regime:" + REG_NAMES[i], "regime", lambda c, i=i: c["reg"] == i) for i in range(len(REG_NAMES))]
    g += [("%s %s %s" % (nm, tf, REG_NAMES[i]), "cross", lambda c, d=d, tf=tf, i=i: c["d"] == d and c["tf"] == tf and c["reg"] == i)
          for d, nm in sides for tf in tfs for i in range(len(REG_NAMES))]
    return g


# One mistake kind per state: (kind, plain words, did the trade's result contradict the call?). Outcome facts only, no trading rule.
KINDS = {"S": ("S_lost", "STRONG but the trade lost", lambda c: c["fin"] < 0),
         "T": ("T_lost", "STABLE but the trade lost", lambda c: c["fin"] < 0),
         "W": ("W_ran", "WEAKENING but the trade ended in profit and holding beat leaving", lambda c: c["left"] > 0 and c["fin"] > 0),
         "R": ("R_ran", "REVERSED but the trade recovered, ended in profit and holding beat leaving", lambda c: c["left"] > 0 and c["fin"] > 0)}


def ledger(calls):
    """PURE. The mistakes ledger over all calls. -> (per state [{state, kind, label, n, mistakes, rate, usual, diff, halves, p, p_adj, verdict, text}],
    [frozen mistake rows as dicts]). rate / usual are % of trades; usual = the same outcome among all first calls per cell of trades that were there
    before (every judged observation) - a plain reference, the verdict still needs 30 trades, agreeing halves and the luck test."""
    fine = _first_per(calls, lambda c: _cell(c["n"], c["roi"]))
    book = _Base(fine)
    out, rows = [], []
    for s in STATES:
        kind, label, hit = KINDS[s]
        obs = sorted((c for c in _first_per(calls, lambda c: c["st"]) if c["st"] == s), key=lambda c: c["t"])
        ex = {c["id"]: e for c, e, _b in judged(calls, s, book)[0]}
        usual = _mean([1.0 if hit(c) else 0.0 for c in fine])
        n, m = len(obs), sum(1 for c in obs if hit(c))
        rate = m / n if n else None
        r = {"state": s, "kind": kind, "label": label, "n": n, "mistakes": m, "rate": None if rate is None else int(round(100 * rate)),
             "usual": None if usual is None else int(round(100 * usual)), "diff": None, "halves": None, "p": None}
        if n and usual is not None:
            hs = [1.0 if hit(c) else 0.0 for c in obs]
            r["diff"] = _r(100 * (rate - usual))
            if n >= 2 * MIN_HALF:
                r["halves"] = [_r(100 * (_mean(hs[:n // 2]) - usual)), _r(100 * (_mean(hs[n // 2:]) - usual))]
            if n >= MIN_N:
                r["p"] = _r(_luck_p([(1.0 if hit(c) else 0.0) - usual for c in fine], n, rate - usual), 3)
        out.append(r)
        rows += [{"id": c["id"], "st": s, "kind": kind, "v": STATS_VERSION, "t": c["t"], "n": c["n"], "roi": _r(c["roi"]), "fin": _r(c["fin"], 2),
                  "mx": _r(c["mx"]), "mn": _r(c["mn"]), "tf": c["tf"], "d": c["d"], "reg": c.get("reg"), "excess": _r(ex.get(c["id"]), 2)}
                 for c in obs if hit(c)]
    k = max(1, sum(1 for r in out if r["n"] >= MIN_N))
    for r in out:
        r["p_adj"] = None if r["p"] is None else _r(min(1.0, r["p"] * k), 3)
        r["verdict"] = _judge(r["n"], r["halves"], r["diff"], r["p"], k)
        r["text"] = _ltext(r)
    return out, rows


def _ltext(r):
    if r["verdict"] == "NOT ENOUGH DATA":
        return "%s: %d of %d trades. NOT ENOUGH DATA (need %d)." % (r["label"], r["mistakes"], r["n"], MIN_N)
    base = "%s: %d of %d trades (%d%%), usual %d%%." % (r["label"], r["mistakes"], r["n"], r["rate"], r["usual"])
    if r["verdict"] == "NO CLEAR PATTERN":
        return base + " No clear pattern: it could be luck, or older and newer trades disagree."
    return base + (" More" if r["diff"] > 0 else " Fewer") + " than usual (%s). Not advice yet." % r["verdict"].lower()


def analyze(calls):
    """PURE. Everything B4b-2b measures from the calls of load(): {version, trades, judged_calls, tests, slices: [{slice, kind, trades, states}], ledger, mistakes}."""
    sl = []
    for name, kind, keep in _groups(calls):
        sub = [c for c in calls if keep(c)]
        if sub or name == "all":
            r = compute(sub)
            sl.append({"slice": name, "kind": kind, "trades": r["trades"], "judged_calls": r["judged_calls"], "states": r["states"]})
    k_all = max(1, sum(1 for r in sl[0]["states"].values() if r["n"] >= MIN_N))
    k_sl = max(1, sum(1 for g in sl[1:] for r in g["states"].values() if r["n"] >= MIN_N))
    for g in sl:
        for r in g["states"].values():                         # many slices at once: the luck test gets stricter (p times the number of results)
            _finish(r, k_all if g["slice"] == "all" else k_sl)
            if g["slice"] != "all":
                r["text"] = g["slice"] + " - " + r["text"]
    led, rows = ledger(calls)
    return {"version": STATS_VERSION, "trades": sl[0]["trades"], "judged_calls": sl[0]["judged_calls"], "tests": k_sl, "slices": sl, "ledger": led,
            "mistakes": rows, "provisional": True}


def _snapshot(res):
    """The compact copy that is stored forever: only results with enough data, only the numbers."""
    keep = ("state", "n", "excess", "shrunk", "p", "p_adj", "verdict", "lean", "halves")
    return json.dumps({"v": res["version"], "trades": res["trades"], "tests": res["tests"],
                       "res": [dict({k: r[k] for k in keep}, slice=g["slice"]) for g in res["slices"] for r in g["states"].values() if r["n"] >= MIN_N],
                       "ledger": [{k: r[k] for k in ("kind", "n", "mistakes", "rate", "usual", "diff", "p_adj", "verdict")} for r in res["ledger"]]},
                      separators=(",", ":"))


def refresh(base=None, force=False):
    """Recompute everything when the journeys changed (at most every REFRESH_S), add NEW mistakes to the ledger and, every SNAP_EVERY finished
    trades, one frozen copy of the numbers. Reads dual_archive.db / brain_archive.db read-only, writes only brain_archive.db (mistake, learn_stats,
    insert-only). Never raises. -> the analysis dict, or None when it could not be made (see _C["err"])."""
    now = time.time()
    try:
        same = _C["res"] is not None and _C["base"] == base            # the cache belongs to ONE archive folder
        if not force and same and now - _C["t"] < REFRESH_S:
            return _C["res"]
        c = TA.learn_counts(LEARN_VERSION, base)
        key = (c["journeys"], c["outcomes"])
        if not force and same and key == _C["key"]:
            _C["t"] = now
            return _C["res"]
        calls, info = load(base)
        res = analyze(calls)
        res["left_out"], res["no_regime"] = info["left_out"], info["no_regime"]
        if res["mistakes"]:
            TA.save_mistakes([tuple(now if k == "saved" else m[k] for k in TA.MCOLS) for m in res["mistakes"]], base)
        if res["trades"]:
            TA.save_stats_snapshot(STATS_VERSION, res["trades"], _snapshot(res), SNAP_EVERY, base)
        _C.update(t=now, key=key, res=res, err="", base=base)
        return res
    except Exception as ex:
        _C.update(t=now, err="%s: %s" % (type(ex).__name__, str(ex)[:100]), base=base, res=None)
        return None


def summary(base=None):
    """The small block for the Brain view (key learn.stats). Never raises. status 'collecting' until some state has MIN_N trades, then 'measuring'."""
    res = refresh(base)
    if res is None:
        return {"version": STATS_VERSION, "status": "collecting", "err": _C["err"], "overall": [], "slices": [], "ledger": [], "provisional": True}
    show = ("state", "name", "n", "unjudged", "left", "excess", "shrunk", "avail", "back", "win", "halves", "p_adj", "verdict", "lean", "text")
    waiting = sum(1 for g in res["slices"][1:] for r in g["states"].values() if 0 < r["n"] < MIN_N)
    return {"version": STATS_VERSION, "status": "measuring" if any(r["n"] >= MIN_N for r in res["slices"][0]["states"].values()) else "collecting",
            "trades": res["trades"], "min_n": MIN_N, "tests": res["tests"],
            "overall": [{k: r[k] for k in show} for r in res["slices"][0]["states"].values()],
            "slices": [dict({k: r[k] for k in show}, slice=g["slice"]) for g in res["slices"][1:] for r in g["states"].values() if r["n"] >= MIN_N],
            "slices_waiting": waiting, "ledger": [{k: r[k] for k in ("state", "kind", "label", "n", "mistakes", "rate", "usual", "diff", "p_adj", "verdict", "text")}
                                                   for r in res["ledger"]],
            "mistakes_total": len(res["mistakes"]), "no_regime": res.get("no_regime", 0), "err": _C["err"], "provisional": True}


def run(base=None):
    """Hand run / tests: load + analyze, no writes. Never raises. -> analysis dict (with `err` when something went wrong)."""
    try:
        calls, info = load(base)
        out = analyze(calls)
        out.update(left_out=info["left_out"], no_regime=info["no_regime"], err="")
        out["states"] = out["slices"][0]["states"]                 # the 2a shape: the overall result per state
        return out
    except Exception as ex:
        return {"version": STATS_VERSION, "states": {}, "slices": [], "ledger": [], "mistakes": [], "trades": 0, "judged_calls": 0, "provisional": True,
                "err": "%s: %s" % (type(ex).__name__, str(ex)[:100])}


if __name__ == "__main__":
    o = run()
    print(json.dumps({k: v for k, v in o.items() if k not in ("states", "slices", "ledger", "mistakes")}, indent=1))
    for s in STATES:
        if s in o.get("states", {}):
            print(o["states"][s]["text"])
    for g in o.get("slices", [])[1:]:
        for r in g["states"].values():
            if r["n"] >= MIN_N:
                print(r["text"])
    for r in o.get("ledger", []):
        print(r["text"])
