"""owl_sniper_learn.py - OwlSniper LEARN mode (Part 3 / FILE 05). PAPER ONLY. Nothing here can send a real order and there is NO live path.
Why: the REAL gate (owl_sniper_exec.py, FLOOR = 0.85 + proof on TEST days) lets almost nothing pass, so Sniper gets no trades and learns nothing. LEARN is a SEPARATE paper gate:
a lower win-chance floor, a tiny size, every trade tagged LEARN, so data (wins AND losses) comes fast. The real 85% floor is NOT touched and NOT imported-and-changed here.
LEARN gates, in this order (the first one that fails is named in the answer, plain words, so the screen can say WHY Sniper is quiet):
  1 LEARN switch on -> 2 a Sniper signal exists -> 3 fresh candle -> 4 win chance >= LEARN floor (default 0.62, allowed 0.50-0.80, never near the real 0.85)
  -> 5 stop distance inside MIN / MAX_SL_PCT -> 6 open LEARN cap -> 7 LEARN kill switch / daily loss limit -> 8 same signal never twice.
  The regime is NOT a gate in LEARN: sideways trades teach "avoid" too. It is saved in the order so the learner can use it.
Size = LEARN_SIZE_USDT (1 USDT, allowed 0.5-5) at 1x. Orders carry mode "learn", tag "LEARN" and ids that start with "LRN-" (the real executor ids start with "OWL-", they never collide).
Progress: closed LEARN trades count n of 30 (the minimum for a verdict). Below 30 nothing is called proven.
State: ONE atomic json file v2_sniper_learn.json in the data folder. Missing file = defaults (ON, paper). A BROKEN file = everything blocked (never guess).
Part 4 wires this into owl_sniper_exec.py / owl_sniper_paper.py. Run (Termux, optional):  python3 backend/owl_sniper_learn.py --data DIR status | on | off | floor 0.65 | size 1 | reset_kill"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_engine_c1 as C
import owl_sniper_feed as F
import owl_sniper_tf as TF

VERSION = "owl_sniper_learn 1 (Part 3)"
STATE_FILE = "v2_sniper_learn.json"
TAG = "LEARN"
ID_PREFIX = "LRN-"
FLOOR_DEFAULT, FLOOR_MIN, FLOOR_MAX = 0.62, 0.50, 0.80      # the real floor is 0.85 and lives in owl_sniper_exec.py only
SIZE_DEFAULT, SIZE_MIN, SIZE_MAX = 1.0, 0.5, 5.0            # USDT per LEARN trade, 1x
MAX_OPEN = 5
DAILY_LOSS_LIMIT = 0.5                                      # USDT lost in one UTC day -> LEARN kill switch (reset by the owner)
XP_SIZE, XP_LEV, XP_MAX_OPEN, XP_DAILY_LOSS = 100.0, 10.0, 40, 1000.0   # R26a EXPLORE paper trades: margin USDT, leverage, open at once, runaway cap per UTC day (own book, paper)
MIN_SAMPLE = 30                                             # closed LEARN trades before any verdict
FRESH_STEPS = 3
KEEP_ORDERS = 400
KEEP_LOG = 30
LIVE_ALLOWED = False                                        # constant: LEARN can never go live


class StateBroken(Exception):
    pass


def _default():
    return {"v": 1, "enabled": True, "floor": FLOOR_DEFAULT, "size_usdt": SIZE_DEFAULT, "max_open": MAX_OPEN, "daily_loss_limit": DAILY_LOSS_LIMIT,
            "day": "", "day_pnl": 0.0, "xp_day_pnl": 0.0, "kill": {"on": False, "reason": ""}, "open": {}, "orders": [],
            "closed": {"n": 0, "wins": 0, "losses": 0, "pnl": 0.0}, "log": []}


def _clamp(x, lo, hi, dflt):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return dflt
    return min(hi, max(lo, x)) if x == x else dflt


def _load(d):
    p = os.path.join(os.path.realpath(d), STATE_FILE)
    if not os.path.exists(p):
        return _default()
    s = F.read_json(d, STATE_FILE)
    if not isinstance(s, dict) or not isinstance(s.get("open"), dict) or not isinstance(s.get("orders"), list) or not isinstance(s.get("closed"), dict):
        raise StateBroken("The LEARN state file is broken")
    base = _default()
    base.update(s)
    base["floor"] = _clamp(base["floor"], FLOOR_MIN, FLOOR_MAX, FLOOR_DEFAULT)
    base["size_usdt"] = _clamp(base["size_usdt"], SIZE_MIN, SIZE_MAX, SIZE_DEFAULT)
    return base


def _save(d, s):
    if not F.write_json(d, STATE_FILE, s):
        raise StateBroken("The LEARN state file cannot be saved")


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def _roll(s, now):
    if s["day"] != _day(now):
        s["day"], s["day_pnl"], s["xp_day_pnl"] = _day(now), 0.0, 0.0


def _log(s, now, text):
    s["log"] = (s["log"] + [{"ts": int(now), "text": text}])[-KEEP_LOG:]


def client_id(interval, card):
    return "%s%s-%s-%s-%s" % (ID_PREFIX, interval, card.get("symbol"), card.get("side"), card.get("t"))


def _block(gate, text, **extra):
    return dict({"decision": "BLOCKED", "gate": gate, "text": text, "order": None, "tag": TAG}, **extra)


def set_config(d, enabled=None, floor=None, size=None, now=None):
    """Owner switches. The floor is clamped to 0.50-0.80 and the size to 0.5-5 USDT, so LEARN can never look like the real gate."""
    now = time.time() if now is None else now
    s = _load(d)
    if enabled is not None:
        s["enabled"] = bool(enabled)
    if floor is not None:
        s["floor"] = _clamp(floor, FLOOR_MIN, FLOOR_MAX, s["floor"])
    if size is not None:
        s["size_usdt"] = _clamp(size, SIZE_MIN, SIZE_MAX, s["size_usdt"])
    _log(s, now, "LEARN config: on=%s floor=%.2f size=%.2f" % (s["enabled"], s["floor"], s["size_usdt"]))
    _save(d, s)
    return s


def decide(d, card, now=None, interval="5m", opener=None, explore=False, xp=False):
    """One Sniper card -> {decision OPEN | WOULD_OPEN | BLOCKED, gate, text, order, tag}. Never raises. Paper only: the caller's opener is a paper opener.
    The card may carry any regime and any win chance above the LEARN floor. The real 85% gate is NOT consulted here.
    R3c: explore=True (the autopilot is still learning) = the win-chance floor is NOT checked: tiny paper trades teach wins AND losses. Every other LEARN gate stays (signal, fresh, stop range, cap, kill switch, daily loss, same signal once)."""
    now = time.time() if now is None else now
    try:
        s = _load(d)
    except StateBroken as e:
        return _block("state", "%s, so every LEARN order is blocked." % e)
    _roll(s, now)
    c = card or {}
    if not s["enabled"]:
        return _block("switch", "LEARN mode is OFF.")
    if c.get("action") not in ("SNIPER_LONG", "SNIPER_SHORT") or c.get("side") not in ("LONG", "SHORT"):
        return _block("signal", "There is no Sniper signal on this card.")
    t = c.get("t")
    if not isinstance(t, (int, float)) or now - t > FRESH_STEPS * TF.step(interval):
        return _block("fresh", "The signal candle is too old to act on.")
    p = c.get("confidence")
    if not explore and (not isinstance(p, (int, float)) or p < s["floor"]):
        return _block("floor", "Win chance is below the LEARN floor of %.0f%%." % (s["floor"] * 100))
    e, sl = c.get("entry_price"), c.get("stop_loss")
    if not (isinstance(e, (int, float)) and isinstance(sl, (int, float)) and e > 0):
        return _block("stop", "Entry or stop price is missing.")
    dist = ((e - sl) if c["side"] == "LONG" else (sl - e)) / e * 100.0
    if not C.MIN_SL_PCT <= dist <= C.MAX_SL_PCT:
        return _block("stop", "The stop is %.2f%% away; only %.2f%% to %.2f%% is allowed." % (dist, C.MIN_SL_PCT, C.MAX_SL_PCT))
    cid = client_id(interval, c)
    n_xp = len([1 for o in s["open"].values() if o.get("xp")])
    if xp:                                                      # R26a: EXPLORE paper trades have their own cap and one trade per coin
        if n_xp >= XP_MAX_OPEN:
            return _block("cap", "%d EXPLORE trades are already open (the cap is %d)." % (n_xp, XP_MAX_OPEN))
        if any(o.get("xp") and o.get("symbol") == c["symbol"] for o in s["open"].values()):
            return _block("cap", "An EXPLORE trade on %s is already open." % c["symbol"])
        import owl_sniper_mistakes as MS                       # R26b: a coin + side + market state that lost its last 3 trades rests 24 h (never raises)
        why = None if c.get("fill") else MS.blocked(d, c.get("symbol"), c.get("side"), c.get("regime"), now)   # R33: a FILL card (no signal, learning trade) never rests: the owner wants trades even after mistakes
        if why:
            return _block("mistake", why)
    elif len(s["open"]) - n_xp >= int(s["max_open"]):
        return _block("cap", "%d LEARN trades are already open (the cap is %d)." % (len(s["open"]) - n_xp, int(s["max_open"])))
    if s["kill"]["on"]:
        return _block("kill", "The LEARN kill switch is on: " + (s["kill"]["reason"] or "owner"))
    if xp and s.get("xp_day_pnl", 0.0) <= -XP_DAILY_LOSS:
        return _block("kill", "Today's EXPLORE loss cap (%.0f USDT paper) is reached. It resets on a new UTC day." % XP_DAILY_LOSS)
    if not xp and s["day_pnl"] <= -abs(float(s["daily_loss_limit"])):
        return _block("kill", "Today's LEARN loss limit is reached.")
    if cid in [o.get("id") for o in s["orders"]] or cid in s["open"]:
        return _block("duplicate", "This exact signal was already used.")
    order = {"id": cid, "mode": "learn", "tag": TAG, "symbol": c["symbol"], "side": c["side"], "entry": e, "stop": sl, "take_profit": c.get("take_profit"),
             "stop_pct": round(dist, 3), "invest_usdt": XP_SIZE if xp else s["size_usdt"], "leverage": XP_LEV if xp else 1.0, "xp": bool(xp), "confidence": p, "regime": c.get("regime"), "signal_t": t, "created": int(now), "explore": bool(explore)}
    if opener is None:
        return {"decision": "WOULD_OPEN", "gate": "", "text": "Every LEARN gate passed. No opener was given, so nothing was opened.", "order": order, "tag": TAG}
    s["orders"] = (s["orders"] + [{"id": cid, "ts": int(now), "opened": False}])[-KEEP_ORDERS:]     # saved BEFORE the opener runs: if saving fails, nothing is opened
    s["open"][cid] = order
    try:
        _save(d, s)
    except StateBroken as e:
        return _block("state", "%s, so the LEARN order was not opened." % e)
    try:
        ok = bool(opener(order))
    except Exception:
        ok = False
    if ok:
        s["orders"][-1]["opened"] = True
    else:
        s["open"].pop(cid, None)
    _log(s, now, ("LEARN paper order opened: " if ok else "Opener refused: ") + cid)
    try:
        _save(d, s)
    except StateBroken:
        pass
    return {"decision": "OPEN" if ok else "BLOCKED", "gate": "" if ok else "opener", "text": "LEARN paper order opened." if ok else "The paper opener did not accept the order.", "order": order if ok else None, "tag": TAG}


def record_close(d, cid, pnl_usdt, now=None):
    """A LEARN paper trade closed with NET result pnl_usdt. Frees the slot, counts n, wins, losses; a loss past the daily limit turns the LEARN kill switch on."""
    now = time.time() if now is None else now
    try:
        s = _load(d)
    except StateBroken:
        return False
    _roll(s, now)
    o = s["open"].pop(cid, None)
    if o is None:
        return False
    x = float(pnl_usdt) if isinstance(pnl_usdt, (int, float)) and pnl_usdt == pnl_usdt else 0.0
    cl = s["closed"]
    cl["n"] += 1
    cl["wins" if x > 0 else "losses"] += 1
    cl["pnl"] = round(cl["pnl"] + x, 6)
    if o.get("xp"):                                              # R26a: an EXPLORE result never feeds the tiny-LEARN kill switch
        s["xp_day_pnl"] = round(s.get("xp_day_pnl", 0.0) + x, 6)
    else:
        s["day_pnl"] = round(s["day_pnl"] + x, 6)
    _log(s, now, "LEARN closed %s: %+.4f USDT" % (cid, x))
    if not o.get("xp") and s["day_pnl"] <= -abs(float(s["daily_loss_limit"])) and not s["kill"]["on"]:
        s["kill"] = {"on": True, "reason": "daily LEARN loss limit reached"}
        _log(s, now, "LEARN kill switch ON (daily loss limit)")
    try:
        _save(d, s)
    except StateBroken:
        return False
    return True


def reset_kill(d, now=None):
    now = time.time() if now is None else now
    s = _load(d)
    s["kill"] = {"on": False, "reason": ""}
    s["day_pnl"] = 0.0
    _log(s, now, "LEARN kill switch reset by the owner")
    _save(d, s)
    return s


def progress(d):
    """For the screen (Part 5): {n, target, wins, losses, net_usdt, text}. Below 30 closed trades the text says NOT ENOUGH DATA (never a fake verdict)."""
    try:
        s = _load(d)
    except StateBroken as e:
        return {"n": 0, "target": MIN_SAMPLE, "wins": 0, "losses": 0, "net_usdt": 0.0, "state": "broken", "text": str(e)}
    cl = s["closed"]
    txt = "LEARN trades %d of %d. %s" % (cl["n"], MIN_SAMPLE, "NOT ENOUGH DATA for a verdict yet." if cl["n"] < MIN_SAMPLE else "Enough trades to judge (still paper).")
    return {"n": cl["n"], "target": MIN_SAMPLE, "wins": cl["wins"], "losses": cl["losses"], "net_usdt": cl["pnl"], "state": "ok", "text": txt}


def status(d, now=None):
    now = time.time() if now is None else now
    try:
        s = _load(d)
    except StateBroken as e:
        return {"state": "broken", "text": str(e), "live_allowed": False}
    _roll(s, now)
    return {"state": "ok", "tag": TAG, "enabled": s["enabled"], "floor": s["floor"], "size_usdt": s["size_usdt"], "max_open": s["max_open"], "open": list(s["open"]),
            "day_pnl": s["day_pnl"], "daily_loss_limit": s["daily_loss_limit"], "xp": {"size": XP_SIZE, "lev": XP_LEV, "max_open": XP_MAX_OPEN, "open": len([1 for o in s["open"].values() if o.get("xp")]), "day_pnl": s.get("xp_day_pnl", 0.0), "daily_loss_cap": XP_DAILY_LOSS}, "kill": s["kill"], "progress": progress(d), "log": s["log"][-10:], "live_allowed": LIVE_ALLOWED}


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper LEARN mode (paper only)")
    ap.add_argument("--data", required=True)
    ap.add_argument("cmd", choices=["status", "on", "off", "floor", "size", "reset_kill"])
    ap.add_argument("value", nargs="?")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "on":
            set_config(a.data, enabled=True)
        elif a.cmd == "off":
            set_config(a.data, enabled=False)
        elif a.cmd == "floor":
            set_config(a.data, floor=a.value)
        elif a.cmd == "size":
            set_config(a.data, size=a.value)
        elif a.cmd == "reset_kill":
            reset_kill(a.data)
    except StateBroken as e:
        print(json.dumps({"state": "broken", "text": str(e)}))
        return 1
    print(json.dumps(status(a.data), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
