"""
ai_path_logger.py - saves the REAL price path of every paper trade.

Why: until now a closed trade only kept its best ROI, worst ROI and the time
it touched each TP. Nobody could tell whether the peak came before the dip,
so trail / stop / hold ideas were guesses. With the whole path saved, those
ideas can be replayed on real trades (see ai_miner._path_study).

What is saved (one JSON line per closed trade in ai_trade_paths.jsonl):
  key, id, symbol, action, entry, leverage, opened_ts, closed_ts, reason,
  roi_final, levels (SL + TP1..4 as ROI %, fixed at the first sample),
  gaps (seconds with no price - restarts / feed outage),
  s = [[t_sec, roi, lo, hi], ...]
      t_sec = seconds since entry, roi = ROI % at that moment,
      lo/hi = lowest / highest ROI seen since the previous sample, so a spike
      between two samples is never lost.

Safety (same rules as ai_data_logger):
  - pure appends / small atomic rewrites, every public function swallows its
    own errors and never raises into the trading code
  - NOT used by any trading decision - it only records
  - open-trade paths are flushed to ai_open_paths.json every ~30 s so a
    restart in the middle of a trade does not lose the path so far
  - memory is capped: max _MAX_SAMPLES per trade (older samples are merged in
    pairs, keeping lo/hi), file is trimmed to the newest _KEEP_LINES trades
"""
import json
import os
import threading
import time

_lock = threading.Lock()
_dir = None
_open_file = None
_paths_file = None
_open = {}                 # key -> record being built
_last_flush = 0.0
_cache = {"mtime": None, "data": {}}

SAMPLE_S = 15              # one sample per trade every 15 s
GAP_S = 90                 # a longer silence counts as a gap
_MAX_SAMPLES = 1800        # ~7.5 h at 15 s; beyond that samples are merged
_FLUSH_S = 30
_KEEP_LINES = 1500         # newest trades kept in the paths file
_TRIM_AT = 1800


def make_key(trade_id, opened_ts):
    """Trade ids restart every day, so the key also carries the open time."""
    try:
        return f"{trade_id}@{int(float(opened_ts or 0))}"
    except Exception:
        return f"{trade_id}@0"


def init(path):
    """path: directory (same one ai_data_logger uses). Safe to call once."""
    global _dir, _open_file, _paths_file, _open
    try:
        os.makedirs(path, exist_ok=True)
        _dir = path
        _open_file = os.path.join(path, "ai_open_paths.json")
        _paths_file = os.path.join(path, "ai_trade_paths.jsonl")
        if os.path.exists(_open_file):
            with open(_open_file, "r") as f:
                d = json.load(f)
            if isinstance(d, dict):
                with _lock:
                    _open = d
    except Exception as e:
        print(f"[PathLogger] init failed (paths will not be recorded): {e}")


def _roi_of_price(price, entry, buy, lev):
    if not entry:
        return None
    raw = (price - entry) / entry * 100.0
    return (raw if buy else -raw) * lev


def _levels(pos, sl, tps):
    """SL and TP1-4 as ROI % (leverage-adjusted, direction-signed)."""
    entry = float(pos.get("entry_price") or 0.0)
    lev = float(pos.get("leverage") or 1.0)
    buy = pos.get("action") == "BUY"
    out = {}
    # SL: use the ORIGINAL signal SL when present (trailed_sl is a later move)
    sl0 = pos.get("signal_stop_loss")
    if sl0 in (None, ""):
        sl0 = sl
    if sl0 not in (None, ""):
        out["sl"] = _roi_of_price(float(sl0), entry, buy, lev)
    for n in (1, 2, 3, 4):
        v = (tps or {}).get(n)
        if v not in (None, ""):
            out[f"tp{n}"] = _roi_of_price(float(v), entry, buy, lev)
    return {k: round(v, 3) for k, v in out.items() if v is not None}


def _compact(samples):
    """Merge neighbouring samples in pairs (keeps lo/hi) to cap memory."""
    out = []
    for i in range(0, len(samples) - 1, 2):
        a, b = samples[i], samples[i + 1]
        out.append([b[0], b[1], min(a[2], b[2]), max(a[3], b[3])])
    if len(samples) % 2:
        out.append(samples[-1])
    return out


def tick(pos, roi, sl=None, tps=None):
    """Call from the monitor loop for every open position on every price tick.
    Cheap: it only stores a sample when SAMPLE_S has passed, otherwise it just
    widens the running lo/hi."""
    try:
        opened = pos.get("opened_at_ts")
        if not opened:
            return
        now = time.time()
        key = make_key(pos.get("id"), opened)
        roi = float(roi)
        with _lock:
            rec = _open.get(key)
            if rec is None:
                rec = {"key": key, "id": pos.get("id"), "symbol": pos.get("symbol"),
                       "action": pos.get("action"), "entry": pos.get("entry_price"),
                       "lev": pos.get("leverage"), "opened_ts": float(opened),
                       "levels": _levels(pos, sl, tps), "gaps": 0.0,
                       "s": [], "_lo": roi, "_hi": roi, "_t": float(opened)}
                _open[key] = rec
            rec["_lo"] = min(rec["_lo"], roi)
            rec["_hi"] = max(rec["_hi"], roi)
            gap = now - rec["_t"]
            if gap < SAMPLE_S and rec["s"]:
                return
            if rec["s"] and gap > GAP_S:
                rec["gaps"] = round(rec["gaps"] + gap, 1)
            rec["s"].append([round(now - rec["opened_ts"], 1), round(roi, 3),
                             round(rec["_lo"], 3), round(rec["_hi"], 3)])
            rec["_lo"] = rec["_hi"] = roi
            rec["_t"] = now
            if len(rec["s"]) > _MAX_SAMPLES:
                rec["s"] = _compact(rec["s"])
        _flush_open()
    except Exception:
        pass


def add_sd(key, sample, sd0=None):
    """Attach one SD-band sample [t_sec, width_pct, mean, k_now] to an OPEN trade.
    Called by ai_sd_tracker (background thread). Never raises."""
    try:
        with _lock:
            rec = _open.get(key)
            if rec is None:
                return False
            if sd0 is not None and rec.get("sd0") is None:
                rec["sd0"] = sd0
            lst = rec.setdefault("sd", [])
            lst.append(sample)
            if len(lst) > 400:
                del lst[:len(lst) - 400]
        return True
    except Exception:
        return False


def add_slope(key, sample, slope0=None):
    """Attach one EMA-slope sample [t_sec, slope3_pct, ema, close_vs_ema_pct] to an OPEN trade.
    Called by ai_slope_tracker (background thread). Never raises."""
    try:
        with _lock:
            rec = _open.get(key)
            if rec is None:
                return False
            if slope0 is not None and rec.get("slope0") is None:
                rec["slope0"] = slope0
            lst = rec.setdefault("slope", [])
            lst.append(sample)
            if len(lst) > 400:
                del lst[:len(lst) - 400]
        return True
    except Exception:
        return False


def add_ind(key, sample):
    """Attach one indicator sample [t_sec, z, tsi, tsi_signal] to an OPEN trade.
    Called by ai_ind_tracker (background thread). Never raises."""
    try:
        with _lock:
            rec = _open.get(key)
            if rec is None:
                return False
            lst = rec.setdefault("ind", [])
            lst.append(sample)
            if len(lst) > 400:
                del lst[:len(lst) - 400]
        return True
    except Exception:
        return False


def open_snapshot():
    """Small read-only copy of every OPEN trade's path so far (for the diary page). Never raises."""
    out = []
    try:
        with _lock:
            for k, r in _open.items():
                ss = r.get("s") or []
                out.append({"key": k, "id": r.get("id"), "symbol": r.get("symbol"), "action": r.get("action"),
                            "lev": r.get("lev"), "opened_ts": r.get("opened_ts"), "levels": dict(r.get("levels") or {}),
                            "now": ss[-1][1] if ss else None,
                            "peak": max([x[3] for x in ss] + [r.get("_hi", 0.0)]) if ss else r.get("_hi"),
                            "low": min([x[2] for x in ss] + [r.get("_lo", 0.0)]) if ss else r.get("_lo"),
                            "n_ind": len(r.get("ind") or []), "n_sd": len(r.get("sd") or [])})
    except Exception:
        pass
    return out


_KEYCACHE = {}            # key -> finished path record (newest few hundred)
_MISS = {}                # key -> time it was not found (not asked again for 60 s)
_IDX = {"sig": None, "pos": 0, "map": {}}      # key -> (offset, length) of its line in the paths file
_IDX_LOCK = threading.Lock()


def _index_rebuild_from(start_pos):
    """Walk the file from start_pos, remember (offset, length) of each complete line by its key. Caller holds _IDX_LOCK."""
    with open(_paths_file, "rb") as f:
        f.seek(start_pos)
        base = start_pos
        tail = b""
        while True:
            chunk = f.read(4 << 20)
            if not chunk:
                break
            data = tail + chunk
            data_base = base - len(tail)
            start = 0
            while True:
                nl = data.find(b"\n", start)
                if nl < 0:
                    break
                head = data[start:start + 160]
                i = head.find(b'"key":"')
                if i >= 0:
                    j = head.find(b'"', i + 7)
                    if j > i:
                        _IDX["map"][head[i + 7:j].decode("utf-8", "ignore")] = (data_base + start, nl - start)
                start = nl + 1
            tail = data[start:]
            base = base + len(chunk)
        _IDX["pos"] = base - len(tail)          # only complete lines count; a half-written last line is read next time


def read_keys(keys, max_lines=0):
    """Finished path records for just these keys. Uses a small offset index: the file is scanned once (new bytes only),
    then each wanted trade is ONE seek + ONE json parse, so even a very big paths file answers in milliseconds.
    Keys that are not there are remembered for 60 s. {} on any problem. Never raises."""
    out = {}
    try:
        now = time.time()
        todo = []
        for k in keys:
            if not k:
                continue
            r = _KEYCACHE.get(k)
            if r is not None:
                out[k] = r
            elif now - _MISS.get(k, 0.0) > 60.0:
                todo.append(k)
        if not todo or not _paths_file or not os.path.exists(_paths_file):
            return out
        _index_sync()
        with open(_paths_file, "rb") as f:
            for k in todo:
                ent = _IDX["map"].get(k)
                if ent is None:
                    _MISS[k] = now
                    continue
                f.seek(ent[0])
                try:
                    rec = json.loads(f.read(ent[1]).decode("utf-8", "ignore"))
                except Exception:
                    _MISS[k] = now
                    continue
                out[k] = rec
                _KEYCACHE[k] = rec
        if len(_KEYCACHE) > 300:
            for k in list(_KEYCACHE)[:100]:
                _KEYCACHE.pop(k, None)
        if len(_MISS) > 2000:
            _MISS.clear()
    except Exception:
        pass
    return out


def _index_sync():
    try:
        st = os.stat(_paths_file)
        with _IDX_LOCK:
            if _IDX["sig"] is not None and (st.st_ino != _IDX["sig"] or st.st_size < _IDX["pos"]):
                _IDX.update(sig=None, pos=0, map={})
                _KEYCACHE.clear()
                _MISS.clear()
            if _IDX["sig"] is None:
                _IDX["sig"] = st.st_ino
            if st.st_size > _IDX["pos"]:
                _index_rebuild_from(_IDX["pos"])
    except Exception:
        pass


def open_path(key):
    """Read-only copy of ONE open trade's samples + levels (for the Bot vs AI chart). None if unknown. Never raises."""
    try:
        with _lock:
            r = _open.get(key)
            if not r:
                return None
            return {"s": [list(x) for x in (r.get("s") or [])], "levels": dict(r.get("levels") or {}),
                    "opened_ts": r.get("opened_ts"), "ind": bool(r.get("ind"))}
    except Exception:
        return None


def open_path_full(key):
    """Read-only copy of one OPEN trade record including indicator / SD samples (for the replay). None if unknown."""
    try:
        with _lock:
            r = _open.get(key)
            if not r:
                return None
            return {"s": [list(x) for x in (r.get("s") or [])], "levels": dict(r.get("levels") or {}),
                    "ind": [list(x) for x in (r.get("ind") or [])], "sd": [list(x) for x in (r.get("sd") or [])]}
    except Exception:
        return None


def open_keys():
    """{key: last SD sample time} for open trades - lets the tracker skip bars it already logged."""
    try:
        with _lock:
            return {k: (r["sd"][-1][0] if r.get("sd") else None) for k, r in _open.items()}
    except Exception:
        return {}


def _flush_open(force=False):
    global _last_flush
    try:
        if not _open_file:
            return
        now = time.time()
        if not force and now - _last_flush < _FLUSH_S:
            return
        _last_flush = now
        with _lock:
            snap = json.dumps(_open)
        tmp = _open_file + ".tmp"
        with open(tmp, "w") as f:
            f.write(snap)
        os.replace(tmp, _open_file)
    except Exception:
        pass


def finish(pos, reason=None):
    """Call when a trade closes (pos already has closed_at_ts / roi_pct).
    Writes the finished path as one line and forgets the open copy."""
    try:
        opened = pos.get("opened_at_ts")
        key = make_key(pos.get("id"), opened)
        with _lock:
            rec = _open.pop(key, None)
        if rec is None:
            return
        # path ROI is GROSS (price move only); the fee is stored beside it so the
        # analysis can show net numbers without double-counting.
        fee = float(pos.get("fee_roi_pct") or 0.0)
        roi_final = float(pos.get("gross_roi_pct", pos.get("roi_pct")) or 0.0)
        closed_ts = float(pos.get("closed_at_ts") or time.time())
        # closing tick: make sure the last sample is the real exit
        rec["s"].append([round(closed_ts - rec["opened_ts"], 1), round(roi_final, 3),
                         round(min(rec["_lo"], roi_final), 3), round(max(rec["_hi"], roi_final), 3)])
        out = {k: v for k, v in rec.items() if not k.startswith("_")}
        out.update({"closed_ts": closed_ts, "reason": reason, "roi_final": round(roi_final, 3),
                    "fee": round(fee, 3)})
        if _paths_file:
            with open(_paths_file, "a") as f:
                f.write(json.dumps(out, separators=(",", ":")) + "\n")
            _maybe_trim()
        _flush_open(force=True)
    except Exception:
        pass


_line_count = None        # lines in the paths file (counted once, then +1 per finished trade)


def _maybe_trim():
    """Keep only the newest _KEEP_LINES trades. The old version read the WHOLE file (tens of MB) on every single trade
    close, on the thread that closes the trade. Now the lines are counted once and the file is only read when it really
    has to be cut."""
    global _line_count
    try:
        if _line_count is None:
            n = 0
            with open(_paths_file, "rb") as f:
                while True:
                    chunk = f.read(4 << 20)
                    if not chunk:
                        break
                    n += chunk.count(b"\n")
            _line_count = n                      # includes the line that was just written
        else:
            _line_count += 1
        if _line_count <= _TRIM_AT:
            return
        with open(_paths_file, "r") as f:
            lines = f.readlines()
        if len(lines) <= _TRIM_AT:
            _line_count = len(lines)
            return
        tmp = _paths_file + ".tmp"
        with open(tmp, "w") as f:
            f.writelines(lines[-_KEEP_LINES:])
        os.replace(tmp, _paths_file)
        _line_count = min(len(lines), _KEEP_LINES)
    except Exception:
        pass


def load_paths():
    """{key: path record} for every finished trade. Cached until the file
    changes. Never raises."""
    try:
        if not _paths_file or not os.path.exists(_paths_file):
            return {}
        m = os.path.getmtime(_paths_file)
        with _lock:
            if _cache["mtime"] == m:
                return _cache["data"]
        data = {}
        with open(_paths_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    data[r["key"]] = r
                except Exception:
                    pass
        with _lock:
            _cache["mtime"] = m
            _cache["data"] = data
        return data
    except Exception:
        return {}


def stats():
    """Small status dict for the UI: how many paths are saved so far."""
    try:
        p = load_paths()
        with _lock:
            n_open = len(_open)
        return {"saved": len(p), "open": n_open}
    except Exception:
        return {"saved": 0, "open": 0}
