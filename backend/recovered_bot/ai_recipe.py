"""
ai_recipe.py - the RESULT page: "kaun se signal lo, kaun se skip karo, kahan exit karo".

Not a table of data. One answer:
    WHEN (1-2 conditions that must be true at entry)  +  EXIT (which TP)  ->  net ROI per trade.

How it is found (all from the Shadow Lab replay, fee + leverage already inside every ROI):
  1. all finished lab signals of one timeframe are split by TIME: older 60% = search, newer 40% = exam.
  2. on the older 60% every 1- and 2-condition entry filter x 5 exit rules is scored (min sample size).
  3. the single best one by the OLDER data is then judged ONLY on the newer 40% that it never saw,
     and compared with "take every signal" (what the bot does now) on that same newer data.
  4. luck test: pick the same number of random signals from the newer data 300 times - how often is the
     random pick as good? (low % = not luck)
Verdict:  FOUND   = positive on new data, clearly better than taking everything, luck < 10%, 30+ trades
          MAYBE   = better than taking everything but not proven (or still a loss)
          NONE    = nothing found that survives new data  (this is also an answer: do not trust a filter yet)
          TOO_FEW = under 100 signals

READ-ONLY. It never opens, blocks or closes a trade. Never raises.
Honest limits: replay is not live trading; signals inside one market move are not independent;
searching many filters can find a lucky one - that is exactly why the newer 40% and the luck test exist.
"""
import random
import threading
import time

from . import ai_exit_study as X
from . import ai_rowcache as RC
from . import ai_shadow_lab as L

RULES = X.RULES
LIVE = X.LIVE
NICE = X.NICE
KINDS = ("move", "z_tsi", "sd_shape", "sd_size", "z_div", "zma_vs_trade", "phase", "tsi_vs_trade", "z_zone",
         "z_move", "momentum", "warning", "mtf_agree", "htf_15m", "htf_1h", "htft_15m", "htft_1h", "regime",
         "volume", "direction", "market")
MIN_ALL = 100
MIN_KEEP_TEST = 30
MIN_GAIN = 1.0           # ROI points better than "take every signal" on the exam data
LUCK_RUNS = 300
LUCK_MAX = 10.0
CACHE_MIN_AGE_S = 300
DAY_MS = 86_400_000

_lock = threading.RLock()
_busy = {"v": False}
_cache = {}              # tf -> {"key", "ts", "out"}


def _stat(vals):
    n = len(vals)
    if not n:
        return {"n": 0, "avg": 0.0, "wr": 0.0}
    return {"n": n, "avg": round(sum(vals) / n, 3), "wr": round(sum(1 for v in vals if v > 0) / n * 100.0, 1)}


def _tokens(row):
    return [f"{k}={row['lab'][k]}" for k in KINDS if row["lab"].get(k)]


def _search(train):
    """Best (tokens tuple, rule) by average net ROI on `train`. Also returns the next best distinct ones."""
    n = len(train)
    minn = max(25, int(n * 0.05))
    idx = {}
    for i, r in enumerate(train):
        for t in _tokens(r):
            idx.setdefault(t, set()).add(i)
    singles = {t: s for t, s in idx.items() if len(s) >= minn}
    vals = {k: [r["v"][k] for r in train] for k in RULES}
    cands = []

    def score(tok, s):
        for rule in RULES:
            v = vals[rule]
            cands.append((sum(v[i] for i in s) / len(s), tok, rule, len(s)))

    for t, s in singles.items():
        score((t,), s)
    toks = list(singles)
    for a in range(len(toks)):
        ka = toks[a].split("=", 1)[0]
        for b in range(a + 1, len(toks)):
            if toks[b].split("=", 1)[0] == ka:
                continue
            s = singles[toks[a]] & singles[toks[b]]
            if len(s) >= minn:
                score((toks[a], toks[b]), s)
    cands.sort(key=lambda c: -c[0])
    out, seen = [], set()
    for c in cands:
        if c[1] in seen:
            continue
        seen.add(c[1])
        out.append(c)
        if len(out) >= 3:
            break
    return out


def _match(row, toks):
    return all(row["lab"].get(t.split("=", 1)[0]) == t.split("=", 1)[1] for t in toks)


def _luck(test_vals_all, k, observed_avg):
    if k <= 0 or len(test_vals_all) < k:
        return 100.0
    rnd = random.Random(7)
    hit = 0
    for _ in range(LUCK_RUNS):
        if sum(rnd.sample(test_vals_all, k)) / k >= observed_avg:
            hit += 1
    return hit / LUCK_RUNS * 100.0


def _human(toks):
    return [t.split("=", 1)[1] for t in toks]


def _compute(tf, lev, fee):
    rows = X.lab_rows(tf, lev, fee)
    n = len(rows)
    out = {"tf": tf, "signals": n, "verdict": "TOO_FEW", "headline": "", "recipe": None, "alts": [],
           "steps": [], "caveats": ["Replay, live trading nahi: slippage nahi, order hamesha fill.",
                                    "Ek hi market move ke signals alag-alag nahi hote. Bade sample pe hi bharosa.",
                                    "Ye sirf dekhna hai: bot ka koi trade isse nahi badalta."]}
    if n < MIN_ALL:
        out["headline"] = f"Abhi {n} signal. Recipe ke liye {MIN_ALL}+ chahiye."
        out["steps"] = ["Bot ko chalne do. Naye signals ke saath ye khud bharega.",
                        "Tab tak apni strategy me koi badlav mat karo."]
        return out
    cut = int(n * 0.6)
    train, test = rows[:cut], rows[cut:]
    best = _search(train)
    if not best:
        out["verdict"] = "NONE"
        out["headline"] = "Koi bhi condition itne signals pe nahi mili jisse bharosa ban sake."
        return out
    test_all = {k: [r["v"][k] for r in test] for k in RULES}

    def judge(c):
        avg_tr, toks, rule, ntr = c
        kept = [r for r in test if _match(r, toks)]
        kv = [r["v"][rule] for r in kept]
        return {"when": list(toks), "when_human": _human(toks), "exit": rule, "exit_nice": NICE[rule],
                "train": {"n": ntr, "avg": round(avg_tr, 3), "wr": _stat([r["v"][rule] for r in train if _match(r, toks)])["wr"]},
                "test": _stat(kv), "base_test": _stat(test_all[LIVE]), "kept_n": len(kept)}

    top = judge(best[0])
    alts = [judge(c) for c in best[1:]]
    luck = _luck(test_all[top["exit"]], top["test"]["n"], top["test"]["avg"])
    top["luck_pct"] = round(luck, 1)
    days = max(0.5, (rows[-1]["t"] - rows[0]["t"]) / DAY_MS)
    keep_all = sum(1 for r in rows if _match(r, top["when"]))
    top["per_day"] = round(keep_all / days, 1)
    top["all_per_day"] = round(n / days, 1)
    out["recipe"] = top
    out["alts"] = [{"when_human": a["when_human"], "exit_nice": a["exit_nice"], "test": a["test"]} for a in alts]
    t, b = top["test"], top["base_test"]
    better = t["avg"] - b["avg"]
    if t["n"] >= MIN_KEEP_TEST and t["avg"] > 0 and better >= MIN_GAIN and luck < LUCK_MAX:
        v = "FOUND"
    elif t["n"] >= 15 and better > 0:
        v = "MAYBE"
    else:
        v = "NONE"
    out["verdict"] = v
    wh = " + ".join(top["when_human"])
    if v == "FOUND":
        out["headline"] = (f"Setup mila: {wh}, exit '{top['exit_nice']}'. Naye data pe avg {t['avg']:+.1f}% per trade "
                           f"(sab signal lene pe {b['avg']:+.1f}%), {t['n']} trade, luck chance {luck:.0f}%.")
        out["steps"] = ["Chart pe sirf in conditions ke signal pe trade lo, baaki skip.",
                        f"Exit: {top['exit_nice']}.",
                        "Pehle paper me 2-3 din isi rule se chalao, tabhi live. Bot ka code abhi mat chhedo."]
    elif v == "MAYBE":
        out["headline"] = (f"Thoda behtar, par pakka nahi: {wh}, exit '{top['exit_nice']}'. Naye data pe avg {t['avg']:+.1f}% "
                           f"vs sab signal {b['avg']:+.1f}% ({t['n']} trade, luck {luck:.0f}%).")
        out["steps"] = ["Abhi isse live trade mat lo.", "Aur data jama hone do, phir ye dobara jaanch hogi.",
                        "Tab tak har signal pe trade karna loss ka sauda hai, sirf zarurat ke signal lo."]
    else:
        out["headline"] = ("Koi setup nahi mila jo naye data pe bhi chale. Best filter bhi naye data pe "
                           f"{t['avg']:+.1f}% de raha hai (sab signal {b['avg']:+.1f}%).")
        out["steps"] = ["Matlab problem sirf in conditions ki nahi, entry idea hi kamzor hai.",
                        "Strategy me naya filter/indicator socho (Pine me), phir wahi replay se jaanchenge."]
    return out


def build(tf=""):
    """Never raises. Heavy part runs at most every 5 minutes per timeframe and only if the data changed."""
    try:
        tf = tf if tf in L.SIGNAL_TFS else str(X._cfg("timeframe", "3m"))
        if tf not in L.SIGNAL_TFS:
            tf = "3m"
        lev = float(X._cfg("leverage", 1) or 1)
        fee = max(0.0, float(X._cfg("fee_roi_pct", 1.0) or 0.0))
        key = (RC.version(), lev, fee)
        with _lock:
            hit = _cache.get(tf)
            if hit and (hit["key"] == key or time.time() - hit["ts"] < CACHE_MIN_AGE_S):
                return hit["out"]
            if _busy["v"]:
                return hit["out"] if hit else {"tf": tf, "verdict": "TOO_FEW", "signals": 0, "recipe": None,
                                               "alts": [], "steps": [], "headline": "Hisaab ho raha hai, thodi der baad dekho."}
            _busy["v"] = True
        try:
            out = _compute(tf, lev, fee)
            with _lock:
                _cache[tf] = {"key": key, "ts": time.time(), "out": out}
            return out
        finally:
            with _lock:
                _busy["v"] = False
    except Exception as e:
        return {"tf": tf, "verdict": "TOO_FEW", "signals": 0, "recipe": None, "alts": [], "steps": [],
                "headline": "", "error": f"{type(e).__name__}: {e}"}


def match_for(tf, lab):
    """True / False if the (finished or running) signal facts match the current recipe, None if no usable recipe."""
    try:
        hit = _cache.get(tf)
        out = hit["out"] if hit else build(tf)
        rc = out.get("recipe")
        if not rc or out.get("verdict") not in ("FOUND", "MAYBE"):
            return None
        return _match({"lab": lab}, rc["when"])
    except Exception:
        return None
