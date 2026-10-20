"""Final Scoreboard (crypto Strategy Doctor, top).

ONE result per idea instead of pages of numbers. Two independent sources are put side by side:
  1. REPLAY    - Strategy Lab (variant_lab.py): the bot's signals replayed on candles, per timeframe 3m / 5m / 15m.
  2. SAVED     - the bot's own closed trades (Doctor's trade list): "if this rule had been on, which saved trades would be skipped".
A verdict needs the two sources to agree. Read-only: nothing here touches the bot, its settings or strategy.py.

Numbers are ROI points after fees. vs_bot > 0 means the idea beat the normal bot.
"""
import math
import time

try:
    import variant_lab as VL
except Exception:                       # tests / odd path: the scoreboard then shows "replay not available"
    VL = None

TFS = ("3m", "5m", "15m")
GROUP_TITLES = {
    "Exit and stop-loss": "Exit and stop-loss",
    "Indicators (skip signals)": "TSI / Z-score / chop",
    "Bollinger (skip signals)": "Bollinger Bands",
    "CVD (order flow)": "CVD (order flow)",
    "Bands": "SD bands / EMA bands",
    "Mixes": "Mixes",
    "Outside suggestion (4 points)": "Kim's ideas",
    "Photo ideas (SD100, mean reversion, Kell)": "Photo ideas",
}
GROUP_ORDER = ["Bollinger Bands", "SD bands / EMA bands", "TSI / Z-score / chop", "CVD (order flow)",
               "Exit and stop-loss", "Kim's ideas", "Photo ideas", "Mixes"]

LABELS = {
    "helps": "HELPS",
    "hurts": "HURTS",
    "mixed": "MIXED",
    "replay_up": "REPLAY ONLY +",
    "replay_down": "REPLAY ONLY -",
    "saved_up": "SAVED ONLY +",
    "saved_down": "SAVED ONLY -",
    "unclear": "NOT CLEAR",
}


# One plain line per idea: what it does to the bot's signals (shown under the idea name in the app).
DESC = {
    "sl_prev1": "Stop-loss placed at the previous candle's extreme, so it is a bit wider than the bot's.",
    "sl_prev3": "Stop-loss at the extreme of the last 3 candles (wider than the bot).",
    "sl_swing": "Stop-loss at the extreme of the last 10 candles (much wider).",
    "sl_atr": "Stop-loss 1.5 x ATR away (ATR = normal candle size).",
    "be_fee": "After TP1 is hit, move the stop to entry + fee instead of leaving it.",
    "tp2": "Close the whole trade at TP2 instead of waiting for TP4.",
    "run": "No TP4 exit. Stay in the trade until the opposite signal comes.",
    "run_prev1": "Stay till the opposite signal, with the wider previous-candle stop-loss.",
    "tsi": "Take the signal only if TSI (buyers vs sellers) points the same way as the trade.",
    "zmove": "Take the signal only if the Z-score is moving in the trade's direction.",
    "zrule": "SD 0 rule: no BUY below the mean line, no SELL above the mean line.",
    "both": "Take the signal only if both TSI and Z-score agree with the trade.",
    "chop": "Skip signals when the EMA50 was crossed more than 2 times in the last 20 candles (messy market).",
    "bb_sq": "Bollinger Bands squeeze = bands tight = sideways market. Skip signals inside a squeeze.",
    "bb_side": "BUY only above the Bollinger middle line, SELL only below it.",
    "bb_late": "Skip signals when price is already outside the Bollinger band (move is late).",
    "bb_exp": "Take signals only while the Bollinger Bands are opening up (trend starting).",
    "cvd3": "Take the signal only if real buy/sell flow (CVD) of the last 3 candles agrees.",
    "cvd_push": "Take the signal only if the signal candle was pushed by real flow (10% or more).",
    "cvd_exp": "CVD agrees AND Bollinger Bands are opening up.",
    "wait": "Do not enter on the signal candle. Wait 1 candle, then enter (control test).",
    "wait_cvd": "Wait 1 candle, then enter only if CVD still agrees.",
    "run_cvd": "Stay till the opposite signal, but only on signals where CVD agrees.",
    "ema": "SD bands built on EMA200 instead of SMA200 (EMA reacts faster than SMA).",
    "mix1": "Wider previous-candle stop-loss + skip Bollinger squeeze.",
    "mix2": "TSI and Z both agree + wider previous-candle stop-loss.",
    "mix3": "Stay till the opposite signal, only when TSI agrees.",
    "mix4": "Stay till the opposite signal + wider stop-loss + skip squeeze.",
    "sd100": "SD bands built on the last 100 candles instead of 200 (reacts faster). Same entry, same stop, targets = next 4 bands.",
    "meanrev": "Opposite idea: when the signal fires while price is already beyond the 2nd SD band, trade BACK to the mean instead. Only those signals are traded.",
    "nospike": "Skip the signal when its candle is a spike (range bigger than 3 ATR). Often a late chase.",
    "e30side": "Filter on the bot's signals: take it only if EMA30 is already on the trade's side of EMA50. (It is a filter, not a new EMA30 entry.)",
    "smaside": "Filter on the bot's signals: take it only if price is on the trade's side of the SMA200 mean, the line your SD bands are built on.",
    "kell_base": "Oliver Kell idea: take the signal only when price breaks out of a tight sideways base (last 8 candles within 2.5 ATR).",
    "kell_exit": "Oliver Kell exit: stay in until a candle closes beyond BOTH EMA10 and EMA20 against the trade (same stop-loss, no TP4 exit).",
    "kell_mix": "Kell base break for entry + Kell EMA10/20 exit. Few trades remain.",
    "o_adx": "Kim: take the signal only if ADX is 20 or more (trend is strong).",
    "o_adx22": "Kim: same as ADX 20, but stricter (ADX 22 or more).",
    "o_htf": "Kim: take the signal only if the higher-timeframe trend agrees.",
    "o_slope": "Kim: take the signal only if the EMA50 line is sloping the same way as the trade.",
    "o_vol": "Kim: take the signal only if volume is at least 1.1x of the last 20 candles.",
    "o_gap": "Kim: skip if price is already far from EMA50 (more than 0.75 ATR).",
    "o_1r": "Kim: skip if TP1 is closer than the stop-loss (reward smaller than risk).",
    "o_bundle": "Kim: all his filters together (ADX, higher TF, slope, chop, volume, gap, 1R). Very few trades remain.",
    "o_atr": "Kim: stop-loss set by ATR (0.8 to 1.8 ATR), skip if TP1 is less than 1R.",
    "o_part": "Kim: book profit in parts: 40% at TP1, 30% at TP2, 20% at TP3, 10% at TP4.",
    "o_conf": "Kim: wait 1 candle and enter only if it also closes beyond the signal candle.",
    "o_pull": "Kim: after the signal wait up to 5 candles for a pullback to EMA50, then enter.",
    "o_pkg": "Kim: full package = all filters + ATR stop + partial exits. Very few trades.",
}

# Short names for the table (the long name + plain line open when the row is tapped).
SHORT = {
    "sl_prev1": "SL prev candle", "sl_prev3": "SL last 3 candles", "sl_swing": "SL last 10 candles", "sl_atr": "SL 1.5 ATR",
    "be_fee": "SL to entry after TP1", "tp2": "Exit at TP2", "run": "Hold till opposite", "run_prev1": "Hold + wider SL",
    "tsi": "TSI agrees", "zmove": "Z moving with trade", "zrule": "SD 0 rule", "both": "TSI + Z agree", "chop": "Low chop",
    "bb_sq": "Skip BB squeeze", "bb_side": "Above/below BB mid", "bb_late": "Skip late (outside BB)", "bb_exp": "BB expanding",
    "cvd3": "CVD agrees", "cvd_push": "Real flow push", "cvd_exp": "CVD + BB expanding", "wait": "Wait 1 candle",
    "wait_cvd": "Wait 1 + CVD", "run_cvd": "Hold + CVD", "ema": "EMA200 bands",
    "mix1": "Wider SL + no squeeze", "mix2": "TSI+Z + wider SL", "mix3": "Hold + TSI", "mix4": "Hold + SL + no squeeze",
    "sd100": "SD100 bands", "meanrev": "Mean reversion", "nospike": "Skip spike", "e30side": "EMA30 side", "smaside": "SMA200 side",
    "kell_base": "Kell base break", "kell_exit": "Kell EMA exit", "kell_mix": "Kell mix",
    "o_adx": "ADX 20+", "o_adx22": "ADX 22+", "o_htf": "Higher TF agrees", "o_slope": "EMA50 slope agrees", "o_vol": "Volume 1.1x",
    "o_gap": "Not stretched (0.75 ATR)", "o_1r": "TP1 at least 1R", "o_bundle": "All Kim filters", "o_atr": "ATR stop (Kim)",
    "o_part": "Partial exits 40/30/20/10", "o_conf": "Wait + close beyond", "o_pull": "Wait for pullback", "o_pkg": "Kim full package",
}
VSHORT = {"helps": "HELPS", "hurts": "HURTS", "mixed": "MIXED", "replay_up": "REPLAY +", "replay_down": "REPLAY -",
          "saved_up": "SAVED +", "saved_down": "SAVED -", "unclear": "NOT CLEAR"}
GOOD = ("helps", "replay_up", "saved_up")
BAD = ("hurts", "replay_down", "saved_down")

# saved-trade version of an idea: (trade dict, "BUY"/"SELL") -> True = trade is kept, False = trade would be skipped, None = data missing.
MIN_OLD, MIN_NEW = 15, 5
Z_OLD, Z_NEW = 2.0, 1.64


def _num(v):
    try:
        if v is None or v == "" or str(v).lower() in ("none", "nan"):
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _s_adx(t, act):
    v = _num(t.get("adx"))
    return None if v is None else v >= 20.0


def _s_htf(t, act):
    h = str(t.get("htf_trend") or "")
    if h not in ("up", "down", "flat"):
        return None
    return h == ("up" if act == "BUY" else "down")


def _s_slope(t, act):
    v = _num(t.get("ema_slope_pct"))
    if v is None:
        return None
    return v > 0 if act == "BUY" else v < 0


def _s_vol(t, act):
    v = _num(t.get("volume_ratio"))
    return None if v is None else v >= 1.1


def _s_gap(t, act):
    v = _num(t.get("ema_gap_atr"))
    return None if v is None else abs(v) <= 0.75


def _s_chop(t, act):
    v = _num(t.get("regime_cross_n"))
    return None if v is None else v <= 2


_ZONES = ["<-3sd", "-3sd..-2sd", "-2sd..-1sd", "-1sd..mean", "mean..+1sd", "+1sd..+2sd", "+2sd..+3sd", ">+3sd"]


def _s_zrule(t, act):
    z = str(t.get("entry_zone") or "")
    if z not in _ZONES:
        return None
    zi = _ZONES.index(z)
    blocked = (act == "BUY" and zi < 4) or (act == "SELL" and zi >= 4)
    return not blocked


def _s_bundle(t, act):
    vals = [f(t, act) for f in (_s_adx, _s_htf, _s_slope, _s_vol, _s_gap, _s_chop)]
    if any(v is None for v in vals):
        return None
    return all(vals)


SAVED_FN = {
    "zrule": _s_zrule,
    "chop": _s_chop,
    "o_adx": _s_adx,
    "o_htf": _s_htf,
    "o_slope": _s_slope,
    "o_vol": _s_vol,
    "o_gap": _s_gap,
    "o_bundle": _s_bundle,
}


def _z(a, b, sign):
    """Welch distance. sign=+1: group a is WORSE than b by this many standard errors; sign=-1: group a is BETTER."""
    try:
        if len(a) < 2 or len(b) < 2:
            return 0.0
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
        vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
        se = (va / len(a) + vb / len(b)) ** 0.5
        if se <= 0:
            return 0.0
        return sign * (mb - ma) / se
    except Exception:
        return 0.0


IST_OFFSET = 19800          # 5h30m: days are counted in Indian time (same as the app)


def _day(ts):
    try:
        ts = float(ts)
        return time.strftime("%d %b", time.gmtime(ts + IST_OFFSET)) if ts > 0 else None
    except Exception:
        return None


def day_table(pairs, days=7):
    """pairs: [(row, kept_bool)] -> newest day first: [{day, bot_n, bot_net, idea_n, idea_net}] (last `days` days with trades)."""
    d = {}
    for r, kept in pairs:
        k = _day(r.get("ts"))
        if not k:
            continue
        e = d.setdefault(k, {"day": k, "ts": float(r["ts"]), "bot_n": 0, "bot_net": 0.0, "idea_n": 0, "idea_net": 0.0})
        e["bot_n"] += 1
        e["bot_net"] += r["roi"]
        if kept:
            e["idea_n"] += 1
            e["idea_net"] += r["roi"]
    out = sorted(d.values(), key=lambda x: -x["ts"])[:days]
    for e in out:
        e.pop("ts", None)
        e["bot_net"], e["idea_net"] = round(e["bot_net"], 1), round(e["idea_net"], 1)
    return out


def saved_eval(rows):
    """rows: Doctor's clean trades (oldest first): {"t": trade, "act": BUY/SELL, "roi": float}.
    -> {key: {state, n_known, n_skip, vs_bot, verdict}}.  verdict: up (rule would have helped) / down / unclear."""
    out = {}
    for key, fn in SAVED_FN.items():
        known = []
        for r in rows:
            k = fn(r["t"], r["act"])
            if k is not None:
                known.append((r, k))
        if len(known) < 30:
            out[key] = {"state": "no_data", "n_known": len(known), "n_skip": 0, "vs_bot": 0.0, "verdict": "unclear"}
            continue
        split = int(len(known) * 0.7)
        old, new = known[:split], known[split:]

        def part(seg):
            skip = [r["roi"] for r, k in seg if not k]
            keep = [r["roi"] for r, k in seg if k]
            return skip, keep

        so, ko = part(old)
        sn, kn = part(new)
        skipped = so + sn
        vs = -sum(skipped)                     # skipping those trades changes the total by this much
        verdict = "unclear"
        if len(so) >= MIN_OLD and len(sn) >= MIN_NEW and ko and kn:
            if _z(so, ko, +1) >= Z_OLD and _z(sn, kn, +1) >= Z_NEW:
                verdict = "up"                  # skipped trades were clearly worse in both halves
            elif _z(so, ko, -1) >= Z_OLD and _z(sn, kn, -1) >= Z_NEW:
                verdict = "down"                # skipped trades were clearly better in both halves
        out[key] = {"state": "ok", "n_known": len(known), "n_skip": len(skipped), "vs_bot": round(vs, 1), "verdict": verdict,
                    "net": round(sum(r["roi"] for r, k in known if k), 1), "n_keep": sum(1 for r, k in known if k),
                    "by_day": day_table([(r, k) for r, k in known])}
    return out


def _replay_sign(per_tf):
    ups = sum(1 for v in per_tf.values() if v.get("verdict") == "better")
    downs = sum(1 for v in per_tf.values() if v.get("verdict") == "worse")
    if ups and downs:
        return 0, True
    return (1 if ups else -1 if downs else 0), False


def _combine(r_sign, r_mixed, saved):
    s_sign = {"up": 1, "down": -1}.get(saved.get("verdict"), 0) if saved.get("state") == "ok" else 0
    if r_mixed:
        return "mixed"
    if r_sign > 0 and s_sign > 0:
        return "helps"
    if r_sign < 0 and s_sign < 0:
        return "hurts"
    if r_sign * s_sign < 0:
        return "mixed"
    if r_sign > 0:
        return "replay_up"
    if r_sign < 0:
        return "replay_down"
    if s_sign > 0:
        return "saved_up"
    if s_sign < 0:
        return "saved_down"
    return "unclear"


def build_from(replay, rows):
    """replay: variant_lab.status() dict. rows: Doctor clean trades. Pure function (tests call it with fake data)."""
    tfs = (replay or {}).get("tfs") or {}
    done = [tf for tf in TFS if isinstance(tfs.get(tf), dict) and tfs[tf].get("ok")]
    saved = saved_eval(rows) if rows else {}
    out = {"ok": True, "t": time.time(), "replay_running": bool((replay or {}).get("running")),
           "replay_progress": (replay or {}).get("progress", ""), "replay_tfs": done, "saved_n": len(rows),
           "bot": {}, "groups": [], "headline": [], "by_tf": []}
    saved_net = round(sum(r["roi"] for r in rows), 1) if rows else 0.0
    out["bot_saved"] = {"n": len(rows), "net": saved_net}
    for tf in done:
        b = tfs[tf].get("bot") or {}
        out["bot"][tf] = {"n": b.get("n", 0), "net": b.get("net", 0.0), "win": b.get("win", 0.0)}

    ideas = {}
    for tf in done:
        for r in tfs[tf].get("rows") or []:
            d = ideas.setdefault(r["key"], {"key": r["key"], "title": r["title"], "group": GROUP_TITLES.get(r["group"], r["group"]), "replay": {}})
            d["replay"][tf] = {"vs_bot": r.get("vs_bot", 0.0), "verdict": r.get("verdict", "unclear"),
                               "taken": r.get("taken", 0), "net": r.get("net", 0.0)}
    if not ideas and saved:                  # replay not run yet: still show the saved-trades half
        for key, title, group in (("zrule", "No long below mean / no short above (SD rule)", "SD bands / EMA bands"),
                                  ("chop", "Low chop (max 2 EMA50 crosses)", "TSI / Z-score / chop"),
                                  ("o_adx", "Trend strength: ADX 20 or more", "Kim's ideas"),
                                  ("o_htf", "Higher-timeframe trend agrees", "Kim's ideas"),
                                  ("o_slope", "EMA50 slope agrees with the trade", "Kim's ideas"),
                                  ("o_vol", "Volume at least 1.1x of last 20 candles", "Kim's ideas"),
                                  ("o_gap", "Price not stretched from EMA50 (0.75 ATR)", "Kim's ideas"),
                                  ("o_bundle", "All filters together", "Kim's ideas")):
            ideas[key] = {"key": key, "title": title, "group": group, "replay": {}}

    flat = []
    for key, d in ideas.items():
        s = saved.get(key) or {"state": "replay_only", "n_known": 0, "n_skip": 0, "vs_bot": 0.0, "verdict": "unclear"}
        sign, mixed = _replay_sign(d["replay"])
        v = _combine(sign, mixed, s)
        nets = [x.get("net", 0.0) for x in d["replay"].values() if x.get("taken")]
        profit_tfs = [tf for tf, x in d["replay"].items() if x.get("taken") and x.get("net", 0.0) > 0]
        saved_profit = s.get("state") == "ok" and s.get("n_keep", 0) >= 30 and s.get("net", 0.0) > 0
        if profit_tfs or saved_profit:
            answer = "PROFIT"
        elif nets or s.get("state") == "ok":
            answer = "LOSING"
        else:
            answer = "NO DATA"
        row = {"key": key, "title": d["title"], "group": d["group"], "replay": d["replay"], "saved": s, "answer": answer,
               "best_net": max(nets) if nets else None,
               "verdict": v, "label": LABELS[v], "vshort": VSHORT[v], "desc": DESC.get(key, ""),
               "short": SHORT.get(key) or d["title"][:24],
               "profit_tfs": [tf for tf, x in d["replay"].items() if x.get("taken") and x.get("net", 0.0) > 0],
               "still_losing": bool(nets) and all(n <= 0 for n in nets)}
        flat.append(row)
    for g in GROUP_ORDER:
        rs = [r for r in flat if r["group"] == g]
        if rs:
            out["groups"].append({"title": g, "rows": rs})

    out["total"] = len(flat)
    out["counts"] = [{"title": g["title"], "n": len(g["rows"]),
                      "better": sum(1 for r in g["rows"] if r["verdict"] in GOOD),
                      "worse": sum(1 for r in g["rows"] if r["verdict"] in BAD),
                      "mixed": sum(1 for r in g["rows"] if r["verdict"] == "mixed")} for g in out["groups"]]
    out["bot_by_day"] = day_table([(r, False) for r in rows])
    profit_ideas = sorted((r for r in flat if r["answer"] == "PROFIT"),
                          key=lambda r: -(r["best_net"] if r["best_net"] is not None else -1e9))[:5]
    closest = sorted((r for r in flat if r["answer"] == "LOSING" and r["best_net"] is not None), key=lambda r: -r["best_net"])[:3]
    out["profit_ideas"], out["closest"] = profit_ideas, closest
    bot_best = max((out["bot"][tf]["net"] for tf in done), default=None)
    if profit_ideas:
        out["answer_box"] = {"kind": "profit", "text": f"{len(profit_ideas)} idea(s) made a real profit after fees: "
                             + "; ".join(r["short"] for r in profit_ideas[:3]) + ". Try on paper first."}
    elif flat:
        c = closest[0] if closest else None
        extra = f" Closest: {c['short']} still loses {c['best_net']:.0f}" + (f" (bot {bot_best:.0f})." if bot_best is not None else ".") if c else ""
        out["answer_box"] = {"kind": "none", "text": "No idea makes a profit yet. Change nothing." + extra}
    else:
        out["answer_box"] = {"kind": "wait", "text": "Tap Run tests to start. Nothing to show yet."}
    out["bot_row"] = {"replay": {tf: out["bot"][tf]["net"] for tf in done}, "saved": saved_net if rows else None, "saved_n": len(rows)}
    rank = {"helps": 0, "replay_up": 1, "saved_up": 2, "mixed": 3, "unclear": 4, "saved_down": 5, "replay_down": 5, "hurts": 6}
    out["top"] = sorted((r for r in flat if r["verdict"] in ("helps", "replay_up", "saved_up", "mixed")),
                        key=lambda r: (rank[r["verdict"]], -sum(x["vs_bot"] for x in r["replay"].values())))[:5]
    n_profit = sum(1 for r in flat if r["profit_tfs"])
    n_help = sum(1 for r in flat if r["verdict"] == "helps")
    n_hurt = sum(1 for r in flat if r["verdict"] == "hurts")
    n_mix = sum(1 for r in flat if r["verdict"] == "mixed")
    n_one = sum(1 for r in flat if r["verdict"] in ("replay_up", "replay_down", "saved_up", "saved_down"))
    n_unc = len(flat) - n_help - n_hurt - n_mix - n_one
    h = out["headline"]
    if done:
        b = out["bot"]
        h.append("Normal bot (replay): " + ", ".join(f"{tf} {b[tf]['net']:+.0f}" for tf in done) + " ROI pts after fees.")
    if rows:
        h.append(f"Normal bot (your {len(rows)} saved trades): {saved_net:+.0f} ROI pts after fees.")
    if not done:
        h.append("Replay is not run yet. Tap Run tests to get the replay half. Saved-trade half is shown below.")
    if flat:
        h.append(f"{len(flat)} ideas checked: {n_help} help, {n_hurt} hurt, {n_mix} mixed, {n_one} show one source only, {n_unc} not clear.")
        if n_help:
            top = sorted((r for r in flat if r["verdict"] == "helps"), key=lambda r: -sum(x["vs_bot"] for x in r["replay"].values()))[:2]
            h.append("Safe to try on paper: " + "; ".join(r["title"] for r in top) + ".")
        else:
            h.append("Change nothing yet: no idea beat the bot in BOTH the replay and your saved trades.")
        bad = [r for r in flat if r["verdict"] == "hurts"]
        if bad:
            h.append("Do not use: " + "; ".join(r["title"] for r in bad[:3]) + ".")

    if done and flat:
        if n_profit:
            h.append(f"{n_profit} ideas make a real profit after fees on at least one timeframe (marked PROFIT on the line).")
        else:
            h.append("No idea makes a profit after fees on any timeframe yet. BETTER only means it loses less than the bot.")

    for tf in done:                          # which idea works / fails on which timeframe
        best = worst = None
        for r in flat:
            x = r["replay"].get(tf)
            if not x or not x.get("taken"):
                continue
            if best is None or x["vs_bot"] > best[1]:
                best = (r["title"], x["vs_bot"], x["verdict"])
            if worst is None or x["vs_bot"] < worst[1]:
                worst = (r["title"], x["vs_bot"], x["verdict"])
        if best:
            out["by_tf"].append({"tf": tf, "best": {"title": best[0], "vs_bot": best[1], "verdict": best[2]},
                                 "worst": {"title": worst[0], "vs_bot": worst[1], "verdict": worst[2]}})
    return out


def sd_block(sd):
    """scan_lab SD length test (200/150/100/50, plain and with the SD 0 rule) -> short lines + one compact line per timeframe."""
    if not isinstance(sd, dict) or not sd.get("tfs"):
        return None
    out = {"answer": [str(x) for x in (sd.get("answer") or [])][:4], "tfs": []}
    for t in sd["tfs"]:
        rows = {(r.get("label", "").replace(" (bot)", "")): r for r in (t.get("rows") or []) if isinstance(r, dict)}
        plain = [(n, rows.get(f"SD {n}")) for n in (200, 150, 100, 50)]
        rule = [(n, rows.get(f"SD {n} + rule")) for n in (200, 150, 100, 50)]
        fmt = lambda xs: [{"len": n, "avg": r.get("avg"), "n": r.get("n"), "verdict": r.get("verdict")} for n, r in xs if r]
        out["tfs"].append({"tf": t.get("tf"), "plain": fmt(plain), "rule": fmt(rule)})
    return out


def build(limit=5000):
    """Reads the saved Strategy Lab result + the bot's closed trades. Never raises."""
    try:
        replay = VL.status() if VL else {"tfs": {}}
    except Exception:
        replay = {"tfs": {}}
    rows = []
    try:
        from recovered_bot import trade_store, strategy_doctor as SD
        rows = SD._clean_trades(trade_store.get_all_closed(int(limit or 5000), net=True))
    except Exception:
        rows = []
    try:
        res = build_from(replay, rows)
        try:
            import scan_lab
            res["sd_length"] = sd_block(scan_lab.status().get("sd"))
        except Exception:
            res["sd_length"] = None
        return res
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "headline": ["Scoreboard could not be built yet."], "groups": []}
