"""
ai_exit_study.py - PHASE 2: "kab TP1 pe poora band karna behtar, kab TP4 tak hold".

Shadow Lab already replays every signal under 5 exit rules (T1/T2/T3/T4/T4n). Here those results are
grouped by scenario (sideways / trending, Z+TSI agree or not, SD shape, Z divergence ...) and the
average NET ROI of each rule is compared with what the live bot does (T4).

READ-ONLY. Nothing here is used by any trading decision. Never raises.
Honest: a replay is not live trading, and a result is only called CLEAR when it holds in BOTH the older
and the newer half of the data. Otherwise MAYBE (watch it) or TOO_FEW (ignore it).
"""
import threading
import time

from . import ai_ind_features as F
from . import ai_shadow_lab as L
from . import ai_rowcache as RC

RULES = ("T1", "T2", "T3", "T4", "T4n")
LIVE = L.LIVE_RULE
KINDS = ("move", "z_tsi", "sd_shape", "z_div", "zma_vs_trade", "phase", "tsi_vs_trade")
MIN_SCEN = 25          # a scenario with fewer signals is not shown
MIN_CLEAR = 40         # signals needed before a scenario can be CLEAR
MIN_GAIN = 1.0         # ROI points a rule must beat the live rule by
MIN_ALL = 100
_CACHE_S = 90
_lock = threading.RLock()
_rows_cache = {"key": None, "v": []}
_out_cache = {}

NICE = {
    "T1": "TP1 pe poora band", "T2": "TP2 pe poora band", "T3": "TP3 pe poora band",
    "T4": "TP4 tak hold (bot jaisa)", "T4n": "TP4 tak hold, SL entry pe nahi",
}


def _cfg(name, default):
    try:
        from . import settings_store
        v = settings_store.get(name, default)
        return default if v is None else v
    except Exception:
        return default


def lab_rows(tf, lev, fee):
    """Finished lab signals of one timeframe, oldest first:
    {'t','sym','a','lab': {kind: text}, 'v': {rule: net ROI %}, 'w': {rule: how it ended}}.
    From the shared slim reader (ai_rowcache)."""
    key = (RC.version(), tf, lev, fee)
    with _lock:
        if _rows_cache["key"] == key:
            return _rows_cache["v"]
    out = []
    for r in RC.rows(tf):
        try:
            o = r["o"]
            if any(k not in o or o[k][1] == "OPEN" for k in RULES):
                continue
            out.append({"t": r["t"], "sym": r["sym"], "a": r["a"], "lab": r["f"],
                        "v": {k: L._net(o[k][0], lev, fee) for k in RULES},
                        "w": {k: o[k][1] for k in RULES}})
        except Exception:
            continue
    with _lock:
        _rows_cache.update(key=key, v=out)
    return out


def _avg(rows, rule):
    return sum(r["v"][rule] for r in rows) / len(rows) if rows else 0.0


def _best(rows):
    return max(RULES, key=lambda k: _avg(rows, k))


def _scenario(label, rows):
    n = len(rows)
    avgs = {k: round(_avg(rows, k), 3) for k in RULES}
    best = _best(rows)
    gain = avgs[best] - avgs[LIVE]
    half = n // 2
    old, new = rows[:half], rows[half:]
    stable = bool(old and new and _best(old) == best and _best(new) == best
                  and _avg(old, best) - _avg(old, LIVE) >= MIN_GAIN * 0.5
                  and _avg(new, best) - _avg(new, LIVE) >= MIN_GAIN * 0.5)
    if best == LIVE or gain < MIN_GAIN:
        verdict = "SAME"          # live rule is fine here
    elif n >= MIN_CLEAR and stable:
        verdict = "CLEAR"
    else:
        verdict = "MAYBE"
    if best == LIVE or verdict == "SAME":
        msg = "Yaha bot jaisa hold karna theek hai."
    else:
        msg = f"Yaha '{NICE[best]}' behtar dikha: avg {avgs[best]:+.1f}% vs bot {avgs[LIVE]:+.1f}%."
        if verdict == "MAYBE":
            msg += " Abhi pakka nahi."
    return {"label": label, "n": n, "avg": avgs, "best": best, "gain": round(gain, 3),
            "verdict": verdict, "stable": stable, "msg": msg}


def build(tf=""):
    """Scoreboard for one timeframe. Never raises."""
    try:
        tf = tf if tf in L.SIGNAL_TFS else str(_cfg("timeframe", "3m"))
        if tf not in L.SIGNAL_TFS:
            tf = "3m"
        with _lock:
            hit = _out_cache.get(tf)
            if hit and time.time() - hit[0] < _CACHE_S:
                return hit[1]
        lev = float(_cfg("leverage", 1) or 1)
        fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
        rows = lab_rows(tf, lev, fee)
        n = len(rows)
        out = {"tf": tf, "signals": n, "leverage": lev, "rules": list(RULES), "nice": NICE,
               "overall": {k: round(_avg(rows, k), 3) for k in RULES} if n else {},
               "status": "TOO_FEW" if n < MIN_ALL else "OK", "scenarios": [], "headline": "",
               "caveats": ["Replay on real candles, live trading nahi: slippage nahi, order hamesha fill.",
                           "ROI = price move x leverage minus fee. Har trade ka margin barabar.",
                           "Ye sirf dekhna hai: bot ka exit koi nahi badla."]}
        if n >= MIN_SCEN:
            by = {}
            for r in rows:
                for k in KINDS:
                    t = r["lab"].get(k)
                    if t:
                        by.setdefault(t, []).append(r)
            sc = [_scenario(t, rs) for t, rs in by.items() if len(rs) >= MIN_SCEN]
            order = {"CLEAR": 0, "MAYBE": 1, "SAME": 2}
            sc.sort(key=lambda s: (order[s["verdict"]], -s["gain"]))
            out["scenarios"] = sc[:12]
        if n < MIN_ALL:
            out["headline"] = f"Abhi sirf {n} signal. Exit ka faisla ke liye {MIN_ALL}+ chahiye."
        else:
            ov = out["overall"]
            b = max(RULES, key=lambda k: ov[k])
            clear = [s for s in out["scenarios"] if s["verdict"] == "CLEAR"]
            if clear:
                out["headline"] = f"{len(clear)} condition me alag exit behtar pakka dikha. Neeche dekho."
            elif b != LIVE and ov[b] - ov[LIVE] >= MIN_GAIN:
                out["headline"] = f"Sab milake '{NICE[b]}' thoda aage hai, par condition-wise pakka nahi."
            else:
                out["headline"] = "Abhi koi exit rule bot ke TP4 hold se pakka behtar nahi nikla."
        with _lock:
            _out_cache[tf] = (time.time(), out)
        return out
    except Exception as e:
        return {"tf": tf, "signals": 0, "status": "ERROR", "scenarios": [], "overall": {},
                "headline": "", "error": f"{type(e).__name__}: {e}"}
