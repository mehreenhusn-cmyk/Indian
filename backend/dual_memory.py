#!/usr/bin/env python3
"""
dual_memory.py - Dual Bot Part B: fake-signal labels, mistake memory and lessons. Plain code, no AI key, paper only.

Three small jobs (nothing here is a trading rule, it only describes and remembers):
  1. label_trade()   after a trade ends: REAL / FAKE / UNCLEAR, with a plain reason taken from the tags known at entry.
  2. lookalikes()    before a new trade: "this looks like N old trades, X% of them lost" (only trades older than this one).
  3. lessons()       the repeat check: did the old-mistake warning really predict the next loss? And the top fake reasons.
The model in dual_lab.py also sees the sideways tags (they are normal tags), so it learns the effect from data by itself.
"""
import tag_lab as TL

K_NEAR = 30            # how many look-alike trades are compared
MIN_SIM = 8            # a look-alike must share at least this many of the tags (of 14, time of day is ignored)
WARN_LOSS = 60         # % of look-alikes that lost = "old mistake" warning
MIN_TAG_N = 20         # a single tag needs this many old trades before it is named as the worst one


def _dims():
    return [k for k, d in enumerate(TL.DIMS) if d != "hour"]


def label_trade(tg, net, end, hit):
    """-> (label, reason). hit = how many TP levels were reached. FAKE = stopped out before TP1. REAL = TP1 reached or a clean win."""
    net = net or 0.0
    if hit >= 1 or (net > 0 and end in ("TP", "TRAIL", "REV", "HOLD", "TIMEOUT")):
        if (tg.get("side_main_pct") or 0) < 34 and (tg.get("side_z_pct") or 0) < 34:
            return "real", "Clean move: both panes were trending."
        return "real", "It worked, even though a pane looked sideways."
    if end == "SL" and net < 0:
        if max(tg.get("side_main_pct") or 0, tg.get("side_z_pct") or 0) >= 67:
            return "fake", "Sideways market: a pane was choppy when it entered."
        if "OPPOSITE" in (tg.get("order") or ""):
            return "fake", "The other indicator had just given the opposite signal."
        if "against the trade" in (tg.get("tsi_zero") or ""):
            return "fake", "TSI was against the trade."
        if "against both" in (tg.get("z_ema") or ""):
            return "fake", "The Z candle was against both its EMAs."
        return "fake", "No warning sign. Price just reversed."
    return "unclear", "Closed small or by time, not clearly real or fake."


def lookalikes(rows, tg_list, t_before, tf=None):
    """rows: dual_lab memory values [sym, tf, t, d, tags, nets]. tg_list = tags of the new trade (same order as TL.DIMS).
    -> dict (n, loss_pct, avg, worst, text, warn) or None when the memory is too small. Only rows older than t_before count."""
    bot_i = list(TL.EXITS).index(TL.BOT)
    use = _dims()
    scored = []
    for r in rows:
        if r[2] >= t_before or len(r[4]) != len(TL.DIMS):
            continue
        sim = sum(1 for k in use if r[4][k] == tg_list[k])
        if sim >= MIN_SIM:
            scored.append((sim, r))
    if len(scored) < 10:
        return None
    scored.sort(key=lambda x: -x[0])
    near = [r for _, r in scored[:K_NEAR]]
    losses = sum(1 for r in near if r[5][bot_i] < 0)
    avg = sum(r[5][bot_i] for r in near) / len(near)
    loss_pct = int(round(100.0 * losses / len(near)))
    # the single tag of this trade that lost most often in the whole older memory
    stat, worst = {}, None
    for r in rows:
        if r[2] >= t_before or len(r[4]) != len(TL.DIMS):
            continue
        for k in use:
            if r[4][k] == tg_list[k]:
                s = stat.setdefault(k, [0, 0])
                s[0] += 1
                s[1] += 1 if r[5][bot_i] < 0 else 0
    best = [(100.0 * s[1] / s[0], k, s[0]) for k, s in stat.items() if s[0] >= MIN_TAG_N]
    if best:
        pc, k, n = max(best)
        worst = f"{TL.DIM_NAME[TL.DIMS[k]]}: {tg_list[k]} ({int(round(pc))}% lost of {n})"
    warn = loss_pct >= WARN_LOSS
    text = (f"Looks like {len(near)} old trades: {loss_pct}% lost, average {avg:+.1f}% of margin."
            + (" This is an old mistake." if warn else ""))
    return {"n": len(near), "loss_pct": loss_pct, "avg": round(avg, 2), "worst": worst, "text": text, "warn": warn}


def lessons(trades):
    """Repeat check + fake reasons over the closed trades. Counting only."""
    done = [t for t in trades if t.get("status") == "closed" and t.get("label")]
    fakes = [t for t in done if t["label"] == "fake"]
    reasons = {}
    for t in fakes:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    top = sorted(reasons.items(), key=lambda kv: -kv[1])[:3]
    flag = [t for t in done if (t.get("mem") or {}).get("warn")]
    free = [t for t in done if t.get("mem") and not t["mem"].get("warn")]
    lost = lambda v: sum(1 for t in v if (t.get("net") or 0) < 0)
    return {"closed": len(done), "fake": len(fakes), "real": sum(1 for t in done if t["label"] == "real"),
            "top_reasons": [{"reason": a, "n": b} for a, b in top],
            "repeat": {"warned": len(flag), "warned_lost": lost(flag), "not_warned": len(free), "not_warned_lost": lost(free)}}
