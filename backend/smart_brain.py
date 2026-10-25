#!/usr/bin/env python3
"""
smart_brain.py - SMART BRAIN (Dual Bot v2 side layer). Paper only, analysis + scoring only, no AI key.

It sits NEXT to Dual Bot v1. v1 keeps taking signals and writing dual_lab_data.json exactly as before.
Smart Brain only READS that file (never writes it) and writes its own small file: smart_brain_view.json.

What it answers, in plain words:
  - Do the Main chart and the Z pane agree or disagree on this setup?         (divergence score 0-100)
  - Is it a clean setup or a dirty one?                                       (clean score 0-100)
  - How did look-alike old trades end?                                        (probability, measured, never invented)
  - Which hours, which tag mixes keep losing / keep winning?                  (time of day, repeat losses, patterns)
  - Are there coins that look good right now even though no signal fired?     (watch list only, places no trades)
  - What would it have earned if it had picked the trades itself?             (its own paper book: picks are frozen at signal time;
                                                                               'shadow' until trust is earned, then 'paper')
  - Can the Brain be trusted?                                                 (trust meter: its scores are checked on trades
                                                                               it had not seen yet, against "take everything")

Honest limits: a probability is the share of look-alike old trades that won. With fewer than MIN_N look-alikes it says
"not enough data". The clean-score weights are a starting guess; the band table in the view shows what each band really earned.
Run by hand:  cd backend && python3 smart_brain.py once      (one pass, prints a short summary)
              cd backend && python3 smart_brain.py worker    (normally the backend starts it by itself)
"""
import json
import math
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CYCLE_S = 60                 # recompute the numbers every minute (cheap: reads one file)
SCAN_S = 300                 # opportunity scan every 5 minutes (downloads candles for a few coins)
SCAN_COINS = 12              # how many coins one scan reads
SCAN_TF = "15m"
BEAT_STALE_S = 180
MIN_N = 20                   # fewer look-alikes than this = "not enough data"
K_NEAR = 40                  # look-alikes compared
MIN_SIM = 9                  # a look-alike must share at least this many tags (of 14, time of day ignored)
MIN_GROUP = 15               # a tag mix / hour needs this many old trades before it is named
LOSS_WARN = 65               # % lost = repeat-loss mix
WIN_GOOD = 65                # % won = good pattern
TRUST_MIN = 100              # judged trades needed before the trust meter says anything
TRUST_LAST = 150             # the trust meter looks at the newest this-many closed trades
SHOW_TRADES = 40
ROLL_HALF = 400              # rolling memory: an old trade counts half as much for every this-many newer setups
LUCK_RUNS = 1000             # random re-draws in the luck test
RISK_MIN = 10                # finished picks needed before risk numbers are shown
SIDE_WORD_PCT = {"trending": 15, "mixed": 50, "sideways": 85}
KEY_DIMS = ("order", "tsi_zero", "tsi_line", "z_ema", "cloud", "zsm", "z_room", "side_main", "side_z", "diverge")


def _tl():
    import tag_lab as TL
    return TL


# ---------------------------------------------------------------- files (read dual_lab's file, write only our own)
def _dir():
    import dual_lab
    return dual_lab._dir()


def _p(name):
    return os.path.join(_dir(), name)


def _load(name, default):
    try:
        with open(_p(name), "r", encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, type(default)) else default
    except Exception:
        return default


def _save(name, obj):
    path = _p(name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


# ---------------------------------------------------------------- 1. reader
def read_v1():
    """Reads Dual Bot v1's memory. -> (rows, trades). rows: [sym, tf, t, d, tags, nets per exit, bars per exit]. Never writes."""
    TL = _tl()
    data = _load("dual_lab_data.json", {})
    rows = [r for r in (data.get("rows") or {}).values() if isinstance(r, list) and len(r) >= 7 and len(r[4]) == len(TL.DIMS)]
    trades = [t for t in (data.get("trades") or []) if isinstance(t, dict) and t.get("tg")]
    rows.sort(key=lambda r: r[2])
    return rows, trades


def _bot_i():
    TL = _tl()
    return list(TL.EXITS).index(TL.BOT)


def _tg_list(tg):
    TL = _tl()
    return [tg.get(k) for k in TL.DIMS]


# ---------------------------------------------------------------- 2. divergence (do Main and Z agree?)
def divergence(tg):
    """-> (score 0-100, label, reasons). Counts the signs that the two indicators (and TSI) do not point the same way."""
    pts, why = 0, []
    checks = (
        ("OPPOSITE" in (tg.get("order") or ""), "The other indicator just gave the opposite signal."),
        ("disagree" in (tg.get("diverge") or ""), "Price and Z moved in different directions."),
        ("against the trade" in (tg.get("tsi_zero") or ""), "TSI is against the trade."),
        ("wrong side" in (tg.get("tsi_line") or ""), "TSI is on the wrong side of its signal line."),
        ("against both" in (tg.get("z_ema") or ""), "The Z candle is against both its EMAs."),
        ("against the trade" in (tg.get("cloud") or ""), "The Z cloud colour is against the trade."),
        ("wrong side" in (tg.get("zsm") or ""), "Z is on the wrong side of ZSM."),
    )
    for bad, txt in checks:
        if bad:
            pts += 1
            why.append(txt)
    score = int(round(100.0 * pts / len(checks)))
    sm, sz = _side(tg, "main"), _side(tg, "z")
    if (sm >= 67) != (sz >= 67) and min(sm, sz) < 34:
        label = "One pane is sideways, the other is trending."
    elif score >= 43:
        label = "Main chart and Z pane disagree."
    elif score <= 14:
        label = "Main chart and Z pane agree."
    else:
        label = "Mostly agree, a few warning signs."
    return score, label, why


def _side(tg, which):
    """How sideways is a pane, 0 trending - 100 sideways. Uses the exact % when known, else the tag word."""
    v = tg.get("side_%s_pct" % which)
    if v is not None:
        return int(v)
    word = (tg.get("side_" + which) or "").lower()
    for k in ("sideways", "mixed", "trending"):
        if k in word:
            return SIDE_WORD_PCT[k]
    return 50


# ---------------------------------------------------------------- 3. clean score (0 dirty - 100 clean)
def clean_score(tg):
    """Starting weights (a guess, checked by the band table + trust meter). Starts at 100, every warning sign takes points off."""
    s = 100.0
    s -= 0.30 * _side(tg, "main") + 0.30 * _side(tg, "z")               # sideways panes: up to -51
    if "OPPOSITE" in (tg.get("order") or ""):
        s -= 20
    if "against the trade" in (tg.get("tsi_zero") or ""):
        s -= 15
    if "wrong side" in (tg.get("tsi_line") or ""):
        s -= 8
    z = tg.get("z_ema") or ""
    s -= 12 if "against both" in z else 5 if "between" in z else 0
    if "against the trade" in (tg.get("cloud") or ""):
        s -= 8
    if "wrong side" in (tg.get("zsm") or ""):
        s -= 6
    if "stretched" in (tg.get("z_room") or ""):
        s -= 10
    if "disagree" in (tg.get("diverge") or ""):
        s -= 6
    return int(max(0, min(100, round(s))))


def why_lines(tg):
    """Plain reasons, good first. Returns (good list, bad list)."""
    good, bad = [], []
    if _side(tg, "main") < 34 and _side(tg, "z") < 34:
        good.append("Both panes are trending, not sideways.")
    if "lots of room" in (tg.get("z_room") or ""):
        good.append("Lots of room left in the SD bands.")
    if "with the trade" in (tg.get("tsi_zero") or ""):
        good.append("TSI agrees with the trade.")
    if "beyond both" in (tg.get("z_ema") or ""):
        good.append("Z candle is beyond both its EMAs.")
    if "came first" in (tg.get("order") or ""):
        good.append("The other indicator gave the same signal just before.")
    if max(_side(tg, "main"), _side(tg, "z")) >= 67:
        bad.append("A pane is sideways (choppy market).")
    if "stretched" in (tg.get("z_room") or ""):
        bad.append("Z is already stretched, little room left.")
    bad.extend(divergence(tg)[2][:3])
    return good[:3], bad[:3]


# ---------------------------------------------------------------- 4. probability (look-alikes from the old trades)
def _use_dims():
    TL = _tl()
    return [k for k, d in enumerate(TL.DIMS) if d != "hour"]


def probability(rows, tg, t_before=None, use=None):
    """Share of look-alike old trades (BOT exit) that won. Only rows older than t_before count.
    -> dict {n, win_pct, avg, fast_pct, text} or None when there are fewer than MIN_N look-alikes."""
    use = use or _use_dims()
    bi = _bot_i()
    tl = _tg_list(tg)
    elig = [r for r in rows if t_before is None or r[2] < t_before]
    last = len(elig) - 1
    scored = []
    for pos, r in enumerate(elig):
        sim = 0
        for k in use:
            if r[4][k] == tl[k]:
                sim += 1
        if sim >= MIN_SIM:
            scored.append((sim, pos, r))
    if len(scored) < MIN_N:
        return None
    scored.sort(key=lambda x: (-x[0], -x[1]))
    near = scored[:K_NEAR]
    # rolling memory: newer look-alikes count more (half-life ROLL_HALF setups), so the number follows the market as it changes
    wts = [0.5 ** ((last - pos) / float(ROLL_HALF)) for _, pos, _r in near]
    nets = [r[5][bi] for _, _p, r in near]
    wsum = sum(wts)
    win_pct = int(round(100.0 * sum(w for w, x in zip(wts, nets) if x > 0) / wsum))
    avg = sum(w * x for w, x in zip(wts, nets)) / wsum
    wins = sum(1 for x in nets if x > 0)
    fast = sum(1 for _, _p, r in near if r[5][bi] > 0 and int(r[6][bi]) <= 6)
    return {"n": len(near), "win_pct": win_pct, "avg": round(avg, 2),
            "fast_pct": int(round(100.0 * fast / max(1, wins))) if wins else 0,
            "text": f"{len(near)} similar old trades: {win_pct}% won, average {avg:+.1f}% of margin."}


# ---------------------------------------------------------------- 5. time of day, repeat losses, patterns
def hours_table(rows):
    TL = _tl()
    bi, hi = _bot_i(), TL.DIMS.index("hour")
    st = {}
    for r in rows:
        s = st.setdefault(r[4][hi], [0, 0, 0.0])
        s[0] += 1
        s[1] += 1 if r[5][bi] > 0 else 0
        s[2] += r[5][bi]
    out = []
    for k in sorted(st):
        n, w, tot = st[k]
        if n >= MIN_GROUP:
            out.append({"hour": k, "n": n, "win_pct": int(round(100.0 * w / n)), "avg": round(tot / n, 2),
                        "bad": 100.0 * w / n < 40.0, "good": 100.0 * w / n >= 60.0})
    return out


def _combo_stats(rows, dims_idx):
    """All 2-tag mixes -> {(k1, v1, k2, v2): [n, wins, total_net, wins_old_half, n_old_half, wins_new_half, n_new_half]}"""
    TL = _tl()
    bi = _bot_i()
    half = len(rows) // 2
    st = {}
    for pos, r in enumerate(rows):
        won = 1 if r[5][bi] > 0 else 0
        old = pos < half
        for a in range(len(dims_idx)):
            for b in range(a + 1, len(dims_idx)):
                ka, kb = dims_idx[a], dims_idx[b]
                key = (ka, r[4][ka], kb, r[4][kb])
                s = st.setdefault(key, [0, 0, 0.0, 0, 0, 0, 0])
                s[0] += 1
                s[1] += won
                s[2] += r[5][bi]
                if old:
                    s[3] += won
                    s[4] += 1
                else:
                    s[5] += won
                    s[6] += 1
    return st


def patterns(rows):
    """-> (repeat_losses, good_patterns). A mix is only named when it is stable: the older and the newer half of the memory agree."""
    TL = _tl()
    if len(rows) < 4 * MIN_GROUP:
        return [], []
    idx = [TL.DIMS.index(k) for k in KEY_DIMS]
    st = _combo_stats(rows, idx)
    losses, goods = [], []
    for key, s in st.items():
        n, w, tot, wo, no, wn, nn = s
        if n < MIN_GROUP or no < 5 or nn < 5:
            continue
        win = 100.0 * w / n
        a, b = TL.DIM_NAME[TL.DIMS[key[0]]], TL.DIM_NAME[TL.DIMS[key[2]]]
        item = {"text": f"{a}: {key[1]}  +  {b}: {key[3]}", "n": n, "win_pct": int(round(win)), "avg": round(tot / n, 2)}
        if 100.0 - win >= LOSS_WARN and wo / no < 0.5 and wn / nn < 0.5:
            losses.append(item)
        elif win >= WIN_GOOD and wo / no >= 0.55 and wn / nn >= 0.55:
            goods.append(item)
    losses.sort(key=lambda x: (x["win_pct"], -x["n"]))
    goods.sort(key=lambda x: (-x["win_pct"], -x["n"]))
    return losses[:6], goods[:6]


def fast_slow(rows):
    """How long winners take (BOT exit): how many finish within 6 candles, and the median."""
    bi = _bot_i()
    bars = sorted(int(r[6][bi]) for r in rows if r[5][bi] > 0)
    if len(bars) < MIN_N:
        return None
    return {"n": len(bars), "median": bars[len(bars) // 2],
            "fast_pct": int(round(100.0 * sum(1 for b in bars if b <= 6) / len(bars)))}


def bands(rows):
    """Does the clean score mean anything? Win rate of old trades per score band (the honest check of the weights)."""
    TL = _tl()
    bi = _bot_i()
    edges = ((0, 40, "Dirty (0-39)"), (40, 70, "Medium (40-69)"), (70, 101, "Clean (70-100)"))
    out = []
    for lo, hi, name in edges:
        n = w = 0
        tot = 0.0
        for r in rows:
            tg = dict(zip(TL.DIMS, r[4]))
            if lo <= clean_score(tg) < hi:
                n += 1
                w += 1 if r[5][bi] > 0 else 0
                tot += r[5][bi]
        out.append({"band": name, "n": n, "win_pct": int(round(100.0 * w / n)) if n >= MIN_GROUP else None,
                    "avg": round(tot / n, 2) if n >= MIN_GROUP else None})
    return out


# ---------------------------------------------------------------- 6. trust meter
def _judge(rows, trades):
    """The Brain scores each finished trade using ONLY older memory. -> (nets of all judged trades, nets of the ones it would have picked)."""
    done = [t for t in trades if t.get("status") in ("closed", "skipped_done") and t.get("net") is not None]
    done.sort(key=lambda t: t["t"])
    done = done[-TRUST_LAST:]
    use = _use_dims()
    judged, picks = [], []
    for t in done:
        pr = probability(rows, t["tg"], t["t"], use)
        if pr is None:
            continue
        judged.append(t["net"])
        if pr["win_pct"] >= 50 and clean_score(t["tg"]) >= 50:
            picks.append(t["net"])
    return judged, picks


def trust(rows, trades):
    """Would the Brain have helped on trades it had not seen? For each finished trade the Brain scores it using ONLY older memory.
    'Brain picks' = trades with enough look-alikes, win chance >= 50% and clean score >= 50. Compared with taking everything.
    Verdict is only 'earned' if the picks beat 'take everything' by a clear margin on at least TRUST_MIN judged trades."""
    judged, picks = _judge(rows, trades)
    out = {"judged": len(judged), "picks": len(picks), "need": TRUST_MIN}
    if len(judged) < TRUST_MIN or len(picks) < 8:
        out.update(verdict="learning", text=f"Still learning: {len(judged)} of {TRUST_MIN} unseen trades judged. No trust yet.")
        return out
    all_avg = sum(judged) / len(judged)
    pick_avg = sum(picks) / len(picks)
    out.update(all_avg=round(all_avg, 2), picks_avg=round(pick_avg, 2),
               all_win=int(round(100.0 * sum(1 for x in judged if x > 0) / len(judged))),
               picks_win=int(round(100.0 * sum(1 for x in picks if x > 0) / len(picks))))
    if pick_avg > all_avg + 1.0 and pick_avg > 0:
        out.update(verdict="earned", text=f"Brain picks beat take-everything ({pick_avg:+.1f} vs {all_avg:+.1f} per trade) on {len(judged)} unseen trades.")
    else:
        out.update(verdict="not_yet", text=f"Brain picks do not beat take-everything yet ({pick_avg:+.1f} vs {all_avg:+.1f} per trade). No trust yet.")
    return out


# ---------------------------------------------------------------- 7. one setup, scored
def score_setup(rows, tg, t_before=None):
    ds, dl, dwhy = divergence(tg)
    good, bad = why_lines(tg)
    pr = probability(rows, tg, t_before)
    sc = {"clean": clean_score(tg), "div": ds, "div_label": dl, "good": good, "bad": bad,
          "prob": pr, "prob_text": pr["text"] if pr else "Not enough data yet (needs %d similar old trades)." % MIN_N}
    sc["verdict"], sc["verdict_text"] = verdict_of(sc)
    return sc


def verdict_of(sc):
    """One plain opinion per setup: 'like' / 'unsure' / 'dislike', with the reason in one sentence. Same rules as the paper-book pick."""
    pr = sc.get("prob")
    if is_pick(sc):
        return "like", "Likes it: clean setup, Main and Z agree, and %d%% of similar old trades won." % pr["win_pct"]
    if sc["clean"] < 40:
        return "dislike", "Dislikes it: dirty setup (clean score %d)." % sc["clean"]
    if sc["div"] >= PICK_DIV:
        return "dislike", "Dislikes it: Main chart and Z pane disagree."
    if pr and pr["win_pct"] < 45:
        return "dislike", "Dislikes it: only %d%% of similar old trades won." % pr["win_pct"]
    if pr is None:
        return "unsure", "Not sure: too few similar old trades to judge."
    return "unsure", "Not sure: it is not clean enough or similar trades won too rarely to pick it."


def signals_view(rows, trades):
    out = []
    ordered = sorted(trades, key=lambda t: t["t"], reverse=True)
    pick = [t for t in ordered if t.get("status") in ("open", "skipped")] + [t for t in ordered if t.get("status") not in ("open", "skipped")]
    for t in pick[:SHOW_TRADES]:
        sc = score_setup(rows, t["tg"], t["t"])
        sc.update({"id": t.get("id"), "s": t["s"], "f": t["f"], "d": t["d"], "src": t["src"], "t": t["t"], "status": t.get("status"),
                   "net": t.get("net"), "live": t.get("live")})
        out.append(sc)
    return out


# ---------------------------------------------------------------- 8. opportunity scan (watch list, no trades)
def scan(rows, coins, fetch_limit):
    """Reads the newest closed candle of a few coins and scores BUY and SELL as if a signal fired now. Only good-looking setups are listed.
    This never places a trade and never writes into Dual Bot."""
    TL = _tl()
    from recovered_bot import ai_ind_features as F
    import brain_own as BO
    from recovered_bot.strategy import ABCDStrategy
    strat = ABCDStrategy()
    found = []
    for sym in coins[:SCAN_COINS]:
        try:
            cs = fetch_limit(sym, SCAN_TF, 470)
            if not cs or len(cs) < F.MIN_BARS + 5:
                continue
            S = F.build(cs)
            Z = TL.z_series(S)
            i = S["n"] - 1
            if S["xup"][i] or S["xdn"][i] or Z["up"][i] or Z["dn"][i]:
                continue                                     # a real signal: Dual Bot v1 handles it
            for d in (1, -1):
                tg = TL.make_tags(S, Z, i, d, "MAIN", S["t"][i])
                if tg is None:
                    continue
                sc = score_setup(rows, tg)
                pr = sc["prob"]
                if pr and sc["clean"] >= 70 and pr["win_pct"] >= 55 and sc["div"] <= 29:
                    sc.update({"s": sym, "f": SCAN_TF, "d": d, "t": int(time.time() * 1000)})
                    sc["_plan"], sc["_tg"] = BO.plan_levels(S, i, d, strat), tg   # used by brain_own, removed before the view is saved
                    found.append(sc)
        except Exception:
            continue
        time.sleep(0.05)
    found.sort(key=lambda x: (-x["prob"]["win_pct"], -x["clean"]))
    return found[:8]


# ---------------------------------------------------------------- 8b. the Brain's own paper book (forward only, frozen at signal time)
PICK_CLEAN, PICK_WIN, PICK_DIV = 60, 55, 43
BOOK_MAX = 400


def is_pick(sc):
    """The Brain would take this setup: enough look-alikes, they won >= PICK_WIN %, clean score >= PICK_CLEAN, Main and Z do not disagree."""
    pr = sc.get("prob")
    return bool(pr and pr["win_pct"] >= PICK_WIN and sc["clean"] >= PICK_CLEAN and sc["div"] < PICK_DIV)


def update_book(book, rows, trades, verdict, now_ms=None):
    """Adds NEW Dual Bot signals the Brain would have picked. Each pick is scored with only OLDER memory and then never changed.
    mode = 'paper' when the trust meter had EARNED trust at that moment, else 'shadow' (a note only, 'what if I had followed the Brain').
    Only signals that appear after the book was started are judged, so there is no looking back with hindsight."""
    book.setdefault("since", int(now_ms if now_ms is not None else time.time() * 1000))
    book.setdefault("picks", {})
    book.setdefault("seen", {})
    for t in sorted(trades, key=lambda x: x["t"]):
        tid = t.get("id")
        if not tid or t["t"] < book["since"] or tid in book["seen"]:
            continue
        book["seen"][tid] = 1
        sc = score_setup(rows, t["tg"], t["t"])
        if is_pick(sc):
            book["picks"][tid] = {"id": tid, "s": t["s"], "f": t["f"], "d": t["d"], "src": t["src"], "t": t["t"], "clean": sc["clean"],
                                  "div": sc["div"], "win_pct": sc["prob"]["win_pct"], "n": sc["prob"]["n"],
                                  "mode": "paper" if verdict == "earned" else "shadow"}
    if len(book["picks"]) > BOOK_MAX:                       # keep the newest
        keep = sorted(book["picks"].values(), key=lambda x: x["t"])[-BOOK_MAX:]
        book["picks"] = {x["id"]: x for x in keep}
    if len(book["seen"]) > 4 * BOOK_MAX:
        book["seen"] = {k: 1 for k in list(book["seen"])[-2 * BOOK_MAX:]}
    return book


def book_summary(book, trades):
    """Results of the Brain's frozen picks (result = what Dual Bot's own trade for that signal earned, skipped signals are followed too)
    against ALL signals since the book started. USDT uses each trade's own margin."""
    import dual_lab
    byid = {t.get("id"): t for t in trades}
    since = book.get("since") or 0

    def usdt(t):
        return dual_lab._mg(t) * (t.get("net") or 0.0) / 100.0

    def agg(items):
        done = [t for t in items if t.get("status") in ("closed", "skipped_done") and t.get("net") is not None]
        return {"n": len(items), "closed": len(done), "wins": sum(1 for t in done if t["net"] > 0),
                "pnl": round(sum(usdt(t) for t in done), 2), "avg": round(sum(t["net"] for t in done) / len(done), 2) if done else 0.0}

    pk = [(p, byid[p["id"]]) for p in (book.get("picks") or {}).values() if p["id"] in byid]
    allsig = [t for t in trades if t["t"] >= since]
    out = {"since": since, "picks": agg([t for _, t in pk]), "all": agg(allsig),
           "paper": agg([t for p, t in pk if p["mode"] == "paper"]), "shadow": agg([t for p, t in pk if p["mode"] == "shadow"])}
    recent = []
    for p, t in sorted(pk, key=lambda x: -x[0]["t"])[:10]:
        recent.append(dict(p, status=t.get("status"), net=t.get("net"), live=t.get("live")))
    out["recent"] = recent
    return out


# ---------------------------------------------------------------- 8c. "what is the Brain thinking now" (one summary for the top of the Brain tab)
SCORE_GUIDE = [
    {"band": "70-100", "name": "Clean", "color": "green", "meaning": "Both panes are trending and the signs point the same way."},
    {"band": "40-69", "name": "Medium", "color": "yellow", "meaning": "Some warning signs. Not bad, not great."},
    {"band": "0-39", "name": "Dirty", "color": "red", "meaning": "Sideways market or the indicators disagree. Old trades like this lost more."},
]


def _slim(sc):
    return {"s": sc.get("s"), "f": sc.get("f"), "d": sc.get("d"), "clean": sc.get("clean"), "div": sc.get("div"),
            "verdict": sc.get("verdict"), "text": sc.get("verdict_text"), "prob_text": sc.get("prob_text")}


def thin_spots(rows, limit=4):
    """Tag values the Dual Bot has seen too rarely (fewer than MIN_GROUP old trades) - the places where the Brain cannot judge yet."""
    TL = _tl()
    out = []
    for k in KEY_DIMS:
        if k not in TL.DIMS:
            continue
        ix = TL.DIMS.index(k)
        cnt = {}
        for r in rows:
            cnt[r[4][ix]] = cnt.get(r[4][ix], 0) + 1
        for val, c in cnt.items():
            if 0 < c < MIN_GROUP:
                out.append((c, "%s: %s (%d of %d old trades)" % (TL.DIM_NAME.get(k, k), val, c, MIN_GROUP)))
    out.sort(key=lambda x: x[0])
    return [t for _, t in out[:limit]]


def thinking(rows, signals, tv, scan_coins=None, scan_t=0, watch=None):
    """-> dict for the top card: headline, best and worst live setup, and 'what is it learning'. Pure reading of numbers already computed."""
    need_rows = 4 * MIN_GROUP
    cur = [s for s in signals if s.get("status") in ("open", "skipped")]
    likes = [s for s in cur if s.get("verdict") == "like"]
    dislikes = [s for s in cur if s.get("verdict") == "dislike"]
    if len(rows) < need_rows:
        mood, head = "collecting", "Still collecting: %d of about %d old setups read. No opinions yet." % (len(rows), need_rows)
    elif not cur:
        mood, head = "idle", "No live Dual Bot setup right now. The Brain is watching %d coins." % len(scan_coins or [])
    else:
        mood = "like" if likes else ("dislike" if len(dislikes) == len(cur) else "unsure")
        head = "%d of %d live setups look good, %d look bad." % (len(likes), len(cur), len(dislikes))
    best = worst = None
    if len(rows) >= need_rows and cur:
        ranked = sorted(cur, key=lambda s: ((s["prob"]["win_pct"] if s.get("prob") else -1), s["clean"]), reverse=True)
        best = _slim(ranked[0])
        if len(ranked) > 1 and ranked[-1] is not ranked[0]:
            worst = _slim(min(cur, key=lambda s: (s["clean"], -s["div"])))
    judged, need_j = int((tv or {}).get("judged") or 0), int((tv or {}).get("need") or TRUST_MIN)
    if len(rows) < need_rows:
        nxt = "Next: %d more old setups for the first patterns." % (need_rows - len(rows))
    elif (tv or {}).get("verdict") != "earned" and judged < need_j:
        nxt = "Next: %d more unseen trades before the trust meter can say anything." % (need_j - judged)
    elif (tv or {}).get("verdict") != "earned":
        nxt = "Next: the Brain must beat take-everything on unseen trades to earn trust."
    else:
        nxt = "Trust is earned. New picks are paper picks. Still paper money only."
    coins = [str(c).replace("USDT", "") for c in (scan_coins or [])]
    return {"mood": mood, "headline": head, "best": best, "worst": worst, "live": len(cur), "likes": len(likes), "dislikes": len(dislikes),
            "learning": {"rows": len(rows), "need_rows": need_rows, "judged": judged, "need_judged": need_j,
                         "thin": thin_spots(rows) if rows else [], "scan_n": len(coins), "scan_list": coins[:8], "scan_t": scan_t,
                         "watch_n": len(watch or []), "next": nxt},
            "guide": SCORE_GUIDE}


# ---------------------------------------------------------------- 8d. luck test, risk numbers, worst case (ideas from Jesse, own numpy-free code)
def luck_test(rows, trades, runs=LUCK_RUNS):
    """Is the Brain's edge real or luck? Same trades the trust meter judged. Draw the same number of trades AT RANDOM many times and count
    how often a random draw earns at least as much per trade as the Brain's picks. Small share = hard to explain by luck."""
    judged, picks = _judge(rows, trades)
    if len(judged) < TRUST_MIN or len(picks) < 8:
        return {"verdict": "learning", "p": None, "text": "Not enough unseen trades yet to test luck (%d of %d judged)." % (len(judged), TRUST_MIN)}
    pick_avg = sum(picks) / len(picks)
    rnd = random.Random(5)
    better = sum(1 for _ in range(runs) if sum(rnd.sample(judged, len(picks))) / len(picks) >= pick_avg)
    p = (better + 1.0) / (runs + 1.0)
    pct = int(round(100 * p))
    verdict = "solid" if p <= 0.05 else ("maybe" if p <= 0.20 else "luck")
    word = {"solid": "Hard to explain by luck.", "maybe": "Maybe real, not proven.", "luck": "Could easily be luck."}[verdict]
    return {"verdict": verdict, "p": round(p, 3), "n_picks": len(picks), "n_judged": len(judged), "pick_avg": round(pick_avg, 2),
            "text": "If trades were picked at random, %d out of 100 random sets would earn as much as the Brain's picks. %s" % (pct, word)}


def _max_dd(pnls):
    peak = cum = dd = 0.0
    for x in pnls:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def risk_stats(pnls):
    """pnls = USDT result per finished trade, oldest first. Ratios are PER TRADE (not per year). None when there are too few trades."""
    n = len(pnls)
    if n < RISK_MIN:
        return None
    mean = sum(pnls) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in pnls) / n)
    dsd = math.sqrt(sum(min(0.0, x) ** 2 for x in pnls) / n)
    k = max(1, int(n * 0.05))
    cvar = sum(sorted(pnls)[:k]) / k
    return {"n": n, "total": round(sum(pnls), 2), "mean": round(mean, 2), "max_dd": round(_max_dd(pnls), 2),
            "sharpe": round(mean / sd, 2) if sd > 0 else None, "sortino": round(mean / dsd, 2) if dsd > 0 else None,
            "cvar5": round(cvar, 2)}


def worst_case(pnls, runs=LUCK_RUNS):
    """Same trades, order shuffled many times: how deep can the biggest drop get when the bad trades come together?"""
    if len(pnls) < RISK_MIN:
        return None
    rnd = random.Random(11)
    dds = []
    for _ in range(runs):
        x = list(pnls)
        rnd.shuffle(x)
        dds.append(_max_dd(x))
    dds.sort()
    p95 = dds[int(0.95 * runs) - 1]
    return {"runs": runs, "actual": round(_max_dd(pnls), 2), "median": round(dds[runs // 2], 2), "p95": round(p95, 2),
            "text": "In 95 of 100 shuffles of the same trades the biggest drop stayed under %.2f USDT (the real one was %.2f)." % (p95, _max_dd(pnls))}


def risk_view(book, trades):
    """Risk numbers for the Brain's frozen picks and for 'all signals', both since the book started. Reads only."""
    import dual_lab
    since = (book or {}).get("since") or 0
    ids = set(((book or {}).get("picks") or {}).keys())

    def series(items):
        done = [t for t in items if t.get("status") in ("closed", "skipped_done") and t.get("net") is not None]
        done.sort(key=lambda t: t.get("end") or t["t"])
        return [dual_lab._mg(t) * t["net"] / 100.0 for t in done]

    pk = series([t for t in trades if t.get("id") in ids])
    al = series([t for t in trades if t["t"] >= since])
    if len(pk) < RISK_MIN:
        return {"picks": None, "all": risk_stats(al), "worst": None, "n_picks": len(pk),
                "text": "Risk numbers need %d finished Brain picks (now %d)." % (RISK_MIN, len(pk))}
    return {"picks": risk_stats(pk), "all": risk_stats(al), "worst": worst_case(pk), "n_picks": len(pk), "text": ""}


def recent_vs_old(rows, recent=100):
    """Rolling memory check: how did the newest setups end compared with the older ones (BOT exit)?"""
    if len(rows) < 2 * MIN_GROUP + recent // 2:
        return None
    bi = _bot_i()
    new, old = rows[-recent:], rows[:-recent]
    pct = lambda xs: int(round(100.0 * sum(1 for r in xs if r[5][bi] > 0) / len(xs)))
    return {"recent_n": len(new), "recent_win": pct(new), "old_n": len(old), "old_win": pct(old), "half_life": ROLL_HALF}


# ---------------------------------------------------------------- 8b. exit learner (shadow only, see brain_exit.py)
def _exit_view(state, trades):
    try:
        import brain_exit as BX
        return BX.view(state, trades)
    except Exception as e:
        return {"status": "error", "text": "Exit learner error: %s" % str(e)[:80], "n_past": 0, "open": [], "stages": [], "score": {"n": 0, "right": 0, "pct": None, "text": ""}}


def _follow_view(rows, trades):
    try:
        import brain_follow as BF
        return BF.build(rows, trades, score_setup)
    except Exception as e:
        return {"status": "error", "text": "Follow report error: %s" % str(e)[:80], "judged": 0, "need": 30, "stories": [], "dislike_avg": None}


# ---------------------------------------------------------------- 9. the view for the app
def _exitpick_view(rows):
    try:
        import brain_exit_pick as XP
        return XP.exit_table(rows)
    except Exception:
        return None


def _own_view(own):
    try:
        import brain_own as BO
        return BO.summary(own)
    except Exception:
        return None


def build_view(rows=None, trades=None, watch=None, scan_t=0, progress="", err="", book=None, tv=None, scan_coins=None, exit_state=None, own=None):
    if rows is None:
        rows, trades = read_v1()
    trades = trades or []
    rl, gp = patterns(rows)
    sigs = signals_view(rows, trades) if rows else []
    tv = tv or trust(rows, trades)
    return {"beat": time.time(), "enabled": True, "rows": len(rows), "min_n": MIN_N,
            "status": "ready" if len(rows) >= 4 * MIN_GROUP else "collecting",
            "status_text": ("Ready." if len(rows) >= 4 * MIN_GROUP else
                            f"Collecting: {len(rows)} old setups read. Needs about {4 * MIN_GROUP} for the first patterns."),
            "signals": sigs,
            "now": thinking(rows, sigs, tv, scan_coins, scan_t, watch),
            "luck": luck_test(rows, trades) if rows else None, "risk": risk_view(book, trades) if book and book.get("picks") is not None else None,
            "drift": recent_vs_old(rows),
            "exit": _exit_view(exit_state, trades),
            "follow": _follow_view(rows, trades),
            "own": _own_view(own),
            "exit_pick": _exitpick_view(rows),
            "by_key": {"%s|%s|%s" % (x["s"], x["f"], x["t"]): {"clean": x["clean"], "div": x["div"], "verdict": x["verdict"], "text": x["verdict_text"]} for x in sigs},
            "hours": hours_table(rows), "repeat_loss": rl, "patterns": gp, "speed": fast_slow(rows),
            "bands": bands(rows) if len(rows) >= 3 * MIN_GROUP else [], "trust": tv,
            "watch": watch or [], "scan_t": scan_t, "progress": progress, "error": err,
            "book": book_summary(book, trades) if book and book.get("picks") is not None else None}


# ---------------------------------------------------------------- 10. worker (own low-priority process)
def _lock():
    try:
        import fcntl
    except Exception:
        return -1
    for path in (os.path.join(os.path.expanduser("~"), ".owl_smart_brain.lock"), _p("smart_brain.lock")):
        try:
            fd = os.open(path, os.O_CREAT | os.O_RDWR)
        except Exception:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            os.close(fd)
            return None
        except Exception:
            os.close(fd)
            continue
    return -1


def worker():
    lock = _lock()
    if lock is None:
        print("smart_brain: already running", flush=True)
        return 0
    try:
        os.nice(10)
    except Exception:
        pass
    try:
        from recovered_bot.dns_fallback import ensure_dns_fallback
        ensure_dns_fallback()
    except Exception:
        pass
    from recovered_bot import ai_shadow_lab as LAB
    watch, scan_t, scan_list = [], 0.0, []
    first = True                       # first round: skip the slow coin scan so the numbers appear within seconds
    print("smart_brain worker started", flush=True)
    while True:
        err = ""
        try:
            enabled = bool(_load("smart_brain_ctl.json", {"enabled": True}).get("enabled", True))
            scanned = False
            if enabled:
                rows, trades = read_v1()
                if not first and time.time() - scan_t > SCAN_S and len(rows) >= 4 * MIN_GROUP:
                    coins = [k.split("|")[0] for k in (_load("dual_lab_data.json", {}).get("fetched") or {}) if k.endswith("|" + SCAN_TF)]
                    scan_list = list(dict.fromkeys(coins))[:SCAN_COINS]
                    watch, scan_t = scan(rows, scan_list, LAB._fetch_limit), time.time()
                    scanned = True
                own = _load("smart_brain_own.json", {})
                try:                                           # the Brain's own pretend trades: any problem here is ignored
                    import brain_own as BO
                    if scanned:
                        import brain_exit_pick as XP
                        BO.open_from(own, watch, pick_fn=lambda tg: XP.pick(rows, tg))   # also strips the plan out of the watch list
                    BO.settle(own, LAB._fetch_limit)
                    if own.get("since") is not None:
                        _save("smart_brain_own.json", own)
                except Exception as e:
                    print("smart_brain: own trades skipped: %s: %s" % (type(e).__name__, str(e)[:100]), flush=True)
                for w in watch:                                # never leave plan data in the saved view
                    w.pop("_plan", None), w.pop("_tg", None)
                book = _load("smart_brain_book.json", {})
                tv = trust(rows, trades)
                if len(rows) >= 4 * MIN_GROUP:
                    update_book(book, rows, trades, tv.get("verdict"))
                    _save("smart_brain_book.json", book)
                try:
                    import brain_exit as BX
                    ex = BX.update(_load("smart_brain_exit.json", {}), trades)
                    _save("smart_brain_exit.json", ex)
                except Exception:
                    ex = None
                view = build_view(rows, trades, watch, scan_t, book=book, tv=tv, scan_coins=scan_list, exit_state=ex, own=own)
            else:
                view = dict(build_view([], []), enabled=False, status="stopped", status_text="Stopped.")
            _save("smart_brain_view.json", view)
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:120]}"
            try:
                v = _load("smart_brain_view.json", {})
                v.update(beat=time.time(), error=err)
                _save("smart_brain_view.json", v)
            except Exception:
                pass
        time.sleep(8 if first else CYCLE_S)   # 8 s after the first quick round, then the normal minute
        first = False


# ---------------------------------------------------------------- 11. backend side (starts the worker, reads the view)
_SPAWN = {"t": 0.0, "err": ""}


def set_enabled(on):
    ctl = _load("smart_brain_ctl.json", {"enabled": True})
    ctl["enabled"] = bool(on)
    _save("smart_brain_ctl.json", ctl)


GATE_WINDOW_S = 1800         # a main-bot signal is matched to a Dual Bot setup of the same coin and side seen in the last 30 minutes


def gate_on():
    return bool(_load("smart_brain_ctl.json", {}).get("gate", False))


def set_gate(on):
    """The skip switch. Default OFF. Only changes the one flag; never touches Dual Bot."""
    ctl = _load("smart_brain_ctl.json", {"enabled": True})
    ctl["gate"] = bool(on)
    _save("smart_brain_ctl.json", ctl)


def gate_reason(symbol, action, now=None):
    """Called by the main bot before it opens a paper trade. Returns a reason text ONLY when ALL of these are true, else None (= take it):
    the switch is ON, the Brain is running, trust is 'earned', the luck test says 'solid', the same coin and side has a matching Dual Bot
    setup from the last 30 minutes, and the Brain DISLIKES that setup. Unknown or unsure always means: take the trade."""
    try:
        if not gate_on():
            return None
        now = now or time.time()
        view = _load("smart_brain_view.json", {})
        if now - float(view.get("beat") or 0) > BEAT_STALE_S:
            return None
        if (view.get("trust") or {}).get("verdict") != "earned" or (view.get("luck") or {}).get("verdict") != "solid":
            return None
        want = 1 if str(action).upper() in ("BUY", "LONG") else -1
        best = None
        for x in view.get("signals") or []:
            if x.get("s") != symbol or x.get("d") != want or x.get("src") not in ("MAIN", "BOTH"):
                continue
            t = float(x.get("t") or 0)
            t = t / 1000.0 if t > 1e11 else t
            if 0 <= now - t <= GATE_WINDOW_S and (best is None or t > best[0]):
                best = (t, x)
        if best and best[1].get("verdict") == "dislike":
            return "Smart Brain skipped it: " + str(best[1].get("verdict_text") or "dislikes this setup")[:110]
    except Exception:
        return None
    return None


def ensure_running():
    """Starts the worker when it is enabled and its heartbeat is stale. A second copy cannot start (file lock)."""
    try:
        if not _load("smart_brain_ctl.json", {"enabled": True}).get("enabled", True):
            return False
        view = _load("smart_brain_view.json", {})
        if time.time() - float(view.get("beat") or 0) < BEAT_STALE_S or time.time() - _SPAWN["t"] < 60:
            return False
        _SPAWN["t"] = time.time()
        log = open(_p("smart_brain.log"), "a", encoding="utf-8")
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "worker"], stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, cwd=HERE)
        _SPAWN["err"] = ""
        return True
    except Exception as e:
        _SPAWN["err"] = f"Could not start Smart Brain: {type(e).__name__}: {str(e)[:120]}"
        return False


def status():
    view = _load("smart_brain_view.json", {})
    age = time.time() - float(view.get("beat") or 0) if view.get("beat") else None
    enabled = bool(_load("smart_brain_ctl.json", {"enabled": True}).get("enabled", True))
    running = age is not None and age < BEAT_STALE_S
    if not enabled:
        state, text = "stopped", "Stopped."
    elif running:
        state, text = view.get("status", "ready"), view.get("status_text", "")
    else:
        state, text = "starting", "Starting up, give it a minute."
    out = dict(view) if view else {"signals": [], "hours": [], "repeat_loss": [], "patterns": [], "bands": [], "watch": [],
                                    "trust": {"verdict": "learning", "text": "No data yet."}, "rows": 0, "min_n": MIN_N}
    out.update({"gate": gate_on(), "enabled": enabled, "running": running, "state": state, "state_text": text,
                "error": _SPAWN["err"] or out.get("error", "")})
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "worker":
        worker()
    else:
        v = build_view()
        print(json.dumps({k: v[k] for k in ("rows", "status", "status_text", "trust")}, default=str)[:1500])
