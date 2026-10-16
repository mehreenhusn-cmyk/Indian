"""
ai_rowcache.py - ONE shared, SLIM, incremental reader of the Shadow Lab rows file.

Why: ai_ab_board, ai_exit_study, ai_wait_study, ai_advice and ai_recipe all need the same lab rows.
Before, each of them parsed the whole ai_lab_rows.jsonl (up to ~33 MB) into full dicts on its own timer.
That spikes RAM (the phone was at 65% used) and holds the GIL so the trading threads stall.

Now: the file is read ONCE, line by line, and only a slim record is kept per row
  {'t','sym','a','f': {kind: label text}, 'o': {rule: (ROI %, how it ended)}}.
After that only NEW lines are read (the file is append-only; a rewrite/compaction is detected by its
inode / size and triggers one fresh read). Strings are interned so 20000 rows stay small.

READ-ONLY. Never touches a trade. Never raises.
"""
import json
import os
import sys
import threading
import time

from . import ai_ind_features as F
from . import ai_shadow_lab as L

_lock = threading.RLock()
_by_key = {}                 # row key -> slim row
_pos = {"ino": None, "off": 0}
_ver = {"n": 0}
_tf_cache = {}               # tf -> (version, sorted list)
_source = {"fn": None}       # tests only: callable returning FULL rows instead of the file
_last = {"ts": 0.0}
MIN_GAP_S = 2.0              # do not even stat the file more often than this
_I = sys.intern


def _pz(ind, action, sfx, zeps, peps):
    zp, zm, zs = ind.get("zp" + sfx), ind.get("zm" + sfx), ind.get("zs" + sfx)
    if zp is None or zm is None or zs is None:
        return None
    d = 1 if str(action).upper() == "BUY" else -1
    dz = zp + zm + zs
    p = "flat" if abs(zp) <= peps else ("WITH" if zp * d > 0 else "AGAINST")
    z = "flat" if abs(dz) <= zeps else ("WITH" if dz * d > 0 else "AGAINST")
    return f"Price {p} / Z {z}"


def _slim(r):
    """Full lab row -> slim row (or None if unusable)."""
    try:
        ind = r.get("ind")
        o = r.get("o")
        if not ind or not o:
            return None
        a = r["a"]
        f = F.labels(a, ind, r.get("ctx"), r.get("sig"))
        f["direction"] = "BUY" if a == "BUY" else "SELL"
        for sfx, ze, pe in (("3", 0.15, 0.05), ("10", 0.30, 0.10)):
            v = _pz(ind, a, sfx, ze, pe)
            if v:
                f["pz" + sfx] = v
        mk = r.get("mk")
        if mk and mk.get("side") in ("G", "L"):
            f["market"] = "coin is a Top-10 GAINER" if mk["side"] == "G" else "coin is a Top-10 LOSER"
        f = {_I(str(k)): _I(v) for k, v in f.items() if isinstance(v, str)}
        oo = {_I(k): (float(v[0]), _I(str(v[1]))) for k, v in o.items()}
        return {"k": r["k"], "t": int(r["t"]), "tf": _I(str(r.get("tf"))), "sym": _I(str(r.get("s", "?"))),
                "a": _I(str(a)), "f": f, "o": oo}
    except Exception:
        return None


def _put(sl):
    if sl is not None:
        _by_key[sl["k"]] = sl


def set_source(fn):
    """Tests only: feed FULL rows from a callable instead of the file."""
    with _lock:
        _source["fn"] = fn
        reset()


def reset():
    with _lock:
        _by_key.clear()
        _pos.update(ino=None, off=0)
        _tf_cache.clear()
        _ver["n"] += 1
        _last["ts"] = 0.0


def _refresh(force=False):
    with _lock:
        now = time.time()
        if not force and now - _last["ts"] < MIN_GAP_S:
            return
        _last["ts"] = now
        changed = False
        try:
            fn = _source["fn"]
            if fn is not None:
                if not _by_key:
                    for r in fn():
                        _put(_slim(r))
                    changed = True
            else:
                path = getattr(L, "_rows_file", None)
                if not path or not os.path.exists(path):
                    return
                st = os.stat(path)
                if _pos["ino"] != st.st_ino or st.st_size < _pos["off"]:
                    _by_key.clear()
                    _pos.update(ino=st.st_ino, off=0)
                    changed = True
                if st.st_size > _pos["off"]:
                    with open(path, "rb") as f:
                        f.seek(_pos["off"])
                        n = 0
                        while True:
                            line = f.readline()
                            if not line:
                                break
                            if not line.endswith(b"\n"):
                                break               # half-written last line: read it next time
                            _pos["off"] += len(line)
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                _put(_slim(json.loads(line)))
                            except Exception:
                                pass
                            n += 1
                            if n % 150 == 0:
                                time.sleep(0.001)   # let the trading threads run
                    changed = True
        except Exception:
            return
        if changed:
            _ver["n"] += 1
            _tf_cache.clear()


def version():
    _refresh()
    return _ver["n"]


def rows(tf):
    """Slim rows of one timeframe, oldest first (includes rows whose outcome is still OPEN)."""
    _refresh()
    with _lock:
        hit = _tf_cache.get(tf)
        if hit and hit[0] == _ver["n"]:
            return hit[1]
        out = sorted((r for r in _by_key.values() if r["tf"] == tf), key=lambda r: r["t"])
        _tf_cache[tf] = (_ver["n"], out)
        return out
