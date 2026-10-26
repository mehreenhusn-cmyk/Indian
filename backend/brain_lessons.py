"""brain_lessons.py - Part B1: TIMING SYNC report + plain "how to use both indicators" lessons.

Which indicator spoke first, and how far apart, when Dual Bot took a trade? Counts finished Dual Bot trades by the existing
"order" tag (tag_lab._order). REPORT ONLY: reads trades, changes nothing, Dual Bot still takes every signal.
BTC has its own margin and totals, so it is left out (same rule as the Performance tab). Real USDT, fee inside.
No network. Test: cd backend && python3 test_brain_lessons.py
"""
MIN_DONE = 30        # finished alt trades before the report talks
MIN_G = 10           # trades a group needs before it gets a verdict
MIN_HALF = 20        # trades a group needs before the older-half / newer-half check is shown

GROUPS = (
    ("same", "Same candle (both at once)"),
    ("z12", "Z first, Main 1-2 candles later"),
    ("z35", "Z first, Main 3-5 candles later"),
    ("m12", "Main first, Z 1-2 candles later"),
    ("m35", "Main first, Z 3-5 candles later"),
    ("zonly", "Z only (Main gave nothing)"),
    ("monly", "Main only (Z gave nothing)"),
    ("opp", "Other indicator said the opposite"),
)
NAME = dict(GROUPS)


def classify(t):
    """One finished trade -> group key (or None if the old trade has no usable 'order' tag)."""
    tg = t.get("tg") or {}
    o = str(tg.get("order") or "")
    if o.startswith("both on the same candle") or (t.get("src") or tg.get("src")) == "BOTH":
        return "same"
    if "OPPOSITE" in o:
        return "opp"
    if "gave nothing" in o:                       # "main chart gave nothing" = the Z candle fired alone
        return "zonly" if o.startswith("main chart") else "monly"
    if "came first" in o:
        who = "m" if o.startswith("main chart") else "z"
        return who + ("12" if "(1-2" in o else "35")
    return None


def _stat(items, usdt):
    n = len(items)
    w = sum(1 for t in items if t["net"] > 0)
    p = round(sum(usdt(t) for t in items), 2)
    return {"n": n, "wins": w, "win_pct": int(round(100.0 * w / n)) if n else None, "pnl": p, "avg": round(p / n, 2) if n else None}


def _steady(items, usdt):
    """Do the older and the newer half of the group point the same way? None = too few trades to say."""
    if len(items) < MIN_HALF:
        return None
    h = len(items) // 2
    return (sum(usdt(t) for t in items[:h]) < 0) == (sum(usdt(t) for t in items[h:]) < 0)


def _tsi_with(t):
    return str((t.get("tg") or {}).get("tsi_zero") or "").startswith("TSI with the trade")


def _pool(rows, keys):
    """Several groups as one: only if every group is ready (so one tiny group cannot steer it)."""
    its = []
    for k in keys:
        if not rows[k]["ready"]:
            return None
        its += rows[k]["_items"]
    return its


def timing_report(trades):
    import dual_lab
    import smart_brain as B
    usdt = lambda t: dual_lab._mg(t) * t["net"] / 100.0
    done = [t for t in trades if t.get("status") == "closed" and t.get("net") is not None and t.get("tg") and t.get("s") != dual_lab.BTC_SYM]
    done.sort(key=lambda t: t["t"])
    out = {"status": "collecting", "done": len(done), "need": MIN_DONE, "total": round(sum(usdt(t) for t in done), 2),
           "text": "Collecting: %d finished trades read, the timing report needs %d." % (len(done), MIN_DONE), "groups": [], "deep": None, "lessons": []}
    if len(done) < MIN_DONE:
        return out
    rows = {}
    for key, name in GROUPS:
        its = [t for t in done if classify(t) == key]
        r = {"key": key, "name": name, "ready": len(its) >= MIN_G, "steady": _steady(its, usdt), "_items": its}
        r.update(_stat(its, usdt))
        if r["ready"]:
            r["tsi_with"] = _stat([t for t in its if _tsi_with(t)], usdt)
            r["tsi_against"] = _stat([t for t in its if not _tsi_with(t)], usdt)
            sw = [t for t in its if B.side_group(t["tg"]) == "sideways"]
            r["side_n"], r["side_pnl"] = len(sw), round(sum(usdt(t) for t in sw), 2)
        rows[key] = r
    ready = [r for r in rows.values() if r["ready"]]
    out["status"] = "ready"
    if ready:
        best, worst = max(ready, key=lambda r: r["avg"]), min(ready, key=lambda r: r["avg"])
        out["text"] = "Best timing: %s (%+.2f USDT per trade, %d trades). Worst: %s (%+.2f USDT per trade, %d trades)." % (
            best["name"], best["avg"], best["n"], worst["name"], worst["avg"], worst["n"])
    else:
        out["text"] = "%d finished trades read, but no timing group has %d trades yet." % (len(done), MIN_G)
    # deep clean candidate: both indicators within 1-2 candles + TSI with the trade + market not sideways (defined up front, tested on the same trades = a hint)
    dk = [t for t in done if classify(t) in ("same", "z12", "m12") and _tsi_with(t) and B.side_group(t["tg"]) != "sideways"]
    ids = {id(t) for t in dk}
    rest = [t for t in done if id(t) not in ids]
    out["deep"] = dict(_stat(dk, usdt), ready=len(dk) >= MIN_G, steady=_steady(dk, usdt), rest=_stat(rest, usdt),
                       rule="both indicators within 1-2 candles + TSI with the trade + market not sideways")
    out["lessons"] = lessons(rows, out["deep"], usdt)
    for r in rows.values():
        r.pop("_items")
        out["groups"].append(r)
    return out


def _care(r):
    return " Careful: the older and the newer half disagree." if r.get("steady") is False else ""


def lessons(rows, deep, usdt):
    L = []

    def add(tone, text):
        L.append({"tone": tone, "text": text})

    def avg(its):
        return sum(usdt(t) for t in its) / len(its)
    same = rows["same"]
    if same["ready"]:
        add("good" if same["pnl"] > 0 else "bad", "Both indicators on the SAME candle: %d trades, %d%% won, %+.2f USDT.%s" % (same["n"], same["win_pct"], same["pnl"], _care(same)))
    zo, mo = rows["zonly"], rows["monly"]
    if zo["ready"] and mo["ready"]:
        add("info", "One indicator alone: Z only made %+.2f USDT per trade, Main only %+.2f. %s is the weaker one to trust alone." % (
            zo["avg"], mo["avg"], "Main" if mo["avg"] < zo["avg"] else "Z"))
    first, alone = _pool(rows, ("z12", "z35", "m12", "m35")), _pool(rows, ("zonly", "monly"))
    if first and alone:
        a, b = avg(first), avg(alone)
        add("good" if a > b else "bad", "When the second indicator had already spoken a few candles before: %+.2f USDT per trade. Entry with the other one silent: %+.2f. %s" % (
            a, b, "Waiting for the second indicator looks better." if a > b else "No gain from the second indicator here."))
    near, far = _pool(rows, ("z12", "m12")), _pool(rows, ("z35", "m35"))
    if near and far:
        a, b = avg(near), avg(far)
        add("info", "Second indicator 1-2 candles apart: %+.2f per trade. 3-5 candles apart: %+.2f. %s" % (a, b, "Closer is better." if a > b else "A longer gap did not hurt."))
    allr = [r for r in rows.values() if r["ready"]]
    w = [t for r in allr for t in r["_items"] if _tsi_with(t)]
    ag = [t for r in allr for t in r["_items"] if not _tsi_with(t)]
    if len(w) >= MIN_G and len(ag) >= MIN_G:
        a, b = avg(w), avg(ag)
        add("good" if a > b else "bad", "TSI with the trade: %+.2f USDT per trade (%d trades). TSI against it: %+.2f (%d trades)." % (a, len(w), b, len(ag)))
    if same["ready"] and same.get("side_n", 0) >= 5:
        add("bad" if same["side_pnl"] < 0 else "info", "Even with both on the same candle, the %d sideways ones made %+.2f USDT." % (same["side_n"], same["side_pnl"]))
    if deep["ready"]:
        rest = deep["rest"]
        add("good" if deep["avg"] > (rest["avg"] or 0) else "bad", "Deep clean candidate (%s): %d trades, %d%% won, %+.2f per trade. All other trades: %+.2f per trade.%s" % (
            deep["rule"], deep["n"], deep["win_pct"], deep["avg"], rest["avg"] or 0, _care(deep)))
    add("info", "These are counts of what Dual Bot already did (it takes every signal). Where the older and the newer half disagree it says so. Report only.")
    return L[:10]
