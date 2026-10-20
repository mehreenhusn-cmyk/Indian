"""
ai_desk.py - the AI DESK: the AI's OWN virtual account that trades side by side with the bot.

  * The bot keeps doing its job (EMA50 cross -> trade). Nothing here touches it.
  * Entry: the SAME EMA50-cross signal the bot just took (so both always share the entry trigger).
    The AI looks at what Z-score, TSI and the SD bands were saying at that moment (Shadow Lab labels),
    checks how such situations ended in the OLD signals, and answers  LE / SKIP / WAIT.
    LE = AI opens its virtual trade. SKIP / WAIT = AI stays out (and we later see what the bot made on it).
  * Exit: the AI manages its own virtual trade. Default = hold like the bot (SL at the signal candle
    extreme, SL moves to entry after TP1). Only if the exit study CLEARLY proved that closing early at
    TP1/2/3 is better for this kind of signal, it closes early. After TP4 it may keep holding with a
    trailing stop (TP3 locked, then trailing). That "hold beyond TP4" is measured on its own trades and
    switched OFF automatically if it does not pay (see _hold_beyond_on).
  * Everything is net ROI % (price move x leverage - fee), equal margin per trade, no real money.

Safety (same rules as the other AI modules):
  - READ-ONLY toward the bot: only reads open positions, the live price cache and closed trades.
    Never opens/closes/blocks a bot trade, never changes a setting.
  - ONE small daemon thread, one tick every TICK_S, no candle downloads, no network of its own
    (live price comes from market_ws's cache) - it must not add lag to the app.
  - own file (ai/ai_desk.json, atomic write). Setting desk_enabled (default True) turns it off.
  - every public function swallows its own errors.
Honest limits: the virtual trade opens at the bot's exact entry price and is then moved by the live price, no slippage; an old-data match is not a promise;
with few matching old signals the answer is WAIT (no trade) on purpose.
"""
import os
import threading
import time

from . import ai_exit_study as X
from . import ai_rowcache as RC
from . import ai_shadow_lab as L

TICK_S = 5.0
MATCH_GRACE_S = 180          # wait this long for the lab to write the signal's labels, then give up (NO_DATA)
MATCH_GAP_MS = 2 * 3_600_000
MAX_HOLD_S = 24 * 3600       # a virtual trade is closed at market after 24h
MIN_N = 30                   # old signals a situation needs before the AI trusts it
EDGE_NET = 0.5               # avg net ROI % a situation must show to count as LE (or be <= -EDGE_NET for SKIP)
TRAIL_RISK_MULT = 1.0        # after TP4 the trailing stop keeps at least this many "signal-candle risks" (entry->first SL) of room
BEYOND_MIN = 10              # TP4 trades needed before "hold beyond TP4" is judged
KEEP_CLOSED = 300
KEEP_DECISIONS = 300
READ_KINDS = (
    # price behaviour
    "move", "phase", "z_zone", "z_move", "z_div", "zma_vs_trade", "momentum", "mtf_agree", "ema_turn", "volume",
    # TSI
    "tsi_vs_trade", "tsi_4zone", "tsi_zero", "warning", "ema_dist",
    # SD band: size, shape, where price sits
    "sd_shape", "sd_size", "sd_zone", "regime",
    # both indicators together
    "z_tsi",
)
NICE_KIND = {
    "move": "market", "phase": "phase", "z_zone": "Z zone", "z_move": "Z move", "z_div": "Z divergence",
    "zma_vs_trade": "Z avg-line", "momentum": "momentum", "mtf_agree": "bade timeframe", "ema_turn": "EMA turn",
    "volume": "volume", "tsi_vs_trade": "TSI", "tsi_4zone": "TSI vs signal", "tsi_zero": "TSI zero line", "ema_dist": "price vs EMA50", "warning": "reversal arrow",
    "sd_shape": "SD shape", "sd_size": "SD size", "sd_zone": "SD level", "regime": "cross regime", "z_tsi": "Z + TSI",
}
# Situations made of TWO or more facts. The first one is the most specific and keeps the old name.
COMBOS = (
    ("market + Z/TSI", ("move", "z_tsi")),
    ("SD size + shape", ("sd_size", "sd_shape")),
    ("SD level + TSI", ("sd_zone", "tsi_4zone")),
    ("Z zone + Z move", ("z_zone", "z_move")),
    ("regime + phase", ("regime", "phase")),
    ("EMA50 distance + TSI zero line", ("ema_dist", "tsi_zero")),
)

_lock = threading.RLock()
_file = None
_loaded = False
_started = False
_dirty = False
_state = {"open": {}, "closed": [], "decisions": [], "seen": {}}
_last = {"save": 0.0}


# ------------------------------------------------------------------ small helpers
def _cfg(name, default):
    try:
        from . import settings_store
        v = settings_store.get(name, default)
        return default if v is None else v
    except Exception:
        return default


def enabled():
    return bool(_cfg("desk_enabled", True))


def init(path):
    """Folder for ai_desk.json (same ai/ folder as the other AI files)."""
    global _file
    try:
        os.makedirs(path, exist_ok=True)
        _file = os.path.join(path, "ai_desk.json")
    except Exception as e:
        print(f"[AIDesk] init: {e}")


def _load():
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            if _file:
                from . import safe_io
                d, _src = safe_io.read_json_safe(_file, "ai_desk")
                if isinstance(d, dict):
                    for k in ("open", "seen"):
                        if isinstance(d.get(k), dict):
                            _state[k] = d[k]
                    for k in ("closed", "decisions"):
                        if isinstance(d.get(k), list):
                            _state[k] = d[k]
        except Exception as e:
            print(f"[AIDesk] load: {e}")


def _save(force=False):
    global _dirty
    with _lock:
        if not _file or not (_dirty or force):
            return
        if not force and time.time() - _last["save"] < 10:
            return
        try:
            from . import safe_io
            _state["closed"] = _state["closed"][-KEEP_CLOSED:]
            _state["decisions"] = _state["decisions"][-KEEP_DECISIONS:]
            cut = time.time() - 3 * 86400
            _state["seen"] = {k: v for k, v in _state["seen"].items() if v >= cut}
            safe_io.write_json_atomic(_file, _state)
            _dirty = False
            _last["save"] = time.time()
        except Exception as e:
            print(f"[AIDesk] save: {e}")


def _mark():
    global _dirty
    _dirty = True


def _net(raw_pct, lev, fee):
    return raw_pct * lev - fee


def _raw(side, entry, px):
    d = 1.0 if side == "BUY" else -1.0
    return (px - entry) / entry * 100.0 * d if entry else 0.0


def _side(p):
    s = str(p.get("action") or "").upper()
    return "BUY" if s == "BUY" else ("SELL" if s == "SELL" else "")


# ------------------------------------------------------------------ what the bot is doing (read-only)
_BOT_KEYS = ("id", "symbol", "action", "entry_price", "signal_stop_loss", "signal_tp1", "signal_tp2",
             "signal_tp3", "signal_tp4", "opened_at_ts", "timeframe", "leverage", "invest_usdt")


def _bot_open():
    try:
        from . import paper_trader as P
        with P._lock:
            return [{k: p.get(k) for k in _BOT_KEYS} for p in P._positions.values()]
    except Exception:
        return []


def _bot_closed():
    """{bot trade id: (net roi %, reason, net pnl USDT)} for recently closed bot trades."""
    out = {}
    try:
        from . import trade_store
        for t in trade_store.get_recent_closed(400, net=True):
            tid = t.get("id")
            if tid is not None:
                reason = str(t.get("status") or t.get("close_reason") or "").replace("CLOSED_", "")
                out[str(tid)] = (float(t.get("roi_pct") or 0.0), reason, float(t.get("pnl_usdt") or 0.0))
    except Exception:
        pass
    return out


def _price(sym):
    try:
        from . import market_ws
        px, _src, _err = market_ws.get_best_live_price(sym)
        return float(px) if px else None
    except Exception:
        return None


# ------------------------------------------------------------------ the decision (old signals -> LE / SKIP / WAIT)
def _cell_stats(rows):
    n = len(rows)
    vals = [r["v"][X.LIVE] for r in rows]
    half = n // 2
    old, new = vals[:half], vals[half:]
    m = lambda v: sum(v) / len(v) if v else 0.0   # noqa: E731
    return {"n": n, "avg": m(vals), "wr": sum(1 for v in vals if v > 0) / n * 100.0,
            "old": m(old), "new": m(new)}


def _verdict(st):
    if st["n"] < MIN_N:
        return "FEW"
    if st["avg"] >= EDGE_NET and st["old"] > 0 and st["new"] > 0:
        return "LE"
    if st["avg"] <= -EDGE_NET:
        return "SKIP"
    return "WAIT"


def _cell_dict(kind, text, sub, combo):
    st = _cell_stats(sub) if sub else {"n": 0, "avg": 0.0, "wr": 0.0, "old": 0.0, "new": 0.0}
    return {"kind": kind, "text": text, "n": st["n"], "avg": round(st["avg"], 2), "wr": round(st["wr"], 1),
            "verdict": _verdict(st), "combo": combo}


def decide(tf, side, labels, hist=None):
    """-> {'call': LE|SKIP|WAIT, 'why': plain text, 'cells': [...]}. `hist` = finished lab rows (tests).
    The AI looks at the situation through BOTH indicators (price/SD band/EMA, and Z-score + TSI):
      * COMBOS = several facts together (e.g. SD size + SD shape). A combo with >= MIN_N old signals is trusted.
        If any trusted combo says SKIP -> SKIP. LE only when MORE THAN HALF of the trusted combos say LE.
      * No trusted combo yet: single facts decide, and LE needs at least 2 of them and no SKIP among them."""
    try:
        lev = float(_cfg("leverage", 1) or 1)
        fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
        rows = hist if hist is not None else X.lab_rows(tf, lev, fee)
        rows = [r for r in rows if r["a"] == side]
        cs, seen = [], set()
        for name, kinds in COMBOS:
            vals = [labels.get(k) for k in kinds]
            if all(vals):
                sub = [r for r in rows if all(r["lab"].get(k) == v for k, v in zip(kinds, vals))]
                txt = " + ".join(vals)
                if txt not in seen:
                    seen.add(txt)
                    cs.append(_cell_dict(name, txt, sub, True))
        for k in READ_KINDS:
            t = labels.get(k)
            if t and t not in seen:
                seen.add(t)
                cs.append(_cell_dict(NICE_KIND.get(k, k), t, [r for r in rows if r["lab"].get(k) == t], False))
        trusted = [c for c in cs if c["combo"] and c["n"] >= MIN_N]
        if trusted:
            good = [c for c in trusted if c["verdict"] == "LE"]
            bad = [c for c in trusted if c["verdict"] == "SKIP"]
            if bad:
                w = min(bad, key=lambda c: c["avg"])
                return {"call": "SKIP", "cells": bad + good,
                        "why": f"Aisi situation ('{w['text']}') me pehle {w['n']} baar bot ka avg {w['avg']:+.1f}% raha. Skip."}
            if good and len(good) * 2 > len(trusted):
                w = max(good, key=lambda c: c["avg"])
                return {"call": "LE", "cells": good,
                        "why": f"Aisi situation ('{w['text']}') me pehle {w['n']} baar avg {w['avg']:+.1f}% mila, "
                               f"purane aur naye dono hisse me plus. Le."}
            return {"call": "WAIT", "cells": trusted,
                    "why": "Purane data me na pakka fayda, na pakka nuksaan (ya indicators ki situations aapas me alag baat bol rahi). Edge nahi dikha, isliye trade nahi."}
        good = [c for c in cs if c["verdict"] == "LE"]
        bad = [c for c in cs if c["verdict"] == "SKIP"]
        quiet = [c for c in cs if c["verdict"] not in ("LE", "SKIP")]
        if len(good) < 2:
            quiet, good = quiet + good, []      # one lonely LE is too easy to get by luck
        if bad:
            w = min(bad, key=lambda c: c["avg"])
            return {"call": "SKIP", "cells": bad + good,
                    "why": f"Aisi situation ('{w['text']}') me pehle {w['n']} baar bot ka avg {w['avg']:+.1f}% raha. Skip."}
        if good:
            w = max(good, key=lambda c: c["avg"])
            return {"call": "LE", "cells": good,
                    "why": f"Aisi situation ('{w['text']}') me pehle {w['n']} baar avg {w['avg']:+.1f}% mila, "
                           f"purane aur naye dono hisse me plus. Le."}
        if not [c for c in quiet if c["n"] >= MIN_N]:
            return {"call": "WAIT", "cells": quiet,
                    "why": "Is situation ka purana data kam hai (30 se kam signal). Pakka nahi, isliye trade nahi."}
        return {"call": "WAIT", "cells": quiet,
                "why": "Purane data me na pakka fayda, na pakka nuksaan. Edge nahi dikha, isliye trade nahi."}
    except Exception as e:
        return {"call": "WAIT", "cells": [], "why": f"Decision error: {type(e).__name__}"}


# ------------------------------------------------------------------ what the AI has learned so far (for the screen)
_learn_cache = {"key": None, "t": 0.0, "v": None}


def learned(tf=None):
    """Every situation (single facts + combos, BUY and SELL apart) with >= MIN_N finished old signals, sorted by
    what the bot made there. Same numbers decide() uses. Cached 60s (display only)."""
    try:
        lev = float(_cfg("leverage", 1) or 1)
        fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
        tf = tf or (_state["decisions"][-1]["tf"] if _state["decisions"] else None) or str(_cfg("timeframe", "3m") or "3m")
        key = (tf, lev, fee)
        now = time.time()
        if _learn_cache["key"] == key and now - _learn_cache["t"] < 60.0 and _learn_cache["v"] is not None:
            return _learn_cache["v"]
        all_rows = X.lab_rows(tf, lev, fee)
        total_cells, ready, good, bad = 0, 0, [], []
        for side in ("BUY", "SELL"):
            rows = [r for r in all_rows if r["a"] == side]
            groups = []
            for k in READ_KINDS:
                g = {}
                for r in rows:
                    t = r["lab"].get(k)
                    if t:
                        g.setdefault(t, []).append(r)
                groups += [(NICE_KIND.get(k, k), t, sub) for t, sub in g.items()]
            for name, kinds in COMBOS:
                g = {}
                for r in rows:
                    vals = [r["lab"].get(k) for k in kinds]
                    if all(vals):
                        g.setdefault(" + ".join(vals), []).append(r)
                groups += [(name, t, sub) for t, sub in g.items()]
            for kind, text, sub in groups:
                total_cells += 1
                if len(sub) < MIN_N:
                    continue
                ready += 1
                c = _cell_dict(kind, text, sub, False)
                c["side"] = side
                if c["verdict"] == "LE":
                    good.append(c)
                elif c["verdict"] == "SKIP":
                    bad.append(c)
        good.sort(key=lambda c: -c["avg"])
        bad.sort(key=lambda c: c["avg"])
        if ready == 0:
            msg = (f"AI ne {len(all_rows)} purane band signal dekhe ({tf}). Kisi situation ke 30 signal poore nahi hue, "
                   "isliye abhi kuch pakka nahi seekha.")
        else:
            msg = (f"{len(all_rows)} purane signal se {ready} situations ka pakka hisaab bana: "
                   f"{len(good)} lene layak, {len(bad)} chhodne layak.")
        v = {"tf": tf, "rows": len(all_rows), "cells": total_cells, "ready": ready, "msg": msg,
             "good": [{k: c[k] for k in ("side", "kind", "text", "n", "avg", "wr")} for c in good[:6]],
             "bad": [{k: c[k] for k in ("side", "kind", "text", "n", "avg", "wr")} for c in bad[:6]]}
        _learn_cache.update(key=key, t=now, v=v)
        return v
    except Exception as e:
        return {"tf": tf or "", "rows": 0, "cells": 0, "ready": 0, "msg": f"Seekha hua dikha nahi paya: {type(e).__name__}",
                "good": [], "bad": []}


def _exit_target(tf, labels):
    """TP number (1-4) the AI holds to. 4 = hold like the bot. Early close ONLY if the exit study is CLEAR."""
    try:
        have = set(v for v in labels.values() if isinstance(v, str))
        best, gain = 4, 0.0
        for s in (X.build(tf) or {}).get("scenarios", []):
            if s.get("verdict") == "CLEAR" and s.get("label") in have and s.get("gain", 0) > gain:
                b = s.get("best")
                best, gain = (int(b[1]) if b in ("T1", "T2", "T3") else 4), s["gain"]
        return best
    except Exception:
        return 4


def _labels_for(sym, side, tf, opened_ms):
    best, gap = None, MATCH_GAP_MS
    for r in RC.rows(tf):
        if r["sym"] == sym and r["a"] == side:
            g = abs(r["t"] - opened_ms)
            if g <= gap:
                best, gap = r, g
    return best["f"] if best else None


# ------------------------------------------------------------------ hold beyond TP4 (judged on its own trades)
def _beyond_stats():
    ex = [c["beyond_extra"] for c in _state["closed"] if c.get("beyond_extra") is not None]
    return {"n": len(ex), "sum": round(sum(ex), 2), "avg": round(sum(ex) / len(ex), 2) if ex else 0.0}


def _hold_beyond_on():
    b = _beyond_stats()
    return not (b["n"] >= BEYOND_MIN and b["sum"] < 0)


# ------------------------------------------------------------------ one virtual trade
def _open_virtual(bp, entry, call, why, target):
    return {"bot_id": bp["id"], "sym": bp["symbol"], "side": _side(bp), "tf": bp.get("timeframe") or "3m",
            "entry": entry, "sl": float(bp["signal_stop_loss"]), "be": False,
            "tps": [float(bp["signal_tp%d" % i]) for i in (1, 2, 3, 4)], "hit": 0, "best": entry,
            "trail": None, "target": target, "why": why, "t0": time.time(),
            "lev": float(bp.get("leverage") or _cfg("leverage", 1) or 1), "tp4_roi": None,
            "risk0": abs(entry - float(bp["signal_stop_loss"])),
            "inv": float(bp.get("invest_usdt") or 0.0)}


def _close_virtual(v, px, reason, bot_res):
    fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
    roi = _net(_raw(v["side"], v["entry"], px), v["lev"], fee)
    rec = {"bot_id": v["bot_id"], "sym": v["sym"], "side": v["side"], "tf": v["tf"], "roi": round(roi, 3),
           "reason": reason, "hit": v["hit"], "t0": v["t0"], "t1": time.time(), "why": v["why"],
           "beyond_extra": None, "inv": v.get("inv", 0.0), "pnl": round(v.get("inv", 0.0) * roi / 100.0, 4)}
    if v.get("tp4_roi") is not None:
        rec["beyond_extra"] = round(roi - v["tp4_roi"], 3)
    _state["closed"].append(rec)
    _state["open"].pop(str(v["bot_id"]), None)
    _mark()


def _step(v, px, bot_closed, bot_open_ids):
    """Move one virtual trade with the live price. Returns True if it closed."""
    d = 1.0 if v["side"] == "BUY" else -1.0
    fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
    if (px - v["best"]) * d > 0:
        v["best"] = px
    for i, tp in enumerate(v["tps"], 1):          # which TP has price touched (never goes back)
        if (px - tp) * d >= 0 and i > v["hit"]:
            v["hit"] = i
            if i == 1 and not v["be"]:
                v["be"], v["sl"] = True, v["entry"]       # same as the bot: SL to entry after TP1
            if i == 4 and v["tp4_roi"] is None:
                v["tp4_roi"] = _net(_raw(v["side"], v["entry"], tp), v["lev"], fee)
    if v["hit"] >= v["target"] and v["target"] < 4:
        _close_virtual(v, v["tps"][v["target"] - 1], f"TP{v['target']} (AI ne jaldi band kiya)", None)
        return True
    if v["hit"] >= 4:
        if not _hold_beyond_on():
            _close_virtual(v, v["tps"][3], "TP4", None)
            return True
        # Room behind the best price: the TP3->TP4 gap OR the signal candle's own risk, whichever is bigger.
        # The gap alone was tiny on quiet coins, so a normal 3m bounce stopped the AI out right after TP4
        # while price kept running (PHAROSUSDT: AI left ~1% above the low and the bot's TP4 exit was only
        # 1-3% worse). More room = the AI really holds a trend; a real reversal still hits the trail.
        gap = max(abs(v["tps"][3] - v["tps"][2]), float(v.get("risk0") or 0.0) * TRAIL_RISK_MULT)
        t = max(v["tps"][2] * d, (v["best"] - d * gap) * d) / d if d else v["tps"][2]
        if v["trail"] is None or (t - v["trail"]) * d > 0:
            v["trail"] = t
    stop = v["trail"] if v["trail"] is not None else v["sl"]
    if (px - stop) * d <= 0:
        why = "TRAIL (TP4 ke aage hold, profit lock)" if v["trail"] is not None else ("BE (entry pe)" if v["be"] else "SL")
        _close_virtual(v, stop, why, None)
        return True
    bid = str(v["bot_id"])
    if bid not in bot_open_ids and bid in bot_closed and bot_closed[bid][1] == "REVERSED":
        _close_virtual(v, px, "REVERSED (EMA ulta cross, bot jaisa)", None)
        return True
    if time.time() - v["t0"] > MAX_HOLD_S:
        _close_virtual(v, px, "TIMEOUT 24h", None)
        return True
    return False


# ------------------------------------------------------------------ one tick
def _tick():
    _load()
    if not enabled():
        return
    now = time.time()
    bots = _bot_open()
    bot_ids = {str(b["id"]) for b in bots}
    bot_closed = _bot_closed()
    with _lock:
        for d in _state["decisions"]:                   # remember what the bot made on each signal once it closed
            if d.get("bot_pnl") is None and str(d["bot_id"]) in bot_closed:
                bc = bot_closed[str(d["bot_id"])]
                d["bot_roi"], d["bot_pnl"] = round(bc[0], 3), round(bc[2], 4)
                _mark()
        for b in bots:
            bid = str(b["id"])
            if bid in _state["seen"] or not _side(b) or b.get("signal_stop_loss") is None \
                    or any(b.get("signal_tp%d" % i) is None for i in (1, 2, 3, 4)):
                if bid not in _state["seen"] and _side(b):
                    _state["seen"][bid] = now           # top-up trade without SL/TP levels: ignore
                continue
            tf = b.get("timeframe") or "3m"
            opened = float(b.get("opened_at_ts") or now)
            lab = _labels_for(b["symbol"], _side(b), tf, opened * 1000.0)
            if lab is None and now - opened < MATCH_GRACE_S:
                continue                                  # lab has not written this signal yet - try again
            _state["seen"][bid] = now
            bot_entry = float(b["entry_price"])         # the AI trade opens at the BOT's exact entry price,
            px = _price(b["symbol"]) or bot_entry       # never at "the price a few seconds later" (fair Bot vs AI)
            if lab is None:
                call, why, cells = "WAIT", "Lab me is signal ke indicators nahi mile. Trade nahi.", []
            else:
                r = decide(tf, _side(b), lab)
                call, why, cells = r["call"], r["why"], r["cells"]
            rec = {"t": now, "bot_id": b["id"], "sym": b["symbol"], "side": _side(b), "tf": tf, "call": call,
                   "why": why, "cells": cells[:3], "px": px, "inv": float(b.get("invest_usdt") or 0.0),
                   "bot_roi": None, "bot_pnl": None}
            if call == "LE":
                tgt = _exit_target(tf, lab or {})
                rec["target"] = tgt
                _state["open"][bid] = _open_virtual(b, bot_entry, call, why, tgt)
            _state["decisions"].append(rec)
            _mark()
        for bid, v in list(_state["open"].items()):
            px = _price(v["sym"])
            if px:
                _step(v, px, bot_closed, bot_ids)
                _mark()
    _save()


def _loop():
    time.sleep(30)
    while True:
        try:
            _tick()
        except Exception as e:
            print(f"[AIDesk] tick error (ignored): {e}")
        time.sleep(TICK_S)


def start():
    """Start the background thread once. Safe to call repeatedly."""
    global _started
    if _started:
        return
    _started = True
    try:
        threading.Thread(target=_loop, name="ai-desk", daemon=True).start()
    except Exception as e:
        print(f"[AIDesk] could not start: {e}")


# ------------------------------------------------------------------ what the screen shows
def _sum(rs):
    n = len(rs)
    return {"n": n, "avg": round(sum(rs) / n, 2) if n else 0.0, "total": round(sum(rs), 2),
            "wr": round(sum(1 for x in rs if x > 0) / n * 100.0, 1) if n else 0.0}


def _side_sum(rois, pnls, opened):
    """One column of the Bot-vs-AI table."""
    n = len(rois)
    return {"closed": n, "open": opened, "wins": sum(1 for x in pnls if x > 0), "losses": sum(1 for x in pnls if x < 0),
            "pnl": round(sum(pnls), 2), "avg": round(sum(rois) / n, 2) if n else 0.0,
            "wr": round(sum(1 for x in pnls if x > 0) / n * 100.0, 1) if n else 0.0}


def _scorecard(decs, ai_by_bot):
    """'AI ki galtiyan': every decision that has an outcome is RIGHT or WRONG.
      SKIP/WAIT + the bot lost = RIGHT (loss avoided);  SKIP/WAIT + the bot won = WRONG (profit missed).
      LE + the AI trade made money = RIGHT;  LE + it lost = WRONG.
    A mistake keeps its situation text, so it is visible WHICH situation fooled the AI.
    Nothing here changes a rule by itself: rules only change from 30+ old signals (decide())."""
    right = wrong = 0
    mistakes = []
    for d in decs:
        if d["call"] == "LE":
            c = ai_by_bot.get(str(d["bot_id"]))
            if c is None:
                continue
            ok = c.get("pnl", 0.0) > 0
            res = c.get("pnl", 0.0)
        else:
            if d.get("bot_pnl") is None:
                continue
            ok = d["bot_pnl"] <= 0
            res = d["bot_pnl"]
        if ok:
            right += 1
        else:
            wrong += 1
            cell = (d.get("cells") or [{}])[0]
            mistakes.append({"t": d["t"], "sym": d["sym"], "side": d["side"], "call": d["call"],
                             "result": round(res, 2), "situation": cell.get("text") or ""})
    n = right + wrong
    return {"n": n, "right": right, "wrong": wrong, "right_pct": round(right / n * 100.0, 1) if n else 0.0,
            "mistakes": mistakes[-5:][::-1]}


def build():
    """Everything the AI Desk screen needs, in plain words. Never raises."""
    try:
        _load()
        fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
        bot_closed = _bot_closed()
        with _lock:
            closed = list(_state["closed"])
            decs = [dict(d) for d in _state["decisions"]]
            opens = [dict(v) for v in _state["open"].values()]
        for d in decs:                       # latest bot result (the tick stores it, this covers the gap)
            if d.get("bot_pnl") is None and str(d["bot_id"]) in bot_closed:
                bc = bot_closed[str(d["bot_id"])]
                d["bot_roi"], d["bot_pnl"] = bc[0], bc[2]
        ai_by_bot = {str(c["bot_id"]): c for c in closed}
        ai_open_ids = {str(v["bot_id"]) for v in opens}
        # open virtual trades (live)
        op, open_pnl = [], 0.0
        for v in opens:
            px = _price(v["sym"])
            roi = _net(_raw(v["side"], v["entry"], px), v["lev"], fee) if px else None
            if roi is not None:
                open_pnl += v.get("inv", 0.0) * roi / 100.0
            stage = ("TP4 ke aage trail" if v["trail"] is not None else
                     f"TP{v['hit']} ho chuka" if v["hit"] else "entry ke baad, TP1 ka intezaar")
            op.append({"sym": v["sym"], "side": v["side"], "entry": v["entry"], "px": px,
                       "roi": round(roi, 2) if roi is not None else None, "stage": stage,
                       "target": v["target"], "why": v["why"], "since": v["t0"]})
        by_call = {c: sum(1 for d in decs if d["call"] == c) for c in ("LE", "SKIP", "WAIT")}
        n_all = len(decs)
        # BOT column: every signal the bot traded (the Desk sees every bot trade)
        bot_done = [d for d in decs if d.get("bot_pnl") is not None]
        bot_col = _side_sum([d["bot_roi"] for d in bot_done], [d["bot_pnl"] for d in bot_done], n_all - len(bot_done))
        bot_col["traded"] = n_all
        # AI column: only the signals it took
        ai_col = _side_sum([c["roi"] for c in closed], [c.get("pnl", 0.0) for c in closed], len(opens))
        ai_col["traded"] = by_call["LE"]
        # signals the AI left out (SKIP / WAIT): what the bot made on them
        left = [d for d in decs if d["call"] != "LE"]
        left_done = [d for d in left if d.get("bot_pnl") is not None]
        left_pnl = round(sum(d["bot_pnl"] for d in left_done), 2)
        skipped = {"n": len(left), "closed": len(left_done), "bot_pnl": left_pnl,
                   "bot_wins": sum(1 for d in left_done if d["bot_pnl"] > 0),
                   "bot_losses": sum(1 for d in left_done if d["bot_pnl"] < 0)}
        # fair comparison on the SAME finished signals: bot closed AND (AI left it OR AI closed it)
        same = [d for d in decs if d.get("bot_pnl") is not None
                and (d["call"] != "LE" or str(d["bot_id"]) in ai_by_bot)]
        same_bot = round(sum(d["bot_pnl"] for d in same), 2)
        same_ai = round(sum(ai_by_bot[str(d["bot_id"])].get("pnl", 0.0) for d in same if d["call"] == "LE"), 2)
        taken_same = [d for d in same if d["call"] == "LE"]
        exit_effect = round(sum(ai_by_bot[str(d["bot_id"])].get("pnl", 0.0) - d["bot_pnl"] for d in taken_same), 2)
        entry_effect = round(-sum(d["bot_pnl"] for d in same if d["call"] != "LE"), 2)
        diff = round(same_ai - same_bot, 2)
        beyond = _beyond_stats()
        if len(same) < 5:
            head = "AI abhi seekh raha hai. Kam se kam 5 signal band hone do, phir bot vs AI ka hisaab pakka dikhega."
        elif diff > 0:
            head = f"Ab tak {len(same)} band signal par AI bot se {diff:+.2f} USDT aage hai."
        elif diff < 0:
            head = f"Ab tak {len(same)} band signal par AI bot se {abs(diff):.2f} USDT peeche hai."
        else:
            head = f"Ab tak {len(same)} band signal par AI aur bot barabar hain."
        if by_call["LE"] == 0 and n_all >= 5:
            head += " AI ne abhi tak ek bhi trade nahi li, purane data me pakka edge nahi mila."
        return {
            "ts": time.time(), "enabled": enabled(), "headline": head,
            "signals": n_all, "calls": by_call,
            "bot": bot_col, "ai": ai_col, "ai_open_pnl": round(open_pnl, 2),
            "skipped": skipped,
            "compare": {"n": len(same), "bot": same_bot, "ai": same_ai, "diff": diff,
                        "entry_effect": entry_effect, "exit_effect": exit_effect},
            "beyond": {**beyond, "on": _hold_beyond_on(),
                       "msg": ("TP4 ke aage hold: abhi test ho raha hai." if beyond["n"] < BEYOND_MIN else
                               ("TP4 ke aage hold ne extra " + f"{beyond['sum']:+.1f}% diya. Chalu." if beyond["sum"] >= 0
                                else f"TP4 ke aage hold se {beyond['sum']:+.1f}% gaya. AI ne ise band kar diya."))},
            "learned": learned(),
            "scorecard": _scorecard(decs, ai_by_bot),
            "open": op,
            "recent": [{"t": d["t"], "sym": d["sym"], "side": d["side"], "call": d["call"], "why": d["why"],
                        "bot": (round(d["bot_pnl"], 2) if d.get("bot_pnl") is not None else None),
                        "ai": (round(ai_by_bot[str(d["bot_id"])].get("pnl", 0.0), 2)
                               if str(d["bot_id"]) in ai_by_bot else None)}
                       for d in decs[-15:]][::-1],
            "caveats": ["Virtual khata hai, asli paisa nahi. AI ka margin har trade me wahi jo bot ka tha.",
                        "Paisa = price move x leverage minus fee. Bot ka koi trade AI se block ya close nahi hota."],
        }
    except Exception as e:
        return {"ts": time.time(), "enabled": False, "headline": "", "error": f"{type(e).__name__}: {e}",
                "open": [], "recent": []}


def reset():
    """Clear the AI's virtual account (the bot is untouched)."""
    try:
        _load()
        with _lock:
            _state.update(open={}, closed=[], decisions=[], seen={})
            _mark()
        _save(force=True)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
