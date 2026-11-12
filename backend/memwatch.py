"""memwatch.py - Part 19: MEMORY WATCH of the backend (start.py grows to ~1.1 GB in a day). Measures only, never touches a trade.
Why: the code has no single obvious leak. Two suspects: (1) a container in some module that keeps growing, (2) Python / glibc holding freed memory (fragmentation after big file reads, many threads), which looks like a leak in RSS.
This thread writes one JSON line to memwatch.jsonl (data folder) and tells which suspect is true:
  every 10 min (light, a few ms): rss_mb, thread count, size of every module-level dict / list / set / deque that is 100+ long (one level deeper for dict-of-list), sorted, top 25
  every 60 min (heavy, about 1-2 s): top 12 object types by count (gc) - run only when the heap is above 300 MB
  TRIM TEST (mode 'on', every 30 min): glibc malloc_trim(0) is called and rss_before / rss_after are written. A big drop (100+ MB) = fragmentation (suspect 2): the fix is MALLOC_ARENA_MAX=2 + periodic trim. No drop = a real growing container (suspect 1): the report shows which one.
Setting memwatch_mode: 'on' (default: measure + trim test), 'measure' (measure only, no trim), 'off'. Any error = nothing written, fail-open. File is cut at 2 MB (old part kept as .old).
Read it:  python3 memwatch.py --data /home/owl/owl_data   (prints RSS trend, trim effect, containers that grew)"""
import argparse
import collections
import gc
import json
import os
import sys
import threading
import time

VERSION = "memwatch 1 (Part 19)"
FILE, FILE_MAX = "memwatch.jsonl", 2 * 1024 * 1024
LIGHT_S, HEAVY_S, TRIM_S, FIRST_S = 600, 3600, 1800, 90
MIN_LEN, TOP_N, SCAN_CAP = 100, 25, 200000
_st = {"started": False, "last_heavy": 0.0, "last_trim": 0.0, "n": 0, "error": ""}


def _mode():
    try:
        from recovered_bot import settings_store
        m = str(settings_store.get("memwatch_mode", "on") or "on").lower()
        return m if m in ("on", "measure", "off") else "on"
    except Exception:
        return "on"


def rss_mb():
    try:
        with open("/proc/self/statm") as f:
            return round(int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1048576.0, 1)
    except Exception:
        try:
            import resource
            return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
        except Exception:
            return None


def trim():
    """glibc malloc_trim(0). -> True when called (Linux glibc only), False otherwise."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
        return True
    except Exception:
        return False


def containers(top=TOP_N):
    """Sizes of module-level containers of our own modules: [(module.name, kind, len, deep_len)] sorted by deep_len."""
    here = os.path.dirname(os.path.abspath(__file__))
    out = []
    for mname, mod in list(sys.modules.items()):
        try:
            f = getattr(mod, "__file__", None)
            if not f or not os.path.abspath(f).startswith(here):
                continue
            for k, v in list(vars(mod).items()):
                kind = type(v).__name__
                if not isinstance(v, (dict, list, set, collections.deque)) or k.startswith("__"):
                    continue
                n = len(v)
                if n < MIN_LEN and kind != "dict":
                    continue
                deep, seen = n, 0
                if isinstance(v, dict):
                    for x in list(v.values()):
                        seen += 1
                        if seen > SCAN_CAP:
                            break
                        if isinstance(x, (list, dict, set, tuple)):
                            deep += len(x)
                if deep >= MIN_LEN:
                    out.append((mname + "." + k, kind, n, deep))
        except Exception:
            continue
    out.sort(key=lambda a: a[3], reverse=True)
    return out[:top]


def heavy_types(top=12):
    c = collections.Counter(type(o).__name__ for o in gc.get_objects())
    return c.most_common(top)


def _write(line):
    p = os.path.join(_root, FILE)
    if os.path.isfile(p) and os.path.getsize(p) > FILE_MAX:
        os.replace(p, p + ".old")
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(line, separators=(",", ":"), default=str) + "\n")


_root = "."


def sample(force_heavy=False):
    mode = _mode()
    if mode == "off":
        return None
    now = time.time()
    rec = {"t": int(now), "rss": rss_mb(), "threads": threading.active_count(), "mode": mode}
    rec["containers"] = [list(c) for c in containers()]
    if (force_heavy or now - _st["last_heavy"] >= HEAVY_S) and (rec["rss"] or 0) > 300:
        _st["last_heavy"] = now
        rec["types"] = [list(c) for c in heavy_types()]
        rec["gc_objects"] = len(gc.get_objects())
    if mode == "on" and now - _st["last_trim"] >= TRIM_S:
        _st["last_trim"] = now
        before = rss_mb()
        ok = trim()
        time.sleep(0.5)
        rec["trim"] = {"called": ok, "rss_before": before, "rss_after": rss_mb()}
    _write(rec)
    _st["n"] += 1
    return rec


def _run():
    time.sleep(FIRST_S)
    while True:
        try:
            sample()
        except Exception as e:
            _st["error"] = str(e)[:160]
        time.sleep(LIGHT_S)


def start(data_dir):
    global _root
    if _st["started"] or not data_dir:
        return
    _st["started"] = True
    try:
        os.makedirs(data_dir, exist_ok=True)
        _root = data_dir
        threading.Thread(target=_run, name="memwatch", daemon=True).start()
    except Exception as e:
        _st["error"] = str(e)[:160]


# ---------------------------------------------------------------- reader (by hand, no import of the bot)
def read_lines(root):
    out = []
    for name in (FILE + ".old", FILE):
        try:
            with open(os.path.join(root, name), "r", encoding="utf-8", errors="replace") as f:
                for ln in f:
                    try:
                        x = json.loads(ln)
                    except ValueError:
                        continue
                    if isinstance(x, dict) and x.get("t"):
                        out.append(x)
        except OSError:
            pass
    return out


def report(root):
    ls = read_lines(root)
    if len(ls) < 2:
        return "memwatch: %d samples so far. Wait at least 1 hour after the deploy and run again." % len(ls)
    a, b = ls[0], ls[-1]
    hrs = max((b["t"] - a["t"]) / 3600.0, 0.01)
    t = ["MEMWATCH: %d samples over %.1f h | RSS %.0f MB -> %.0f MB (%+.0f MB per hour) | threads %s -> %s" % (len(ls), hrs, a.get("rss") or 0, b.get("rss") or 0, ((b.get("rss") or 0) - (a.get("rss") or 0)) / hrs, a.get("threads"), b.get("threads"))]
    tr = [x["trim"] for x in ls if x.get("trim") and x["trim"].get("called") and x["trim"].get("rss_before") and x["trim"].get("rss_after")]
    if tr:
        drops = [round(z["rss_before"] - z["rss_after"], 1) for z in tr]
        t.append("TRIM TEST: %d tries, RSS drop per try (MB): %s -> %s" % (len(tr), drops[-6:], ("FRAGMENTATION likely (drops of 100+ MB)" if max(drops) >= 100 else ("small drop: mostly a real growing container" if max(drops) < 30 else "mixed")))) 
    else:
        t.append("TRIM TEST: no result yet (mode measure / off, or no glibc).")
    fa = {c[0]: c for c in a.get("containers", [])}
    grew = []
    for c in b.get("containers", []):
        before = fa.get(c[0], [None, None, 0, 0])[3]
        grew.append((c[3] - before, c[0], c[1], before, c[3]))
    grew.sort(reverse=True)
    t.append("CONTAINERS that grew most (size now - size at first sample):")
    for g in grew[:8]:
        t.append("  %+d  %s (%s)  %d -> %d" % g)
    types = [x["types"] for x in ls if x.get("types")]
    if types:
        t.append("OBJECT TYPES (latest, count): " + ", ".join("%s %d" % (k, v) for k, v in types[-1][:8]))
    t.append("Read: big RSS growth + no container growth + trim drop = fragmentation. Container growth = that name is the leak. Paper money only; nothing here touches trading.")
    return "\n".join(t)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=".")
    print(report(ap.parse_args().data))
