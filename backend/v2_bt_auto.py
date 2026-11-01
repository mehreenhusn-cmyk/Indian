"""v2_bt_auto.py - Part 89a-auto: BRAIN TRADER AUTO-RUNNER. The owner does not want Termux commands: everything must start from git by itself, together with the backend.
It is ONE more thread inside the Part 72 runner worker (v2_runner.py), so no protected file (api_server.py) is touched: the backend already starts that worker by itself.
Jobs (both already built, both PAPER only, pretend money, no order code, LIVE stays locked):
  TICK  every 5 minutes, about 100 s after each 5m candle closes (the candle collector needs that time): v2_bt_wait.tick = close finished paper trades, look at every followed coin, answer finished waits. Writes only v2_brain_trader.db.
  STUDY every 6 hours (first one 5 minutes after the start, or at once when the saved study is older than 6 h): v2_bt_zonestudy.run_study, then (Part 89b) v2_bt_limits.run_study. Writes only v2_bt_zonestudy_5m.json and v2_bt_limits_5m.json.
Own status file v2_bt_auto_status.json (last tick, last study, error counts, last error NAME only). Every job is inside try / except: one bad coin or one bad round never stops the thread or the collectors.
OWNER SWITCH STAYS IN CHARGE: the first start (marker file v2_bt_auto_first_on) switches it ON once because the owner asked for auto; after that the file v2_bt_auto_enabled decides.
Switch it off for good:  python3 backend/v2_bt_auto.py off   (the thread keeps idling and never switches itself back on)   |  on  |  status  |  once (one tick + one study now, then print).
No network (candles come from the collector's saved store), no trading import."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "v2_bt_auto 1 (Part 89a-auto)"
FLAG, FIRST, STATUS = "v2_bt_auto_enabled", "v2_bt_auto_first_on", "v2_bt_auto_status.json"
STEP, DELAY, STUDY_EVERY, STUDY_FIRST, IDLE = 300, 100, 6 * 3600, 300, 20


def _p(data_dir, name):
    return os.path.join(os.path.realpath(data_dir), name)


def is_enabled(data_dir):
    p = _p(data_dir, FLAG)
    try:
        if os.path.islink(p) or not os.path.isfile(p):
            return False
        with open(p, "r", encoding="utf-8") as f:
            return f.read(10).strip().lower() in ("1", "on", "true", "yes")
    except OSError:
        return False


def set_enabled(data_dir, on):
    with open(_p(data_dir, FLAG), "w", encoding="utf-8") as f:
        f.write("1\n" if on else "0\n")


def first_on(data_dir):
    m = _p(data_dir, FIRST)
    if os.path.lexists(m):
        return False
    set_enabled(data_dir, True)
    with open(m, "w", encoding="utf-8") as f:
        f.write("first start: Brain auto-runner switched ON once (owner asked for auto, 1 Nov 2026)\n")
    return True


def read_status(data_dir):
    try:
        with open(_p(data_dir, STATUS), "r", encoding="utf-8") as f:
            x = json.load(f)
            return x if isinstance(x, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data_dir, st):
    p = _p(data_dir, STATUS)
    if os.path.islink(p):
        return
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(tmp, p)


def do_tick(data_dir, now=None):
    import v2_bt_store as B
    import v2_bt_wait as W
    con = B.connect(data_dir)
    try:
        r = W.tick(con, data_dir, now, "PAPER", "5m")
        try:                                                       # Part E3: BT-02 (the Brain decides the exit) walks beside it in SHADOW only; if it fails PAPER still counts
            W.tick(con, data_dir, now, "SHADOW", "5m", "BT-02")
        except Exception:
            pass
    finally:
        con.close()
    return {"coins": len(r.get("coins", [])), "no_data": len(r.get("no_data", [])), "opened": sum(1 for c in r.get("coins", []) if c.get("trade_opened"))}


def do_study(data_dir, now=None):
    import v2_bt_zonestudy as Z
    r = Z.run_study(data_dir, "5m", now)
    out = {"coins": len(r["coins"]), "cases": r["cases"]}
    try:                                                           # Part 89b: the squeeze + limits study rides on the same 6-hour job; if it fails the zone study result still counts
        import v2_bt_limits as L
        q = L.run_study(data_dir, "5m", now)
        out.update({"squeeze_ends": q["squeeze_ends"], "limit_entries": q["entries"]})
    except Exception as e:
        out["limits_error"] = type(e).__name__
    return out


def _study_age(data_dir):
    try:
        return time.time() - os.path.getmtime(_p(data_dir, "v2_bt_zonestudy_5m.json"))
    except OSError:
        return None


def step(data_dir, st, now):
    """One look at the clock. Runs a job when it is due. Never raises. -> the updated status dict."""
    bucket = int((now - DELAY) // STEP)
    if st.get("tick_bucket") != bucket and now % STEP >= DELAY:
        st["tick_bucket"] = bucket
        try:
            st["last_tick"] = dict(do_tick(data_dir, now), ts=int(now))
        except Exception as e:
            st["tick_errors"] = st.get("tick_errors", 0) + 1
            st["last_error"] = {"job": "tick", "name": type(e).__name__, "ts": int(now)}
    due = st.get("study_due")
    if due is None:
        age = _study_age(data_dir)
        due = st["study_due"] = now + STUDY_FIRST if age is None or age > STUDY_EVERY else now + max(STUDY_FIRST, STUDY_EVERY - age)
    if now >= due:
        st["study_due"] = now + STUDY_EVERY
        try:
            st["last_study"] = dict(do_study(data_dir, now), ts=int(now))
        except Exception as e:
            st["study_errors"] = st.get("study_errors", 0) + 1
            st["last_error"] = {"job": "study", "name": type(e).__name__, "ts": int(now)}
    return st


def loop(data_dir, max_rounds=None, clock=time.time, sleep=time.sleep):
    """The thread body (started by v2_runner.worker). Never raises, never switches itself back on after the owner said off."""
    try:
        first_on(data_dir)
    except OSError:
        pass
    st = {"version": VERSION}
    rounds = 0
    while max_rounds is None or rounds < max_rounds:
        rounds += 1
        try:
            if is_enabled(data_dir):
                step(data_dir, st, clock())
                st["enabled"] = True
            else:
                st["enabled"] = False
            st["beat"] = int(clock())
            _save(data_dir, st)
        except Exception as e:
            try:
                st["last_error"] = {"job": "loop", "name": type(e).__name__, "ts": int(clock())}
            except Exception:
                pass
        sleep(IDLE)
    return st


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("status", "on", "off", "once"))
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    a = ap.parse_args(argv)
    if a.cmd in ("on", "off"):
        set_enabled(a.data, a.cmd == "on")
    if a.cmd == "once":
        print(json.dumps({"tick": do_tick(a.data), "study": do_study(a.data)}, indent=1))
        return 0
    print(json.dumps({"version": VERSION, "switch": "ON" if is_enabled(a.data) else "OFF", "status": read_status(a.data)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
