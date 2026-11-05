"""owl_sniper_xrules.py - OwlSniper A/B TEST + EXIT RULES ENGINE (R32b, Part 7). PAPER ONLY: touches ONLY Sniper paper trades (tag sniper_id), never the Current Bot, Dual or Brain, never a real order.
The Sniper learns by TRADING, not by a win-chance wall: every new paper LEARN / EXPLORE trade is put in one of two arms at the moment it opens (by a hash of its own id, so both arms trade the same days):
  arm A = control: the lines as they are (1R stop / 2R profit, or the learned combo of Part 6).
  arm B = challenger: ONE exit rule of owl_sniper_exitlearn.RULES that needs an exit engine: be05 / be1 (stop moves to the entry once +0.5R / +1R was seen), trail1 (stop trails 1R behind the best price after +1R), t6 / t12 (closed at the close of candle 6 / 12). The challenger is the booking learner's advice for that market state when it has one, else the five rules take turns.
manage() runs every loop turn (owl_sniper_paper.step): it only moves a stop IN the trade's favour (field trailed_sl, which the paper monitor already honours) or closes the trade at its time line. Best price is read from the position's last price each turn (coarser than a candle: honest limit).
view(): per arm and per rule, closed trades in R of their own stop (paper pnl / (size x stop %)), and ONE sentence verdict. B_BETTER / A_BETTER only with 20+ closed trades in each arm, a gap of 0.05 R or more and a Welch t of 2 or more. When B is clearly better the challenger share rises to 3 of 4 trades and only the best rule is used. Nothing is a profit promise.
Switch: file v2_ab_off in the data folder = every new trade is arm A (open B trades are still managed). Own file v2_sniper_ab.json. API: plan(d, order), note(d, order, tid, now), manage(d, pt, now), view(d)."""
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_exitlearn as XL
import owl_sniper_feed as F
import owl_sniper_lessons as LS

VERSION = "owl_sniper_xrules 1 (R32b)"
FILE, OFF_FILE = "v2_sniper_ab.json", "v2_ab_off"
CHALLENGERS = ("be05", "be1", "trail1", "t6", "t12")
STEP = 300                                      # one 5m candle in seconds
MIN_ARM, MIN_GAP, T_MIN, KEEP = 20, 0.05, 2.0, 400


def _h(s):
    return int(hashlib.md5(str(s).encode()).hexdigest(), 16)


def _load(d):
    st = F.read_json(d, FILE)
    return st if isinstance(st, dict) and isinstance(st.get("trades"), dict) else {"trades": {}}


def _off(d):
    return os.path.exists(os.path.join(os.path.realpath(d), OFF_FILE))


def plan(d, o):
    """The order BEFORE it opens: arm + rule decided, the profit line set to the rule's own line (R of the order's stop). Any problem = the order as it is (arm A)."""
    try:
        e, sl = float(o["entry"]), float(o["stop"])
        risk, sgn = abs(e - sl), 1.0 if o["side"] == "LONG" else -1.0
        if _off(d) or e <= 0 or risk <= 0:
            return o
        v, h = view(d), _h(o["id"])
        best = v.get("best_rule") if v.get("verdict") == "B_BETTER" else None
        if h % (4 if best else 2) == 0:
            return dict(o, ab_arm="A")
        adv = (XL.load(d) or {}).get("advice") or {}
        rule = best or (adv.get("%s|5m" % (o.get("regime") or "?")) if adv.get("%s|5m" % (o.get("regime") or "?")) in CHALLENGERS else CHALLENGERS[(h // 4) % len(CHALLENGERS)])
        return dict(o, ab_arm="B", ab_rule=rule, take_profit=e + sgn * risk * XL.RULES[rule][0], exit_rule=rule)
    except Exception:
        return o


def note(d, o, tid, now=None):
    """After the paper trade opened: remember its arm, rule, size and stop distance (the join key is the Sniper order id = sniper_id on the position and on the closed row)."""
    try:
        if not o.get("ab_arm"):
            return
        st = _load(d)
        e, sl = float(o["entry"]), float(o["stop"])
        st["trades"][o["id"]] = {"arm": o["ab_arm"], "rule": o.get("ab_rule"), "tid": tid, "entry": e, "risk": abs(e - sl), "side": o["side"], "best": 0.0,
                                 "t0": time.time() if now is None else now, "notional": float(o.get("invest_usdt") or 0) * float(o.get("leverage") or 1.0)}
        if len(st["trades"]) > KEEP:
            for k in sorted(st["trades"], key=lambda k: st["trades"][k].get("t0", 0))[:len(st["trades"]) - KEEP]:
                del st["trades"][k]
        F.write_json(d, FILE, st)
    except Exception:
        pass


def manage(d, pt, now=None):
    """Every loop turn: move the stop (in the trade's favour only) or close at the time line, for open arm B Sniper trades. -> {moved, closed}. Never raises."""
    now, out, to_close = time.time() if now is None else now, {"moved": 0, "closed": 0}, []
    try:
        st = _load(d)
        live = [r for r in st["trades"].values() if r.get("arm") == "B" and not r.get("done")]
        if not live:
            return out
        with pt._lock:
            for tid, p in pt._positions.items():
                sid = p.get("sniper_id")
                r = st["trades"].get(sid) if sid else None
                ltp = p.get("ltp")
                if not r or r.get("arm") != "B" or not isinstance(ltp, (int, float)) or r["risk"] <= 0:
                    continue
                tp, be_at, trail, bars = XL.RULES[r["rule"]]
                sgn, e = 1.0 if r["side"] == "LONG" else -1.0, r["entry"]
                r["best"] = max(r["best"], sgn * (ltp - e) / r["risk"])
                new = e + sgn * (r["best"] - 1.0) * r["risk"] if trail is not None and r["best"] >= trail else (e if be_at is not None and r["best"] >= be_at else None)
                cur = p.get("trailed_sl") or p.get("signal_stop_loss")
                if new is not None and cur and sgn * (new - cur) > 0:
                    p["trailed_sl"] = new
                    out["moved"] += 1
                if bars < XL.HOLD and now - r["t0"] >= bars * STEP:
                    to_close.append(tid)
                    r["done"] = True
        for tid in to_close:
            pt.close_position_manual(tid)
            out["closed"] += 1
        F.write_json(d, FILE, st)
    except Exception:
        pass
    return out


def _stats(rs):
    n = len(rs)
    m = sum(rs) / n if n else None
    sd = (sum((x - m) ** 2 for x in rs) / (n - 1)) ** 0.5 if n > 1 else None
    return {"n": n, "mean_r": None if m is None else round(m, 4), "win_pct": round(100.0 * sum(1 for x in rs if x > 0) / n, 1) if n else None, "_sd": sd, "_m": m}


def view(d):
    """Closed arm A vs arm B (and each B rule), R per trade after paper fees, + the verdict sentence. Never raises."""
    out = {"version": VERSION, "paper_only": True, "verdict": "COLLECTING", "arms": {}, "rules": {}, "best_rule": None, "text": "", "switch_off": _off(d)}
    try:
        tr = _load(d)["trades"]
        rows, _p = LS.read_own(d)
        a, b, by = [], [], {}
        for t in rows:
            r = tr.get(t.get("sniper_id"))
            pnl = LS._num(t.get("pnl_usdt"))
            if not r or pnl is None or r["notional"] <= 0 or r["risk"] <= 0:
                continue
            x = pnl / (r["notional"] * r["risk"] / r["entry"])
            (a if r["arm"] == "A" else b).append(x)
            if r["arm"] == "B":
                by.setdefault(r["rule"], []).append(x)
        sa, sb = _stats(a), _stats(b)
        out["arms"] = {"A": {k: v for k, v in sa.items() if k[0] != "_"}, "B": {k: v for k, v in sb.items() if k[0] != "_"}}
        out["rules"] = {k: {kk: vv for kk, vv in _stats(v).items() if kk[0] != "_"} for k, v in by.items()}
        ok = [(k, _stats(v)["_m"]) for k, v in by.items() if len(v) >= 8]
        out["best_rule"] = max(ok, key=lambda z: z[1])[0] if ok else None
        if sa["n"] < MIN_ARM or sb["n"] < MIN_ARM:
            out["text"] = "Still collecting: %d closed control trades, %d closed challenger trades, %d needed in each arm." % (sa["n"], sb["n"], MIN_ARM)
            return out
        gap = sb["_m"] - sa["_m"]
        t = gap / ((sa["_sd"] ** 2 / sa["n"] + sb["_sd"] ** 2 / sb["n"]) ** 0.5) if sa["_sd"] and sb["_sd"] else 0.0
        out["gap_r"], out["t"] = round(gap, 4), round(t, 2)
        if gap >= MIN_GAP and t >= T_MIN:
            out["verdict"], out["text"] = "B_BETTER", "The challenger exits keep %.2f R per trade more than the control (t %.1f): the Sniper now trades them on 3 of 4 trades." % (gap, t)
        elif gap <= -MIN_GAP and t <= -T_MIN:
            out["verdict"], out["text"] = "A_BETTER", "The control exits are %.2f R per trade better than the challengers (t %.1f): the plain 1R / 2R lines stay." % (-gap, -t)
        else:
            out["verdict"], out["text"] = "NOT_CLEAR", "No clear winner yet (gap %+.2f R, t %.1f): both arms keep trading." % (gap, t)
    except Exception as e:
        out["verdict"], out["text"] = "error", "%s: %s" % (type(e).__name__, str(e)[:80])
    return out
