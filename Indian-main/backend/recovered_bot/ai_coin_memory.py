"""
ai_coin_memory.py - what the AI has learned about each COIN, and about trading with / against the bigger trend.

Two sources, both honest about how little data one or two signals are:
  1. REPLAY  - every old finished signal the Shadow Lab replays (ai_exit_learn.learn calls learn_replay once per
               signal): how the NORMAL management ended on that coin. This gives a coin history from day one.
  2. LIVE    - every trade the AI itself closes (ai_coach._close calls on_close), together with whether the trade
               went WITH or AGAINST the 1h / 4h / 1d trend (ai_context.tag) when it was opened.

Coin status (plain words on the screen):
  Watching  fewer than MIN_SEEN trades in total - too little to say anything
  Learning  some data, no clear result yet
  Trusted   >= MIN_HALF trades in EACH of two independent halves and both halves clearly profitable
  Avoid     same, both halves clearly losing
Halves are split by a hash of the trade id, so one lucky streak cannot fill both.

WITH vs AGAINST the bigger trend is one global table (all coins together, live AI trades only) because per coin it
would stay empty for weeks. It is shown as information; no rule is hard-coded from it.

All results are stored as PRICE % in the trade direction, after fee (1 ROI fee point / leverage), so replay and live
trades are comparable. READ-ONLY: nothing here opens, closes or blocks a trade. Every public function swallows errors.
"""
import threading
import time
import zlib

MIN_SEEN = 6
MIN_HALF = 8
EDGE_ROI = 1.0            # average ROI points per trade a coin must beat / miss in BOTH halves
SAVE_EVERY_S = 60
MAX_COINS = 400

_lock = threading.RLock()
_loaded = False
_dirty = False
_last_save = 0.0
_file_override = None
_coins = {}               # sym -> {"h": [n0, s0, n1, s1], "live": [n, wins, sum_roi], "last": ts}
_ctx = {}                 # align -> [n0, s0, n1, s1]   (live AI trades only)


def _file():
    if _file_override:
        return _file_override
    try:
        import os
        from . import ai_shadow_lab as L
        return os.path.join(L._dir, "ai_coin_memory.json") if L._dir else None
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
            d, _src = safe_io.read_json_safe(f, "ai_coin_memory")
            if isinstance(d, dict):
                if isinstance(d.get("coins"), dict):
                    _coins.update(d["coins"])
                if isinstance(d.get("ctx"), dict):
                    _ctx.update(d["ctx"])
        except Exception as e:
            print(f"[CoinMemory] load: {e}")


def _save(force=False):
    global _dirty, _last_save
    with _lock:
        if not _dirty or (not force and time.time() - _last_save < SAVE_EVERY_S):
            return
        f = _file()
        if not f:
            return
        try:
            from . import safe_io
            if len(_coins) > MAX_COINS:
                for k in sorted(_coins, key=lambda x: _coins[x].get("last", 0))[: len(_coins) - MAX_COINS]:
                    _coins.pop(k, None)
            safe_io.write_json_atomic(f, {"coins": _coins, "ctx": _ctx})
            _dirty = False
            _last_save = time.time()
        except Exception as e:
            print(f"[CoinMemory] save: {e}")


def _cfg():
    """(leverage, fee ROI points) from the coach settings; safe defaults if unavailable."""
    try:
        from . import ai_coach as C
        return max(1.0, float(C._cfg("leverage", 1) or 1)), max(0.0, float(C._cfg("fee_roi_pct", 1.0) or 0.0))
    except Exception:
        return 1.0, 1.0


def _half(trade_id):
    return (zlib.crc32(str(trade_id).encode()) >> 1) & 1


def _add(rec, half, pct):
    rec[half * 2] += 1
    rec[half * 2 + 1] += pct


# ------------------------------------------------------------------ writing
def learn_replay(sym, final_pct, signal_key):
    """One OLD finished signal of this coin. final_pct = price % in the trade direction, no fee. Counted once by the
    caller (ai_exit_learn keeps the list of signals it has already studied)."""
    global _dirty
    try:
        _load()
        lev, fee = _cfg()
        pct = float(final_pct) - fee / lev
        with _lock:
            c = _coins.setdefault(sym, {"h": [0, 0.0, 0, 0.0], "live": [0, 0, 0.0], "last": 0})
            _add(c["h"], _half(signal_key), pct)
            c["last"] = time.time()
            _dirty = True
        _save()
    except Exception as e:
        print(f"[CoinMemory] replay: {e}")


def on_close(sym, roi, lev, align, trade_id):
    """One trade the AI closed. roi = net ROI % (fee already taken), lev = leverage used, align = ai_context tag."""
    global _dirty
    try:
        _load()
        lev = max(1.0, float(lev or 1))
        pct = float(roi) / lev
        h = _half(trade_id)
        with _lock:
            c = _coins.setdefault(sym, {"h": [0, 0.0, 0, 0.0], "live": [0, 0, 0.0], "last": 0})
            _add(c["h"], h, pct)
            c["live"][0] += 1
            c["live"][1] += 1 if roi > 0 else 0
            c["live"][2] += float(roi)
            c["last"] = time.time()
            if align and align != "UNKNOWN":
                _add(_ctx.setdefault(align, [0, 0.0, 0, 0.0]), h, pct)
            _dirty = True
        _save()
    except Exception as e:
        print(f"[CoinMemory] close: {e}")


# ------------------------------------------------------------------ reading
def _verdict(h, lev):
    na, sa, nb, sb = h
    if na < MIN_HALF or nb < MIN_HALF:
        return None
    a, b = sa / na * lev, sb / nb * lev
    if a >= EDGE_ROI and b >= EDGE_ROI:
        return "Trusted"
    if a <= -EDGE_ROI and b <= -EDGE_ROI:
        return "Avoid"
    return "Learning"


def status(sym, lev=None):
    """-> {'status', 'n', 'avg_roi', 'live_n', 'live_wins'} - 'Watching' when there is (almost) nothing."""
    try:
        _load()
        lev = lev or _cfg()[0]
        with _lock:
            c = _coins.get(sym)
            if not c:
                return {"status": "Watching", "n": 0, "avg_roi": 0.0, "live_n": 0, "live_wins": 0}
            h, live = list(c["h"]), list(c["live"])
        n = h[0] + h[2]
        if n < MIN_SEEN:
            st = "Watching"
        else:
            st = _verdict(h, lev) or "Learning"
        return {"status": st, "n": n, "avg_roi": round((h[1] + h[3]) / n * lev, 2) if n else 0.0,
                "live_n": live[0], "live_wins": live[1]}
    except Exception:
        return {"status": "Watching", "n": 0, "avg_roi": 0.0, "live_n": 0, "live_wins": 0}


def ctx_summary(lev=None):
    """WITH / AGAINST / MIXED / SIDE the bigger trend: how many AI trades and the average ROI of each, plus one
    honest sentence. A comparison is only made when WITH and AGAINST both have enough trades in both halves."""
    try:
        _load()
        lev = lev or _cfg()[0]
        with _lock:
            snap = {k: list(v) for k, v in _ctx.items()}
        rows = {}
        for k in ("WITH", "AGAINST", "MIXED", "SIDE"):
            r = snap.get(k, [0, 0.0, 0, 0.0])
            n = r[0] + r[2]
            rows[k] = {"n": n, "avg": round((r[1] + r[3]) / n * lev, 2) if n else None}
        w, a = snap.get("WITH"), snap.get("AGAINST")
        text = "Still collecting: the AI needs about %d trades WITH and %d AGAINST the bigger trend, in both halves of its data, before it can compare them." % (MIN_HALF * 2, MIN_HALF * 2)
        if w and a and min(w[0], w[2], a[0], a[2]) >= MIN_HALF:
            wa, wb = w[1] / w[0] * lev, w[3] / w[2] * lev
            aa, ab = a[1] / a[0] * lev, a[3] / a[2] * lev
            if wa - aa >= EDGE_ROI and wb - ab >= EDGE_ROI:
                text = "Trades WITH the bigger trend did better than trades AGAINST it, in both halves of the data."
            elif aa - wa >= EDGE_ROI and ab - wb >= EDGE_ROI:
                text = "Trades AGAINST the bigger trend did better than trades WITH it, in both halves of the data."
            else:
                text = "No clear difference yet between trades with and against the bigger trend."
        return {"rows": rows, "text": text}
    except Exception:
        return {"rows": {}, "text": ""}


def ctx_verdict(lev=None):
    """'WITH_BETTER' / 'AGAINST_BETTER' / 'NONE' / 'COLLECTING' - the same honesty test as ctx_summary()."""
    try:
        _load()
        lev = lev or _cfg()[0]
        with _lock:
            w, a = list(_ctx.get("WITH", [])), list(_ctx.get("AGAINST", []))
        if len(w) != 4 or len(a) != 4 or min(w[0], w[2], a[0], a[2]) < MIN_HALF:
            return "COLLECTING"
        wa, wb = w[1] / w[0] * lev, w[3] / w[2] * lev
        aa, ab = a[1] / a[0] * lev, a[3] / a[2] * lev
        if wa - aa >= EDGE_ROI and wb - ab >= EDGE_ROI:
            return "WITH_BETTER"
        if aa - wa >= EDGE_ROI and ab - wb >= EDGE_ROI:
            return "AGAINST_BETTER"
        return "NONE"
    except Exception:
        return "COLLECTING"


def summary(open_syms=(), top=12):
    """For the screen: the coins with an open AI trade first, then the most-studied coins."""
    try:
        _load()
        lev = _cfg()[0]
        with _lock:
            syms = list(_coins)
        order = list(dict.fromkeys(list(open_syms) + sorted(syms, key=lambda s: -(_coins[s]["h"][0] + _coins[s]["h"][2]))))
        out = []
        for s in order[:top]:
            st = status(s, lev)
            st["sym"] = s
            st["open"] = s in open_syms
            out.append(st)
        counts = {"Watching": 0, "Learning": 0, "Trusted": 0, "Avoid": 0}
        for s in syms:
            counts[status(s, lev)["status"]] += 1
        return {"coins": out, "counts": counts, "total": len(syms), "ctx": ctx_summary(lev)}
    except Exception:
        return {"coins": [], "counts": {}, "total": 0, "ctx": {"rows": {}, "text": ""}}


def reset():
    global _dirty
    with _lock:
        _coins.clear()
        _ctx.clear()
        _dirty = True
    _save(force=True)
