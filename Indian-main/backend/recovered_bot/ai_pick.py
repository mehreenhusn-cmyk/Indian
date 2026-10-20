"""
ai_pick.py - AI PICK: on every bot signal the AI says TAKE, SKIP or WATCH, from what the old signals proved.

The idea (user's): the bot keeps its fixed EMA50-cross entry. The AI looks at the situation of each signal through
both indicators (main chart: SD zone / shape / size, price vs EMA, EMA turn, volume, higher timeframe. Pane: Z-score,
Z vs its average line, TSI, TSI vs signal, TSI zero line) and answers:
    TAKE   a situation of this signal is PROVEN to pay (and none is proven to lose)
    SKIP   a situation of this signal is PROVEN to lose
    WATCH  nothing is proven yet: the AI only watches and writes down what the bot made
No rule is written by hand. Every situation (single facts + combos from ai_desk) is counted on the finished Shadow Lab
signals of the bot's own rule, after fees, BUY and SELL apart. The count is the only teacher.

What "proven" means (no fixed "100 signals"):
    * break-even is calculated live from the bot's own results (avg loss / (avg win + avg loss)), after fees
    * a situation is TAKING when its avg net ROI is clearly above zero (EDGE_MIN) AND the evidence is strong
      (z >= Z_TAKE: avg divided by its own uncertainty, so a big edge needs few signals and a small edge needs many)
      AND both the older and the newer half are positive. Only a small floor (FLOOR_N) stops 3-4 lucky signals.
    * AVOID = clearly below zero with strong evidence
    * STOPPED = was TAKING before, but no longer shows the edge (it is re-checked every REBUILD_S on the newest WINDOW signals)
    * TAKE needs TWO taking situations, or one taking combo (one lonely fact is too easy to get by luck)

How the result is measured (the coach is NOT changed): the AI Coach still opens a virtual trade on EVERY bot signal
(that is how it keeps learning). This module only writes the decision per signal. The scoreboard then splits the coach's
finished trades into TAKE / SKIP / WATCH, so we see what the AI would have made by taking only its picks, and what the
bot lost on the signals the AI stayed out of ("saved").

Safety (same rules as the other AI modules): read-only toward the bot, own daemon thread, no network, own file
ai/ai_pick.json, setting pick_enabled (default True), every error swallowed.
Honest limits: many situations are tested, so a few will pass by luck; z >= Z_TAKE + both halves + 2 situations lowers
that but does not remove it. Virtual results have no slippage. A proven past is not a promise.
"""
import math
import os
import threading
import time

from . import ai_desk as D
from . import ai_exit_study as X
from . import ai_rowcache as RC

TICK_S = 6.0
REBUILD_S = 300.0            # the book of situations is re-counted this often (newest WINDOW signals)
WINDOW = 2500                # newest finished lab signals used for counting (about 4 days on 3m): old market behaviour fades out
FLOOR_N = 30                 # fewer finished signals than this: the AI never judges a situation
KEEP_MIN_N = 8               # situations with fewer signals are not even listed
EDGE_MIN = 0.3               # avg net ROI % a situation must be above (or below, for AVOID) zero
Z_TAKE = 2.0                 # evidence needed to TAKE
Z_AVOID = -1.3               # evidence needed to AVOID
GRACE_S = 180                # wait this long for the lab to write the labels of a new signal, then WATCH (NO_DATA)
START_AGE_S = 600            # a bot trade older than this when first seen is ignored (opened before the AI Pick started)
KEEP_DEC, KEEP_LOG = 600, 80

_lock = threading.RLock()
_file = None
_loaded = False
_started = False
_dirty = False
_state = {"dec": [], "pending": {}, "was": {}, "log": [], "since": 0.0}
_book_cache = {}             # tf -> {"t", "ver", "book", "be"}
_last = {"save": 0.0, "tick_ok": 0.0}


# ------------------------------------------------------------------ plumbing
def _cfg(name, default):
    try:
        from . import settings_store
        v = settings_store.get(name, default)
        return default if v is None else v
    except Exception:
        return default


def enabled():
    return bool(_cfg("pick_enabled", True))


def init(path):
    global _file
    try:
        os.makedirs(path, exist_ok=True)
        _file = os.path.join(path, "ai_pick.json")
    except Exception as e:
        print(f"[AIPick] init: {e}")


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
                d, _src = safe_io.read_json_safe(_file, "ai_pick")
                if isinstance(d, dict):
                    for k in ("dec", "log"):
                        if isinstance(d.get(k), list):
                            _state[k] = d[k]
                    for k in ("pending", "was"):
                        if isinstance(d.get(k), dict):
                            _state[k] = d[k]
                    _state["since"] = float(d.get("since") or 0.0)
        except Exception as e:
            print(f"[AIPick] load: {e}")
        if not _state["since"]:
            _state["since"] = time.time()
            _mark()


def _save(force=False):
    global _dirty
    with _lock:
        if not _file or not (_dirty or force):
            return
        if not force and time.time() - _last["save"] < 10:
            return
        try:
            from . import safe_io
            _state["dec"] = _state["dec"][-KEEP_DEC:]
            _state["log"] = _state["log"][-KEEP_LOG:]
            safe_io.write_json_atomic(_file, _state)
            _dirty = False
            _last["save"] = time.time()
        except Exception as e:
            print(f"[AIPick] save: {e}")


def _log(text):
    _state["log"].append({"t": time.time(), "text": text})
    _mark()


# ------------------------------------------------------------------ counting: situation -> proof
def _situations(labels):
    """[(text, kind name, is_combo)] for one signal's labels, same facts and combos the AI Desk reads."""
    out, seen = [], set()
    for name, kinds in D.COMBOS:
        vals = [labels.get(k) for k in kinds]
        if all(vals):
            txt = " + ".join(vals)
            if txt not in seen:
                seen.add(txt)
                out.append((txt, name, True))
    for k in D.READ_KINDS:
        t = labels.get(k)
        if t and t not in seen:
            seen.add(t)
            out.append((t, D.NICE_KIND.get(k, k), False))
    return out


def _stats(vals):
    """n, avg, win rate, z (avg divided by its own uncertainty), avg of the older half, avg of the newer half."""
    n = len(vals)
    if n == 0:
        return {"n": 0, "avg": 0.0, "wr": 0.0, "z": 0.0, "old": 0.0, "new": 0.0}
    avg = sum(vals) / n
    sd = math.sqrt(sum((x - avg) ** 2 for x in vals) / (n - 1)) if n > 1 else 0.0
    z = avg / (sd / math.sqrt(n)) if sd > 1e-9 else 0.0
    half = n // 2
    old, new = vals[:half], vals[half:]
    m = lambda v: sum(v) / len(v) if v else 0.0   # noqa: E731
    return {"n": n, "avg": avg, "wr": sum(1 for x in vals if x > 0) / n * 100.0, "z": z, "old": m(old), "new": m(new)}


def _raw_status(st):
    """-> (status, why). WATCHING | TAKING | AVOID. STOPPED is added later (needs memory of the past)."""
    n = st["n"]
    if n < FLOOR_N:
        return "WATCHING", "Only %d signals so far. The AI needs at least %d before it judges." % (n, FLOOR_N)
    if st["avg"] >= EDGE_MIN and st["z"] >= Z_TAKE and st["old"] > 0 and st["new"] > 0:
        return "TAKING", "Paid %+.1f%% on average over %d signals, and both the older and the newer half are positive." % (st["avg"], n)
    if st["avg"] <= -EDGE_MIN and st["z"] <= Z_AVOID:
        return "AVOID", "Lost %+.1f%% on average over %d signals." % (st["avg"], n)
    if st["avg"] > 0:
        return "WATCHING", "Looks positive (%+.1f%% over %d signals) but it is not proven yet." % (st["avg"], n)
    return "WATCHING", "No edge (%+.1f%% over %d signals)." % (st["avg"], n)


def _break_even(rows):
    """Live break-even win rate of the bot's own rule on these signals, after fees."""
    vals = [r["v"][X.LIVE] for r in rows]
    wins = [v for v in vals if v > 0]
    loss = [-v for v in vals if v < 0]
    if not vals:
        return {"n": 0, "wr": 0.0, "be": None, "avg_win": 0.0, "avg_loss": 0.0, "avg": 0.0}
    aw = sum(wins) / len(wins) if wins else 0.0
    al = sum(loss) / len(loss) if loss else 0.0
    be = al / (aw + al) * 100.0 if (aw + al) > 0 else None
    return {"n": len(vals), "wr": round(len(wins) / len(vals) * 100.0, 1), "be": None if be is None else round(be, 1),
            "avg_win": round(aw, 2), "avg_loss": round(al, 2), "avg": round(sum(vals) / len(vals), 3)}


def _count(tf, rows):
    """Pure counting (tests call this). rows = finished lab rows, oldest first -> {key: situation dict}."""
    groups = {}
    for r in rows:
        v = r["v"][X.LIVE]
        for txt, name, combo in _situations(r["lab"]):
            g = groups.setdefault((r["a"], txt), {"kind": name, "combo": combo, "vals": []})
            g["vals"].append(v)
    book = {}
    for (side, txt), g in groups.items():
        if len(g["vals"]) < KEEP_MIN_N:
            continue
        st = _stats(g["vals"])
        status, why = _raw_status(st)
        book["%s|%s" % (side, txt)] = {"side": side, "text": txt, "kind": g["kind"], "combo": g["combo"], "n": st["n"],
                                       "avg": round(st["avg"], 2), "wr": round(st["wr"], 1), "z": round(st["z"], 2),
                                       "old": round(st["old"], 2), "new": round(st["new"], 2), "status": status, "why": why}
    return book


def _apply_memory(book, now):
    """STOPPED = was TAKING before and is not any more. Logs every change in plain English. Caller holds _lock."""
    was = _state["was"]
    for key, c in book.items():
        if c["status"] == "TAKING":
            if key not in was or was[key].get("stopped"):
                _log("Started taking: %s %s (%+.1f%% over %d signals)." % (c["side"], c["text"], c["avg"], c["n"]))
            was[key] = {"since": (was.get(key) or {}).get("since") or now, "stopped": None}
        elif key in was:
            if c["status"] != "AVOID":
                c["status"] = "STOPPED"
                c["why"] = "Was taking this, but it no longer shows a proven edge on the newest signals (%+.1f%% over %d)." % (c["avg"], c["n"])
            if not was[key].get("stopped"):
                was[key]["stopped"] = now
                _log("Stopped taking: %s %s. %s" % (c["side"], c["text"], c["why"]))
    for key in list(was):                       # a taking situation that fell out of the list completely (too few signals now)
        if key not in book and not was[key].get("stopped"):
            was[key]["stopped"] = now
            _log("Stopped taking: %s (not enough recent signals any more)." % key.replace("|", " "))


def _tf():
    tf = str(_cfg("timeframe", "3m") or "3m")
    return tf if tf in ("3m", "5m", "15m") else "3m"


def _book(tf, force=False):
    """The counted book for one timeframe, re-counted at most every REBUILD_S. Counting runs OUTSIDE _lock."""
    now = time.time()
    with _lock:
        c = _book_cache.get(tf)
    if c and not force and now - c["t"] < REBUILD_S:
        return c
    lev = float(_cfg("leverage", 1) or 1)
    fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
    rows = X.lab_rows(tf, lev, fee)[-WINDOW:]
    book = _count(tf, rows)
    be = {"BUY": _break_even([r for r in rows if r["a"] == "BUY"]), "SELL": _break_even([r for r in rows if r["a"] == "SELL"]),
          "ALL": _break_even(rows)}
    with _lock:
        _apply_memory(book, now)
        c = {"t": now, "book": book, "be": be, "n": len(rows)}
        _book_cache[tf] = c
        _mark()
    return c


# ------------------------------------------------------------------ the decision
def decide(side, labels, book):
    """-> {'call': TAKE|SKIP|WATCH, 'why': plain English, 'cells': [...]} for one signal."""
    try:
        cells = []
        for txt, name, combo in _situations(labels):
            c = book.get("%s|%s" % (side, txt))
            if c:
                cells.append(c)
        avoid = [c for c in cells if c["status"] == "AVOID"]
        taking = [c for c in cells if c["status"] == "TAKING"]
        brief = lambda cs: [{"text": c["text"], "kind": c["kind"], "n": c["n"], "avg": c["avg"], "status": c["status"]} for c in cs[:4]]  # noqa: E731
        if avoid:
            w = min(avoid, key=lambda c: c["avg"])
            return {"call": "SKIP", "cells": brief(avoid),
                    "why": "SKIP: when '%s' showed up before, the bot lost %.1f%% on average over %d signals." % (w["text"], abs(w["avg"]), w["n"])}
        if len(taking) >= 2 or any(c["combo"] for c in taking):
            w = max(taking, key=lambda c: c["avg"])
            return {"call": "TAKE", "cells": brief(sorted(taking, key=lambda c: -c["avg"])),
                    "why": "TAKE: '%s' paid %+.1f%% on average over %d signals (win rate %.0f%%), in both the older and the newer half. %d proven situation(s) match this signal." % (
                        w["text"], w["avg"], w["n"], w["wr"], len(taking))}
        if taking:
            w = taking[0]
            return {"call": "WATCH", "cells": brief(taking),
                    "why": "WATCH: only one proven situation ('%s', %+.1f%% over %d) matches. One alone can be luck, so the AI waits for a second one." % (w["text"], w["avg"], w["n"])}
        solid = [c for c in cells if c["n"] >= KEEP_MIN_N]
        if solid:
            w = max(solid, key=lambda c: c["z"])
            return {"call": "WATCH", "cells": brief(sorted(solid, key=lambda c: -c["z"])),
                    "why": "WATCH: nothing is proven yet. Closest: '%s' (%+.1f%% over %d signals, needs more proof)." % (w["text"], w["avg"], w["n"])}
        return {"call": "WATCH", "cells": [], "why": "WATCH: the AI has not seen this situation often enough yet."}
    except Exception as e:
        return {"call": "WATCH", "cells": [], "why": "WATCH: decision error (%s)." % type(e).__name__}


# ------------------------------------------------------------------ one tick: new bot signals -> decisions
def _tick():
    _load()
    if not enabled():
        return
    now = time.time()
    tf_default = _tf()
    bots = D._bot_open()
    with _lock:
        known = {str(d["bot_id"]) for d in _state["dec"]}
        for b in bots:
            bid = str(b.get("id"))
            side = D._side(b)
            if not side or bid in known or bid in _state["pending"]:
                continue
            opened = float(b.get("opened_at_ts") or now)
            if now - opened > START_AGE_S:
                known.add(bid)                     # opened before the AI Pick existed: never judged, never counted
                continue
            _state["pending"][bid] = {"sym": b.get("symbol"), "side": side, "tf": b.get("timeframe") or tf_default,
                                      "opened": opened, "first": now}
            _mark()
        pend = dict(_state["pending"])
    for bid, p in pend.items():
        lab = None
        try:
            lab = D._labels_for(p["sym"], p["side"], p["tf"], p["opened"] * 1000.0)
        except Exception:
            lab = None
        if lab is None and now - p["first"] < GRACE_S:
            continue
        if lab is None:
            res = {"call": "WATCH", "cells": [], "no_data": True,
                   "why": "WATCH: the Shadow Lab had no reading for this signal within %d minutes, so the AI stayed out." % (GRACE_S // 60)}
        else:
            res = decide(p["side"], lab, _book(p["tf"])["book"])
        rec = {"t": now, "bot_id": bid, "sym": p["sym"], "side": p["side"], "tf": p["tf"], "call": res["call"],
               "why": res["why"], "cells": res.get("cells", []), "no_data": bool(res.get("no_data")),
               "delay_s": round(now - p["opened"], 1)}
        with _lock:
            _state["dec"].append(rec)
            _state["pending"].pop(bid, None)
            _mark()
    with _lock:
        for bid in [k for k, p in _state["pending"].items() if now - p["first"] > 3600]:
            _state["pending"].pop(bid, None)
    try:
        _book(tf_default)                           # keep the "what the AI learned" lists fresh even when no signal comes
    except Exception as e:
        print(f"[AIPick] book: {e}")
    _save()
    _last["tick_ok"] = time.time()


def _loop():
    time.sleep(12)
    while True:
        try:
            _tick()
        except Exception as e:
            print(f"[AIPick] tick error (ignored): {e}")
        time.sleep(TICK_S)


def start():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="ai-pick", daemon=True).start()


# ------------------------------------------------------------------ scoreboard + screen answer
def _group(rows):
    n = len(rows)
    bot = [r["bot_pnl"] for r in rows]
    ai = [r["pnl"] for r in rows]
    return {"n": n, "bot_pnl": round(sum(bot), 2), "ai_pnl": round(sum(ai), 2),
            "bot_wins": sum(1 for x in bot if x > 0), "ai_wins": sum(1 for x in ai if x > 0),
            "bot_wr": round(sum(1 for x in bot if x > 0) / n * 100.0, 1) if n else 0.0,
            "ai_wr": round(sum(1 for x in ai if x > 0) / n * 100.0, 1) if n else 0.0}


def calls_by_bot_id(limit=400):
    """{bot trade id: {'call': TAKE|SKIP|WATCH, 'why': one plain-English line}} for the Trades tab. Cheap, never raises."""
    try:
        _load()
        with _lock:
            decs = list(_state["dec"][-limit:])
        return {str(d["bot_id"]): {"call": d["call"], "why": d["why"]} for d in decs}
    except Exception:
        return {}


def scoreboard(closed, decisions):
    """closed = coach finished trades, decisions = this module's decisions. Only trades whose bot trade also closed count."""
    dec = {str(d["bot_id"]): d["call"] for d in decisions}
    take, skip, watch = [], [], []
    for c in closed:
        call = dec.get(str(c.get("bot_id")))
        if call is None or c.get("bot_pnl") is None or c.get("pnl") is None:
            continue
        {"TAKE": take, "SKIP": skip}.get(call, watch).append(c)
    out = _group(take + skip + watch)
    stayed = _group(skip + watch)
    return {"all": out, "take": _group(take), "skip": _group(skip), "watch": _group(watch), "stayed_out": stayed,
            "saved": round(-stayed["bot_pnl"], 2),
            "pick_vs_all": round(_group(take)["ai_pnl"] - out["ai_pnl"], 2)}


def build():
    """Screen answer (GET /api/ai/pick). Cheap: the book is re-counted by the thread, never here (except the first time)."""
    try:
        _load()
        tf = _tf()
        c = _book(tf)
        book = c["book"]
        by = {"TAKING": [], "STOPPED": [], "AVOID": [], "WATCHING": []}
        for v in book.values():
            by[v["status"]].append(v)
        taking = sorted(by["TAKING"], key=lambda x: -x["avg"])[:12]
        avoid = sorted(by["AVOID"], key=lambda x: x["avg"])[:8]
        stopped = sorted(by["STOPPED"], key=lambda x: x["avg"])[:6]
        close = sorted([v for v in by["WATCHING"] if v["avg"] > 0 and v["n"] >= KEEP_MIN_N], key=lambda x: -x["z"])[:8]
        try:
            from . import ai_coach as C
            with C._lock:
                closed = [{"bot_id": x.get("bot_id"), "pnl": x.get("pnl"), "bot_pnl": x.get("bot_pnl"), "sym": x.get("sym"),
                           "side": x.get("side"), "roi": x.get("roi")} for x in C._state["closed"]]
        except Exception:
            closed = []
        with _lock:
            decs = list(_state["dec"])
            log = list(_state["log"][-12:])
            since = _state["since"]
        sb = scoreboard(closed, decs)
        pnl_by = {str(x["bot_id"]): x for x in closed}
        recent = []
        for d in reversed(decs[-25:]):
            x = pnl_by.get(str(d["bot_id"]))
            recent.append({"t": d["t"], "sym": d["sym"], "side": d["side"], "call": d["call"], "why": d["why"],
                           "bot_pnl": None if not x else x.get("bot_pnl"), "ai_pnl": None if not x else x.get("pnl")})
        counts = {"taking": len(by["TAKING"]), "watching": len(by["WATCHING"]), "avoid": len(by["AVOID"]),
                  "stopped": len(by["STOPPED"]), "total": len(book), "signals": c["n"]}
        calls = {"TAKE": 0, "SKIP": 0, "WATCH": 0}
        for d in decs:
            calls[d["call"]] = calls.get(d["call"], 0) + 1
        return {"enabled": enabled(), "tf": tf, "ts": time.time(), "built_ts": c["t"], "since": since, "counts": counts,
                "calls": calls, "break_even": c["be"], "taking": taking, "avoid": avoid, "stopped": stopped, "close": close,
                "scoreboard": sb, "recent": recent, "log": list(reversed(log)),
                "rules": {"floor_n": FLOOR_N, "z_take": Z_TAKE, "edge_min": EDGE_MIN, "window": WINDOW, "rebuild_s": int(REBUILD_S)},
                "tick_age": None if not _last["tick_ok"] else int(time.time() - _last["tick_ok"])}
    except Exception as e:
        return {"enabled": enabled(), "error": "%s: %s" % (type(e).__name__, e), "ts": time.time()}
