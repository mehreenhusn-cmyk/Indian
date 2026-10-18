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
}
GROUP_ORDER = ["Bollinger Bands", "SD bands / EMA bands", "TSI / Z-score / chop", "CVD (order flow)",
               "Exit and stop-loss", "Kim's ideas", "Mixes"]

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
        out[key] = {"state": "ok", "n_known": len(known), "n_skip": len(skipped), "vs_bot": round(vs, 1), "verdict": verdict}
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
                               "taken": r.get("taken", 0)}
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
        row = {"key": key, "title": d["title"], "group": d["group"], "replay": d["replay"], "saved": s,
               "verdict": v, "label": LABELS[v]}
        flat.append(row)
    for g in GROUP_ORDER:
        rs = [r for r in flat if r["group"] == g]
        if rs:
            out["groups"].append({"title": g, "rows": rs})

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
        return build_from(replay, rows)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "headline": ["Scoreboard could not be built yet."], "groups": []}
