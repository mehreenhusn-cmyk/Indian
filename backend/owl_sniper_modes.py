"""owl_sniper_modes.py - OwlSniper MODES (R6a: SCALP / SHORT_SWING / SWING). PAPER ONLY, READ ONLY: reads saved files + the candle store (read only), writes ONE own file (v2_sniper_modes.json). No network, no order code.
Owner idea: "in a fast market take the quick profit, in a slow market let it run - and learn which market is which by itself".
Method (same honest frame as the booking learner R4, whose helpers are reused, nothing in R4 is changed):
  1. Every old trade (feedall examples: Dual / Brain / Main, same signal counted once) gets its forward candles (HOLD = 30).
  2. SPEED of a trade = the number of candles the price needed to reach +1R in its favour (never within HOLD = HOLD + 1). 1R = the trade's own stop.
  3. Market state = regime|tf (TRENDING / SIDEWAYS x 5m / 15m), same key as R4. On the OLDER days (TRAIN) the MEDIAN speed of a state sets its mode:
       SCALP        median speed <= 6 candles   -> quick profit line  1R  (rule tp1)
       SHORT_SWING  median speed <= 14 candles  -> the default line   2R  (rule tp2)
       SWING        slower                      -> let it run         3R  (rule tp3)
     A state with fewer than 15 TRAIN trades stays SHORT_SWING (= the default, nothing changes).
  4. The newest whole days (30%) = TEST. The mode rule of each state is applied ONCE to the TEST trades and compared with the fixed 2R, in R after fees (stop first when one candle touches both).
  LEARNED_MODE only if it beats the fixed 2R on TEST by 0.05 R per trade, the gain stands out of the noise (t >= 2) AND it wins on more than half of the test days, with at least 30 test trades. Otherwise EXPLORE_MODE (nothing changes).
ADVICE ONLY: nothing here opens, closes or changes a trade. The only live profit line is still the R4 one (owl_sniper_exitlearn.live_tp_r).
NOT BUILT in R6a: the weekly LOOKBACK self-tuning (owl_sniper_regime.py was not in the uploaded repo, so it was not connected blind).
API: run(d, now=None, since_days=None, persist=False), load(d), save(d, st), mode_for(d, regime, tf). CLI: python3 backend/owl_sniper_modes.py [--data DIR] [--save]"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_bridge_learn as BL
import owl_sniper_engine_c1 as C
import owl_sniper_exitlearn as XL
import owl_sniper_feed as F
import owl_sniper_feedall as FA

VERSION = "owl_sniper_modes 1 (R6a)"
PAPER_ONLY = True
FILE = "v2_sniper_modes.json"
HOLD = XL.HOLD
MODE_RULE = {"SCALP": "tp1", "SHORT_SWING": "tp2", "SWING": "tp3"}
SCALP_MAX, SWING_MIN = 6, 14            # median candles to +1R: up to 6 = SCALP, up to 14 = SHORT_SWING, slower = SWING
MIN_STATE, MIN_TEST, TEST_GAIN, T_MIN = XL.MIN_STATE, XL.MIN_TEST, XL.TEST_GAIN, XL.T_MIN
DEFAULT = XL.DEFAULT


def speed(path):
    """Candles until the price first reaches +1R in favour (1 = the first candle); HOLD + 1 when it never does."""
    for k, (fav, _adv, _cl) in enumerate(path[:HOLD]):
        if fav >= 1.0:
            return k + 1
    return HOLD + 1


def _median(xs):
    s = sorted(xs)
    n = len(s)
    return None if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0)


def mode_of(med):
    return "SHORT_SWING" if med is None else ("SCALP" if med <= SCALP_MAX else ("SHORT_SWING" if med <= SWING_MIN else "SWING"))


def learn_modes(train):
    """TRAIN items -> {state key: {"mode", "median_speed", "n"}}. A thin state keeps the default mode."""
    by, out = {}, {}
    for it in train:
        by.setdefault(it["key"], []).append(it)
    for k, its in by.items():
        med = _median([i["speed"] for i in its])
        out[k] = {"mode": mode_of(med) if len(its) >= MIN_STATE else "SHORT_SWING", "median_speed": med, "n": len(its)}
    return out


def judge(items):
    """items = [{uid, ts, key, speed, net {rule: r_net}}] -> the state dict. Pure."""
    st = {"version": VERSION, "paper_only": True, "advice_only": True, "state": "EXPLORE_MODE", "reasons": [], "modes": {}, "made": int(time.time()), "default": DEFAULT,
          "lookback": {"built": False, "why": "weekly lookback tuning needs owl_sniper_regime.py (not connected yet)"}}
    tr, te, days = XL._split(items)
    st["days"] = len(days)
    if tr is None:
        st["reasons"].append("Not enough days to judge modes: %d whole days, %d needed." % (len(days), XL.MIN_DAYS))
        return st
    st["n_train"], st["n_test"] = len(tr), len(te)
    modes = learn_modes(tr)
    st["modes"] = modes
    pick = {k: MODE_RULE[m["mode"]] for k, m in modes.items()}
    base = XL._mean([i["net"][DEFAULT] for i in te])
    got = XL._mean([i["net"][pick.get(i["key"], DEFAULT)] for i in te]) if te else None
    st["compare"] = {"test_trades": len(te), "default_mean_r": XL._r(base), "mode_mean_r": XL._r(got),
                     "test_speed_median": _median([i["speed"] for i in te])}
    if len(te) < MIN_TEST:
        st["reasons"].append("Only %d unseen trades, %d needed for a verdict." % (len(te), MIN_TEST))
    elif got - base >= TEST_GAIN and XL._days_won(te, pick) and any(v != DEFAULT for v in pick.values()):
        st["state"] = "LEARNED_MODE"
        st["reasons"].append("On unseen days the mode lines keep %.3f R per trade more than the fixed 2R, after fees (advice only, paper only)." % (got - base))
    else:
        st["reasons"].append("On unseen days the mode lines do not clearly beat the fixed 2R (needs +%.2f R per trade and more than half of the test days): nothing is changed." % TEST_GAIN)
    return st


def run(d, now=None, since_days=None, persist=False):
    """feedall examples -> paths -> speed + 3 rules -> judge. Never raises."""
    try:
        ex, x = BL.load_examples(d, 0, since_days, FA.B.SOURCES, now)
        merged, _n = FA.merge(ex)
        recs = {r["uid"]: r for r in x["recs"]}
        pairs = [(e, recs[e["uid"]]) for e in merged if e["uid"] in recs]
        pth = XL.paths(d, pairs)
        cost, items = C.cost_pct(), []
        for e, _r in pairs:
            p = pth.get(e["uid"])
            if not p:
                continue
            cr = cost / e["label"]["risk_pct"]
            items.append({"uid": e["uid"], "ts": e["entry_ts"], "key": XL._key(e), "speed": speed(p), "net": {n: XL.sim(p, n, cr) for n in ("tp1", "tp2", "tp3")}})
        items.sort(key=lambda i: i["ts"])
        st = judge(items)
        st["feed"] = {"examples": len(merged), "with_candles": len(items), "no_path": len(pairs) - len(items)}
        if persist:
            save(d, st)
        return st
    except Exception as e:
        return {"version": VERSION, "state": "EXPLORE_MODE", "reasons": ["modes learner error: %s: %s" % (type(e).__name__, str(e)[:100])], "modes": {}}


def load(d):
    return F.read_json(d, FILE)


def save(d, st):
    return F.write_json(d, FILE, st)


def mode_for(d, regime, tf):
    """SCALP / SHORT_SWING / SWING for a live state, or None (= no verdict yet). Only when the state is LEARNED_MODE."""
    try:
        st = load(d) or {}
        m = (st.get("modes") or {}).get("%s|%s" % (regime or "?", tf))
        return m["mode"] if st.get("state") == "LEARNED_MODE" and m else None
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper modes learner (paper only, read only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.data, since_days=a.since_days, persist=a.save), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
