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
        data["rows"][key] = [sym, tf, r["t"], r["d"], tg_list, [round(r["x"][n][0], 2) for n in exit_names]]
        added += 1
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
            tr["net"], tr["end"], tr["bars"] = round(r["net"], 2), r["why"], r["bars"]
            tr["status"] = "closed" if tr["take"] else "skipped_done"
            tr["closed_at"] = time.time()
        else:
            lv = TL.sim_rule(S, Z, i, tr["d"], tr["entry"], tr["sl"], tr["tps"], LEV, FEE, allow_open=True, **rule)
            tr["live"] = round(lv["net"], 2) if lv else None
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
        data["trades"].append({
            "id": key, "s": sym, "f": tf, "ct": e["ct"], "t": e["t"], "d": e["d"], "src": e["src"], "entry": e["entry"],
            "sl": e["sl"], "tps": e["tps"], "exit": exit_names[xi], "take": take, "mode": mode, "pred": pred, "why": why,
            "status": "open" if take else "skipped", "opened": time.time(), "tg": e["tg"]})
    return added


def trim(data):
    if len(data["rows"]) > MAX_ROWS:
        keep = sorted(data["rows"].items(), key=lambda kv: kv[1][2])[-MAX_ROWS:]
        data["rows"] = dict(keep)
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


def summary(data, model, exit_names):
    tr = data["trades"]
    closed = [t for t in tr if t["status"] == "closed"]
    opens = [t for t in tr if t["status"] == "open"]
    skipped_done = [t for t in tr if t["status"] == "skipped_done"]
    pnl = lambda t: MARGIN * (t.get("net") or 0.0) / 100.0
    by_src = {}
    for t in closed:
        s = by_src.setdefault(t["src"], {"n": 0, "wins": 0, "pnl": 0.0})
        s["n"] += 1
        s["wins"] += 1 if (t.get("net") or 0) > 0 else 0
        s["pnl"] += pnl(t)
    return {
        "closed": len(closed), "wins": sum(1 for t in closed if (t.get("net") or 0) > 0),
        "pnl": round(sum(pnl(t) for t in closed), 2), "open": len(opens),
        "open_pnl": round(sum(MARGIN * (t.get("live") or 0.0) / 100.0 for t in opens), 2),
        "skipped_done": len(skipped_done), "skipped_pnl": round(sum(pnl(t) for t in skipped_done), 2),
        "skipped_open": sum(1 for t in tr if t["status"] == "skipped"),
        "by_src": {k: {"n": v["n"], "wins": v["wins"], "pnl": round(v["pnl"], 2)} for k, v in by_src.items()},
    }


def slim(t):
    return {"s": t["s"], "f": t["f"], "d": t["d"], "src": t["src"], "exit": t["exit"], "mode": t["mode"], "why": t["why"],
            "status": t["status"], "net": t.get("net"), "live": t.get("live"), "end": t.get("end"), "bars": t.get("bars"),
            "t": t["t"], "entry": t["entry"], "sl": t["sl"]}


def make_view(data, model, ins, exit_names, progress, err, enabled):
    tr = sorted(data["trades"], key=lambda t: t["t"], reverse=True)
    mv = None
    if model:
        mv = {"mode": model["mode"], "rows": model["rows"], "val": model["val"],
              "best_exit": exit_names[model["best_exit"]]}
    return {"enabled": enabled, "beat": time.time(), "model": mv, "rows": len(data["rows"]), "summary": summary(data, model, exit_names),
            "insights": ins, "recent": [slim(t) for t in tr[:40]], "progress": progress, "error": err,
            "margin": MARGIN, "lev": LEV, "started": data.get("started")}


# ---------------------------------------------------------------- the worker (own process)
def _lock():
    try:
        import fcntl
        fd = os.open(_p("dual_lab.lock"), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except Exception:
        return None


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
            st["err"] = f"coin list: {type(e).__name__}"
    coins = list(dict.fromkeys(st.get("coins", []) + [t["s"] for t in data["trades"] if t["status"] in ("open", "skipped")]))
    done = 0
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
                continue
            process(data, sym, tf, candles, boot, now_ms, st.get("model"), exit_names)
            data["fetched"][key] = latest
            if boot:
                data["boot"][key] = 1
            done += 1
            time.sleep(0.05)
    return done


def worker():
    lock = _lock()
    if lock is None:
        print("dual_lab: already running", flush=True)
        return 0
    try:
        os.nice(10)
    except Exception:
        pass
    import filter_lab as FL
    from recovered_bot import ai_shadow_lab as LAB
    TL = _tl()
    exit_names = list(TL.EXITS.keys())
    data = _load("dual_lab_data.json", {})
    for k, v in (("rows", {}), ("trades", []), ("seen", {}), ("boot", {}), ("fetched", {})):
        if not isinstance(data.get(k), type(v)):
            data[k] = v
    data.setdefault("started", time.time())
    st = {"model": None, "rows_at_train": -999, "train_t": 0, "ins": {"best": [], "worst": []}, "ins_t": 0}
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
                _save("dual_lab_data.json", data)
                err = st.get("err", "")
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:120]}"
        _save("dual_lab_view.json", make_view(data, st["model"], st["ins"], exit_names, st.get("progress", "") if enabled else "stopped", err, enabled))
        time.sleep(CYCLE_S if enabled else 5)


# ---------------------------------------------------------------- the backend side (reads the small view file, starts the worker)
_SPAWN = {"t": 0.0}


def set_enabled(on):
    _save("dual_lab_ctl.json", {"enabled": bool(on)})


def ensure_running():
    """Starts the worker if it is enabled and its heartbeat is stale. The lock file inside the worker stops a second copy."""
    try:
        if not _load("dual_lab_ctl.json", {"enabled": True}).get("enabled", True):
            return False
        view = _load("dual_lab_view.json", {})
        if time.time() - float(view.get("beat") or 0) < BEAT_STALE_S or time.time() - _SPAWN["t"] < 60:
            return False
        _SPAWN["t"] = time.time()
        log = open(_p("dual_lab.log"), "a", encoding="utf-8")
        kw = {"preexec_fn": (lambda: os.nice(10))} if hasattr(os, "nice") else {}
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "worker"], stdout=log, stderr=subprocess.STDOUT, cwd=HERE, **kw)
        return True
    except Exception:
        return False


def status():
    view = _load("dual_lab_view.json", {})
    ctl = _load("dual_lab_ctl.json", {"enabled": True})
    age = time.time() - float(view.get("beat") or 0) if view.get("beat") else None
    view["enabled"] = bool(ctl.get("enabled", True))
    view["running"] = age is not None and age < BEAT_STALE_S
    view["age_s"] = int(age) if age is not None else None
    return view


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        sys.exit(worker() or 0)
    print(json.dumps(status())[:2000])
