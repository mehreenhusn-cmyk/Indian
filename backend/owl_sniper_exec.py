"""owl_sniper_exec.py - OwlSniper Round 22: the EXECUTOR GATE (backend, plain python). OFF by default. PAPER only. Nothing here can send a real order.
What this file is: the strict checklist a Sniper signal must pass BEFORE any trade is opened, plus the owner's switches. It does not trade by itself: decide() hands back an order and,
only when the caller passes an `opener` function (paper trade opener), calls it. This file imports NO trading module and NO network code. Live mode is refused ("live orders are not built").
STATE (one atomic json file, v2_sniper_exec.json, in the data folder): enabled / armed_until, arm request, kill switch, today's loss, open orders, order ids already used.
  A missing file = everything OFF. A BROKEN file = everything blocked (never "guess OFF -> ON").
ARM = TWO separate calls: request_arm() gives a one-time code, confirm_arm(code) within 60 s switches it on for ARM_HOURS (12 h), then it falls back to OFF by itself. disarm() = OFF at once.
GATES, in this order (the first one that fails stops the order and is named in the answer):
  1 armed -> 2 paper mode -> 3 a Sniper signal exists -> 4 fresh candle -> 5 regime TRENDING -> 6 win chance >= 85% AND the floor is proven on the TEST days -> 7 stop distance inside MIN / MAX_SL_PCT
  -> 8 open-trade cap (1) -> 9 kill switch / daily loss limit -> 10 same signal never twice (idempotent client id).
The 85% floor is a constant here and is never lowered: a card carrying a lower floor is still held to 85%. Size = 10 USDT base. The stop is only ever moved IN the trade's favour (trail_stop).
Daily loss limit: when record_close() brings today's (UTC) closed result to -limit or worse, the KILL SWITCH goes on by itself and stays on until the owner calls reset_kill().
Run (Termux, optional):  python3 backend/owl_sniper_exec.py --data DIR status | arm | confirm CODE | disarm | kill | reset"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_engine_c1 as C
import owl_sniper_feed as F
import owl_sniper_tf as TF

VERSION = "owl_sniper_exec 1 (Round 22)"
STATE_FILE = "v2_sniper_exec.json"
FLOOR = 0.85                    # never lowered
SIZE_USDT = 10.0
MAX_OPEN = 1
ARM_WINDOW_SEC = 60
ARM_HOURS = 12
DAILY_LOSS_LIMIT = 1.0          # USDT lost in one UTC day -> kill switch (a 10 USDT base with a stop of at most MAX_SL_PCT risks about 0.2 USDT per trade)
FRESH_STEPS = 3                 # a card older than 3 candles is not acted on
KEEP_ORDERS = 200
KEEP_LOG = 30


class StateBroken(Exception):
    """The state file exists but cannot be read: everything stays blocked."""


def _default():
    return {"version": VERSION, "mode": "paper", "armed_until": 0, "arm_request": None, "kill": {"on": False, "reason": "", "ts": 0}, "day": "", "day_pnl": 0.0,
            "daily_loss_limit": DAILY_LOSS_LIMIT, "open": {}, "orders": [], "log": []}


def _load(d):
    p = os.path.join(os.path.realpath(d), STATE_FILE)
    if not os.path.exists(p):
        return _default()
    s = F.read_json(d, STATE_FILE)
    if s is None or not isinstance(s.get("kill"), dict) or not isinstance(s.get("open"), dict):
        raise StateBroken("the executor state file is unreadable")
    return dict(_default(), **s)


def _save(d, s):
    if not F.write_json(d, STATE_FILE, s):
        raise StateBroken("the executor state file could not be written")


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def _roll(s, now):
    if s.get("day") != _day(now):
        s["day"], s["day_pnl"] = _day(now), 0.0


def _log(s, now, text):
    s["log"] = (s.get("log") or [])[-(KEEP_LOG - 1):] + [{"ts": int(now), "text": text}]


# ------------------------------------------------------------------ the owner's switches
def request_arm(d, now=None):
    """Call 1 of 2: -> {code, valid_sec}. Switches nothing on. A new request replaces the old one."""
    now = time.time() if now is None else now
    s = _load(d)
    s["arm_request"] = {"code": os.urandom(3).hex(), "ts": int(now)}
    _log(s, now, "Arm requested (waiting for the second call).")
    _save(d, s)
    return {"code": s["arm_request"]["code"], "valid_sec": ARM_WINDOW_SEC}


def confirm_arm(d, code, now=None):
    """Call 2 of 2: the right code within 60 s -> armed for ARM_HOURS. -> (ok, plain text). Never arms while the kill switch is on."""
    now = time.time() if now is None else now
    s = _load(d)
    req = s.get("arm_request")
    s["arm_request"] = None                                          # a code works once, right or wrong
    if s["kill"]["on"]:
        _save(d, s)
        return False, "The kill switch is on. Reset it first."
    if not req or str(code) != req.get("code") or not 0 <= now - req.get("ts", 0) <= ARM_WINDOW_SEC:
        _log(s, now, "Arm confirm refused (wrong or late code).")
        _save(d, s)
        return False, "Wrong or late code. Ask for a new one."
    s["armed_until"] = int(now) + ARM_HOURS * 3600
    _log(s, now, "ARMED for %d h (paper)." % ARM_HOURS)
    _save(d, s)
    return True, "Armed in paper mode for %d hours." % ARM_HOURS


def disarm(d, now=None):
    now = time.time() if now is None else now
    s = _load(d)
    s["armed_until"], s["arm_request"] = 0, None
    _log(s, now, "Disarmed.")
    _save(d, s)


def kill(d, reason="owner pressed the kill switch", now=None):
    now = time.time() if now is None else now
    try:
        s = _load(d)
    except StateBroken:
        s = _default()                                               # a broken file is replaced by a safe one with the switch ON
    s["kill"], s["armed_until"] = {"on": True, "reason": reason, "ts": int(now)}, 0
    _log(s, now, "KILL SWITCH ON: " + reason)
    _save(d, s)


def reset_kill(d, now=None):
    """Owner only. Does NOT arm: arming is the two calls again."""
    now = time.time() if now is None else now
    s = _load(d)
    s["kill"] = {"on": False, "reason": "", "ts": 0}
    _log(s, now, "Kill switch reset (still disarmed).")
    _save(d, s)


# ------------------------------------------------------------------ results and stops
def record_close(d, client_id, pnl_usdt, now=None):
    """The caller reports a closed order: frees the open slot, adds to today's result, turns the kill switch on at the daily loss limit."""
    now = time.time() if now is None else now
    s = _load(d)
    _roll(s, now)
    s["open"].pop(client_id, None)
    s["day_pnl"] = round(float(s["day_pnl"]) + float(pnl_usdt), 6)
    if s["day_pnl"] <= -abs(float(s["daily_loss_limit"])):
        s["kill"], s["armed_until"] = {"on": True, "reason": "daily loss limit reached (%.2f USDT)" % s["day_pnl"], "ts": int(now)}, 0
        _log(s, now, "KILL SWITCH ON by itself: daily loss limit reached.")
    _save(d, s)
    return s["kill"]["on"]


def trail_stop(side, current_stop, proposed_stop):
    """A stop only moves in the trade's favour: LONG up, SHORT down. A looser line is ignored."""
    if proposed_stop is None:
        return current_stop
    if current_stop is None:
        return proposed_stop
    return max(current_stop, proposed_stop) if side == "LONG" else min(current_stop, proposed_stop)


# ------------------------------------------------------------------ the gate
def client_id(interval, card):
    return "OWL-%s-%s-%s-%s" % (interval, card.get("symbol"), card.get("side"), card.get("t"))


def _block(gate, text, **extra):
    return dict({"decision": "BLOCKED", "gate": gate, "text": text, "order": None}, **extra)


def decide(d, card, floor_verified, now=None, interval="5m", opener=None):
    """One Sniper card (a card of v2_sniper_live.json) -> {decision OPEN | WOULD_OPEN | BLOCKED, gate, text, order}. Never raises.
    OPEN = the caller's opener accepted the paper order. WOULD_OPEN = every gate passed but no opener was given (nothing was opened)."""
    now = time.time() if now is None else now
    try:
        s = _load(d)
    except StateBroken as e:
        return _block("state", "%s, so every order is blocked." % e)
    _roll(s, now)
    c = card or {}
    if not (s["armed_until"] > now):
        return _block("armed", "The executor is OFF (not armed).")
    if s["mode"] != "paper":
        return _block("mode", "Only paper mode exists. Live orders are not built.")
    if c.get("action") not in ("SNIPER_LONG", "SNIPER_SHORT") or c.get("side") not in ("LONG", "SHORT"):
        return _block("signal", "There is no Sniper signal on this card.")
    t = c.get("t")
    if not isinstance(t, (int, float)) or now - t > FRESH_STEPS * TF.step(interval):
        return _block("fresh", "The signal candle is too old to act on.")
    if c.get("regime") != "TRENDING":
        return _block("regime", "The market is not TRENDING (sideways or not clear): blocked.")
    p = c.get("confidence")
    if not isinstance(p, (int, float)) or p < FLOOR:
        return _block("floor", "Win chance is below the %.0f%% floor: blocked." % (FLOOR * 100))
    if floor_verified is not True:
        return _block("floor", "The %.0f%% floor is not proven on the TEST days: blocked." % (FLOOR * 100))
    e, sl = c.get("entry_price"), c.get("stop_loss")
    if not (isinstance(e, (int, float)) and isinstance(sl, (int, float)) and e > 0):
        return _block("stop", "Entry or stop price is missing: blocked.")
    dist = ((e - sl) if c["side"] == "LONG" else (sl - e)) / e * 100.0
    if not C.MIN_SL_PCT <= dist <= C.MAX_SL_PCT:
        return _block("stop", "The stop is %.2f%% away; only %.2f%% to %.2f%% is allowed." % (dist, C.MIN_SL_PCT, C.MAX_SL_PCT))
    cid = client_id(interval, c)
    if len(s["open"]) >= MAX_OPEN:
        return _block("cap", "%d trade is already open (the cap is %d)." % (len(s["open"]), MAX_OPEN))
    if s["kill"]["on"]:
        return _block("kill", "The kill switch is on: " + (s["kill"]["reason"] or "owner"))
    if s["day_pnl"] <= -abs(float(s["daily_loss_limit"])):
        return _block("kill", "Today's loss limit is reached.")
    if cid in [o.get("id") for o in s["orders"]] or cid in s["open"]:
        return _block("duplicate", "This exact signal was already used.")
    order = {"id": cid, "mode": "paper", "symbol": c["symbol"], "side": c["side"], "entry": e, "stop": sl, "take_profit": c.get("take_profit"), "stop_pct": round(dist, 3),
             "invest_usdt": SIZE_USDT, "confidence": p, "signal_t": t, "created": int(now)}
    if opener is None:
        return {"decision": "WOULD_OPEN", "gate": "", "text": "Every gate passed. No opener was given, so nothing was opened.", "order": order}
    s["orders"] = (s["orders"] + [{"id": cid, "ts": int(now), "opened": False}])[-KEEP_ORDERS:]      # the id and the open slot are saved BEFORE the opener runs: if saving fails, nothing is opened
    s["open"][cid] = order
    try:
        _save(d, s)
    except StateBroken as e:
        return _block("state", "%s, so the order was not opened." % e)
    try:
        ok = bool(opener(order))
    except Exception:
        ok = False
    if ok:
        s["orders"][-1]["opened"] = True
    else:
        s["open"].pop(cid, None)                                      # the id stays used: one signal is never retried blindly
    _log(s, now, ("Paper order opened: " if ok else "Opener refused: ") + cid)
    try:
        _save(d, s)
    except StateBroken:
        pass                                                          # the slot stays reserved in the file: the safe side
    return {"decision": "OPEN" if ok else "BLOCKED", "gate": "" if ok else "opener", "text": "Paper order opened." if ok else "The paper opener did not accept the order.", "order": order if ok else None}


def status(d, now=None):
    """What the app may show (the code of an arm request is never included)."""
    now = time.time() if now is None else now
    try:
        s = _load(d)
    except StateBroken as e:
        return {"version": VERSION, "ok": False, "text": str(e), "armed": False, "mode": "paper", "live_built": False}
    _roll(s, now)
    return {"version": VERSION, "ok": True, "mode": s["mode"], "armed": s["armed_until"] > now, "armed_until": s["armed_until"], "kill": s["kill"], "day": s["day"], "day_pnl": s["day_pnl"],
            "daily_loss_limit": s["daily_loss_limit"], "open": list(s["open"]), "max_open": MAX_OPEN, "floor": FLOOR, "size_usdt": SIZE_USDT, "log": s["log"][-10:], "live_built": False}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("cmd", choices=("status", "arm", "confirm", "disarm", "kill", "reset"))
    ap.add_argument("code", nargs="?", default="")
    a = ap.parse_args(argv)
    if a.cmd == "arm":
        out = request_arm(a.data)
    elif a.cmd == "confirm":
        out = dict(zip(("ok", "text"), confirm_arm(a.data, a.code)))
    elif a.cmd == "disarm":
        disarm(a.data)
        out = status(a.data)
    elif a.cmd == "kill":
        kill(a.data)
        out = status(a.data)
    elif a.cmd == "reset":
        reset_kill(a.data)
        out = status(a.data)
    else:
        out = status(a.data)
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
