"""Smart Brain - its OWN paper trades (separate book, paper only, no real money).

What it does: when the Brain's 5-minute scan finds a setup it likes (clean score, win chance, both panes agree), it opens a pretend
trade at that candle's close, with the same stop / take-profit levels and the same exit rule as Dual Bot, and follows it to the end.
Where it lives: its own file smart_brain_own.json. It reads candles only. It never writes dual_lab_data.json, never touches the main bot.
Plain Python, no numpy, no torch. Anything that goes wrong here is caught by the caller and must never stop the Brain.
"""
import time

try:   # Batch 2: version label (label only). Missing file = no label
    import brain_meta as _BM
except Exception:
    _BM = None

MAX_OPEN = 20            # most pretend trades open at once (keeps the phone light, not a trading rule)
KEEP_CLOSED = 300        # finished trades kept in the file
MAX_FETCH = 6            # coins re-checked per round (candles are downloaded, so keep it small)
EXIT_NAME = "BOT exit (TP4, main cross)"   # default exit = what Dual Bot uses; brain_exit_pick can choose another style per trade
LEV, FEE = 10.0, 1.0     # same as Dual Bot: 10x, fee in ROI points
MAX_DAY = 40             # most new own trades per trading day (day = 5:30 AM IST = 00:00 UTC); keeps learning from turning into noise
# The Brain starts loose and gets pickier by itself as its own judged trades grow: (judged trades needed, stage, min clean, min win %, max divergence)
# BE1 Force Explore: until the Brain has EXPLORE_N finished own trades it takes a few small, capped paper trades so it can make mistakes and learn.
EXPLORE_N = 30           # finished own trades that end the explore phase (then the normal stages below take over)
EXPLORE_MG = 25.0        # margin (USDT) of one explore trade (normal own trades use the Dual Bot margin)
EXPLORE_MAX_OPEN = 6     # most explore trades open at once
EXPLORE_DAY = 12         # most new explore trades per trading day
EXPLORE_LOSS = -30.0     # explore trades closed today lose more than this (USDT) = no new explore trade until tomorrow
EXPLORE_ROUND = 3        # most new explore trades per 5-minute scan (the cleanest first)
STAGES = ((0, "learning", 45, 45, 55), (100, "medium", 55, 50, 48), (300, "quality", 60, 55, 43))


def judged(own):
    return len([t for t in (own or {}).get("closed", []) if t.get("net") is not None])


def exploring(own):
    """True while the Brain still has fewer than EXPLORE_N finished own trades (Force Explore, paper only)."""
    return judged(own) < EXPLORE_N


def stage_for(n):
    """-> (stage name, min clean, min win %, max divergence) for n finished own trades. Explore = no floor, only the lessons still block."""
    if n < EXPLORE_N:
        return "exploring", 0, 0, 100
    cur = STAGES[0]
    for st in STAGES:
        if n >= st[0]:
            cur = st
    return cur[1], cur[2], cur[3], cur[4]


def next_stage(n):
    for st in STAGES:
        if n < st[0]:
            return st[1], st[0] - n
    return None, 0


def _day_start_ms(now_ms):
    return now_ms - now_ms % 86_400_000


def plan_levels(S, i, d, strat):
    """Entry / stop / take-profit levels for a BUY (d=1) or SELL (d=-1) at closed candle i, built exactly like Dual Bot's entry.
    -> dict or None when there is no sensible room."""
    mean, sd = S["sma"][i], S["std"][i]
    if not sd or mean is None:
        return None
    entry = S["c"][i]
    sl = S["l"][i] if d > 0 else S["h"][i]
    lv = {"zero_price": mean, "onesd": mean + sd, "twosd": mean + 2 * sd, "threesd": mean + 3 * sd,
          "neg_onesd": mean - sd, "neg_twosd": mean - 2 * sd, "neg_threesd": mean - 3 * sd}
    tps = list(strat.calculate_tp_levels(entry, d > 0, lv))
    if (d > 0 and not (sl < entry < tps[0])) or (d < 0 and not (tps[0] < entry < sl)):
        return None
    return {"entry": entry, "sl": sl, "tps": tps, "ct": S["t"][i]}


def open_from(own, watch, now_ms=None, pick_fn=None):
    """Opens pretend trades from the scan's list. Each item carries '_plan' and '_tg' (removed here, so the app view stays small).
    A candle is used once; one open trade per coin and side.
    pick_fn(tags) -> (exit rule name, reason) lets the Brain choose the exit style it learned; any problem there = default exit."""
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    own.setdefault("since", now_ms)
    own.setdefault("open", [])
    own.setdefault("closed", [])
    own.setdefault("seen", {})
    opened = 0
    opened_side = 0   # F1: sideways own trades opened in this round (see brain_side.py)
    opened_blk = 0    # F3: own trades opened in this round (all in the same 6-hour block, see brain_week.py)
    import brain_side as BS
    import brain_week as BW
    day0 = _day_start_ms(now_ms)
    today = len([t for t in own["open"] + own["closed"] if t.get("t", 0) >= day0])
    exp = exploring(own)
    cap_open, cap_day = (EXPLORE_MAX_OPEN, EXPLORE_DAY) if exp else (MAX_OPEN, MAX_DAY)
    if exp:   # the cleanest setups first; a day that already lost too much opens nothing more
        watch = sorted(watch or [], key=lambda x: -(x.get("clean") or 0))
        lost = sum(_usdt(t) for t in own["closed"] if t.get("explore") and t.get("closed_at", 0) >= day0 and t.get("net") is not None)
        if lost <= EXPLORE_LOSS:
            watch = []
    for w in watch or []:
        plan, tg = w.pop("_plan", None), w.pop("_tg", None)
        if not plan or not tg:
            continue
        key = "%s|%s|%s|%s" % (w["s"], w["f"], w["d"], plan["ct"])
        if key in own["seen"]:
            continue
        own["seen"][key] = 1
        if today + opened >= cap_day or (exp and opened >= EXPLORE_ROUND):
            continue
        if BS.blocked(own, tg, now_ms, opened_side):   # F1: only active after 100+ own trades and a losing sideways book
            continue
        if BW.blocked(own, now_ms, opened_blk):   # F3: only after 7+ days, 300+ own trades and a block that loses in both halves
            continue
        if len(own["open"]) >= cap_open or any(t["s"] == w["s"] and t["d"] == w["d"] for t in own["open"]):
            continue
        ex, why = EXIT_NAME, ""
        if pick_fn:
            try:
                ex, why = pick_fn(tg)
            except Exception:
                ex, why = EXIT_NAME, ""
        own["open"].append({
            "id": key, "s": w["s"], "f": w["f"], "d": w["d"], "ct": plan["ct"], "t": now_ms, "entry": plan["entry"], "sl": plan["sl"],
            "tps": plan["tps"], "exit": ex, "why_exit": why, "clean": w.get("clean"), "div": w.get("div"),
            "win_pct": (w.get("prob") or {}).get("win_pct"), "n": (w.get("prob") or {}).get("n"), "tg": tg,
            "stage": w.get("stage"), "lesson": w.get("lesson") or "",
            "status": "open", "live": None, "chk": 0, "brain_version": _BM.BRAIN_VERSION if _BM else None})
        if exp:
            own["open"][-1].update(explore=True, mg=EXPLORE_MG)
        opened += 1
        opened_side += 1 if BS.is_side(tg) else 0
        opened_blk += 1
    if len(own["seen"]) > 2000:
        own["seen"] = {k: 1 for k in list(own["seen"])[-1000:]}
    return opened


def settle(own, fetch_limit, now_ms=None):
    """Follows every open pretend trade with the newest candles and closes it when its stop / target / exit rule says so.
    Only coins whose newest candle is probably new are downloaded, at most MAX_FETCH per round."""
    import filter_lab as FL
    import tag_lab as TL
    from recovered_bot import ai_ind_features as F
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    todo = [t for t in own.get("open", []) if now_ms - t.get("chk", 0) >= FL.TF_MS[t["f"]]]
    todo.sort(key=lambda t: t.get("chk", 0))
    groups = {}
    for t in todo:
        groups.setdefault((t["s"], t["f"]), []).append(t)
    done = 0
    for (sym, tf), items in list(groups.items())[:MAX_FETCH]:
        cs = fetch_limit(sym, tf, 470)
        if not cs or len(cs) < F.MIN_BARS + 5:
            continue
        S = F.build(cs)
        Z = TL.z_series(S)
        pos = {c: k for k, c in enumerate(S["t"])}
        for t in items:
            rule = TL.EXITS.get(t.get("exit")) or TL.EXITS[EXIT_NAME]
            t["chk"] = now_ms
            i = pos.get(t["ct"])
            if i is None:
                t["status"] = "expired"
                continue
            r = TL.sim_rule(S, Z, i, t["d"], t["entry"], t["sl"], t["tps"], LEV, FEE, **rule)
            if r is not None:
                t.update(net=round(r["net"], 2), end=r["why"], bars=r["bars"], hit=r["hit"], status="closed", closed_at=now_ms,
                         mfe=round(r["mfe"], 2), giveback=round(r["giveback"], 2))   # Batch 2
                try:   # F2: what would waiting for a retest have made? (measure only, see brain_retest.py)
                    import brain_retest as BR
                    res = BR.twin(S, Z, i, t["d"], t["sl"], t["tps"], rule, TL, LEV, FEE)
                    if res is not None:
                        t["rt"] = list(res)
                except Exception:
                    pass
                t["live"] = None
                done += 1
            else:
                lv = TL.sim_rule(S, Z, i, t["d"], t["entry"], t["sl"], t["tps"], LEV, FEE, allow_open=True, **rule)
                t["live"] = round(lv["net"], 2) if lv else None
                t["lbars"] = int(lv["bars"]) if lv else 0
        time.sleep(0.05)
    still = [t for t in own.get("open", []) if t["status"] == "open"]
    fin = [t for t in own.get("open", []) if t["status"] == "closed"]
    own["open"] = still
    own["closed"] = (own.get("closed", []) + fin)[-KEEP_CLOSED:]
    return done


def _usdt(t):
    if t.get("mg"):   # explore trades carry their own small margin
        return t["mg"] * (t.get("net") or 0.0) / 100.0
    try:
        import dual_lab
        mg = dual_lab._mg(t)
    except Exception:
        mg = 100.0
    return mg * (t.get("net") or 0.0) / 100.0


def _side_rule(own):
    try:
        import brain_side as BS
        return BS.state(own, int(time.time() * 1000))
    except Exception:
        return None


def _week(own):
    try:
        import brain_week as BW
        return BW.report(own)
    except Exception:
        return None


def _retest_book(own):
    try:
        import brain_retest as BR
        return BR.report(own)
    except Exception:
        return None


def summary(own):
    """Small summary for the Brain tab. None until the book exists."""
    if not own or own.get("since") is None:
        return None
    cl = [t for t in own.get("closed", []) if t.get("net") is not None]
    wins = sum(1 for t in cl if t["net"] > 0)
    pnl = round(sum(_usdt(t) for t in cl), 2)
    def kind(t):
        try:
            import brain_exit_pick as XP
            return XP.KIND_WORD[XP.kind_of(t.get("exit") or EXIT_NAME)]
        except Exception:
            return None
    by = {}
    for t in cl:
        b = by.setdefault(kind(t) or "?", {"kind": kind(t) or "?", "n": 0, "wins": 0, "pnl": 0.0})
        b["n"] += 1
        b["wins"] += 1 if t["net"] > 0 else 0
        b["pnl"] = round(b["pnl"] + _usdt(t), 2)
    op = []
    for t in own.get("open", []):
        live = t.get("live")
        op.append({"s": t["s"], "f": t["f"], "d": t["d"], "live": live, "kind": kind(t), "why_exit": t.get("why_exit"), "win_pct": t.get("win_pct"), "clean": t.get("clean"),
                   "usdt": None if live is None else round(_usdt(dict(t, net=live)), 2)})
    rec = [{"s": t["s"], "f": t["f"], "d": t["d"], "kind": kind(t), "net": t["net"], "usdt": round(_usdt(t), 2), "end": t.get("end"), "bars": t.get("bars")}
           for t in sorted(cl, key=lambda x: -x.get("closed_at", 0))[:8]]
    n = len(cl)
    exp = n < EXPLORE_N
    if n == 0:
        text = ("The Brain has %d own pretend trade(s) open. None has finished yet." % len(op)) if op else \
               "No own trade yet. The Brain opens one only when its scan finds a setup it really likes."
    else:
        text = "Own pretend trades finished: %d. Won %d%% of them. Total %+.2f USDT (fee inside)." % (n, round(100.0 * wins / n), pnl)
    if exp:
        text = "Exploring - taking limited paper trades to learn (%d of %d finished). Small size, a few at a time. " % (n, EXPLORE_N) + text
    stg = stage_for(n)[0]
    nxt, left = next_stage(n)
    return {"stage": stg, "exploring": exp, "explore_n": EXPLORE_N, "next_stage": nxt, "next_in": left, "since": own.get("since"), "open": op, "n": n, "wins": wins, "pnl": pnl, "avg": round(sum(t["net"] for t in cl) / n, 2) if n else 0.0,
            "recent": rec, "text": text, "side_rule": _side_rule(own), "retest_book": _retest_book(own), "week": _week(own), "exit": EXIT_NAME, "by_exit": sorted(by.values(), key=lambda x: -x["pnl"])}
