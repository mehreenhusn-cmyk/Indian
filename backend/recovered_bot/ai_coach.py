"""
ai_coach.py - the AI COACH: on EVERY bot signal the AI opens its OWN virtual trade (same entry, same SL/TP),
manages it by itself, keeps watching the price after it closes, and writes a memo of what it did and learned.

Why (user's idea): bot and AI share the entry, only the MANAGEMENT differs. The AI is allowed to make mistakes
(no LE/SKIP gate - that gate stopped it from learning). Result: Bot alone vs AI-managed, in USDT, side by side.

What the AI looks at on every CLOSED candle of its trade: ALL ~20 facts of ai_ind_features.labels() - Z zone / Z move /
Z divergence / Z vs its average line (ZSMA), TSI position / TSI vs signal / TSI zero line, SD shape and size, price vs EMA50,
momentum, phase, reversal arrow ... (relative to the trade direction, WITH / AGAINST).
It then counts what the price did over the NEXT 3 candles for EVERY single fact and EVERY PAIR of facts. We write no rule:
the AI finds on its own which situations go with the trade and which fade (page / app show the best and the worst).
  - a situation with >= MIN_N samples has a real probability  -> shown; >= EXIT_MIN_N and clearly below normal -> used to exit
  - fewer samples -> it says "jama ho raha hai n/30" and uses only a BASIC protection rule (labelled BASIC)

AI management (the only difference from the bot):
  1. PROTECT: price went >= 60% of the way to TP1 -> SL moves to entry (bot waits for TP1).
  2. INDICATOR EXIT (only while the trade is in profit): learned probability of "next 3 candles go my way" is below
     45% (LEARNED), or - while still collecting - TSI and Z are both AGAINST the trade (BASIC).
  3. Otherwise like the bot: SL at the signal candle, SL to entry after TP1, TP4 then trailing stop.
After the trade closes the AI keeps watching WATCH_BARS candles: "did price go on without me or did I exit right?"

MARGIN (real-money thinking): every trade uses the bot's fixed margin; the AI has a balance. A new signal needs a free
slot. No free margin -> the AI first closes its most useless open trade (30+ min and almost no move = sideways time waste)
to make room; if there is none, it SKIPS the new signal. Skipped signals are followed (what did the bot make on them?) and
forced closes are watched (did price go on?) so the page shows whether saving margin paid off.

Safety (same rules as the other AI modules): read-only toward the bot, own daemon thread, at most MAX_FETCH candle
downloads per cycle, own file ai/ai_coach.json, setting coach_enabled (default True), every error swallowed.
Honest limits: virtual trades open at the bot's exact entry price, no slippage; Z "green/red" here means Z rising/falling
versus the previous candle; a probability from few samples is not a promise.
"""
import os
import threading
import time

from . import ai_ind_features as F

CYCLE_S = 5.0
MAX_FETCH = 4
LOOKBACK = 330
MIN_N = 30
EXIT_MIN_N = 50
EXIT_EDGE = 0.10
MAX_KEYS = 9000
FWD_BARS = 3
WATCH_BARS = 20
PROTECT_AT = 0.6
BASIC_MIN_PROGRESS = 0.3
MAX_HOLD_S = 24 * 3600
START_AGE_S = 600
KEEP_CLOSED, KEEP_MEMO = 300, 300

_lock = threading.RLock()
_file = None
_loaded = False
_started = False
_dirty = False
_state = {"open": {}, "watch": {}, "closed": [], "memo": [], "seen": {}, "stats": {}, "pending": [], "cfg": {}, "skips": []}
_last = {"save": 0.0}
_bar_done = {}        # (sym, tf_min) -> open time (ms) of the last candle already processed


def _fm_min(m):
    """minutes -> text, over 60 min = hours + minutes (owner rule)"""
    try:
        from timefmt import mins as _fm
        return _fm(m)
    except Exception:
        return "%s min" % m


def _cfg(name, default):
    try:
        from . import settings_store
        v = settings_store.get(name, default)
        return default if v is None else v
    except Exception:
        return default


def enabled():
    return bool(_cfg("coach_enabled", True))


def init(path):
    global _file
    try:
        os.makedirs(path, exist_ok=True)
        _file = os.path.join(path, "ai_coach.json")
    except Exception as e:
        print(f"[AICoach] init: {e}")


def _mark():
    global _dirty
    _dirty = True


def _load():
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            if _file:
                from . import safe_io
                d, _src = safe_io.read_json_safe(_file, "ai_coach")
                if isinstance(d, dict):
                    for k in ("open", "watch", "seen", "stats", "cfg"):
                        if isinstance(d.get(k), dict):
                            _state[k] = d[k]
                    for k in ("closed", "memo", "pending", "skips"):
                        if isinstance(d.get(k), list):
                            _state[k] = d[k]
        except Exception as e:
            print(f"[AICoach] load: {e}")
        try:
            if not _state["cfg"].get("started"):
                sv = [float(x) for x in _state["seen"].values()]
                _state["cfg"]["started"] = min(sv) if sv else time.time()
                _mark()
        except Exception:
            pass


def _save(force=False):
    global _dirty
    with _lock:
        if not _file or not (_dirty or force):
            return
        if not force and time.time() - _last["save"] < 15:
            return
        try:
            from . import safe_io
            _state["closed"] = _state["closed"][-KEEP_CLOSED:]
            _state["memo"] = _state["memo"][-KEEP_MEMO:]
            _state["skips"] = _state["skips"][-200:]
            _state["pending"] = _state["pending"][-2000:]
            if len(_state["stats"]) > MAX_KEYS:        # keep the situations that have real counts
                _state["stats"] = {k: c for k, c in _state["stats"].items() if c[0] >= 3 or k == "ALL"}
            cut = time.time() - 3 * 86400
            _state["seen"] = {k: v for k, v in _state["seen"].items() if v >= cut}
            safe_io.write_json_atomic(_file, _state)
            _dirty = False
            _last["save"] = time.time()
        except Exception as e:
            print(f"[AICoach] save: {e}")


def _memo(sym, text):
    _state["memo"].append({"t": time.time(), "sym": sym, "text": text})
    _mark()


# ------------------------------------------------------------------ maths
def _net(raw_pct, lev, fee):
    return raw_pct * lev - fee


def _raw(side, entry, px):
    d = 1.0 if side == "BUY" else -1.0
    return (px - entry) / entry * 100.0 * d if entry else 0.0


def _dir(side):
    return 1.0 if side == "BUY" else -1.0


def _tf_min(tf):
    try:
        from . import exchange
        return int(exchange.resolve_timeframe(tf))
    except Exception:
        return 3


def _price(sym):
    """Live price WITH a one-symbol REST fallback. Only the background tick may call this (and never inside _lock):
    right after a restart the feed cache is empty and every call is a network round trip."""
    try:
        from . import market_ws
        px, _s, _e = market_ws.get_best_live_price(sym)
        return float(px) if px else None
    except Exception:
        return None


def _prices_for(syms):
    """{symbol: price}. Live feed first; for the coins the feed does not cover (AI still in a trade after the bot left)
    ONE bulk request for all prices instead of one request per coin. Never raises."""
    out = {sy: _price_cached(sy) for sy in syms}
    miss = [sy for sy, px in out.items() if not px]
    if miss:
        try:
            from . import exchange
            bulk = exchange.get_active_usdt_symbols(max_age=10.0) or {}
            for sy in miss:
                if bulk.get(sy):
                    out[sy] = float(bulk[sy])
        except Exception:
            pass
    return out


def _price_cached(sym):
    """Price from the live feed cache only. Never touches the network, so screens (build / pairs / replay) stay fast."""
    try:
        from . import market_ws
        live = market_ws.get_live(sym)
        return float(live["price"]) if live else None
    except Exception:
        return None


# ------------------------------------------------------------------ indicator facts (direction-relative)
def sd_event(S, i, side, look=5):
    """What price did at the SD levels in the last candles, relative to the trade: bounce / break / rejection."""
    try:
        d = _dir(side)
        lo_z = hi_z = None
        lo_lv = hi_lv = 0
        for j in range(max(0, i - look + 1), i + 1):
            m, sd = S["sma"][j], S["std"][j]
            if m is None or not sd:
                continue
            zl, zh = (S["l"][j] - m) / sd, (S["h"][j] - m) / sd
            if zl <= -1 and (lo_z is None or zl < lo_z):
                lo_z = zl
            if zh >= 1 and (hi_z is None or zh > hi_z):
                hi_z = zh
        zn = S["z"][i]
        if zn is None:
            return None
        if lo_z is not None:
            lo_lv = min(3, int(-lo_z))
        if hi_z is not None:
            hi_lv = min(3, int(hi_z))
        if not lo_lv and not hi_lv:
            return "no SD touch lately"
        if lo_lv >= hi_lv:                       # lower band touched (the deeper one wins)
            bounced = zn > -float(lo_lv)
            w = (d > 0) == bounced               # bounce up helps a long, break down helps a short
            return "%s -%dSD (%s trade)" % ("bounced off" if bounced else "broke", lo_lv, "WITH" if w else "AGAINST")
        bounced = zn < float(hi_lv)              # price fell back under the upper band
        w = (d < 0) == bounced
        return "%s +%dSD (%s trade)" % ("rejected at" if bounced else "broke", hi_lv, "WITH" if w else "AGAINST")
    except Exception:
        return None


def labs_of(S, i, side):
    """{kind: 'self-describing fact'} for candle i of the trade (WITH / AGAINST the trade), {} while not computable."""
    try:
        ind = F.own_features(S, i)
        out = {k: v for k, v in F.labels(side, ind, None).items() if isinstance(v, str)} if ind else {}
        if out:
            ev = sd_event(S, i, side)
            if ev:
                out["sd_event"] = ev
        return out
    except Exception:
        return {}


def _keys(labs):
    """Every table key a situation feeds: each single fact and each pair of facts."""
    items = sorted("%s=%s" % (k, v) for k, v in labs.items())
    ks = list(items)
    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            ks.append(items[a] + " & " + items[b])
    return ks


def _count(labs, fav, move):
    for k in _keys(labs) + ["ALL"]:
        c = _state["stats"].setdefault(k, [0, 0, 0.0])
        c[0] += 1
        c[1] += 1 if fav else 0
        c[2] += move
    _mark()


def prob(key):
    c = _state["stats"].get(key)
    if not c or c[0] <= 0:
        return None, 0
    return c[1] / c[0], c[0]


def _base():
    p, n = prob("ALL")
    return (p if p is not None else 0.5), n


def _nice(key):
    return key.replace("=", ": ").replace(" & ", "  +  ")


def decide_exit(labs, progress):
    """(exit?, mode, text) for a trade that is IN PROFIT. LEARNED = a situation with >= EXIT_MIN_N cases that is clearly
    worse than normal; BASIC = nothing trusted yet, only 'Z and TSI both against'."""
    base, _ = _base()
    worst, wp, wn = None, 1.0, 0
    for k in _keys(labs):
        p, n = prob(k)
        if p is not None and n >= EXIT_MIN_N and p < wp:
            worst, wp, wn = k, p, n
    if worst is not None and wp <= base - EXIT_EDGE:
        return True, "LEARNED", "In this situation (%s) the next 3 candles went with the trade only %d%% of the time (normal %d%%, %d cases). The AI exited." % (
            _nice(worst), round(wp * 100), round(base * 100), wn)
    if worst is None and labs.get("z_tsi") == "Z and TSI both AGAINST trade" and progress >= BASIC_MIN_PROGRESS:
        return True, "BASIC", "Z-score and TSI both turned against the trade (basic rule: not enough data yet). The AI exited."
    return False, "LEARNED" if worst is not None else "BASIC", ""


# ------------------------------------------------------------------ margin
SLOTS_DEFAULT = 20
SIDEWAYS_MIN, SIDEWAYS_ROI = 30, 3.0


def _balance(inv):
    b = _state["cfg"].get("balance")
    return float(b) if b else SLOTS_DEFAULT * float(inv or 0.0)


def _free(inv):
    used = sum(v["inv"] for v in _state["open"].values())
    return _balance(inv) + float(_state["cfg"].get("realized", 0.0)) - used


def _roi_now(v, px):
    fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
    return _net(_raw(v["side"], v["entry"], px), v["lev"], fee)


def pick_victim(now_px):
    """The open AI trade that wastes margin most: 30+ min old and almost no move. None if every trade is still working."""
    best, age_best = None, 0.0
    for v in _state["open"].values():
        age = (time.time() - v["t0"]) / 60.0
        px = now_px.get(v["sym"])
        if px is None or age < SIDEWAYS_MIN:
            continue
        if abs(_roi_now(v, px)) < SIDEWAYS_ROI and age > age_best:
            best, age_best = v, age
    return best


def set_balance(x):
    with _lock:
        _load()
        _state["cfg"]["balance"] = max(0.0, float(x))
        _mark()
    _save(force=True)
    return {"ok": True, "balance": _state["cfg"]["balance"]}


# ------------------------------------------------------------------ one virtual trade
def _live(kind, v, px=None, reason=""):
    """STAGE 2 hook: tell the real-account executor what the coach just did. Returns at once (the executor has its own
    thread) and does nothing while real trading is OFF. It can never break the coach."""
    try:
        from . import ai_live_executor as _LX
        _LX.submit(kind, v, px, reason)
    except Exception as e:
        print(f"[AICoach] live hook (ignored): {e}")


def _new_trade(bp, entry):
    sl = float(bp["signal_stop_loss"])
    tps = [float(bp["signal_tp%d" % i]) for i in (1, 2, 3, 4)]
    return {"bot_id": bp["id"], "sym": bp["symbol"], "side": "BUY" if str(bp.get("action")).upper() == "BUY" else "SELL",
            "tf": bp.get("timeframe") or "3m", "entry": entry, "sl": sl, "tps": tps, "hit": 0, "best": entry,
            "be": False, "trail": None, "t0": time.time(), "lev": float(bp.get("leverage") or _cfg("leverage", 1) or 1),
            "inv": float(bp.get("invest_usdt") or 0.0), "labs": None, "mode": "-",
            "bot_opened": bp.get("opened_at_ts"), "copy_after": None,
            "risk0": abs(entry - sl)}


def _progress(v):
    d = _dir(v["side"])
    dist = abs(v["tps"][0] - v["entry"])
    return max(0.0, (v["best"] - v["entry"]) * d / dist) if dist else 0.0


def _close(v, px, reason, mode="-"):
    fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
    roi = _net(_raw(v["side"], v["entry"], px), v["lev"], fee)
    best_roi = _net(_raw(v["side"], v["entry"], v["best"]), v["lev"], fee)
    rec = {"bot_id": v["bot_id"], "sym": v["sym"], "side": v["side"], "tf": v["tf"], "roi": round(roi, 3),
           "peak": round(best_roi, 2), "reason": reason, "mode": mode, "hit": v["hit"], "t0": v["t0"], "t1": time.time(),
           "inv": v["inv"], "pnl": round(v["inv"] * roi / 100.0, 4), "bot_roi": None, "bot_pnl": None,
           "after_best": None, "after_worst": None, "after": "",
           "bot_opened": v.get("bot_opened"), "facts": _facts(v.get("labs")), "entry": v["entry"],
           "copy_after": v.get("copy_after"), "exit_px": px}
    rec["freed"] = mode == "MARGIN"
    rec["align"] = (v.get("ctx") or {}).get("align", "UNKNOWN")
    try:
        from . import ai_coin_memory as _CM
        _CM.on_close(v["sym"], roi, v["lev"], rec["align"], v["bot_id"])
    except Exception:
        pass
    _state["cfg"]["realized"] = round(float(_state["cfg"].get("realized", 0.0)) + rec["pnl"], 4)
    _state["closed"].append(rec)
    _state["open"].pop(str(v["bot_id"]), None)
    _state["watch"][str(v["bot_id"])] = {"sym": v["sym"], "side": v["side"], "tf": v["tf"], "px": px, "t1": rec["t1"],
                                         "lev": v["lev"], "bot_id": v["bot_id"]}
    _memo(v["sym"], "%s %s closed: %s | result %+.1f%% (peak %+.1f%%)" % (
        v["sym"], "LONG" if v["side"] == "BUY" else "SHORT", reason, roi, best_roi))
    _live("close", v, px, reason)


def _step(v, px, bot_closed, bot_ids):
    d = _dir(v["side"])
    fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
    if (px - v["best"]) * d > 0:
        v["best"] = px
    for i, tp in enumerate(v["tps"], 1):
        if (px - tp) * d >= 0 and i > v["hit"]:
            v["hit"] = i
            _memo(v["sym"], "%s: TP%d reached" % (v["sym"], i))
            if i == 1 and not v["be"]:
                v["be"], v["sl"] = True, v["entry"]
    if v.get("scalp") and v["hit"] >= 2:
        _memo(v["sym"], "%s: SCALP - this trade runs against the bigger trend and the AI learned such trades pay less, so it booked at TP2" % v["sym"])
        _close(v, v["tps"][1], "SCALP: against the bigger trend, so booked at TP2 (learned from past trades)", "SCALP")
        return True
    if v["hit"] >= 4:
        # room behind the best price = the TP3->TP4 gap OR the signal candle's own risk, whichever is bigger
        # (the gap alone was tiny on quiet coins: one normal bounce stopped the AI out right after TP4 - PHAROSUSDT)
        gap = max(abs(v["tps"][3] - v["tps"][2]), float(v.get("risk0") or 0.0))
        t = max(v["tps"][2] * d, (v["best"] - d * gap) * d) / d
        if v["trail"] is None or (t - v["trail"]) * d > 0:
            v["trail"] = t
    stop = v["trail"] if v["trail"] is not None else v["sl"]
    if (px - stop) * d <= 0:
        why = "TRAIL (trailing stop after TP4, profit locked)" if v["trail"] is not None else (
            "SL at entry (stop moved to entry, profit protected)" if v["sl"] == v["entry"] else "SL")
        _close(v, stop, why, v.get("mode", "-"))
        return True
    bid = str(v["bot_id"])
    if bid not in bot_ids and bid in bot_closed and bot_closed[bid][1] == "REVERSED":
        _close(v, px, "REVERSED (EMA crossed back)", "-")
        return True
    if time.time() - v["t0"] > MAX_HOLD_S:
        _close(v, px, "TIMEOUT 24h", "-")
        return True
    return False


def on_bar(v, S, i):
    """Called once per CLOSED candle for an open trade: learn the facts, protect, maybe exit. Returns True if closed."""
    labs = labs_of(S, i, v["side"])
    if not labs:
        return False
    v["labs"] = labs
    try:                                               # bigger-trend tag (cache only); kept until the pictures are known
        if (v.get("ctx") or {}).get("align", "UNKNOWN") == "UNKNOWN":
            from . import ai_context as _CTX
            v["ctx"] = _CTX.tag(v["sym"], v["side"])
        if not v.get("scalp") and (v.get("ctx") or {}).get("align") == "AGAINST":
            from . import ai_coin_memory as _CM2          # SCALP MODE: only once the data says against-trend trades pay less
            v["scalp"] = _CM2.ctx_verdict() == "WITH_BETTER"
    except Exception:
        pass
    close = S["c"][i]
    _state["pending"].append({"sym": v["sym"], "tf": v["tf"], "t": S["t"][i], "side": v["side"], "px": close, "labs": labs})
    d = _dir(v["side"])
    prog = _progress(v)
    if not v["be"] and prog >= PROTECT_AT:
        v["be"], v["sl"] = True, v["entry"]
        _memo(v["sym"], "%s: price reached %d%% of the way to TP1, so the AI moved its stop to entry (the bot waits for TP1)" % (v["sym"], round(prog * 100)))
    # NEW: the exit-vs-hold table the AI learned from OLD finished trades (ai_exit_learn). It works in profit AND in loss:
    # "in this indicator situation, closing now beat holding" -> close (a loss is cut before the stop; a profit is locked).
    # A trusted HOLD verdict also skips the weaker 3-candle exit below. No table yet -> the old logic runs as before.
    v["read"], v["hold_reason"] = "", ""
    try:
        from . import ai_exit_learn as XL
        lab2 = XL.state(S, i, d)
        r2 = XL.evaluate(lab2, v["lev"], align=(v.get("ctx") or {}).get("align")) if lab2 else None
        if lab2:
            v["read"] = XL.describe(lab2)
        if r2 and r2["call"] == "BOOK":
            v["mode"] = "LEARNED"
            _memo(v["sym"], "%s: %s" % (v["sym"], r2["why"]))
            _close(v, close, "INDICATOR EXIT: " + r2["why"], "LEARNED")
            return True
        if r2 and r2["call"] == "HOLD":
            v["mode"], v["hold_reason"] = "LEARNED", r2["why"]
            v["decision"] = {"call": "HOLD", "src": "LEARNED", "why": str(r2["why"])[:260], "t": time.time()}
            return False
    except Exception as e:
        print(f"[AICoach] exit table: {e}")
    if (close - v["entry"]) * d > 0:
        out, mode, why = decide_exit(labs, prog)
        v["mode"] = mode
        if out:
            _close(v, close, why, mode)
            return True
    v["decision"] = _basic_decision(v, close, d)
    return False


def _basic_decision(v, close, d):
    """The Decision card's line when the learned table has no trusted answer for this situation."""
    t = time.time()
    if v.get("scalp"):
        return {"call": "SCALP", "src": "LEARNED", "t": t,
                "why": "This trade runs against the bigger trend and the AI learned such trades pay less, so it will book at TP2."}
    if (close - v["entry"]) * d > 0:
        return {"call": "HOLD", "src": "BASIC", "t": t,
                "why": "In profit. No exit signal yet: the basic rule needs TSI and Z-score to both turn against the trade. The stop only moves up."}
    return {"call": "HOLD", "src": "BASIC", "t": t,
            "why": "In loss. The AI has not seen enough past cases of this situation to cut early, so the stop stays where it is."}


def resolve_pending(sym, tf, S):
    """Fill in 'what happened over the next FWD_BARS candles' for samples of this symbol."""
    step = _tf_min(tf) * 60000
    idx = {t: j for j, t in enumerate(S["t"])}
    others, keep = [], []
    for s in _state["pending"]:
        if s["sym"] != sym or s["tf"] != tf:
            others.append(s)
            continue
        j = idx.get(s["t"] + FWD_BARS * step)
        if j is None:
            if s["t"] + FWD_BARS * step > S["t"][-1] and time.time() - s["t"] / 1000.0 < 86400:
                keep.append(s)                      # candle not here yet - wait
            continue                                # too old / gap: drop
        mv = (S["c"][j] - s["px"]) / s["px"] * 100.0 * _dir(s["side"])
        _count(s["labs"], mv > 0, mv)
    _state["pending"] = others + keep


def update_watch(w, S):
    """After the exit: best / worst move (net ROI points vs the exit price) over the next WATCH_BARS candles."""
    cs = [j for j in range(len(S["t"])) if S["t"][j] / 1000.0 >= w["t1"] - 1][:WATCH_BARS]
    if not cs:
        return 0, None, None
    hi = max(S["h"][j] for j in cs)
    lo = min(S["l"][j] for j in cs)
    px, lev = w["px"], w["lev"]
    if w["side"] == "BUY":
        best, worst = (hi - px) / px * 100.0 * lev, (lo - px) / px * 100.0 * lev
    else:
        best, worst = (px - lo) / px * 100.0 * lev, (px - hi) / px * 100.0 * lev
    return len(cs), round(best, 1), round(worst, 1)


def _after_text(best, worst):
    if best is None:
        return ""
    if best >= 5 and best >= abs(worst):
        return "Exit was early: after the AI left, price went another %+.1f%%" % best
    if worst <= -5 and abs(worst) > best:
        return "Exit was good: after the AI left, price moved %.1f%% against the trade" % worst
    return "Exit was neutral: price did not do much after the AI left (+%.1f / %.1f)" % (best, worst)


# ------------------------------------------------------------------ candles (budgeted, own thread)
def _fetch(sym, tf):
    from . import exchange
    return exchange.get_klines(sym, tf=_tf_min(tf), limit=LOOKBACK, fast=True)


def _bar_work(items):
    """items: {(sym, tf): ...} -> at most MAX_FETCH downloads, each new closed candle processed once."""
    budget = MAX_FETCH
    now = time.time()
    for (sym, tf) in items:
        step = _tf_min(tf) * 60
        need = int(now // step) * step * 1000 - step * 1000      # open time (ms) of the newest closed candle
        if _bar_done.get((sym, tf), 0) >= need:
            continue
        if budget <= 0:
            break
        budget -= 1
        try:
            cs = _fetch(sym, tf)
            if not cs or int(cs[-1]["timestamp"]) < need:
                continue
            S = F.build(cs)
        except Exception:
            continue
        _bar_done[(sym, tf)] = int(cs[-1]["timestamp"])
        i = S["n"] - 1
        with _lock:
            for bid, v in list(_state["open"].items()):
                if v["sym"] == sym and v["tf"] == tf:
                    on_bar(v, S, i)
            resolve_pending(sym, tf, S)
            for bid, w in list(_state["watch"].items()):
                if w["sym"] == sym and w["tf"] == tf:
                    n, b, wr = update_watch(w, S)
                    for c in _state["closed"]:
                        if str(c["bot_id"]) == bid:
                            c["after_best"], c["after_worst"], c["after"] = b, wr, _after_text(b, wr)
                    if n >= WATCH_BARS:
                        _state["watch"].pop(bid, None)
                        for c in _state["closed"]:
                            if str(c["bot_id"]) == bid:
                                _memo(sym, "%s: %s" % (sym, c["after"]))
            _mark()


# ------------------------------------------------------------------ one tick
def _copy_one(b, now, px_map):
    bid = str(b["id"])
    if bid in _state["seen"]:
        return
    _state["seen"][bid] = now
    side = "BUY" if str(b.get("action")).upper() == "BUY" else ("SELL" if str(b.get("action")).upper() == "SELL" else "")
    if not side or b.get("signal_stop_loss") is None or any(b.get("signal_tp%d" % i) is None for i in (1, 2, 3, 4)):
        return
    if now - float(b.get("opened_at_ts") or now) > START_AGE_S:
        return                                   # old trade from before the coach started
    v = _new_trade(b, float(b["entry_price"]))
    try:                                                # the AI's own day plan: hard loss cap / max trades + its data-based skips
        from . import ai_planner as PL, ai_coin_memory as CM
        opens_now = [(x["inv"], _roi_now(x, x.get("px") or x["entry"])) for x in _state["open"].values()]
        take, _mode, why = PL.check(b["symbol"], side, _state["closed"], opens_now, len(_state["open"]),
                                    CM.status(b["symbol"])["status"])
        if not take:
            _state["skips"].append({"t": now, "bot_id": b["id"], "sym": b["symbol"], "side": side, "bot_pnl": None, "plan": True, "why": str(why)[:200]})
            _memo(b["symbol"], "%s %s SKIPPED by the day plan: %s" % (b["symbol"], "LONG" if side == "BUY" else "SHORT", why))
            return
    except Exception as e:
        print(f"[AICoach] day plan check (ignored): {e}")
    v["copy_after"] = round(max(0.0, now - float(b.get("opened_at_ts") or now)), 1)
    if v["inv"] > 0 and _free(v["inv"]) < v["inv"] - 1e-9:
        prices = {x["sym"]: (px_map.get(x["sym"]) or x.get("px") or x["entry"]) for x in _state["open"].values()}
        victim = pick_victim(prices)
        if victim is None:
            _state["skips"].append({"t": now, "bot_id": b["id"], "sym": b["symbol"], "side": side, "bot_pnl": None})
            _memo(b["symbol"], "%s %s SKIPPED: no free margin (%.0f of %.0f used) and no AI trade is sideways, so nothing could be closed to make room" % (
                b["symbol"], "LONG" if side == "BUY" else "SHORT", sum(x["inv"] for x in _state["open"].values()), _balance(v["inv"])))
            return
        _close(victim, prices[victim["sym"]], "MARGIN: closed to make room for a new signal (%s); this trade had been sideways for %s" % (
            b["symbol"], _fm_min(round((time.time() - victim["t0"]) / 60.0))), "MARGIN")
    _state["open"][bid] = v
    _live("open", v)
    _memo(b["symbol"], "%s %s opened (same entry as the bot, the AI manages its own exit)" % (b["symbol"], "LONG" if side == "BUY" else "SHORT"))


def _copy_new(bots, now, px_map):
    """Open the AI copy of every NEW bot position (same entry, same SL/TP). The caller holds _lock.
    No network in here: prices come from the live-feed cache, so a copy opens the moment the bot position exists.
    If opening one copy fails for any reason it is retried on the next second instead of being lost for good."""
    for b in bots:
        bid = str(b["id"])
        if bid in _state["seen"]:
            continue
        try:
            _copy_one(b, now, px_map)
        except Exception as e:
            _state["seen"].pop(bid, None)
            print(f"[AICoach] copy of {b.get('symbol')} failed, will retry: {e}")


def _tick():
    _load()
    if not enabled():
        return
    from . import ai_desk as D
    now = time.time()
    bots = D._bot_open()
    bot_ids = {str(b["id"]) for b in bots}
    bot_closed = D._bot_closed()
    with _lock:
        open_syms = list({v["sym"] for v in _state["open"].values()})
    px_map = _prices_for(open_syms)                    # network happens HERE, outside the lock (screens never wait for it)
    try:                                               # open coins on 1h/4h/1d (cached, budgeted, own thread)
        from . import ai_context as _CTX
        _CTX.refresh(open_syms)
    except Exception as e:
        print(f"[AICoach] context refresh: {e}")
    with _lock:
        for c in _state["closed"]:
            if c["bot_pnl"] is None and str(c["bot_id"]) in bot_closed:
                bc = bot_closed[str(c["bot_id"])]
                c["bot_roi"], c["bot_pnl"] = round(bc[0], 3), round(bc[2], 4)
                _mark()
        for k in _state["skips"]:
            if k.get("bot_pnl") is None and str(k["bot_id"]) in bot_closed:
                k["bot_pnl"] = round(bot_closed[str(k["bot_id"])][2], 4)
                _mark()
        _copy_new(bots, now, px_map)
        for bid, v in list(_state["open"].items()):
            px = px_map.get(v["sym"])              # trade opened a moment ago: no price yet, next tick handles it
            if px:
                v["px"] = px
                if not _step(v, px, bot_closed, bot_ids):
                    _live("stop", v)                       # entry / trail stop moved? the executor only ever tightens it
                _mark()
        items = {}
        for v in _state["open"].values():
            items[(v["sym"], v["tf"])] = 1
        for w in _state["watch"].values():
            items[(w["sym"], w["tf"])] = 1
        for s in _state["pending"][:400]:
            items[(s["sym"], s["tf"])] = 1
    _bar_work(list(items))
    _save()
    _last["tick_ok"] = time.time()


def _copy_loop():
    """Own 1-second loop that ONLY copies new bot positions. The big tick below also downloads candles (slow on 4G),
    so before this loop the AI copy could open several seconds - sometimes minutes - after the bot."""
    time.sleep(3)
    while True:
        try:
            if enabled():
                _load()
                from . import ai_desk as D
                bots = D._bot_open()
                with _lock:
                    new = [b for b in bots if str(b["id"]) not in _state["seen"]]
                    syms = list({v["sym"] for v in _state["open"].values()}) if new else []
                if new:
                    px_map = {sy: _price_cached(sy) for sy in syms}
                    with _lock:
                        _copy_new(new, time.time(), px_map)
                        _mark()
                _last["copy_ok"] = time.time()
        except Exception as e:
            print(f"[AICoach] copier error (ignored): {e}")
        time.sleep(1.0)


def _loop():
    time.sleep(10)
    while True:
        try:
            _tick()
        except Exception as e:
            print(f"[AICoach] tick error (ignored): {e}")
        time.sleep(CYCLE_S)


_view = {"v": None, "t": 0.0, "build_s": 0.0, "err": None, "n": 0, "thread": None,
         "t_start": 0.0,       # when the build that is running right now started (0 = none running)
         "t_warn": 0.0}        # last time the watchdog printed a "stuck" line


def _publisher():
    """Builds the Bot vs AI screen answer every 2 s in its OWN thread and keeps the newest one ready.
    The endpoint just hands it out (no thread pool, no queue), so a busy / stuck AI job elsewhere can never make this
    screen show a 20-minute-old answer again. If a build is slow or fails, /api/ai/health says which and where."""
    time.sleep(6)
    while True:
        t0 = time.time()
        _view["t_start"] = t0
        try:
            if enabled():
                v = build()
                _view.update(v=v, t=time.time(), err=None, n=_view["n"] + 1)
        except Exception as e:
            _view["err"] = "%s: %s" % (type(e).__name__, e)
            print(f"[AICoach] view build failed (old answer kept): {_view['err']}")
        _view["t_start"] = 0.0
        _view["build_s"] = round(time.time() - t0, 2)
        if _view["build_s"] > 4.0:
            print(f"[AICoach] view build took {_view['build_s']}s")
        time.sleep(max(1.0, 2.0 - (time.time() - t0)))


def view():
    """Newest ready answer for the Bot vs AI screen, or None before the first build has finished."""
    return _view["v"]


STUCK_S = 60.0     # a screen answer older than this, or a build running longer than this, counts as stuck


def _where_stuck():
    """Last lines of the stack of the Bot vs AI thread: shows which call it is waiting in. None if unknown."""
    try:
        import sys, traceback
        th = _view.get("thread")
        fr = sys._current_frames().get(th.ident) if th is not None else None
        return [x.strip() for x in traceback.format_stack(fr)[-4:]] if fr is not None else None
    except Exception:
        return None


def view_info():
    """Plain facts about the screen answer, sent to the app so it can say WHERE the problem is:
    how old the answer is, whether a build is running for too long, the last error and where the thread waits."""
    now = time.time()
    age = None if not _view["t"] else round(now - _view["t"], 1)
    running = round(now - _view["t_start"], 1) if _view["t_start"] else 0.0
    stuck = bool((age is not None and age > STUCK_S) or running > STUCK_S)
    if stuck:
        reason = (f"The screen answer is being built since {running:.0f}s and has not finished: the backend thread is waiting for something."
                  if running > STUCK_S else f"The last finished answer is {age:.0f}s old and no new one arrived.")
    elif _view["err"]:
        reason = "The last build failed: " + str(_view["err"])
    else:
        reason = ""
    return {"age_s": age, "building_for_s": running, "build_s": _view["build_s"], "stuck": stuck,
            "error": _view["err"], "reason": reason, "where": _where_stuck() if stuck else None}


def _watchdog():
    """Prints one clear line to the Termux log when the Bot vs AI build is stuck (every 60 s at most)."""
    while True:
        time.sleep(15)
        try:
            now = time.time()
            running = (now - _view["t_start"]) if _view["t_start"] else 0.0
            if running > STUCK_S and now - _view["t_warn"] > 60:
                _view["t_warn"] = now
                print(f"[AICoach] WATCHDOG: the Bot vs AI build has been running for {running:.0f}s. Waiting in: {_where_stuck()}")
        except Exception:
            pass


def start():
    global _started
    if _started:
        return
    _started = True
    try:
        th = threading.Thread(target=_publisher, name="ai-coach-view", daemon=True)
        th.start()
        _view["thread"] = th
        threading.Thread(target=_watchdog, name="ai-coach-watchdog", daemon=True).start()
        threading.Thread(target=_copy_loop, name="ai-coach-copy", daemon=True).start()
        threading.Thread(target=_loop, name="ai-coach", daemon=True).start()
    except Exception as e:
        print(f"[AICoach] could not start: {e}")


# ------------------------------------------------------------------ what the page / app shows
def _learned():
    base, n_all = _base()
    rows = []
    for k, (n, f, sm) in _state["stats"].items():
        if k == "ALL" or n < MIN_N:
            continue
        rows.append({"text": _nice(k), "n": n, "p": round(f / n * 100), "avg": round(sm / n, 3), "pair": " & " in k})
    best = sorted([r for r in rows if r["p"] >= base * 100 + 8], key=lambda r: (-r["p"], -r["n"]))[:6]
    worst = sorted([r for r in rows if r["p"] <= base * 100 - 8], key=lambda r: (r["p"], -r["n"]))[:6]
    return {"samples": n_all, "base": round(base * 100), "trusted": len(rows), "best": best, "worst": worst,
            "min_n": MIN_N, "exit_min_n": EXIT_MIN_N}


def _margin_view():
    inv = 0.0
    for v in list(_state["open"].values())[:1] + [{"inv": c.get("inv", 0.0)} for c in _state["closed"][-1:]]:
        inv = inv or float(v.get("inv") or 0.0)
    used = sum(v["inv"] for v in _state["open"].values())
    mskips = [k for k in _state["skips"] if not k.get("plan")]          # margin skips only; the day plan's skips are counted below
    pskips = [k for k in _state["skips"] if k.get("plan")]
    sk = [k for k in mskips if k.get("bot_pnl") is not None]
    psd = [k for k in pskips if k.get("bot_pnl") is not None]
    fr = [c for c in _state["closed"] if c.get("freed")]
    fa = [c["after_best"] for c in fr if c.get("after_best") is not None]
    bal = _balance(inv)
    return {"balance": round(bal, 2), "custom": bool(_state["cfg"].get("balance")), "equity": round(bal + float(_state["cfg"].get("realized", 0.0)), 2),
            "used": round(used, 2), "free": round(_free(inv), 2), "per_trade": round(inv, 2),
            "slots": int(bal // inv) if inv else 0, "open": len(_state["open"]),
            "skipped": len(mskips), "plan_skipped": len(pskips), "plan_skipped_done": len(psd),
            "plan_skipped_bot_pnl": round(sum(k["bot_pnl"] for k in psd), 2), "skipped_done": len(sk), "skipped_bot_pnl": round(sum(k["bot_pnl"] for k in sk), 2),
            "freed": len(fr), "freed_after_avg": round(sum(fa) / len(fa), 1) if fa else None,
            "fee_roi": round(max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0)), 3), "lev": float(_cfg("leverage", 1) or 1),
            "fee_binance": round(0.10 * float(_cfg("leverage", 1) or 1), 3)}      # Binance USDT-M taker 0.05% in + 0.05% out, as ROI points


KEEP_FACTS = ("z_zone", "z_move", "z_div", "zma_vs_trade", "tsi_pos", "tsi_vs_sig", "tsi_zero", "sd_shape", "sd_size", "ema_dist")
MAX_PAIRS = 30


def _facts(labs):
    try:
        return [str(labs[k]) for k in KEEP_FACTS if labs and k in labs]
    except Exception:
        return []


def _thin(samples, n=60):
    """[[t, roi, lo, hi], ...] -> at most n points [[t_sec, roi], ...] (first and last always kept)."""
    try:
        if not samples:
            return []
        if len(samples) <= n:
            return [[int(s[0]), round(float(s[1]), 2)] for s in samples]
        step = (len(samples) - 1) / float(n - 1)
        out = []
        for i in range(n):
            s = samples[min(len(samples) - 1, int(round(i * step)))]
            out.append([int(s[0]), round(float(s[1]), 2)])
        return out
    except Exception:
        return []


def _bot_closed_rows():
    out = {}
    try:
        from . import trade_store
        for t in trade_store.get_recent_closed(400, net=True):
            out.setdefault(str(t.get("id")), []).append(t)
    except Exception:
        pass
    return out


def _match_closed(rows, bid, t0, opened=None):
    for t in rows.get(str(bid), []):
        o = float(t.get("opened_at_ts") or 0.0)
        if opened is not None:
            if abs(o - float(opened)) < 2.0:
                return t
        elif abs(o - float(t0)) < 900.0:
            return t
    return None


def _tags(bot, ai, path, levels, rec_after):
    """Plain-English mistake / good-call tags for ONE signal. Only says what the saved numbers prove."""
    out = []
    try:
        peak = max([x[1] for x in path], default=0.0)
        bc = bot.get("state") == "closed"
        ac = ai.get("state") == "closed"
        if bc and peak >= 3.0 and peak - float(bot.get("gross") or 0.0) >= max(4.0, 0.5 * peak):
            out.append(["bad", "Bot gave back profit (peak %+.1f%%, left at %+.1f%%)" % (peak, float(bot.get("gross") or 0.0))])
        if bc and str(bot.get("reason")).upper() == "SL" and ac and float(ai.get("roi") or 0) - float(bot.get("roi") or 0) >= 2.0:
            out.append(["good", "AI avoided part of the stop loss"])
        if bc and str(bot.get("reason")).upper() == "REVERSED" and ac and float(ai.get("roi") or 0) - float(bot.get("roi") or 0) <= -2.0:
            out.append(["bad", "Bot's reversal exit was worse than holding"])
        if ac and rec_after is not None and rec_after - float(ai.get("gross") or 0.0) >= 4.0:
            out.append(["bad", "AI left too early (price went %.1f%% further)" % (rec_after - float(ai.get("gross") or 0.0))])
        if ac and bc and float(ai.get("roi") or 0) - float(bot.get("roi") or 0) >= 3.0 and not any(t[0] == "good" for t in out):
            out.append(["good", "AI finished clearly better"])
        if bc and ac and float(ai.get("roi") or 0) - float(bot.get("roi") or 0) <= -3.0 and not any(t[1].startswith("AI left too early") for t in out):
            out.append(["bad", "AI finished clearly worse"])
    except Exception:
        pass
    return out[:3]


def _what_if(bot, path, levels, fee):
    """If the bot had moved its stop to entry right after TP1: what would this trade have ended with?"""
    try:
        tp1 = levels.get("tp1")
        if bot.get("state") != "closed" or tp1 is None or len(path) < 3:
            return ""
        hit = None
        for i, x in enumerate(path):
            if x[1] >= float(tp1):
                hit = i
                break
        if hit is None:
            return ""
        for x in path[hit + 1:]:
            if x[1] <= 0.0:
                new = -fee
                old = float(bot.get("roi") or 0.0)
                if new - old >= 1.0:
                    return "What if: stop moved to entry after TP1 -> would have ended %+.1f%% instead of %+.1f%%." % (new, old)
                return ""
        return ""
    except Exception:
        return ""


def _digest(pairs):
    """One short line for the top of the screen: TODAY (IST day) when there is data, else the last finished signals."""
    try:
        done = [p for p in pairs if p["ai"]["state"] == "closed" and p["bot"]["state"] == "closed"]
        if not done:
            return ""
        ist = time.gmtime(time.time() + 19800)
        day0 = time.time() - (ist.tm_hour * 3600 + ist.tm_min * 60 + ist.tm_sec)
        today = [p for p in done if float(p.get("t0") or 0) >= day0]
        use, label = (today, "Today") if len(today) >= 3 else (done, "Last %d finished signals" % len(done))
        ab = sum(1 for p in use if p["ai"]["roi"] - p["bot"]["roi"] >= 0.5)
        bb = sum(1 for p in use if p["ai"]["roi"] - p["bot"]["roi"] <= -0.5)
        cnt = {}
        for p in use:
            for k, t in p.get("tags") or []:
                if k == "bad":
                    key = t.split(" (")[0]
                    cnt[key] = cnt.get(key, 0) + 1
        top = max(cnt.items(), key=lambda kv: kv[1]) if cnt else None
        if label == "Today":
            line = "Today: %d finished signals. AI was better in %d, bot was better in %d." % (len(use), ab, bb)
        else:
            line = "%s: AI was better in %d, bot was better in %d." % (label, ab, bb)
        if top:
            line += " Most common mistake: %s (%dx)." % (top[0], top[1])
        return line
    except Exception:
        return ""


def replay(bot_id, opened):
    """Everything the app needs to replay ONE signal candle by candle: ROI path + Z-score / TSI per closed candle + SD band,
    plus where the bot and the AI left. Data from ai_path_logger (indicator samples exist only for trades opened after the
    tracker started). {"ok": False} when nothing was saved."""
    try:
        from . import ai_path_logger as PL
        key = PL.make_key(bot_id, opened)
        rec = PL.open_path_full(key) or PL.read_keys([key]).get(key)
        if not rec or not rec.get("s"):
            return {"ok": False, "why": "No price path was saved for this trade. It was closed before path recording started, "
                                         "or the saved file no longer holds it."}
        smp = rec["s"]
        if len(smp) > 140:
            step = (len(smp) - 1) / 139.0
            smp = [smp[min(len(smp) - 1, int(round(i * step)))] for i in range(140)]
        ind = rec.get("ind") or []
        sd = rec.get("sd") or []
        mine = None
        with _lock:
            for c in _state["closed"]:
                if str(c["bot_id"]) == str(bot_id) and abs(float(c.get("bot_opened") or c["t0"]) - float(opened)) < 900.0:
                    mine = dict(c)
            for v in _state["open"].values():
                if str(v["bot_id"]) == str(bot_id) and abs(float(v.get("bot_opened") or v["t0"]) - float(opened)) < 900.0:
                    mine = dict(v, open=True)
        return {"ok": True, "s": [[int(x[0]), round(float(x[1]), 2)] for x in smp],
                "ind": [[int(x[0]), round(float(x[1]), 2), round(float(x[2]), 1), round(float(x[3]), 1)] for x in ind][-120:],
                "sd": [[int(x[0]), round(float(x[1]), 3), round(float(x[3]), 2) if len(x) > 3 else 0.0] for x in sd][-120:],
                "levels": rec.get("levels") or {},
                "ai_exit": None if (not mine or mine.get("open")) else round(float(mine["t1"]) - float(opened)),
                "ai_open": bool(mine and mine.get("open")),
                "facts": _facts((mine or {}).get("labs")) if mine and mine.get("open") else ((mine or {}).get("facts") or [])}
    except Exception as e:
        print(f"[AICoach] replay: {e}")
        return {"ok": False, "why": "The replay could not be built (backend error). Try again in a minute."}


MAX_OPEN_ROWS, MAX_CLOSED_ROWS = 40, 30


def _started_at():
    """When the AI coach first started watching the bot (so we can say 'this trade opened before the AI was on')."""
    try:
        st = _state["cfg"].get("started")
        if st:
            return float(st)
        sv = [float(x) for x in _state["seen"].values()]
        return min(sv) if sv else time.time()
    except Exception:
        return time.time()


def _bot_open_full():
    """Every position the bot holds right now (read-only copy, same source as the Positions tab)."""
    try:
        from . import paper_trader as P
        keys = ("id", "symbol", "action", "entry_price", "signal_stop_loss", "signal_tp1", "opened_at_ts", "timeframe",
                "leverage", "invest_usdt", "ltp", "tp_hit_levels", "max_roi_pct", "signal_no", "fee_roi_pct", "signal_tp2", "signal_tp3", "signal_tp4")
        with P._lock:
            return [{k: p.get(k) for k in keys} for p in P._positions.values()]
    except Exception:
        return []


def _why_none(bid, opened, seen, skips, started, now):
    """Plain-English reason why the AI has no copy of this bot trade."""
    for k in skips:
        if str(k.get("bot_id")) == bid and abs(float(k.get("t") or 0) - opened) < 1800:
            if k.get("plan"):             # the day plan said no (max open trades, loss cap, target rest, Avoid coin) - NOT the margin
                return "Skipped by the AI day plan: " + (k.get("why") or "loss cap, max open trades, target rest or an Avoid coin (see the AI DAY PLAN journal).")
            return "Skipped: margin was full and no AI trade was sideways, so nothing could be closed to make room."
    if opened < started - 5:
        return "This bot trade opened before the AI was switched on, so the AI has no copy of it."
    if bid in seen:
        return "Not copied: the signal had no stop-loss / targets, or it was already older than 10 minutes when the AI saw it."
    if now - opened > 120:
        return "The AI has not picked this trade up yet. The backend is busy or the AI engine is behind."
    return "Waiting: the AI checks for new bot trades every few seconds."


def health():
    """Seconds since the AI copier (1 s loop) and the AI engine (5 s loop) last finished a round."""
    now = time.time()
    stack = None
    try:
        import sys, traceback
        th = _view.get("thread")
        fr = sys._current_frames().get(th.ident) if th is not None else None
        if fr is not None and (now - _view["t"] > 10):          # only when the screen answer is old: where is it stuck?
            stack = traceback.format_stack(fr)[-6:]
    except Exception:
        pass
    return {"copier_ago_s": None if not _last.get("copy_ok") else round(now - _last["copy_ok"]),
            "engine_ago_s": None if not _last.get("tick_ok") else round(now - _last["tick_ok"]),
            "open_ai_trades": len(_state["open"]),
            "view_age_s": None if not _view["t"] else round(now - _view["t"], 1),
            "view_building_for_s": round(now - _view["t_start"], 1) if _view["t_start"] else 0.0,
            "view_build_s": _view["build_s"], "view_error": _view["err"], "view_builds": _view["n"],
            "view_stuck_at": stack}


def _status(bot, ai):
    """One clear label per row: which side is running and which has finished."""
    b, a = bot.get("state"), ai.get("state")
    if b == "open" and a == "open":
        return "both_running", "BOTH RUNNING"
    if b == "open" and a == "closed":
        return "bot_running", "AI CLOSED - BOT RUNNING"
    if b != "open" and a == "open":
        return "ai_running", "BOT CLOSED - AI STILL IN"
    if b == "open" and a == "none":
        return "ai_waiting", "BOT RUNNING - NO AI COPY"
    if b == "closed" and a == "none":
        return "no_copy", "FINISHED - NO AI COPY"
    return "both_closed", "BOTH CLOSED"


def _pairs():
    """One row per BOT trade (every open position + recent closed ones), with the AI copy next to it - the same trades the
    Positions / Alerts tabs show. AI trades whose bot trade is no longer in that list are added too, so an AI trade that
    is still open never disappears."""
    out = []
    try:
        from . import ai_path_logger as PL
        now = time.time()
        fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
        bots_open = _bot_open_full()
        crows = _bot_closed_rows()
        flat = [t for lst in crows.values() for t in lst]
        flat.sort(key=lambda t: -float(t.get("closed_at_ts") or 0))
        flat = flat[:MAX_CLOSED_ROWS]
        with _lock:
            ai_open = {str(v["bot_id"]): dict(v) for v in _state["open"].values()}
            ai_closed = [dict(c) for c in _state["closed"][-300:]]
            skips = [dict(k) for k in _state["skips"][-200:]]
            seen = dict(_state["seen"])
            started = _started_at()

        def ai_open_for(bid, opened):
            v = ai_open.get(bid)
            if v is None:
                return None
            ref = float(v.get("bot_opened") or v["t0"])
            return v if abs(ref - opened) < (2.0 if v.get("bot_opened") else 900.0) else None

        def ai_closed_for(bid, opened):
            for c in reversed(ai_closed):
                if str(c["bot_id"]) != bid:
                    continue
                ref = float(c.get("bot_opened") or c["t0"])
                if abs(ref - opened) < (2.0 if c.get("bot_opened") else 900.0):
                    return c
            return None

        # ---- the list of signals: bot open, bot closed, then AI trades that are still open without a listed bot trade
        sig = []                                              # (bot_open_dict|None, bot_closed_dict|None, ai_open, ai_closed, opened)
        used_ai = set()
        for b in bots_open[:MAX_OPEN_ROWS]:
            bid = str(b["id"])
            opened = float(b.get("opened_at_ts") or now)
            ao = ai_open_for(bid, opened)
            if ao is not None:
                used_ai.add(bid)
            sig.append((b, None, ao, None if ao else ai_closed_for(bid, opened), opened))
        for t in flat:
            bid = str(t.get("id"))
            opened = float(t.get("opened_at_ts") or 0.0)
            ao = ai_open_for(bid, opened)
            if ao is not None:
                used_ai.add(bid)
            sig.append((None, t, ao, None if ao else ai_closed_for(bid, opened), opened))
        for bid, v in ai_open.items():
            if bid in used_ai:
                continue
            opened = float(v.get("bot_opened") or v["t0"])
            sig.append((None, _match_closed(crows, bid, v["t0"], v.get("bot_opened")), v, None, opened))

        try:
            from . import ai_pick
            picks = ai_pick.calls_by_bot_id()          # AI Pick's TAKE / SKIP / WATCH + reason, shown on every trade
        except Exception:
            picks = {}

        # ---- saved price paths for the finished bot trades (one indexed read, not a full file parse)
        need = [PL.make_key(str((t or {}).get("id") if t else ""), op) for (b, t, ao, ac, op) in sig if b is None and t is not None]
        paths = PL.read_keys(need) if need else {}

        for b, t, ao, ac, opened in sig:
            src = b or t or {}
            a = ao or ac
            sym = (src.get("symbol") or (a or {}).get("sym") or "")
            side_raw = str(src.get("action") or (a or {}).get("side") or "").upper()
            side = "BUY" if side_raw == "BUY" else "SELL"
            bid = str(src.get("id") if src else (a or {}).get("bot_id"))
            lev = float(src.get("leverage") or (a or {}).get("lev") or 1.0)
            key = PL.make_key(bid, opened)
            pr = PL.open_path(key) if b is not None else paths.get(key)
            if pr is None and ao is not None and b is None and t is None:
                pr = None
            samples = (pr or {}).get("s") or []
            lv = (pr or {}).get("levels") or {}

            # same live price for both sides, so the two numbers can really be compared
            px = _price_cached(sym) or (ao or {}).get("px") or (float(b["ltp"]) if b and b.get("ltp") else None)

            # ---- bot side
            if b is not None:
                if px and b.get("entry_price"):
                    g = _net(_raw(side, float(b["entry_price"]), px), lev, 0.0)
                elif samples:
                    g = float(samples[-1][1])
                else:
                    g = None
                bot = {"state": "open", "gross": None if g is None else round(g, 2),
                       "roi": None if g is None else round(g - fee, 2), "reason": "", "exit_sec": None,
                       "entry": b.get("entry_price")}
            elif t is not None:
                gross = t.get("gross_roi_pct")
                if gross is None:
                    gross = float(t.get("roi_pct") or 0.0) + float(t.get("fee_roi_pct") or 0.0)
                bot = {"state": "closed", "gross": round(float(gross), 2), "roi": round(float(t.get("roi_pct") or 0.0), 2),
                       "pnl": round(float(t.get("pnl_usdt") or 0.0), 3),
                       "reason": str(t.get("status") or "").replace("CLOSED_", ""),
                       "exit_sec": round(float(t.get("closed_at_ts") or now) - opened),
                       "closed_ts": float(t.get("closed_at_ts") or now), "entry": t.get("entry_price"),
                       "exit_px": t.get("exit_price") or t.get("ltp")}
            else:
                bot = {"state": "unknown", "gross": None, "roi": (a or {}).get("bot_roi"), "reason": "", "exit_sec": None}

            # ---- AI side
            if ao is not None:
                if px:
                    a_gross = _net(_raw(ao["side"], ao["entry"], px), float(ao.get("lev") or 1.0), 0.0)
                elif samples and b is not None:
                    a_gross = float(samples[-1][1])
                else:
                    a_gross = None
                a_net = None if a_gross is None else a_gross - fee
                peak = round(_net(_raw(ao["side"], ao["entry"], ao["best"]), float(ao.get("lev") or 1.0), fee), 1)
                if a_net is not None:
                    peak = max(peak, round(a_net, 1))
                ai = {"state": "open", "gross": None if a_gross is None else round(a_gross, 2),
                      "roi": None if a_net is None else round(a_net, 2), "peak": peak, "hit": ao["hit"], "be": ao["be"],
                      "mode": ao["mode"], "reason": "", "exit_sec": None, "facts": _facts(ao.get("labs")), "entry": ao["entry"],
                      "copy_after": ao.get("copy_after"), "entry_ts": ao.get("t0")}
            elif ac is not None:
                ai = {"state": "closed", "gross": round(ac["roi"] + fee, 2), "roi": ac["roi"], "pnl": ac.get("pnl"),
                      "peak": ac.get("peak"), "hit": ac.get("hit"), "mode": ac.get("mode"), "reason": ac.get("reason"),
                      "exit_sec": round(ac["t1"] - opened), "closed_ts": ac["t1"], "facts": ac.get("facts") or [],
                      "entry": ac.get("entry"), "copy_after": ac.get("copy_after"), "entry_ts": ac.get("t0")}
            else:
                ai = {"state": "none", "gross": None, "roi": None, "reason": "", "exit_sec": None, "facts": [],
                      "why": _why_none(bid, opened, seen, skips, started, now)}

            if ai.get("state") == "closed":
                ai["exit_px"] = (ac or {}).get("exit_px")
            elif ai.get("state") == "open":
                ai["exit_px"] = px
            plv = {"entry": src.get("entry_price") or (a or {}).get("entry"), "sl": src.get("signal_stop_loss")}
            for k in (1, 2, 3, 4):
                plv["tp%d" % k] = src.get("signal_tp%d" % k)
            status, status_text = _status(bot, ai)
            th = _thin(samples)
            after = ac.get("after_best") if ac else None
            out.append({"id": bid, "signal_no": src.get("signal_no"), "sym": sym, "side": side, "tf": src.get("timeframe") or (a or {}).get("tf"), "t0": opened,
                        "now_sec": round(now - opened), "levels": lv, "has_ind": bool((pr or {}).get("ind")),
                        "path": th, "bot": bot, "ai": ai, "plevels": plv, "tf_chart": src.get("timeframe") or (a or {}).get("tf"), "status": status, "status_text": status_text,
                        "tags": _tags(bot, ai, th, lv, after), "pick": picks.get(bid),
                        "what_if": _what_if(bot, th, lv, fee),
                        "live": bot["state"] == "open" or ai["state"] == "open"})
        # live rows first (newest open first), then finished rows (newest first)
        def rank(p):
            if p["live"]:
                return (0, -p["t0"])
            ct = max(float(p["bot"].get("closed_ts") or 0), float(p["ai"].get("closed_ts") or 0))
            return (1, -(ct or p["t0"]))
        out.sort(key=rank)
    except Exception as e:
        print(f"[AICoach] pairs: {e}")
    return out


def _live_brief():
    """Small block for the AI DAY PLAN card: the AI's REAL account today (Stage 2). Never raises; off = {"on": False}."""
    try:
        from . import ai_live_executor as _LV
        s = _LV.status()
        g = s["guard"]
        if not (g["enabled"] or s["open"] or s["today"]["n"]):
            return {"on": False}
        return {"on": bool(g["enabled"]), "halted": g["halted"], "today_pnl": s["today"]["pnl"], "today_n": s["today"]["n"],
                "open_n": len(s["open"]), "upnl": s["upnl"], "slip": s.get("slip")}
    except Exception:
        return {"on": False}


def _ready_view(both, ai_p, bot_p, ai_wins, bot_wins):
    """'Is the AI ready?' - plain facts only, no promise. Sample size, how often the AI beat the bot, and a verdict."""
    n = len(both)
    need = 100
    ai_better = sum(1 for c in both if c["pnl"] - c["bot_pnl"] > 0.0005)
    bot_better = sum(1 for c in both if c["bot_pnl"] - c["pnl"] > 0.0005)
    if n < 30:
        level, text = "low", "Too little data. Only %d finished trades so far, wait for at least 30 before reading anything into the result." % n
    elif n < need:
        level, text = "mid", "Early data (%d of %d trades). The AI was better in %d and the bot in %d. A streak this short can flip, keep collecting." % (n, need, ai_better, bot_better)
    elif ai_p > bot_p and ai_better > bot_better:
        level, text = "good", "Enough trades (%d). The AI is ahead of the bot by %+.2f USDT and better in %d trades vs %d. Still check that it holds for several days." % (n, ai_p - bot_p, ai_better, bot_better)
    else:
        level, text = "mid", "Enough trades (%d), but the AI is not clearly ahead of the bot (AI %+.2f vs bot %+.2f USDT). Do not rely on it yet." % (n, ai_p, bot_p)
    return {"n": n, "need": need, "ai_better": ai_better, "bot_better": bot_better, "level": level, "text": text,
            "ai_pnl": ai_p, "bot_pnl": bot_p, "pct": min(100, round(n / need * 100))}


def _today_block(cl, ai_opens):
    """Today's numbers on the SAME basis as the Dashboard: closed today + open (both after fee).
    bot = what the Dashboard shows (trade_store today + the bot's open positions, net).
    ai  = the AI's own virtual trades closed today + its open ones (net). Never raises."""
    out = {"bot": {"closed": 0.0, "open": 0.0, "total": 0.0, "closed_n": 0, "open_n": 0},
           "ai": {"closed": 0.0, "open": 0.0, "total": 0.0, "closed_n": 0, "open_n": 0}, "ok": False}
    try:
        from . import trade_store
        day0 = float(trade_store._trading_day_start_ts())
        st = trade_store.get_today_stats()
        out["bot"]["closed"] = round(float(st.get("today_pnl_usdt") or 0.0), 2)
        out["bot"]["closed_n"] = int(st.get("total_trades") or 0)
        bo = 0.0
        n = 0
        for b in _bot_open_full():
            px = _price_cached(b.get("symbol") or "")
            if not px or not b.get("entry_price"):
                continue
            side = "BUY" if str(b.get("action")).upper() == "BUY" else "SELL"
            lev = float(b.get("leverage") or 1.0)
            fee = float(b.get("fee_roi_pct") if b.get("fee_roi_pct") is not None else _cfg("fee_roi_pct", 1.0) or 0.0)
            roi = _net(_raw(side, float(b["entry_price"]), px), lev, fee)
            bo += float(b.get("invest_usdt") or 0.0) * roi / 100.0
            n += 1
        out["bot"]["open"] = round(bo, 2)
        out["bot"]["open_n"] = n
        out["bot"]["total"] = round(out["bot"]["closed"] + out["bot"]["open"], 2)
        ac = [c for c in cl if float(c.get("t1") or 0) >= day0]
        out["ai"]["closed"] = round(sum(float(c.get("pnl") or 0.0) for c in ac), 2)
        out["ai"]["closed_n"] = len(ac)
        ao = 0.0
        fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
        for v in _state["open"].values():
            px = _price_cached(v["sym"]) or v.get("px") or v["entry"]
            ao += float(v.get("inv") or 0.0) * _net(_raw(v["side"], v["entry"], px), v["lev"], fee) / 100.0
        out["ai"]["open"] = round(ao, 2)
        out["ai"]["open_n"] = len(_state["open"])
        out["ai"]["total"] = round(out["ai"]["closed"] + out["ai"]["open"], 2)
        out["ok"] = True
    except Exception as e:
        print(f"[AICoach] today block: {e}")
    return out


def _exit_learn_view():
    try:
        from . import ai_exit_learn as XL
        return XL.summary(float(_cfg("leverage", 1) or 1))
    except Exception:
        return {"studied": 0, "book": [], "hold": []}


def _context_view(open_syms):
    try:
        from . import ai_context as CTX, ai_coin_memory as CM
        m = {"mood": "", "text": "", "tfs": {}}
        m["coins"] = {sy: CTX.coin_view(sy) for sy in open_syms[:12]}
        return m, CM.summary(open_syms)
    except Exception:
        return {"mood": "LOADING", "text": "", "tfs": {}, "coins": {}}, {"coins": [], "counts": {}, "total": 0, "ctx": {"rows": {}, "text": ""}}


def build():
    _load()
    pairs = _pairs()          # outside the lock: it reads other modules (bot positions, trade archive, path file)
    with _lock:
        cl = list(_state["closed"])
        both = [c for c in cl if c["bot_pnl"] is not None]
        ai_p = round(sum(c["pnl"] for c in both), 2)
        bot_p = round(sum(c["bot_pnl"] for c in both), 2)
        win = lambda xs: sum(1 for x in xs if x > 0)
        sideways = [c for c in cl if (c["t1"] - c["t0"]) > 1800 and abs(c["roi"]) < 3]
        fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
        opens = []
        for v in _state["open"].values():
            px = _price_cached(v["sym"]) or v.get("px") or v["entry"]
            labs = v.get("labs") or {}
            keep = ("z_zone", "z_move", "z_div", "zma_vs_trade", "tsi_pos", "tsi_vs_sig", "tsi_zero", "sd_shape", "sd_size", "ema_dist")
            dd = _dir(v["side"])
            r0 = float(v.get("risk0") or (abs(v["entry"] - v["sl"]) if v.get("sl") is not None else 0.0) or 0.0)
            stop_now = v.get("trail") if v.get("trail") is not None else v.get("sl")
            rr = (lambda x: round((x - v["entry"]) * dd / r0, 2) if x is not None else None) if r0 > 0 else (lambda x: None)
            opens.append({"sym": v["sym"], "side": v["side"], "roi": round(_net(_raw(v["side"], v["entry"], px), v["lev"], fee), 1),
                          "dec": v.get("decision"), "r_now": rr(px), "stop_r": rr(stop_now), "tp_r": [rr(x) for x in (v.get("tps") or [])],
                          "trail": v.get("trail") is not None, "scalp": bool(v.get("scalp")),
                          "peak": round(_net(_raw(v["side"], v["entry"], v["best"]), v["lev"], fee), 1), "hit": v["hit"],
                          "be": v["be"], "mode": v["mode"], "min": round((time.time() - v["t0"]) / 60.0),
                          "facts": [labs[k] for k in keep if k in labs],
                          "read": v.get("read", ""), "hold": v.get("hold_reason", ""),
                          "align": (v.get("ctx") or {}).get("align", "UNKNOWN")})
        today = _today_block(cl, opens)
        _mkt, _coins = _context_view(sorted({o["sym"] for o in opens}))
        try:
            from . import ai_planner as _PL
            _plan = _PL.view(cl, [(v["inv"], o["roi"]) for v, o in zip(_state["open"].values(), opens)])
        except Exception:
            _plan = {"cfg": {}, "mode": "HUNT", "why": "", "journal": [], "on": False}
        return {"plan": _plan, "live": _live_brief(), "market": _mkt, "coin_memory": _coins, "enabled": enabled(), "min_n": MIN_N, "today": today,
                "compare": {"n": len(both), "ai_pnl": ai_p, "bot_pnl": bot_p, "ai_wins": win([c["pnl"] for c in both]),
                            "bot_wins": win([c["bot_pnl"] for c in both]), "open": len(_state["open"]),
                            "ready": len(both) >= MIN_N},
                "learned": _learned(), "exit_learn": _exit_learn_view(), "margin": _margin_view(), "ready": _ready_view(both, ai_p, bot_p, win([c["pnl"] for c in both]), win([c["bot_pnl"] for c in both])),
                "sideways": {"n": len(sideways), "avg_min": round(sum((c["t1"] - c["t0"]) / 60.0 for c in sideways) / len(sideways)) if sideways else 0},
                "open": opens, "pairs": pairs, "digest": _digest(pairs), "ts": time.time(), "tick_age": (None if not _last.get("tick_ok") else round(time.time() - _last["tick_ok"])), "closed": list(reversed(cl[-40:])), "memo": list(reversed(_state["memo"][-60:]))}


def reset():
    with _lock:
        _state.update({"open": {}, "watch": {}, "closed": [], "memo": [], "seen": {}, "stats": {}, "pending": [], "skips": []})
        _state["cfg"] = {k: v for k, v in _state["cfg"].items() if k == "balance"}
        _bar_done.clear()
        _mark()
    _save(force=True)
    return {"ok": True}
