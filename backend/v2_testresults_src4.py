"""v2_testresults_src4.py - R12 / EXIT STUDY: 9 EXIT RULES x MARKET STATE. PAPER ONLY, READ ONLY. Family "exitrule" in the TestResult shape + one table object `exit_table` for the Lab card.
Question: "which exit is best in which market?" The SAME replayed old trades the booking learner (R4, owl_sniper_exitlearn) uses (Dual / Brain / Main, same signal once, all saved days, 1R = own stop, fees in) are walked with the SAME 9 rules (tp1, tp1_5, tp2 = the default, tp3, be05, be1, trail1, t6, t12).
  TABLE: per market state (regime|tf, e.g. TRENDING|5m) the mean R after fees of every rule, so the owner sees the whole grid, not only a winner.
  JUDGMENT per state, the same method as R4 (one honest test, no peeking): the OLDER 70% of the days pick the best rule (needs 15 trades in the state and +0.02 R over tp2, else tp2 stays); the NEWEST 30% of the days judge that pick ONCE against tp2, paired per trade.
    EDGE            the pick beats tp2 by 0.05 R or more per trade on the unseen days AND paired t >= 2 AND on more than half of the unseen days.
    DIAGNOSIS_ONLY  a gain of 0.02 R or more that is not proven (too few trades or one lucky day).
    NO_EDGE         tp2 stayed, or the pick did not beat tp2.
    NOT_ENOUGH_DATA fewer than 6 whole days, or fewer than 20 unseen trades in the state.
  A profit-line pick (tp1 / tp1_5 / tp3) can run in the paper LEARN lane (R4); break-even / trail / time picks are ADVICE ONLY until the paper trader has an exit engine. use_in_sniper is always false here. Not a profit promise.
refresh(d, now) = the heavy replay (slow loop only), writes ONLY v2_lab_exit.json. collect(d, now) / exit_table(d, now) = cheap reads. Never raise. No network, no order code."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_feed as F
import v2_testresults as T

VERSION = "v2_testresults_src4 1 (R12)"
FILE = "v2_lab_exit.json"
MIN_TEST_STATE = 20            # unseen trades one state needs before it may leave NOT_ENOUGH_DATA (R4 asks 30 for all states together)
DESC = {"tp1": "Profit line 1R", "tp1_5": "Profit line 1.5R", "tp2": "Profit line 2R (the default)", "tp3": "Profit line 3R", "be05": "2R line, stop to the entry after +0.5R",
        "be1": "2R line, stop to the entry after +1R", "trail1": "3R line, stop trails 1R behind the best price after +1R", "t6": "1.5R line, closed at candle 6", "t12": "2R line, closed at candle 12"}
CAV = "Replay of old trades after fees, 1R = the trade's own stop. The rule was picked on older days and judged once on unseen days. Not a profit promise."


def _xl():
    import owl_sniper_exitlearn as XL           # lazy: it pulls the candle / bridge modules
    return XL


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _r(x):
    return None if x is None else round(x, 4)


def _t(diffs):
    n = len(diffs)
    if n < 2:
        return 0.0
    m = sum(diffs) / n
    sd = (sum((x - m) ** 2 for x in diffs) / (n - 1)) ** 0.5
    return m / (sd / n ** 0.5) if sd > 0 else 0.0


def _judge(row, XL):
    """One state -> (verdict, plain sentence). Pure."""
    te = row.get("test")
    if not te:
        return "NOT_ENOUGH_DATA", "Not enough whole days to split into older and unseen days (%d needed)." % XL.MIN_DAYS
    if te["n"] < MIN_TEST_STATE:
        return "NOT_ENOUGH_DATA", "Only %d unseen trades in this state, %d needed." % (te["n"], MIN_TEST_STATE)
    if row["pick"] == XL.DEFAULT:
        return "NO_EDGE", "No rule beat the fixed 2R on the older days, so tp2 stays."
    g = te["gain_r"]
    if g >= XL.TEST_GAIN and te["t"] >= XL.T_MIN and te["days_won"] * 2 > te["days"]:
        return "EDGE", "%s keeps %+.3f R per trade more than the fixed 2R on unseen days (t %.1f, better on %d of %d days)." % (row["pick"], g, te["t"], te["days_won"], te["days"])
    if g >= XL.MIN_GAIN:
        return "DIAGNOSIS_ONLY", "%s kept %+.3f R per trade more on unseen days, but it is not proven (t %.1f, better on %d of %d days)." % (row["pick"], g, te["t"], te["days_won"], te["days"])
    return "NO_EDGE", "%s did not beat the fixed 2R on unseen days (%+.3f R per trade)." % (row["pick"], g)


def table(items, now=None):
    """items = [{ts, key, net {rule: r_net}}] -> the exit_table dict. Pure."""
    XL = _xl()
    now = int(time.time() if now is None else now)
    names = list(XL.RULES)
    tr, te, days = XL._split(items)
    out = {"version": VERSION, "made": now, "state": "OK" if items else "NO_TRADES", "n": len(items), "days": len(days), "default": XL.DEFAULT, "live": list(XL.LIVE),
           "rules": [{"name": n, "live": n in XL.LIVE, "text": DESC.get(n, n)} for n in names], "all": {"n": len(items), "mean": {n: _r(_mean([i["net"][n] for i in items])) for n in names}}, "states": []}
    by = {}
    for i in items:
        by.setdefault(i["key"], []).append(i)
    for key, its in sorted(by.items(), key=lambda kv: -len(kv[1])):
        rg, _s, tf = key.partition("|")
        row = {"key": key, "regime": rg, "tf": tf, "n": len(its), "mean": {n: _r(_mean([i["net"][n] for i in its])) for n in names}, "pick": None, "test": None}
        if tr is not None:
            trk, tek = [i for i in tr if i["key"] == key], [i for i in te if i["key"] == key]
            row["train_n"], row["pick"] = len(trk), XL.DEFAULT
            if len(trk) >= XL.MIN_STATE:
                m = {n: _mean([i["net"][n] for i in trk]) for n in names}
                top = max(names, key=lambda n: m[n])
                if m[top] - m[XL.DEFAULT] >= XL.MIN_GAIN:
                    row["pick"] = top
            diffs = [i["net"][row["pick"]] - i["net"][XL.DEFAULT] for i in tek]
            byday = {}
            for i, dv in zip(tek, diffs):
                byday.setdefault(int(i["ts"] // 86400), []).append(dv)
            if tek:
                row["test"] = {"n": len(tek), "default_mean_r": _r(_mean([i["net"][XL.DEFAULT] for i in tek])), "pick_mean_r": _r(_mean([i["net"][row["pick"]] for i in tek])),
                               "gain_r": _r(_mean(diffs)), "t": round(_t(diffs), 2), "days": len(byday), "days_won": sum(1 for v in byday.values() if sum(v) > 0)}
        row["verdict"], row["text"] = _judge(row, XL)
        out["states"].append(row)
    c = {}
    for s in out["states"]:
        c[s["verdict"]] = c.get(s["verdict"], 0) + 1
    out["line"] = ("%d trades, %d market states: %s." % (len(items), len(out["states"]), ", ".join("%d %s" % (v, k.replace("_", " ").lower()) for k, v in sorted(c.items())))) if items else "No old trade with candles yet."
    return out


def build(d, now):
    """The heavy replay, the same first half as owl_sniper_exitlearn.run (feedall examples -> candle paths -> every rule). Raises on a broken source; refresh() catches it."""
    import owl_sniper_bridge_learn as BL
    import owl_sniper_engine_c1 as C
    import owl_sniper_feedall as FA
    XL = _xl()
    ex, x = BL.load_examples(d, 0, None, FA.B.SOURCES, now)
    merged, _n = FA.merge(ex)
    recs = {r["uid"]: r for r in x["recs"]}
    pairs = [(e, recs[e["uid"]]) for e in merged if e["uid"] in recs]
    pth, cost, items = XL.paths(d, pairs), C.cost_pct(), []
    for e, _r_ in pairs:
        p = pth.get(e["uid"])
        if p:
            cr = cost / e["label"]["risk_pct"]
            items.append({"ts": e["entry_ts"], "key": XL._key(e), "net": {n: XL.sim(p, n, cr) for n in XL.RULES}})
    items.sort(key=lambda i: i["ts"])
    return table(items, now)


def refresh(d, now=None):
    now = int(time.time() if now is None else now)
    try:
        ok = F.write_json(d, FILE, build(d, now))
        return {"exitrule": "saved" if ok else "not saved (folder not writable)"}
    except Exception as e:
        return {"exitrule": "error: %s: %s" % (type(e).__name__, str(e)[:80])}


def _rows(tb, ago, src=FILE):
    XL = _xl()
    out = []
    for s in tb.get("states") or []:
        te, v = s.get("test") or {}, s["verdict"]
        pick = s.get("pick")
        title = "Exit rule, %s %s" % (str(s["regime"]).lower(), s["tf"])
        head = {"EDGE": "%s: %s beats the 2R exit on unseen days" % (title, pick), "DIAGNOSIS_ONLY": "%s: %s looks better, not proven" % (title, pick),
                "NO_EDGE": "%s: the fixed 2R stays" % title, "NOT_ENOUGH_DATA": "%s: not enough unseen trades yet" % title}[v]
        cav = CAV + ("" if pick in (None, XL.DEFAULT) else (" A profit-line pick can run in the paper LEARN lane." if pick in XL.LIVE else " Break-even / trail / time rules are advice only: no exit engine yet."))
        out.append(T.simple("exitrule", s["key"], title, v, "", head, s.get("text", ""), te.get("n") or s.get("n"), MIN_TEST_STATE, context="%s, %d trades in all" % (s["key"], s["n"]), exp_r=te.get("pick_mean_r"), lift_r=te.get("gain_r"), caveat=cav, ago=ago, source=src))
    return out


def exit_table(d, now=None):
    """The object for the Lab card. Never raises."""
    now = time.time() if now is None else now
    try:
        tb = F.read_json(d, FILE)
        if not isinstance(tb, dict):
            return {"state": "NOT_RUN_YET", "n": 0, "states": [], "rules": [], "line": "The first run has not finished yet (the slow loop makes it by itself)."}
        return dict(tb, updated_ago_sec=int(now - tb["made"]) if T.num(tb.get("made")) else -1)
    except Exception as e:
        return {"state": "ERROR", "n": 0, "states": [], "rules": [], "line": "%s: %s" % (type(e).__name__, str(e)[:80])}


def collect(d, now=None):
    """-> (TestResults, meta {exitrule: ...}). Never raises."""
    try:
        tb = exit_table(d, now)
        if tb.get("state") not in ("OK", "NO_TRADES"):
            return [], {"exitrule": {"state": tb.get("state"), "why": tb.get("line", "")}}
        rows = _rows(tb, tb.get("updated_ago_sec", -1))
        return rows, {"exitrule": {"state": "OK", "tests": len(rows), "age_sec": tb.get("updated_ago_sec")}}
    except Exception as e:
        return [], {"exitrule": {"state": "ERROR", "why": "%s: %s" % (type(e).__name__, str(e)[:100])}}
