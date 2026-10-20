"""
ai_exit_learn.py - teaches the AI "indicators ki ye situation ho to nikal jao, ye ho to hold karo".

The question it answers for every closed candle of a trade:
    "If I close the trade RIGHT NOW, or keep managing it the normal way until it ends - which gives more?"
  delta = (final result of the normal management) - (result if closed now)      [price % in the trade direction]
  delta < 0 on average in a situation  ->  closing now was better there  (BOOK)
  delta > 0 on average                 ->  holding was better there      (HOLD)
This replaces the old question "did price go my way over the next 3 candles?", which says nothing about where
the trade finally ends. Fee is the same for both choices (one exit), so it cancels out of delta.

Where the data comes from: the Shadow Lab already replays thousands of OLD signals on real candles (winners AND
losers, finished trades). For each of them ai_shadow_lab._process calls learn() here, which walks the trade
candle by candle, reads the situation at every candle close and notes delta. So the AI does not have to wait for
its own trades - it studies every closed trade the lab has seen, from day one, and keeps adding new ones daily.

The situation = what the indicators say RELATIVE TO THE TRADE (so BUY and SELL share the same table):
  tsi : TSI vs its signal line  (with the trade or against, widening or fading)
  zz  : Z-score zone (stretched / with / middle / against) + whether it is rising or falling for the trade
  ema : EMA50 slope for the trade        sd : SD band expanding / shrinking / steady
  singles + pairs/triples of them are tables.

Honesty rules (same spirit as the other AI modules):
  - each (trade, situation) counts ONCE (the first candle it appeared) - candles of one trade are not 20 samples
  - a verdict needs >= MIN_HALF trades in EACH of two independent halves (split by a hash of the signal) and the
    same sign in both halves, and size >= EDGE (ROI points at the current leverage). Otherwise: no verdict.
  - READ-ONLY: this module never opens/closes/blocks anything. evaluate() only answers; the Coach decides.
  - every public function swallows its own errors.
"""
import threading
import time
import zlib

REF_MAX_BARS = 300      # same horizon as the Shadow Lab simulation
MIN_HALF = 12           # trades per half  (>= 24 trades per situation)
EDGE_ROI = 1.0          # ROI points a situation must be better/worse than "normal management" to count
SEEN_CAP = 40000
TAG_MAX_AGE_S = 3 * 3600  # a replayed signal gets the bigger-trend tag only if it is this young (the cached 1h/4h/1d picture is "now")
BUCKET_NICE = {"W": "bade trend ke SAATH", "A": "bade trend ke ULTA", "O": "bade trend side/mixed"}
SAVE_EVERY_S = 60

_lock = threading.RLock()
_loaded = False
_dirty = False
_last_save = 0.0
_file_override = None
_stats = {}             # key -> [n_half0, sum_delta_half0, n_half1, sum_delta_half1]   (delta in price %)
_seen = {}              # crc32(signal key) -> 1


# ------------------------------------------------------------------ files
def _file():
    if _file_override:
        return _file_override
    try:
        import os
        from . import ai_shadow_lab as L
        return os.path.join(L._dir, "ai_exit_learn.json") if L._dir else None
    except Exception:
        return None


def _load():
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            f = _file()
            if not f:
                return
            from . import safe_io
            d, _src = safe_io.read_json_safe(f, "ai_exit_learn")
            if isinstance(d, dict):
                if isinstance(d.get("stats"), dict):
                    for k, v in d["stats"].items():
                        if isinstance(v, list) and len(v) == 4:
                            _stats[k] = [int(v[0]), float(v[1]), int(v[2]), float(v[3])]
                if isinstance(d.get("seen"), list):
                    for x in d["seen"]:
                        _seen[int(x)] = 1
        except Exception as e:
            print(f"[ExitLearn] load: {e}")


def _save(force=False):
    global _dirty, _last_save
    with _lock:
        if not _dirty:
            return
        if not force and time.time() - _last_save < SAVE_EVERY_S:
            return
        f = _file()
        if not f:
            return
        try:
            from . import safe_io
            if len(_seen) > SEEN_CAP:
                for k in list(_seen)[: len(_seen) - SEEN_CAP]:
                    _seen.pop(k, None)
            safe_io.write_json_atomic(f, {"stats": _stats, "seen": list(_seen)})
            _dirty = False
            _last_save = time.time()
        except Exception as e:
            print(f"[ExitLearn] save: {e}")


# ------------------------------------------------------------------ the situation at one closed candle
ZONE_NICE = {"Zstretch": "Z bahut khicha", "Zwith": "Z trade ke saath", "Zmid": "Z beech me", "Zagainst": "Z ulta"}
MOVE_NICE = {"up": "badh raha", "down": "gir raha", "flat": "flat"}
TSI_NICE = {"T+up": "TSI saath, majboot", "T+fade": "TSI saath, kamzor", "T-recover": "TSI ulta, sambhal raha",
            "T-down": "TSI ulta, badh raha"}
EMA_NICE = {"EMA+": "EMA50 trade ke saath", "EMA-": "EMA50 trade ke ulta", "EMA0": "EMA50 flat"}
SD_NICE = {"SDwide": "SD band faila", "SDnarrow": "SD band sikuda", "SDsteady": "SD band steady"}


def state(S, j, d):
    """Labels of candle j relative to the trade direction d (+1 long / -1 short). None if not computable."""
    try:
        z, diff, e50, std, w = S["z"], S["diff"], S["e50"], S["std"], S["width"]
        if j < 25:
            return None
        zj, z3, dj, dp = z[j], z[j - 3], diff[j], diff[j - 1]
        e, e10, sd, wj, w20 = e50[j], e50[j - 10], std[j], w[j], w[j - 20]
        if None in (zj, z3, dj, dp, e, e10, sd, wj, w20) or not sd or not w20:
            return None
        fav = dj * d > 0
        widening = abs(dj) > abs(dp)
        tsi = ("T+up" if widening else "T+fade") if fav else ("T-down" if widening else "T-recover")
        zd = zj * d
        zone = "Zstretch" if zd >= 2.0 else ("Zwith" if zd >= 0.5 else ("Zmid" if zd > -0.5 else "Zagainst"))
        mv = (zj - z3) * d
        move = "up" if mv > 0.15 else ("down" if mv < -0.15 else "flat")
        es = (e - e10) / sd * d
        ema = "EMA+" if es > 0.15 else ("EMA-" if es < -0.15 else "EMA0")
        wr = wj / w20
        sdl = "SDwide" if wr > 1.15 else ("SDnarrow" if wr < 0.87 else "SDsteady")
        return {"tsi": tsi, "zz": zone + "/" + move, "ema": ema, "sd": sdl}
    except Exception:
        return None


def keys(lab):
    """[(table key, is_combo)] - every single fact and some combinations."""
    t, z, e, s = "tsi=" + lab["tsi"], "zz=" + lab["zz"], "ema=" + lab["ema"], "sd=" + lab["sd"]
    return [(t, False), (z, False), (e, False), (s, False),
            (t + " & " + z, True), (t + " & " + e, True), (z + " & " + s, True), (t + " & " + z + " & " + e, True)]


def nice(key):
    key, _, tg = str(key).partition("@")
    out = []
    for part in key.split(" & "):
        k, v = part.split("=", 1)
        if k == "zz":
            zn, mv = v.split("/")
            out.append(f"{ZONE_NICE.get(zn, zn)}, {MOVE_NICE.get(mv, mv)}")
        else:
            out.append({"tsi": TSI_NICE, "ema": EMA_NICE, "sd": SD_NICE}[k].get(v, v))
    return " + ".join(out) + ((" [" + BUCKET_NICE.get(tg, tg) + "]") if tg else "")


def describe(lab):
    """The current situation in plain words (for the screen)."""
    try:
        return " | ".join([TSI_NICE[lab["tsi"]], nice("zz=" + lab["zz"]), EMA_NICE[lab["ema"]], SD_NICE[lab["sd"]]])
    except Exception:
        return ""


# ------------------------------------------------------------------ replay of one finished signal
def replay(S, i, is_long, entry, sl, tps):
    """Walk the trade candle by candle with the NORMAL management (SL to entry after TP1, TP4 then a trailing stop
    with room = max(TP3-TP4 gap, signal-candle risk), opposite EMA cross exits).
    -> (events, final) with events = [(candle j, labels, result if closed at that close)], final = result of the normal
    management (all in price %, trade direction). None while the trade has not finished inside the data."""
    d = 1.0 if is_long else -1.0
    h, l, c, n = S["h"], S["l"], S["c"], S["n"]
    end = min(n - 1, i + REF_MAX_BARS)
    opp = S["xdn"] if is_long else S["xup"]
    risk0 = abs(entry - sl)
    cur_sl, be, hit, best, trail = sl, False, 0, entry, None
    events, final = [], None
    pct = lambda px: (px - entry) / entry * 100.0 * d
    for j in range(i + 1, end + 1):
        hh, ll = h[j], l[j]
        stop = trail if trail is not None else cur_sl
        if (ll <= stop) if is_long else (hh >= stop):
            final = pct(stop)
            break
        ext = hh if is_long else ll
        if (ext - best) * d > 0:
            best = ext
        for k, tp in enumerate(tps, 1):
            if ((hh >= tp) if is_long else (ll <= tp)) and k > hit:
                hit = k
        if hit >= 1 and not be and ((entry > cur_sl) if is_long else (entry < cur_sl)):
            cur_sl, be = entry, True                       # applies from the next candle
        if hit >= 4:
            gap = max(abs(tps[3] - tps[2]), risk0)
            t = max(tps[2] * d, (best - d * gap) * d) / d
            if trail is None or (t - trail) * d > 0:
                trail = t
        if opp[j]:
            final = pct(c[j])
            break
        lab = state(S, j, d)
        if lab:
            events.append((j, lab, pct(c[j])))
    if final is None:
        if end - i >= REF_MAX_BARS:
            final = pct(c[end])
        else:
            return None
    return events, final


def learn(key, S, i, is_long, entry, sl, tps):
    """Called by the Shadow Lab for every signal it replays. Safe to call again for the same signal (counted once)."""
    global _dirty
    try:
        _load()
        h = zlib.crc32(str(key).encode()) & 0xFFFFFFFF
        with _lock:
            if h in _seen:
                return False
        r = replay(S, i, is_long, float(entry), float(sl), [float(x) for x in tps])
        if r is None:
            return False                                   # still running - try again on a later scan
        events, final = r
        half = (h >> 1) & 1
        done = set()
        tg = _tag_of_signal(key, S, i, is_long)            # None when the bigger-trend picture is unknown for this signal
        with _lock:
            for _j, lab, now in events:
                for k, _combo in keys(lab):
                    for kk in ((k, k + "@" + tg) if tg else (k,)):   # plain table AND (when known) the bigger-trend table
                        if kk in done:
                            continue
                        done.add(kk)
                        rec = _stats.setdefault(kk, [0, 0.0, 0, 0.0])
                        rec[half * 2] += 1
                        rec[half * 2 + 1] += final - now
            if tg:                                          # one count per signal (for the screen: how much bigger-trend data there is)
                _stats.setdefault("ctx@" + tg, [0, 0.0, 0, 0.0])[half * 2] += 1
            _seen[h] = 1
            _dirty = True
        _save()
        try:                                               # the same finished signal also feeds the per-coin memory
            from . import ai_coin_memory as _CM
            _CM.learn_replay(str(key).split("|")[0], final, key)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[ExitLearn] learn: {e}")
        return False



# ------------------------------------------------------------------ bigger-trend tag (3B)
def bucket(align):
    """ai_context align -> W (with the bigger trend) / A (against) / O (sideways or mixed) / None (not known)."""
    return {"WITH": "W", "AGAINST": "A", "MIXED": "O", "SIDE": "O"}.get(align)


def _tag_of_signal(key, S, i, is_long):
    """Bucket of a replayed signal, only when the cached 1h/4h/1d picture of its coin is still a fair picture of that
    moment (signal younger than TAG_MAX_AGE_S). Cache only, no network. None = unknown (then only the plain table learns)."""
    try:
        t = float(S["t"][i])
        t = t / 1000.0 if t > 1e11 else t
        age = time.time() - t
        if age < 0 or age > TAG_MAX_AGE_S:
            return None
        from . import ai_context as CTX
        return bucket(CTX.tag(str(key).split("|")[0], "BUY" if is_long else "SELL").get("align"))
    except Exception:
        return None


# ------------------------------------------------------------------ the answer for a live trade
def _verdict(rec, lev):
    na, sa, nb, sb = rec
    if na < MIN_HALF or nb < MIN_HALF:
        return None
    a, b = sa / na * lev, sb / nb * lev
    if a <= -EDGE_ROI and b <= -EDGE_ROI:
        return "BOOK"
    if a >= EDGE_ROI and b >= EDGE_ROI:
        return "HOLD"
    return "FLAT"


def _cells(lab, lev, S, tg=None):
    cells = []
    for k, combo in keys(lab):
        kk = k + "@" + tg if tg else k
        rec = S.get(kk)
        v = _verdict(rec, lev) if rec else None
        if v is None:
            continue
        n = rec[0] + rec[2]
        avg = (rec[1] + rec[3]) / n * lev
        cells.append({"key": kk, "text": nice(kk), "combo": combo, "verdict": v, "n": n, "avg": round(avg, 2)})
    return cells


def _decide(cells):
    """BOOK needs: a trusted pair/triple that says BOOK and at least as many BOOKs as HOLDs among trusted pairs/triples;
    with no trusted pair/triple: >= 2 trusted singles say BOOK and none says HOLD."""
    combos = [c for c in cells if c["combo"]]
    pool = combos if combos else [c for c in cells if not c["combo"]]
    book = [c for c in pool if c["verdict"] == "BOOK"]
    hold = [c for c in pool if c["verdict"] == "HOLD"]
    need = 1 if combos else 2
    if len(book) >= need and len(book) >= len(hold) and (combos or not hold):
        w = min(book, key=lambda c: c["avg"])
        return {"call": "BOOK", "cells": book + hold,
                "why": "Indicators ki ye situation (%s): pehle %d band trades me abhi nikalna hold se avg %.1f%% ROI behtar raha. AI ne nikal liya."
                       % (w["text"], w["n"], abs(w["avg"]))}
    if hold and len(hold) > len(book):
        w = max(hold, key=lambda c: c["avg"])
        return {"call": "HOLD", "cells": hold + book,
                "why": "Ye situation (%s): pehle %d trades me hold karna avg %.1f%% ROI behtar raha. AI hold kar raha hai."
                       % (w["text"], w["n"], w["avg"])}
    return {"call": "NONE", "cells": cells, "why": ""}


def evaluate(lab, lev=1.0, stats=None, align=None):
    """lab = state() of the latest closed candle. -> {'call': BOOK|HOLD|NONE, 'why': text, 'cells': [...]}.
    3B: when the trade's bigger-trend tag is known (align = ai_context WITH/AGAINST/MIXED/SIDE) the table of THAT kind of trade is
    asked first, but only if it already has enough data (same rule: 12+ trades in each half, both halves agree). Otherwise the plain
    table answers, exactly as before - so a new tag can never make the AI know LESS than it did."""
    try:
        _load()
        S = stats if stats is not None else _stats
        tg = bucket(align)
        if tg:
            r = _decide(_cells(lab, lev, S, tg))
            if r["call"] != "NONE":
                r["ctx"] = tg
                return r
        r = _decide(_cells(lab, lev, S))
        r["ctx"] = None
        return r
    except Exception:
        return {"call": "NONE", "cells": [], "why": "", "ctx": None}


def summary(lev=1.0, top=5):
    """For the screen: how many trades studied + the clearest BOOK / HOLD situations."""
    try:
        _load()
        rows = []
        with _lock:
            items = list(_stats.items())
            n_seen = len(_seen)
        for k, rec in items:
            v = _verdict(rec, lev)
            if v in ("BOOK", "HOLD"):
                n = rec[0] + rec[2]
                rows.append({"text": nice(k), "verdict": v, "n": n, "avg": round((rec[1] + rec[3]) / n * lev, 2)})
        book = sorted([r for r in rows if r["verdict"] == "BOOK"], key=lambda r: r["avg"])[:top]
        hold = sorted([r for r in rows if r["verdict"] == "HOLD"], key=lambda r: -r["avg"])[:top]
        ctx_n = {t: (_stats.get("ctx@" + t) or [0, 0, 0, 0])[0] + (_stats.get("ctx@" + t) or [0, 0, 0, 0])[2] for t in ("W", "A", "O")}   # signals learned WITH / AGAINST / SIDE-MIXED
        return {"studied": n_seen, "book": book, "hold": hold, "ctx_obs": ctx_n}
    except Exception:
        return {"studied": 0, "book": [], "hold": []}


def reset():
    global _dirty
    with _lock:
        _stats.clear()
        _seen.clear()
        _dirty = True
    _save(force=True)
