"""brain_look.py - Batch 4c-1: LOOK-ALIKE LEARNING with walk-forward checking (measurement only, nothing is decided, nothing is stored yet).

Question: "when a Brain call looks like earlier calls of the same state, did those earlier trades do better or worse than usual after the call,
and did that tell us anything about how THIS trade went on?"   It never opens, closes, changes or rejects a trade, calls no API, reads no price feed.

Reused, not copied (brain_stats.py): load() of the calls, the first-call-per-trade rule, the baseline book (exact candle count x ROI band, only
trades that finished before), judged() = excess over baseline, the verdict rule _judge() (30 trades / older-newer halves / luck p), MIN_N, PRIOR_K,
FULL_N, and the slice list (all, BUY / SELL, timeframe, regime, crosses). brain_stats.features() reads the 8 numbers from the B4a obs rows.

FIXED SET (version l1, set BEFORE any result was looked at; a change needs a new LOOK_VERSION, never a quiet edit):
  features  tsi, hist, z, zg, sm, bw, ed, sc   (B4a obs numbers, signs are "with the trade")
  K_NEAR 15 nearest look-alikes, MAX_RMS 1.0 (a look-alike must be within 1.0 standard deviations on average over the numbers both rows have),
  MIN_COMMON 6 numbers that both rows have (zg depends on Z-SMA, which needs ~400 candles, so it is often missing on old candles: never guessed),
  MIN_POOL 30 earlier trades in the group, MIN_LOOK 10 look-alikes, POOL_MAX 300 newest earlier trades looked at.

How one call is judged:
  group     same BUY/SELL, same timeframe, same state letter. One trade is at most ONE member of a pool (its first call of that state),
            so one trade can never be many pieces of evidence.
  pool      only trades whose exit candle had CLOSED before this call's candle opened (same walk-forward rule as the baseline). Their `excess`
            (left - baseline, from brain_stats) was fixed with older trades only.
  scaling   the spread (standard deviation) of every number is taken from that same pool, so nothing from the future leaks into the distance.
  guess     pred = sum of the look-alikes' excess / (m + PRIOR_K)  (pulled toward 0 when there are few).   sign(pred): + = "holding did better than usual".
  score     sign(pred) x actual excess of THIS trade, averaged over the judged calls. Positive = the look-alikes pointed the right way, by this many
            ROI points per trade. 0 = they told us nothing. It is a measurement of the guess, not a rule that was applied.
LUCK (same-market-move protection): trades opened in one market move are not independent, so a plain shuffle is too kind. The luck test shifts
  the actual results around the time-ordered list by a whole number of positions larger than the busiest BLOCK_MS window (so a guess is always
  paired with a result from another market move), tries every such shift and asks how often luck alone gives a score as far from 0. Too few
  shifts possible (everything happened in a few hours) = no p = no verdict. A score <= 0 is never a hint.
SAMPLE: fewer than MIN_N scored calls = NOT ENOUGH DATA. A hint needs older and newer half to agree and p_adj <= 0.20; SUPPORTED needs 100 and 0.05.
  p_adj = p x the number of results that had 30+ calls in this run (many slices at once).
Run by hand: cd backend && python3 brain_look.py      (not connected to the worker; B4c-2 stores / shows it)
"""
import bisect
import json
import sys

import brain_stats as BS

LOOK_VERSION = "l1"
FEATS = ("tsi", "hist", "z", "zg", "sm", "bw", "ed", "sc")
K_NEAR = 15
MAX_RMS = 1.0
MIN_COMMON = 6
MIN_POOL = 30
MIN_LOOK = 10
POOL_MAX = 300
BLOCK_MS = 2 * 3600 * 1000            # one market move = trades inside this window are treated as one block when the luck shift is chosen
MIN_SHIFTS = 20
MAX_SHIFTS = 500
HINTS = ("EARLY HINT", "SUPPORTED")
CONFIG = {"feats": list(FEATS), "k": K_NEAR, "max_rms": MAX_RMS, "min_common": MIN_COMMON, "min_pool": MIN_POOL, "min_look": MIN_LOOK,
          "pool_max": POOL_MAX, "block_ms": BLOCK_MS, "min_shifts": MIN_SHIFTS}


def load(base=None):
    """-> (calls, info): the calls of brain_stats.load(), each with c["x"] = its 8 numbers (None when the obs row is missing). Reads only."""
    calls, info = BS.load(base)
    fx = BS.features(base, {c["id"] for c in calls}, FEATS)
    for c in calls:
        c["x"] = fx.get((c["id"], c["t"]))
    info["no_feats"] = sum(1 for c in calls if c["x"] is None)
    return calls, info


def _spread(window):
    """Standard deviation of each number over the pool window (None when under 10 values or no spread). Uses the window only."""
    out = []
    for i in range(len(FEATS)):
        v = [r[1]["x"][i] for r in window if r[1]["x"][i] is not None]
        if len(v) < 10:
            out.append(None)
            continue
        m = sum(v) / len(v)
        sd = (sum((a - m) ** 2 for a in v) / len(v)) ** 0.5
        out.append(sd if sd > 1e-9 else None)
    return out


def _dist(a, b, sd):
    s = n = 0
    for x, y, d in zip(a, b, sd):
        if x is None or y is None or d is None:
            continue
        s += ((x - y) / d) ** 2
        n += 1
    return (s / n) ** 0.5 if n >= MIN_COMMON else None


def _guess(x, window):
    """PURE. -> (pred, how many look-alikes) from the pool window, or None when there are too few look-alikes."""
    sd = _spread(window)
    near = []
    for xc, c, e in window:
        dd = _dist(x, c["x"], sd)
        if dd is not None and dd <= MAX_RMS:
            near.append((dd, xc, e))
    if len(near) < MIN_LOOK:
        return None
    near.sort(key=lambda r: (r[0], r[1]))
    pick = near[:K_NEAR]
    return sum(e for _d, _x, e in pick) / (len(pick) + BS.PRIOR_K), len(pick)


def evaluate(calls, state, book=None):
    """PURE. Every judged first call of `state` that has numbers, guessed from earlier finished trades only.
    -> (targets [{id, t, st, d, tf, reg, pred, m, actual}] oldest first, judged calls, without numbers, without enough look-alikes)."""
    rows, _n = BS.judged(calls, state, book)
    groups = {}
    for c, e, _b in rows:
        if c.get("x") is not None:
            groups.setdefault((c["d"], c["tf"]), []).append((c["xc"], c, e))
    xcs = {}
    for k, g in groups.items():
        g.sort(key=lambda r: r[0])
        xcs[k] = [r[0] for r in g]
    out, nofeat, nolook = [], 0, 0
    for c, e, _b in rows:
        if c.get("x") is None:
            nofeat += 1
            continue
        k = (c["d"], c["tf"])
        j = bisect.bisect_right(xcs[k], c["t"])                 # exit candle closed at or before this call candle opened
        win = groups[k][max(0, j - POOL_MAX):j]
        g = _guess(c["x"], win) if len(win) >= MIN_POOL else None
        if g is None or g[0] == 0:
            nolook += 1
            continue
        out.append({"id": c["id"], "t": c["t"], "st": state, "d": c["d"], "tf": c["tf"], "reg": c.get("reg"), "pred": g[0], "m": g[1], "actual": e})
    return out, len(rows), nofeat, nolook


def _sg(x):
    return (x > 0) - (x < 0)


def _shift_p(sg, ac, ts):
    """Luck test with market-move protection (see the module text). -> p, or None when too few safe shifts exist or under MIN_N."""
    n = len(ts)
    if n < BS.MIN_N:
        return None
    j = blk = 0
    for i in range(n):
        while ts[j] <= ts[i] - BLOCK_MS:
            j += 1
        blk = max(blk, i - j + 1)
    if n - 2 * blk + 1 < MIN_SHIFTS:
        return None
    offs = range(blk, n - blk + 1)[::max(1, (n - 2 * blk + 1) // MAX_SHIFTS)]
    obs = abs(sum(s * a for s, a in zip(sg, ac)) / n)
    hit = sum(1 for o in offs if abs(sum(sg[i] * ac[(i + o) % n] for i in range(n)) / n) >= obs - 1e-12)
    return (hit + 1.0) / (len(offs) + 1.0)


def _stat(state, rows, judged_n, nofeat, nolook):
    """One result (a state inside one slice) from its targets."""
    rows = sorted(rows, key=lambda r: r["t"])
    n = len(rows)
    r = {"state": state, "name": BS.NAMES[state], "n": n, "judged": judged_n, "nofeat": nofeat, "nolook": nolook, "score": None, "shrunk": None,
         "hit": None, "hold_n": 0, "hold_ex": None, "exit_n": 0, "exit_ex": None, "look": None, "halves": None, "p": None}
    if n:
        sg, ac = [_sg(x["pred"]) for x in rows], [x["actual"] for x in rows]
        sc = [s * a for s, a in zip(sg, ac)]
        hold, leave = [a for s, a in zip(sg, ac) if s > 0], [a for s, a in zip(sg, ac) if s < 0]
        r.update(score=BS._r(BS._mean(sc)), shrunk=BS._r(sum(sc) / (n + BS.PRIOR_K)), hit=int(round(100.0 * sum(1 for x in sc if x > 0) / n)),
                 hold_n=len(hold), hold_ex=BS._r(BS._mean(hold)), exit_n=len(leave), exit_ex=BS._r(BS._mean(leave)),
                 look=BS._r(BS._mean([x["m"] for x in rows])))
        if n >= 2 * BS.MIN_HALF:
            h = n // 2
            r["halves"] = [BS._r(BS._mean(sc[:h])), BS._r(BS._mean(sc[h:]))]
        if n >= BS.MIN_N:
            r["p"] = BS._r(_shift_p(sg, ac, [x["t"] for x in rows]), 3)
        r["_score"] = BS._mean(sc)
    return r


def _finish(r, ptests):
    r["tests"] = ptests
    r["p_adj"] = None if r["p"] is None else BS._r(min(1.0, r["p"] * max(1, ptests)), 3)
    sc = r.pop("_score", None)
    v = BS._judge(r["n"], r["halves"], sc, r["p"], ptests)
    if v in HINTS and (sc or 0) <= 0:
        v = "NO CLEAR PATTERN"                                   # look-alikes pointed the wrong way: never a hint
    r["verdict"] = v
    r["text"] = _text(r)


def _text(r):
    who = "%s look-alikes" % r["name"]
    if r["verdict"] == "NOT ENOUGH DATA":
        return "%s: %d of %d judged calls had enough look-alikes. NOT ENOUGH DATA (need %d)." % (who, r["n"], r["judged"], BS.MIN_N)
    base = "%s (%d calls): the guess from look-alikes was %+.1f ROI points per trade better than no guess (right way %d%% of the time)." % (
        who, r["n"], r["score"], r["hit"])
    if r["verdict"] == "NO CLEAR PATTERN":
        why = " Too bunched in time to test luck." if r["p"] is None else " No clear pattern: it could be luck, or older and newer calls disagree."
        return base + why
    return base + " %s. Not advice." % r["verdict"].capitalize()


def analyze(calls, flag=None):
    """PURE. Everything B4c-1 measures. -> {version, look_version, config, trades, tests, slices: [{slice, kind, targets, states}], targets, coverage}.
    slices use brain_stats' list (all, BUY, SELL, each timeframe, each regime, crosses); the guesses are made once and only re-grouped.
    flag = optional f(call, state) -> number that replaces what is measured (`left`) for that state; None = the B4c-1 measure (what holding added).
    brain_pattern (B4c-2) uses it to measure mistakes with the same machinery: the baseline and the look-alikes are then made from that number."""
    tg, cov = [], {}
    for s in BS.STATES:
        cs = calls if flag is None else [dict(c, left=flag(c, s)) for c in calls]
        book = BS._Base(BS._first_per(cs, lambda c: BS._cell(c["n"], c["roi"])))
        t, jn, nf, nl = evaluate(cs, s, book)
        tg += t
        cov[s] = {"judged": jn, "nofeat": nf, "nolook": nl, "scored": len(t)}
    sl = []
    for name, kind, keep in BS._groups(calls):
        sub = [t for t in tg if keep(t)]
        if not (sub or name == "all"):
            continue
        res = {s: _stat(s, [t for t in sub if t["st"] == s], cov[s]["judged"] if name == "all" else sum(1 for t in sub if t["st"] == s),
                        cov[s]["nofeat"] if name == "all" else 0, cov[s]["nolook"] if name == "all" else 0) for s in BS.STATES}
        sl.append({"slice": name, "kind": kind, "targets": len(sub), "states": res})
    k_all = max(1, sum(1 for r in sl[0]["states"].values() if r["n"] >= BS.MIN_N))
    k_sl = max(1, sum(1 for g in sl[1:] for r in g["states"].values() if r["n"] >= BS.MIN_N))
    for g in sl:
        for r in g["states"].values():
            _finish(r, k_all if g["slice"] == "all" else k_sl)
            if g["slice"] != "all":
                r["text"] = g["slice"] + " - " + r["text"]
    return {"version": BS.STATS_VERSION, "look_version": LOOK_VERSION, "config": CONFIG, "trades": len({c["id"] for c in calls}), "tests": k_sl,
            "slices": sl, "targets": tg, "coverage": cov, "provisional": True}


def run(base=None):
    """Hand run / tests: load + analyze, no writes. Never raises. -> analysis dict (with `err` when something went wrong)."""
    try:
        calls, info = load(base)
        out = analyze(calls)
        out.update(left_out=info["left_out"], no_feats=info["no_feats"], err="")
        out["states"] = out["slices"][0]["states"]
        return out
    except Exception as ex:
        return {"look_version": LOOK_VERSION, "config": CONFIG, "states": {}, "slices": [], "targets": [], "coverage": {}, "trades": 0, "provisional": True,
                "err": "%s: %s" % (type(ex).__name__, str(ex)[:100])}


if __name__ == "__main__":
    o = run()
    print(json.dumps({k: v for k, v in o.items() if k not in ("states", "slices", "targets")}, indent=1))
    for s in BS.STATES:
        if s in o.get("states", {}):
            print(o["states"][s]["text"])
    for g in o.get("slices", [])[1:]:
        for r in g["states"].values():
            if r["n"] >= BS.MIN_N:
                print(r["text"])
