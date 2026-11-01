"""owl_sniper_feed.py - OwlSniper Part S4 of 7: the FEED. It reads the saved 5m candles of v2_market.db (READ-ONLY), gives them to OwlSniperLive (owl_sniper_prob.py) and saves two small result files in the data folder.
It is a WATCHER: no order, no trade, no bot / Brain / Dual Bot file is imported or touched, the market store is opened read-only and never written.
Own files (all in the data folder, all written atomically):
  v2_sniper_model.json  the slow part: SD-length search + win-chance model + 85% floor proof + equity curve of the TEST days. Made again after 24 h (6 h when the model could not be learned, 30 min when there were no candles yet).
  v2_sniper_live.json   the fast part: one scan of the newest closed candle of up to 40 coins, headline, Safe / Sideways banner, order cards (newest first, no repeats). Made again after about 4.5 min.
  v2_sniper_lock        only ONE refresh runs at a time (a lock older than 30 min is treated as dead).
  v2_sniper_off         if this file exists nothing starts by itself any more (delete it to switch back on).
Auto start without Termux commands: the read-only route (api/sniper.py, Part S5) calls kick(). kick() starts `owl_sniper_feed.py refresh` as its OWN process (low priority, own lock) when the live file is older than 4.5 min,
so the API process never waits for the maths. Run by hand (optional): python3 backend/owl_sniper_feed.py status | calibrate | scan | refresh | off | on
Candle rows: (open_ts, o, h, l, c, v) in seconds, the store keeps only CLOSED candles. Calibration uses the NEWEST gap-free run of every coin (the engine needs one gap-free run per coin)."""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import owl_sniper_prob as P
import v2_defs as D
import v2_inventory as I
import v2_setup_finder as SF
import v2_store as S

VERSION = "owl_sniper_feed 1 (Part S4)"
INTERVAL = "5m"
MODEL_FILE, LIVE_FILE, LOCK_FILE, OFF_FILE, KICK_FILE = "v2_sniper_model.json", "v2_sniper_live.json", "v2_sniper_lock", "v2_sniper_off", "v2_sniper_kick"
MAX_COINS = 40                       # same cap as the candle collector
TAIL = 700                           # newest candles read per coin for a scan (SD 200 + regime window 50 + indicator warm-up)
MODEL_MAX_AGE = {"OK": 24 * 3600, "NOT_TRAINED": 6 * 3600, "NO_DATA": 30 * 60}
LIVE_MAX_AGE, LOCK_STALE, KICK_GAP = 270, 30 * 60, 60
KEEP_CARDS, EQUITY_POINTS, N_TRIALS = 30, 60, 25
STALE_STEPS = 3                      # a coin whose newest candle is older than 3 candle steps is skipped (counted as stale), never scanned on old data
SHOW = ("SNIPER_LONG", "SNIPER_SHORT", "BLOCK_TRADE")


# ---------------------------------------------------------------- small file helpers
def _p(d, name):
    return os.path.join(os.path.realpath(d), name)


def read_json(d, name):
    """The saved dict, or None when the file is missing or broken (never raises)."""
    try:
        p = _p(d, name)
        if os.path.islink(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            x = json.load(f)
        return x if isinstance(x, dict) else None
    except (OSError, ValueError):
        return None


def write_json(d, name, obj):
    """Atomic write (temp file, then rename). False when the folder cannot be written."""
    p = _p(d, name)
    try:
        if os.path.islink(p):
            return False
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(obj, f, separators=(",", ":"), allow_nan=False)
        os.replace(p + ".tmp", p)
        return True
    except (OSError, ValueError):
        return False


def lock_busy(d, now=None):
    now = time.time() if now is None else now
    try:
        return now - os.path.getmtime(_p(d, LOCK_FILE)) < LOCK_STALE
    except OSError:
        return False


def lock_take(d, now=None):
    if lock_busy(d, now):
        return False
    try:
        os.remove(_p(d, LOCK_FILE))                      # a dead (stale) lock
    except OSError:
        pass
    try:
        fd = os.open(_p(d, LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except OSError:
        return False


def lock_free(d):
    try:
        os.remove(_p(d, LOCK_FILE))
    except OSError:
        pass


# ---------------------------------------------------------------- candles in (read-only)
def open_ro(d):
    """Read-only connection to the market store, or None when it does not exist yet (it is NEVER created here)."""
    path = S.store_path(d)
    if not os.path.isfile(path):
        return None
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    con.execute("PRAGMA query_only=ON")
    return con


def symbols(con, interval=INTERVAL, cap=MAX_COINS):
    """The coins with the most saved candles (they have the longest history)."""
    rows = con.execute("SELECT symbol, COUNT(*) n FROM candles WHERE interval=? GROUP BY symbol ORDER BY n DESC, symbol LIMIT ?", (interval, int(cap))).fetchall()
    return [r[0] for r in rows]


def newest_run(rows, interval=INTERVAL):
    """Rows -> the NEWEST gap-free run of clean candles ([] when none). Gaps are cut, never bridged."""
    good, _bad = D.clean_candles(rows, interval)
    runs = SF.runs(good, interval)
    return runs[-1] if runs else []


def load_runs(d, interval=INTERVAL, cap=MAX_COINS):
    """[(symbol, newest gap-free run)] for up to `cap` coins. [] when the store or the candles are missing."""
    con = open_ro(d)
    if con is None:
        return []
    out = []
    try:
        for sym in symbols(con, interval, cap):
            run = newest_run(D.candles_from_store(con, sym, interval, 0, 2 ** 31), interval)
            if run:
                out.append((sym, run))
    finally:
        con.close()
    return out


def load_tail(con, sym, interval=INTERVAL, n=TAIL):
    rows = con.execute("SELECT open_ts, o, h, l, c, v FROM candles WHERE symbol=? AND interval=? ORDER BY open_ts DESC LIMIT ?", (sym, interval, int(n))).fetchall()
    rows.reverse()
    return rows


# ---------------------------------------------------------------- the slow part: calibrate
def _thin(xs, k=EQUITY_POINTS):
    if len(xs) <= k:
        return list(xs)
    step = -(-len(xs) // k)
    pts = xs[::step]
    if (len(xs) - 1) % step:                             # the newest point is always kept
        pts.append(xs[-1])
    return pts


def _equity(eng, sets):
    """Running net USDT of the TEST-day trades: all of them (after the sideways guard) and only those the model rated at the floor or more."""
    _tr, te = eng.collect_trades(sets)
    te = sorted(te, key=lambda t: t["exit_t"])
    allc, flo, a, f = [], [], 0.0, 0.0
    for t in te:
        a += t["net_usdt"]
        if eng.model and P.predict(eng.model, t["feat"]) >= eng.floor:
            f += t["net_usdt"]
        allc.append(round(a, 4))
        flo.append(round(f, 4))
    return {"test_trades": len(te), "all": _thin(allc), "floor": _thin(flo)}


def calibrate(d, interval=INTERVAL, n_trials=N_TRIALS, seed=42, now=None):
    """Search + learn + save v2_sniper_model.json. -> the saved dict. Slow (minutes on a phone): it runs in its own process."""
    now = int(time.time() if now is None else now)
    runs = load_runs(d, interval)
    rec = {"version": VERSION, "saved_at": now, "interval": interval, "coins": [s for s, _ in runs], "status": "NO_DATA", "lines": [], "model": None,
           "is_trained": False, "floor_verified": False, "verdict": None, "floor_check": None, "curve": [], "sd_curve": [], "split": None, "guard": None, "equity": None}
    if not runs:
        rec["lines"] = ["No saved %s candles yet, so OwlSniper cannot learn. The candle collector must run first." % interval]
        write_json(d, MODEL_FILE, rec)
        return rec
    sets = [r for _, r in runs]
    eng = P.OwlSniperLive()
    res = eng.run_all(sets, n_trials, seed)
    cal, pro = res["calibration"], res["probability"]
    rec.update(status="OK" if eng.is_trained else "NOT_TRAINED", lines=res["lines"], model=eng.export_model(), is_trained=eng.is_trained, floor_verified=eng.floor_verified,
               verdict=cal.get("verdict"), floor_check=pro.get("floor_check"), curve=pro.get("curve") or [], sd_curve=cal.get("curve") or [], split=cal.get("split"), guard=cal.get("guard"))
    if eng.is_trained:
        rec["equity"] = _equity(eng, sets)
    write_json(d, MODEL_FILE, rec)
    return rec


# ---------------------------------------------------------------- the fast part: scan
def _card(sym, r):
    c = r.get("confidence")
    return {"symbol": sym, "action": r["action"], "side": r.get("side"), "reason": r["reason"], "confidence": None if c is None else round(c, 4), "entry_price": r.get("entry_price"),
            "stop_loss": r.get("stop_loss"), "take_profit": r.get("take_profit"), "regime": r.get("regime"), "report": r["report"], "t": r.get("t")}


def _banner(reg):
    tot = sum(reg.values())
    if not tot:
        return "UNKNOWN"
    if (reg["SIDEWAYS"] + reg["UNKNOWN"]) / float(tot) >= 0.6:
        return "SIDEWAYS"
    return "TRENDING" if reg["TRENDING"] / float(tot) >= 0.6 else "MIXED"


def _headline(counts, reg, scanned, floor, verified):
    n_ok = counts["SNIPER_LONG"] + counts["SNIPER_SHORT"]
    if n_ok:
        return "%d coin(s) pass every check right now. Watch only, no order is sent." % n_ok
    txt = "No coin passes right now. %d of %d coins are sideways or unclear, %d signal(s) were blocked." % (reg["SIDEWAYS"] + reg["UNKNOWN"], scanned, counts["BLOCK_TRADE"])
    return txt if verified else txt + " The %.0f%% floor is not proven yet, so no signal can pass." % (floor * 100.0)


def scan(d, interval=INTERVAL, now=None):
    """One look at the newest closed candle of every coin -> save v2_sniper_live.json. Needs the model file (made by calibrate)."""
    now = int(time.time() if now is None else now)
    prev = read_json(d, LIVE_FILE) or {}
    m = read_json(d, MODEL_FILE) or {}
    live = {"version": VERSION, "saved_at": now, "interval": interval, "status": "NO_MODEL", "headline": "OwlSniper is learning for the first time. This page fills by itself.", "banner": "UNKNOWN",
            "counts": {}, "regimes": {}, "coins_scanned": 0, "stale_coins": 0, "floor": 0.85, "floor_verified": False, "cards": prev.get("cards") or []}
    eng = P.OwlSniperLive()
    if not (m.get("model") and eng.load_model(m["model"])):
        if m:                                            # a model file exists but it holds no learned model: say why in plain words
            live.update(status="NOT_READY", headline=(m.get("lines") or ["OwlSniper is not ready yet."])[-1])
        write_json(d, LIVE_FILE, live)
        return live
    live.update(floor=eng.floor, floor_verified=eng.floor_verified)
    con = open_ro(d)
    if con is None:
        live.update(status="NO_DATA", headline="The market store does not exist yet, so there is nothing to scan.")
        write_json(d, LIVE_FILE, live)
        return live
    counts = dict((k, 0) for k in ("STANDBY", "SCANNING_MARKET", "BLOCK_TRADE", "SNIPER_LONG", "SNIPER_SHORT"))
    reg, fresh, stale, step = {"TRENDING": 0, "SIDEWAYS": 0, "UNKNOWN": 0}, [], 0, D.STEP[interval]
    try:
        for sym in symbols(con, interval, MAX_COINS):
            run = newest_run(load_tail(con, sym, interval), interval)
            if not run or run[-1][0] + STALE_STEPS * step < now:
                stale += 1
                continue
            r = eng.evaluate_live(run)
            counts[r["action"]] = counts.get(r["action"], 0) + 1
            reg[r["regime"]] = reg.get(r["regime"], 0) + 1
            if r["action"] in SHOW:
                fresh.append(_card(sym, r))
    finally:
        con.close()
    scanned = sum(counts.values())
    seen, cards = set(), []
    for c in sorted(fresh + (prev.get("cards") or []), key=lambda x: (x.get("t") or 0), reverse=True):      # newest first, one card per coin + side + candle
        key = (c.get("symbol"), c.get("side"), c.get("t"))
        if key not in seen:
            seen.add(key)
            cards.append(c)
    live.update(status="OK" if scanned else "NO_DATA", counts=counts, regimes=reg, coins_scanned=scanned, stale_coins=stale, banner=_banner(reg), cards=cards[:KEEP_CARDS],
                headline=_headline(counts, reg, scanned, eng.floor, eng.floor_verified) if scanned else "No coin has fresh candles right now (%d are stale)." % stale)
    write_json(d, LIVE_FILE, live)
    return live


# ---------------------------------------------------------------- the self-starting part
def refresh(d, now=None, force=False):
    """Calibrate when the model is missing or old, then scan. One at a time (lock). Always leaves a live file behind, also after an error."""
    if not lock_take(d, now):
        return {"skipped": "another refresh is running"}
    try:
        now = int(time.time() if now is None else now)
        m = read_json(d, MODEL_FILE)
        if force or m is None or now - int(m.get("saved_at") or 0) > MODEL_MAX_AGE.get(m.get("status"), 6 * 3600):
            calibrate(d, now=now)
        return scan(d, now=now)
    except Exception as e:                               # own process: leave a plain note instead of dying silently
        live = {"version": VERSION, "saved_at": int(time.time()), "status": "ERROR", "headline": "OwlSniper could not finish (%s). It will try again by itself." % e.__class__.__name__,
                "banner": "UNKNOWN", "counts": {}, "regimes": {}, "coins_scanned": 0, "stale_coins": 0, "floor": 0.85, "floor_verified": False, "cards": (read_json(d, LIVE_FILE) or {}).get("cards") or []}
        write_json(d, LIVE_FILE, live)
        return live
    finally:
        lock_free(d)


def kick(d, now=None):
    """Called by the read-only route. Starts `refresh` as its own low-priority process when the live file is old. -> True when a process was started. Never raises, never waits."""
    now = time.time() if now is None else now
    try:
        if os.path.exists(_p(d, OFF_FILE)) or lock_busy(d, now):
            return False
        live = read_json(d, LIVE_FILE)
        if live and now - float(live.get("saved_at") or 0) < LIVE_MAX_AGE:
            return False
        try:
            if now - os.path.getmtime(_p(d, KICK_FILE)) < KICK_GAP:      # a start that died at once must not be repeated on every screen refresh
                return False
        except OSError:
            pass
        with open(_p(d, KICK_FILE), "w", encoding="utf-8") as f:
            f.write(str(int(now)))
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "refresh", "--data", d], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
        return True
    except (OSError, ValueError):
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper feed (watcher only, never trades)")
    ap.add_argument("cmd", choices=("status", "calibrate", "scan", "refresh", "off", "on"))
    ap.add_argument("--data")
    a = ap.parse_args(argv)
    d = I.find_data_dir(a.data)
    try:
        os.nice(10)                                      # the maths must never slow the bot down
    except (OSError, AttributeError):
        pass
    try:
        if a.cmd == "off":
            open(_p(d, OFF_FILE), "w").close()
            print("OwlSniper auto start: OFF")
        elif a.cmd == "on":
            try:
                os.remove(_p(d, OFF_FILE))
            except OSError:
                pass
            print("OwlSniper auto start: ON")
        elif a.cmd == "status":
            x = read_json(d, LIVE_FILE) or {}
            print(VERSION, "|", x.get("status", "no live file yet"), "|", x.get("headline", ""))
        elif a.cmd == "calibrate":
            print("\n".join(calibrate(d)["lines"]))
        elif a.cmd == "scan":
            print(scan(d)["headline"])
        else:
            r = refresh(d)
            print(r.get("headline") or r.get("skipped"))
    except (S.StoreRefused, OSError) as e:
        print("STOP:", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
