"""F1 sideways self-rule for the Brain's OWN pretend trades only (never Dual Bot, never the main bot).

Rule: once the own book has 100+ finished trades AND 30+ of them were sideways entries AND the sideways ones lost USDT in BOTH the
older and the newer half, the Brain opens at most DAY_CAP new sideways own trades per trading day. Before that it does nothing.
It is a cap (not a ban), so the Brain keeps learning from sideways. Anything that goes wrong here = no rule, trade as before.
"""
MIN_OWN, MIN_SIDE, DAY_CAP = 100, 30, 5


def _is_side(t):
    import smart_brain as B
    return B.side_group(t.get("tg") or {}) == "sideways"


def _usdt(t):
    import brain_own as BO
    return BO._usdt(t)


def _day0(now_ms):
    return now_ms - now_ms % 86_400_000


def state(own, now_ms=None):
    """-> small plain dict for the Brain tab: numbers + one plain sentence. Never raises."""
    try:
        cl = [t for t in (own or {}).get("closed", []) if t.get("net") is not None]
        sw = [t for t in cl if _is_side(t)]
        pnl = round(sum(_usdt(t) for t in sw), 2)
        h = len(sw) // 2
        older, newer = sum(_usdt(t) for t in sw[:h]), sum(_usdt(t) for t in sw[h:])
        ready = len(cl) >= MIN_OWN and len(sw) >= MIN_SIDE
        active = ready and older < 0 and newer < 0
        sk = (own or {}).get("side_skip") or {}
        skipped = sk.get("n", 0) if sk.get("day") == _day0(int(now_ms or 0)) or now_ms is None else 0
        if not ready:
            text = "Waiting for data: %d of %d own finished trades, %d of %d of them sideways." % (len(cl), MIN_OWN, len(sw), MIN_SIDE)
        elif active:
            text = "ON: sideways own trades lost %+.2f USDT (older and newer half both negative), so the Brain opens at most %d sideways trades a day." % (pnl, DAY_CAP)
        else:
            text = "OFF: enough data, but sideways is not losing in both halves (%+.2f USDT), so no limit is needed." % pnl
        return {"ready": ready, "active": active, "n": len(cl), "n_side": len(sw), "side_pnl": pnl, "cap": DAY_CAP, "skipped": skipped, "text": text}
    except Exception:
        return {"ready": False, "active": False, "text": "Sideways self-rule: not available right now."}


def blocked(own, tg, now_ms, opened_side=0):
    """True when this candidate must be skipped. Counts the skip. Never raises."""
    try:
        if not _is_side({"tg": tg}):
            return False
        if not state(own, now_ms)["active"]:
            return False
        d0 = _day0(now_ms)
        today = len([t for t in own.get("open", []) + own.get("closed", []) if t.get("t", 0) >= d0 and _is_side(t)])
        if today + opened_side < DAY_CAP:
            return False
        sk = own.setdefault("side_skip", {"day": d0, "n": 0})
        if sk.get("day") != d0:
            sk["day"], sk["n"] = d0, 0
        sk["n"] += 1
        return True
    except Exception:
        return False


def is_side(tg):
    try:
        return _is_side({"tg": tg})
    except Exception:
        return False
