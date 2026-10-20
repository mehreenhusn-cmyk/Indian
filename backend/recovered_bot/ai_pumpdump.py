"""
ai_pumpdump.py - Vision AI's pump / dump memory and playbook.

What it does
  * Detects recent pumps and dumps on 15m candles from measured numbers (range, impulse,
    volume, TSI, Z, Z-SMA, SD zone) - no AI guesswork.
  * For every detected event stores a BEFORE snapshot (TSI, Z, Z-SMA, SD zone, volume shape)
    and an AFTER outcome (reverse / continue / sideways over the next N candles).
  * Builds simple stats and a short prompt block so Vision AI can see "last time price
    pumped like this from this zone, what usually happened next".
  * Can seed itself from the longest 15m history one call gives (~15 days) (no need to wait for live trades).
  * Buyer vs seller read from candle body, wick and volume (plain arithmetic).

Safety: read-only. Own file ai/vision_pumpdump.json. Never touches bot trades or orders.
Honest limit: past patterns are not a guarantee; the stats are shown so the owner can judge.
"""
import json
import math
import os
import threading
import time

from . import ai_ind_features as F

KEEP_EVENTS = 400
LOOKBACK_CANDLES = 96          # ~1 day on 15m
AFTER_BARS = 12                # outcome window (~3 h on 15m)
PUMP_PCT = 3.5                 # min move % (low->close for a pump, high->close for a dump) inside WINDOW_BARS
WINDOW_BARS = 16               # the move must happen inside ~4 h on 15m
COOLDOWN_BARS = 16             # same kind of event is not counted again for ~4 h (= WINDOW_BARS, so one leg is never counted twice)
SEED_CANDLES = 1500            # max one exchange call gives (~15 days of 15m)
MIN_EVENTS_NOTE = 20           # below this many events the playbook is labelled "small sample"

_lock = threading.RLock()
_state = {"events": [], "stats": {}, "last_seed": 0.0, "seeded": {}, "log": []}
_file = None
_loaded = False
_dirty = False


# ------------------------------------------------------------------ storage
def init(path):
    global _file
    try:
        os.makedirs(path, exist_ok=True)
        _file = os.path.join(path, "vision_pumpdump.json")
    except Exception as e:
        print(f"[PumpDump] init: {e}")


def _load():
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            if _file:
                from . import safe_io
                d, _src = safe_io.read_json_safe(_file, "vision_pumpdump")
                if isinstance(d, dict):
                    if isinstance(d.get("events"), list):
                        _state["events"] = d["events"]
                    if isinstance(d.get("stats"), dict):
                        _state["stats"] = d["stats"]
                    _state["last_seed"] = float(d.get("last_seed") or 0.0)
                    if isinstance(d.get("seeded"), dict):
                        _state["seeded"] = d["seeded"]
        except Exception as e:
            print(f"[PumpDump] load: {e}")


def _save(force=False):
    global _dirty
    with _lock:
        if not _file:
            return
        if not force and not _dirty:
            return
        try:
            from . import safe_io
            _state["events"] = _state["events"][-KEEP_EVENTS:]
            safe_io.write_json_atomic(_file, {
                "events": _state["events"],
                "stats": _state["stats"],
                "last_seed": _state["last_seed"],
                "seeded": _state.get("seeded") or {},
            })
            _dirty = False
        except Exception as e:
            print(f"[PumpDump] save: {e}")


def _log(text):
    with _lock:
        _state["log"].append(f"{time.strftime('%H:%M:%S')} {text}")
        _state["log"] = _state["log"][-80:]


def _f(x, default=None):
    try:
        v = float(x)
        return v if v == v else default
    except Exception:
        return default


def _pct(a, b):
    try:
        if b and abs(b) > 1e-12:
            return (a - b) / abs(b) * 100.0
    except Exception:
        pass
    return 0.0


# ------------------------------------------------------------------ buyer / seller from candle body + wick + volume
def buyer_seller(candles, look=8):
    """Plain-English read of who is in control from the last few closed candles.
    Returns a short string for the Vision prompt and a dict of numbers."""
    try:
        if not candles or len(candles) < look + 2:
            return "", {}
        seg = candles[-look:]
        bodies, upper_w, lower_w, vols, dirs = [], [], [], [], []
        for c in seg:
            o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
            body = abs(cl - o)
            rng = max(h - l, 1e-12)
            bodies.append(body / rng)
            upper_w.append((h - max(o, cl)) / rng)
            lower_w.append((min(o, cl) - l) / rng)
            vols.append(float(c.get("volume") or 0))
            dirs.append(1 if cl >= o else -1)
        avg_body = sum(bodies) / len(bodies)
        avg_up = sum(upper_w) / len(upper_w)
        avg_lo = sum(lower_w) / len(lower_w)
        net = sum(dirs)
        vol_now = sum(vols[-3:]) / 3.0 if len(vols) >= 3 else (vols[-1] if vols else 0)
        vol_prev = sum(vols[:-3]) / max(len(vols) - 3, 1) if len(vols) > 3 else vol_now
        vol_ratio = vol_now / vol_prev if vol_prev > 0 else 1.0
        # classification
        if net >= 3 and avg_body > 0.45 and avg_lo < 0.25:
            who = "buyers in control (full green bodies, little lower wick)"
            score = 1
        elif net <= -3 and avg_body > 0.45 and avg_up < 0.25:
            who = "sellers in control (full red bodies, little upper wick)"
            score = -1
        elif avg_up > 0.4 and avg_body < 0.35:
            who = "sellers rejecting highs (long upper wicks)"
            score = -0.5
        elif avg_lo > 0.4 and avg_body < 0.35:
            who = "buyers rejecting lows (long lower wicks)"
            score = 0.5
        elif abs(net) <= 1 and avg_body < 0.3:
            who = "indecision (small bodies, mixed direction)"
            score = 0
        else:
            who = "mixed pressure"
            score = 0.2 if net > 0 else (-0.2 if net < 0 else 0)
        vol_note = ""
        if vol_ratio >= 1.6:
            vol_note = f"; volume elevated ({vol_ratio:.1f}x recent)"
        elif vol_ratio <= 0.6:
            vol_note = f"; volume quiet ({vol_ratio:.1f}x recent)"
        text = f"Last {look} candles: {who}{vol_note}."
        nums = {
            "net_dir": net,
            "avg_body": round(avg_body, 3),
            "avg_upper_wick": round(avg_up, 3),
            "avg_lower_wick": round(avg_lo, 3),
            "vol_ratio": round(vol_ratio, 2),
            "score": score,
        }
        return text, nums
    except Exception:
        return "", {}


# ------------------------------------------------------------------ detect pumps / dumps (causal: uses only candles up to the trigger bar)
def _scan_events(candles, feat, symbol, tf_min=15, first_bar=0):
    """Walk the candles once. A PUMP triggers on the first bar whose close is >= PUMP_PCT above the lowest low of the
    last WINDOW_BARS bars; a DUMP the same downwards. Nothing after the trigger bar is used to detect it, so the
    stats are not biased by hindsight. Then it stores:
      before = numbers at the START of the move (the situation BEFORE the pump / dump)
      at_top = numbers at the trigger bar (the pump / dump itself)
      outcome over the next AFTER_BARS bars: reverse / continue / sideways.
    Only events with a full AFTER_BARS window are returned (others are still unfinished)."""
    out = []
    try:
        n = len(candles)
        if n < WINDOW_BARS + AFTER_BARS + 60:
            return out
        closes = [float(c["close"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        vols = [float(c.get("volume") or 0) for c in candles]
        last_j = {"pump": -10 ** 9, "dump": -10 ** 9}
        leg_end = {"pump": -10 ** 9, "dump": -10 ** 9}   # where the last pump / dump leg stopped (only used to not count it twice)
        for j in range(max(60, WINDOW_BARS, first_bar), n - AFTER_BARS):
            wl = lows[j - WINDOW_BARS:j + 1]
            wh = highs[j - WINDOW_BARS:j + 1]
            lo, hi = min(wl), max(wh)
            if lo <= 0 or hi <= 0:
                continue
            lo_i = j - WINDOW_BARS + wl.index(lo)
            hi_i = j - WINDOW_BARS + wh.index(hi)
            up = (closes[j] - lo) / lo * 100.0
            dn = (hi - closes[j]) / hi * 100.0
            kind = start_i = move = None
            if up >= PUMP_PCT and lo_i < j and up >= dn:
                kind, start_i, move = "pump", lo_i, up
            elif dn >= PUMP_PCT and hi_i < j:
                kind, start_i, move = "dump", hi_i, dn
            # a new pump must START after the previous pump's leg ended; otherwise it is the same leg still running
            if not kind or j - last_j[kind] < COOLDOWN_BARS or start_i <= leg_end[kind]:
                continue
            last_j[kind] = j
            seg_c = closes[j:j + WINDOW_BARS + 1]
            leg_end[kind] = j + (seg_c.index(max(seg_c)) if kind == "pump" else seg_c.index(min(seg_c)))
            seg = sorted(vols[max(0, j - 40):j]) or [1.0]
            med_vol = seg[len(seg) // 2] or 1.0
            vol_ratio = vols[j] / med_vol if med_vol > 0 else 1.0
            fut_c = closes[j + 1:j + 1 + AFTER_BARS]
            if len(fut_c) < AFTER_BARS:
                continue
            ret = _pct(fut_c[-1], closes[j])
            max_up = _pct(max(highs[j + 1:j + 1 + AFTER_BARS]), closes[j])
            max_dn = _pct(min(lows[j + 1:j + 1 + AFTER_BARS]), closes[j])
            if kind == "pump":
                outcome = "reverse" if (ret <= -1.2 or max_dn <= -2.0) else ("continue" if (ret >= 1.0 or max_up >= 2.0) else "sideways")
            else:
                outcome = "reverse" if (ret >= 1.2 or max_up >= 2.0) else ("continue" if (ret <= -1.0 or max_dn <= -2.0) else "sideways")
            ts = int(candles[j].get("timestamp") or 0)
            out.append({
                "id": f"{symbol}_{tf_min}_{kind}_{ts}",
                "symbol": symbol, "tf_min": tf_min, "kind": kind, "ts": ts,
                "move_pct": round(move, 2),
                "move_bars": j - start_i,
                "vol_ratio": round(vol_ratio, 2),
                "before": _snapshot_at(feat, candles, max(start_i - 1, 1)),
                "at_top": _snapshot_at(feat, candles, j),
                "outcome": outcome,
                "after_ret": round(ret, 2),
                "after_max_up": round(max_up, 2),
                "after_max_dn": round(max_dn, 2),
                "t": time.time(),
            })
    except Exception as e:
        _log(f"scan: {e}")
    return out


def _snapshot_at(feat, candles, i):
    """Measured numbers at index i for the BEFORE block."""
    out = {}
    try:
        c = feat.get("c") or []
        tsi = feat.get("tsi") or []
        tsl = feat.get("tsl") or []
        z = feat.get("z") or []
        zs = feat.get("zsma") or []
        sma = feat.get("sma") or []
        std = feat.get("std") or []
        if i >= len(c) or c[i] is None:
            return out
        out["close"] = round(float(c[i]), 6)
        if i < len(tsi) and tsi[i] is not None:
            out["tsi"] = round(float(tsi[i]), 2)
        if i < len(tsl) and tsl[i] is not None:
            out["tsl"] = round(float(tsl[i]), 2)
            if out.get("tsi") is not None:
                out["tsi_above_signal"] = out["tsi"] > out["tsl"]
        if i < len(z) and z[i] is not None:
            out["z"] = round(float(z[i]), 3)
        if i < len(zs) and zs[i] is not None:
            out["zsma"] = round(float(zs[i]), 3)
            if out.get("z") is not None:
                out["z_above_zsma"] = out["z"] > out["zsma"]
        if i < len(sma) and sma[i] is not None and i < len(std) and std[i]:
            out["sma"] = round(float(sma[i]), 6)
            out["std"] = round(float(std[i]), 6)
            dist = (c[i] - sma[i]) / std[i]
            out["sd_zone"] = round(dist, 2)
            if dist >= 2:
                out["sd_label"] = "above_2sd"
            elif dist >= 1:
                out["sd_label"] = "above_1sd"
            elif dist <= -2:
                out["sd_label"] = "below_2sd"
            elif dist <= -1:
                out["sd_label"] = "below_1sd"
            else:
                out["sd_label"] = "inside_1sd"
        # Z-SMA slope (simple 5-bar)
        if i >= 5 and i < len(zs) and zs[i] is not None and zs[i - 5] is not None:
            out["zsma_slope"] = "up" if zs[i] > zs[i - 5] else ("down" if zs[i] < zs[i - 5] else "flat")
        # volume vs median
        vols = [float(x.get("volume") or 0) for x in candles[max(0, i - 30):i + 1]]
        if vols:
            med = sorted(vols)[len(vols) // 2] or 1
            out["vol_vs_med"] = round(vols[-1] / med, 2)
    except Exception:
        pass
    return out


# ------------------------------------------------------------------ record + stats
def _near_existing(ev, tf_min):
    """True if we already hold the same kind of event on this coin within COOLDOWN_BARS."""
    gap = COOLDOWN_BARS * tf_min * 60 * 1000
    for x in _state["events"]:
        if x.get("symbol") == ev["symbol"] and x.get("kind") == ev["kind"] and abs(int(x.get("ts") or 0) - ev["ts"]) < gap:
            return True
    return False


def _add_events(events, tf_min):
    added = 0
    global _dirty
    with _lock:
        for ev in sorted(events, key=lambda e: e["ts"]):
            if any(x.get("id") == ev["id"] for x in _state["events"]) or _near_existing(ev, tf_min):
                continue
            _state["events"].append(ev)
            added += 1
        if added:
            _dirty = True
    return added


def record_from_candles(symbol, candles, tf_min=15):
    """Live use: scan the latest candles, store every finished pump/dump not stored yet. Returns number added."""
    _load()
    try:
        if not candles or len(candles) < 200:
            return 0
        feat = F.build(candles)
        # only look at the most recent bars (older ones were handled by earlier calls / the seed)
        evs = _scan_events(candles, feat, symbol, tf_min, first_bar=max(0, len(candles) - AFTER_BARS - 3 * WINDOW_BARS))
        added = _add_events(evs, tf_min)
        if added:
            _rebuild_stats()
            _save(force=True)
            _log(f"recorded {added} event(s) on {symbol}")
        return added
    except Exception as e:
        _log(f"record: {e}")
        return 0


def _bucket(events, kind, getter):
    b = {}
    for e in events:
        if e.get("kind") != kind or e.get("outcome") not in ("reverse", "continue", "sideways"):
            continue
        try:
            label = getter(e)
        except Exception:
            label = None
        if label is None:
            continue
        d = b.setdefault(label, {"reverse": 0, "continue": 0, "sideways": 0, "n": 0})
        d[e["outcome"]] += 1
        d["n"] += 1
    return b


def _rebuild_stats():
    with _lock:
        events = list(_state["events"])
    by = {"pump": {"reverse": 0, "continue": 0, "sideways": 0, "n": 0},
          "dump": {"reverse": 0, "continue": 0, "sideways": 0, "n": 0}}
    for e in events:
        k, o = e.get("kind"), e.get("outcome")
        if k in by and o in by[k]:
            by[k][o] += 1
            by[k]["n"] += 1

    def zone(e):
        return (e.get("before") or {}).get("sd_label") or "unknown"

    def tsi(e):
        v = (e.get("at_top") or {}).get("tsi_above_signal")
        return None if v is None else ("tsi_above_signal" if v else "tsi_below_signal")

    def zz(e):
        v = (e.get("at_top") or {}).get("z_above_zsma")
        return None if v is None else ("z_above_zsma" if v else "z_below_zsma")

    stats = {
        "by_kind": by,
        "pump_by_sd_zone": _bucket(events, "pump", zone),   # zone the pump STARTED from
        "dump_by_sd_zone": _bucket(events, "dump", zone),
        "pump_by_tsi": _bucket(events, "pump", tsi),         # TSI vs its signal line AT the pump
        "dump_by_tsi": _bucket(events, "dump", tsi),
        "pump_by_z": _bucket(events, "pump", zz),
        "dump_by_z": _bucket(events, "dump", zz),
        "total": len(events),
        "updated": time.time(),
    }
    global _dirty
    with _lock:
        _state["stats"] = stats
        _dirty = True


# ------------------------------------------------------------------ prompt block for Vision AI
def prompt_block(symbol=None, side=None, candles=None):
    """Short text block to inject into the Vision AI prompt about recent pump/dump memory."""
    _load()
    bits = []
    try:
        with _lock:
            events = list(_state["events"])
            stats = dict(_state.get("stats") or {})
        # global outcome rates
        by = (stats.get("by_kind") or {})
        for kind in ("pump", "dump"):
            d = by.get(kind) or {}
            n = d.get("n") or 0
            if n >= 5:
                bits.append(
                    f"Past {kind}s (n={n}): reverse={d.get('reverse',0)} "
                    f"continue={d.get('continue',0)} sideways={d.get('sideways',0)}."
                )
        # recent similar for this symbol
        if symbol:
            recent = [e for e in events if e.get("symbol") == symbol][-6:]
            if recent:
                lines = []
                for e in recent:
                    b = e.get("before") or {}
                    lines.append(
                        f"{e.get('kind')} move={e.get('move_pct')}% sd={b.get('sd_label','?')} "
                        f"Z={b.get('z','?')} outcome={e.get('outcome')} ({e.get('after_ret'):+.1f}%)"
                    )
                bits.append("Recent events on this coin: " + " | ".join(lines))
        # live buyer/seller if candles given
        if candles:
            bs_text, _ = buyer_seller(candles)
            if bs_text:
                bits.append(bs_text)
            # live stretch warning (extends the simple warning already in ai_vision)
            if len(candles) >= 30:
                closes = [float(c["close"]) for c in candles]
                highs = [float(c["high"]) for c in candles]
                lows = [float(c["low"]) for c in candles]
                seg_h, seg_l = max(highs[-20:]), min(lows[-20:])
                if seg_l > 0:
                    move = (seg_h - seg_l) / seg_l * 100.0
                    pos = (closes[-1] - seg_l) / (seg_h - seg_l) if seg_h > seg_l else 0.5
                    side_u = str(side or "").upper()
                    if move >= 4.0 and pos >= 0.8 and side_u == "BUY":
                        bits.append("WARNING: price near top of a recent pump range — chasing often dumps next.")
                    if move >= 4.0 and pos <= 0.2 and side_u == "SELL":
                        bits.append("WARNING: price near bottom of a recent dump range — shorting often bounces.")
        if not bits:
            return ""
        return "\n\nPUMP/DUMP MEMORY (measured from past 15m candles, not opinions):\n" + "\n".join(f"- {b}" for b in bits)
    except Exception:
        return ""


# ------------------------------------------------------------------ seed from history
def seed_history(symbol, candles, tf_min=15):
    """One pass over the history (features built once). Safe to call again: duplicates are skipped."""
    _load()
    if not candles or len(candles) < 250:
        return {"ok": False, "reason": "need ~250+ candles"}
    try:
        feat = F.build(candles)
        evs = _scan_events(candles, feat, symbol, tf_min)
        added = _add_events(evs, tf_min)
        _rebuild_stats()
        global _dirty
        with _lock:
            _state["last_seed"] = time.time()
            _state.setdefault("seeded", {})[symbol] = time.time()
            _dirty = True
            total = len(_state["events"])
        _save(force=True)
        days = round(len(candles) * tf_min / 1440.0, 1)
        return {"ok": True, "added": added, "found": len(evs), "total": total, "days": days}
    except Exception as e:
        return {"ok": False, "reason": str(e)[:120]}


def maybe_seed(symbol, fetch_fn, tf_min=15):
    """Download the longest history one call allows (~15 days of 15m) and seed THIS coin.
    The 1-hour pause is per coin, so seeding BTC does not block ETH."""
    _load()
    with _lock:
        last = float((_state.get("seeded") or {}).get(symbol) or 0)
    if time.time() - last < 3600:
        return {"ok": True, "skipped": True, "reason": "this coin was seeded less than 1 hour ago"}
    try:
        candles = fetch_fn(symbol, tf_min)
        if not candles:
            return {"ok": False, "reason": "no candles"}
        return seed_history(symbol, candles[-SEED_CANDLES:], tf_min)
    except Exception as e:
        return {"ok": False, "reason": str(e)[:120]}


# ------------------------------------------------------------------ Z-SMA richer use
def zsma_read(feat, side=None):
    """Plain text about Z vs Z-SMA: cross, slope, stretch. For prompt / cards."""
    try:
        i = (feat.get("n") or 0) - 1
        if i < 10:
            return ""
        z = feat.get("z") or []
        zs = feat.get("zsma") or []
        if i >= len(z) or z[i] is None or i >= len(zs) or zs[i] is None:
            return ""
        bits = [f"Z={z[i]:+.2f} vs Z-SMA={zs[i]:+.2f}"]
        # cross in last 5 bars
        crossed = None
        for j in range(max(1, i - 5), i + 1):
            if z[j] is None or zs[j] is None or z[j - 1] is None or zs[j - 1] is None:
                continue
            if z[j - 1] < zs[j - 1] and z[j] >= zs[j]:
                crossed = "Z crossed ABOVE Z-SMA"
            elif z[j - 1] > zs[j - 1] and z[j] <= zs[j]:
                crossed = "Z crossed BELOW Z-SMA"
        if crossed:
            bits.append(crossed + " in last 5 bars")
        # slope
        if i >= 5 and zs[i - 5] is not None:
            if zs[i] > zs[i - 5] * 1.02:
                bits.append("Z-SMA sloping up")
            elif zs[i] < zs[i - 5] * 0.98:
                bits.append("Z-SMA sloping down")
            else:
                bits.append("Z-SMA flat")
        side_u = str(side or "").upper()
        if side_u == "BUY" and z[i] < zs[i]:
            bits.append("(for BUY: Z still below its average — momentum not yet confirmed)")
        if side_u == "SELL" and z[i] > zs[i]:
            bits.append("(for SELL: Z still above its average — downside not yet confirmed)")
        return "; ".join(bits) + "."
    except Exception:
        return ""


# ------------------------------------------------------------------ public snapshot for API / app
def snapshot(limit=40):
    _load()
    with _lock:
        events = list(_state["events"][-limit:])[::-1]
        stats = dict(_state.get("stats") or {})
        log = list(_state.get("log") or [])[-20:]
    # playbook summary lines
    playbook = []
    by = stats.get("by_kind") or {}
    for kind, label in (("pump", "After a pump"), ("dump", "After a dump")):
        d = by.get(kind) or {}
        n = d.get("n") or 0
        if n < 3:
            playbook.append(f"{label}: too few events yet (n={n}).")
            continue
        rev = d.get("reverse", 0)
        cont = d.get("continue", 0)
        side = d.get("sideways", 0)
        top = max(("reverse", rev), ("continue", cont), ("sideways", side), key=lambda x: x[1])
        small = " SMALL SAMPLE - do not trust yet." if n < MIN_EVENTS_NOTE else ""
        playbook.append(
            f"{label} (n={n}): most often {top[0]} ({top[1]}/{n}). "
            f"Reverse {rev}, continue {cont}, sideways {side}.{small}"
        )
    for key, text in (("pump_by_sd_zone", "Pump that started from"), ("dump_by_sd_zone", "Dump that started from"),
                      ("pump_by_tsi", "Pump with"), ("dump_by_tsi", "Dump with"),
                      ("pump_by_z", "Pump with"), ("dump_by_z", "Dump with")):
        for zlabel, d in list((stats.get(key) or {}).items())[:4]:
            n = d.get("n") or 0
            if n >= 5:
                playbook.append(
                    f"{text} {zlabel} (n={n}): reverse={d.get('reverse',0)} "
                    f"continue={d.get('continue',0)} sideways={d.get('sideways',0)}."
                )
    return {
        "events": events,
        "stats": stats,
        "playbook": playbook,
        "log": log,
        "last_seed": _state.get("last_seed") or 0,
        "total": len(_state.get("events") or []),
    }


def clear():
    with _lock:
        _state["events"] = []
        _state["stats"] = {}
        _state["last_seed"] = 0.0
        global _dirty
        _dirty = True
    _save(force=True)
    return {"ok": True}
