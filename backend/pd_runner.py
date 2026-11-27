"""pd_runner.py - ONE background thread that runs the Pump / Dump scanner (PD). Started once by api_server.py after boot.
Loop every poll_sec: feed.poll() -> features of the coins that moved -> tracker (stage events) -> learner (outcomes, missed, daily tuner).
Switch: <data>/pumpdump/enabled.json {"enabled": true/false} (the app has the switch). Off = the thread sleeps, makes NO network call and frees the history.
A network error never stops it: it backs off (20 s ... 120 s) and says so in the app. Read README5 "PUMP DUMP SCANNER"."""
import os
import threading
import time

import pd_config as C
import pd_feed
import pd_chance
import pd_learn
import pd_pre
import pd_rank
import pd_scorer as S
import pd_store as ST
import pd_tracker
import pd_tsi

_R = {"thread": None, "stop": False, "feed": None, "tracker": None, "learn": None, "rank": None, "pre": None, "lock": threading.RLock(),
      "state": {"running": False, "enabled": True, "last_poll": 0.0, "last_error": "", "errors": 0, "polls": 0, "tracked": 0, "started": 0.0, "events_today": 0, "restored": 0}}
_SAVE_EVERY = 120  # seconds between history saves (Round E)
_last_save = [0.0]


def enabled():
    return bool(ST.read_json("enabled.json", {"enabled": True}).get("enabled", True))


def set_enabled(on):
    ST.write_json("enabled.json", {"enabled": bool(on), "changed": int(time.time())})
    _R["state"]["enabled"] = bool(on)


def _emit(ev):
    ST.append("events", ev["day"], ev)
    _R["state"]["events_today"] = _R["state"].get("events_today", 0) + 1
    if ev["stage"] == "START" and _R["learn"] is not None:
        _R["learn"].add_start(ev)
    if ev["stage"] == "START" and _R["pre"] is not None:      # Round 2: how long before this START did "Taiyari me" show the coin?
        try:
            _R["pre"].on_start(ev)
        except Exception as e:
            print(f"[pd] pre lead failed: {type(e).__name__}: {e}")
    print("[pd] %s %s %s %+.1f%% vol %.1fx score %s" % (ev["stage"], ev["side"], ev["symbol"], ev["r5"], ev["vr5"], ev["score"]))


def step(feed, tracker, learn, now, rank=None, pre=None):
    """ONE poll cycle (also used by the test). Returns the number of coins tracked."""
    n = feed.poll(now)
    poll = C.get("poll_sec")
    prices = {}
    warm = feed.warm_left_min(now) <= 0
    for sym, h in feed.hist.items():
        if not h.t or h.t[-1] != now:
            continue
        prices[sym] = h.p[-1]
        qv24 = feed.meta[sym]["qv24"]
        # cheap pre-filter: only a coin that moved at least 0.3% in 5 min, or is already tracked, gets the full numbers
        quiet = len(h.t) > 20 and abs(h.p[-1] / h.p[max(0, len(h.p) - 16)] - 1.0) * 100.0 < 0.3
        if quiet and not tracker.is_active(sym, "pump") and not tracker.is_active(sym, "dump"):
            continue
        f = S.features(h, now, qv24, poll)
        if f is None:
            continue
        if warm:
            tracker.eval_symbol(sym, f, now, qv24)
            learn.check_missed(sym, f, now, tracker, qv24)
    learn.track(prices, now)
    if warm:
        learn.tune_if_due(now, tracker)
        if rank is not None:          # Round 1: Naye Movers + Chal rahe. A problem here must never stop the scanner.
            try:
                rank.update(feed, tracker, now)
            except Exception as e:
                print(f"[pd] rank step failed: {type(e).__name__}: {e}")
        if pre is not None:           # Round 2: Taiyari me (pre-pump / pre-dump). Coins already in the Round 1 lists are left out. Never stops the scanner.
            try:
                skip = set()
                if rank is not None:
                    for grp in (rank.snap["movers"], rank.snap["running"]):
                        skip.update(r["symbol"] for side in grp for r in grp[side])
                pre.update(feed, tracker, now, skip)
            except Exception as e:
                print(f"[pd] pre step failed: {type(e).__name__}: {e}")
    return n


def _loop(data_dir):
    st = _R["state"]
    feed, tracker, learn, rank, pre = _R["feed"], _R["tracker"], _R["learn"], _R["rank"], _R["pre"]
    backoff = 0
    st.update(running=True, started=time.time())
    while not _R["stop"]:
        try:
            on = enabled()
            st["enabled"] = on
            if not on:
                if feed.hist:
                    feed.clear()
                    tracker.states.clear()
                    rank.clear()
                    pre.clear()
                time.sleep(5)
                continue
            now = time.time()
            n = step(feed, tracker, learn, now, rank, pre)
            st.update(last_poll=now, tracked=n, polls=feed.polls, last_error="")
            if now - _last_save[0] >= _SAVE_EVERY and feed.warm_left_min(now) <= 0:
                _last_save[0] = now
                try:
                    feed.save(C.path("feed_cache.json.gz"), now)
                except Exception as e:
                    print(f"[pd] history save failed ({type(e).__name__})")
            backoff = 0
            time.sleep(max(1.0, C.get("poll_sec") - (time.time() - now)))
        except Exception as e:
            backoff = min(120, (backoff or 10) * 2)
            st["errors"] += 1
            st["last_error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
            print(f"[pd] poll failed ({st['last_error']}), retry in {backoff}s")
            time.sleep(backoff)
    st["running"] = False


def start(data_dir):
    """Called once at boot. Safe to call twice."""
    with _R["lock"]:
        if _R["thread"] is not None and _R["thread"].is_alive():
            return False
        C.init(data_dir)
        _R["feed"] = pd_feed.Feed()
        _R["state"]["restored"] = _R["feed"].load(C.path("feed_cache.json.gz"))  # Round E: no warm-up after a short restart
        if _R["state"]["restored"]:
            print(f"[pd] history restored for {_R['state']['restored']} coins, no warm-up")
        _R["learn"] = pd_learn.Learner()
        _R["tracker"] = pd_tracker.Tracker(_emit)
        _R["tracker"].adj = dict(_R["learn"].tuner.get("coin_adj", {}))
        _R["rank"] = pd_rank.Rank(pd_tsi.Klines(), pd_chance.Chance())
        _R["pre"] = pd_pre.Pre(_R["rank"].kl)       # Round 2: shares the candle cache of Round 1 (one cap of calls per minute for both)
        _R["stop"] = False
        _R["state"]["enabled"] = enabled()
        t = threading.Thread(target=_loop, args=(data_dir,), daemon=True, name="pd_scanner")
        _R["thread"] = t
        t.start()
        print(f"[pd] Pump / Dump scanner started ({C.VERSION}), data folder: {C.root()}")
        return True


def stop():
    _R["stop"] = True


def live(now=None):
    """What the app's top part shows: status + the coins in play on each side + the last START events."""
    now = time.time() if now is None else now
    st = dict(_R["state"])
    feed, tracker = _R["feed"], _R["tracker"]
    snap = tracker.snapshot() if tracker is not None else {"pump": [], "dump": []}
    for side in snap:
        for r in snap[side]:
            r["age_min"] = round((now - r["since"]) / 60.0, 1)
    return {"version": C.VERSION, "enabled": st["enabled"], "running": st["running"], "last_poll_age": round(now - st["last_poll"], 1) if st["last_poll"] else None,
            "last_error": st["last_error"], "errors": st["errors"], "polls": st["polls"], "tracked": st["tracked"],
            "warm_left_min": round(feed.warm_left_min(now), 1) if feed is not None else None, "restored": st.get("restored", 0), "poll_sec": C.get("poll_sec"),
            "pump": snap["pump"], "dump": snap["dump"], "latest_starts": list(tracker.recent[:10]) if tracker is not None else [],
            "auto_tune": (_R["learn"].tuner.get("auto_tune", True) if _R["learn"] is not None else True)}


def movers(now=None):
    """Round 1: what the app's "Naye Movers" + "Pehle se chal rahe" section shows (GET /api/pd/movers)."""
    now = time.time() if now is None else now
    rk = _R["rank"]
    if rk is None:
        return {"state": "off", "ready": False, "movers": {"pump": [], "dump": []}, "running": {"pump": [], "dump": []}}
    out = rk.snapshot(now)
    out["enabled"] = _R["state"]["enabled"]
    out["warm_left_min"] = round(_R["feed"].warm_left_min(now), 1) if _R["feed"] is not None else None
    return out


def pre_view(now=None):
    """Round 2: what the app's \"Taiyari me\" section shows (GET /api/pd/pre)."""
    now = time.time() if now is None else now
    pr = _R["pre"]
    if pr is None:
        return {"state": "off", "ready": False, "pre": {"pump": [], "dump": []}}
    out = pr.snapshot(now)
    out["enabled"] = _R["state"]["enabled"]
    out["warm_left_min"] = round(_R["feed"].warm_left_min(now), 1) if _R["feed"] is not None else None
    return out


def set_auto_tune(on):
    if _R["learn"] is not None:
        _R["learn"].set_auto_tune(on)
        return True
    return False
