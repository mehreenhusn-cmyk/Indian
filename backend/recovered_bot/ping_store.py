"""Atomic JSON / JSONL helpers for the Ping data engine.

Files live under OWL_DATA_DIR/ai/ (same folder other AI modules use).
Missing or corrupt files start empty; never raise to the caller.
"""
import json
import os
import time

# ---- constants (starting guesses) ----
EVENTS_CAP = 5000
STATE_NAME = "ping_state.json"
EVENTS_NAME = "ping_events.jsonl"
TRADES_NAME = "ping_trades.json"
LEAD_NAME = "ping_lead.json"


def _ai_dir():
    base = os.path.expanduser(os.environ.get("OWL_DATA_DIR") or "~/owl_data")
    path = os.path.join(base, "ai")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def state_path():
    return os.path.join(_ai_dir(), STATE_NAME)


def events_path():
    return os.path.join(_ai_dir(), EVENTS_NAME)


def write_json_atomic(path, data):
    text = json.dumps(data, separators=(",", ":"), default=str)
    tmp = path + ".tmp"
    try:
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
    except Exception as e:
        print(f"[ping_store] write_json_atomic failed: {e}")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def read_json_safe(path, default=None):
    if default is None:
        default = {}
    for candidate in (path, path + ".bak"):
        if not os.path.exists(candidate):
            continue
        try:
            with open(candidate, "r") as f:
                data = json.load(f)
            return data if data is not None else default
        except Exception as e:
            print(f"[ping_store] read failed {candidate}: {e}")
            try:
                os.replace(candidate, f"{candidate}.corrupt-{int(time.time())}")
            except OSError:
                pass
    return default


def append_event(event):
    path = events_path()
    try:
        with open(path, "a") as f:
            f.write(json.dumps(event, separators=(",", ":"), default=str) + "\n")
    except Exception as e:
        print(f"[ping_store] append_event failed: {e}")
        return
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        if len(lines) > EVENTS_CAP:
            keep = lines[-EVENTS_CAP:]
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                f.writelines(keep)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, path)
    except Exception as e:
        print(f"[ping_store] trim events failed: {e}")


def write_state(state):
    """Live snapshot, rewritten every ~2 s. Fast path: no fsync, no .bak copy.

    (The phone's shared storage is slow; the full atomic write with fsync + .bak
    every 2 s was needless wear. A lost snapshot just means 'stale' for 2 s.)
    """
    path = state_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write(json.dumps(state, separators=(",", ":"), default=str))
        os.replace(tmp, path)
    except Exception as e:
        print(f"[ping_store] write_state failed: {e}")


def read_state():
    path = state_path()
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def trades_path():
    return os.path.join(_ai_dir(), TRADES_NAME)


def lead_path():
    return os.path.join(_ai_dir(), LEAD_NAME)


def write_trades(data):
    write_json_atomic(trades_path(), data)


def read_trades():
    return read_json_safe(trades_path(), default={})


def write_lead(data):
    write_json_atomic(lead_path(), data)


def read_lead():
    return read_json_safe(lead_path(), default={})
