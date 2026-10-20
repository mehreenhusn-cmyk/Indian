"""
ai_observer.py - "Agar AI bot ke HAR trade ko khud manage karta, to kya hota?"

Simple words
------------
* The bot takes a trade. The AI does NOT open a second trade. It WATCHES the same trade
  (same entry, same SL, same TP1-TP4 - nothing can differ) and we already save the whole journey of
  every bot trade (ai_path_logger: price path + SD width/mean + EMA slope after entry).
* Here that saved journey is REPLAYED under several exit rules (one engine, many rules):

    BOT    what the bot really does: SL, SL moves to entry after TP1, close at TP4   (the control)
    T1     close everything at TP1
    T2     close everything at TP2
    T3     close everything at TP3
    DYN4   TP levels FOLLOW the live SD bands (mean +/- n x SD, re-computed on every closed candle)
           instead of staying where they were at signal time. Hold to the shifted TP4.
    DYN2   same, but close at the shifted TP2
    ADAPT  hold like the bot; after TP1, leave at market as soon as the SD ballooned (>= 1.3x its
           entry width) or the EMA50 slope turned against the trade

  Also: "Entry vs Exit" - how many trades never reached TP1 (entry/SL side) vs trades that reached TP1
  and still lost (exit side). The AI never assumes "entry is perfect"; the numbers say it.

Honest rules (so nobody fools himself):
  - The BOT replay is the control. It is compared with what the bot REALLY got (fidelity). If the
    control does not match reality, the other numbers are shown with a warning.
  - Inside one 15 s sample the order of low and high is unknown -> the STOP is checked first (pessimistic).
  - A rule is called CLEAR only if it beats the bot in BOTH the older 60% and the newer 40% of trades
    and enough trades exist. Otherwise MAYBE (watch) / SAME / WORSE. No rule is changed because of one trade.
  - Fixed numbers (1.3x, slope eps) are NOT tuned on the data, so they cannot be over-fitted.
  - Replay, not live trading: no slippage, trades end when the bot's trade ended.

READ-ONLY. Never opens/closes/changes a bot trade. Never raises. Result is cached until a new
trade path is saved; heavy loops yield the CPU so the price feed / app never stalls.
"""
import threading
import time

SPLIT = 0.6                # oldest 60% = discovery, newest 40% = re-check (same as ai_miner)
MIN_ALL = 30               # trades before any verdict
MIN_CLEAR = 40             # trades before a rule can be CLEAR
MIN_NEW = 12               # trades in the newer part
MIN_GAIN = 0.5             # ROI points (total per trade) a rule must beat the bot by
MIN_SCEN = 15              # trades in a scenario
MAX_TRADES = 500           # newest saved trades used (keeps the phone light)
EXPAND = 1.3               # SD width now / at entry that counts as "ballooned"
FLIP_EPS = 0.005           # % - EMA slope smaller than this is flat, not a flip
Z_DROP = 0.5               # Z (in trade direction) must fall this far from its best since entry (fixed, not tuned)
FLOOR_ROI = 1.0            # a shifted TP below this ROI % is meaningless -> the old level stays

POLICIES = (
    ("BOT", "Bot jaisa (control)"),
    ("T1", "TP1 pe poora band"),
    ("T2", "TP2 pe poora band"),
    ("T3", "TP3 pe poora band"),
    ("DYN4", "TP SD ke saath shift, TP4 tak hold"),
    ("DYN2", "TP SD ke saath shift, TP2 pe band"),
    ("ADAPT", "TP1 ke baad SD phoole/EMA ulta to nikal"),
    ("IND", "TP1 ke baad TSI ulta + Z wapas to nikal"),
    ("ALL", "SD + EMA + TSI + Z me se koi bhi warning to nikal"),
    ("STEP1", "Step trail: stop follows one TP behind (TP1: entry, TP2: TP1, TP3: TP2), close at TP4"),
    ("STEP2", "Slow trail: stop stays after TP1, moves to entry after TP2, to TP1 after TP3, close at TP4"),
)
TRAIL_KEYS = ("STEP1", "STEP2")      # trailing tests: shown only in the Overview "Trailing test" card, not in Bot vs AI
NAME = dict(POLICIES)
NEEDS = {"DYN4": ("has_sd",), "DYN2": ("has_sd",), "ADAPT": ("has_sd", "has_slope"),
         "IND": ("has_ind",), "ALL": ("has_ind",)}       # rule -> saved data it can use (any one counts)
DATA_NAME = {"has_sd": "SD band path", "has_slope": "EMA50 slope path", "has_ind": "TSI + Z path"}


def _have(rows, key):
    """How many replayed trades carry the saved data rule `key` needs (None = needs nothing)."""
    need = NEEDS.get(key)
    if not need:
        return None
    return sum(1 for r in rows if any(r.get(f) for f in need))

_lock = threading.Lock()
_cache = {"key": None, "t": 0.0, "v": None}


def _f(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def _cfg(name, default):
    try:
        from . import settings_store
        v = settings_store.get(name, default)
        return default if v is None else v
    except Exception:
        return default


# ------------------------------------------------------------------ one trade, one rule
def _prep(rec):
    """Facts of one saved trade the replay needs. None = trade cannot be replayed."""
    lv = rec.get("levels") or {}
    sl = lv.get("sl")
    tps = [lv.get(f"tp{n}") for n in (1, 2, 3, 4)]
    s = rec.get("s") or []
    if sl is None or tps[0] is None or len(s) < 2:
        return None
    tps = [t if t is not None else tps[0] for t in tps]
    buy = rec.get("action") != "SELL"
    sgn = 1.0 if buy else -1.0
    lev = _f(rec.get("lev"), 1.0) or 1.0
    entry = _f(rec.get("entry"))
    sd = [x for x in (rec.get("sd") or []) if len(x) >= 4]
    sd0 = rec.get("sd0") or {}
    w0 = _f(sd0.get("w")) or (_f(sd[0][1]) if sd else 0.0)
    mean0 = _f(sd0.get("mean")) or (_f(sd[0][2]) if sd else 0.0)
    std0 = _f(sd0.get("std")) or (w0 / 100.0 * mean0 if w0 and mean0 else 0.0)
    mult = None                       # TP1..TP4 as SD multiples at signal time (read from the saved prices)
    if entry > 0 and mean0 > 0 and std0 > 0:
        mult = []
        for r in tps:
            price = entry * (1.0 + sgn * r / (100.0 * lev))
            mult.append((price - mean0) / std0)
    return {"sl": sl, "tps": tps, "s": s, "sgn": sgn, "lev": lev, "entry": entry, "sd": sd, "w0": w0,
            "mult": mult, "slope": [x for x in (rec.get("slope") or []) if len(x) >= 2],
            "slope0": rec.get("slope0"),
            "ind": [x for x in (rec.get("ind") or []) if len(x) >= 4], "final": _f(rec.get("roi_final"))}


def _dyn_tps(p, sdrow):
    """TP1..TP4 as ROI % when the SD bands are where the LAST closed candle put them."""
    if not p["mult"] or not sdrow:
        return p["tps"]
    w, mean = _f(sdrow[1]), _f(sdrow[2])
    if w <= 0 or mean <= 0 or p["entry"] <= 0:
        return p["tps"]
    std = w / 100.0 * mean
    out = []
    for m, static in zip(p["mult"], p["tps"]):
        price = mean + m * std
        roi = p["sgn"] * (price - p["entry"]) / p["entry"] * 100.0 * p["lev"]
        out.append(roi if roi >= FLOOR_ROI else static)       # a target behind the entry is not a target
    return out


def _trail_stop(kind, sl, tps, lvl):
    """Stop (ROI %) of the two trailing tests after `lvl` of TP1..TP3 were touched (TP4 = close, so never needed).
    STEP1: TP1 -> entry, TP2 -> TP1, TP3 -> TP2.   STEP2: TP1 -> same stop, TP2 -> entry, TP3 -> TP1."""
    if kind == "STEP1":
        floor = (None, 0.0, tps[0], tps[1])[lvl]
    else:
        floor = (None, None, 0.0, tps[0])[lvl]
    return sl if floor is None else max(sl, floor)


def run(p, kind):
    """Replay one prepared trade under rule `kind` -> (exit ROI %, GROSS, minutes)."""
    tgt = {"BOT": 4, "T1": 1, "T2": 2, "T3": 3, "DYN4": 4, "DYN2": 2, "ADAPT": 4, "IND": 4, "ALL": 4,
           "STEP1": 4, "STEP2": 4}[kind]
    dyn = kind in ("DYN4", "DYN2")
    sd, slope = p["sd"], p["slope"]
    ind = p["ind"]
    isd = isl = ii = -1                # newest SD / slope / indicator bar already visible at this sample
    zbest = None                       # best Z (in trade direction) seen since entry
    be = False
    lvl = 0                            # how many of TP1..TP3 the price has touched (a trailing stop moves from the NEXT sample)
    for t, roi, lo, hi in p["s"]:
        while isd + 1 < len(sd) and _f(sd[isd + 1][0]) <= t:
            isd += 1
        while isl + 1 < len(slope) and _f(slope[isl + 1][0]) <= t:
            isl += 1
        while ii + 1 < len(ind) and _f(ind[ii + 1][0]) <= t:
            ii += 1
            zz = _f(ind[ii][1]) * p["sgn"]
            zbest = zz if zbest is None else max(zbest, zz)
        tps = _dyn_tps(p, sd[isd] if isd >= 0 else None) if dyn else p["tps"]
        if kind in TRAIL_KEYS:
            stop = _trail_stop(kind, p["sl"], tps, lvl)
        else:
            stop = max(p["sl"], 0.0) if be else p["sl"]
        if lo <= stop:
            return stop, t / 60.0
        if hi >= tps[tgt - 1]:
            return tps[tgt - 1], t / 60.0
        if hi >= tps[0]:
            be = True                  # SL moves to entry from the NEXT sample (same as the bot)
        while lvl < 3 and hi >= tps[lvl]:
            lvl += 1
        if kind in ("ADAPT", "IND", "ALL") and be:
            ind_warn = False
            if ii >= 0 and zbest is not None:
                tsi_against = (_f(ind[ii][2]) - _f(ind[ii][3])) * p["sgn"] < 0
                z_fell = zbest - _f(ind[ii][1]) * p["sgn"] >= Z_DROP
                ind_warn = tsi_against and z_fell        # BOTH indicators warn, not just one
            if kind == "IND":
                if ind_warn:
                    return roi, t / 60.0
                continue
            ballooned = isd >= 0 and p["w0"] > 0 and _f(sd[isd][1]) >= EXPAND * p["w0"]
            flipped = False
            if isl >= 0 and p["slope0"] is not None:
                k = p["sgn"]
                flipped = _f(slope[isl][1]) * k < -FLIP_EPS
            if ballooned or flipped or (kind == "ALL" and ind_warn):
                return roi, t / 60.0
    return p["final"], p["s"][-1][0] / 60.0


# ------------------------------------------------------------------ the whole book
def _fee(rec, default):
    f = _f(rec.get("fee"))
    return f if f > 0 else default


def _usdt_index():
    """{(id, opened second): invest USDT} from the permanent archive, to show money next to ROI %."""
    out = {}
    try:
        from . import trade_store
        for t in trade_store.get_all_closed(5000, net=False):
            try:
                out[(str(t.get("id")), int(float(t.get("opened_at_ts") or 0)))] = float(t.get("invest_usdt") or 0.0)
            except Exception:
                continue
    except Exception:
        pass
    return out


def _entry_state(p):
    """Facts known AT ENTRY (usable for a rule, no hindsight): side, SD size, EMA slope direction."""
    out = {"side": "BUY" if p["sgn"] > 0 else "SELL"}
    if p["slope0"] is not None:
        v = _f(p["slope0"]) * p["sgn"]
        out["slope"] = "EMA slope WITH trade" if v > FLIP_EPS else ("EMA slope AGAINST trade" if v < -FLIP_EPS else "EMA slope flat")
    return out


def _avg(v):
    return sum(v) / len(v) if v else 0.0


def _verdict(diff_old, diff_new, n, n_new, avg_gain):
    if avg_gain < MIN_GAIN:
        return "WORSE" if avg_gain <= -MIN_GAIN else "SAME"
    if diff_old > 0 and diff_new > 0 and n >= MIN_CLEAR and n_new >= MIN_NEW:
        return "CLEAR"
    return "MAYBE"


def _compare(rows, kind, cut):
    """Rule `kind` vs the bot replay on a list of rows (each has 'net' per rule)."""
    d = [r["net"][kind] - r["net"]["BOT"] for r in rows]
    old, new = d[:cut], d[cut:]
    return {"avg_gain": _avg(d), "total_gain": sum(d), "old": _avg(old), "new": _avg(new), "n_new": len(new)}


def _summary(rows, usdt_on):
    out = []
    cut = int(len(rows) * SPLIT)
    for key, name in POLICIES:
        nets = [r["net"][key] for r in rows]
        c = _compare(rows, key, cut)
        item = {"key": key, "name": name, "n": len(rows), "avg": round(_avg(nets), 2), "total": round(sum(nets), 1),
                "wr": round(sum(1 for x in nets if x > 0) / len(nets) * 100.0, 1) if nets else 0.0,
                "gain_total": round(c["total_gain"], 1), "gain_avg": round(c["avg_gain"], 2),
                "gain_old": round(c["old"], 2), "gain_new": round(c["new"], 2)}
        if usdt_on:
            item["usdt"] = round(sum(r["inv"] * r["net"][key] / 100.0 for r in rows if r["inv"] > 0), 2)
        item["verdict"] = "CONTROL" if key == "BOT" else _verdict(c["old"], c["new"], len(rows), c["n_new"], c["avg_gain"])
        have = _have(rows, key)
        if have is not None:
            item["have"] = have
            if have < MIN_ALL:                  # not enough saved data: this rule is a copy of the bot so far -> no verdict
                item["verdict"] = "COLLECTING"
                item["need"] = MIN_ALL
        out.append(item)
    return out


def _entry_vs_exit(rows):
    """Where does the money go? never reached TP1 (entry / SL side) vs reached TP1 and still lost (exit side)."""
    never = [r for r in rows if not r["tp1"]]
    reached = [r for r in rows if r["tp1"]]
    gave_back = [r for r in reached if r["net"]["BOT"] <= 0]
    kept = [r for r in reached if r["net"]["BOT"] > 0]
    n = len(rows)
    s = lambda rs: round(sum(r["net"]["BOT"] for r in rs), 1)       # noqa: E731
    out = {"n": n, "tp1_pct": round(len(reached) / n * 100.0, 1) if n else 0.0,
           "never": {"n": len(never), "sum": s(never),
                     "peak": round(_avg([r["peak"] for r in never]), 1)},
           "gave_back": {"n": len(gave_back), "sum": s(gave_back)},
           "kept": {"n": len(kept), "sum": s(kept)}}
    loss_entry, loss_exit = -min(out["never"]["sum"], 0.0), -min(out["gave_back"]["sum"], 0.0)
    tot = loss_entry + loss_exit
    out["blame"] = "unknown"
    if n < MIN_ALL:
        out["msg"] = f"Abhi {n} trade ka journey mila. {MIN_ALL}+ ho to entry vs exit ka faisla dikhega."
    elif out["tp1_pct"] < 40 and tot > 0 and loss_entry >= 0.6 * tot:
        out["msg"] = (f"Sirf {out['tp1_pct']:.0f}% trade TP1 tak pahunchte hain. Nuksaan ka bada hissa wahi hai jo "
                      "TP1 tak gaye hi nahi: entry/SL side ki problem. Sirf exit badalne se ye theek nahi hoga.")
        out["blame"] = "entry"
    elif tot > 0 and loss_exit >= 0.5 * tot:
        out["msg"] = (f"{out['tp1_pct']:.0f}% trade TP1 tak pahunche, par kaafi wapas haare: exit side ki problem. "
                      "Alag exit rule yahan kaam kar sakta hai.")
        out["blame"] = "exit"
    else:
        out["msg"] = (f"{out['tp1_pct']:.0f}% trade TP1 tak pahunche. Nuksaan entry aur exit dono se mix hai, "
                      "ek taraf pakka nahi.")
    return out


def _scenarios(rows):
    """Per situation known at ENTRY: which rule beat the bot, and does it hold in old AND new trades."""
    groups = {}
    for r in rows:
        for k, v in r["state"].items():
            groups.setdefault(v, []).append(r)
    ws = sorted(r["w0"] for r in rows if r["w0"] > 0)
    if len(ws) >= 9:
        a, b = ws[len(ws) // 3], ws[2 * len(ws) // 3]
        for r in rows:
            if r["w0"] > 0:
                lab = "SD narrow at entry" if r["w0"] < a else ("SD mid at entry" if r["w0"] < b else "SD wide at entry")
                groups.setdefault(lab, []).append(r)
    out = []
    for label, rs in groups.items():
        if len(rs) < MIN_SCEN:
            continue
        cut = int(len(rs) * SPLIT)
        best, bc = None, None
        for key, _n in POLICIES[1:]:
            if key in TRAIL_KEYS:
                continue                              # trailing tests live in the Overview card only
            if (_have(rows, key) or MIN_ALL) < MIN_ALL:
                continue                          # still collecting its data
            c = _compare(rs, key, cut)
            if bc is None or c["avg_gain"] > bc["avg_gain"]:
                best, bc = key, c
        if best is None:
            continue
        v = _verdict(bc["old"], bc["new"], len(rs), bc["n_new"], bc["avg_gain"])
        bot_avg = _avg([r["net"]["BOT"] for r in rs])
        if v in ("SAME", "WORSE"):
            msg = "Yaha bot jaisa hold theek hai."
        else:
            msg = f"Yaha '{NAME[best]}' behtar: avg {bot_avg + bc['avg_gain']:+.1f}% vs bot {bot_avg:+.1f}%."
            if v == "MAYBE":
                msg += " Abhi pakka nahi."
        out.append({"label": label, "n": len(rs), "best": best, "best_name": NAME[best], "bot_avg": round(bot_avg, 2),
                    "gain": round(bc["avg_gain"], 2), "verdict": v, "msg": msg})
    order = {"CLEAR": 0, "MAYBE": 1, "SAME": 2, "WORSE": 3}
    out.sort(key=lambda x: (order[x["verdict"]], -x["gain"]))
    return out[:8]


_memo = {}                 # (trade key, fee) -> replayed row. A closed trade never changes, so it is replayed ONCE.


def _one(rec, fee_default):
    """Replay one saved trade under every rule -> row (or None). Result is memoised."""
    k = (rec.get("key"), fee_default)
    if k in _memo:
        return _memo[k]
    row = None
    try:
        p = _prep(rec)
        if p:
            dur = max(1.0, _f(p["s"][-1][0]))
            if _f(rec.get("gaps")) <= 0.1 * dur:             # long price gaps: the journey is not trustworthy
                fee = _fee(rec, fee_default)
                gross = {kk: run(p, kk)[0] for kk, _n in POLICIES}
                peak = max(_f(x[3]) for x in p["s"])
                row = {"t": _f(rec.get("opened_ts")), "net": {kk: v - fee for kk, v in gross.items()},
                       "actual": p["final"] - fee, "tp1": peak >= p["tps"][0], "peak": peak, "w0": p["w0"],
                       "state": _entry_state(p), "has_ind": bool(p["ind"]), "has_sd": bool(p["sd"]),
                       "has_slope": bool(p["slope"]), "sym": rec.get("symbol")}
    except Exception:
        row = None
    if rec.get("key") is not None:
        if len(_memo) > 3 * MAX_TRADES:
            _memo.clear()
        _memo[k] = row
    return row


def replay_all(paths, fee_default, inv=None):
    """paths: {key: saved path record} -> list of per-trade results, oldest first. Yields the CPU often."""
    rows = []
    recs = sorted(paths.values(), key=lambda r: _f(r.get("opened_ts")))[-MAX_TRADES:]
    for i, rec in enumerate(recs):
        fresh = (rec.get("key"), fee_default) not in _memo
        base = _one(rec, fee_default)
        if base is not None:
            ik = (str(rec.get("id")), int(_f(rec.get("opened_ts"))))
            rows.append(dict(base, inv=(inv or {}).get(ik, 0.0)))
        if fresh and i % 4 == 3:
            time.sleep(0.003)                                # let the price feed / REST breathe
    return rows


def _fidelity(rows):
    err = [abs(r["net"]["BOT"] - r["actual"]) for r in rows]
    if not err:
        return {"n": 0, "err": 0.0, "close_pct": 0.0, "ok": False}
    close = sum(1 for e in err if e <= 1.5)
    return {"n": len(err), "err": round(_avg(err), 2), "close_pct": round(close / len(err) * 100.0, 1),
            "ok": close / len(err) >= 0.7}


def build_from(rows):
    """Everything the screen needs from replayed rows (also used by the tests)."""
    n = len(rows)
    usdt_on = any(r["inv"] > 0 for r in rows)
    out = {"ts": time.time(), "n": n, "status": "OK" if n >= MIN_ALL else "TOO_FEW", "policies": [], "entry_exit": {},
           "scenarios": [], "fidelity": _fidelity(rows), "headline": "", "names": NAME,
           "ind_n": sum(1 for r in rows if r.get("has_ind")),
           "caveats": ["Replay hai, live trading nahi: slippage nahi, trade wahi tak jahan bot ka trade chala.",
                       "AI ne koi alag trade nahi li: wahi entry, wahi SL, wahi TP. Sirf exit rule alag chalaye gaye.",
                       "Ek rule tabhi 'pakka' jab purane aur naye dono trades me bot se behtar ho.",
                       "TSI/Z ka path sirf naye trades ka hai (jo tracker chalne ke baad khule). Purane trades par TSI/Z wale rules bot jaisa hi chalte hain."]}
    if not n:
        out["headline"] = "Abhi koi band trade ka journey save nahi hua. Bot trade karta rahe, AI dekhta rahega."
        return out
    out["policies"] = _summary(rows, usdt_on)
    out["collect"] = [{"key": k, "name": DATA_NAME[k], "have": sum(1 for r in rows if r.get(k)), "need": MIN_ALL}
                      for k in ("has_sd", "has_slope", "has_ind")]
    out["entry_exit"] = _entry_vs_exit(rows)
    if n >= MIN_SCEN:
        out["scenarios"] = _scenarios(rows)
    pol = {p["key"]: p for p in out["policies"]}
    bot = pol["BOT"]
    if n < MIN_ALL:
        out["headline"] = f"Abhi {n} trade ka journey hai. {MIN_ALL}+ ho to rules ka hisaab dikhega."
        return out
    ready = [p for p in out["policies"][1:] if p["verdict"] != "COLLECTING" and p["key"] not in TRAIL_KEYS]
    best = max(ready, key=lambda p: p["gain_total"]) if ready else bot
    clear = [p for p in out["policies"] if p["verdict"] == "CLEAR" and p["key"] not in TRAIL_KEYS]
    if clear:
        c = max(clear, key=lambda p: p["gain_total"])
        out["headline"] = (f"{n} trade me '{c['name']}' bot se {c['gain_total']:+.0f}% ROI aage, "
                           "purane aur naye dono hisse me. Pakka dikha.")
    elif best["gain_total"] >= MIN_GAIN * n:
        out["headline"] = (f"{n} trade me '{best['name']}' bot se {best['gain_total']:+.0f}% ROI aage dikha, "
                           "par purane/naye dono me pakka nahi. Dekhte raho.")
    else:
        blame = {"entry": " Nuksaan zyada entry/SL side ka lagta hai.", "exit": " Nuksaan zyada exit side ka lagta hai."}
        out["headline"] = (f"{n} trade me koi exit rule bot se pakka behtar nahi nikla "
                           f"(bot total {bot['total']:+.0f}%)." + blame.get(out["entry_exit"].get("blame"), ""))
    if not out["fidelity"]["ok"]:
        out["headline"] += " Dhyan: control replay asli result se poora match nahi hua, numbers andaza hain."
    return out


def build():
    """Screen data. Cached until a new trade path is saved (or 5 min). Never raises."""
    try:
        from . import ai_path_logger
        paths = ai_path_logger.load_paths()
        key = (len(paths), max((_f(r.get("closed_ts")) for r in paths.values()), default=0.0))
        with _lock:
            if _cache["key"] == key and _cache["v"] is not None and time.time() - _cache["t"] < 300:
                return _cache["v"]
        fee = max(0.0, _f(_cfg("fee_roi_pct", 1.0), 1.0))
        out = build_from(replay_all(paths, fee, _usdt_index()))
        with _lock:
            _cache.update(key=key, t=time.time(), v=out)
        return out
    except Exception as e:
        return {"ts": time.time(), "n": 0, "status": "ERROR", "policies": [], "entry_exit": {}, "scenarios": [],
                "headline": "", "error": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------------ trade diary (one line per trade, plain words)
def _lesson(row):
    """One plain sentence: what happened in this trade and what another exit would have given."""
    bot, peak = row["rules"]["BOT"], row["peak"]
    best, bv = row["best"], row["rules"][row["best"]]
    if not row["tp"][0]:
        if peak > 0.5:
            return f"Profit me gaya (peak {peak:+.1f}%) par TP1 se pehle palta. TP1 tak pahunchi hi nahi: entry/SL side."
        return "Entry ke baad seedha ulta gaya, kabhi profit me nahi aaya: entry/SL side ki problem."
    if bot <= 0:
        extra = f" {NAME.get(best, best)} hota to {bv:+.1f}%." if bv > bot + MIN_GAIN else ""
        return f"TP1 chhua (peak {peak:+.1f}% {row['peak_min']:.0f} min me) phir wapas haara: exit/booking side.{extra}"
    extra = f" {NAME.get(best, best)} me {bv:+.1f}% hota." if bv > bot + 2 * MIN_GAIN else ""
    return f"Theek raha: bot {bot:+.1f}% (peak {peak:+.1f}%).{extra}"


def diary(limit=40):
    """Per-trade diary for the /diary page: newest closed trades with the AI's replay under every rule, plus the
    OPEN trades (peak vs now = booking alert). Read-only, never raises."""
    try:
        from . import ai_path_logger
        fee_d = max(0.0, _f(_cfg("fee_roi_pct", 1.0), 1.0))
        recs = sorted(ai_path_logger.load_paths().values(), key=lambda r: _f(r.get("closed_ts")))[-int(limit):]
        rows = []
        for rec in reversed(recs):
            p = _prep(rec)
            if not p:
                continue
            fee = _fee(rec, fee_d)
            rules = {k: round(run(p, k)[0] - fee, 2) for k, _n in POLICIES}
            peak = max(_f(x[3]) for x in p["s"])
            tpk = max(p["s"], key=lambda x: _f(x[3]))
            row = {"sym": rec.get("symbol"), "side": "BUY" if p["sgn"] > 0 else "SELL", "opened": _f(rec.get("opened_ts")),
                   "closed": _f(rec.get("closed_ts")), "reason": rec.get("reason"), "roi": round(p["final"] - fee, 2),
                   "peak": round(peak, 2), "peak_min": round(_f(tpk[0]) / 60.0, 1), "low": round(min(_f(x[2]) for x in p["s"]), 2),
                   "tp": [peak >= t for t in p["tps"]], "rules": rules,
                   "has": {"sd": bool(p["sd"]), "slope": bool(p["slope"]), "ind": bool(p["ind"])}}
            row["best"] = max((k for k in rules if k not in TRAIL_KEYS), key=lambda k: rules[k])
            row["lesson"] = _lesson(row)
            rows.append(row)
        open_rows = []
        for o in ai_path_logger.open_snapshot():
            lv = o.get("levels") or {}
            peak, now = _f(o.get("peak")), _f(o.get("now"))
            tp1 = lv.get("tp1")
            hit1 = tp1 is not None and peak >= tp1
            gave = peak - now
            alert = ""
            if hit1 and gave >= max(2.0, 0.5 * peak):
                alert = f"Booking alert: peak {peak:+.1f}% tha, ab {now:+.1f}%. {gave:.1f} point wapas gaya."
            elif hit1:
                alert = f"TP1 chhua (peak {peak:+.1f}%), abhi {now:+.1f}%."
            open_rows.append({"sym": o.get("symbol"), "side": o.get("action"), "now": round(now, 2), "peak": round(peak, 2),
                              "low": round(_f(o.get("low")), 2), "tp1": hit1, "alert": alert,
                              "opened": _f(o.get("opened_ts")), "ind": o.get("n_ind", 0)})
        losers = [r for r in rows if r["roi"] <= 0]
        pos_losers = [r for r in losers if r["peak"] > 0.5]
        n = len(rows)
        head = "Abhi koi band trade ka journey nahi hai." if not n else (
            f"Pichle {n} trade me {sum(1 for r in rows if r['tp'][0])} TP1 tak gaye. {len(losers)} haare, unme se "
            f"{len(pos_losers)} pehle profit me the (avg peak {_avg([r['peak'] for r in pos_losers]):+.1f}%) phir wapas haare.")
        return {"ts": time.time(), "n": n, "headline": head, "rows": rows, "open": open_rows, "names": NAME}
    except Exception as e:
        return {"ts": time.time(), "n": 0, "headline": "", "rows": [], "open": [], "error": f"{type(e).__name__}: {e}"}
