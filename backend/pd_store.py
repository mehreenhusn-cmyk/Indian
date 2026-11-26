"""pd_store.py - tiny file helpers of the Pump / Dump scanner. Append-only JSON lines per day, atomic JSON files. Never raises on a read."""
import json
import os
import threading
import time

import pd_config as C

_lock = threading.RLock()


def _dir(kind):
    d = C.path(kind)
    os.makedirs(d, exist_ok=True)
    return d


def append(kind, day, rec):
    """Add one line to <kind>/<day>.jsonl."""
    line = json.dumps(rec, separators=(",", ":"))
    with _lock:
        with open(os.path.join(_dir(kind), day + ".jsonl"), "a", encoding="utf-8") as f:
            f.write(line + "\n")


def read_day(kind, day):
    p = os.path.join(C.path(kind), day + ".jsonl")
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass          # a half-written last line is skipped
    except Exception:
        pass
    return out


def list_days(kind):
    try:
        names = [n[:-6] for n in os.listdir(C.path(kind)) if n.endswith(".jsonl") and len(n) == 16]
    except Exception:
        return []
    return sorted(names, reverse=True)


def read_json(name, default=None):
    try:
        with open(C.path(name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


def write_json(name, obj):
    p = C.path(name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, separators=(",", ":"))
        os.replace(tmp, p)


def prune(keep_days):
    """Delete day files older than keep_days (only inside the pumpdump folder)."""
    cut = time.strftime("%Y-%m-%d", time.gmtime(time.time() + C.get("tz_min") * 60 - keep_days * 86400))
    n = 0
    for kind in ("events", "outcomes", "missed", "reports"):
        d = C.path(kind)
        try:
            for name in os.listdir(d):
                if name[:10] < cut and (name.endswith(".jsonl") or name.endswith(".json")):
                    os.remove(os.path.join(d, name))
                    n += 1
        except Exception:
            pass
    return n
