#!/usr/bin/env python3
"""
vol_layer.py - VOLUME CONTEXT (observation layer, version 2). It only WATCHES and writes its own log. It never trades, never skips,
never touches Dual Bot (dual_lab_data.json is only READ) and never changes Smart Brain. Same idea as pa_layer.py (Price Action Light);
the small file helpers and the trade reader are shared with it.

For every Dual Bot trade it looks at the volume of the signal candle and the next 3 candles and writes down:
  - relative volume: this candle's volume / the average of the 20 candles before it (low / normal / high / climax),
  - volume trend: were the last 3 candles getting busier or quieter,
  - was the signal candle itself in the trade direction (a BUY candle that closed up),
  - follow-through: did the next 3 candles keep the volume up (building) or die out (fading).
From that it gives ONE plain verdict per trade (supports / unclear / against). After the trades finish, report() compares the verdicts
with what Dual Bot's own trades really earned. Nothing here is used for trading yet; it is joined with the Brain later.

Run by hand:  cd backend && python3 vol_layer.py once     (one pass, prints a short summary)
              cd backend && python3 vol_layer.py worker   (normally the backend starts it by itself)
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pa_layer as PA                       # shared: file helpers, trade reader, group maths

_p, _load, _save, read_trades, _agg = PA._p, PA._load, PA._save, PA.read_trades, PA._agg
LOG_NAME = "vol_layer_log.json"
VIEW_NAME = "vol_layer_view.json"
CYCLE_S, BEAT_STALE_S = 60, 240
AVG_N = 20                  # candles before the signal used as "normal volume"
FW_N = 3                    # candles after the signal used for follow-through
FETCH_BARS, MAX_FETCH, MAX_AGE_S, KEEP_ROWS = PA.FETCH_BARS, PA.MAX_FETCH, PA.MAX_AGE_S, PA.KEEP_ROWS
MIN_JUDGED, MIN_GROUP, TF_MS = PA.MIN_JUDGED, PA.MIN_GROUP, PA.TF_MS


# ---------------------------------------------------------------- 1. the numbers
def features(cs, i, d):
    """Volume numbers of signal candle i for trade direction d (+1 buy, -1 sell). None when it cannot be measured."""
    if i < AVG_N + 3 or i >= len(cs):
        return None
    avg = sum(c["volume"] for c in cs[i - AVG_N:i]) / float(AVG_N)
    if avg <= 0:
        return None
    vx = cs[i]["volume"] / avg
    last3 = sum(c["volume"] for c in cs[i - 2:i + 1]) / 3.0
    prev3 = sum(c["volume"] for c in cs[i - 5:i - 2]) / 3.0
    ratio = last3 / prev3 if prev3 > 0 else 1.0
    c = cs[i]
    return {"vol_x": round(vx, 2),
            "level": "climax" if vx >= 3.0 else "high" if vx >= 1.2 else "low" if vx < 0.8 else "normal",
            "trend": "rising" if ratio > 1.15 else "falling" if ratio < 0.87 else "flat",
            "with_trade": bool((c["close"] > c["open"]) if d > 0 else (c["close"] < c["open"]))}


def follow(cs, i):
    """Next FW_N candles' average volume / the signal candle's volume. -> {"state": pending / building / steady / fading, "x": ratio}."""
    if i + FW_N > len(cs) - 1 or cs[i]["volume"] <= 0:
        return {"state": "pending", "x": None}
    x = sum(c["volume"] for c in cs[i + 1:i + 1 + FW_N]) / FW_N / cs[i]["volume"]
    return {"state": "building" if x > 1.2 else "fading" if x < 0.7 else "steady", "x": round(x, 2)}


def verdict(f):
    """Plain, fixed rules (no learning): -> (points, 'supports' | 'unclear' | 'against'). A starting guess, checked by report()."""
    pts = {"low": -1, "normal": 0, "high": 1, "climax": -1}[f["level"]]      # climax = often the end of a move, not the start
    pts += {"rising": 1, "flat": 0, "falling": -1}[f["trend"]]
    pts += 1 if f["with_trade"] else -1
    return pts, ("supports" if pts >= 2 else "against" if pts <= -1 else "unclear")


# ---------------------------------------------------------------- 2. the log
def process(trades, log, fetch, now=None, max_fetch=MAX_FETCH):
    """Adds new Dual Bot trades to the log and finishes the follow-through of older ones. Only writes into `log` (our own file)."""
    now = now or time.time()
    rows = log.setdefault("rows", {})
    log.setdefault("since", now)
    work = {}
    for t in trades:
        if now - t["t"] / 1000.0 > MAX_AGE_S:
            continue
        r = rows.get(t["id"])
        tf_ms = TF_MS.get(t.get("f"), 900_000)
        if r is None or (r.get("fw", {}).get("state") == "pending" and now * 1000 >= t["ct"] + (FW_N + 1) * tf_ms):
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
            miss = {"s": sym, "f": tf, "d": t["d"], "t": t["t"], "miss": True}
            if k is None:
                if t["id"] not in rows and now - t["t"] / 1000.0 > MAX_AGE_S / 2:
                    rows[t["id"]] = miss
                continue
            if t["id"] in rows:
                fw = follow(cs, k)
                if fw["state"] != "pending":
                    rows[t["id"]]["fw"] = fw
                    finished += 1
                continue
            f = features(cs, k, t["d"])
            if f is None:
                rows[t["id"]] = miss
                continue
            pts, v = verdict(f)
            rows[t["id"]] = {"s": sym, "f": tf, "d": t["d"], "t": t["t"], "f_": f, "pts": pts, "v": v, "fw": follow(cs, k)}
            added += 1
    if len(rows) > KEEP_ROWS:
        for k in sorted(rows, key=lambda x: rows[x]["t"])[:len(rows) - KEEP_ROWS]:
            del rows[k]
    return {"added": added, "follow_done": finished, "pending": sum(1 for r in rows.values() if r.get("fw", {}).get("state") == "pending")}


# ---------------------------------------------------------------- 3. the report
def report(trades, log, now=None):
    """Did the volume reading fit the finished Dual Bot trades? Real USDT, fee inside. Report only."""
    import dual_lab
    now = now or time.time()
    rows = log.get("rows") or {}
    usdt = lambda t: dual_lab._mg(t) * t["net"] / 100.0
    joined = [(rows[t["id"]], t) for t in trades if t.get("id") in rows and rows[t["id"]].get("v") and t.get("status") == "closed" and t.get("net") is not None]
    out = {"logged": sum(1 for r in rows.values() if r.get("v")), "judged": len(joined), "need": MIN_JUDGED,
           "days": round((now - float(log.get("since") or now)) / 86400.0, 1), "status": "collecting", "verdicts": [], "levels": [], "follows": [], "text": ""}
    names = (("supports", "Volume supports the trade"), ("unclear", "Unclear"), ("against", "Volume is against the trade"))
    out["verdicts"] = [dict(_agg([x for x in joined if x[0]["v"] == k], usdt), key=k, name=nm) for k, nm in names]
    lv = (("low", "Low volume (under 0.8x normal)"), ("normal", "Normal volume"), ("high", "High volume (1.2x to 3x)"), ("climax", "Climax volume (3x or more)"))
    out["levels"] = [dict(_agg([x for x in joined if x[0]["f_"]["level"] == k], usdt), key=k, name=nm) for k, nm in lv]
    fw = (("building", "Volume kept building after the signal"), ("steady", "Volume stayed steady"), ("fading", "Volume faded after the signal"))
    out["follows"] = [dict(_agg([x for x in joined if x[0].get("fw", {}).get("state") == k], usdt), key=k, name=nm) for k, nm in fw]
    if len(joined) < MIN_JUDGED:
        out["text"] = "Collecting: %d trades watched, %d finished. The first read needs %d finished." % (out["logged"], len(joined), MIN_JUDGED)
        return out
    out["status"] = "ready"
    s, a = out["verdicts"][0], out["verdicts"][2]
    if s["n"] >= MIN_GROUP and a["n"] >= MIN_GROUP:
        edge = round(s["avg"] - a["avg"], 2)
        srt, half, sign = sorted(joined, key=lambda x: x[1]["t"]), len(joined) // 2, []
        for part in (srt[:half], srt[half:]):
            ps, pa = [x for x in part if x[0]["v"] == "supports"], [x for x in part if x[0]["v"] == "against"]
            sign.append(None if len(ps) < 5 or len(pa) < 5 else (_agg(ps, usdt)["avg"] > _agg(pa, usdt)["avg"]))
        out["edge"], out["steady"] = edge, (sign[0] is not None and sign[0] == sign[1])
        out["text"] = ("Trades volume supported earned %+.2f USDT each, trades it was against %+.2f. Difference %+.2f USDT per trade. %s"
                       % (s["avg"], a["avg"], edge, "The older and the newer half agree." if out["steady"] else "Not proven in both halves yet."))
    else:
        out["text"] = "%d finished trades read. Too few in the 'supports' or 'against' group yet to compare." % len(joined)
    return out


# ---------------------------------------------------------------- 4. worker + backend side
def _lock():
    try:
        import fcntl
    except Exception:
        return -1
    for path in (os.path.join(os.path.expanduser("~"), ".owl_vol_layer.lock"), _p("vol_layer.lock")):
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
        print("vol_layer: already running", flush=True)
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
    print("vol_layer worker started", flush=True)
    while True:
        try:
            if _load("vol_layer_ctl.json", {"enabled": True}).get("enabled", True):
                trades = read_trades()
                log = _load(LOG_NAME, {})
                st = process(trades, log, LAB._fetch_limit)
                _save(LOG_NAME, log)
                view = {"beat": time.time(), "enabled": True, "report": report(trades, log), "last": st}
            else:
                view = {"beat": time.time(), "enabled": False, "report": _load(VIEW_NAME, {}).get("report"), "last": {}}
            _save(VIEW_NAME, view)
        except Exception as e:
            try:
                v = _load(VIEW_NAME, {})
                v.update(beat=time.time(), error="%s: %s" % (type(e).__name__, str(e)[:120]))
                _save(VIEW_NAME, v)
            except Exception:
                pass
        time.sleep(CYCLE_S)


_SPAWN = {"t": 0.0}


def ensure_running():
    """Starts the worker when its heartbeat is stale. A second copy cannot start (file lock)."""
    try:
        if not _load("vol_layer_ctl.json", {"enabled": True}).get("enabled", True):
            return False
        if time.time() - float(_load(VIEW_NAME, {}).get("beat") or 0) < BEAT_STALE_S or time.time() - _SPAWN["t"] < 60:
            return False
        _SPAWN["t"] = time.time()
        log = open(_p("vol_layer.log"), "a", encoding="utf-8")
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
    if (sys.argv[1] if len(sys.argv) > 1 else "once") == "worker":
        worker()
    else:
        import json
        from recovered_bot import ai_shadow_lab as LAB
        tr, lg = read_trades(), {}
        print(json.dumps(process(tr, lg, LAB._fetch_limit)), json.dumps(report(tr, lg))[:800])
