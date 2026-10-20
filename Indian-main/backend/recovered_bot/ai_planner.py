"""
ai_planner.py - the AI's day: a target, a loss cap, how much of the day is left, and a written journal of its choices.

It works ONLY on the AI's own paper copy (ai_coach). It never touches the bot, and paper and real stay separate.

The day runs 5:30 AM IST to 5:30 AM IST (= 00:00 UTC), the same day as the Dashboard ring and the P&L calendar.
You give it three numbers (all optional, 0 = off). It decides everything else and writes the reason.

HARD rules (the only two the AI cannot argue with - "seat belt"):
  loss_cap_usdt   closed P&L of the day + open P&L  <=  -loss cap   ->  STOPPED: no new AI trade until the next day
  max_open        this many AI trades open at the same time          ->  the next signal is skipped
Everything else is the AI's own judgement, from data, with a reason:
  HUNT     normal. The AI takes the same signals as the bot (no data = no reason to skip).
  DONE     target reached. The AI keeps going only on coins whose own history is clearly profitable (Trusted).
  REST     target was reached, then more than giveback_pct % of the day's best profit was given back: stop for today.
  STOPPED  loss cap reached.
  A coin with status Avoid (both halves of its history clearly losing, see ai_coin_memory) is skipped, with the reason.
Nothing here raises the position size after a loss or because the target is far away: the target never makes the AI
take MORE risk (that is how revenge trading starts).
Every public function swallows its own errors.
"""
import threading
import time

DAY_S = 86400
JOURNAL_MAX = 80
SAVE_EVERY_S = 30

_lock = threading.RLock()
_loaded = False
_dirty = False
_last_save = 0.0
_file_override = None
_cfg = {"target_usdt": 0.0, "loss_cap_usdt": 0.0, "max_open": 0, "giveback_pct": 50.0}
_day = {"start": 0, "peak": 0.0, "mode": "HUNT", "why": ""}
_journal = []             # [{"t": ts, "kind": "TAKE|SKIP|MODE", "text": str}]


def _file():
    if _file_override:
        return _file_override
    try:
        import os
        from . import ai_coach as C
        return os.path.join(os.path.dirname(C._file), "ai_planner.json") if C._file else None
    except Exception:
        return None


def _load():
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            f = _file()
            if not f:
                return
            from . import safe_io
            d, _src = safe_io.read_json_safe(f, "ai_planner")
            if isinstance(d, dict):
                if isinstance(d.get("cfg"), dict):
                    for k in _cfg:
                        if k in d["cfg"]:
                            _cfg[k] = type(_cfg[k])(d["cfg"][k])
                if isinstance(d.get("day"), dict):
                    _day.update(d["day"])
                if isinstance(d.get("journal"), list):
                    _journal[:] = d["journal"][-JOURNAL_MAX:]
        except Exception as e:
            print(f"[AIPlanner] load: {e}")


def _save(force=False):
    global _dirty, _last_save
    with _lock:
        if not _dirty or (not force and time.time() - _last_save < SAVE_EVERY_S):
            return
        f = _file()
        if not f:
            return
        try:
            from . import safe_io
            safe_io.write_json_atomic(f, {"cfg": _cfg, "day": _day, "journal": _journal[-JOURNAL_MAX:]})
            _dirty = False
            _last_save = time.time()
        except Exception as e:
            print(f"[AIPlanner] save: {e}")


def day_start(now=None):
    now = now or time.time()
    return int(now // DAY_S) * DAY_S


def set_config(**kw):
    """Update target / loss cap / max open / giveback. Negative or non-numeric values are rejected."""
    global _dirty
    try:
        _load()
        with _lock:
            for k, v in kw.items():
                if k in _cfg and v is not None:
                    x = float(v)
                    if x < 0:
                        continue
                    _cfg[k] = int(x) if k == "max_open" else x
            _dirty = True
            _journal.append({"t": time.time(), "kind": "MODE", "text": "Settings changed: target %.2f, loss cap %.2f, max open %d, give-back %.0f%%" % (
                _cfg["target_usdt"], _cfg["loss_cap_usdt"], _cfg["max_open"], _cfg["giveback_pct"])})
        _save(force=True)
        return {"ok": True, "cfg": dict(_cfg)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def config():
    _load()
    with _lock:
        return dict(_cfg)


def day_numbers(closed, opens, now=None):
    """closed: the coach's closed records (need t1, pnl). opens: [(inv, roi %)] of AI trades open now.
    -> (closed P&L of today, open P&L now)."""
    t0 = day_start(now)
    cp = sum(float(c.get("pnl") or 0.0) for c in closed if float(c.get("t1") or 0) >= t0)
    op = sum(float(inv) * float(roi) / 100.0 for inv, roi in opens)
    return round(cp, 4), round(op, 4)


def _mode(closed_pnl, open_pnl, now):
    """-> (mode, reason). Also keeps the day's best profit (peak) and a fresh start on a new day."""
    global _dirty
    with _lock:
        t0 = day_start(now)
        if _day.get("start") != t0:
            _day.update(start=t0, peak=0.0, mode="HUNT", why="")
            _dirty = True
        tot = closed_pnl + open_pnl
        if tot > _day["peak"]:
            _day["peak"] = round(tot, 4)
            _dirty = True
        tgt, cap, gb = _cfg["target_usdt"], _cfg["loss_cap_usdt"], _cfg["giveback_pct"]
        peak = _day["peak"]
        if cap > 0 and tot <= -cap:
            mode, why = "STOPPED", "Loss cap reached (%.2f of %.2f USDT). No new AI trade until the next day." % (-tot, cap)
        elif tgt > 0 and peak >= tgt and gb > 0 and tot <= peak - peak * gb / 100.0:
            mode, why = "REST", "Target was reached (best %.2f USDT) but %.0f%% of it has been given back. Resting for today to keep the rest." % (peak, gb)
        elif tgt > 0 and tot >= tgt:
            mode, why = "DONE", "Target reached (%.2f of %.2f USDT). Only coins with a clearly profitable history are taken now." % (tot, tgt)
        else:
            mode, why = "HUNT", ""
        if mode != _day.get("mode"):
            _day["mode"], _day["why"] = mode, why
            _journal.append({"t": now, "kind": "MODE", "text": "Mode %s. %s" % (mode, why) if why else "Mode HUNT (normal)."})
            _dirty = True
        return mode, why


def check(sym, side, closed, opens, n_open, coin_status, now=None):
    """Should the AI copy a new bot signal? -> (take: bool, mode, reason). coin_status is ai_coin_memory's word."""
    global _dirty
    try:
        _load()
        now = now or time.time()
        cp, op = day_numbers(closed, opens, now)
        mode, why = _mode(cp, op, now)
        take, reason = True, ""
        if mode == "STOPPED" or mode == "REST":
            take, reason = False, why
        elif _cfg["max_open"] > 0 and n_open >= _cfg["max_open"]:
            take, reason = False, "Max open trades (%d) reached, so this signal was skipped." % _cfg["max_open"]
        elif mode == "DONE" and coin_status != "Trusted":
            take, reason = False, "Target already reached today and %s is not a Trusted coin (status: %s)." % (sym, coin_status)
        elif coin_status == "Avoid":
            take, reason = False, "%s lost money in both halves of its history (status Avoid), so the AI skipped it." % sym
        with _lock:
            _journal.append({"t": now, "kind": "TAKE" if take else "SKIP",
                             "text": "%s %s %s%s" % ("Took" if take else "Skipped", sym, "LONG" if side == "BUY" else "SHORT",
                                                      "" if take else ": " + reason)})
            _dirty = True
        _save()
        return take, mode, reason
    except Exception as e:
        print(f"[AIPlanner] check: {e}")
        return True, "HUNT", ""


def view(closed, opens, now=None):
    """For the screen."""
    try:
        _load()
        now = now or time.time()
        cp, op = day_numbers(closed, opens, now)
        mode, why = _mode(cp, op, now)
        with _lock:
            c, peak, jr = dict(_cfg), _day["peak"], list(_journal[-15:])
        tot = cp + op
        left_h = max(0.0, (day_start(now) + DAY_S - now) / 3600.0)
        return {"cfg": c, "mode": mode, "why": why, "closed_pnl": round(cp, 2), "open_pnl": round(op, 2),
                "day_pnl": round(tot, 2), "peak": round(peak, 2), "hours_left": round(left_h, 1),
                "target_pct": round(max(0.0, tot) / c["target_usdt"] * 100.0, 0) if c["target_usdt"] > 0 else None,
                "loss_left": round(c["loss_cap_usdt"] + tot, 2) if c["loss_cap_usdt"] > 0 else None,
                "mirror": mirror(closed), "journal": list(reversed(jr)), "on": c["target_usdt"] > 0 or c["loss_cap_usdt"] > 0 or c["max_open"] > 0}
    except Exception:
        return {"cfg": {}, "mode": "HUNT", "why": "", "journal": [], "on": False}


AFTER_LOSS_S = 600        # "right after a loss" = opened within 10 minutes of an AI loss closing
SAME_COIN_S = 1800        # same coin re-entered within 30 minutes of a loss on it
MIRROR_MIN = 10           # trades in a group before the AI says anything about it


def mirror(closed):
    """The 'mirror' for revenge trading: how do trades opened right after a loss do, compared with all the others?
    Pure statistics of the AI's own closed trades - it blocks nothing, it only shows the AI (and you) the numbers.
    -> {'after_loss': {n, wins, avg}, 'same_coin': {...}, 'other': {...}, 'text': str}"""
    try:
        cl = sorted([c for c in closed if c.get("t0") and c.get("t1")], key=lambda c: c["t0"])
        losses = [(c["t1"], c["sym"]) for c in cl if float(c.get("roi") or 0) < 0]
        g = {"after_loss": [], "same_coin": [], "other": []}
        for c in cl:
            prior = [(t, sy) for t, sy in losses if t <= c["t0"] and c["t0"] - t <= AFTER_LOSS_S]
            same = [1 for t, sy in losses if sy == c["sym"] and t <= c["t0"] and c["t0"] - t <= SAME_COIN_S]
            roi = float(c.get("roi") or 0)
            if same:
                g["same_coin"].append(roi)
            if prior:
                g["after_loss"].append(roi)
            if not prior and not same:
                g["other"].append(roi)
        out = {k: {"n": len(v), "wins": sum(1 for x in v if x > 0), "avg": round(sum(v) / len(v), 2) if v else None}
               for k, v in g.items()}
        a, o = out["after_loss"], out["other"]
        if a["n"] >= MIRROR_MIN and o["n"] >= MIRROR_MIN:
            if a["avg"] < o["avg"] - 1.0:
                text = "Trades opened right after a loss did worse (avg %.1f%% ROI vs %.1f%%). The AI treats that as a warning sign." % (a["avg"], o["avg"])
            elif a["avg"] > o["avg"] + 1.0:
                text = "Trades right after a loss did NOT do worse (avg %.1f%% ROI vs %.1f%%), so no revenge pattern so far." % (a["avg"], o["avg"])
            else:
                text = "No clear difference between trades right after a loss and the others yet."
        else:
            text = "Still collecting: needs %d trades right after a loss and %d others." % (MIRROR_MIN, MIRROR_MIN)
        out["text"] = text
        return out
    except Exception:
        return {"after_loss": {}, "same_coin": {}, "other": {}, "text": ""}


def reset_day():
    global _dirty
    with _lock:
        _day.update(start=0, peak=0.0, mode="HUNT", why="")
        _journal.clear()
        _dirty = True
    _save(force=True)
