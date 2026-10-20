"""ops_status.py - ONE plain answer to "which code is running, since when, did it restart, what went wrong".

Read-only. Never raises (every part is wrapped). Used by GET /api/ops (the app's left-swipe Backend panel) and by the
app-settings backup (GET/POST /api/app_prefs) so a freshly installed app gets its theme / sound choices back.
Sources: ~/.owl_last_zip (written by owl_auto.sh when it deploys a zip), ~/owl_backend.log (written by start_forever.sh).
"""
import json
import os
import re
import time

BUILD = "2026-10-20"
_T0 = time.time()
_HOME = os.path.expanduser("~")
_MARK = os.path.join(_HOME, ".owl_last_zip")
_OVDONE = os.path.join(_HOME, ".owl_overlays_done")
_BLOG = os.path.join(_HOME, "owl_backend.log")
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROBLEM = re.compile(r"Traceback|Error|ERROR|STALL|CRASH LOOP|WARNING|exited with code [^0]", re.I)


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


def snapshot(data_dir=""):
    out = {"build": BUILD, "pid": os.getpid(), "started_at": int(_T0), "uptime_s": int(time.time() - _T0),
           "data_dir": data_dir or "", "now": int(time.time())}
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
        }
    except Exception:
        pass
    try:
        lines = _tail_lines(_BLOG)
        starts = [l for l in lines if "starting backend" in l]
        exits = [l for l in lines if "exited with code" in l]
        loops = [l for l in lines if "CRASH LOOP" in l]
        day = time.strftime("[%Y-%m-%d")
        out["restarts_today"] = sum(1 for l in starts if l.startswith(day))
        out["starts_in_log"] = len(starts)
        out["crash_loops"] = len(loops)
        out["last_exits"] = [l[:140] for l in exits[-3:]]
        seen, probs = set(), []
        for l in reversed(lines):
            if _PROBLEM.search(l) and "exited with code 0" not in l:
                k = re.sub(r"^\[[^\]]*\]\s*", "", l)[:90]
                if k in seen:
                    continue
                seen.add(k)
                probs.append(l.strip()[:170])
                if len(probs) >= 6:
                    break
        out["problems"] = probs
    except Exception:
        out["problems"] = []
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
