"""ops_status.py - ONE plain answer to "which code is running, since when, did it restart, what went wrong".

Read-only. Never raises (every part is wrapped). Used by GET /api/ops (the app's left-swipe Backend panel) and by the
app-settings backup (GET/POST /api/app_prefs) so a freshly installed app gets its theme / sound choices back.
Sources: ~/.owl_last_zip (written by owl_auto.sh when it deploys a zip), ~/owl_backend.log (written by start_forever.sh).

Oct 20 Part A: problems + exits are scoped to the CURRENT run only (after the last "starting backend" line),
each problem line keeps its timestamp, and restart reasons are summarised when the log has them.
"""
import json
import os
import re
import time

BUILD = "2026-10-22-part9"
_T0 = time.time()
_HOME = os.path.expanduser("~")
_MARK = os.path.join(_HOME, ".owl_last_zip")
_OVDONE = os.path.join(_HOME, ".owl_overlays_done")
_BLOG = os.path.join(_HOME, "owl_backend.log")
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROBLEM = re.compile(r"Traceback|Error|ERROR|STALL|CRASH LOOP|WARNING|exited with code [^0]", re.I)
_TS_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")


def _tail_lines(path, max_bytes=200000):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", "replace").splitlines()
    except Exception:
        return []


def _zip_info():
    try:
        parts = open(_MARK).read().split()
        if len(parts) >= 3:
            mtime = int(parts[-1])
            return {"name": os.path.basename(" ".join(parts[:-2])), "zip_time": mtime, "deployed_at": int(os.path.getmtime(_MARK))}
    except Exception:
        pass
    return {"name": "", "zip_time": 0, "deployed_at": 0}


def _current_run_slice(lines):
    """Return only lines that belong to the latest 'starting backend' run (inclusive)."""
    last_start = -1
    for i, l in enumerate(lines):
        if "starting backend" in l:
            last_start = i
    if last_start < 0:
        return lines, None
    start_line = lines[last_start]
    m = _TS_RE.match(start_line)
    started_at = m.group(1) if m else None
    return lines[last_start:], started_at


def snapshot(data_dir=""):
    out = {
        "build": BUILD,
        "pid": os.getpid(),
        "started_at": int(_T0),
        "uptime_s": int(time.time() - _T0),
        "data_dir": data_dir or "",
        "now": int(time.time()),
    }
    try:
        out["zip"] = _zip_info()
        try:
            out["overlays"] = sum(1 for _ in open(_OVDONE))
        except Exception:
            out["overlays"] = 0
        out["has"] = {
            "vision_notebook": os.path.exists(os.path.join(_HERE, "ai_vision_lessons.py")),
            "india_fast_ticks": os.path.exists(os.path.join(_HERE, "..", "test_india_ticks.py")),
            "free_keys_4": "ai4_api_key" in open(os.path.join(_HERE, "settings_store.py")).read(),
            "ai_health": os.path.exists(os.path.join(_HERE, "ai_health.py")),
        }
    except Exception:
        pass
    try:
        all_lines = _tail_lines(_BLOG)
        # Whole-log stats (restarts today still need the full day)
        starts = [l for l in all_lines if "starting backend" in l]
        day = time.strftime("[%Y-%m-%d")
        out["restarts_today"] = sum(1 for l in starts if l.startswith(day))
        out["starts_in_log"] = len(starts)

        # Current-run only
        run_lines, run_started = _current_run_slice(all_lines)
        out["run_started"] = run_started
        exits = [l for l in run_lines if "exited with code" in l]
        loops = [l for l in run_lines if "CRASH LOOP" in l]
        out["crash_loops"] = len(loops)
        out["last_exits"] = [l[:160] for l in exits[-3:]]

        # Restart reasons (from lines that mention why the previous process died)
        reasons = []
        for l in run_lines:
            if "CRASH LOOP" in l or "exited with code" in l:
                reasons.append(l.strip()[:160])
        out["restart_reasons"] = reasons[-5:]

        # Problems: unique, current run only, keep timestamp
        seen, probs = set(), []
        for l in reversed(run_lines):
            if _PROBLEM.search(l) and "exited with code 0" not in l:
                body = re.sub(r"^\[[^\]]*\]\s*", "", l)[:100]
                if body in seen:
                    continue
                seen.add(body)
                probs.append(l.strip()[:180])
                if len(probs) >= 8:
                    break
        out["problems"] = probs
        out["problems_scope"] = "current_run"
    except Exception:
        out["problems"] = []
        out["problems_scope"] = "error"
    return out


# ---------------------------------------------------------------- app settings backup (theme, sounds ...)
_ALLOWED = {"theme_mode", "voice_enabled", "voice_entry", "voice_exit", "voice_fg_only", "sm_settings"}


def _prefs_path(data_dir):
    return os.path.join(data_dir, "app_prefs.json")


def prefs_get(data_dir):
    try:
        from recovered_bot import safe_io
        d, _src = safe_io.read_json_safe(_prefs_path(data_dir), "app prefs")
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def prefs_merge(data_dir, incoming):
    """Only whitelisted keys, only str/bool/int values, small. Returns the stored dict."""
    cur = prefs_get(data_dir)
    if isinstance(incoming, dict):
        for k, v in incoming.items():
            if k in _ALLOWED and isinstance(v, (str, bool, int)) and len(str(v)) < 4000:
                cur[k] = v
    try:
        from recovered_bot import safe_io
        safe_io.write_json_atomic(_prefs_path(data_dir), cur)
    except Exception:
        pass
    return cur
