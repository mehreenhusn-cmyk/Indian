#!/usr/bin/env python3
"""
dual_lab.py - DUAL BOT (paper only, no AI key, own low-priority process).

What it is: a paper bot that reads BOTH indicators (the main EMA50 chart + the Special Master Z pane with the
Z-EMA 30/50 cloud and the black Z candle) and learns by itself when to trade and how to exit. The live bot is not touched.

How it works (plain code, no AI calls, so a key limit can never stop it):
  1. START: it downloads the last days of candles for today's top-10 gainers + losers on 5m and 15m, replays every
     signal (MAIN = EMA50 cross, Z = black Z candle, BOTH) with 9 exit rules and keeps the results as its memory.
  2. LEARN: a small ridge-regression model learns "what does this situation earn with each exit rule" from the
     tags of both indicators. It is trained on the older 60% and graded on the newer 40% it never saw. Only if it
     beats "take everything" there does it switch from EXPLORE to LEARNED. Nothing is hand-written as a rule.
  3. TRADE (paper, 100 USDT x 10): on every new signal it takes the trade and the exit rule the model likes.
     In EXPLORE mode it takes every signal (to learn); in LEARNED mode it skips signals it expects to lose, and
     still takes a few test trades so it keeps learning. Skipped signals are followed too ("what if").
  4. REPORT: the app shows live results, the skipped-signal check and the best / worst situations.

Honest limits: exits are chosen from the 9 rules of tag_lab.EXITS (SL = signal candle extreme, TPs = SD levels, as the
bot), not invented freely. A replay is evidence, not a promise: no slippage, fee is a flat number.

Run by hand:   cd backend && python3 dual_lab.py worker      (normally the backend starts it by itself)
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

BTC_SYM, BTC_MARGIN = "BTCUSDT", 1000.0     # BTC is always in the Dual Bot and trades 1000 USDT (10x like the rest, paper only)


def _mg(t):
    """Margin (USDT) of ONE trade: BTC 1000, every other coin MARGIN."""
    return BTC_MARGIN if (t or {}).get("s") == BTC_SYM else MARGIN


LEV, MARGIN, FEE = 10.0, 100.0, 1.0          # same as the Tag Lab: 10x, 100 USDT margin, fee in ROI points
TFS = ("5m", "15m")
BOOT_DAYS = 7
CYCLE_S = 20
MAX_ROWS, MAX_TRADES, MAX_SEEN = 5000, 600, 6000
MIN_TRAIN = 150            # rows needed before the model is trained
THRESH = 0.3               # predicted ROI points a signal must reach in LEARNED mode
EXPLORE_P = 0.08           # share of "skip" signals still taken as test trades in LEARNED mode
RIDGE = 15.0
LUCK_RUNS = 5              # shuffled-result tests the model must beat before it is called LEARNED
CLIP = 100.0               # one trade counts at most +-100 ROI points in the model (keeps one freak candle from steering it)
BEAT_STALE_S = 150
RT_WAITS, RT_ZONE = (3, 6, 12, 24), 0.25   # retest check: how long to wait for price to come back to EMA50 (+ a quarter SD zone): all four are measured
MAX_RT = 4000
LATEST = 3                 # a signal is new if it is on one of the last 3 closed candles


# ---------------------------------------------------------------- files
def _dir():
    base = os.environ.get("OWL_DATA_DIR")
    if not base:
        try:
            with open(os.path.expanduser("~/.owl_data_dir"), "r", encoding="utf-8") as f:
                base = f.read().strip()
        except Exception:
            base = ""
    base = base or os.path.expanduser("~/owl_data")
    os.makedirs(base, exist_ok=True)
    return base


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


# ---------------------------------------------------------------- the model (pure Python ridge regression)
def _tl():
    import tag_lab as TL
    return TL


import dual_memory as MD            # Part B: fake-signal labels, mistake memory, lessons


def feats_of(tg_list, tf, d):
    TL = _tl()
    out = [f"{TL.DIMS[k]}={v}" for k, v in enumerate(tg_list)]
    out.append("tf=" + tf)
    out.append("side=" + ("L" if d > 0 else "S"))
    return out


def _solve(A, B):
    """Gauss-Jordan for A x = B (several right-hand sides at once). A is symmetric positive definite (ridge added)."""
    m, k = len(A), len(B[0])
    M = [A[i][:] + B[i][:] for i in range(m)]
    for c in range(m):
        piv = max(range(c, m), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            continue
        M[c], M[piv] = M[piv], M[c]
        pv = M[c][c]
        M[c] = [v / pv for v in M[c]]
        for r in range(m):
            if r != c and M[r][c] != 0.0:
                f = M[r][c]
                Mc = M[c]
                M[r] = [a - f * b for a, b in zip(M[r], Mc)]
    return [[M[i][m + j] for j in range(k)] for i in range(m)]


def fit(samples, n_exits):
    """samples: list of (feature names, [net per exit rule]). -> {'vocab', 'W'} (W[feature][exit])."""
    vocab = {}
    for fs, _ in samples:
        for f in fs:
            vocab.setdefault(f, len(vocab) + 1)          # 0 = bias
    m = len(vocab) + 1
    A = [[0.0] * m for _ in range(m)]
    B = [[0.0] * n_exits for _ in range(m)]
    for fs, ys in samples:
        idx = [0] + [vocab[f] for f in fs]
        for a in idx:
            Aa = A[a]
            for b in idx:
                Aa[b] += 1.0
            Ba = B[a]
            for e in range(n_exits):
                Ba[e] += max(-CLIP, min(CLIP, ys[e]))
    for a in range(1, m):
        A[a][a] += RIDGE
    A[0][0] += 1e-6
    return {"vocab": vocab, "W": _solve(A, B)}


def predict(model, fs):
    W, vocab = model["W"], model["vocab"]
    n = len(W[0])
    out = list(W[0])
    for f in fs:
        j = vocab.get(f)
        if j:
            row = W[j]
            for e in range(n):
                out[e] += row[e]
    return out


def train(rows_list, exit_names):
    """rows_list: [(t, feats, nets)] -> model dict (or None when there is too little data).
    Trains on the older 60%, grades on the newer 40% (the model never saw), then refits on everything."""
    if len(rows_list) < MIN_TRAIN:
        return None
    rows_list = sorted(rows_list, key=lambda r: r[0])
    cut = int(len(rows_list) * 0.6)
    old, new = rows_list[:cut], rows_list[cut:]
    ne = len(exit_names)
    bot_i = exit_names.index(_tl().BOT)
    m1 = fit([(f, n) for _, f, n in old], ne)
    taken, base = [], []
    for _, fs, nets in new:
        pr = predict(m1, fs)
        e = max(range(ne), key=lambda k: pr[k])
        base.append(nets[bot_i])
        if pr[e] > THRESH:
            taken.append(nets[e])
    avg = lambda v: (sum(v) / len(v)) if v else 0.0
    val = {"train": len(old), "test": len(new), "taken": len(taken), "taken_avg": round(avg(taken), 2),
           "all_avg": round(avg(base), 2), "taken_sum": round(sum(taken), 1), "all_sum": round(sum(base), 1)}
    gain = val["taken_avg"] - val["all_avg"]
    # luck check: the same test on SHUFFLED results (features no longer match outcomes). Real gain must beat every shuffle.
    rnd = random.Random(7)
    luck = []
    for _ in range(LUCK_RUNS):
        ys = [n for _, _, n in rows_list]
        rnd.shuffle(ys)
        sh = [(f, y) for (_, f, _), y in zip(rows_list, ys)]
        ms = fit(sh[:cut], ne)
        tk, bs = [], []
        for fs, nets in sh[cut:]:
            pr = predict(ms, fs)
            e = max(range(ne), key=lambda k: pr[k])
            bs.append(nets[bot_i])
            if pr[e] > THRESH:
                tk.append(nets[e])
        luck.append(avg(tk) - avg(bs) if len(tk) >= 5 else 0.0)
    val["gain"], val["luck_max"] = round(gain, 2), round(max(luck), 2) if luck else 0.0
    learned = len(taken) >= 30 and val["taken_avg"] > 0.5 and gain > 0.5 and gain > (max(luck) if luck else 0.0)
    full = fit([(f, n) for _, f, n in rows_list], ne)
    glob = [avg([n[e] for _, _, n in rows_list]) for e in range(ne)]
    full.update(mode="LEARNED" if learned else "EXPLORE", val=val, best_exit=max(range(ne), key=lambda k: glob[k]),
                glob=[round(g, 2) for g in glob], rows=len(rows_list))
    return full


def decide(model, fs, exit_names):
    """-> (take, exit index, mode word, predicted ROI points or None, reason in plain English)."""
    bot_i = exit_names.index(_tl().BOT)
    if model is None:
        return True, bot_i, "explore", None, "Not enough history yet. Taking the signal with the bot's own exit to learn."
    if model["mode"] == "EXPLORE":
        e = model["best_exit"]
        return True, e, "explore", None, ("Exploring: the model has not beaten 'take everything' on new data yet, "
                                          "so it takes every signal with the exit that earned most so far.")
    pr = predict(model, fs)
    e = max(range(len(pr)), key=lambda k: pr[k])
    if pr[e] > THRESH:
        return True, e, "learned", round(pr[e], 2), f"Learned: expects {pr[e]:+.1f} ROI points with '{exit_names[e]}'."
    if random.random() < EXPLORE_P:
        return True, bot_i, "test", round(pr[e], 2), f"Test trade: the model expects only {pr[e]:+.1f}, taken so it keeps learning."
    return False, bot_i, "skip", round(pr[e], 2), f"Skipped: the model expects at most {pr[e]:+.1f} ROI points here."


# ---------------------------------------------------------------- signals + trades
TF_MIN = {"5m": 5, "15m": 15}
WHY_WORD = {"SL": "Stop loss was hit", "BE": "Stop at entry was hit (no loss)", "TRAIL": "The trailing stop was hit",
            "TP": "The take-profit level was reached", "REV": "The opposite signal came, so it closed",
            "HOLD": "The time limit ended the trade", "TIMEOUT": "The time limit ended the trade"}


def _bits(S, i, step, r, live=False):
    """Chart facts of one replayed trade: where the stop moved, where / when it ended (or the latest price if still open)."""
    j = min(S["n"] - 1, i + int(r["bars"]))
    out = {"path": [[S["t"][k] + step, p] for k, p in r.get("path", [])], "xt": S["t"][j]}
    out["lpx" if live else "xpx"] = r["px"]
    out["lbars" if live else "bars2"] = int(r["bars"])
    return out


def _dur(candles, tf):
    m = int(candles) * TF_MIN.get(tf, 5)
    return f"{m} min" if m < 120 else f"{m // 60}h {m % 60:02d}m"


def _px(x):
    return "-" if x is None else f"{x:.8g}"


def _scenario(t):
    """The situation in plain words, from the tags of both indicators (nothing here is a rule, it only describes)."""
    tg = t.get("tg") or {}
    side = "BUY" if t["d"] > 0 else "SELL"
    head = {"MAIN": f"Main chart {side} signal (EMA50 cross)", "Z": f"Z black candle {side}",
            "BOTH": f"Both indicators gave {side} on the same candle"}.get(t["src"], f"{side} signal")
    parts = [head]
    if t["src"] != "BOTH" and tg.get("order"):
        parts.append(tg["order"])
    for k in ("tsi_zero", "z_ema", "cloud", "zsm"):
        if tg.get(k):
            parts.append(tg[k])
    if tg.get("side_main_pct") is not None:
        parts.append(f"Sideways: main chart {tg['side_main_pct']}%, Z pane {tg['side_z_pct']}%")
    return ". ".join(parts) + "."


def _what(t):
    """Two lines: what happened in this trade."""
    path = t.get("path") or []
    moves = f"The stop moved {len(path)} time{'s' if len(path) != 1 else ''}" if path else "The stop did not move"
    now_sl = path[-1][1] if path else t["sl"]
    status = t["status"]
    if status in ("closed", "skipped_done"):
        net = t.get("net") or 0.0
        usdt = _mg(t) * net / 100.0
        lead = ("" if status == "closed" else "It was skipped, but if taken: ")
        return (f"{lead}{WHY_WORD.get(t.get('end'), 'The trade ended')} after {_dur(t.get('bars') or 0, t['f'])}. "
                f"Result {usdt:+.2f} USDT ({net:+.1f}% of margin, fee inside).",
                f"Exit rule: {t['exit']}. {moves}; last stop {_px(now_sl)}.")
    net = t.get("live")
    if net is None:
        return ("Waiting for the first candle after the entry.", f"Exit rule: {t['exit']}. First stop {_px(t['sl'])}.")
    lead = "Skipped, but if taken it would be " if status == "skipped" else "Open for "
    dur = _dur(t.get("lbars") or 0, t["f"])
    txt = (f"{lead}{dur}. " if status == "open" else f"{lead}at {net * _mg(t) / 100.0:+.2f} USDT after {dur}.")
    if status == "open":
        txt += f"Now {net * _mg(t) / 100.0:+.2f} USDT ({net:+.1f}% of margin)."
    return (txt, f"Exit rule: {t['exit']}. {moves}; stop now {_px(now_sl)}.")


def _entry(S, Z, i, tf, strat, TL, FL):
    """Same entry as Tag Lab (MAIN / Z / BOTH). None = no signal or no sensible room."""
    m = 1 if S["xup"][i] else -1 if S["xdn"][i] else 0
    zc = 1 if Z["up"][i] else -1 if Z["dn"][i] else 0
    if not m and not zc or (m and zc and m != zc):
        return None
    d = m or zc
    src = "BOTH" if (m and zc) else ("Z" if zc else "MAIN")
    mean, sd = S["sma"][i], S["std"][i]
    if not sd or mean is None:
        return None
    t_close = S["t"][i] + FL.TF_MS[tf] - 1
    tg = TL.make_tags(S, Z, i, d, src, t_close)
    if tg is None:
        return None
    entry = S["c"][i]
    sl = S["l"][i] if d > 0 else S["h"][i]
    lv = {"zero_price": mean, "onesd": mean + sd, "twosd": mean + 2 * sd, "threesd": mean + 3 * sd,
          "neg_onesd": mean - sd, "neg_twosd": mean - 2 * sd, "neg_threesd": mean - 3 * sd}
    tps = list(strat.calculate_tp_levels(entry, d > 0, lv))
    if (d > 0 and not (sl < entry < tps[0])) or (d < 0 and not (tps[0] < entry < sl)):
        return None
    return {"d": d, "src": src, "tg": tg, "entry": entry, "sl": sl, "tps": tps, "t": t_close, "ct": S["t"][i]}


def process(data, sym, tf, candles, boot, now_ms, model, exit_names):
    """One coin on one timeframe: add finished replays to the memory, finish open / skipped trades, open new ones."""
    TL = _tl()
    import filter_lab as FL
    from recovered_bot import ai_ind_features as F
    from recovered_bot.strategy import ABCDStrategy
    if len(candles) < F.MIN_BARS + 5:
        return 0
    S = F.build(candles)
    Z = TL.z_series(S)
    strat = ABCDStrategy()
    # 1. memory: every finished MAIN / Z / BOTH replay
    added = 0
    since = now_ms - (BOOT_DAYS if boot else 1) * 86_400_000
    rows, _ = TL.rows_from_candles(sym, tf, candles, since, LEV, FEE)
    for r in rows:
        key = f"{sym}|{tf}|{r['t']}"
        if key in data["rows"]:
            continue
        tg_list = [r["tg"][k] for k in TL.DIMS]
        data["rows"][key] = [sym, tf, r["t"], r["d"], tg_list, [round(r["x"][n][0], 2) for n in exit_names],
                            [int(r["x"][n][1]) for n in exit_names]]
        added += 1
    # 1b. retest check (measurement only)
    rt = data.setdefault("rt", {})
    try:
        for r in _retest_rows(S, Z, tf, since, strat, TL, FL):
            rk = f"{sym}|{tf}|{r[0]}"
            if rk not in rt or len(rt[rk]) != 8:
                rt[rk] = list(r)
    except Exception as ex:                                  # a measurement problem must never stop the bot
        print(f"dual_lab: retest check skipped for {sym} {tf}: {ex}", flush=True)
    # 2. finish open / skipped trades of this coin
    pos = {t: k for k, t in enumerate(S["t"])}
    for tr in data["trades"]:
        if tr["s"] != sym or tr["f"] != tf or tr["status"] not in ("open", "skipped"):
            continue
        i = pos.get(tr["ct"])
        if i is None:
            tr["status"] = "expired"
            continue
        rule = TL.EXITS[tr["exit"]]
        r = TL.sim_rule(S, Z, i, tr["d"], tr["entry"], tr["sl"], tr["tps"], LEV, FEE, **rule)
        if r is not None:
            tr["net"], tr["end"], tr["bars"], tr["hit"] = round(r["net"], 2), r["why"], r["bars"], r["hit"]
            tr["label"], tr["reason"] = MD.label_trade(tr.get("tg") or {}, tr["net"], r["why"], r["hit"])
            tr.update(_bits(S, i, FL.TF_MS[tf], r))
            tr.pop("lpx", None)
            tr["status"] = "closed" if tr["take"] else "skipped_done"
            tr["closed_at"] = time.time()
        else:
            lv = TL.sim_rule(S, Z, i, tr["d"], tr["entry"], tr["sl"], tr["tps"], LEV, FEE, allow_open=True, **rule)
            tr["live"] = round(lv["net"], 2) if lv else None
            if lv:
                tr.update(_bits(S, i, FL.TF_MS[tf], lv, live=True))
    # 3. new signals on the last closed candles
    n = S["n"]
    for i in range(max(F.MIN_BARS, n - LATEST), n):
        e = _entry(S, Z, i, tf, strat, TL, FL)
        if e is None:
            continue
        key = f"{sym}|{tf}|{e['t']}"
        if key in data["seen"]:
            continue
        data["seen"][key] = 1
        fs = feats_of([e["tg"][k] for k in TL.DIMS], tf, e["d"])
        take, xi, mode, pred, why = decide(model, fs, exit_names)
        mem = MD.lookalikes(list(data["rows"].values()), [e["tg"][k] for k in TL.DIMS], e["t"])
        data["trades"].append({
            "id": key, "s": sym, "f": tf, "ct": e["ct"], "t": e["t"], "d": e["d"], "src": e["src"], "entry": e["entry"],
            "sl": e["sl"], "tps": e["tps"], "exit": exit_names[xi], "take": take, "mode": mode, "pred": pred, "why": why,
            "status": "open" if take else "skipped", "opened": time.time(), "tg": e["tg"], "mem": mem})
    return added


def _retest_rows(S, Z, tf, since, strat, TL, FL):
    """What if we had WAITED for a retest? For every signal: enter at once (the bot's way) versus wait up to RT_WAIT candles for price to
    come back to the EMA50 zone, then enter there with the SAME stop, take-profits and exit rule. Nothing here changes the bot, it only measures.
    -> [(t, d, src, tsi_line_ok, tsi_hist_grow, net_now, net_retest_or_None, candles_until_the_retest)] of finished trades only.
    The retest candle is the FIRST touch, so one pass answers every wait length: a wait of W candles only counts touches with k <= W."""
    from recovered_bot import ai_ind_features as F
    rule = TL.EXITS[TL.BOT]
    o, h, l, n = S["o"], S["h"], S["l"], S["n"]
    out = []
    for i in range(F.MIN_BARS, n):
        if S["t"][i] + FL.TF_MS[tf] - 1 < since:
            continue
        e = _entry(S, Z, i, tf, strat, TL, FL)
        if e is None:
            continue
        d, entry, sl, tps = e["d"], e["entry"], e["sl"], e["tps"]
        a = TL.sim_rule(S, Z, i, d, entry, sl, tps, LEV, FEE, **rule)
        if a is None:
            continue
        rt, fill_j = None, None
        for j in range(i + 1, min(n - 1, i + max(RT_WAITS)) + 1):
            ema, sd = S["e50"][j], S["std"][j]
            if ema is None or sd is None:
                continue
            if (h[j] >= tps[0]) if d > 0 else (l[j] <= tps[0]):
                break                                           # it ran to TP1 without us: the retest never came
            if (l[j] <= sl) if d > 0 else (h[j] >= sl):
                break                                           # the stop level was hit before a retest entry
            zone = ema + d * RT_ZONE * sd
            if (l[j] <= zone) if d > 0 else (h[j] >= zone):
                fill = min(zone, o[j]) if d > 0 else max(zone, o[j])
                if (sl < fill < tps[0]) if d > 0 else (tps[0] < fill < sl):
                    fill_j = j
                    r = TL.sim_rule(S, Z, j, d, fill, sl, tps, LEV, FEE, **rule)
                    if r is None:
                        fill_j = -1                             # entered but not finished yet: count it next cycle
                    else:
                        rt = r["net"]
                break
        if fill_j == -1:
            continue
        tg = e["tg"]
        out.append((e["t"], d, e["src"], 1 if str(tg.get("tsi_line", "")).startswith("TSI on the trade") else 0,
                    1 if tg.get("tsi_hist") == "histogram growing" else 0, round(a["net"], 2), None if rt is None else round(rt, 2),
                    None if rt is None else fill_j - i))
    return out


def retest_summary(data):
    """Plain numbers (USDT on the paper margin) for the app: waiting for a retest versus entering at the signal, for several wait lengths."""
    rows = [r for r in (data.get("rt") or {}).values() if len(r) == 8]
    k = MARGIN / 100.0

    def block(rs, W):
        eff = [(r, r[6] if (r[6] is not None and r[7] is not None and r[7] <= W) else None) for r in rs]
        ent = [(r, x) for r, x in eff if x is not None]
        mis = [r for r, x in eff if x is None]
        now_all = sum(r[5] for r in rs) * k
        now_ent = sum(r[5] for r, _ in ent) * k
        now_mis = sum(r[5] for r in mis) * k
        rt_sum = sum(x for _, x in ent) * k
        return {"wait": W, "n": len(rs), "entered": len(ent), "missed": len(mis), "now_all": round(now_all, 2),
                "now_entered": round(now_ent, 2), "now_missed": round(now_mis, 2), "retest": round(rt_sum, 2),
                "gain": round(rt_sum - now_all, 2), "extra_on_entered": round(rt_sum - now_ent, 2)}
    if len(rows) < 10:
        return {"status": "collecting", "n": len(rows)}
    waits = [block(rows, W) for W in RT_WAITS]
    best = max(waits, key=lambda b: b["gain"])
    W = best["wait"]
    tsi = []
    for idx, names in ((3, ("TSI on the trade side of its signal line", "TSI on the wrong side of its signal line")),
                       (4, ("TSI histogram growing", "TSI histogram shrinking"))):
        for v, lab in ((1, names[0]), (0, names[1])):
            sub = [r for r in rows if r[idx] == v]
            if len(sub) >= 5:
                b = block(sub, W)
                b["name"] = lab
                tsi.append(b)
    out = dict(best)
    out.update({"status": "ok", "waits": waits, "tsi": tsi})
    return out


def trim(data):
    if len(data["rows"]) > MAX_ROWS:
        keep = sorted(data["rows"].items(), key=lambda kv: kv[1][2])[-MAX_ROWS:]
        data["rows"] = dict(keep)
    rt = data.get("rt")
    if rt is not None and len(rt) > MAX_RT:
        data["rt"] = dict(sorted(rt.items(), key=lambda kv: kv[1][0])[-MAX_RT:])
    if len(data["seen"]) > MAX_SEEN:
        data["seen"] = dict(list(data["seen"].items())[-MAX_SEEN:])
    if len(data["trades"]) > MAX_TRADES:
        done = sorted((t for t in data["trades"] if t["status"] not in ("open", "skipped")), key=lambda t: t["t"])
        live = [t for t in data["trades"] if t["status"] in ("open", "skipped")]
        data["trades"] = done[-max(50, MAX_TRADES - len(live)):] + live


# ---------------------------------------------------------------- report numbers
def _avg(v):
    return sum(v) / len(v) if v else 0.0


def insights(data, exit_names):
    """Best and worst situations (one or two tags) over all remembered replays. Plain counting, n >= 25."""
    TL = _tl()
    bot_i = exit_names.index(TL.BOT)
    rows = sorted(data["rows"].values(), key=lambda r: r[2])
    if len(rows) < 80:
        return {"best": [], "worst": []}
    cut = len(rows) // 2
    groups = {}
    nd = len(TL.DIMS)
    for idx, r in enumerate(rows):
        tg, nets = r[4], r[5]
        half = 0 if idx < cut else 1
        keys = [(k, tg[k]) for k in range(nd) if TL.DIMS[k] != "hour"]
        for a in range(len(keys)):
            for b in range(a, len(keys)):
                key = (keys[a],) if a == b else (keys[a], keys[b])
                g = groups.setdefault(key, [[], []])
                g[half].append(nets)
    out = []
    for key, (o, nw) in groups.items():
        allr = o + nw
        if len(allr) < 25:
            continue
        bot = _avg([x[bot_i] for x in allr])
        best_e = max(range(len(exit_names)), key=lambda e: _avg([x[e] for x in allr]))
        best = _avg([x[best_e] for x in allr])
        both = bool(o) and bool(nw) and _avg([x[best_e] for x in o]) > 0 and _avg([x[best_e] for x in nw]) > 0
        name = " + ".join(f"{TL.DIM_NAME[TL.DIMS[k]]}: {v}" for k, v in key)
        out.append({"name": name, "n": len(allr), "bot": round(bot, 2), "best": round(best, 2), "exit": exit_names[best_e],
                    "both_halves": both})
    out.sort(key=lambda g: g["best"], reverse=True)
    worst = sorted(out, key=lambda g: g["bot"])[:5]
    return {"best": out[:6], "worst": worst}


MIN_SCEN, SCEN_DAYS = 25, 2.0


def scenarios(data, exit_names):
    """Part C: every situation (1 or 2 tags of both indicators) seen in the memory, in plain numbers: how often it repeats per day,
    how many trades, win %, average result and time taken with the bot's exit and with the best exit, and a verdict.
    Verdict is counting only: USE = best exit earns in the older AND the newer half, SKIP = the bot's exit loses in both, else UNSURE."""
    TL = _tl()
    rows = sorted((r for r in data["rows"].values() if len(r) > 6), key=lambda r: r[2])
    if len(rows) < 80:
        return {"status": "collecting", "days": 0.0, "cards": [], "tips": []}
    days = (rows[-1][2] - rows[0][2]) / 86_400_000.0
    if days < SCEN_DAYS:
        return {"status": "collecting", "days": round(days, 1), "cards": [], "tips": []}
    bot_i, cut, nd = exit_names.index(TL.BOT), len(rows) // 2, len(TL.DIMS)
    keys_of = [k for k in range(nd) if TL.DIMS[k] != "hour"]
    groups = {}
    for idx, r in enumerate(rows):
        for a in range(len(keys_of)):
            for b in range(a, len(keys_of)):
                ka, kb = keys_of[a], keys_of[b]
                key = ((ka, r[4][ka]),) if a == b else ((ka, r[4][ka]), (kb, r[4][kb]))
                groups.setdefault(key, []).append(idx)
    cards = []
    for key, ix in groups.items():
        if len(ix) < MIN_SCEN:
            continue
        rs = [rows[i] for i in ix]
        be = max(range(len(exit_names)), key=lambda e: _avg([x[5][e] for x in rs]))
        o, nw = [rows[i] for i in ix if i < cut], [rows[i] for i in ix if i >= cut]
        best, bot = _avg([x[5][be] for x in rs]), _avg([x[5][bot_i] for x in rs])
        use = bool(o) and bool(nw) and _avg([x[5][be] for x in o]) > 0.5 and _avg([x[5][be] for x in nw]) > 0.5
        skip = bool(o) and bool(nw) and _avg([x[5][bot_i] for x in o]) < -0.5 and _avg([x[5][bot_i] for x in nw]) < -0.5
        mins = _avg([x[6][be] * TF_MIN.get(x[1], 5) for x in rs])
        name = " + ".join(f"{TL.DIM_NAME[TL.DIMS[k]]}: {v}" for k, v in key)
        cards.append({"name": name, "n": len(rs), "per_day": round(len(rs) / max(days, 1.0), 1),
                      "bot_avg": round(bot, 1), "bot_win": int(round(100.0 * sum(1 for x in rs if x[5][bot_i] > 0) / len(rs))),
                      "best_avg": round(best, 1), "best_exit": exit_names[be], "best_win": int(round(100.0 * sum(1 for x in rs if x[5][be] > 0) / len(rs))),
                      "mins": int(round(mins)), "verdict": "USE" if use else "SKIP" if skip else "UNSURE", "singles": len(key) == 1})
    use_c = sorted((c for c in cards if c["verdict"] == "USE"), key=lambda c: -c["best_avg"])[:6]
    skip_c = sorted((c for c in cards if c["verdict"] == "SKIP"), key=lambda c: c["bot_avg"])[:6]
    tips = [f"Use: {c['name']}. About {c['best_avg']:+.1f}% per trade with '{c['best_exit']}', takes about {c['mins']} min, seen {c['per_day']}x a day."
            for c in use_c if c["singles"]][:3]
    tips += [f"Skip: {c['name']}. The bot's exit loses {c['bot_avg']:+.1f}% per trade here ({c['n']} trades)." for c in skip_c if c["singles"]][:3]
    return {"status": "ready", "days": round(days, 1), "cards": use_c + skip_c, "tips": tips}


# ---------------------------------------------------------------- Part 2: the setup book
# A "setup" = the full state of BOTH indicators at the entry (8 tags), counted the same way for every coin and both
# timeframes. All tags are already relative to the trade side ("with the trade" / "against"), so a BUY and a SELL with the
# same picture count as the same setup. Nothing is typed by hand: the bot counts what each picture earned.
SETUP_DIMS = ("src", "tsi_zero", "tsi_line", "tsi_hist", "z_ema", "cloud", "zsm", "diverge")
MIN_SETUP = 10             # trades a setup needs before it is judged
_BOOK = {}                 # setup key -> small stats, used to tag every open trade with its setup


def _short(dim, v):
    """Short plain words for one tag value (display only, the stored tags stay as they are)."""
    v = str(v)
    if dim == "src":
        return {"MAIN": "Main signal", "Z": "Z signal", "BOTH": "Both signals"}.get(v, v)
    if dim == "tsi_zero":
        return "TSI with trade" if v.startswith("TSI with") else "TSI against trade"
    if dim == "tsi_line":
        return "TSI line with trade" if "trade side" in v else "TSI line against trade"
    if dim == "tsi_hist":
        return "TSI histogram growing" if "growing" in v else "TSI histogram shrinking"
    if dim == "z_ema":
        return "Z beyond both EMAs" if "beyond" in v else "Z between its EMAs" if "between" in v else "Z against both EMAs"
    if dim == "cloud":
        return "Z cloud with trade" if "with the trade" in v else "Z cloud against trade"
    if dim == "zsm":
        return "Z with ZSM" if "trade side" in v else "Z against ZSM"
    if dim == "diverge":
        return "price and Z agree" if (v.endswith("agree") and "disagree" not in v) else "price and Z disagree"
    return v


def _skey(vals):
    return "|".join(str(v) for v in vals)


def _row_vals(r, TL):
    return [r[4][TL.DIMS.index(d)] for d in SETUP_DIMS]


def _trade_vals(t):
    tg = t.get("tg") or {}
    vals = [tg.get(d) for d in SETUP_DIMS]
    return None if any(v is None for v in vals) else vals


def setup_book(data, exit_names):
    """Every setup seen in the memory with its own numbers. Counting only, judged on older and newer half like the scenarios."""
    TL = _tl()
    rows = sorted((r for r in data["rows"].values() if len(r) > 6), key=lambda r: r[2])
    if len(rows) < 80:
        _BOOK.clear()
        return {"status": "collecting", "days": 0.0, "totals": {}, "use": [], "skip": [], "common": []}
    days = (rows[-1][2] - rows[0][2]) / 86_400_000.0
    bot_i, cut = exit_names.index(TL.BOT), len(rows) // 2
    groups = {}
    for idx, r in enumerate(rows):
        groups.setdefault(_skey(_row_vals(r, TL)), []).append(idx)
    book, cards = {}, []
    tot = {"seen": len(groups), "judged": 0, "use": 0, "skip": 0, "unsure": 0, "few": 0}
    for key, ix in groups.items():
        rs = [rows[i] for i in ix]
        n = len(rs)
        bot = _avg([x[5][bot_i] for x in rs])
        win = int(round(100.0 * sum(1 for x in rs if x[5][bot_i] > 0) / n))
        if n < MIN_SETUP:
            tot["few"] += 1
            book[key] = {"n": n, "win": win, "avg": round(bot, 1), "verdict": "FEW"}
            continue
        o, nw = [rows[i] for i in ix if i < cut], [rows[i] for i in ix if i >= cut]
        be = max(range(len(exit_names)), key=lambda e: _avg([x[5][e] for x in rs]))
        ok = len(o) >= 4 and len(nw) >= 4
        use = ok and _avg([x[5][be] for x in o]) > 0.5 and _avg([x[5][be] for x in nw]) > 0.5
        skip = ok and _avg([x[5][bot_i] for x in o]) < -0.5 and _avg([x[5][bot_i] for x in nw]) < -0.5
        verdict = "USE" if use else "SKIP" if skip else "UNSURE"
        tot["judged"] += 1
        tot[verdict.lower()] += 1
        vals = key.split("|")
        card = {"name": " + ".join(_short(d, v) for d, v in zip(SETUP_DIMS, vals)), "n": n,
                "per_day": round(n / max(days, 1.0), 1), "bot_avg": round(bot, 1), "bot_win": win,
                "best_avg": round(_avg([x[5][be] for x in rs]), 1), "best_exit": exit_names[be],
                "best_win": int(round(100.0 * sum(1 for x in rs if x[5][be] > 0) / n)),
                "mins": int(round(_avg([x[6][be] * TF_MIN.get(x[1], 5) for x in rs]))), "verdict": verdict}
        cards.append(card)
        book[key] = {"n": n, "win": win, "avg": round(bot, 1), "verdict": verdict}
    _BOOK.clear()
    _BOOK.update(book)
    use_c = sorted((c for c in cards if c["verdict"] == "USE"), key=lambda c: -c["best_avg"])[:6]
    skip_c = sorted((c for c in cards if c["verdict"] == "SKIP"), key=lambda c: c["bot_avg"])[:6]
    common = sorted(cards, key=lambda c: -c["n"])[:5]
    return {"status": "ready" if days >= SCEN_DAYS else "collecting", "days": round(days, 1), "totals": tot,
            "use": use_c, "skip": skip_c, "common": common}


def setup_of(t):
    """The setup of one trade and what that setup did before (n = 0 means the bot never saw this picture)."""
    vals = _trade_vals(t)
    if vals is None or not _BOOK:
        return None
    b = _BOOK.get(_skey(vals))
    if b is None:
        return {"n": 0, "win": 0, "avg": 0.0, "verdict": "NEW"}
    return b


# ---------------------------------------------------------------- Part 3: today numbers + the daily review
DAY_MS = 86_400_000
REVIEW_DIMS = SETUP_DIMS + ("side_main", "side_z", "z_room")
MIN_REV = 5                # trades a scenario needs inside one day before the review talks about it


def _day_start_ms(now=None):
    """Start of the trading day = crypto daily open, 00:00 UTC = 5:30 AM IST (the same day as Dashboard and Calendar)."""
    ms = int((time.time() if now is None else now) * 1000)
    return ms - ms % DAY_MS


def _usdt(t, key="net"):
    return _mg(t) * (t.get(key) or 0.0) / 100.0


def _day_items(trades, a, b):
    """Finished PAPER trades whose entry was inside [a, b): (result in USDT, set of scenario words)."""
    out = []
    for t in trades:
        if t.get("status") != "closed" or not (a <= t["t"] < b):
            continue
        tg = t.get("tg") or {}
        names = set()
        for d in REVIEW_DIMS:
            if tg.get(d):
                names.add(_short(d, tg[d]) if d in SETUP_DIMS else str(tg[d]))
        out.append((_usdt(t), names))
    return out


def _by_name(items):
    g = {}
    for pnl, names in items:
        for nm in names:
            r = g.setdefault(nm, [0, 0.0, 0, 0.0])
            r[0] += 1
            r[1] += pnl
            if pnl > 0:
                r[2] += 1
                r[3] += pnl
    return g


def day_review(data, now=None):
    """Looks back at the last FULL day (5:30 AM to 5:30 AM IST). The bot took every signal that day. For each scenario:
    what it earned, what skipping it would have saved (its losses), what skipping would have cost (its profits) and the net.
    One day is a hint, not proof, so a scenario that was also bad the day before is marked."""
    d0 = _day_start_ms(now)
    a, b = d0 - DAY_MS, d0
    trades = data["trades"]
    cur, pre = _day_items(trades, a, b), _day_items(trades, a - DAY_MS, a)
    left = sum(1 for t in trades if t.get("status") == "open" and a <= t["t"] < b)
    day = time.strftime("%d %b", time.gmtime(a / 1000.0))
    if len(cur) < 10:
        return {"status": "collecting", "day": day, "n": len(cur), "open_left": left}
    prev = _by_name(pre)
    rows = []
    wide = max(MIN_REV, int(0.6 * len(cur)))              # a tag on most trades is not a scenario you can skip
    for nm, (n, pnl, won, gain) in _by_name(cur).items():
        if n < MIN_REV or n > wide:
            continue
        pv = prev.get(nm)
        rows.append({"name": nm, "n": n, "won": won, "pnl": round(pnl, 2), "saved": round(gain - pnl, 2), "missed": round(gain, 2),
                     "net": round(-pnl, 2), "prev": round(pv[1], 2) if pv and pv[0] >= MIN_REV else None})
    bad = sorted((r for r in rows if r["pnl"] < 0), key=lambda r: r["pnl"])[:5]
    good = sorted((r for r in rows if r["pnl"] > 0), key=lambda r: -r["pnl"])[:3]
    skipset = {r["name"] for r in bad}
    kept = [p for p, names in cur if not (names & skipset)]
    total = sum(p for p, _ in cur)
    return {"status": "ready", "day": day, "n": len(cur), "won": sum(1 for p, _ in cur if p > 0), "pnl": round(total, 2), "open_left": left,
            "bad": bad, "good": good,
            "combo": {"skipped": len(cur) - len(kept), "with": round(sum(kept), 2), "without": round(total, 2)}}


def summary(data, model, exit_names):
    """Alt-coin numbers at the top level; BTC (own margin, own totals) under ["btc"] - never added together."""
    alt = [t for t in data["trades"] if t.get("s") != BTC_SYM]
    btc = [t for t in data["trades"] if t.get("s") == BTC_SYM]
    out = _summary_of(alt)
    out["btc"] = _summary_of(btc)
    return out


def _summary_of(tr):
    closed = [t for t in tr if t["status"] == "closed"]
    opens = [t for t in tr if t["status"] == "open"]
    skipped_done = [t for t in tr if t["status"] == "skipped_done"]
    pnl = lambda t: _mg(t) * (t.get("net") or 0.0) / 100.0
    by_src = {}
    for t in closed:
        s = by_src.setdefault(t["src"], {"n": 0, "wins": 0, "pnl": 0.0})
        s["n"] += 1
        s["wins"] += 1 if (t.get("net") or 0) > 0 else 0
        s["pnl"] += pnl(t)
    d0 = _day_start_ms()
    closed_today = [t for t in closed if (t.get("closed_at") or t["t"] / 1000.0) * 1000 >= d0]
    real_today = sum(pnl(t) for t in closed_today)
    open_now = sum(_mg(t) * (t.get("live") or 0.0) / 100.0 for t in opens)
    today = {"opened": sum(1 for t in tr if t["status"] in ("open", "closed") and t["t"] >= d0),
             "closed": len(closed_today), "wins": sum(1 for t in closed_today if (t.get("net") or 0) > 0),
             "losses": sum(1 for t in closed_today if (t.get("net") or 0) <= 0),
             "realized": round(real_today, 2), "open_pnl": round(open_now, 2), "total": round(real_today + open_now, 2),
             "open": len(opens), "open_long": sum(1 for t in opens if t["d"] > 0),
             "skipped": sum(1 for t in tr if t["status"] in ("skipped", "skipped_done") and t["t"] >= d0)}
    return {
        "today": today,
        "closed": len(closed), "wins": sum(1 for t in closed if (t.get("net") or 0) > 0),
        "pnl": round(sum(pnl(t) for t in closed), 2), "open": len(opens),
        "open_pnl": round(sum(_mg(t) * (t.get("live") or 0.0) / 100.0 for t in opens), 2),
        "skipped_done": len(skipped_done), "skipped_pnl": round(sum(pnl(t) for t in skipped_done), 2),
        "skipped_open": sum(1 for t in tr if t["status"] == "skipped"),
        "by_src": {k: {"n": v["n"], "wins": v["wins"], "pnl": round(v["pnl"], 2)} for k, v in by_src.items()},
    }


def slim(t):
    scn = _scenario(t)
    w1, w2 = _what(t)
    return {"s": t["s"], "f": t["f"], "d": t["d"], "src": t["src"], "exit": t["exit"], "mode": t["mode"], "why": t["why"],
            "status": t["status"], "net": t.get("net"), "live": t.get("live"), "end": t.get("end"), "bars": t.get("bars"),
            "t": t["t"], "ct": t.get("ct"), "entry": t["entry"], "sl": t["sl"], "tps": t.get("tps"),
            "margin": _mg(t), "path": t.get("path") or [], "xpx": t.get("xpx"), "xt": t.get("xt"), "lpx": t.get("lpx"),
            "scn": scn, "what1": w1, "what2": w2, "label": t.get("label"), "reason": t.get("reason"), "mem": t.get("mem"),
            "side": [(t.get("tg") or {}).get("side_main_pct"), (t.get("tg") or {}).get("side_z_pct")]}


def make_view(data, model, ins, exit_names, progress, err, enabled):
    tr = sorted(data["trades"], key=lambda t: t["t"], reverse=True)
    mv = None
    if model:
        mv = {"mode": model["mode"], "rows": model["rows"], "val": model["val"],
              "best_exit": exit_names[model["best_exit"]]}
    return {"enabled": enabled, "beat": time.time(), "model": mv, "rows": len(data["rows"]), "summary": summary(data, model, exit_names),
            "insights": {"best": ins.get("best", []), "worst": ins.get("worst", [])}, "scen": ins.get("scen") or {"status": "collecting", "days": 0.0, "cards": [], "tips": []}, "lessons": MD.lessons(data["trades"]), "review": day_review(data),
            "setups": ins.get("setups") or {"status": "collecting", "days": 0.0, "totals": {}, "use": [], "skip": [], "common": []},
            "recent": [dict(slim(t), stp=setup_of(t)) for t in ([t for t in tr if t["status"] == "open"] + [t for t in tr if t["status"] != "open"][:40])], "progress": progress, "error": err, "retest": retest_summary(data),
            "margin": MARGIN, "btc_margin": BTC_MARGIN, "lev": LEV, "started": data.get("started")}


# ---------------------------------------------------------------- the worker (own process)
def _lock():
    """Only one worker at a time.
    Returns a file handle (got the lock), None (another worker really holds it) or -1 (this phone cannot lock files: run without).
    The lock file is tried in the HOME folder first. On many phones flock does NOT work inside the shared-storage data folder
    (Internal storage/owl_data); before, that error was read as "already running" and the worker quit at once - the app then
    showed "Starting..." forever."""
    try:
        import fcntl
    except Exception:
        return -1
    for path in (os.path.join(os.path.expanduser("~"), ".owl_dual_lab.lock"), _p("dual_lab.lock")):
        try:
            fd = os.open(path, os.O_CREAT | os.O_RDWR)
        except Exception:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:                      # a real second worker is running
            os.close(fd)
            return None
        except Exception:                            # this folder does not support locks: try the next one
            os.close(fd)
            continue
    return -1


def cycle(data, st, fetch_limit, fetch_range, coins_fn):
    """One pass over all coins. Returns the number of coins processed. fetch_* are passed in so a test can fake the market."""
    import filter_lab as FL
    TL = _tl()
    exit_names = list(TL.EXITS.keys())
    now = time.time()
    now_ms = int(now * 1000)
    if now - st.get("coins_t", 0) > 1800 or not st.get("coins"):
        try:
            st["coins"], st["coins_t"] = list(coins_fn()), now
        except Exception as e:
            st["err"] = f"Cannot get today's coin list from Binance ({type(e).__name__}: {str(e)[:90]})"
    coins = list(dict.fromkeys(st.get("coins", []) + [t["s"] for t in data["trades"] if t["status"] in ("open", "skipped")]))
    if BTC_SYM not in coins:
        coins.append(BTC_SYM)                                  # BTC is always read, whatever today top list is
    done = 0
    failed = 0
    total = len(coins) * len(TFS)
    for tf in TFS:
        step = FL.TF_MS[tf]
        latest = (now_ms // step) * step - step              # open time of the newest closed candle
        for k, sym in enumerate(coins):
            key = f"{sym}|{tf}"
            if data["fetched"].get(key, 0) >= latest:
                done += 1
                continue
            if now_ms - (latest + step) < 4000:               # give Binance a moment to close the candle
                continue
            boot = key not in data["boot"]
            st["progress"] = f"{'loading history' if boot else 'reading'} {sym} {tf} ({done + 1}/{total})"
            candles = fetch_range(sym, tf, now_ms - BOOT_DAYS * 86_400_000 - 450 * step) if boot else fetch_limit(sym, tf, 470)
            if not candles:
                data["fetched"][key] = latest - step + 1       # try again next cycle, not in a tight loop
                failed += 1
                continue
            process(data, sym, tf, candles, boot, now_ms, st.get("model"), exit_names)
            data["fetched"][key] = latest
            if boot:
                data["boot"][key] = 1
            done += 1
            if st.get("push") and time.time() - st.get("push_t", 0) > 2:     # the app sees progress while history loads
                st["push"]()
                st["push_t"] = time.time()
            time.sleep(0.05)
    if failed and not st.get("err"):                          # never fail silently: the app shows this line in red
        why = ""
        try:
            from recovered_bot import ai_shadow_lab as _LAB
            why = str(_LAB._st.get("last_error") or "")[:100]
        except Exception:
            pass
        st["err"] = f"Could not download candles for {failed} of {total} coin/timeframe pairs. {why}".strip()
    return done


PULSE_S = 8


def _start_pulse():
    """Daemon thread: writes the time into dual_lab_pulse.json every PULSE_S seconds. status() reads it, so the app can tell
    'worker busy replaying history' from 'worker not running' (before, a long replay looked like 'Starting...')."""
    import threading

    def run():
        while True:
            try:
                _save("dual_lab_pulse.json", {"t": time.time(), "pid": os.getpid()})
            except Exception:
                pass
            time.sleep(PULSE_S)
    threading.Thread(target=run, daemon=True, name="dual_pulse").start()


def worker():
    lock = _lock()
    if lock is None:
        print("dual_lab: already running", flush=True)
        return 0
    try:
        os.nice(10)
    except Exception:
        pass
    try:                                   # own process = the backend's DNS workaround is NOT active here unless we switch it on
        from recovered_bot.dns_fallback import ensure_dns_fallback
        ensure_dns_fallback()
    except Exception as e:
        print(f"dual_lab: dns fallback not active ({e})", flush=True)
    import filter_lab as FL
    from recovered_bot import ai_shadow_lab as LAB
    TL = _tl()
    exit_names = list(TL.EXITS.keys())
    _start_pulse()                         # tiny "I am alive" signal every few seconds, even while a long history replay blocks the main loop
    data = _load("dual_lab_data.json", {})
    for k, v in (("rows", {}), ("trades", []), ("seen", {}), ("boot", {}), ("fetched", {})):
        if not isinstance(data.get(k), type(v)):
            data[k] = v
    data.setdefault("started", time.time())
    if data.get("dims") != list(TL.DIMS) + ["bars"]:             # new tags (Part B): old rows have fewer tags, so the history is read again once
        data["rows"], data["boot"], data["fetched"], data["dims"] = {}, {}, {}, list(TL.DIMS) + ["bars"]
    st = {"model": None, "rows_at_train": -999, "train_t": 0, "ins": {"best": [], "worst": []}, "ins_t": 0}
    st["push"] = lambda: _save("dual_lab_view.json", make_view(data, st["model"], st["ins"], exit_names, st.get("progress", ""), st.get("err", ""), True))
    st["push"]()
    print("dual_lab worker started", flush=True)
    while True:
        enabled = bool(_load("dual_lab_ctl.json", {"enabled": True}).get("enabled", True))
        err = ""
        if enabled:
            try:
                st["err"] = ""
                cycle(data, st, LAB._fetch_limit, LAB._fetch_range, lambda: FL.default_coins(log=lambda m: None))
                trim(data)
                now = time.time()
                if (len(data["rows"]) - st["rows_at_train"] >= 100 or now - st["train_t"] > 900) and len(data["rows"]) >= MIN_TRAIN:
                    rows_list = [(r[2], feats_of(r[4], r[1], r[3]), r[5]) for r in data["rows"].values()]
                    st["model"] = train(rows_list, exit_names)
                    st["rows_at_train"], st["train_t"] = len(data["rows"]), now
                if now - st["ins_t"] > 300:
                    st["ins"], st["ins_t"] = insights(data, exit_names), now
                    st["ins"]["scen"] = scenarios(data, exit_names)
                    st["ins"]["setups"] = setup_book(data, exit_names)
                _save("dual_lab_data.json", data)
                err = st.get("err", "")
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:120]}"
        _save("dual_lab_view.json", make_view(data, st["model"], st["ins"], exit_names, st.get("progress", "") if enabled else "stopped", err, enabled))
        time.sleep(CYCLE_S if enabled else 5)


# ---------------------------------------------------------------- the backend side (reads the small view file, starts the worker)
_SPAWN = {"t": 0.0, "err": ""}


def set_enabled(on):
    _save("dual_lab_ctl.json", {"enabled": bool(on)})


def ensure_running():
    """Starts the worker if it is enabled and its heartbeat is stale. The lock inside the worker stops a second copy.
    A failure to start is no longer silent: it is kept in _SPAWN['err'] and shown in the app (red line)."""
    try:
        if not _load("dual_lab_ctl.json", {"enabled": True}).get("enabled", True):
            return False
        view = _load("dual_lab_view.json", {})
        if time.time() - float(view.get("beat") or 0) < BEAT_STALE_S or time.time() - _SPAWN["t"] < 60:
            return False
        if time.time() - float(_load("dual_lab_pulse.json", {}).get("t") or 0) < PULSE_S * 3:
            return False                   # the worker is alive but busy (long replay): do not start a second copy
        _SPAWN["t"] = time.time()
        log = open(_p("dual_lab.log"), "a", encoding="utf-8")
        # no preexec_fn: it can hang inside a multi-threaded server. The worker lowers its own priority (os.nice) itself.
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "worker"], stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, cwd=HERE)
        _SPAWN["err"] = ""
        return True
    except Exception as e:
        _SPAWN["err"] = f"Could not start the Dual Bot worker: {type(e).__name__}: {str(e)[:120]}"
        return False


def _log_tail(n=4):
    try:
        with open(_p("dual_lab.log"), "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4000))
            lines = [x.strip() for x in f.read().decode("utf-8", "replace").splitlines() if x.strip()]
        return " | ".join(lines[-n:])[-300:]
    except Exception:
        return ""


_LIVE = {"t": 0.0, "px": {}}


def _live_prices(syms):
    """Latest price of a few coins (the close of the newest, still forming 1m candle = the price now). Cached 6 s; any failure just means no live update."""
    if time.time() - _LIVE["t"] < 6 and all(s in _LIVE["px"] for s in syms):
        return _LIVE["px"]
    try:
        from recovered_bot import ai_shadow_lab as LAB
        for s in list(syms)[:14]:
            raw = LAB._fetch_raw(s, "1m", limit=1)             # the newest (still forming) 1m candle: its close is the price now
            if raw:
                _LIVE["px"][s] = float(raw[-1][4])
        _LIVE["t"] = time.time()
    except Exception:
        pass
    return _LIVE["px"]


def _live_overlay(view):
    """Open trades get the price of RIGHT NOW (not only of the last closed candle): live_now / lpx_now in ROI points of the margin."""
    rec = [t for t in (view.get("recent") or []) if t.get("status") == "open" and t.get("entry")]
    if not rec:
        return
    px = _live_prices(sorted({t["s"] for t in rec}))
    delta = 0.0
    for t in rec:
        p = px.get(t["s"])
        if p:
            t["lpx_now"] = p
            t["live_now"] = round((p - t["entry"]) / t["entry"] * 100.0 * t["d"] * LEV - FEE, 2)
            if t.get("live") is not None:
                delta += (t["live_now"] - t["live"]) * _mg(t) / 100.0
    sm = view.get("summary") or {}
    if delta and isinstance(sm, dict):                        # the open part of every total moves with the live price too
        td = sm.get("today")
        if isinstance(td, dict) and "open_pnl" in td:
            td["open_pnl"] = round(td["open_pnl"] + delta, 2)
            td["total"] = round(td["total"] + delta, 2)
        if "open_pnl" in sm:
            sm["open_pnl"] = round(sm["open_pnl"] + delta, 2)


# ---------------------------------------------------------------- Download report (for the user and for any AI)
def _ts(ms):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.gmtime(float(ms) / 1000.0)) + " UTC"
    except Exception:
        return "-"


def _jd(obj, limit=2500):
    t = json.dumps(obj, default=str, separators=(",", ":"), ensure_ascii=False)
    return t if len(t) <= limit else t[:limit] + " ...(cut)"


REPORT_INTRO = (
    "WHAT THIS IS: the Dual Bot of the Owl Terminal app. It is a PAPER bot (no real money). It reads TWO indicators on the same coin: the main chart "
    "(EMA50 cross) and the Z pane of Special Master v6 (Z candle crossing its EMA50, with EMA30/50 and a cloud), on 5m and 15m. A signal can come from the "
    "main chart (MAIN), from the Z pane (Z) or from both on the same candle (BOTH). Every signal is tagged with the full picture of both indicators at that "
    "moment (TSI vs zero and vs its signal line, histogram, Z vs its EMAs, cloud colour, sideways %, chop, room, time of day). The bot replays 7 days of history, "
    "learns which pictures earn money, and then trades live on paper. Until it beats luck on newer data it takes EVERY signal (mode EXPLORE) so it can keep learning.\n"
    "PAPER SETTINGS: 10x leverage, 100 USDT margin per trade, fee included. Results are ROI % of the margin and USDT. Stop = low/high of the signal candle, "
    "take-profits = main chart SD levels. 9 exit rules exist; each trade uses the one the model expects to be best.\n"
    "HOW TO READ THE TRADES: 'path' = every place the stop moved (time, new stop). 'tags' = the situation. 'label' = real or fake signal with a reason. "
    "'setup' = how the same picture of both indicators did before. Open trades show the live result.\n"
    "RETEST CHECK: measurement only. For every signal the bot also asks what would have happened if it had WAITED for price to come back to the EMA50 zone "
    "(3, 6, 12 or 24 candles) and entered there with the same stop, targets and exit. Positive gain = waiting was better.\n"
    "QUESTIONS TO ASK THE AI: which pictures (tags) lose again and again? Is waiting for a retest better than entering at the signal, and for how long? "
    "Does TSI change the answer? Which exit rule fits which picture? Which coins or hours are bad? What would you skip, and what would that have saved?\n")


def build_report(limit_trades=250):
    view = status()
    data = _load("dual_lab_data.json", {})
    L = [f"DUAL BOT REPORT - made {time.strftime('%Y-%m-%d %H:%M', time.gmtime())} UTC", "", REPORT_INTRO]
    m = view.get("model") or {}
    L += ["== STATUS ==",
          f"running={view.get('running')} enabled={view.get('enabled')} mode={m.get('mode')} history rows={view.get('rows')} best exit={m.get('best_exit')}",
          f"validation on newer data: {_jd(m.get('val'))}", f"error line: {view.get('error') or '-'}", f"progress: {view.get('progress') or '-'}", ""]
    L += ["== TOTALS ==", _jd(view.get("summary"), 3500), ""]
    rt = view.get("retest") or {}
    L.append("== RETEST CHECK (wait for price to come back to EMA50, versus entering at the signal) ==")
    if rt.get("status") == "ok":
        L.append(f"signals measured: {rt['n']}. Best wait: {rt['wait']} candles.")
        for b in rt.get("waits", []):
            L.append(f"  wait {b['wait']:>2} candles: {b['entered']} entered, {b['missed']} never came back | at signal {b['now_all']:+.2f} USDT | after retest {b['retest']:+.2f} USDT "
                     f"| waiting is {'better' if b['gain'] >= 0 else 'worse'} by {b['gain']:+.2f} USDT | missed trades would have made {b['now_missed']:+.2f} USDT")
        L.append("TSI split (at the best wait):")
        for b in rt.get("tsi", []):
            L.append(f"  {b['name']}: {b['n']} signals, {b['entered']} entered | at signal {b['now_all']:+.2f} | after retest {b['retest']:+.2f} | gain {b['gain']:+.2f} USDT")
    else:
        L.append(f"collecting ({rt.get('n', 0)} signals so far, needs 10)")
    L.append("")
    for title, key in (("DAILY REVIEW", "review"), ("SETUPS (same picture of both indicators)", "setups"), ("SCENARIOS", "scen"),
                       ("LESSONS (old mistakes)", "lessons"), ("BEST / WORST SITUATIONS", "insights")):
        L += [f"== {title} ==", _jd(view.get(key), 3500), ""]
    trades = sorted(data.get("trades") or [], key=lambda t: t.get("t", 0), reverse=True)[:limit_trades]
    L.append(f"== TRADES (newest first, {len(trades)} of {len(data.get('trades') or [])}) ==")
    for t in trades:
        net = t.get("net") if t.get("status") in ("closed", "skipped_done") else t.get("live")
        usdt = "-" if net is None else f"{_mg(t) * net / 100.0:+.2f} USDT ({net:+.1f}% of margin)"
        path = "; ".join(f"{_ts(a)} stop {_px(b)}" for a, b in (t.get("path") or [])) or "stop never moved"
        try:
            scn = _scenario(t)
            w1, w2 = _what(t)
        except Exception:
            scn, w1, w2 = "", "", ""
        L += [f"- {t.get('s')} {t.get('f')} {'LONG' if t.get('d', 1) > 0 else 'SHORT'} from {t.get('src')} | status {t.get('status')} | taken={t.get('take')} ({t.get('mode')}, model expected {t.get('pred')})",
              f"  signal candle closed {_ts(t.get('t'))} | entry {_px(t.get('entry'))} | first stop {_px(t.get('sl'))} | TP1-4 {', '.join(_px(x) for x in (t.get('tps') or []))}",
              f"  exit rule: {t.get('exit')} | ended by: {t.get('end') or '-'} at {_px(t.get('xpx'))} {('on ' + _ts(t.get('xt'))) if t.get('xt') else ''} | candles in trade: {t.get('bars') if t.get('bars') is not None else t.get('lbars', '-')} | TPs hit: {t.get('hit', '-')}",
              f"  result: {usdt} | label: {t.get('label') or '-'} {t.get('reason') or ''}",
              f"  stop path: {path}", f"  situation: {scn}", f"  what happened: {w1} {w2}", f"  why taken: {t.get('why')}",
              f"  tags: {_jd(t.get('tg'), 1200)}"]
        mem = t.get("mem")
        if isinstance(mem, dict) and mem.get("text"):
            L.append(f"  memory: {mem['text']}")
    return "\n".join(L) + "\n"


def save_report():
    """Writes the report into the phone Download folder (same way as the other reports). -> {ok, path, bytes, hint}"""
    text = build_report()
    name = "owl_dualbot_report_" + time.strftime("%Y%m%d_%H%M") + ".txt"
    try:
        from recovered_bot import ai_report
        dirs = ai_report._download_dirs()
    except Exception:
        dirs = []
    for d in dirs:
        try:
            if os.path.isdir(d) and os.access(d, os.W_OK):
                path = os.path.join(d, name)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                return {"ok": True, "path": path, "bytes": len(text.encode("utf-8")), "hint": ""}
        except Exception:
            continue
    try:
        path = _p(name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        path = ""
    return {"ok": False, "path": path, "bytes": len(text.encode("utf-8")),
            "hint": "Phone Download folder is not reachable from Termux. Run  termux-setup-storage  once in Termux, allow storage, then press Download again."}


def _state_of(view, enabled, running, alive, pulse_age):
    """One plain word + sentence for the app: stopped / starting / busy / loading / running / error."""
    prog = str(view.get("progress") or "")
    if not enabled:
        return "stopped", "Stopped. Tap Start to run it again."
    if view.get("error") and not running and not alive:
        return "error", "Not running. See the red line below."
    if alive and not running:
        return "busy", "Busy: reading old candles (can take a few minutes on a phone). It is alive, nothing to do."
    if running and prog.startswith("loading history"):
        return "loading", "Loading history... " + prog.replace("loading history ", "")
    if running:
        return "running", "Running"
    return "starting", "Starting up. The backend starts it by itself, give it about a minute."


def status():
    view = _load("dual_lab_view.json", {})
    ctl = _load("dual_lab_ctl.json", {"enabled": True})
    age = time.time() - float(view.get("beat") or 0) if view.get("beat") else None
    pulse = _load("dual_lab_pulse.json", {})
    pulse_age = time.time() - float(pulse.get("t") or 0) if pulse.get("t") else None
    alive = pulse_age is not None and pulse_age < PULSE_S * 3          # the process itself is alive (even if the main loop is busy)
    view.setdefault("margin", MARGIN)
    view.setdefault("lev", LEV)
    view["enabled"] = bool(ctl.get("enabled", True))
    view["running"] = age is not None and age < BEAT_STALE_S
    view["alive"] = bool(alive)
    view["age_s"] = int(age) if age is not None else None
    view["log_tail"] = _log_tail()
    try:
        _live_overlay(view)
    except Exception:
        pass
    if view["enabled"] and not view["running"] and not alive and not view.get("error"):
        if _SPAWN.get("err"):
            view["error"] = _SPAWN["err"]
        elif _SPAWN["t"] and time.time() - _SPAWN["t"] > 25:
            view["error"] = "The worker was started but sends no heartbeat. Last log: " + (view["log_tail"] or "(empty)")
    st, txt = _state_of(view, view["enabled"], view["running"], alive, pulse_age)
    view["state"], view["state_text"] = st, txt
    return view


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        try:
            sys.exit(worker() or 0)
        except SystemExit:
            raise
        except BaseException as e:                   # a crash before the loop: say it in the log AND in the app
            import traceback
            traceback.print_exc()
            try:
                _save("dual_lab_view.json", {"enabled": True, "beat": 0, "progress": "", "rows": 0,
                                             "error": f"Worker crashed: {type(e).__name__}: {str(e)[:140]}"})
            except Exception:
                pass
            sys.exit(1)
    print(json.dumps(status())[:2000])
