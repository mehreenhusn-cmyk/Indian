"""owl_sniper_autopilot.py - OwlSniper AUTOPILOT, part A of 2 (R3). PAPER ONLY. The learning brain: no order code, no network, no live path. Writes ONE own state file (v2_sniper_autopilot.json), atomically.
Owner idea: like a person who sits 10 years with the chart and learns "not every signal, only these". The Sniper learns BY ITSELF from all old trades (owl_sniper_feedall table, 20 numbers each).
Two states, the same pattern as Dual:
  EXPLORE = learning. In PAPER it may take signals at a tiny size, any number of trades, mistakes are fine. Only 4 hard caps stay: open-trade cap, tiny size, kill switch, stop limits (the caller checks them; see explore_ok).
  LEARNED = the model beats "take every signal" on UNSEEN days, after fees. Only then it picks signals by its win chance (cut learned on TRAIN days, judged on TEST days).
HONEST: LEARNED means "better than taking everything on days it never saw". It is NOT a profit promise. The 85% win-rate wall is for LIVE only and is not touched here.
Split: older days = TRAIN, newest whole days (30%) = TEST (same rule as the bridge, needs 6 whole days). The cut is chosen on TRAIN only, then applied to TEST once. No peeking.
API: judge(trades, now=None), explore_ok(open_n, kill, caps=None), decide(state, wide, open_n=0, kill=False), run(d, now=None, since_days=None), load(d), save(d, st). CLI: python3 backend/owl_sniper_autopilot.py [--data DIR] [--save]"""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_bridge_learn as BL
import owl_sniper_feedall_feat as WF
import owl_sniper_prob as P

VERSION = "owl_sniper_autopilot 2 (R30)"
PAPER_ONLY = True
LIVE_ALLOWED = False
FILE = "v2_sniper_autopilot.json"
CUTS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)    # win-chance cuts tried on TRAIN
MIN_TRAIN, MIN_TEST, MIN_PICKED = 30, 30, 15          # too few = no honest verdict
CAPS = {"max_open": 5, "size_mult": 0.25}             # EXPLORE hard caps (the only ones): open trades, size x of normal (tiny)


def _sig(x):
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def trades_from(examples):
    """Feedall examples -> trade rows: uid, entry_ts, secs, win, net_r, wide. Examples without numbers are left out."""
    out = []
    for e in examples:
        lb = e.get("label") or {}
        if e.get("wide") and lb.get("r_net") is not None:
            out.append({"uid": e["uid"], "entry_ts": e["entry_ts"], "secs": lb.get("secs_to_result") or 0, "win": bool(lb.get("win")), "net_r": lb["r_net"], "wide": e["wide"]})
    return out


def fit(train):
    """TRAIN trades -> model {w, b, mu, sd} on the wide numbers, or None when it cannot be learned (too few, or all the same result)."""
    wins = sum(1 for t in train if t["win"])
    if len(train) < MIN_TRAIN or wins in (0, len(train)):
        return None
    step = -(-len(train) // P.MAX_FIT_ROWS)
    use = train[::step] if step > 1 else train
    X = [t["wide"] for t in use]
    mu, sd = P.fit_standardizer(X)
    Xs = [[(r[j] - mu[j]) / sd[j] for j in range(len(r))] for r in X]
    w, b = P.fit_logistic(Xs, [1 if t["win"] else 0 for t in use])
    return {"w": [round(v, 6) for v in w], "b": round(b, 6), "mu": [round(v, 6) for v in mu], "sd": [round(v, 6) for v in sd]}


def prob(model, wide):
    """Win chance 0..1 of one signal (its wide numbers)."""
    s = model["b"] + sum(model["w"][j] * (wide[j] - model["mu"][j]) / model["sd"][j] for j in range(len(wide)))
    return _sig(s)


def _net(ts):
    return round(sum(t["net_r"] for t in ts), 4)


def _pick_cut(train, ps):
    """The cut with the best net R on TRAIN (at least MIN_PICKED trades). None when no cut qualifies."""
    best = None
    for c in CUTS:
        sel = [t for t, p in zip(train, ps) if p >= c]
        if len(sel) >= MIN_PICKED and (best is None or _net(sel) > best[1]):
            best = (c, _net(sel))
    return best[0] if best else None


def judge(trades, now=None):
    """All trades -> state dict. EXPLORE until the model beats 'take everything' on unseen TEST days after fees. Never raises."""
    now = time.time() if now is None else now
    st = {"version": VERSION, "paper_only": True, "state": "EXPLORE", "made": int(now), "model": None, "cut": None, "reasons": [], "compare": None,
          "n_all": len(trades), "n_train": 0, "n_test": 0, "days": 0}
    why = st["reasons"]
    train, test, cut_ts, days = BL.split(trades)
    st["n_train"], st["n_test"], st["days"] = len(train), len(test), days
    if not test:
        why.append("NOT_ENOUGH_DATA: %d whole days (need 6) - keep learning in paper." % days)
        return st
    model = fit(train)
    if model is None:
        why.append("Model not learned: %d TRAIN trades (need %d), or all ended the same way." % (len(train), MIN_TRAIN))
        return st
    st["model"] = model
    cut = _pick_cut(train, [prob(model, t["wide"]) for t in train])
    if cut is None:
        why.append("No win-chance cut gave %d+ trades on TRAIN days - keep learning." % MIN_PICKED)
        return st
    st["cut"] = cut
    pt = [prob(model, t["wide"]) for t in test]
    picked = [t for t, p in zip(test, pt) if p >= cut]
    wins = sum(1 for t in picked if t["win"])
    st["compare"] = {"test_all": {"trades": len(test), "net_r": _net(test), "avg_r": round(_net(test) / len(test), 4)},
                     "test_picked": {"trades": len(picked), "wins": wins, "net_r": _net(picked), "avg_r": round(_net(picked) / len(picked), 4) if picked else None}}
    if len(test) < MIN_TEST:
        why.append("Only %d TEST trades (need %d) - verdict too early." % (len(test), MIN_TEST))
    elif len(picked) < MIN_PICKED:
        why.append("Model picked only %d TEST trades (need %d)." % (len(picked), MIN_PICKED))
    elif _net(picked) <= 0:
        why.append("Picked trades lost %.2f R after fees on unseen days." % -_net(picked))
    elif _net(picked) / len(picked) <= _net(test) / len(test):
        why.append("Picking did NOT beat taking every signal on unseen days (%.3f vs %.3f R per trade)." % (_net(picked) / len(picked), _net(test) / len(test)))
    else:
        st["state"] = "LEARNED"
        why.append("LEARNED: on %d unseen trades the model's picks made %.3f R per trade vs %.3f for taking everything, after fees. Not a profit promise." % (
            len(picked), _net(picked) / len(picked), _net(test) / len(test)))
    return st


def explore_ok(open_n, kill, caps=None):
    """EXPLORE gate: the only hard stops are the open-trade cap and the kill switch. -> (ok, reason, size_mult)."""
    c = dict(CAPS, **(caps or {}))
    if kill:
        return False, "kill switch is ON", 0.0
    if open_n >= c["max_open"]:
        return False, "open-trade cap %d reached" % c["max_open"], 0.0
    return True, "EXPLORE: learning trade, tiny size", c["size_mult"]


def decide(state, wide, open_n=0, kill=False, caps=None):
    """One signal -> {take, why, p, size_mult}. LEARNED = take only if p >= cut. EXPLORE = take (tiny) unless a hard cap says no. Never opens anything itself."""
    ok, why, mult = explore_ok(open_n, kill, caps)
    if not ok:
        return {"take": False, "why": why, "p": None, "size_mult": 0.0}
    p = prob(state["model"], wide) if state.get("model") else None
    if state.get("state") == "LEARNED" and p is not None:
        if p < state["cut"]:
            return {"take": False, "why": "LEARNED: win chance %.0f%% is below the cut %.0f%%" % (p * 100, state["cut"] * 100), "p": round(p, 4), "size_mult": 0.0}
        return {"take": True, "why": "LEARNED: win chance %.0f%% passes the cut" % (p * 100), "p": round(p, 4), "size_mult": 1.0 if open_n < CAPS["max_open"] else mult}
    return {"take": True, "why": why, "p": None if p is None else round(p, 4), "size_mult": mult}


def explore_active(d):
    """True while the Sniper is still learning (no state yet, or EXPLORE). False when LEARNED, or when the owner made the file v2_autopilot_explore_off (his switch)."""
    if os.path.exists(os.path.join(d, "v2_autopilot_explore_off")):
        return False
    st = load(d)
    return st is None or st.get("state") != "LEARNED"


def load(d):
    try:
        with open(os.path.join(d, FILE)) as f:
            st = json.load(f)
        if (st.get("model") or {}).get("w") and len(st["model"]["w"]) != len(WF.WIDE_FEATS):     # R30: the number list grew (BTC + session): an old model is dropped, the Sniper learns again
            st = dict(st, state="EXPLORE", model=None, cut=None, reasons=list(st.get("reasons") or []) + ["Old model used another number list (R30 added BTC + session numbers); it was dropped and is learned again."])
        return st
    except Exception:
        return None


def save(d, st):
    p = os.path.join(d, FILE)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, p)


def run(d, now=None, since_days=None, persist=False):
    """feedall table -> judge -> (optionally saved). Never raises."""
    try:
        import owl_sniper_feedall as FA
        res = FA.build(d, since_days=since_days, now=now, knowledge=False)
        st = judge(trades_from(res["examples"]), now)
        st["feed"] = res.get("counts")
        if res.get("error"):
            st["reasons"].append("feed error: " + res["error"])
        if persist:
            save(d, st)
        return st
    except Exception as e:
        return {"version": VERSION, "state": "EXPLORE", "reasons": ["autopilot error: %s: %s" % (type(e).__name__, str(e)[:100])], "model": None}


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper autopilot judge (paper only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    st = run(a.data, since_days=a.since_days, persist=a.save)
    st = dict(st, model=("learned" if st.get("model") else None))
    print(json.dumps(st, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
