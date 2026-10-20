"""
ai_backup.py - a daily zip of everything the AI has learned, plus a restore that cannot corrupt a running AI.

Why it exists: the backend runs on a phone (Termux). One lost or broken data folder would erase every day of learning
(exit table, coin memory, day plan, Shadow Lab rows). This keeps a zip of the whole AI data folder.

  - run(): zip every file of DATA_DIR/ai (not the backup folder itself, not files over MAX_FILE_MB) -> ai_backups/ai_<date>_<time>.zip
    written to a temp name first, so a half-written zip is never listed. Keeps the newest KEEP zips.
  - start(): own thread, checks every 10 minutes, makes ONE backup per IST day (first check after the day changes).
  - restore(name): copies the chosen zip to a "pending" file. It is applied at the NEXT backend start, before any module
    loads its data (apply_pending, called from the start-up code). Restoring into a running AI would be overwritten by
    its own next save, so it is deliberately done at start-up. A safety backup of the current data is made first.
READ-ONLY for the bot: nothing here touches trades, orders or settings.
"""
import os
import re
import threading
import time
import zipfile

KEEP = 7                      # newest zips kept (older ones are deleted)
MAX_FILE_MB = 60              # a single file bigger than this is skipped (and reported)
CHECK_EVERY_S = 600
IST = 5.5 * 3600
_NAME = re.compile(r"^ai_\d{4}-\d{2}-\d{2}_\d{4}(_[a-z]+)?\.zip$")

_lock = threading.RLock()
_dir = None                   # DATA_DIR/ai
_bdir = None                  # DATA_DIR/ai_backups (next to the ai folder, so zipping the ai folder never includes it)
_st = {"last_ok": None, "last_name": None, "last_error": "", "skipped": [], "running": False}
_started = False


def init(path):
    global _dir, _bdir
    try:
        _dir = path
        _bdir = os.path.join(os.path.dirname(os.path.abspath(path)), "ai_backups")
        os.makedirs(_bdir, exist_ok=True)
    except Exception as e:
        _st["last_error"] = f"init: {e}"


def _ist_day(ts=None):
    return time.strftime("%Y-%m-%d", time.gmtime((ts or time.time()) + IST))


def list_backups():
    """[{'name', 'size_kb', 'ts'}] newest first."""
    try:
        if not _bdir or not os.path.isdir(_bdir):
            return []
        out = []
        for n in os.listdir(_bdir):
            if _NAME.match(n):
                p = os.path.join(_bdir, n)
                out.append({"name": n, "size_kb": round(os.path.getsize(p) / 1024.0), "ts": round(os.path.getmtime(p))})
        return sorted(out, key=lambda r: -r["ts"])
    except Exception:
        return []


def run(tag=""):
    """Make one backup now. -> {'ok': bool, 'name': str, 'files': int, 'error': str}"""
    if not _dir or not _bdir:
        return {"ok": False, "name": "", "files": 0, "error": "backup folder is not set"}
    with _lock:
        if _st["running"]:
            return {"ok": False, "name": "", "files": 0, "error": "a backup is already running"}
        _st["running"] = True
    tmp = None
    try:
        stamp = time.strftime("%Y-%m-%d_%H%M", time.gmtime(time.time() + IST))
        name = f"ai_{stamp}{('_' + tag) if tag else ''}.zip"
        final = os.path.join(_bdir, name)
        tmp = final + ".tmp"
        skipped, n = [], 0
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for fn in sorted(os.listdir(_dir)):
                p = os.path.join(_dir, fn)
                if not os.path.isfile(p) or fn.endswith(".tmp") or fn.startswith("_restore"):
                    continue
                if os.path.getsize(p) > MAX_FILE_MB * 1024 * 1024:
                    skipped.append(fn)
                    continue
                try:
                    z.write(p, fn)
                    n += 1
                except Exception:
                    skipped.append(fn)
        if n == 0:
            os.remove(tmp)
            return {"ok": False, "name": "", "files": 0, "error": "no AI files to save yet"}
        os.replace(tmp, final)
        tmp = None
        _prune()
        with _lock:
            _st.update({"last_ok": time.time(), "last_name": name, "last_error": "", "skipped": skipped})
        return {"ok": True, "name": name, "files": n, "error": ""}
    except Exception as e:
        with _lock:
            _st["last_error"] = str(e)[:160]
        return {"ok": False, "name": "", "files": 0, "error": str(e)[:160]}
    finally:
        with _lock:
            _st["running"] = False
        if tmp:
            try:
                os.remove(tmp)
            except Exception:
                pass


def _prune():
    try:
        auto = [b for b in list_backups() if not b["name"].endswith(("_manual.zip", "_prerestore.zip"))]
        for b in auto[KEEP:]:
            os.remove(os.path.join(_bdir, b["name"]))
    except Exception:
        pass


def restore(name):
    """Queue a restore of one backup; it is applied at the next backend start. -> {'ok', 'msg'}"""
    try:
        if not _NAME.match(str(name or "")):
            return {"ok": False, "msg": "unknown backup name"}
        src = os.path.join(_bdir, name)
        if not os.path.isfile(src):
            return {"ok": False, "msg": "that backup is not on disk any more"}
        with zipfile.ZipFile(src) as z:
            bad = z.testzip()
        if bad:
            return {"ok": False, "msg": f"backup is damaged ({bad}), not restored"}
        r = run("prerestore")                                   # a way back, in case the restore turns out to be wrong
        import shutil
        shutil.copyfile(src, os.path.join(_dir, "_restore_pending.zip"))
        return {"ok": True, "msg": "Restore is queued. Restart the backend to apply it." + ("" if r.get("ok") else " (safety copy of the current data could not be made)")}
    except Exception as e:
        return {"ok": False, "msg": str(e)[:160]}


def apply_pending(path):
    """Call at start-up BEFORE any AI module loads its file. Extracts a queued restore over the AI folder."""
    try:
        pend = os.path.join(path, "_restore_pending.zip")
        if not os.path.isfile(pend):
            return False
        base = os.path.abspath(path)
        with zipfile.ZipFile(pend) as z:
            for m in z.namelist():
                tgt = os.path.abspath(os.path.join(base, m))
                if os.path.dirname(tgt) != base:                # flat files only: a zip can never write outside the folder
                    continue
                tmp = tgt + ".tmp"
                with z.open(m) as src, open(tmp, "wb") as dst:
                    dst.write(src.read())
                os.replace(tmp, tgt)
        os.remove(pend)
        print("[AIBackup] restore applied at start-up")
        return True
    except Exception as e:
        print(f"[AIBackup] restore failed (data left as it was): {e}")
        return False


def status():
    with _lock:
        s = dict(_st)
    bl = list_backups()
    return {"backups": bl[:10], "last_ok": s["last_ok"] or (bl[0]["ts"] if bl else None), "last_name": s["last_name"] or (bl[0]["name"] if bl else None),
            "last_error": s["last_error"], "skipped": s["skipped"], "running": s["running"], "keep": KEEP,
            "pending_restore": bool(_dir and os.path.isfile(os.path.join(_dir, "_restore_pending.zip")))}


def _loop():
    time.sleep(120)                                             # let the backend finish starting
    while True:
        try:
            bl = [b for b in list_backups() if not b["name"].endswith(("_manual.zip", "_prerestore.zip"))]
            if not bl or _ist_day(bl[0]["ts"]) != _ist_day():
                run()
        except Exception as e:
            print(f"[AIBackup] loop: {e}")
        time.sleep(CHECK_EVERY_S)


def start():
    global _started
    if _started or not _dir:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="ai-backup").start()
