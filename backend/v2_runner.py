"""v2_runner.py - Part 72: COLLECTOR AUTO-START. Starts the two V2 collectors by itself so the data clock runs (Radar needs it).

What it runs (both already built, both public-GET only, both write only v2_market.db, no trading file touched):
  v2_collector.loop  (Part 16: every 5 min one ticker GET -> top gainers / losers + the 00:00 UTC cohort)
  v2_candles.loop    (Part 17: closed 3m / 5m candles for max 40 coins, request budget, gaps recorded)
  v2_bt_auto.loop    (Part 89a-auto: the paper Brain tick every 5 min + the zone study every 6 h; own thread, own switch file v2_bt_auto_enabled)
How it starts: the backend calls start_watchdog(DATA_DIR) 45 s after boot (same pattern as the Brain / Dual / Price Action workers). The watchdog
checks every 2 min; if the worker's heartbeat file (v2_runner_beat.json) is older than 2 min it starts ONE worker (own process, file lock, so a
second copy cannot run). A dead loop ends the worker, so the watchdog starts a fresh one. Log: v2_runner.log in the data folder (cut at 1 MB).
OWNER SWITCHES STAY IN CHARGE: the first start (only the first, marker file v2_runner_first_on) switches both collectors ON because the owner
said "ok kro"; after that the switch files decide. `python3 backend/v2_collector.py --off` and `python3 backend/v2_candles.py --off` stop the
collecting for good (the worker keeps idling and never switches them back on). Not started when the data folder is not usable.
Run by hand (optional): python3 backend/v2_runner.py status | start | worker
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import v2_candles as K
import v2_collector as C
import v2_inventory as I
import v2_store as S

VERSION = "v2_runner 1 (Part 72)"
BEAT_FILE, LOCK_FILE, FIRST_ON, LOG_FILE = "v2_runner_beat.json", "v2_runner.lock", "v2_runner_first_on", "v2_runner.log"
BEAT_STALE_S, BEAT_EVERY_S, WATCH_EVERY_S, SPAWN_GAP_S, LOG_MAX = 120, 30, 120, 60, 1000000
_SPAWN = {"t": 0.0}


def _p(data_dir, name):
    return os.path.join(os.path.realpath(data_dir), name)


def read_beat(data_dir):
    """-> seconds since the worker's last heartbeat, or None (no file / unreadable / a link)."""
    p = _p(data_dir, BEAT_FILE)
    try:
        if os.path.islink(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            return max(0.0, time.time() - float(json.load(f).get("beat")))
    except (OSError, ValueError, TypeError):
        return None


def write_beat(data_dir):
    p = _p(data_dir, BEAT_FILE)
    if os.path.islink(p):
        return False
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"beat": time.time(), "pid": os.getpid(), "version": VERSION}, f)
    os.replace(tmp, p)
    return True


def first_on(data_dir):
    """Switches BOTH collectors ON the first time only (marker file). After that the owner's switch files decide. -> True if it switched them."""
    m = _p(data_dir, FIRST_ON)
    if os.path.lexists(m):
        return False
    C.set_enabled(data_dir, True)
    K.set_enabled(data_dir, True)
    with open(m, "w", encoding="utf-8") as f:
        f.write("first start: both collector switches set ON once (owner ok, Part 72)\n")
    return True


def ensure_running(data_dir):
    """Starts the worker when its heartbeat is stale. Never raises. -> True if a worker was started."""
    try:
        d = os.path.realpath(data_dir)
        age = read_beat(d)
        if (age is not None and age < BEAT_STALE_S) or time.time() - _SPAWN["t"] < SPAWN_GAP_S:
            return False
        _SPAWN["t"] = time.time()
        lp = _p(d, LOG_FILE)
        big = os.path.exists(lp) and os.path.getsize(lp) > LOG_MAX
        log = open(lp, "w" if big else "a", encoding="utf-8")
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "worker", "--data", d], stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, cwd=HERE)
        return True
    except Exception:
        return False


def start_watchdog(data_dir, first_delay=45.0):
    """Called once by the backend. Checks every WATCH_EVERY_S seconds (daemon timers, they never keep the backend alive). Never raises."""
    def tick():
        ensure_running(data_dir)
        t = threading.Timer(WATCH_EVERY_S, tick)
        t.daemon = True
        t.start()
    try:
        t = threading.Timer(first_delay, tick)
        t.daemon = True
        t.start()
        return True
    except Exception:
        return False


def status(data_dir):
    age = read_beat(data_dir)
    return {"version": VERSION, "running": age is not None and age < BEAT_STALE_S, "beat_age_s": None if age is None else round(age),
            "ticker_switch": "ON" if C.is_enabled(data_dir) else "OFF", "candle_switch": "ON" if K.is_enabled(data_dir) else "OFF",
            "first_on_done": os.path.lexists(_p(data_dir, FIRST_ON))}


def worker(data_dir):
    d = os.path.realpath(data_dir)
    lock = open(_p(d, LOCK_FILE), "a")
    try:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        pass
    except BlockingIOError:
        print("another runner is already working: exit")
        return 0
    except OSError as e:
        # 31 Oct fix: the shared-storage folder on the phone may not support file locks at all (any other OSError than "busy").
        # That used to be reported as "another runner" and EVERY worker quit before its first heartbeat. Now: no lock there, and the
        # fresh heartbeat decides (the watchdog only starts a worker when the beat is stale, plus a 60 s gap).
        age = read_beat(d)
        if age is not None and age < BEAT_STALE_S:
            print("another runner has a fresh heartbeat: exit")
            return 0
        print("file lock not supported here (%s): working without it" % type(e).__name__, flush=True)
    try:
        print("runner start:", VERSION, "first_on:", first_on(d), flush=True)
    except (S.StoreRefused, OSError) as e:
        print("STOP:", e)
        return 1
    threads = [threading.Thread(target=C.loop, args=(d,), name="ticker", daemon=True),
               threading.Thread(target=K.loop, args=(d,), name="candles", daemon=True)]
    for t in threads:
        t.start()
    try:                    # Part 89a-auto: the Brain tick + zone study run in this same worker (own thread, never stops the collectors)
        import v2_bt_auto as BA
        threading.Thread(target=BA.loop, args=(d,), name="brain", daemon=True).start()
    except Exception as e:
        print("brain auto-runner not started: %s" % type(e).__name__, flush=True)
    while all(t.is_alive() for t in threads):
        try:
            write_beat(d)
        except OSError:
            pass
        time.sleep(BEAT_EVERY_S)
    print("a collector loop ended: runner stops, the backend watchdog starts a new one", flush=True)
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl V2 collector runner")
    ap.add_argument("cmd", choices=("status", "start", "worker"))
    ap.add_argument("--data")
    a = ap.parse_args(argv)
    d = I.find_data_dir(a.data)
    if a.cmd == "worker":
        return worker(d)
    if a.cmd == "start":
        print("worker started" if ensure_running(d) else "not started (already running or just started)")
    print(json.dumps(status(d), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
