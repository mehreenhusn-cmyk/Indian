"""F2 retest own book: for the Brain's OWN finished pretend trades, what if it had WAITED for a retest of the EMA50 zone instead of entering at the signal?

A paper twin, measure only: it opens nothing, changes no trade, never touches Dual Bot or the main bot. When an own trade finishes, brain_own.settle
calls twin() with the candles it already downloaded; the answer is stored on the trade as t["rt"] = [net at the retest or None, candles until the retest].
report(own) then compares the two books in USDT (fee inside). Same fill rule as Dual Bot's retest check (first touch of EMA50 + a quarter SD zone,
same stop / targets / exit rule), same waits as dual_lab.RT_WAITS. Trades finished before this part existed have no t["rt"] and are simply not counted.
"""
RT_WAITS, RT_ZONE = (3, 6, 12, 24), 0.25
MIN_SEEN = 10        # resolved trades before any number is shown
MIN_CAME = 100       # trades that came back to the retest before a verdict is given (the F2 start rule)


def twin(S, Z, i, d, sl, tps, rule, TL, lev, fee, waits=RT_WAITS, zone=RT_ZONE):
    """-> (net_at_retest, candles_until_retest) | (None, None) when it never came back | None when the retest trade is not finished yet."""
    o, h, l, n = S["o"], S["h"], S["l"], S["n"]
    for j in range(i + 1, min(n - 1, i + max(waits)) + 1):
        ema, sd = S["e50"][j], S["std"][j]
        if ema is None or sd is None:
            continue
        if (h[j] >= tps[0]) if d > 0 else (l[j] <= tps[0]):
            return (None, None)                      # ran to TP1 without us
        if (l[j] <= sl) if d > 0 else (h[j] >= sl):
            return (None, None)                      # the stop level came first
        z = ema + d * zone * sd
        if (l[j] <= z) if d > 0 else (h[j] >= z):
            fill = min(z, o[j]) if d > 0 else max(z, o[j])
            if not ((sl < fill < tps[0]) if d > 0 else (tps[0] < fill < sl)):
                return (None, None)
            r = TL.sim_rule(S, Z, j, d, fill, sl, tps, lev, fee, **rule)
            return (round(r["net"], 2), j - i) if r else None
    return (None, None)


def _usdt(t, net):
    import brain_own as BO
    return BO._usdt(dict(t, net=net))


def _block(rs, W):
    ent = [t for t in rs if t["rt"][0] is not None and t["rt"][1] is not None and t["rt"][1] <= W]
    mis = [t for t in rs if t not in ent]
    normal_all = sum(_usdt(t, t["net"]) for t in rs)
    ent_normal = sum(_usdt(t, t["net"]) for t in ent)
    ent_retest = sum(_usdt(t, t["rt"][0]) for t in ent)
    mis_normal = sum(_usdt(t, t["net"]) for t in mis)
    return {"wait": W, "n": len(rs), "entered": len(ent), "missed": len(mis), "normal_all": round(normal_all, 2),
            "entered_normal": round(ent_normal, 2), "entered_retest": round(ent_retest, 2), "missed_normal": round(mis_normal, 2),
            "gain": round(ent_retest - normal_all, 2)}


def report(own):
    """Retest book versus normal own book. Plain dict for the Brain tab. Never raises."""
    try:
        cl = [t for t in (own or {}).get("closed", []) if t.get("net") is not None and isinstance(t.get("rt"), list) and len(t["rt"]) == 2]
        if len(cl) < MIN_SEEN:
            return {"status": "collecting", "n": len(cl), "need": MIN_SEEN, "came": 0, "need_came": MIN_CAME,
                    "text": "Collecting: %d own finished trades have a retest check, the report needs %d." % (len(cl), MIN_SEEN)}
        cl.sort(key=lambda t: t.get("closed_at", 0))
        best = max((_block(cl, W) for W in RT_WAITS), key=lambda b: b["gain"])
        W, h = best["wait"], len(cl) // 2
        g_old, g_new = _block(cl[:h], W)["gain"], _block(cl[h:], W)["gain"]
        steady = (g_old > 0 and g_new > 0) or (g_old < 0 and g_new < 0)
        out = dict(best, need=MIN_SEEN, need_came=MIN_CAME, came=best["entered"], older=g_old, newer=g_new, steady=steady)
        base = ("Best wait %d candles: %d of %d own trades came back to the retest. The retest book made %+.2f USDT on those, the normal book %+.2f USDT on all %d. "
                "Difference %+.2f USDT (the %d that never came back are skipped in the retest book; the normal book made %+.2f USDT on them)."
                % (W, best["entered"], best["n"], best["entered_retest"], best["normal_all"], best["n"], best["gain"], best["missed"], best["missed_normal"]))
        if best["entered"] < MIN_CAME:
            out["status"], out["text"] = "early", base + " Only %d of %d needed trades came back, so treat this as a hint, not proof." % (best["entered"], MIN_CAME)
        elif not steady:
            out["status"], out["text"] = "unsteady", base + " The older and the newer half disagree, so wait for more data."
        else:
            out["status"] = "better" if best["gain"] > 0 else "worse"
            out["text"] = base + " The older and the newer half agree: waiting for the retest is %s for the Brain's own book." % ("better" if best["gain"] > 0 else "worse")
        return out
    except Exception:
        return {"status": "error", "text": "Retest book: not available right now.", "n": 0}
