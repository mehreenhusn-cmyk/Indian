"""
ai_selfsignal.py - ROUND B: the AI looks for its OWN signals (shadow only, no trade is ever opened).

What it does (plain English):
  * It waits until the AI Pick has run for a while AND has proven at least one situation. Then it starts BY ITSELF.
    There is nothing to switch on. (Setting selfsignal_enabled=false turns it off.)
  * About once a minute it takes ONE coin of the watchlist, reads its newest CLOSED candle on the bot's timeframe, and
    asks the AI Pick the same question it asks for bot signals: "does this situation match proven winners?"
    Only a TAKE counts as an AI own signal. Candles where the bot itself fires are left to the AI Pick.
  * The signal is only written down (entry = candle close, stop = candle low / high, targets = SD bands, exactly like the bot).
    Later candles decide how it ended, with the same replay the Shadow Lab uses (bot rule T4).
  * The scoreboard compares these own signals with the bot's signals, after fee. Because the candles are NEW (after the
    proven situations were counted), this is a fair test.

READ-ONLY for trading: never opens, closes or changes any trade, never touches strategy.py or paper_trader.py.
"""
import math
import os
import random
import threading
import time

from . import ai_exit_study as X
from . import ai_pick as P
from . import ai_priority
from . import ai_shadow_lab as L
from . import ai_ind_features as F
from . import ai_rowcache as RC

TICK_S = 60.0
EXPLORE_TICK_S = 20.0        # explore mode looks at a new coin this often (every scan is one coin, read from closed candles)
EXPLORE_BUSY_S = 120.0       # ... and this often while the app is open (the screen still comes first)
EXPLORE_MAX_OPEN = 5         # explore mode: most own paper signals open at the same time (setting selfsignal_max_open)
MIN_RUN_S = 86400.0          # the AI Pick must have been running this long before own signals start
MIN_PROVEN = 1               # ... and must have at least this many proven situations (TAKING)
MAX_OPEN = 20                # most own signals open at the same time
VERDICT_MIN_N = 30           # finished own signals needed before the scoreboard gives a verdict
KEEP_DONE = 500
BUSY_SCAN_EVERY_S = 300.0    # while the app is open the scan only runs this often (the screen comes first)

_lock = threading.RLock()
_file = None
_loaded = False
_started = False
_dirty = False
_state = {"open": {}, "done": [], "rr": 0, "dropped": 0, "since": 0.0, "gate_open_at": 0.0, "learn": {}, "prio": []}
_st = {"tick_ok": 0.0, "last_scan": 0.0, "last_error": None, "gate": {"open": False, "why": "not checked yet"}, "last_sym": None,
       "scans": 0}
_last_save = 0.0


# ------------------------------------------------------------------ plumbing
def _cfg(name, default):
    try:
        from . import settings_store
        v = settings_store.get(name, default)
        return default if v is None else v
    except Exception:
        return default


def enabled():
    return bool(_cfg("selfsignal_enabled", True))


def explore():
    """EXPLORE MODE (default ON): the AI looks for entries on its own at any time, reading the indicators itself.
    It does not wait for the 24 h gate or for a proven situation. It is still paper only, and it still avoids a
    situation the AI Pick has already PROVEN to lose. Setting selfsignal_explore=false brings the old gate back."""
    return bool(_cfg("selfsignal_explore", True))


def max_open():
    if not explore():
        return MAX_OPEN
    try:
        return max(1, min(20, int(_cfg("selfsignal_max_open", EXPLORE_MAX_OPEN))))
    except Exception:
        return EXPLORE_MAX_OPEN


def _read(side, lab):
    """The AI's own indicator reading for a candle (no bot signal needed). -> (take?, plain-English reason).
    Needs: Z and TSI both with the trade, the Z average line with the trade, and the main chart trending with it.
    Refuses: chasing a price far from EMA50, or a reversal arrow against the trade."""
    want = ("Z and TSI both WITH trade", "Z avg-line WITH trade", "trending WITH trade")
    got = (lab.get("z_tsi"), lab.get("zma_vs_trade"), lab.get("move"))
    miss = [w for w, g in zip(want, got) if g != w]
    word = "up" if side == "BUY" else "down"
    if miss:
        return False, "Not all indicators agree for a %s." % side
    if lab.get("ema_dist") == "price far from EMA50 (WITH trade)":
        return False, "Price is already far from EMA50 (chasing)."
    arrow = lab.get("warning")
    if (side == "BUY" and arrow == "reversal arrow DOWN") or (side == "SELL" and arrow == "reversal arrow UP"):
        return False, "A reversal arrow is against the trade."
    why = "%s: main chart trending %s, Z and TSI both agree, Z average line agrees" % (side, word)
    if lab.get("sd_zone"):
        why += ", price zone: %s" % lab["sd_zone"]
    return True, why + "."


def init(path):
    global _file
    try:
        os.makedirs(path, exist_ok=True)
        _file = os.path.join(path, "ai_selfsignal.json")
    except Exception as e:
        print(f"[AISelf] init: {e}")


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
                d, _src = safe_io.read_json_safe(_file, "ai_selfsignal")
                if isinstance(d, dict):
                    if isinstance(d.get("open"), dict):
                        _state["open"] = d["open"]
                    if isinstance(d.get("done"), list):
                        _state["done"] = d["done"]
                    if isinstance(d.get("learn"), dict):
                        _state["learn"] = d["learn"]
                    if isinstance(d.get("prio"), list):
                        _state["prio"] = d["prio"]
                    for k in ("rr", "dropped"):
                        _state[k] = int(d.get(k) or 0)
                    for k in ("since", "gate_open_at"):
                        _state[k] = float(d.get(k) or 0.0)
        except Exception as e:
            print(f"[AISelf] load: {e}")
        if not _state["since"]:
            _state["since"] = time.time()
            _mark()


def _save(force=False):
    global _dirty, _last_save
    with _lock:
        if not _file or not (_dirty or force):
            return
        if not force and time.time() - _last_save < 10:
            return
        try:
            from . import safe_io
            _state["done"] = _state["done"][-KEEP_DONE:]
            safe_io.write_json_atomic(_file, _state)
            _dirty = False
            _last_save = time.time()
        except Exception as e:
            print(f"[AISelf] save: {e}")


# ------------------------------------------------------------------ the gate (starts by itself)
def gate():
    """-> (open?, plain-English reason). Open = the AI Pick has run long enough AND has proven something.
    In explore mode the gate is always open."""
    if free():
        return True, "Free mode: the AI reads the indicators, enters, stops, books profit and flips on its own (paper only). No fixed rules."
    if explore():
        return True, "Explore mode: the AI reads the indicators and enters on its own, paper only, up to %d at a time." % max_open()
    try:
        P._load()
        with P._lock:
            since = float(P._state.get("since") or 0.0)
        run = time.time() - since if since else 0.0
        if run < MIN_RUN_S:
            left_h = (MIN_RUN_S - run) / 3600.0
            return False, "Waiting: the AI Pick has to collect data for about %.0f more hour(s) first." % max(left_h, 0.1)
        book = P._book(P._tf())["book"]
        proven = sum(1 for v in book.values() if v.get("status") == "TAKING")
        if proven < MIN_PROVEN:
            return False, "Waiting: the AI has not proven any situation yet, so there is nothing to look for."
        return True, "Running: %d proven situation(s) to look for." % proven
    except Exception as e:
        return False, "Waiting: gate check failed (%s)." % type(e).__name__


# ------------------------------------------------------------------ one candle -> a possible own signal
def _hypothetical(strat, sym, tf, cs, S, ctxS, side):
    """Same facts the bot's signal would carry, for the newest closed candle, WITHOUT needing an EMA cross.
    -> dict(entry, sl, tps, labels) or None. Uses the strategy's own helper functions (read-only calls)."""
    w = cs[-L.SIG_WINDOW:]
    closes = [float(c["close"]) for c in w]
    ema = strat._compute_ema(closes)
    if ema[-1] is None or ema[-2] is None:
        return None
    mean, std = strat._rolling_mean_std(closes)
    levels = {"zero_price": mean, "onesd": mean + std, "twosd": mean + 2 * std, "threesd": mean + 3 * std,
              "neg_onesd": mean - std, "neg_twosd": mean - 2 * std, "neg_threesd": mean - 3 * std}
    last = w[-1]
    entry = float(last["close"])
    is_long = side == "BUY"
    sl = float(last["low"]) if is_long else float(last["high"])
    if (is_long and sl >= entry) or ((not is_long) and sl <= entry):
        return None
    tps = [float(x) for x in strat.calculate_tp_levels(entry, is_long, levels)]
    i = S["n"] - 1
    ind = F.own_features(S, i)
    if not ind:
        return None
    step = L.TF_MS[tf]
    t_close = S["t"][i] + step - 1
    ctx = {}
    for ctf, CS in (ctxS or {}).items():
        if L.TF_MS[ctf] <= step:
            continue
        ctx[ctf] = F.ctx_features(CS, F.ctx_index(CS, t_close, L.TF_MS[ctf]))
    zone = strat._zone_label(entry, levels)
    slope, vol = strat._entry_context(w, ema)
    _sp, _s10, turn = strat._slope_context(ema)
    cross_n, atr, _sdw = strat._regime_context(w, closes, ema, mean, std)
    sigd = {"zone": zone, "turn": turn, "cross_n": cross_n, "vol": vol, "slope": slope, "atr": atr}
    lab = F.labels(side, ind, ctx, sigd)
    lab["direction"] = side
    for sfx, ze, pe in (("3", 0.15, 0.05), ("10", 0.30, 0.10)):
        v = RC._pz(ind, side, sfx, ze, pe)
        if v:
            lab["pz" + sfx] = v
    return {"entry": entry, "sl": sl, "tps": tps, "labels": lab, "t_close": t_close, "bar_t": S["t"][i]}


def _resolve(sym, tf, S, lev, fee):
    """Finish open own signals of this coin whose candles have now played out (bot rule T4, after fee)."""
    done = []
    with _lock:
        mine = [(k, dict(v)) for k, v in _state["open"].items() if v["sym"] == sym and v["tf"] == tf]
    if not mine:
        return
    index = {int(t): i for i, t in enumerate(S["t"])}
    for k, v in mine:
        i = index.get(int(v["bar_t"]))
        if i is None:
            with _lock:                                   # the candle fell out of the window: cannot judge it, drop it
                _state["open"].pop(k, None)
                _state["dropped"] += 1
                _mark()
            continue
        res = L._simulate(S, i, v["side"] == "BUY", v["entry"], v["sl"], v["tps"]).get(L.LIVE_RULE)
        if not res or res[1] == "OPEN":
            continue
        roi = round(L._net(res[0], lev, fee), 3)
        rec = dict(v)
        rec.update(roi=roi, how=res[1], bars=res[2], closed=time.time())
        done.append((k, rec))
    if done:
        with _lock:
            for k, rec in done:
                _state["open"].pop(k, None)
                _state["done"].append(rec)
            _mark()


# ================================================================== FREE MODE (default ON)
# The AI is on its own. No bot wiring, no AI Pick wiring, no reversal-arrow rule, no "chasing" rule, no fixed number
# of trades, no fixed TP and no fixed SL. It READS Z-score, Z average line, TSI, SD zone and EMA50 on every closed
# candle, enters when its own reading (and what it learned from earlier trades) says so, puts its own stop where the
# chart says, exits / books profit / flips when the reading turns, and writes down what worked.
# Paper only. Nothing here touches strategy.py or paper_trader.py.
FREE_STEP_STALE = 2.5          # technical: a candle older than this many candle-lengths is not entered (the price would be old)
FREE_TIMEOUT_H = 24.0          # technical bookkeeping: a trade that never exits is written down after this long
FREE_CAP_DEFAULT = 40          # technical ceiling (phone CPU), not a trading rule. setting: selfsignal_free_cap
MIN_RISK_PCT = 0.05            # technical: a stop must not sit on top of the entry price
# What the AI may CHOOSE from (it learns which one works, it is not told):
STOP_STYLES = ("swing3", "swing8", "swing20", "sd1", "sd2")        # where to put the stop: behind a swing, or N SD from entry
PB_STYLES = ("tsi", "z", "either")                                  # what makes it book a profit: TSI turning, Z turning, or either
LOSS_STYLES = (True, False)                                        # leave early when the reading flips, or wait for the stop
TRAIL_STYLES = ("none", "be", "swing")                              # stop stays / goes to entry after +1 risk / trails the swing
_chart = {}                    # trade key -> last candles for the little chart (memory only)
_next_eval = {}                # (sym, tf) -> ms when a new closed candle is expected


def free():
    return bool(_cfg("selfsignal_free", True))


def _free_cap():
    try:
        return max(1, min(100, int(_cfg("selfsignal_free_cap", FREE_CAP_DEFAULT))))
    except Exception:
        return FREE_CAP_DEFAULT


def _bucket(S, i, ind):
    """The AI's own words for what the indicators show at candle i. This is what it learns from."""
    z = ind.get("z")
    zd = ind.get("zd3")
    if z is None:
        return None
    if z < -2:
        zb = "Z very low"
    elif z < -1:
        zb = "Z low"
    elif z < 0:
        zb = "Z a bit below average"
    elif z < 1:
        zb = "Z a bit above average"
    elif z < 2:
        zb = "Z high"
    else:
        zb = "Z very high"
    zt = "rising" if (zd or 0) > 0.1 else ("falling" if (zd or 0) < -0.1 else "flat")
    tsi = "TSI above signal" if (ind.get("dif") or 0) > 0 else "TSI below signal"
    if (ind.get("tx") if ind.get("tx") is not None else 99) <= 2:
        tsi += " (just crossed)"
    e50 = S["e50"][i]
    ema = "price above EMA50" if (e50 is not None and S["c"][i] > e50) else "price below EMA50"
    return (zb, "Z " + zt, tsi, ema)


def _stat(key):
    v = _state["learn"].get(key)
    if not v:
        return 0, 0.0, 0, 0.0
    return int(v[0]), float(v[1]), int(v[2]), float(v[3]) if len(v) > 3 else 0.0


def _learn(key, roi):
    v = _state["learn"].get(key) or [0, 0.0, 0, 0.0]
    if len(v) < 4:
        v = list(v) + [0.0]
    v[0] += 1
    v[1] = round(v[1] + roi, 4)
    v[2] += 1 if roi > 0 else 0
    v[3] = round(v[3] + roi * roi, 4)
    _state["learn"][key] = v
    if len(_state["learn"]) > 3000:                      # keep the table small on a phone
        for k in sorted(_state["learn"], key=lambda k: _state["learn"][k][0])[:600]:
            _state["learn"].pop(k, None)


def _var0():
    """How much trade results swing in general (from the AI's own finished trades). Nothing is fixed: with no
    trades yet it just assumes 'could be anything'."""
    rois = [d["roi"] for d in _state["done"][-300:] if isinstance(d.get("roi"), (int, float))]
    if len(rois) < 5:
        return 100.0
    m = sum(rois) / len(rois)
    return max(sum((r - m) ** 2 for r in rois) / len(rois), 1.0)


def _ts(key, var0):
    """Thompson sampling: draw a plausible average result for this choice. Little experience -> wide draw (it tries
    it out); lots of experience -> narrow draw (it trusts what it measured). Exploring fades away BY ITSELF."""
    n, tot, _w, sq = _stat(key)
    mean = tot / n if n else 0.0
    if n >= 2:
        var = max(sq / n - mean * mean, 1e-6)
    else:
        var = var0
    return random.gauss(mean, math.sqrt(var / (n + 1)))


def _pick(prefix, options, var0):
    best = None
    for o in options:
        sc = _ts("%s|%s" % (prefix, o), var0)
        if best is None or sc > best[0]:
            best = (sc, o)
    return best[1]


def _reading_text(S, i, ind, side):
    z = ind.get("z")
    bits = ["Z %+.1f %s" % (z, "rising" if (ind.get("zd3") or 0) > 0.1 else ("falling" if (ind.get("zd3") or 0) < -0.1 else "flat")),
            "TSI %s its signal" % ("above" if (ind.get("dif") or 0) > 0 else "below")]
    e50 = S["e50"][i]
    if e50 is not None:
        bits.append("price %s EMA50" % ("above" if S["c"][i] > e50 else "below"))
    sd = S["std"][i]
    if sd and S["sma"][i] is not None:
        bits.append("%+.1f SD from the average" % ((S["c"][i] - S["sma"][i]) / sd))
    return ", ".join(bits)


def _free_sl(S, i, side, style):
    """The AI's stop for the chosen style. The only limits are physical: not on top of the entry, and not beyond the
    point where the exchange would liquidate the position anyway (100 / leverage %)."""
    entry = S["c"][i]
    if style.startswith("swing"):
        nb = int(style[5:])
        lo = max(0, i - nb + 1)
        sl = (min(S["l"][lo:i + 1]) * 0.9995) if side == "BUY" else (max(S["h"][lo:i + 1]) * 1.0005)
        risk = abs(entry - sl) / entry * 100.0
    else:
        k = 1.0 if style == "sd1" else 2.0
        sd = S["std"][i] or 0.0
        risk = (k * sd / entry * 100.0) if entry else 0.0
    try:
        lev = max(1.0, float(_cfg("leverage", 1) or 1))
    except Exception:
        lev = 1.0
    risk = min(max(risk, MIN_RISK_PCT), 90.0 / lev)
    sl = entry * (1 - risk / 100.0) if side == "BUY" else entry * (1 + risk / 100.0)
    return sl, risk


def _free_replay_core(S, i, side, entry, sl0, xs=None, path=None):
    """Replay the AI's own management of ONE trade over the closed candles after the entry candle i.
    Every closed candle it re-reads the indicators and decides: hold, move the stop, book profit, or leave.
    -> dict(state OPEN/CLOSED, px, how, why, bars, sl, mfe, mae, last_px)"""
    n = S["n"]
    xs = xs or {"pb": "either", "loss": True, "trail": "swing"}
    long_ = side == "BUY"
    dr = 1.0 if long_ else -1.0
    risk = abs(entry - sl0) / entry * 100.0
    sl = sl0
    mfe = mae = 0.0
    step_ms = (S["t"][1] - S["t"][0]) if n > 1 else 180000
    max_bars = int(FREE_TIMEOUT_H * 3600000.0 / max(step_ms, 1))
    c, h, l, o = S["c"], S["h"], S["l"], S["o"]
    z, dif = S["z"], S["diff"]
    crossed_against = False
    for j in range(i + 1, n):
        bars = j - i
        hit = (l[j] <= sl) if long_ else (h[j] >= sl)
        fav = ((h[j] if long_ else l[j]) - entry) / entry * 100.0 * dr
        adv = -((l[j] if long_ else h[j]) - entry) / entry * 100.0 * dr
        mfe, mae = max(mfe, fav), max(mae, adv)
        if hit:
            gap = (o[j] < sl) if long_ else (o[j] > sl)
            px = o[j] if gap else sl
            gain = (px - entry) * dr
            how = "STOP (trailed, profit kept)" if gain > 0 else ("STOP at entry" if gain == 0 else "STOP")
            return {"state": "CLOSED", "px": px, "how": how, "bars": bars, "sl": sl, "mfe": mfe, "mae": mae, "last_px": c[j],
                    "why": "Price came back to my stop at %.6g." % sl, "j": j}
        pnl = (c[j] - entry) / entry * 100.0 * dr
        d0, d1 = dif[j], dif[j - 1]
        z0, z1, z2 = z[j], z[j - 1], z[j - 2]
        tsi_against = d0 is not None and d1 is not None and ((d0 < 0 <= d1) if long_ else (d0 > 0 >= d1))
        crossed_against = crossed_against or bool(tsi_against)
        z_against = None not in (z0, z1, z2) and ((z0 < z1 < z2) if long_ else (z0 > z1 > z2))
        z_stretched = z0 is not None and ((z0 > 1.0) if long_ else (z0 < -1.0))
        e50 = S["e50"][j]
        wrong_side = e50 is not None and ((c[j] < e50) if long_ else (c[j] > e50))
        # 1) in profit and the reading says the move is tiring -> book it (which signs it trusts is the AI's own choice)
        if pnl > 0:
            z_turn = z_against and z_stretched
            fire = (tsi_against if xs["pb"] == "tsi" else (z_turn if xs["pb"] == "z" else (tsi_against or z_turn)))
            if fire:
                why = ("Profit booked: TSI crossed against the trade, buyers/sellers are changing sides."
                       if (tsi_against and xs["pb"] != "z") else "Profit booked: Z is turning back from a stretched level.")
                return {"state": "CLOSED", "px": c[j], "how": "PROFIT BOOK", "bars": bars, "sl": sl, "mfe": mfe, "mae": mae,
                        "last_px": c[j], "why": why, "j": j}
        # 2) the reading flipped while in loss -> leave without waiting for the stop (only if the AI learned that pays)
        if xs["loss"] and pnl < 0 and crossed_against and z_against and wrong_side:
            return {"state": "CLOSED", "px": c[j], "how": "READING FLIPPED", "bars": bars, "sl": sl, "mfe": mfe, "mae": mae,
                    "last_px": c[j], "why": "Left early: TSI and Z both turned against the trade and price is on the wrong side of EMA50.",
                    "j": j}
        # 3) the AI moves its own stop (or leaves it, if that is what it learned works)
        prev_sl = sl
        if xs["trail"] == "swing" and pnl >= risk:
            tr = min(l[j - 2:j + 1]) if long_ else max(h[j - 2:j + 1])
            sl = max(sl, tr) if long_ else min(sl, tr)
        elif xs["trail"] == "be" and pnl >= risk:
            sl = max(sl, entry) if long_ else min(sl, entry)
        if path is not None and sl != prev_sl:
            path.append([S["t"][j], sl])                    # for the chart: when (candle time) and where the stop moved
        if bars >= max_bars:
            return {"state": "CLOSED", "px": c[j], "how": "TIMEOUT 24h", "bars": bars, "sl": sl, "mfe": mfe, "mae": mae,
                    "last_px": c[j], "why": "Bookkeeping: trade was still open after %d h." % FREE_TIMEOUT_H, "j": j}
    last = c[n - 1]
    return {"state": "OPEN", "px": last, "how": "OPEN", "bars": n - 1 - i, "sl": sl, "mfe": mfe, "mae": mae, "last_px": last,
            "why": "", "j": n - 1}


def _free_replay(S, i, side, entry, sl0, xs=None):
    """Same as _free_replay_core, plus every stop move: r["path"] = [[candle_time_ms, new_stop], ...]."""
    path = []
    r = _free_replay_core(S, i, side, entry, sl0, xs, path)
    r["path"] = path
    return r


def _free_resolve(sym, tf, S, lev, fee):
    """Re-read every open own trade of this coin on the newest closed candles. -> True if one was closed."""
    with _lock:
        mine = [(k, dict(v)) for k, v in _state["open"].items() if v["sym"] == sym and v["tf"] == tf]
    if not mine:
        return False
    index = {int(t): i for i, t in enumerate(S["t"])}
    closed_any = False
    for k, v in mine:
        i = index.get(int(v["bar_t"]))
        if i is None:
            with _lock:
                _state["open"].pop(k, None)
                _state["dropped"] += 1
                _mark()
            continue
        sl0 = float(v.get("sl0") or v["sl"])
        r = _free_replay(S, i, v["side"], v["entry"], sl0, v.get("xs"))
        # candles of this trade (25 before the entry until now / the exit + 12), saved with the trade so the chart opens at once
        hi_j = (r["j"] if r.get("j") is not None else S["n"] - 1) + 13
        cand = [[int(S["t"][j]), round(float(S["o"][j]), 8), round(float(S["h"][j]), 8), round(float(S["l"][j]), 8), round(float(S["c"][j]), 8)]
                for j in range(max(0, i - 25), min(S["n"], hi_j))][-110:]
        lo = max(0, S["n"] - 45)
        _chart[k] = [[round(S["o"][j], 8), round(S["h"][j], 8), round(S["l"][j], 8), round(S["c"][j], 8)] for j in range(lo, S["n"])]
        with _lock:
            cur = _state["open"].get(k)
            if cur is None:
                continue
            cur.update(sl_now=r["sl"], now=r["last_px"], mfe=round(r["mfe"], 3), mae=round(r["mae"], 3), ev=time.time(), sl_path=r.get("path", []), cand=cand)
            if "sl0" not in cur:
                cur["sl0"] = sl0
            _mark()
        if r["state"] == "OPEN":
            continue
        ret = (r["px"] - v["entry"]) / v["entry"] * 100.0 * (1.0 if v["side"] == "BUY" else -1.0)
        roi = round(L._net(ret, lev, fee), 3)
        rec = dict(v)
        rec.update(roi=roi, how=r["how"], exit_why=r["why"], bars=r["bars"], closed=time.time(), mfe=round(r["mfe"], 3),
                   mae=round(r["mae"], 3), exit_px=r["px"], left_early=None, sl_path=r.get("path", []), sl_now=r["sl"], cand=cand,
                   exit_t=(S["t"][r["j"]] if r.get("j") is not None else None))
        with _lock:
            _state["open"].pop(k, None)
            _state["done"].append(rec)
            for old_d in _state["done"][:-25]:                       # candles only for the last 25 finished trades (keeps the file small)
                old_d.pop("cand", None)
            if v.get("bkt"):
                _learn("%s|%s" % (v["bkt"], v["side"]), roi)                              # was this reading worth entering?
                if v.get("stop_style"):
                    _learn("stop|%s|%s|%s" % (v["bkt"], v["side"], v["stop_style"]), roi)   # which stop suited this reading?
            if v.get("xs"):
                x = v["xs"]
                _learn("exit|%s/%s/%s" % (x["pb"], x["loss"], x["trail"]), roi)           # which way of leaving works best?
            if r["how"] in ("PROFIT BOOK", "READING FLIPPED"):
                _state["prio"] = ([sym] + [x for x in _state["prio"] if x != sym])[:5]   # look at this coin again at once (flip)
            _mark()
        _chart.pop(k, None)
        closed_any = True
    return closed_any


def _free_try_enter(sym, tf, cs, S, ctx_unused=None):
    """Read the newest closed candle of this coin and decide, by itself, whether to enter and on which side."""
    i = S["n"] - 1
    step = L.TF_MS[tf]
    if time.time() * 1000.0 - (S["t"][i] + step) > FREE_STEP_STALE * step:
        return False                                       # candle too old: the price is no longer the price
    ind = F.own_features(S, i)
    if not ind:
        return False
    bk = _bucket(S, i, ind)
    if not bk:
        return False
    bkey = " | ".join(bk)
    t_close = S["t"][i] + step - 1
    with _lock:
        known = set(_state["open"].keys()) | {d["k"] for d in _state["done"][-200:]}
    var0 = _var0()
    best = None
    for side in ("BUY", "SELL"):
        key = "%s|%s|%d|%s" % (sym, tf, t_close, side[0])
        if key in known:
            continue
        n, tot, _w, _sq = _stat("%s|%s" % (bkey, side))
        draw = _ts("%s|%s" % (bkey, side), var0)           # a plausible average result of this reading, drawn from its record
        if draw <= 0:
            continue                                       # the AI does not expect profit from this reading right now
        if best is None or draw > best[0]:
            best = (draw, side, key, n, (tot / n if n else 0.0))
    if not best:
        return False
    _score, side, key, n, mean = best
    stop_style = _pick("stop|%s|%s" % (bkey, side), STOP_STYLES, var0)
    # the exit style is learned as one combination (choose the best-looking combination from what it has measured)
    combos = [(a_, b_, c_) for a_ in PB_STYLES for b_ in LOSS_STYLES for c_ in TRAIL_STYLES]
    bc = None
    for a_, b_, c_ in combos:
        sc = _ts("exit|%s/%s/%s" % (a_, b_, c_), var0)
        if bc is None or sc > bc[0]:
            bc = (sc, a_, b_, c_)
    xs = {"pb": bc[1], "loss": bc[2], "trail": bc[3]}
    sl, risk = _free_sl(S, i, side, stop_style)
    why = "%s: %s." % (side, _reading_text(S, i, ind, side))
    if n:
        why += " Record of this reading: %+.1f%% on average over %d trade(s)." % (mean, n)
    else:
        why += " New reading, trying it out."
    why += " Stop style: %s. Exit style: profit by %s, %s, stop %s." % (
        stop_style, xs["pb"], "leave if reading flips" if xs["loss"] else "wait for stop",
        {"none": "stays", "be": "to entry after +1 risk", "swing": "trails the swing"}[xs["trail"]])
    rec = {"k": key, "sym": sym, "tf": tf, "side": side, "bar_t": S["t"][i], "t_close": t_close, "entry": S["c"][i], "sl": sl, "sl0": sl,
           "sl_now": sl, "now": S["c"][i], "tps": [], "why": why, "opened": time.time(), "mode": "free", "bkt": bkey, "risk_pct": round(risk, 2), "stop_style": stop_style, "xs": xs}
    with _lock:
        _state["open"][key] = rec
        _mark()
    return True


def _free_scan(sym):
    tf = P._tf()
    _st["last_sym"] = sym
    cs = L._fetch_limit(sym, tf, L.LIVE_LIMIT)
    if not cs or len(cs) < F.MIN_BARS + 5:
        return
    lev = float(_cfg("leverage", 1) or 1)
    fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
    S = F.build(cs)
    step = L.TF_MS[tf]
    _next_eval[(sym, tf)] = S["t"][S["n"] - 1] + 2 * step + 1500      # next closed candle is ready then
    _free_resolve(sym, tf, S, lev, fee)
    with _lock:
        n_open = len(_state["open"])
        have_sym = any(v["sym"] == sym and v["tf"] == tf for v in _state["open"].values())
    if n_open >= _free_cap() or have_sym:
        return
    _free_try_enter(sym, tf, cs, S)


def _free_tick():
    tf = P._tf()
    now_ms = time.time() * 1000.0
    with _lock:
        open_syms = sorted({v["sym"] for v in _state["open"].values() if v["tf"] == tf})
        prio = list(_state["prio"])
        _state["prio"] = []
    todo = []
    for sym in prio:                                       # flip: a coin that just exited is looked at again at once
        if sym not in todo:
            todo.append(sym)
    for sym in open_syms:                                  # every open trade is re-read when its new candle is ready
        if sym not in todo and now_ms >= _next_eval.get((sym, tf), 0):
            todo.append(sym)
    busy = ai_priority.app_busy()
    for sym in todo[:6]:
        _free_scan(sym)
        if busy:
            time.sleep(0.2)
    if busy and time.time() - _st["last_scan"] < EXPLORE_BUSY_S:
        return
    wl = L._watchlist()
    if wl:
        with _lock:
            sym = wl[_state["rr"] % len(wl)]
            _state["rr"] += 1
        if sym not in todo:
            _free_scan(sym)
    _st["last_scan"] = time.time()
    _st["scans"] += 1


def _free_live_view(now):
    out = []
    with _lock:
        opn = list(_state["open"].values())
    for v in opn:
        sgn = 1.0 if v["side"] == "BUY" else -1.0
        px = float(v.get("now") or v["entry"])
        lev = float(_cfg("leverage", 1) or 1)
        pnl = (px - v["entry"]) / v["entry"] * 100.0 * sgn * lev
        out.append({"k": v["k"], "sym": v["sym"], "side": v["side"], "tf": v["tf"], "age_min": round((now - v["opened"]) / 60.0), "why": v["why"],
                    "entry": v["entry"], "sl": v.get("sl_now", v["sl"]), "sl0": v.get("sl0", v["sl"]), "now": px,
                    "pnl": round(pnl, 2), "mfe": v.get("mfe"), "mae": v.get("mae"), "chart": _chart.get(v["k"], []),
                    "cd": (_pack(v, False, v["cand"]) if v.get("cand") else None)})
    out.sort(key=lambda r: r["age_min"])
    return out


def _free_learned():
    items = []
    for k, v in _state["learn"].items():
        if k.endswith("|BUY") or k.endswith("|SELL"):
            if not k.startswith(("stop|", "exit|")) and v[0] >= 3:
                items.append((v[1] / v[0], v[0], k))
    items.sort(reverse=True)
    best = [{"read": k, "avg": round(a, 2), "n": n} for a, n, k in items[:3] if a > 0]
    worst = [{"read": k, "avg": round(a, 2), "n": n} for a, n, k in items[::-1][:3] if a < 0]
    ex = sorted(((v[1] / v[0], v[0], k[5:]) for k, v in _state["learn"].items() if k.startswith("exit|") and v[0] >= 3), reverse=True)
    return {"buckets": sum(1 for k in _state["learn"] if k.endswith(("|BUY", "|SELL")) and not k.startswith(("stop|", "exit|"))),
            "trusted": len(items), "best": best, "worst": worst,
            "exit_best": [{"style": k, "avg": round(a, 2), "n": n} for a, n, k in ex[:2]]}


def _scan_one():
    wl = L._watchlist()
    if not wl:
        return
    tf = P._tf()
    with _lock:
        sym = wl[_state["rr"] % len(wl)]
        _state["rr"] += 1
    _st["last_sym"] = sym
    cs = L._fetch_limit(sym, tf, L.LIVE_LIMIT)
    if not cs or len(cs) < F.MIN_BARS + 5:
        return
    lev = float(_cfg("leverage", 1) or 1)
    fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
    S = F.build(cs)
    _resolve(sym, tf, S, lev, fee)
    with _lock:
        n_open = len(_state["open"])
        have_sym = any(v["sym"] == sym and v["tf"] == tf for v in _state["open"].values())
        known = set(_state["open"].keys()) | {d["k"] for d in _state["done"][-200:]}
    if n_open >= max_open() or have_sym:
        return
    from .strategy import ABCDStrategy
    strat = ABCDStrategy()
    bot_sig = None
    try:
        bot_sig = strat.generate_signal(cs[-L.SIG_WINDOW:], sym, L.TF_MIN[tf])
    except Exception:
        bot_sig = None
    ctx = L._ctx_series(sym)
    book = P._book(tf)["book"]
    t_close = S["t"][S["n"] - 1] + L.TF_MS[tf] - 1
    for side in ("BUY", "SELL"):
        key = "%s|%s|%d|%s" % (sym, tf, t_close, side[0])
        if key in known:
            continue
        if bot_sig is not None and bot_sig.action == side:
            continue                                        # the bot fires here: the AI Pick judges it, not this module
        h = _hypothetical(strat, sym, tf, cs, S, ctx, side)
        if not h:
            continue
        res = P.decide(side, h["labels"], book)
        if explore():
            if res["call"] == "SKIP":
                continue                                    # a situation the AI Pick proved to lose is never taken
            ok_, why_ = _read(side, h["labels"])
            if not ok_:
                continue
            res = {"call": "TAKE", "why": why_ + ("  (AI Pick agrees)" if res["call"] == "TAKE" else "")}
        elif res["call"] != "TAKE":
            continue
        rec = {"k": key, "sym": sym, "tf": tf, "side": side, "bar_t": h["bar_t"], "t_close": h["t_close"], "entry": h["entry"],
               "sl": h["sl"], "tps": h["tps"], "why": res["why"], "opened": time.time(), "mode": "explore" if explore() else "gate"}
        with _lock:
            _state["open"][key] = rec
            _mark()
        break                                               # one own signal per coin at a time


def _tick():
    _load()
    if not enabled():
        _st["gate"] = {"open": False, "why": "Switched off (selfsignal_enabled = false)."}
        return
    ok, why = gate()
    _st["gate"] = {"open": ok, "why": why}
    if not ok:
        _st["tick_ok"] = time.time()
        return
    with _lock:
        if not _state["gate_open_at"]:
            _state["gate_open_at"] = time.time()            # remembered, so the screen can say "running since ..."
            _mark()
    if (not free()) and ai_priority.app_busy() and time.time() - _st["last_scan"] < (EXPLORE_BUSY_S if explore() else BUSY_SCAN_EVERY_S):
        return                                              # the screen comes first
    if free():
        _free_tick()
    else:
        _scan_one()
        _st["last_scan"] = time.time()
        _st["scans"] += 1
    _save()
    _st["tick_ok"] = time.time()


def _loop():
    time.sleep(150)                                         # let the bot, the lab and the AI Pick start first
    while True:
        try:
            _tick()
            _st["last_error"] = None
        except Exception as e:
            _st["last_error"] = "%s: %s" % (type(e).__name__, e)
            print(f"[AISelf] tick error (ignored): {e}")
        time.sleep(EXPLORE_TICK_S if (explore() or free()) else TICK_S)


def start():
    global _started
    if _started:
        return
    _started = True
    try:
        threading.Thread(target=_loop, name="ai-selfsignal", daemon=True).start()
    except Exception as e:
        print(f"[AISelf] could not start: {e}")


# ------------------------------------------------------------------ scoreboard
def _stats(vals):
    n = len(vals)
    if not n:
        return {"n": 0, "wr": 0.0, "avg": 0.0, "pf": None}
    win = sum(v for v in vals if v > 0)
    loss = -sum(v for v in vals if v < 0)
    return {"n": n, "wr": round(sum(1 for v in vals if v > 0) / n * 100.0, 1), "avg": round(sum(vals) / n, 3),
            "pf": None if loss <= 0 else round(win / loss, 2)}


def build():
    """Screen answer (GET /api/ai/selfsignal). Cheap: no candles are fetched here."""
    try:
        _load()
        tf = P._tf()
        with _lock:
            done = list(_state["done"])
            opn = list(_state["open"].values())
            dropped = _state["dropped"]
            opened_at = _state["gate_open_at"]
        ok, why = _st["gate"]["open"], _st["gate"]["why"]
        if not _st["scans"] and enabled():
            ok, why = gate()
        mine = _stats([d["roi"] for d in done])
        lev = float(_cfg("leverage", 1) or 1)
        fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
        bot = _stats([r["v"][X.LIVE] for r in X.lab_rows(tf, lev, fee)[-P.WINDOW:]])
        if mine["n"] < VERDICT_MIN_N:
            verdict = "Too early: %d of %d finished own signals. No verdict until then." % (mine["n"], VERDICT_MIN_N)
        elif mine["pf"] is not None and bot["pf"] is not None and mine["pf"] > bot["pf"] and mine["avg"] > 0:
            verdict = "The AI's own signals are ahead of the bot (profit factor %.2f vs %.2f). Keep watching; the next step would be paper trading them." % (mine["pf"], bot["pf"])
        else:
            verdict = "The AI's own signals are not better than the bot yet (profit factor %s vs %s). Nothing changes." % (
                "n/a" if mine["pf"] is None else "%.2f" % mine["pf"], "n/a" if bot["pf"] is None else "%.2f" % bot["pf"])
        recent = [{"sym": d["sym"], "side": d["side"], "roi": d["roi"], "how": d["how"], "t": d.get("closed"), "why": d.get("why")}
                  for d in reversed(done[-15:])]
        now = time.time()
        live = [{"sym": v["sym"], "side": v["side"], "age_min": round((now - v["opened"]) / 60.0), "why": v["why"]} for v in opn][:10]
        if free():
            live = _free_live_view(now)
            recent = [{"k": d.get("k"), "sym": d["sym"], "side": d["side"], "roi": d["roi"], "how": d["how"], "t": d.get("closed"),
                       "why": d.get("exit_why") or d.get("why"), "entry": d.get("entry"), "exit": d.get("exit_px"),
                       "cd": (_pack(d, True, d["cand"]) if (i < 8 and d.get("cand")) else None)}
                      for i, d in enumerate(reversed(done[-15:]))]
        return {"enabled": enabled(), "explore": explore(), "free": free(), "learned": _free_learned() if free() else None,
                "max_open": _free_cap() if free() else max_open(), "tf": tf, "ts": now, "gate_open": bool(ok), "gate_why": why,
                "running_since": opened_at or None, "mine": mine, "bot": bot, "open": len(opn), "dropped": dropped,
                "money": _money(done, live if free() else [], lev, fee),
                "verdict": verdict, "verdict_min_n": VERDICT_MIN_N, "recent": recent, "live": live,
                "last_symbol": _st["last_sym"], "scan_age_s": None if not _st["last_scan"] else int(now - _st["last_scan"]),
                "last_error": _st["last_error"],
                "note": "Paper only: no real trade is opened. Results are after fee, bot rule T4, on candles that closed AFTER the proven situations were counted."}
    except Exception as e:
        return {"enabled": enabled(), "error": "%s: %s" % (type(e).__name__, e), "ts": time.time()}


def _pack(v, closed, rows):
    """Chart data of one trade (open or finished). Used by the list (instant chart) and by free_trade()."""
    bar_t = int(v["bar_t"])
    end_t = int(v.get("exit_t") or 0) if closed else 0
    return {"ok": True, "k": v.get("k"), "sym": v["sym"], "tf": v["tf"], "side": v["side"], "state": "closed" if closed else "open",
            "entry": v["entry"], "sl0": v.get("sl0", v.get("sl")), "sl_now": v.get("sl_now", v.get("sl")),
            "sl_path": v.get("sl_path", []), "bar_t": bar_t, "exit_px": v.get("exit_px") if closed else None,
            "exit_t": (end_t or None) if closed else None, "roi": v.get("roi"), "how": v.get("how"),
            "why": v.get("why"), "exit_why": v.get("exit_why"), "mfe": v.get("mfe"), "mae": v.get("mae"),
            "covers_entry": bool(rows) and rows[0][0] <= bar_t, "candles": rows}


def _money(done, live, lev, fee):
    """How much margin the Free AI used and what it made or lost, in USDT. The margin per trade is the SAME size the
    paper bot uses (Settings > Invest Amount)."""
    mode = "fixed"
    try:
        val = float(_cfg("invest_amount", 10.0) or 0.0)           # Settings > Trade Risk > Invest Amount (USDT): what the paper bot uses too
    except Exception:
        val = 0.0
    margin = val if val > 0 else None
    rois = [float(d["roi"]) for d in done if isinstance(d.get("roi"), (int, float))]
    opn = [float(r["pnl"]) - fee for r in live if isinstance(r.get("pnl"), (int, float))]
    out = {"mode": mode, "margin": margin, "lev": lev, "open_n": len(live), "closed_n": len(rois),
           "win_n": sum(1 for x in rois if x > 0), "loss_n": sum(1 for x in rois if x < 0)}
    if margin:
        out.update(margin_in_use=round(len(live) * margin, 2),
                   margin_closed=round(len(rois) * margin, 2),
                   closed_usdt=round(sum(rois) / 100.0 * margin, 2),
                   won_usdt=round(sum(x for x in rois if x > 0) / 100.0 * margin, 2),
                   lost_usdt=round(sum(x for x in rois if x < 0) / 100.0 * margin, 2),
                   open_usdt=round(sum(opn) / 100.0 * margin, 2))
        out["total_usdt"] = round(out["closed_usdt"] + out["open_usdt"], 2)
    return out


def free_trade(key, allow_net=True):
    """Chart data of ONE free trade, open or finished: candles, entry, first stop, every stop move, exit.
    Candles come from the copy saved with the trade (instant). Only old trades without it need Binance (allow_net).
    The Free AI has no fixed take-profit: it leaves by its own reading, so there is no TP line. Read-only, never raises."""
    try:
        _load()
        with _lock:
            v = _state["open"].get(key)
            closed = False
            if v is None:
                for d in reversed(_state["done"]):
                    if d.get("k") == key:
                        v, closed = d, True
                        break
            v = dict(v) if v else None
        if not v:
            return {"ok": False, "error": "This trade was not found (it may be too old)."}
        sym, tf = v["sym"], v["tf"]
        bar_t = int(v["bar_t"])
        rows = v.get("cand") or []
        if not rows:
            if not allow_net:
                return {"ok": False, "need_net": True, "error": "needs candles from Binance"}
            cs = L._fetch_limit(sym, tf, L.LIVE_LIMIT)
            if not cs:
                return {"ok": False, "error": "Could not load the candles right now (Binance is busy). Try again in a minute."}
            step = L.TF_MS[tf]
            end_t = int(v.get("exit_t") or ((v.get("closed") or 0) * 1000)) if closed else 0
            first = bar_t - 25 * step
            rows = [[c["timestamp"], c["open"], c["high"], c["low"], c["close"]] for c in cs
                    if c["timestamp"] >= first and (not end_t or c["timestamp"] <= end_t + 12 * step)][-160:]
        return _pack(v, closed, rows)
    except Exception as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def status():
    return {"gate": _st["gate"], "scans": _st["scans"], "last_symbol": _st["last_sym"], "last_error": _st["last_error"],
            "tick_ago_s": None if not _st["tick_ok"] else int(time.time() - _st["tick_ok"])}
