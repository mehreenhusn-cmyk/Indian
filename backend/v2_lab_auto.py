"""v2_lab_auto.py - Part 17c: LAB AUTO-RUN. Two jobs that the owner used to start by hand in Termux now run by themselves, inside the V2 runner worker (v2_runner.py):
  1. Scalp Lab fill   = v2_scalp_run.run(data_dir): replays the saved candles and saves the FINISHED hypothetical records in v2_scalp.db (same code as the hand command).
  2. Knowledge Ledger = v2_playbook_use.build_report() then v2_ledger_fill.fill(): copies the Playbook leads / avoid slots into v2_ledger.db (same code as the hand command).
Every 6 hours (first run 5 min after the worker starts, then only when the saved last run is older than 6 h, so a restart never repeats it at once).
Each step has its own try / except: one failing step never stops the other, and a failure never stops the runner. The result of the last run is in v2_lab_auto.json (the app shows it).
Nothing is traded and no setting is changed. Writes only v2_scalp.db, v2_ledger.db and v2_lab_auto.json. No network.
OWNER SWITCH: create an empty file v2_lab_auto_off in the data folder to stop it (delete the file to start it again).
"""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

VERSION = "v2_lab_auto 1 (Part 17c)"
STATE_FILE, OFF_FILE = "v2_lab_auto.json", "v2_lab_auto_off"
EVERY_S, FIRST_DELAY_S, CHECK_S = 6 * 3600, 300, 600
_RUN_LOCK = threading.Lock()


def _p(data_dir, name):
    return os.path.join(os.path.realpath(data_dir), name)


def read_state(data_dir):
    """-> the saved result of the last run, or {} (no file / unreadable / a link). Never raises."""
    p = _p(data_dir, STATE_FILE)
    try:
        if os.path.islink(p):
            return {}
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data_dir, st):
    p = _p(data_dir, STATE_FILE)
    if os.path.islink(p):
        return False
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(tmp, p)
    return True


def switched_off(data_dir):
    return os.path.lexists(_p(data_dir, OFF_FILE))


def due(data_dir, now=None):
    now = time.time() if now is None else float(now)
    if switched_off(data_dir):
        return False
    try:
        last = float(read_state(data_dir).get("last_run_ts") or 0)
    except (TypeError, ValueError):
        last = 0.0
    return now - last >= EVERY_S


def _scalp(data_dir):
    import v2_scalp_run as SR
    res = SR.run(data_dir)
    if not res.get("ready"):
        return res.get("note", "Scalp Lab not ready")
    saved = sum((v.get("saved_new") or 0) for c in res.get("categories", []) for v in c.get("versions", []))
    return "%d new finished record(s)" % saved


def _ledger(data_dir):
    import v2_ledger_fill as LF
    import v2_playbook_use as PU
    rep = PU.build_report(data_dir)
    if rep.get("error"):
        return str(rep["error"])
    r = LF.fill(data_dir, rep, False)
    return "found %d, new %d, new versions %d, unchanged %d" % (r["found"], r["new_findings"], r["new_versions"], r["unchanged"])


def run_once(data_dir, now=None):
    """Runs both steps once (one run at a time). -> the saved state dict. Never raises."""
    now = time.time() if now is None else float(now)
    if not _RUN_LOCK.acquire(blocking=False):
        return read_state(data_dir)
    try:
        steps = {}
        for name, fn in (("scalp_lab", _scalp), ("ledger", _ledger)):
            t0 = time.time()
            try:
                steps[name] = {"ok": True, "note": fn(data_dir), "secs": round(time.time() - t0, 1)}
            except Exception as e:                       # one failing step must never stop the other
                steps[name] = {"ok": False, "note": "%s: %s" % (type(e).__name__, str(e)[:100]), "secs": round(time.time() - t0, 1)}
        st = {"version": VERSION, "last_run_ts": int(now), "runs": int(read_state(data_dir).get("runs") or 0) + 1, "every_hours": EVERY_S // 3600, "steps": steps}
        try:
            _save(data_dir, st)
        except OSError:
            pass
        return st
    finally:
        _RUN_LOCK.release()


def loop(data_dir):
    """Own thread inside the runner worker. Never raises, never ends."""
    time.sleep(FIRST_DELAY_S)
    while True:
        try:
            if due(data_dir):
                run_once(data_dir)
        except Exception:
            pass
        time.sleep(CHECK_S)
