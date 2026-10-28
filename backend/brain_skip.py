"""brain_skip.py - NEXT-7: SKIPPED-SIGNAL OBSERVATION (read-only, paper only, nothing here controls a trade).

The Dual Bot already runs every skipped signal to the end as a what-if trade (status skipped / skipped_done in dual_archive.db, same exit
simulator and fee as a taken trade). This module only READS those finished what-if trades and compares them with the taken trades:
"if we had taken the signals the model skipped, would they have done better or worse than the ones we took?"

KEPT SEPARATE from the taken-trade evidence (brain_stats / look-alike / shadow): a skipped result is never added to their numbers.
Rule (the same luck test and verdict words as brain_stats._judge): under MIN_N finished skipped signals = NOT ENOUGH DATA; NO CLEAR PATTERN unless the
older and the newer half of the skipped signals point the same way AND a random draw of taken trades rarely differs that much; then EARLY HINT
(SUPPORTED needs FULL_N). No made-up percentage. Numbers are ROI points net of fee (what the Dual Bot stores in `net`).
Only SELECT on dual_archive.db (read-only opener). No new table, no change to dual_lab.py. Never raises.
"""
import json
import time

import brain_stats as BS
import trade_archive as TA

SKIP_VERSION = "k1"
_C = {"t": 0.0, "key": None, "res": None, "base": None}          # same cache pattern as brain_shadow / brain_pattern


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


def compare(skipped, taken):
    """PURE. skipped = [(signal time, net)] of FINISHED skipped signals, taken = [net] of finished taken trades.
    -> {n, mean_skip, mean_taken, diff, halves, p, verdict}. diff < 0 = the skipped signals did worse than the taken ones."""
    sk = sorted(skipped)
    n = len(sk)
    tm = _mean(list(taken))
    out = {"n": n, "mean_skip": _r(_mean([x for _, x in sk])), "mean_taken": _r(tm), "diff": None, "halves": [], "p": None, "verdict": "NOT ENOUGH DATA"}
    if n < BS.MIN_N or tm is None:
        return out
    diff = _mean([x for _, x in sk]) - tm
    h = n // 2
    halves = [_mean([x for _, x in sk[:h]]) - tm, _mean([x for _, x in sk[h:]]) - tm]
    pool = [x - tm for x in taken]                                  # taken trades centred on their own mean: "how far does a random draw drift?"
    p = BS._luck_p(pool, n, diff) if len(pool) >= n else None
    out.update(diff=_r(diff), halves=[_r(x) for x in halves], p=_r(p, 3), verdict=BS._judge(n, halves, diff, p))
    return out


def _load(base=None):
    """Read-only. -> {tf: {"skip": [(t, net)], "taken": [net]}}, skipped still open. Missing file / table = empty."""
    con = TA.open_dual_ro(base)
    if con is None:
        return {}, 0
    try:
        if "trades" not in {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}:
            return {}, 0
        by, open_n = {}, 0
        for st, t, tf, net in con.execute("SELECT status, t, tf, net FROM trades WHERE status IN ('closed', 'skipped_done', 'skipped')"):
            if st == "skipped":
                open_n += 1
                continue
            if net is None:
                continue
            d = by.setdefault(tf or "?", {"skip": [], "taken": []})
            if st == "skipped_done":
                d["skip"].append((int(t or 0), float(net)))
            else:
                d["taken"].append(float(net))
        return by, open_n
    finally:
        con.close()


def summary(base=None, force=False):
    """The small block of the Brain view (key learn.skip). Counts, means and one verdict; no raw rows. Recomputed at most every BS.REFRESH_S and only when
    the number of finished trades changed. Read-only, never raises."""
    now = time.time()
    try:
        same = _C["res"] is not None and _C["base"] == base
        if not force and same and now - _C["t"] < BS.REFRESH_S:
            return _C["res"]
        by, open_n = _load(base)
        key = (sum(len(d["skip"]) for d in by.values()), sum(len(d["taken"]) for d in by.values()), open_n)
        if not force and same and key == _C["key"]:
            _C["t"] = now
            return _C["res"]
        skip = [x for d in by.values() for x in d["skip"]]
        taken = [x for d in by.values() for x in d["taken"]]
        c = compare(skip, taken)
        wins = sum(1 for _, x in skip if x > 0)
        tfs = {tf: {"skipped": len(d["skip"]), "taken": len(d["taken"]), "mean_skip": _r(_mean([x for _, x in d["skip"]])), "mean_taken": _r(_mean(d["taken"]))}
               for tf, d in sorted(by.items())}
        v = c["verdict"]
        if v == "NOT ENOUGH DATA":
            text = "Skipped signals: NOT ENOUGH DATA yet (%d of %d finished skipped signals). Paper numbers only, nothing here controls a trade." % (c["n"], BS.MIN_N)
        elif v == "NO CLEAR PATTERN":
            text = "Skipped signals: no clear difference from the taken trades yet. Paper numbers only."
        else:
            text = ("Skipped signals did %s than the taken trades (%s). Paper numbers only, nothing here controls a trade."
                    % ("worse" if c["diff"] < 0 else "better", v.lower()))
        res = {"version": SKIP_VERSION, "status": "measuring" if c["n"] >= BS.MIN_N else "collecting", "min_n": BS.MIN_N, "provisional": True, "err": "",
               "skipped_done": c["n"], "skipped_open": open_n, "taken_done": len(taken), "skip_win_n": wins, "mean_skip": c["mean_skip"],
               "mean_taken": c["mean_taken"], "diff": c["diff"], "halves": c["halves"], "p": c["p"], "verdict": v, "tf": tfs,
               "total_if_taken": _r(sum(x for _, x in skip)), "unit": "ROI points net of fee", "text": text}
        json.dumps(res, allow_nan=False)                           # must be plain JSON for the app, else it is an error below
        _C.update(t=now, key=key, res=res, base=base)
        return res
    except Exception as ex:
        return {"version": SKIP_VERSION, "status": "error", "min_n": BS.MIN_N, "provisional": True, "err": "%s: %s" % (type(ex).__name__, str(ex)[:80]),
                "verdict": "NOT ENOUGH DATA", "text": "Skipped-signal check could not be measured. NOT ENOUGH DATA."}


if __name__ == "__main__":
    print(json.dumps(summary(force=True), indent=1))
