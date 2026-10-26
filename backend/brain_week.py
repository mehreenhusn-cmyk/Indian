"""F3 weekly report card + time-of-day cap for the Brain's OWN pretend trades only (never Dual Bot, never the main bot).

Report card: last 7 trading days (00:00 UTC = 5:30 AM IST) of own finished trades: trades, win %, USDT (fee inside), best and worst day,
and the same 6-hour blocks the tag lab uses ("00-06 UTC" ...).
Cap: once the own book has 7+ days AND 300+ finished trades, a block with 30+ finished trades that lost USDT in BOTH the older and the newer half
may open at most TOD_CAP new own trades per day. Before that it only reports. It is a cap, not a ban, so the Brain keeps learning.
Anything that goes wrong here = no cap, trade as before.
"""
import time

MIN_DAYS, MIN_OWN, BLOCK_MIN, TOD_CAP, SHOW_DAYS = 7, 300, 30, 3, 7
DAY_MS = 86_400_000


def block_of(ms):
    h = time.gmtime(ms / 1000.0).tm_hour
    return "%02d-%02d UTC" % ((h // 6) * 6, (h // 6) * 6 + 6)


def _usdt(t):
    import brain_own as BO
    return BO._usdt(t)


def _day0(ms):
    return ms - ms % DAY_MS


def _blocks(cl):
    out = []
    for name in ("00-06 UTC", "06-12 UTC", "12-18 UTC", "18-24 UTC"):
        rs = sorted((t for t in cl if block_of(t.get("t", 0)) == name), key=lambda t: t.get("closed_at", 0))
        h = len(rs) // 2
        old, new = sum(_usdt(t) for t in rs[:h]), sum(_usdt(t) for t in rs[h:])
        w = sum(1 for t in rs if t["net"] > 0)
        out.append({"block": name, "n": len(rs), "win_pct": int(round(100.0 * w / len(rs))) if rs else 0, "usdt": round(old + new, 2),
                    "bad": len(rs) >= BLOCK_MIN and old < 0 and new < 0})
    return out


def report(own, now_ms=None):
    """-> plain dict for the Brain tab. Never raises."""
    try:
        now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
        cl = [t for t in (own or {}).get("closed", []) if t.get("net") is not None]
        since = (own or {}).get("since") or now_ms
        days_of_data = int((now_ms - since) // DAY_MS)
        d0 = _day0(now_ms)
        days = []
        for k in range(SHOW_DAYS):
            a = d0 - k * DAY_MS
            ds = [t for t in cl if a <= t.get("closed_at", 0) < a + DAY_MS]
            w = sum(1 for t in ds if t["net"] > 0)
            days.append({"day": time.strftime("%m-%d", time.gmtime(a / 1000.0)), "n": len(ds), "win_pct": int(round(100.0 * w / len(ds))) if ds else 0,
                         "usdt": round(sum(_usdt(t) for t in ds), 2)})
        active_days = [x for x in days if x["n"] > 0]
        tot_n, tot_u = sum(x["n"] for x in days), round(sum(x["usdt"] for x in days), 2)
        ready = days_of_data >= MIN_DAYS and len(cl) >= MIN_OWN
        blocks = _blocks(cl)
        bad = [b["block"] for b in blocks if b["bad"]] if ready else []
        sk = (own or {}).get("tod_skip") or {}
        out = {"ready": ready, "active": bool(bad), "days_of_data": days_of_data, "n": len(cl), "need_days": MIN_DAYS, "need_n": MIN_OWN, "cap": TOD_CAP,
               "days": days, "blocks": blocks, "bad": bad, "week_n": tot_n, "week_usdt": tot_u, "skipped": sk.get("n", 0) if sk.get("day") == d0 else 0}
        if active_days:
            out["best"], out["worst"] = max(active_days, key=lambda x: x["usdt"]), min(active_days, key=lambda x: x["usdt"])
        if not ready:
            out["status"] = "collecting"
            out["text"] = ("Collecting: %d of %d days and %d of %d own finished trades. The time-of-day limit switches on only after both. "
                           "Last 7 days so far: %d trades, %+.2f USDT." % (days_of_data, MIN_DAYS, len(cl), MIN_OWN, tot_n, tot_u))
        elif bad:
            out["status"] = "limit_on"
            out["text"] = ("Last 7 days: %d trades, %+.2f USDT. LIMIT ON: %s lost USDT in both the older and the newer half, so the Brain opens at most %d new trades a day in %s."
                           % (tot_n, tot_u, ", ".join(bad), TOD_CAP, "that block" if len(bad) == 1 else "those blocks"))
        else:
            out["status"] = "limit_off"
            out["text"] = "Last 7 days: %d trades, %+.2f USDT. No time block loses in both halves, so no limit is needed." % (tot_n, tot_u)
        return out
    except Exception:
        return {"ready": False, "active": False, "status": "error", "text": "Week report: not available right now."}


def blocked(own, now_ms, opened_in_block):
    """True when this new own trade (opening at now_ms) must be skipped. opened_in_block = how many were already opened in this block this round. Never raises."""
    try:
        blk = block_of(now_ms)
        if blk not in report(own, now_ms)["bad"]:
            return False
        d0 = _day0(now_ms)
        today = len([t for t in own.get("open", []) + own.get("closed", []) if t.get("t", 0) >= d0 and block_of(t.get("t", 0)) == blk])
        if today + opened_in_block < TOD_CAP:
            return False
        sk = own.setdefault("tod_skip", {"day": d0, "n": 0})
        if sk.get("day") != d0:
            sk["day"], sk["n"] = d0, 0
        sk["n"] += 1
        return True
    except Exception:
        return False
