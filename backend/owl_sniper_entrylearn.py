"""owl_sniper_entrylearn.py - OwlSniper BETTER-ENTRY LEARNER (R5). PAPER ONLY, READ ONLY: saved files + candle store (read only), writes ONE own file (v2_sniper_entrylearn.json). No network, no order code.
Owner idea: "the signal is fine, but was there a better entry?" On the SAME old trades (feedall examples, same signal once) every entry style is walked on the candles AFTER the signal. Stop and profit line stay at the signal's own PRICE levels (stop -1R, profit +2R, 30 candles, as the labels). pnl is always in the signal's own R, after fees:
    now     enter at the signal price (the default, same as the labels)
    w1/w2/w3  wait 1 / 2 / 3 candles, enter at the open of that candle. Skipped (0 R) when, before it, the stop level or the profit line was already touched (the trade is already decided: no look-ahead, only candles before the entry are used)
    pb03/pb05 limit order 0.3R / 0.5R BETTER than the signal price, valid 6 candles. If the profit line is touched first it is cancelled (0 R)
    sma6      limit order at the SMA level of the signal candle (the Z-SMA mean line), only when it lies 0.1R to 0.9R on the better side; valid 6 candles
  Fill candle of a limit order: only the stop is checked there (bad case first). A skipped / unfilled signal counts as 0 R, so the mean is PER SIGNAL (a better price that misses the winners is not hidden). fill_pct is shown per rule.
Learning = same method as the booking learner (owl_sniper_exitlearn): state regime|tf, best rule per state on TRAIN days (needs MIN_STATE signals and +MIN_GAIN R over now), judged ONCE on unseen TEST days (needs +TEST_GAIN R per signal, t >= T_MIN, and a win on more than half of the test days).
  LEARNED_ENTRY = better than entering at the signal on unseen days. ADVICE ONLY: the paper trader has no pending-order / wait engine yet, so nothing live uses it. EMA / SD-band pullbacks are NOT tested here.
API: run(d, now=None, since_days=None, persist=False), load(d), save(d, st), sim_entry(path, rule, cost_r, u_sma). CLI: python3 backend/owl_sniper_entrylearn.py [--data DIR] [--save]"""
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

VERSION = "owl_sniper_entrylearn 1 (R5)"
PAPER_ONLY = True
FILE = "v2_sniper_entrylearn.json"
DEFAULT = "now"
STOP, TARGET, WINDOW = -1.0, 2.0, 6
RULES = {"now": ("mkt", 0), "w1": ("mkt", 1), "w2": ("mkt", 2), "w3": ("mkt", 3), "pb03": ("lim", 0.3), "pb05": ("lim", 0.5), "sma6": ("sma", None)}
MIN_STATE, MIN_TEST, MIN_GAIN, TEST_GAIN, T_MIN = XL.MIN_STATE, XL.MIN_TEST, XL.MIN_GAIN, XL.TEST_GAIN, XL.T_MIN


def _path4(fut, rec, risk):
    """Forward candles -> [(open_r, fav_r, adv_r, close_r)] in R of the signal price, signed WITH the trade direction (adv <= 0 = against the trade)."""
    e, d = rec["entry_price"], 1.0 if rec["side"] == "LONG" else -1.0
    f = lambda x: d * (x / e - 1.0) * 100.0 / risk
    out = []
    for cd in fut[:XL.HOLD]:
        hi, lo = (cd[2], cd[3]) if d > 0 else (cd[3], cd[2])
        out.append((f(cd[1]), f(hi), f(lo), f(cd[4])))
    return out


def _run_from(path, k, u_e, check_target):
    """Trade is in at u_e from candle k on. -> exit level in R. check_target=False: the fill candle only checks the stop."""
    for j in range(k, len(path)):
        _o, fav, adv, cl = path[j]
        if adv <= STOP:
            return STOP
        if fav >= TARGET and (check_target or j > k):
            return TARGET
    return path[-1][3]


def sim_entry(path, rule, cost_r, u_sma=None):
    """One signal, one entry style -> (pnl in R after fees, filled) ; (0.0, False) when no trade happens."""
    kind, v = RULES[rule]
    if kind == "mkt":
        for j in range(v):                                           # only candles BEFORE the entry are known
            if path[j][2] <= STOP or path[j][1] >= TARGET:
                return 0.0, False
        u_e = 0.0 if v == 0 else path[v][0]
        if u_e <= STOP or u_e >= TARGET:
            return 0.0, False
        return _run_from(path, v, u_e, True) - u_e - cost_r, True
    level = -v if kind == "lim" else u_sma
    if level is None or not (-0.9 <= level <= -0.1):
        return 0.0, False
    for j in range(min(WINDOW, len(path))):
        if path[j][2] <= level:                                      # filled in this candle
            return _run_from(path, j, level, False) - level - cost_r, True
        if path[j][1] >= TARGET:                                     # ran away without us: cancel
            return 0.0, False
    return 0.0, False


def _u_sma(ex, risk):
    """SMA level in R of the signal price, signed with the trade direction (negative = on the better side). None when unknown."""
    try:
        dist = float((ex.get("extra") or {}).get("dist_sma_pct"))
        return (-dist if ex["side"] == "LONG" else dist) / risk
    except (TypeError, ValueError, KeyError, ZeroDivisionError):
        return None


def judge(items):
    """items = [{uid, ts, key, net {rule: pnl R}, fill {rule: bool}}] -> state dict. Pure."""
    st = {"version": VERSION, "paper_only": True, "advice_only": True, "state": "EXPLORE_ENTRY", "reasons": [], "rules": {}, "made": int(time.time()), "default": DEFAULT}
    st["fill_pct"] = {n: round(100.0 * sum(1 for i in items if i["fill"][n]) / len(items), 1) for n in RULES} if items else {}
    st["mean_r_all"] = {n: XL._r(XL._mean([i["net"][n] for i in items])) for n in RULES}
    tr, te, days = XL._split(items)
    st["days"] = len(days)
    if tr is None:
        st["reasons"].append("Not enough days to judge entries: %d whole days, %d needed." % (len(days), XL.MIN_DAYS))
        return st
    st["n_train"], st["n_test"] = len(tr), len(te)
    pick = XL._best(tr, list(RULES), DEFAULT)
    st["rules"] = pick
    base = XL._mean([i["net"][DEFAULT] for i in te])
    got = XL._mean([i["net"][pick.get(i["key"], DEFAULT)] for i in te])
    st["compare"] = {"test_signals": len(te), "now_mean_r": XL._r(base), "learned_mean_r": XL._r(got), "by_rule_test": {n: XL._r(XL._mean([i["net"][n] for i in te])) for n in RULES}}
    if len(te) < MIN_TEST:
        st["reasons"].append("Only %d unseen signals, %d needed for a verdict." % (len(te), MIN_TEST))
    elif got - base >= TEST_GAIN and XL._days_won(te, pick, DEFAULT) and any(v != DEFAULT for v in pick.values()):
        st["state"] = "LEARNED_ENTRY"
        st["reasons"].append("On unseen days the learned entry keeps %.3f R per signal more than entering at the signal, after fees (advice only: no wait / limit engine yet)." % (got - base))
    else:
        st["reasons"].append("On unseen days no entry style clearly beats entering at the signal (needs +%.2f R per signal and more than half of the test days): nothing to change." % TEST_GAIN)
    return st


def run(d, now=None, since_days=None, persist=False):
    """feedall examples -> candles after the signal -> every entry style -> judge. Never raises."""
    try:
        ex, x = BL.load_examples(d, 0, since_days, FA.B.SOURCES, now)
        merged, _n = FA.merge(ex)
        recs = {r["uid"]: r for r in x["recs"]}
        pairs = [(e, recs[e["uid"]]) for e in merged if e["uid"] in recs]
        pth = XL.paths(d, pairs, _path4)
        cost, items = C.cost_pct(), []
        for e, _r_ in pairs:
            p = pth.get(e["uid"])
            if not p:
                continue
            risk = e["label"]["risk_pct"]
            cr, us = cost / risk, _u_sma(e, risk)
            res = {n: sim_entry(p, n, cr, us) for n in RULES}
            items.append({"uid": e["uid"], "ts": e["entry_ts"], "key": XL._key(e), "net": {n: r[0] for n, r in res.items()}, "fill": {n: r[1] for n, r in res.items()}})
        items.sort(key=lambda i: i["ts"])
        st = judge(items)
        st["feed"] = {"examples": len(merged), "with_candles": len(items), "no_path": len(pairs) - len(items)}
        if persist:
            save(d, st)
        return st
    except Exception as e:
        return {"version": VERSION, "state": "EXPLORE_ENTRY", "reasons": ["entry learner error: %s: %s" % (type(e).__name__, str(e)[:100])], "rules": {}}


def load(d):
    return F.read_json(d, FILE)


def save(d, st):
    return F.write_json(d, FILE, st)


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper better-entry learner (paper only, read only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.data, since_days=a.since_days, persist=a.save), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
