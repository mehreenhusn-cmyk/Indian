"""v2_f8_runner.py - FILTER STUDY Part 8A: runs the study Parts 1, 1B, 2, 3A, 3B, 4, 5A, 5B, 6 one after the other and SAVES each summary in the data folder.
Why: the study files print their summary on the screen only. The app's Lab tab needs them as files, and the owner does not want to run anything by hand (README_FILTER.md).
READ-ONLY study: this file starts the Part scripts as separate low-priority processes (nice 10). It changes no setting, no trade, no order. Nothing here touches the bot.
Files in the data folder:
  v2_filter_sum_<id>.json   the summary of one Part (id = f1, f1b, f2, f3a, f3b, f4, f5a, f5b, f6, f5c, f6b). Written to a .tmp file first, then renamed, so the app never reads half a file.
  v2_f8_run.json            the run state: running, current Part, done (with seconds), failed (with the reason), started / finished time.
Start from code:  import v2_f8_runner as R;  R.start(root)  -> (True / False, text).  The runner never runs twice at once (a state file that was not updated for 60 min counts as dead).
By hand (normally not needed):  python3 v2_f8_runner.py --data /home/owl/owl_data
Day = 00:00 UTC = 5:30 AM IST. Durations over 60 min are written as hours + minutes."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = "v2_f8_runner 1 (Filter Part 8A)"
STATE_FILE, SUM_FILE = "v2_f8_run.json", "v2_filter_sum_%s.json"
PARTS = (("f1", "v2_f1_counts.py", "Part 1 counts"), ("f1b", "v2_f1b_learn.py", "Part 1B Sniper LEARN + b3"), ("f2", "v2_f2_fakes.py", "Part 2 fake signals"),
         ("f3a", "v2_f3a_moves.py", "Part 3A rallies and dumps"), ("f3b", "v2_f3b_catch.py", "Part 3B caught / missed"), ("f4", "v2_f4_filters.py", "Part 4 filter lab"),
         ("f5a", "v2_f5a_exits.py", "Part 5A exit lab 1"), ("f5b", "v2_f5b_exits.py", "Part 5B exit lab 2"), ("f6", "v2_f6_decisions.py", "Part 6 four words"),
         ("f5c", "v2_f5c_booking.py", "Part 5C split booking"), ("f6b", "v2_f6b_entry.py", "Part 6B entry lab (runs last)"))
PART_IDS = tuple(p[0] for p in PARTS)
IDLE_IO = ["ionice", "-c3"] if shutil.which("ionice") else []   # disk only when nobody else needs it (the study reads a 1.3 million row candle store)
PART_TIMEOUT = 45 * 60          # one Part may run 45 min at most
DEAD_SEC = 60 * 60              # a run whose state file is older than this is treated as dead


def _low():
    """Runs in the child before it starts: lower priority (posix only)."""
    try:
        os.nice(19)   # lowest CPU priority (was 10: the live bot still felt the study run, 9 Nov)
    except Exception:
        pass


def _write(root, st):
    """Atomic write of the state file (never raises)."""
    p = os.path.join(root, STATE_FILE)
    try:
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(st, f, separators=(",", ":"))
        os.replace(p + ".tmp", p)
    except Exception:
        pass


def read_state(root):
    try:
        with open(os.path.join(root, STATE_FILE), "r", encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def is_running(root):
    st = read_state(root)
    return bool(st.get("running")) and time.time() - (st.get("updated_ts") or 0) < DEAD_SEC


def summary_time(root, pid):
    """File time of a saved summary (epoch seconds) or None."""
    try:
        return os.path.getmtime(os.path.join(root, SUM_FILE % pid))
    except OSError:
        return None


def start(root):
    """Starts one run in its own process. -> (started, text). Never raises."""
    root = os.path.realpath(root)
    if is_running(root):
        return False, "A study run is already going on."
    now = time.time()
    _write(root, {"running": True, "started_ts": now, "updated_ts": now, "current": None, "done": [], "failed": [], "finished_ts": None})   # blocks a second start at once
    try:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--data", root], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, preexec_fn=_low)
    except Exception as e:
        _write(root, {"running": False, "started_ts": now, "updated_ts": time.time(), "current": None, "done": [], "failed": [{"id": "start", "why": str(e)[:160]}], "finished_ts": time.time()})
        return False, "Could not start: %s" % str(e)[:120]
    return True, "Study run started."


def run_all(root):
    root = os.path.realpath(root)
    now = time.time()
    st = {"running": True, "started_ts": now, "updated_ts": now, "current": None, "done": [], "failed": [], "finished_ts": None}
    _write(root, st)
    for pid, script, label in PARTS:
        st["current"], st["updated_ts"] = pid, time.time()
        _write(root, st)
        out = os.path.join(root, SUM_FILE % pid)
        t0 = time.time()
        try:
            res = subprocess.run(IDLE_IO + [sys.executable, os.path.join(HERE, script), "--data", root, "--out", out + ".tmp"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                 timeout=PART_TIMEOUT, preexec_fn=_low, text=True)
            if res.returncode == 0 and os.path.isfile(out + ".tmp"):
                os.replace(out + ".tmp", out)
                st["done"].append({"id": pid, "label": label, "seconds": int(time.time() - t0)})
            else:
                st["failed"].append({"id": pid, "label": label, "why": (res.stderr or "exit code %s" % res.returncode).strip()[-200:]})
        except subprocess.TimeoutExpired:
            st["failed"].append({"id": pid, "label": label, "why": "took more than 45 min, stopped"})
        except Exception as e:
            st["failed"].append({"id": pid, "label": label, "why": str(e)[:200]})
        try:
            os.remove(out + ".tmp")
        except OSError:
            pass
    st.update({"running": False, "current": None, "updated_ts": time.time(), "finished_ts": time.time()})
    _write(root, st)
    return st


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 8A: run Parts 1 to 6 and save the summaries")
    ap.add_argument("--data")
    a = ap.parse_args(argv)
    sys.path.insert(0, HERE)
    import v2_inventory as I
    st = run_all(I.find_data_dir(a.data))
    sys.stderr.write("Study run finished: %d done, %d failed. Nothing was changed in trading.\n" % (len(st["done"]), len(st["failed"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
