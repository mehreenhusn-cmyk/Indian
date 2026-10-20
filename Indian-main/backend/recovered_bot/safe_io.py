"""Crash-safe JSON file helpers (settings.json, trades.json, chat history).

Why: the old code did open(path, "w") + json.dump(). If Android/Termux kills
the process (or the battery dies) in the middle of that write, the file is
left half-written; the loader then silently treated it as empty and the next
save overwrote it - settings / today's P&L record gone with no warning.

write_json_atomic(): writes to <path>.tmp, fsyncs, keeps the previous good
copy as <path>.bak, then os.replace()s the tmp file into place (atomic).
read_json_safe(): tries <path>, then <path>.bak. A corrupt file is renamed to
<path>.corrupt-<time> (never overwritten) and a warning is printed.
"""
import json
import os
import time


def write_json_atomic(path, data_or_text):
    text = data_or_text if isinstance(data_or_text, str) else json.dumps(data_or_text)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    if os.path.exists(path):
        try:
            os.replace(path, path + ".bak")
        except OSError:
            pass
    os.replace(tmp, path)


def read_json_safe(path, label="data"):
    """Returns (data, source). data is None if nothing usable exists.
    source is 'main', 'backup' or None."""
    for candidate, source in ((path, "main"), (path + ".bak", "backup")):
        if not os.path.exists(candidate):
            continue
        try:
            with open(candidate, "r") as f:
                data = json.load(f)
            if source == "backup":
                print(f"[safe_io] WARNING: {label} main file unreadable - restored from backup {candidate}")
            return data, source
        except Exception as e:
            print(f"[safe_io] WARNING: {label} file {candidate} is corrupt ({e})")
            try:
                os.replace(candidate, f"{candidate}.corrupt-{int(time.time())}")
            except OSError:
                pass
    return None, None
