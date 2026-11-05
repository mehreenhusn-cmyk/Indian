"""owl_sniper_tpsl.py - OwlSniper TP/SL COMBO LEARNER (R32a, Part 6). PAPER ONLY, READ ONLY: reads saved trades + the candle store (read only), writes ONE own file (v2_sniper_tpsl.json). No network, no order code.
Owner problem: "profit booked late or too early, stop too tight or too loose". The booking learner (owl_sniper_exitlearn) moves only the PROFIT line. This file moves BOTH lines together:
  profit line TPS x stop line SLS, both in R of the trade's own engine stop (1R = that stop). Grid TPS (1, 1.5, 2, 3) x SLS (0.75, 1, 1.5) = 12 combos, default = tp2_sl1 (the Sniper's own 2R / 1R).
  Every old trade (same examples + same candle paths as the booking learner) is walked with all 12 combos. If one candle touches the stop and the profit line, the STOP counts first. Result = r_net in R of the engine stop, after fee + slippage, so the 12 numbers are comparable.
Learning: market state = regime|tf. Older days = TRAIN: per state the best combo by mean r_net (needs MIN_STATE trades and MIN_GAIN over the default). STEADY test: the pick must also beat the default in BOTH halves of the train days, else the default stays. Newest whole days (30%) = TEST: the choice is applied ONCE.
LEARNED_TPSL only if the choice beats the default on TEST by TEST_GAIN, on more than half of the test days, and clearly above noise (t >= 2). Otherwise EXPLORE_TPSL (nothing changes). A combo whose new stop would be outside the allowed stop size keeps the default (same rule live and in the test). NOT a profit promise.
API: run(d, now=None, since_days=None, persist=False), load(d), save(d, st), live_combo(d, regime, tf), apply(d, order, tf), sim_combo(path, k_tp, k_sl, cost_r). CLI: python3 backend/owl_sniper_tpsl.py [--data DIR] [--save]"""
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

VERSION = "owl_sniper_tpsl 1 (R32a)"
PAPER_ONLY = True
FILE = "v2_sniper_tpsl.json"
OFF_FILE = "v2_tpsl_off"                 # owner switch: this file in the data folder = the paper LEARN lane keeps the default stop and profit line
HOLD = C.MAX_HOLD
TPS, SLS = (1.0, 1.5, 2.0, 3.0), (0.75, 1.0, 1.5)
DEFAULT = "tp2_sl1"


def _name(k_tp, k_sl):
    return "tp%g_sl%g" % (k_tp, k_sl)


COMBOS = {_name(t, s): (t, s) for s in SLS for t in TPS}
assert DEFAULT in COMBOS


def sim_combo(path, k_tp, k_sl, cost_r):
    """One trade (path = [(fav_r, adv_r, close_r)] per candle, from owl_sniper_exitlearn) walked with one combo -> r_net in R of the engine stop. Stop first when one candle touches both lines."""
    gross = None
    for k, (fav, adv, cl) in enumerate(path[:HOLD]):
        if adv <= -k_sl:
            gross = -k_sl
            break
        if fav >= k_tp:
            gross = k_tp
            break
        if k == min(HOLD, len(path)) - 1:
            gross = cl
    if gross is None:
        gross = path[-1][2]
    return gross - cost_r


def _fits(risk_pct, k_sl):
    return C.MIN_SL_PCT <= risk_pct * k_sl <= C.MAX_SL_PCT


def _nets(path, risk_pct):
    """All 12 combos for one trade. A combo whose stop would be refused gets the default's result (the live lane keeps the default then)."""
    cr = C.cost_pct() / risk_pct
    base = sim_combo(path, 2.0, 1.0, cr)
    return {n: (sim_combo(path, t, s, cr) if _fits(risk_pct, s) else base) for n, (t, s) in COMBOS.items()}


def _steady(train, key, name):
    """True when `name` beats the default in BOTH halves (by time) of the train trades of this state."""
    its = [i for i in train if i["key"] == key]
    h = len(its) // 2
    for part in (its[:h], its[h:]):
        if not part or XL._mean([i["net"][name] for i in part]) <= XL._mean([i["net"][DEFAULT] for i in part]):
            return False
    return True


def judge(items):
    """items = [{uid, ts, key, net {combo: r_net}}] sorted by ts -> the state dict. Pure."""
    st = {"version": VERSION, "paper_only": True, "state": "EXPLORE_TPSL", "reasons": [], "rules": {}, "made": int(time.time()), "default": DEFAULT, "grid": {}}
    tr, te, days = XL._split(items)
    st["days"] = len(days)
    if tr is None:
        st["reasons"].append("Not enough days to judge stop + profit lines: %d whole days, %d needed." % (len(days), XL.MIN_DAYS))
        return st
    st["n_train"], st["n_test"] = len(tr), len(te)
    pick = XL._best(tr, list(COMBOS), DEFAULT)
    for k in list(pick):
        if pick[k] != DEFAULT and not _steady(tr, k, pick[k]):
            pick[k] = DEFAULT                                         # won only in one half of the train days = luck, not learning
    st["rules"] = pick
    base = XL._mean([i["net"][DEFAULT] for i in te])
    got = XL._mean([i["net"][pick.get(i["key"], DEFAULT)] for i in te]) if te else None
    st["grid"] = {n: {"train": XL._r(XL._mean([i["net"][n] for i in tr])), "test": XL._r(XL._mean([i["net"][n] for i in te]))} for n in COMBOS}
    st["compare"] = {"test_trades": len(te), "default_mean_r": XL._r(base), "choice_mean_r": XL._r(got)}
    if len(te) < XL.MIN_TEST:
        st["reasons"].append("Only %d unseen trades, %d needed for a verdict." % (len(te), XL.MIN_TEST))
    elif got - base >= XL.TEST_GAIN and XL._days_won(te, pick, DEFAULT) and any(v != DEFAULT for v in pick.values()):
        st["state"] = "LEARNED_TPSL"
        st["reasons"].append("On unseen days the learned stop + profit lines keep %.3f R per trade more than the fixed 1R stop / 2R profit, after fees (paper only)." % (got - base))
    else:
        st["reasons"].append("On unseen days the learned lines do not clearly beat the fixed 1R stop / 2R profit (needs +%.2f R per trade, more than half of the test days, and a result above noise): nothing is changed." % XL.TEST_GAIN)
    return st


def run(d, now=None, since_days=None, persist=False):
    """feedall examples -> candle paths -> 12 combos each -> judge. Never raises."""
    try:
        ex, x = BL.load_examples(d, 0, since_days, FA.B.SOURCES, now)
        merged, _n = FA.merge(ex)
        recs = {r["uid"]: r for r in x["recs"]}
        pairs = [(e, recs[e["uid"]]) for e in merged if e["uid"] in recs]
        pth, items = XL.paths(d, pairs), []
        for e, _r in pairs:
            p = pth.get(e["uid"])
            if p:
                items.append({"uid": e["uid"], "ts": e["entry_ts"], "key": XL._key(e), "net": _nets(p, e["label"]["risk_pct"])})
        items.sort(key=lambda i: i["ts"])
        st = judge(items)
        st["feed"] = {"examples": len(merged), "with_candles": len(items), "no_path": len(pairs) - len(items)}
        if persist:
            save(d, st)
        return st
    except Exception as e:
        return {"version": VERSION, "state": "EXPLORE_TPSL", "reasons": ["combo learner error: %s: %s" % (type(e).__name__, str(e)[:100])], "rules": {}}


def load(d):
    return F.read_json(d, FILE)


def save(d, st):
    return F.write_json(d, FILE, st)


def live_combo(d, regime, tf):
    """(k_tp, k_sl) for a new paper LEARN trade, or None (= keep the default). Only when the state is LEARNED_TPSL and the switch file is absent."""
    try:
        if os.path.exists(os.path.join(os.path.realpath(d), OFF_FILE)):
            return None
        st = load(d) or {}
        name = (st.get("rules") or {}).get("%s|%s" % (regime or "?", tf))
        return COMBOS[name] if st.get("state") == "LEARNED_TPSL" and name in COMBOS and name != DEFAULT else None
    except Exception:
        return None


def apply(d, o, tf):
    """The paper LEARN order with the learned stop AND profit line (R multiples of its own stop distance). Entry, size and side stay. Any problem, a refused stop size or the switch = the order is returned as it is."""
    try:
        c = live_combo(d, o.get("regime"), tf)
        e, sl = float(o["entry"]), float(o["stop"])
        if not c or e <= 0 or abs(e - sl) <= 0:
            return o
        risk, sgn = abs(e - sl), 1.0 if o["side"] == "LONG" else -1.0
        pct = risk * c[1] / e * 100.0
        if not _fits(risk / e * 100.0, c[1]):
            return o
        return dict(o, stop=e - sgn * risk * c[1], take_profit=e + sgn * risk * c[0], stop_pct=round(pct, 3), exit_rule="tp%gR_sl%gR" % c)
    except Exception:
        return o


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper TP/SL combo learner (paper only, read only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.data, since_days=a.since_days, persist=a.save), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
