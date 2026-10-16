"""
ai_wait_study.py - PHASE 3: "baar baar sideways me ghus ke SL hit" aur "dono confirm hon tabhi entry".

Two read-only questions answered from Shadow Lab signals (live bot rule T4, net ROI):
  1. Which coins hit SL again and again, and how many of those were sideways entries?
  2. If the bot had entered ONLY when it was not sideways AND Z and TSI both agreed with the trade,
     what would the result have been (and what would it have skipped)?
Result is CLEAR only if the filter wins in both the older and the newer half of the data and does
not skip more profit than loss. Nothing here touches a trade. Never raises.
"""
import time

from . import ai_exit_study as X
from . import ai_shadow_lab as L

LIVE = X.LIVE
MIN_ALL = 100
MIN_KEEP = 30
SIDE = "sideways"
BOTH = "Z and TSI both WITH trade"


def _is_side(r):
    return str(r["lab"].get("move", "")).startswith(SIDE)


def _confirmed(r):
    return (not _is_side(r)) and r["lab"].get("z_tsi") == BOTH


def _mean(rs):
    return sum(r["v"][LIVE] for r in rs) / len(rs) if rs else 0.0


def _wr(rs):
    return sum(1 for r in rs if r["v"][LIVE] > 0) / len(rs) * 100.0 if rs else 0.0


def _gain(rows, keep_fn):
    keep = [r for r in rows if keep_fn(r)]
    skip = [r for r in rows if not keep_fn(r)]
    return keep, skip, _mean(keep) - _mean(rows)


def build(tf=""):
    try:
        tf = tf if tf in L.SIGNAL_TFS else str(X._cfg("timeframe", "3m"))
        if tf not in L.SIGNAL_TFS:
            tf = "3m"
        lev = float(X._cfg("leverage", 1) or 1)
        fee = max(0.0, float(X._cfg("fee_roi_pct", 1.0) or 0.0))
        rows = X.lab_rows(tf, lev, fee)
        n = len(rows)
        out = {"tf": tf, "signals": n, "status": "TOO_FEW" if n < MIN_ALL else "OK",
               "coins": [], "sideways": {}, "confirm": {}, "verdict": "TOO_FEW", "headline": "",
               "caveats": ["Replay, live trading nahi. Sirf dekhna hai, bot koi trade block nahi karta.",
                           "Ek hi market move ke signals alag-alag nahi hote, isliye bade sample pe hi bharosa."]}
        if not n:
            out["headline"] = "Abhi lab signals nahi hain."
            return out
        # 1) repeat-SL coins
        per = {}
        for r in rows:
            d = per.setdefault(r["sym"], {"n": 0, "sl": 0, "side_sl": 0, "sum": 0.0})
            d["n"] += 1
            d["sum"] += r["v"][LIVE]
            if r["w"][LIVE] == "SL":
                d["sl"] += 1
                if _is_side(r):
                    d["side_sl"] += 1
        coins = [{"sym": s, **d, "avg": round(d["sum"] / d["n"], 3)} for s, d in per.items() if d["sl"] >= 3]
        coins.sort(key=lambda c: -c["sl"])
        out["coins"] = [{k: c[k] for k in ("sym", "n", "sl", "side_sl", "avg")} for c in coins[:6]]
        # 2) sideways overall
        side = [r for r in rows if _is_side(r)]
        out["sideways"] = {"n": len(side), "share": round(len(side) / n * 100, 1),
                           "avg": round(_mean(side), 3), "win_rate": round(_wr(side), 1),
                           "bot_avg": round(_mean(rows), 3)}
        # 3) enter only when confirmed
        keep, skip, g = _gain(rows, _confirmed)
        half = n // 2
        g_old = _gain(rows[:half], _confirmed)[2] if half else 0.0
        g_new = _gain(rows[half:], _confirmed)[2] if half else 0.0
        saved = -sum(r["v"][LIVE] for r in skip if r["v"][LIVE] < 0)
        lost = sum(r["v"][LIVE] for r in skip if r["v"][LIVE] > 0)
        out["confirm"] = {"keep_n": len(keep), "skip_n": len(skip),
                          "keep_avg": round(_mean(keep), 3), "keep_wr": round(_wr(keep), 1),
                          "bot_avg": round(_mean(rows), 3), "bot_wr": round(_wr(rows), 1),
                          "gain": round(g, 3), "gain_old": round(g_old, 3), "gain_new": round(g_new, 3),
                          "saved_loss": round(saved, 1), "lost_profit": round(lost, 1)}
        if n < MIN_ALL or len(keep) < MIN_KEEP:
            v = "TOO_FEW"
        elif g >= 1.0 and g_old > 0 and g_new > 0 and saved > lost:
            v = "CLEAR"
        elif g > 0:
            v = "MAYBE"
        else:
            v = "NO"
        out["verdict"] = v
        c = out["confirm"]
        if v == "TOO_FEW":
            out["headline"] = f"Abhi {n} signal ({len(keep)} confirmed). Faisle ke liye aur data chahiye."
        elif v == "NO":
            out["headline"] = "'Dono confirm tabhi entry' se result behtar nahi hua. Isko mat lagao."
        else:
            out["headline"] = (f"Sirf confirmed entry: avg {c['keep_avg']:+.1f}% vs bot {c['bot_avg']:+.1f}%, "
                               f"{c['skip_n']} signal skip. " + ("Dono half me sahi." if v == "CLEAR" else "Par abhi pakka nahi."))
        return out
    except Exception as e:
        return {"tf": tf, "signals": 0, "status": "ERROR", "verdict": "TOO_FEW", "coins": [],
                "sideways": {}, "confirm": {}, "headline": "", "error": f"{type(e).__name__}: {e}"}
