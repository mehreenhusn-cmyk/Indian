"""owl_sniper_lookback.py - OwlSniper WEEKLY LOOKBACK TUNING (R6b). ADVICE ONLY, paper only. Reads candles (read only), writes ONLY v2_sniper_lookback.json.
Once a week (not before 7 days pass) it runs the optimizer of owl_sniper_regime.py on the latest 30 days and keeps the answer per market volatility regime (LOW / MEDIUM / HIGH / EXTREME).
A lookback (50..300) is CONFIRMED for a regime only when: (1) this run says STEADY_BEST for it, AND (2) the run before (a week or more ago) said STEADY_BEST for the SAME lookback.
One lucky run is never enough (6 lookbacks x 5 regimes = 30 checks, luck is likely). Anything else = the default stays.
Nothing in the trader reads this yet (owner OK needed). lookback_for(d, regime) is ready for that day: it gives the confirmed number or None.
Run (Termux, repo folder):  python3 backend/owl_sniper_lookback.py --data ~/storage/shared/owl_data [--force]
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_feed as F
import owl_sniper_regime as R

VERSION = "owl_sniper_lookback 1 (R6b)"
FILE = "v2_sniper_lookback.json"
WEEK, KEEP, DAYS = 7 * 86400, 8, 30
STEADY = "STEADY_BEST"


def load(d):
    return F.read_json(d, FILE)


def _confirm(now_rec, prev_rec, default):
    """{regime: {'lookback', 'confirmed', 'why'}} - confirmed only when two runs in a row agree on a STEADY_BEST number."""
    out = {}
    for rg in R.NAMES:
        a, b = (now_rec or {}).get(rg) or {}, (prev_rec or {}).get(rg) or {}
        if a.get("basis") == STEADY and b.get("basis") == STEADY and a.get("lookback") == b.get("lookback"):
            out[rg] = {"lookback": a["lookback"], "confirmed": True, "why": "STEADY on two runs in a row"}
        elif a.get("basis") == STEADY:
            out[rg] = {"lookback": default, "confirmed": False, "why": "%s looks STEADY once, waiting for the next weekly run" % a.get("lookback")}
        else:
            out[rg] = {"lookback": default, "confirmed": False, "why": "default kept (%s)" % (a.get("basis") or "no result")}
    return out


def run(d, tf="5m", now=None, persist=True, force=False):
    """The weekly job. Returns the saved dict. Before 7 days it returns the saved one unchanged (due=False). Never raises on missing data."""
    now = int(time.time() if now is None else now)
    old = load(d)
    if old and not force and now - int(old.get("made") or 0) < WEEK:
        return dict(old, due=False)
    rep = R.build(d, tf, since_days=DAYS, now=now)
    if not rep.get("ready"):
        return dict(old or {"state": "NOT_READY", "history": []}, due=True, last_try=now, last_note=rep.get("note", "not ready"), paper_only=True, advice_only=True)
    default = rep["default_lookback"]
    rec = {rg: {"lookback": v["lookback"], "basis": v["basis"], "gain_vs_default_r": v["gain_vs_default_r"]} for rg, v in rep["recommended"].items() if rg in R.NAMES}
    hist = list((old or {}).get("history") or [])
    prev_rec = hist[-1]["rec"] if hist else None
    hist = (hist + [{"at": now, "rec": rec}])[-KEEP:]
    use = _confirm(rec, prev_rec, default)
    n_ok = sum(1 for v in use.values() if v["confirmed"])
    st = {"version": VERSION, "made": now, "due": True, "interval": tf, "paper_only": True, "advice_only": True, "default_lookback": default, "days_used": DAYS,
          "state": "LEARNED_LOOKBACK" if n_ok else "DEFAULT_KEPT", "confirmed_regimes": n_ok, "use": use, "history": hist, "runs": len(hist),
          "note": "A lookback is used only after two weekly runs agree. Nothing in the trader reads this yet."}
    if persist:
        st["saved"] = F.write_json(d, FILE, st)
    return st


def lookback_for(d, regime):
    """The CONFIRMED lookback for a regime, else None (= keep the default)."""
    u = ((load(d) or {}).get("use") or {}).get(regime)
    return u["lookback"] if u and u.get("confirmed") else None


def summary(d):
    """Short block for the modes route (key 'lookback')."""
    st = load(d)
    if not st:
        return {"built": True, "state": "NOT_RUN_YET", "why": "First weekly run comes with the first modes run."}
    return {"built": True, "state": st.get("state"), "confirmed_regimes": st.get("confirmed_regimes"), "runs": st.get("runs"), "default": st.get("default_lookback"),
            "use": {k: v["lookback"] for k, v in (st.get("use") or {}).items() if v.get("confirmed")}, "advice_only": True}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.data, a.tf, force=a.force), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
