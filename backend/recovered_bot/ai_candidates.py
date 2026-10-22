"""
ai_candidates.py - every setup the Vision engine SEES, with what happened next.

A candidate is any situation worth remembering: a bot signal, a setup the AI Own scan found, and a sample of the
coins the scan rejected. Each one is saved with its full tag snapshot (SD zone/shape, Z vs price, TSI, regime, EMA ...).
Later the candles are read and a SHADOW outcome is filled in for ALL of them (taken, skipped, missed alike):
  stop = 1.5 x ATR, target = 2R, first one hit wins (both in one candle = stop, the cautious call), else timeout after 32 bars.
  Result is in R (1R = the stop distance), after round-trip fees, with best (MFE) and worst (MAE) move.
So the learning data does not depend on which trades were actually taken. Read-only: it never opens or closes a trade.
"""
import threading
import time

MAX_BARS = 32          # timeout: 32 candles (8 h on 15m)
RR = 2.0
STOP_ATR = 1.5
FEE_PCT = 0.08         # round trip, percent of price
KEEP = 4000
SAMPLE_EVERY = 5       # of the coins the scan rejected, keep about 1 in 5
_lock = threading.Lock()
_file = None
_loaded = False
_dirty = False
_last_save = 0.0
_last_resolve = 0.0
_state = {"seq": 0, "c": []}


def init(path):
    global _file
    import os
    try:
        os.makedirs(path, exist_ok=True)
        _file = os.path.join(path, "vision_candidates.json")
    except Exception as e:
        print(f"[Candidates] init: {e}")


def _load():
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            if _file:
                from . import safe_io
                d, _src = safe_io.read_json_safe(_file, "vision_candidates")
                if isinstance(d, dict) and isinstance(d.get("c"), list):
                    _state["c"] = d["c"][-KEEP:]
                    _state["seq"] = int(d.get("seq") or len(_state["c"]))
        except Exception as e:
            print(f"[Candidates] load: {e}")


def _save(force=False):
    global _dirty, _last_save
    with _lock:
        if not _file or not _dirty:
            return
        if not force and time.time() - _last_save < 60:
            return
        try:
            from . import safe_io
            _state["c"] = _state["c"][-KEEP:]
            safe_io.write_json_atomic(_file, _state)
            _dirty = False
            _last_save = time.time()
        except Exception as e:
            print(f"[Candidates] save: {e}")


def _f(v, d=0.0):
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


def atr(candles, i=None, n=14):
    """Average true range ending at candle i (default last)."""
    try:
        i = len(candles) - 1 if i is None else i
        if i < n + 1:
            return 0.0
        tr = []
        for j in range(i - n + 1, i + 1):
            h, l, pc = _f(candles[j]["high"]), _f(candles[j]["low"]), _f(candles[j - 1]["close"])
            tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        return sum(tr) / len(tr)
    except Exception:
        return 0.0


def sample_ok(symbol, bar_ts):
    """Deterministic 1-in-N sample of rejected coins (same coin + candle always gives the same answer)."""
    try:
        return (abs(hash((str(symbol), int(float(bar_ts) // 1000)))) % SAMPLE_EVERY) == 0
    except Exception:
        return False


def tokens_from(tags2, feat):
    tk = [f"{k}={v}" for k, v in (tags2 or {}).items()]
    for k, v in (feat or {}).items():
        if isinstance(v, bool):
            tk.append(f"{k}={'yes' if v else 'no'}")
    return tk


def add(source, symbol, side, tf, bar_ts, price, candles, tokens, kind="signal", dec_id=None):
    """Remember one candidate. kind: signal (bot or AI Own took a look) | rejected (scan found no setup)."""
    _load()
    try:
        a = atr(candles)
        if not a or not price or not tokens:
            return None
        with _lock:
            _state["seq"] += 1
            cid = f"c{_state['seq']}"
            _state["c"].append({"id": cid, "src": source, "sym": symbol, "side": side, "tf": int(tf), "t": time.time(),
                                "bar_ts": bar_ts, "px": float(price), "atr": round(a, 8), "tk": list(tokens)[:30], "kind": kind,
                                "dec": dec_id, "nxt": time.time() + 4 * int(tf) * 60, "res": None})
            global _dirty
            _dirty = True
        return cid
    except Exception:
        return None


def simulate(side, entry, atr_v, bars):
    """bars = [(high, low, close)] AFTER the signal candle. -> result dict, or None if it is not decided yet."""
    if not entry or not atr_v:
        return None
    dist = STOP_ATR * atr_v
    buy = str(side).upper() == "BUY"
    stop = entry - dist if buy else entry + dist
    tgt = entry + RR * dist if buy else entry - RR * dist
    fee_r = (FEE_PCT / 100.0) * entry / dist
    mfe = mae = 0.0
    for k, (h, l, c) in enumerate(bars[:MAX_BARS], 1):
        fav = (h - entry) / dist if buy else (entry - l) / dist
        adv = (entry - l) / dist if buy else (h - entry) / dist
        hit_stop = (l <= stop) if buy else (h >= stop)
        hit_tgt = (h >= tgt) if buy else (l <= tgt)
        if hit_stop:                                        # both in one candle = stop first (cautious)
            return {"r": round(-1.0 - fee_r, 3), "o": "stop", "mfe": round(max(mfe, min(fav, 0.999)), 2), "mae": round(max(mae, 1.0), 2), "b": k}
        if hit_tgt:
            return {"r": round(RR - fee_r, 3), "o": "target", "mfe": round(max(mfe, RR), 2), "mae": round(mae, 2), "b": k}
        mfe, mae = max(mfe, fav), max(mae, adv)
    if len(bars) >= MAX_BARS:
        last = bars[MAX_BARS - 1][2]
        rr = (last - entry) / dist if buy else (entry - last) / dist
        return {"r": round(rr - fee_r, 3), "o": "timeout", "mfe": round(mfe, 2), "mae": round(mae, 2), "b": MAX_BARS}
    return None


def resolve_some(V, max_syms=4):
    """Fill in shadow outcomes for candidates that are due. Light: few coins per call, one call every 20 s."""
    global _last_resolve, _dirty
    _load()
    now = time.time()
    if now - _last_resolve < 20:
        return False
    _last_resolve = now
    with _lock:
        due = [c for c in _state["c"] if c.get("res") is None and c.get("nxt", 0) <= now]
    if not due:
        _save()
        return False
    groups = {}
    for c in due:
        groups.setdefault((c["sym"], c["tf"]), []).append(c)
    did = False
    for (sym, tf), cs in list(groups.items())[:max_syms]:
        try:
            candles = V._fetch(sym, tf)
        except Exception:
            candles = []
        for c in cs:
            idx = None
            for j in range(len(candles) - 1, -1, -1):
                if candles[j].get("timestamp") == c.get("bar_ts"):
                    idx = j
                    break
            with _lock:
                if idx is None:                              # the candle left the window: too old to judge
                    c["res"] = {"o": "gone"}
                    c["nxt"] = 0
                    _dirty = True
                    did = True
                    continue
                bars = [(_f(x["high"]), _f(x["low"]), _f(x["close"])) for x in candles[idx + 1: idx + 1 + MAX_BARS]]
            r = simulate(c["side"], c["px"], c["atr"], bars)
            with _lock:
                if r is not None:
                    c["res"] = r
                    did = True
                else:
                    c["nxt"] = now + 4 * int(tf) * 60
                _dirty = True
    _save()
    return did


def resolved():
    """Resolved candidates as light rows for the grader and the evidence screens."""
    _load()
    with _lock:
        return [{"t": c["t"], "r": c["res"]["r"], "tk": c["tk"], "src": c["src"], "kind": c.get("kind")}
                for c in _state["c"] if isinstance(c.get("res"), dict) and "r" in c["res"]]


def counts():
    _load()
    with _lock:
        cs = list(_state["c"])
    out = {"total": len(cs), "pending": sum(1 for c in cs if c.get("res") is None), "resolved": 0, "by_src": {}}
    for c in cs:
        r = c.get("res")
        if not (isinstance(r, dict) and "r" in r):
            continue
        out["resolved"] += 1
        s = out["by_src"].setdefault(c["src"], {"n": 0, "wins": 0, "net_r": 0.0})
        s["n"] += 1
        s["wins"] += 1 if r["r"] > 0 else 0
        s["net_r"] += r["r"]
    for s in out["by_src"].values():
        s["win_rate"] = round(100.0 * s["wins"] / s["n"]) if s["n"] else None
        s["avg_r"] = round(s["net_r"] / s["n"], 3) if s["n"] else None
        s["net_r"] = round(s["net_r"], 2)
    return out


def recent(V, limit=40):
    """Latest candidates for the app, with a plain stage joined from the Vision decision (WATCH / READY / TAKEN / REJECTED)."""
    _load()
    with _lock:
        cs = list(_state["c"][-300:])
    with V._lock:
        decs = {d.get("id"): dict(d) for d in V._state.get("dec", [])[-600:]}
    out = []
    for c in reversed(cs):
        if c.get("kind") == "rejected":
            continue                                          # the sampled rejects count in the stats, they would only clutter the list
        d = decs.get(c.get("dec")) or {}
        st = str(d.get("status") or "")
        stage = "TAKEN" if st == "taken" else ("READY" if (st == "waiting" and d.get("gate_note")) else "WATCH" if st in ("waiting", "queued") else "REJECTED")
        res = c.get("res") if isinstance(c.get("res"), dict) else None
        out.append({"id": c["id"], "src": c["src"], "symbol": c["sym"], "side": c["side"], "t": c["t"], "stage": stage,
                    "grade": d.get("grade") or "", "grade_why": d.get("grade_why") or "", "gate_note": d.get("gate_note") or "",
                    "reason": d.get("reason") or "", "shadow": res})
        if len(out) >= limit:
            break
    return out
