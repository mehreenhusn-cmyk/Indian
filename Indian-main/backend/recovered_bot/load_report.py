"""
load_report.py - the backend's own "where is the load?" report (1 h / 4 h / 24 h) + a daily summary.

Every 30 s a small thread writes one sample: CPU, RAM, how late the event loop was, which API calls were slow, whether the
Binance feed was live. From the samples it answers ONE question in plain words: where is the bottleneck?
(CPU, RAM, event loop freezing, one slow API call, the Binance feed, or Android killing the backend).

Read-only. Never raises. Files: <data_dir>/ops_load.json (last 26 h) and <data_dir>/ops_daily.json (last 14 days).
"""
import json
import os
import re
import threading
import time
from collections import deque

SAMPLE_S = 30
KEEP_S = 26 * 3600
_lock = threading.Lock()
_samples = deque(maxlen=3200)
_api = {}                  # endpoint -> [calls, total_ms, max_ms] inside the current 30 s window
_data_dir = ""
_started = False
_last_save = 0.0
_last_day = ""
_stall_seen = 0.0          # timestamp of the newest stall already counted
_BLOG = os.path.join(os.path.expanduser("~"), "owl_backend.log")
_ID = re.compile(r"/[0-9a-fA-F\-]{8,}|/\d+")


# ------------------------------------------------------------------ recorders
def note_api(path, ms):
    """Called for every API answer (by the server middleware): remembers how long it took."""
    try:
        ep = _ID.sub("/{id}", str(path).split("?", 1)[0])[:60]
        with _lock:
            a = _api.setdefault(ep, [0, 0.0, 0.0])
            a[0] += 1
            a[1] += ms
            if ms > a[2]:
                a[2] = ms
    except Exception:
        pass


def _stalls_new():
    global _stall_seen
    out = []
    try:
        from . import loop_watch
        for s in list(loop_watch._stalls):
            if s["ts"] > _stall_seen:
                out.append({"ms": s["ms"], "where": str(s.get("where", ""))[:160]})
        if loop_watch._stalls:
            _stall_seen = max(s["ts"] for s in loop_watch._stalls)
    except Exception:
        pass
    return out


def _sample():
    from . import telemetry
    snap = telemetry.snapshot() or {}
    cpu = (snap.get("cpu") or {})
    mem = (snap.get("mem") or {})
    feed = (snap.get("feed") or {})
    with _lock:
        api = {k: v for k, v in _api.items()}
        _api.clear()
    top = sorted(api.items(), key=lambda kv: kv[1][1], reverse=True)[:5]
    lag = 0
    try:
        from . import loop_watch
        now = time.time()
        lag = int(max([l for t, l in list(loop_watch._lags) if now - t < SAMPLE_S + 5] or [0]))
    except Exception:
        pass
    return {"t": time.time(),
            "cpu": cpu.get("system_pct") if cpu.get("system_pct") is not None else cpu.get("backend_pct"),
            "bcpu": cpu.get("backend_pct"), "ram": mem.get("sys_pct"),
            "rss": int((mem.get("rss") or 0) / 1048576), "lag": lag, "stalls": _stalls_new(),
            "feed": feed.get("state"), "kage": feed.get("kline_age_s"),
            "bc_ms": (snap.get("broadcast") or {}).get("avg_ms"),
            "api": {k: [v[0], round(v[1]), round(v[2])] for k, v in top}}


# ------------------------------------------------------------------ saving
def _path(name):
    return os.path.join(_data_dir, name) if _data_dir else ""


def _save(force=False):
    global _last_save
    if not _data_dir or (not force and time.time() - _last_save < 300):
        return
    _last_save = time.time()
    try:
        with _lock:
            data = list(_samples)
        tmp = _path("ops_load.json") + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, _path("ops_load.json"))
    except Exception:
        pass


def _load():
    try:
        with open(_path("ops_load.json")) as f:
            data = json.load(f)
        cut = time.time() - KEEP_S
        with _lock:
            for s in data:
                if isinstance(s, dict) and s.get("t", 0) > cut:
                    _samples.append(s)
    except Exception:
        pass


def _restarts(since):
    """Backend starts and crashes written in ~/owl_backend.log since `since` (epoch)."""
    starts, crashes = 0, 0
    try:
        with open(_BLOG, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400000))
            lines = f.read().decode("utf-8", "ignore").splitlines()
        for l in lines:
            m = re.match(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", l)
            if not m:
                continue
            ts = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
            if ts < since:
                continue
            if "starting backend" in l:
                starts += 1
            elif "exited with code" in l and "exited with code 0" not in l:
                crashes += 1
    except Exception:
        pass
    return starts, crashes


# ------------------------------------------------------------------ the report
def _avg(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), 1) if xs else None


def _mx(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(max(xs), 1) if xs else None


def _level(score):
    return "bad" if score >= 70 else "warn" if score >= 40 else "ok"


def build(hours=4.0, samples=None, now=None, starts_crashes=None):
    """-> dict with meters, findings, slow endpoints and the main bottleneck. `samples` is only for tests."""
    now = now or time.time()
    hours = max(0.25, min(24.0, float(hours or 4)))
    since = now - hours * 3600
    with _lock:
        rows = [s for s in (samples if samples is not None else list(_samples)) if s.get("t", 0) >= since]
    n = len(rows)
    out = {"hours": hours, "samples": n, "since": int(since), "now": int(now)}
    if n < 2:
        out.update({"ok": False, "verdict": {"key": "no_data", "title": "Not enough data yet",
                    "why": "The report needs a few minutes of samples. Open it again in 5 minutes.", "fix": ""},
                    "meters": [], "slow": [], "stalls": [], "findings": []})
        out["text"] = _text(out)
        return out
    cpu_avg, cpu_max = _avg([r.get("cpu") for r in rows]), _mx([r.get("cpu") for r in rows])
    ram_avg, ram_max = _avg([r.get("ram") for r in rows]), _mx([r.get("ram") for r in rows])
    lags = [r.get("lag") or 0 for r in rows]
    lag_max = max(lags)
    slow_windows = sum(1 for x in lags if x >= 500)
    stalls = [s for r in rows for s in (r.get("stalls") or [])]
    worst_stall = max([s["ms"] for s in stalls] or [0])
    # API: total time per endpoint
    agg = {}
    for r in rows:
        for ep, (c, tot, mx) in (r.get("api") or {}).items():
            a = agg.setdefault(ep, [0, 0, 0])
            a[0] += c
            a[1] += tot
            a[2] = max(a[2], mx)
    slow = sorted(({"ep": k, "calls": v[0], "avg_ms": round(v[1] / max(1, v[0])), "max_ms": v[2], "total_s": round(v[1] / 1000.0, 1)}
                   for k, v in agg.items()), key=lambda x: x["total_s"], reverse=True)[:6]
    worst_api = max([x["max_ms"] for x in slow] or [0])
    avg_api = max([x["avg_ms"] for x in slow if x["calls"] >= 5] or [0])
    notlive = sum(1 for r in rows if r.get("feed") and r.get("feed") != "LIVE")
    notlive_pct = round(100.0 * notlive / n)
    starts, crashes = starts_crashes if starts_crashes is not None else _restarts(since)
    stall_where = {}
    for s in stalls:
        key = re.sub(r"\s+", " ", s["where"])[:110]
        stall_where[key] = stall_where.get(key, 0) + 1
    top_where = sorted(stall_where.items(), key=lambda kv: kv[1], reverse=True)[:3]

    # score every suspect 0-100 (higher = worse)
    sc = {
        "cpu": min(100, max(0, (cpu_avg or 0) - 40) * 1.6 + max(0, (cpu_max or 0) - 85) * 2),
        "ram": min(100, max(0, (ram_max or 0) - 60) * 2.5),
        "loop": min(100, len(stalls) * 8 + worst_stall / 40.0 + slow_windows * 3),
        "api": min(100, max(avg_api / 12.0, worst_api / 60.0)),
        "feed": min(100, notlive_pct * 2.5),
        "restart": min(100, starts * 12 + crashes * 25),
    }
    meters = [
        {"key": "cpu", "label": "CPU", "score": round(sc["cpu"]), "level": _level(sc["cpu"]), "value": f"{cpu_avg if cpu_avg is not None else '-'}% avg, {cpu_max if cpu_max is not None else '-'}% peak",
         "hint": "How busy the phone's processor is."},
        {"key": "ram", "label": "Memory", "score": round(sc["ram"]), "level": _level(sc["ram"]), "value": f"{ram_avg if ram_avg is not None else '-'}% avg, {ram_max if ram_max is not None else '-'}% peak",
         "hint": "High memory makes Android close apps."},
        {"key": "loop", "label": "Freezes", "score": round(sc["loop"]), "level": _level(sc["loop"]), "value": f"{len(stalls)} freezes, worst {worst_stall / 1000.0:.1f}s",
         "hint": "The backend stopped answering for a moment. This is what makes the app feel stuck."},
        {"key": "api", "label": "Slow answers", "score": round(sc["api"]), "level": _level(sc["api"]), "value": f"slowest {worst_api} ms, typical {avg_api} ms",
         "hint": "How long the backend takes to answer the app."},
        {"key": "feed", "label": "Binance feed", "score": round(sc["feed"]), "level": _level(sc["feed"]), "value": f"not live {notlive_pct}% of the time",
         "hint": "Price stream. Breaks when the internet drops."},
        {"key": "restart", "label": "Restarts", "score": round(sc["restart"]), "level": _level(sc["restart"]), "value": f"{starts} starts, {crashes} crashes",
         "hint": "Each restart means a few seconds of loading in the app."},
    ]
    names = {"cpu": "CPU is too busy", "ram": "Phone memory is almost full", "loop": "The backend freezes for a moment",
             "api": "Some API answers are slow", "feed": "Binance price feed keeps breaking", "restart": "The backend keeps restarting"}
    why, fix = {}, {}
    why["cpu"] = f"CPU averaged {cpu_avg}% and peaked at {cpu_max}%. Too many things run at the same time."
    fix["cpu"] = "Close other heavy apps. Use a longer chart refresh, or fewer background AI jobs."
    why["ram"] = f"Memory peaked at {ram_max}%. Android may close Termux or the app to get memory back."
    fix["ram"] = "Close unused apps. In Termux battery settings choose 'Unrestricted' so it is not killed."
    why["loop"] = (f"{len(stalls)} freezes in {hours:g} h, worst {worst_stall / 1000.0:.1f}s. "
                   + (f"Most common place: {top_where[0][0]}" if top_where else "Exact place was not captured."))
    fix["loop"] = ("Send this report. The place named above is the heavy code that needs to be made lighter.")
    why["api"] = (f"'{slow[0]['ep']}' took {slow[0]['total_s']} s in total (slowest {slow[0]['max_ms']} ms)." if slow else "No slow call found.")
    fix["api"] = "That call returns too much data. Send this report and it can be trimmed."
    why["feed"] = f"The Binance feed was not live for {notlive_pct}% of the time. Prices pause, then the app reloads."
    fix["feed"] = "Check mobile data or WiFi. Switching between WiFi and data cuts the stream."
    why["restart"] = f"{starts} backend starts and {crashes} crashes in {hours:g} h."
    fix["restart"] = "Open the log lines below. Exit code 137/143 means Android closed it (memory or battery saver). 1 means a Python error."
    ranked = sorted(sc.items(), key=lambda kv: kv[1], reverse=True)
    top_key, top_score = ranked[0]
    if top_score < 25:
        verdict = {"key": "ok", "title": "No bottleneck found", "why": f"Everything stayed light in the last {hours:g} h. If the app still feels slow, the cause is inside the app screen, not the backend.", "fix": "", "level": "ok"}
    else:
        verdict = {"key": top_key, "title": names[top_key], "why": why[top_key], "fix": fix[top_key], "level": _level(top_score)}
    findings = [{"key": k, "title": names[k], "why": why[k], "level": _level(v)} for k, v in ranked[1:4] if v >= 40]
    # hourly bars for the small chart
    buckets = {}
    for r in rows:
        buckets.setdefault(int((r["t"] - since) // 3600 if hours > 6 else (r["t"] - since) // 900), []).append(r)
    chart = [{"cpu": _avg([x.get("cpu") for x in b]), "lag": max([x.get("lag") or 0 for x in b])} for _, b in sorted(buckets.items())]
    out.update({"ok": True, "verdict": verdict, "meters": meters, "findings": findings, "slow": slow,
                "stalls": [{"n": c, "where": w} for w, c in top_where], "chart": chart,
                "restarts": {"starts": starts, "crashes": crashes}})
    out["text"] = _text(out)
    return out


def _text(r):
    """Plain text a person (or any AI) can read with no other context."""
    v = r.get("verdict") or {}
    lines = [f"OWL BACKEND LOAD REPORT - last {r.get('hours', 0):g} h ({r.get('samples', 0)} samples, one every {SAMPLE_S}s)",
             f"MAIN BOTTLENECK: {v.get('title', '-')}", f"Why: {v.get('why', '')}"]
    if v.get("fix"):
        lines.append(f"What to do: {v['fix']}")
    if r.get("meters"):
        lines.append("")
        lines.append("Meters (0 = fine, 100 = bad):")
        for m in r["meters"]:
            lines.append(f"  {m['label']}: {m['score']}/100 [{m['level']}]  {m['value']}")
    if r.get("slow"):
        lines.append("")
        lines.append("Slowest API calls (total time):")
        for s in r["slow"]:
            lines.append(f"  {s['ep']}: {s['calls']} calls, typical {s['avg_ms']} ms, slowest {s['max_ms']} ms, total {s['total_s']} s")
    if r.get("stalls"):
        lines.append("")
        lines.append("Where the backend froze:")
        for s in r["stalls"]:
            lines.append(f"  {s['n']}x  {s['where']}")
    for f in r.get("findings") or []:
        lines.append(f"Also: {f['title']} - {f['why']}")
    return "\n".join(lines)


# ------------------------------------------------------------------ daily summary
def daily_list():
    try:
        with open(_path("ops_daily.json")) as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except Exception:
        return []


def _daily_roll():
    """Once per day (first sample after midnight) store yesterday's verdict, keep 14 days."""
    global _last_day
    day = time.strftime("%Y-%m-%d")
    if _last_day == day:
        return
    first = _last_day == ""
    _last_day = day
    if first:
        have = daily_list()
        if have and have[-1].get("day") == time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400)):
            return
    try:
        r = build(24.0)
        if not r.get("ok"):
            return
        rows = daily_list()
        yday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        rows = [x for x in rows if x.get("day") != yday]
        rows.append({"day": yday, "title": r["verdict"]["title"], "why": r["verdict"]["why"],
                     "scores": {m["key"]: m["score"] for m in r["meters"]}, "restarts": r.get("restarts")})
        with open(_path("ops_daily.json"), "w") as f:
            json.dump(rows[-14:], f)
    except Exception:
        pass


# ------------------------------------------------------------------ thread
def _run():
    time.sleep(SAMPLE_S)
    while True:
        try:
            s = _sample()
            with _lock:
                _samples.append(s)
                cut = time.time() - KEEP_S
                while _samples and _samples[0].get("t", 0) < cut:
                    _samples.popleft()
            _save()
            _daily_roll()
        except Exception as e:
            print(f"[load_report] {e}")
        time.sleep(SAMPLE_S)


def start(data_dir):
    global _started, _data_dir
    if _started:
        return
    _started = True
    _data_dir = data_dir or ""
    try:
        if _data_dir:
            os.makedirs(_data_dir, exist_ok=True)
        _load()
        threading.Thread(target=_run, name="load-report", daemon=True).start()
    except Exception as e:
        print(f"[load_report] start: {e}")
