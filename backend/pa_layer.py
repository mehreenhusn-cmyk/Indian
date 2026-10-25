#!/usr/bin/env python3
"""
pa_layer.py - PRICE ACTION LIGHT (observation layer, version 2). It only WATCHES and writes its own log. It never trades,
never skips, never touches Dual Bot (dual_lab_data.json is only READ) and never changes Smart Brain.

For every Dual Bot trade it looks at the signal candle and the next few candles and writes down, in plain numbers:
  - how the signal candle closed (strong in the trade direction, or weak),
  - rejection wicks (a long wick against the trade = sellers / buyers pushed back),
  - did the candle break the previous candle's high / low (long / short),
  - how big the candle was compared with the last 14 (a huge candle often means the move is already used up),
  - did price come back to EMA50 within the next RT_N candles (retest) and was it rejected (held) or broken through.
From that it gives ONE plain verdict for the trade: supports / unclear / against. After the trades finish, report() compares the
verdicts with what Dual Bot's own trades really earned - so you can see whether Price Action reads the market right.
Nothing here is used for trading yet. It is joined with the Brain later, when there is enough data.

Run by hand:  cd backend && python3 pa_layer.py once     (one pass, prints a short summary)
              cd backend && python3 pa_layer.py worker   (normally the backend starts it by itself)
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

LOG_NAME = "pa_layer_log.json"
VIEW_NAME = "pa_layer_view.json"
CYCLE_S = 60
BEAT_STALE_S = 240
RT_N = 6                    # candles after the signal in which a retest of EMA50 is looked for
FETCH_BARS = 500            # candles per coin and timeframe (5m = about 41 h, 15m = about 5 days back)
MAX_FETCH = 10              # coin / timeframe downloads per minute (keeps the phone light)
MAX_AGE_S = 3 * 86400       # trades older than this are not read
KEEP_ROWS = 20000
MIN_JUDGED = 100            # finished trades needed before the report calls itself ready
MIN_GROUP = 20
TF_MS = {"3m": 180_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "2h": 7_200_000}


# ---------------------------------------------------------------- files (read dual_lab's file, write only our own)
def _dir():
    import dual_lab
    return dual_lab._dir()


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


def read_trades():
    """Dual Bot v1's trades. Never writes."""
    data = _load("dual_lab_data.json", {})
    return [t for t in (data.get("trades") or []) if isinstance(t, dict) and t.get("id") and t.get("ct") and t.get("d")]


# ---------------------------------------------------------------- 1. the numbers
def ema(vals, n):
    """EMA seeded with the simple average of the first n values (same idea as the chart indicator)."""
    out = [None] * len(vals)
    if len(vals) < n:
        return out
    e = sum(vals[:n]) / n
    out[n - 1] = e
    k = 2.0 / (n + 1)
    for i in range(n, len(vals)):
        e = vals[i] * k + e * (1 - k)
        out[i] = e
    return out


def features(cs, i, d):
    """Signal candle i, trade direction d (+1 buy, -1 sell). All 0-1 fractions of the candle range. None when it cannot be measured."""
    if i < 15 or i >= len(cs):
        return None
    c = cs[i]
    o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
    rng = h - l
    if rng <= 0:
        return None
    up_wick, dn_wick = (h - max(o, cl)) / rng, (min(o, cl) - l) / rng
    prev = cs[i - 1]
    avg = sum(x["high"] - x["low"] for x in cs[i - 14:i]) / 14.0
    closes = [x["close"] for x in cs[:i + 1]]
    e = ema(closes, 50)[i]
    return {"body": round(abs(cl - o) / rng, 2),
            "close_pos": round(((cl - l) if d > 0 else (h - cl)) / rng, 2),          # 1 = closed at the far end in the trade direction
            "wick_fav": round(dn_wick if d > 0 else up_wick, 2),                      # long tail on the side the trade runs away from = buyers / sellers stepped in
            "wick_against": round(up_wick if d > 0 else dn_wick, 2),                  # long tail towards the trade direction = pushed back
            "broke_prev": bool(cl > prev["high"]) if d > 0 else bool(cl < prev["low"]),
            "range_x": round(rng / avg, 2) if avg > 0 else None,
            "ema_gap": round((cl - e) / e * 100.0 * d, 2) if e else None}             # % the close is on the trade side of EMA50


def retest(cs, i, d):
    """Did price come back to EMA50 within RT_N candles after the signal? -> {"state": pending / none / held / broke, "bars": n or None}.
    held = touched EMA50 and closed back on the trade side (rejected). broke = touched and closed through it."""
    closes = [x["close"] for x in cs]
    e = ema(closes, 50)
    last = min(i + RT_N, len(cs) - 1)
    for j in range(i + 1, last + 1):
        if e[j] is None:
            continue
        touched = cs[j]["low"] <= e[j] if d > 0 else cs[j]["high"] >= e[j]
        if touched:
            held = cs[j]["close"] > e[j] if d > 0 else cs[j]["close"] < e[j]
            return {"state": "held" if held else "broke", "bars": j - i}
    if i + RT_N > len(cs) - 1:
        return {"state": "pending", "bars": None}      # not enough candles after the signal yet
    return {"state": "none", "bars": None}


def verdict(f):
    """Plain, fixed rules (no learning): -> (points, 'supports' | 'unclear' | 'against'). Starting guess, checked by report()."""
    pts = 0
    pts += 1 if f["close_pos"] >= 0.67 else -1 if f["close_pos"] <= 0.33 else 0
    pts += 1 if f["wick_fav"] >= 0.40 else 0
    pts -= 1 if f["wick_against"] >= 0.40 else 0
    pts += 1 if f["broke_prev"] else 0
    pts -= 1 if (f["range_x"] or 0) >= 2.5 else 0
    return pts, ("supports" if pts >= 2 else "against" if pts <= -1 else "unclear")


# ---------------------------------------------------------------- 2. the log
def process(trades, log, fetch, now=None, max_fetch=MAX_FETCH):
    """Adds new Dual Bot trades to the log and finishes the retest part of older ones. fetch(sym, tf, n) -> candles oldest first.
    Only writes into `log` (our own file)."""
    now = now or time.time()
    rows = log.setdefault("rows", {})
    log.setdefault("since", now)
    work = {}
    for t in trades:
        if now - t["t"] / 1000.0 > MAX_AGE_S:
            continue
        r = rows.get(t["id"])
        tf_ms = TF_MS.get(t.get("f"), 900_000)
        if r is None:
            work.setdefault((t["s"], t["f"]), []).append(t)
        elif r.get("rt", {}).get("state") == "pending" and now * 1000 >= t["ct"] + (RT_N + 1) * tf_ms:
            work.setdefault((t["s"], t["f"]), []).append(t)
    added = finished = 0
    for (sym, tf), ts in sorted(work.items(), key=lambda kv: min(x["t"] for x in kv[1]))[:max_fetch]:
        try:
            cs = fetch(sym, tf, FETCH_BARS)
        except Exception:
            cs = None
        if not cs:
            continue
        idx = {c["timestamp"]: k for k, c in enumerate(cs)}
        for t in ts:
            k = idx.get(t["ct"])
            if k is None:
                if t["id"] not in rows and now - t["t"] / 1000.0 > MAX_AGE_S / 2:
                    rows[t["id"]] = {"s": sym, "f": tf, "d": t["d"], "t": t["t"], "miss": True}      # too old to measure, do not try again
                continue
            if t["id"] in rows:
                rt = retest(cs, k, t["d"])
                if rt["state"] != "pending":
                    rows[t["id"]]["rt"] = rt
                    finished += 1
                continue
            f = features(cs, k, t["d"])
            if f is None:
                rows[t["id"]] = {"s": sym, "f": tf, "d": t["d"], "t": t["t"], "miss": True}
                continue
            pts, v = verdict(f)
            rows[t["id"]] = {"s": sym, "f": tf, "d": t["d"], "t": t["t"], "f_": f, "pts": pts, "v": v, "rt": retest(cs, k, t["d"])}
            added += 1
    if len(rows) > KEEP_ROWS:                                       # oldest go first
        for k in sorted(rows, key=lambda x: rows[x]["t"])[:len(rows) - KEEP_ROWS]:
            del rows[k]
    return {"added": added, "retests_done": finished, "pending": sum(1 for r in rows.values() if r.get("rt", {}).get("state") == "pending")}


# ---------------------------------------------------------------- 3. the report
def _agg(items, usdt):
    n = len(items)
    w = sum(1 for _, t in items if t["net"] > 0)
    pnl = round(sum(usdt(t) for _, t in items), 2)
    return {"n": n, "wins": w, "win_pct": int(round(100.0 * w / n)) if n else None, "pnl": pnl, "avg": round(pnl / n, 2) if n else None}


def report(trades, log, now=None):
    """Did Price Action read the finished Dual Bot trades right? Real USDT, fee inside. Report only."""
    import dual_lab
    now = now or time.time()
    rows = log.get("rows") or {}
    usdt = lambda t: dual_lab._mg(t) * t["net"] / 100.0
    joined = [(rows[t["id"]], t) for t in trades if t.get("id") in rows and rows[t["id"]].get("v") and t.get("status") == "closed" and t.get("net") is not None]
    out = {"logged": sum(1 for r in rows.values() if r.get("v")), "judged": len(joined), "need": MIN_JUDGED,
           "days": round((now - float(log.get("since") or now)) / 86400.0, 1), "status": "collecting", "verdicts": [], "retests": [], "text": ""}
    names = (("supports", "Price Action supports the trade"), ("unclear", "Unclear"), ("against", "Price Action is against the trade"))
    out["verdicts"] = [dict(_agg([x for x in joined if x[0]["v"] == k], usdt), key=k, name=nm) for k, nm in names]
    rn = (("held", "Came back to EMA50 and was rejected (held)"), ("broke", "Came back to EMA50 and broke through"), ("none", "Never came back"))
    out["retests"] = [dict(_agg([x for x in joined if x[0].get("rt", {}).get("state") == k], usdt), key=k, name=nm) for k, nm in rn]
    if len(joined) < MIN_JUDGED:
        out["text"] = "Collecting: %d trades watched, %d finished. The first read needs %d finished." % (out["logged"], len(joined), MIN_JUDGED)
        return out
    out["status"] = "ready"
    s, a = out["verdicts"][0], out["verdicts"][2]
    if s["n"] >= MIN_GROUP and a["n"] >= MIN_GROUP:
        edge = round(s["avg"] - a["avg"], 2)
        half = len(joined) // 2
        srt = sorted(joined, key=lambda x: x[1]["t"])
        sign = []
        for part in (srt[:half], srt[half:]):
            ps, pa = [x for x in part if x[0]["v"] == "supports"], [x for x in part if x[0]["v"] == "against"]
            sign.append(None if len(ps) < 5 or len(pa) < 5 else (_agg(ps, usdt)["avg"] > _agg(pa, usdt)["avg"]))
        out["edge"], out["steady"] = edge, (sign[0] is not None and sign[0] == sign[1])
        out["text"] = ("Trades Price Action supported earned %+.2f USDT each, trades it was against %+.2f. Difference %+.2f USDT per trade. %s"
                       % (s["avg"], a["avg"], edge, "The older and the newer half agree." if out["steady"] else "Not proven in both halves yet."))
    else:
        out["text"] = "%d finished trades read. Too few in the 'supports' or 'against' group yet to compare." % len(joined)
    return out


# ---------------------------------------------------------------- 4. worker (own low-priority process)
def _lock():
    try:
        import fcntl
    except Exception:
        return -1
    for path in (os.path.join(os.path.expanduser("~"), ".owl_pa_layer.lock"), _p("pa_layer.lock")):
        try:
            fd = os.open(path, os.O_CREAT | os.O_RDWR)
        except Exception:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            os.close(fd)
            return None
        except Exception:
            os.close(fd)
            continue
    return -1


def worker():
    lock = _lock()
    if lock is None:
        print("pa_layer: already running", flush=True)
        return 0
    try:
        os.nice(10)
    except Exception:
        pass
    try:
        from recovered_bot.dns_fallback import ensure_dns_fallback
        ensure_dns_fallback()
    except Exception:
        pass
    from recovered_bot import ai_shadow_lab as LAB
    print("pa_layer worker started", flush=True)
    while True:
        err = ""
        try:
            ctl = _load("pa_layer_ctl.json", {"enabled": True})
            if ctl.get("enabled", True):
                trades = read_trades()
                log = _load(LOG_NAME, {})
                st = process(trades, log, LAB._fetch_limit)
                _save(LOG_NAME, log)
                view = {"beat": time.time(), "enabled": True, "report": report(trades, log), "last": st}
            else:
                view = {"beat": time.time(), "enabled": False, "report": _load(VIEW_NAME, {}).get("report"), "last": {}}
            _save(VIEW_NAME, view)
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, str(e)[:120])
            try:
                v = _load(VIEW_NAME, {})
                v.update(beat=time.time(), error=err)
                _save(VIEW_NAME, v)
            except Exception:
                pass
        time.sleep(CYCLE_S)


# ---------------------------------------------------------------- 5. backend side
_SPAWN = {"t": 0.0}


def ensure_running():
    """Starts the worker when its heartbeat is stale. A second copy cannot start (file lock)."""
    try:
        if not _load("pa_layer_ctl.json", {"enabled": True}).get("enabled", True):
            return False
        view = _load(VIEW_NAME, {})
        if time.time() - float(view.get("beat") or 0) < BEAT_STALE_S or time.time() - _SPAWN["t"] < 60:
            return False
        _SPAWN["t"] = time.time()
        log = open(_p("pa_layer.log"), "a", encoding="utf-8")
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "worker"], stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, cwd=HERE)
        return True
    except Exception:
        return False


def status():
    view = _load(VIEW_NAME, {})
    age = time.time() - float(view.get("beat") or 0) if view.get("beat") else None
    return {"running": age is not None and age < BEAT_STALE_S, "report": view.get("report"), "last": view.get("last"), "error": view.get("error", "")}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "worker":
        worker()
    else:
        from recovered_bot import ai_shadow_lab as LAB
        tr, lg = read_trades(), {}
        print(json.dumps(process(tr, lg, LAB._fetch_limit)), json.dumps(report(tr, lg))[:800])
