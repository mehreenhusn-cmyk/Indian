"""owl_sniper_exitlearn.py - OwlSniper BOOKING LEARNER (R4). PAPER ONLY, READ ONLY: reads saved files + the candle store (read only), writes ONE own file (v2_sniper_exitlearn.json). No network, no order code.
Owner problem: "the entry is fine, the profit is booked late or too early". This file asks one question on the SAME old trades: which EXIT would have kept more R after fees?
  Every example of owl_sniper_feedall (Dual / Brain / Main trades, replayed, same signal counted once) gets its forward candles (HOLD = 30). The same trade is then walked with several exit rules, always in R (1R = its own stop):
    tp1 / tp1_5 / tp2 / tp3   fixed profit line (tp2 = the Sniper's own default, K_TP 2R / K_SL 1R)          -> LIVE-capable (the paper trade only needs another take-profit price)
    be05 / be1                profit line 2R, once +0.5R / +1R is seen the stop moves to the entry ("never let a profit turn into a loss")
    trail1                    profit line 3R, once +1R is seen the stop trails 1R behind the best price
    t6 / t12                  profit line 1.5R / 2R but closed at the close of candle 6 / 12 (time exit)       -> be/trail/time rules are ADVICE only until the paper trader has an exit engine
  Same honesty as the labels: if one candle touches the stop and a profit line, the STOP counts first (stop level of the candle before). Cost = fee + slippage (engine cost_pct) / 1R.
  LEFT ON THE TABLE = best price move after entry (mfe_r) minus what the default booked (r_gross). Shown as numbers, never hidden.
Learning: market state = regime|tf (TRENDING / SIDEWAYS x 5m / 15m). Older days = TRAIN: per state the best rule by mean r_net (needs MIN_STATE trades and a MIN_GAIN edge over tp2, else tp2 stays). Newest whole days (30%) = TEST: the choice is applied ONCE. Needs 6 whole days.
  LEARNED_EXIT only if the LIVE-capable choice beats tp2 on the TEST days after fees by TEST_GAIN AND on more than half of the test days. Otherwise EXPLORE_EXIT (nothing changes). NOT a profit promise.
API: run(d, now=None, since_days=None, persist=False), load(d), save(d, st), live_tp_r(d, regime, tf), sim(path, rule, cost_r). CLI: python3 backend/owl_sniper_exitlearn.py [--data DIR] [--save]"""
import argparse
import bisect
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_bridge_learn as BL
import owl_sniper_engine_c1 as C
import owl_sniper_feed as F
import owl_sniper_feedall as FA
import owl_sniper_tf as TF
import v2_defs as D
import v2_setup_finder as SF

VERSION = "owl_sniper_exitlearn 1 (R4)"
PAPER_ONLY = True
FILE = "v2_sniper_exitlearn.json"
OFF_FILE = "v2_exitlearn_off"           # owner switch: this file in the data folder = the paper LEARN lane keeps the default 2R profit line
HOLD = C.MAX_HOLD
DEFAULT = "tp2"
# name: (profit line in R, move-stop-to-entry at R or None, trail 1R behind the best after this R or None, max candles)
RULES = {"tp1": (1.0, None, None, HOLD), "tp1_5": (1.5, None, None, HOLD), "tp2": (2.0, None, None, HOLD), "tp3": (3.0, None, None, HOLD),
         "be05": (2.0, 0.5, None, HOLD), "be1": (2.0, 1.0, None, HOLD), "trail1": (3.0, 1.0, 1.0, HOLD), "t6": (1.5, None, None, 6), "t12": (2.0, None, None, 12)}
LIVE = tuple(k for k, v in RULES.items() if v[1] is None and v[2] is None and v[3] == HOLD)     # only the profit line differs = the paper trade can do it today
MIN_DAYS, MIN_STATE, MIN_TEST = 6, 15, 30
MIN_GAIN = 0.02                         # R per trade a rule must win on TRAIN to replace the default
T_MIN = 2.0                             # paired t-value the test gain must reach (a lucky pick among several rules is common)
TEST_GAIN = 0.05                        # R per trade the learned choice must win on TEST, AND it must win on more than half of the test days (one lucky day is not learning)


def _path(fut, rec, risk):
    """Forward candles -> [(fav_r, adv_r, close_r)] per candle, signed with the trade direction (adv is <= 0 when the price goes against the trade)."""
    e, d = rec["entry_price"], 1.0 if rec["side"] == "LONG" else -1.0
    out = []
    for cd in fut[:HOLD]:
        hi, lo = (cd[2], cd[3]) if d > 0 else (cd[3], cd[2])
        out.append((d * (hi / e - 1.0) * 100.0 / risk, d * (lo / e - 1.0) * 100.0 / risk, d * (cd[4] / e - 1.0) * 100.0 / risk))
    return out


def sim(path, rule, cost_r):
    """One trade walked with one rule -> r_net. Stop first when a candle touches the stop and the profit line."""
    tp, be_at, trail, bars = RULES[rule]
    stop, best, gross = -1.0, 0.0, None
    for k, (fav, adv, cl) in enumerate(path[:bars]):
        if adv <= stop:
            gross = stop
            break
        best = max(best, fav)
        if fav >= tp:
            gross = tp
            break
        if be_at is not None and best >= be_at:
            stop = max(stop, 0.0)
        if trail is not None and best >= trail:
            stop = max(stop, best - 1.0)
        if k == min(bars, len(path)) - 1:
            gross = cl
    if gross is None:
        gross = path[-1][2]
    return gross - cost_r


def _fut(runs, e_ts, step):
    for run in runs:
        j = bisect.bisect_left([c[0] for c in run], e_ts - 1e-6)
        if j < len(run):
            return None if run[j][0] - e_ts > step + 1e-6 else run[j:j + HOLD]
    return None


def paths(d, pairs, maker=None):
    """pairs = [(example, record)] -> {uid: path} (maker(fut, rec, risk) builds one path, default = _path; R5 passes its own). Candles are read once per coin + interval, read only. A trade with a missing or short candle window is left out (counted by the caller)."""
    out, groups = {}, {}
    for ex, rec in pairs:
        groups.setdefault((rec["symbol"], rec["tf"]), []).append((ex, rec))
    con = F.open_ro(d) if groups else None
    if con is None:
        return out
    try:
        for (sym, tf), g in groups.items():
            try:
                step, base = TF.step(tf), TF.base(tf)
                lo, hi = min(r["entry_ts"] for _e, r in g), max(r["entry_ts"] for _e, r in g)
                good, _bad = D.clean_candles(D.candles_from_store(con, sym, base, lo - TF.step(base), hi + (HOLD + 2) * step), base)
                runs = [x for x in (TF.aggregate(r, tf) for r in SF.runs(good, base)) if x]
                for ex, rec in g:
                    fut = _fut(runs, rec["entry_ts"], step)
                    if fut and len(fut) >= HOLD:
                        out[ex["uid"]] = (maker or _path)(fut, rec, ex["label"]["risk_pct"])
            except Exception:                                         # one bad coin never stops the others
                continue
    finally:
        con.close()
    return out


def _key(ex):
    return "%s|%s" % (ex.get("regime") or "?", ex.get("tf") or "?")


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _r(x):
    return None if x is None else round(x, 4)


def _split(items):
    days = sorted({int(it["ts"] // 86400) for it in items})
    if len(days) < MIN_DAYS:
        return None, None, days
    cut = days[-max(1, int(round(len(days) * 0.3)))]
    return [i for i in items if int(i["ts"] // 86400) < cut], [i for i in items if int(i["ts"] // 86400) >= cut], days


def _best(train, names, base=DEFAULT):
    """Best rule per state by mean r_net on TRAIN. The default stays unless a rule wins by MIN_GAIN with MIN_STATE trades."""
    by, pick = {}, {}
    for it in train:
        by.setdefault(it["key"], []).append(it)
    for k, its in by.items():
        pick[k] = base
        if len(its) >= MIN_STATE:
            m = {n: _mean([i["net"][n] for i in its]) for n in names}
            top = max(names, key=lambda n: m[n])
            if m[top] - m[base] >= MIN_GAIN:
                pick[k] = top
    return pick


def _days_won(te, pick, base=DEFAULT):
    """True when the learned choice beat the default on MORE THAN HALF of the test days AND the gain is clearly above noise (t >= T_MIN)."""
    by = {}
    for i in te:
        by.setdefault(int(i["ts"] // 86400), []).append(i["net"][pick.get(i["key"], base)] - i["net"][base])
    diffs = [i["net"][pick.get(i["key"], base)] - i["net"][base] for i in te]
    n = len(diffs)
    m = sum(diffs) / n if n else 0.0
    sd = (sum((x - m) ** 2 for x in diffs) / (n - 1)) ** 0.5 if n > 1 else 0.0
    t_ok = sd > 0 and m / (sd / n ** 0.5) >= T_MIN                 # the gain must stand out of the noise (one-sided t)
    return t_ok and sum(1 for v in by.values() if sum(v) > 0) * 2 > len(by)


def judge(items):
    """items = [{uid, ts, key, net {rule: r_net}, left}] -> the state dict. Pure."""
    st = {"version": VERSION, "paper_only": True, "state": "EXPLORE_EXIT", "reasons": [], "rules": {}, "advice": {}, "made": int(time.time()), "default": DEFAULT}
    st["left_on_table"] = {"n": len(items), "mean_r": _r(_mean([i["left"] for i in items])),
                           "reached_1r_then_lost": sum(1 for i in items if i["hit1"] and i["net"][DEFAULT] <= 0)}
    tr, te, days = _split(items)
    st["days"] = len(days)
    if tr is None:
        st["reasons"].append("Not enough days to judge exits: %d whole days, %d needed." % (len(days), MIN_DAYS))
        return st
    st["n_train"], st["n_test"] = len(tr), len(te)
    live, anyr = _best(tr, LIVE), _best(tr, list(RULES))
    st["rules"], st["advice"] = live, anyr
    n_te = len(te)
    base = _mean([i["net"][DEFAULT] for i in te])
    got_live = _mean([i["net"][live.get(i["key"], DEFAULT)] for i in te])
    got_any = _mean([i["net"][anyr.get(i["key"], DEFAULT)] for i in te]) if te else None
    st["compare"] = {"test_trades": n_te, "default_mean_r": _r(base), "live_choice_mean_r": _r(got_live), "any_choice_mean_r": _r(got_any),
                     "by_rule_test": {n: _r(_mean([i["net"][n] for i in te])) for n in RULES}}
    if n_te < MIN_TEST:
        st["reasons"].append("Only %d unseen trades, %d needed for a verdict." % (n_te, MIN_TEST))
    elif got_live - base >= TEST_GAIN and _days_won(te, live) and any(v != DEFAULT for v in live.values()):
        st["state"] = "LEARNED_EXIT"
        st["reasons"].append("On unseen days the learned profit line keeps %.3f R per trade more than the fixed 2R, after fees (paper only)." % (got_live - base))
    else:
        st["reasons"].append("On unseen days the learned profit line does not clearly beat the fixed 2R (needs +%.2f R per trade and more than half of the test days): nothing is changed." % TEST_GAIN)
    if got_any is not None and got_any - base >= MIN_GAIN:
        st["reasons"].append("Advice: break-even / trail / time rules would give %.3f R more on unseen days, but they need an exit engine in the paper trader (not built yet)." % (got_any - base))
    return st


def run(d, now=None, since_days=None, persist=False):
    """feedall examples -> paths -> every rule -> judge. Never raises."""
    try:
        ex, x = BL.load_examples(d, 0, since_days, FA.B.SOURCES, now)
        merged, _n = FA.merge(ex)
        recs = {r["uid"]: r for r in x["recs"]}
        pairs = [(e, recs[e["uid"]]) for e in merged if e["uid"] in recs]
        pth = paths(d, pairs)
        cost, items = C.cost_pct(), []
        for e, _r_ in pairs:
            p = pth.get(e["uid"])
            if not p:
                continue
            lb = e["label"]
            cr = cost / lb["risk_pct"]
            items.append({"uid": e["uid"], "ts": e["entry_ts"], "key": _key(e), "net": {n: sim(p, n, cr) for n in RULES}, "hit1": bool(lb.get("hit_1r")), "left": lb["mfe_r"] - lb["r_gross"]})
        items.sort(key=lambda i: i["ts"])
        st = judge(items)
        st["feed"] = {"examples": len(merged), "with_candles": len(items), "no_path": len(pairs) - len(items)}
        if persist:
            save(d, st)
        return st
    except Exception as e:
        return {"version": VERSION, "state": "EXPLORE_EXIT", "reasons": ["exit learner error: %s: %s" % (type(e).__name__, str(e)[:100])], "rules": {}}


def load(d):
    return F.read_json(d, FILE)


def save(d, st):
    return F.write_json(d, FILE, st)


def live_tp_r(d, regime, tf):
    """Profit line in R for a new paper LEARN trade, or None (= keep the default 2R). Only when the state is LEARNED_EXIT, the switch file is absent and the rule is LIVE-capable."""
    try:
        if os.path.exists(os.path.join(os.path.realpath(d), OFF_FILE)):
            return None
        st = load(d) or {}
        name = (st.get("rules") or {}).get("%s|%s" % (regime or "?", tf))
        return RULES[name][0] if st.get("state") == "LEARNED_EXIT" and name in LIVE and name != DEFAULT else None
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper booking learner (paper only, read only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.data, since_days=a.since_days, persist=a.save), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
