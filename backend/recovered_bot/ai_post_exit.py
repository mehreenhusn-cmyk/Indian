"""
ai_post_exit.py - what the price did AFTER a trade closed (record only).

Answers: "after my SL / TP4 exit, how far did price keep going, and did it come back?"
For every closed Bot 1 trade it keeps reading the live price for WATCH_MIN minutes and saves
one JSON line in ai_post_exit.jsonl:

  key, id, symbol, action, reason, tf, exit_price, entry_price, leverage, closed_ts,
  best_after  - best extra ROI % (leveraged) the trade would have had if held, measured from the exit price
  worst_after - worst dip in ROI % from the exit price
  at15 / at30 / at60 - ROI % vs the exit price after 15 / 30 / 60 minutes (None if not reached)
  back_to_entry - True if price returned to the entry price after the exit
  samples - how many price reads were made (low = feed was missing, treat as weak data)

Safety (same rules as ai_data_logger): own thread, every public function swallows its own errors,
never feeds any trading decision, at most MAX_WATCH trades watched at once (oldest dropped).
A restart while a trade is being watched loses that one watch (nothing else).
"""
import json
import os
import threading
import time

WATCH_MIN = 90
POLL_S = 20
MAX_WATCH = 80
KEEP_LINES = 3000

_lock = threading.Lock()
_dir = None
_file = None
_watch = {}          # key -> record
_thread = None


def init(path):
    global _dir, _file
    try:
        os.makedirs(path, exist_ok=True)
        _dir = path
        _file = os.path.join(path, "ai_post_exit.jsonl")
    except Exception as e:
        print(f"[AIPostExit] init failed (disabled): {e}")


def _price(symbol):
    try:
        from . import market_ws
        px = market_ws.get_best_live_price(symbol)[0]
        px = float(px)
        return px if px > 0 else None
    except Exception:
        return None


def start(pos, reason):
    """Call right after a trade closes. Never raises."""
    global _thread
    try:
        if not _file:
            return
        exit_px = float(pos.get("exit_price") or pos.get("ltp") or 0)
        entry = float(pos.get("entry_price") or 0)
        if exit_px <= 0 or entry <= 0:
            return
        key = f"{pos.get('id')}@{int(float(pos.get('opened_at_ts') or 0))}"
        rec = {
            "key": key, "id": pos.get("id"), "symbol": pos.get("symbol"),
            "action": pos.get("action"), "reason": reason, "tf": pos.get("timeframe"),
            "exit_price": exit_px, "entry_price": entry,
            "leverage": float(pos.get("leverage") or 1),
            "closed_ts": float(pos.get("closed_at_ts") or time.time()),
            "best_after": 0.0, "worst_after": 0.0,
            "at15": None, "at30": None, "at60": None,
            "back_to_entry": False, "samples": 0,
        }
        with _lock:
            _watch[key] = rec
            while len(_watch) > MAX_WATCH:
                _watch.pop(next(iter(_watch)), None)
            if _thread is None or not _thread.is_alive():
                _thread = threading.Thread(target=_loop, name="ai_post_exit", daemon=True)
                _thread.start()
    except Exception:
        pass


def _roi_move(rec, px):
    sign = 1.0 if str(rec["action"]).upper() == "BUY" else -1.0
    return (px - rec["exit_price"]) / rec["exit_price"] * 100.0 * rec["leverage"] * sign


def _loop():
    while True:
        try:
            time.sleep(POLL_S)
            now = time.time()
            with _lock:
                items = list(_watch.values())
            if not items:
                with _lock:
                    if not _watch:
                        return              # thread ends when nothing is watched; start() restarts it
                continue
            done = []
            for rec in items:
                age_min = (now - rec["closed_ts"]) / 60.0
                px = _price(rec["symbol"])
                if px is not None:
                    m = _roi_move(rec, px)
                    rec["samples"] += 1
                    rec["best_after"] = max(rec["best_after"], m)
                    rec["worst_after"] = min(rec["worst_after"], m)
                    for mark, name in ((15, "at15"), (30, "at30"), (60, "at60")):
                        if rec[name] is None and age_min >= mark:
                            rec[name] = round(m, 2)
                    buy = str(rec["action"]).upper() == "BUY"
                    if (buy and px <= rec["entry_price"]) or ((not buy) and px >= rec["entry_price"]):
                        # price is back at/through the entry level; for an SL exit that is trivially true,
                        # so only count it when the exit itself was on the profit side
                        if (buy and rec["exit_price"] > rec["entry_price"]) or ((not buy) and rec["exit_price"] < rec["entry_price"]):
                            rec["back_to_entry"] = True
                if age_min >= WATCH_MIN:
                    done.append(rec)
            for rec in done:
                _finish(rec)
        except Exception:
            time.sleep(5)


def _finish(rec):
    try:
        with _lock:
            _watch.pop(rec["key"], None)
        rec["best_after"] = round(rec["best_after"], 2)
        rec["worst_after"] = round(rec["worst_after"], 2)
        with _lock:
            with open(_file, "a") as f:
                f.write(json.dumps(rec) + "\n")
        _trim()
    except Exception as e:
        print(f"[AIPostExit] write failed: {e}")


def _trim():
    try:
        with open(_file, "r") as f:
            lines = f.readlines()
        if len(lines) > KEEP_LINES + 300:
            tmp = _file + ".tmp"
            with open(tmp, "w") as f:
                f.writelines(lines[-KEEP_LINES:])
            os.replace(tmp, _file)
    except Exception:
        pass


def read_all(limit=2000):
    """Finished watches, newest last. [] if none / disabled."""
    try:
        if not _file or not os.path.exists(_file):
            return []
        out = []
        with open(_file, "r") as f:
            for ln in f.readlines()[-limit:]:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
        return out
    except Exception:
        return []
