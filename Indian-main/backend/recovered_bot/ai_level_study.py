"""
ai_level_study.py - "SD level / Z-score / Z-SMA kaise behave karte hain?"  (event study, no rules taught)

Idea
----
The SD lines on the main chart and the Z-score pane are the SAME maths (price distance from the
200-candle mean in SD units). Traders see "price bounces from the SD line" and "Z crosses its black
average line". Nobody should hand-write that as a rule. This module only COUNTS what really happened,
on real candles of the coins the bot watches, and lets the numbers decide.

Events (closed candles only, own timeframe, default 3m)
  touch  -3 / -2 / -1 / +1 / +2 / +3 SD : the candle reaches the SD line for the first time
         (previous close was on the inside of the line)
  cross  Z crosses its Z-SMA (black line) up / down
Outcome (looked at on the next HORIZON candles, by CLOSE, in SD units of the event candle)
  touch: BOUNCE = a close comes back 0.5 SD towards the mean first,  BREAK = a close goes 0.5 SD beyond the line first
  cross: FOLLOW = a close moves 0.5 SD in the cross direction first,  FAIL = 0.5 SD the other way first
  nothing within HORIZON candles = NEUTRAL (counted, never hidden)
Situation at the event (so "SD bounce" is not one lump):
  SD shape  : expanding / steady / shrinking (width now vs 20 candles ago)
  TSI       : TSI above its signal / below its signal
  Z-SMA     : Z-SMA rising / falling / flat

Honest rules
  - A coin flip gives ~50% bounce / 50% break, so 50% is the yardstick. A situation is called
    BOUNCES (or BREAKS) only if it is >= 60% (<= 40%) in the OLDER 60% AND in the NEWER 40% of events,
    with >= MIN_N events. Otherwise NO EDGE. Less than MIN_ALL events = COLLECTING.
  - Events of one coin on neighbouring candles overlap, so numbers are a guide, not a promise.
  - Fixed numbers (0.5 SD, 10 candles, 1.15x width) are NOT tuned on the data.
Safety: own daemon thread, read-only (public candles only), one coin per cycle with a gap, sleeps in
proportion to the CPU used, setting level_study_enabled (default True) turns it off, every error is
swallowed, nothing here is used by any trading decision. Stores one tiny row per event.
"""
import json
import os
import threading
import time

from . import ai_ind_features as F

HORIZON = 10
MOVE = 0.5              # SD units for bounce/break/follow/fail
WIN_SHAPE = 20
SHAPE_EPS = 0.15
SLOPE_EPS = 0.002       # Z-SMA change over 5 candles that counts as flat
SPLIT = 0.6
MIN_ALL = 60            # events before any verdict
MIN_N = 30              # events in one situation before it can be called
MIN_NEW = 12
HI, LO = 0.60, 0.40
MAX_ROWS = 60000
CANDLES = 800
CYCLE_GAP_S = 25

LEVELS = ["-3SD", "-2SD", "-1SD", "+1SD", "+2SD", "+3SD", "ZSMA up", "ZSMA down"]
_K = {0: -3.0, 1: -2.0, 2: -1.0, 3: 1.0, 4: 2.0, 5: 3.0}
SHAPES = ["SD expanding", "SD steady", "SD shrinking"]
TSIS = ["TSI with bounce/move", "TSI against"]
ZS = ["Z-SMA with", "Z-SMA against", "Z-SMA flat"]

_lock = threading.Lock()
_dir = None
_file = None
_state_file = None
_state = {}             # sym -> last event time (ms)
_rows = None            # [[t_ms, level, outcome, shape, tsi, zsma], ...]  outcome: 1 good / 0 bad / 2 neutral
_started = False
_status = {"phase": "starting", "coins": 0, "last_error": "", "ts": 0.0}
_cache = {"n": -1, "v": None}


def _cfg(name, default):
    try:
        from . import settings_store
        v = settings_store.get(name, default)
        return default if v is None else v
    except Exception:
        return default


def init(path):
    global _dir, _file, _state_file, _rows, _state
    try:
        os.makedirs(path, exist_ok=True)
        _dir = path
        _file = os.path.join(path, "ai_level_rows.jsonl")
        _state_file = os.path.join(path, "ai_level_state.json")
        rows = []
        if os.path.exists(_file):
            with open(_file, "r") as f:
                for ln in f:
                    try:
                        r = json.loads(ln)
                        if isinstance(r, list) and len(r) == 6:
                            rows.append(r)
                    except Exception:
                        continue
        if os.path.exists(_state_file):
            with open(_state_file, "r") as f:
                d = json.load(f)
            if isinstance(d, dict):
                _state = d
        with _lock:
            _rows = rows[-MAX_ROWS:]
    except Exception as e:
        _status["last_error"] = f"init: {type(e).__name__}: {e}"
        _rows = _rows or []


# ------------------------------------------------------------------ the maths
def _situation(S, i, bounce_dir):
    """(shape, tsi, zsma) codes at candle i. bounce_dir = +1 if the 'good' move is up, -1 if down."""
    w, tsi, tsl, zs = S["width"], S["tsi"], S["tsl"], S["zsma"]
    shape = 1
    if w[i] is not None and w[i - WIN_SHAPE] not in (None, 0):
        r = w[i] / w[i - WIN_SHAPE]
        shape = 0 if r > 1 + SHAPE_EPS else (2 if r < 1 - SHAPE_EPS else 1)
    t = 1
    if tsi[i] is not None and tsl[i] is not None:
        t = 0 if (tsi[i] - tsl[i]) * bounce_dir > 0 else 1
    z = 2
    if zs[i] is not None and zs[i - 5] is not None:
        d = zs[i] - zs[i - 5]
        z = 2 if abs(d) < SLOPE_EPS else (0 if d * bounce_dir > 0 else 1)
    return shape, t, z


def _outcome(c, i, base, std, direction):
    """Walk the next candles by CLOSE. direction=+1: good = up. -> 1 good, 0 bad, 2 neutral."""
    for j in range(i + 1, min(len(c), i + 1 + HORIZON)):
        mv = (c[j] - base) / std * direction
        if mv >= MOVE:
            return 1
        if mv <= -MOVE:
            return 0
    return 2


def scan(candles, after_ms=0):
    """Events of one coin -> list of rows. Only events newer than after_ms and with a full HORIZON of candles after them."""
    S = F.build(candles)
    n, c, h, l = S["n"], S["c"], S["h"], S["l"]
    t, sma, std, z, zs = S["t"], S["sma"], S["std"], S["z"], S["zsma"]
    out = []
    last = n - 1 - HORIZON
    for i in range(F.MIN_BARS, last + 1):
        if t[i] <= after_ms or None in (sma[i], std[i]) or not std[i]:
            continue
        for li, k in _K.items():
            lvl = sma[i] + k * std[i]
            lvl_prev = sma[i - 1] + k * std[i - 1] if sma[i - 1] is not None and std[i - 1] else lvl
            if k < 0:
                hit = l[i] <= lvl and c[i - 1] > lvl_prev          # first touch from inside
                direction = +1                                      # good = back up
                base = lvl
            else:
                hit = h[i] >= lvl and c[i - 1] < lvl_prev
                direction = -1
                base = lvl
            if not hit:
                continue
            o = _outcome(c, i, base, std[i], direction)
            sh, ts, zz = _situation(S, i, direction)
            out.append([t[i], li, o, sh, ts, zz])
        if z[i] is not None and z[i - 1] is not None and zs[i] is not None and zs[i - 1] is not None:
            up = z[i - 1] <= zs[i - 1] and z[i] > zs[i]
            dn = z[i - 1] >= zs[i - 1] and z[i] < zs[i]
            if up or dn:
                d = 1 if up else -1
                o = _outcome(c, i, c[i], std[i], d)
                sh, ts, zz = _situation(S, i, d)
                out.append([t[i], 6 if up else 7, o, sh, ts, zz])
    return out


# ------------------------------------------------------------------ numbers for the screen
def _rate(rows):
    g = sum(1 for r in rows if r[2] == 1)
    b = sum(1 for r in rows if r[2] == 0)
    dec = g + b
    return (g / dec * 100.0 if dec else 0.0), g, b, len(rows) - dec


def _verdict(rows):
    n = len(rows)
    if n < MIN_N:
        return "COLLECTING", None
    rows = sorted(rows, key=lambda r: r[0])
    cut = int(n * SPLIT)
    old, new = rows[:cut], rows[cut:]
    ro, rn, ra = _rate(old)[0], _rate(new)[0], _rate(rows)[0]
    if len(new) >= MIN_NEW:
        if ro >= HI * 100 and rn >= HI * 100:
            return "GOOD", (ro, rn)
        if ro <= LO * 100 and rn <= LO * 100:
            return "BAD", (ro, rn)
    return "NO_EDGE", (ro, rn)


def _item(label, rows, extra=None):
    rate, g, b, neu = _rate(rows)
    v, split = _verdict(rows)
    it = {"label": label, "n": len(rows), "good": g, "bad": b, "neutral": neu, "rate": round(rate, 1),
          "verdict": v, "need": MIN_N}
    if split:
        it["old"], it["new"] = round(split[0], 1), round(split[1], 1)
    if extra:
        it.update(extra)
    return it


def build_from(rows):
    n = len(rows)
    out = {"ts": time.time(), "n": n, "status": "OK" if n >= MIN_ALL else "COLLECTING", "need": MIN_ALL,
           "levels": [], "situations": [], "headline": "", "coins": _status.get("coins", 0),
           "caveats": ["Sirf ginti hai: koi rule sikhaya nahi gaya. 50% = sikka uchhalne jaisa (bounce/break barabar).",
                       "Ek coin ki paas-paas ki candle ke events overlap karte hain, isliye numbers andaza hain, wada nahi.",
                       "Bounce = 10 candle me price line se 0.5 SD wapas aaya. Break = 0.5 SD aur aage nikal gaya."]}
    if n == 0:
        out["headline"] = "SD level / Z-SMA ka data jama ho raha hai. Abhi 0 event."
        return out
    for li, name in enumerate(LEVELS):
        rs = [r for r in rows if r[1] == li]
        out["levels"].append(_item(name, rs))
    if n < MIN_ALL:
        out["headline"] = f"Data jama ho raha hai: {n}/{MIN_ALL} event. Itne hone par hi kuch dikhega."
        return out
    sit = []
    for li, name in enumerate(LEVELS):
        rs = [r for r in rows if r[1] == li]
        for idx, (col, names) in enumerate(((3, SHAPES), (4, TSIS), (5, ZS))):
            for vi, vn in enumerate(names):
                sub = [r for r in rs if r[col] == vi]
                if len(sub) >= MIN_N:
                    sit.append(_item(f"{name} + {vn}", sub))
    order = {"GOOD": 0, "BAD": 1, "NO_EDGE": 2, "COLLECTING": 3}
    sit.sort(key=lambda x: (order[x["verdict"]], -abs(x["rate"] - 50)))
    out["situations"] = sit[:12]
    good = [s for s in sit if s["verdict"] == "GOOD"]
    bad = [s for s in sit if s["verdict"] == "BAD"]
    if good or bad:
        out["headline"] = (f"{n} event me {len(good)} situation me level bounce/follow pakka dikha, "
                           f"{len(bad)} me toot/fail hota dikha (purane aur naye dono hisse me).")
    else:
        out["headline"] = f"{n} event me koi situation purane aur naye dono me 60% se upar/40% se neeche pakka nahi nikli. Abhi koi edge nahi."
    return out


def build():
    """Screen data. Cached until new events arrive. Never raises."""
    try:
        with _lock:
            rows = list(_rows or [])
        if _cache["n"] == len(rows) and _cache["v"] is not None:
            _cache["v"]["coins"] = _status.get("coins", 0)
            return _cache["v"]
        v = build_from(rows)
        _cache.update(n=len(rows), v=v)
        return v
    except Exception as e:
        return {"ts": time.time(), "n": 0, "status": "ERROR", "levels": [], "situations": [], "headline": "",
                "error": f"{type(e).__name__}: {e}"}


# ------------------------------------------------------------------ background collector
def _save(new_rows):
    global _rows
    try:
        with _lock:
            _rows = ((_rows or []) + new_rows)[-MAX_ROWS:]
        if _file and new_rows:
            with open(_file, "a") as f:
                for r in new_rows:
                    f.write(json.dumps(r, separators=(",", ":")) + "\n")
            if len(_rows) >= MAX_ROWS:                      # trim the file to the newest rows
                tmp = _file + ".tmp"
                with open(tmp, "w") as f:
                    for r in _rows:
                        f.write(json.dumps(r, separators=(",", ":")) + "\n")
                os.replace(tmp, _file)
        if _state_file:
            tmp = _state_file + ".tmp"
            with open(tmp, "w") as f:
                json.dump(_state, f)
            os.replace(tmp, _state_file)
    except Exception as e:
        _status["last_error"] = f"save: {type(e).__name__}: {e}"


def _symbols():
    try:
        from . import ai_shadow_lab
        return list(ai_shadow_lab._replay_symbols())
    except Exception:
        return []


_cursor = [0]


def _step():
    from . import exchange
    syms = _symbols()
    _status["coins"] = len(syms)
    if not syms:
        _status["phase"] = "no coins yet"
        return False
    sym = syms[_cursor[0] % len(syms)]
    _cursor[0] += 1
    tf = int(_cfg("level_tf", 3))
    t0 = time.process_time()
    candles = exchange.get_klines(sym, tf=tf, limit=CANDLES, fast=True)
    if not candles or len(candles) < F.MIN_BARS + HORIZON + 5:
        return True
    key = f"{sym}|{tf}"
    after = int(_state.get(key, 0))
    rows = scan(candles, after)
    if rows:
        _state[key] = max(r[0] for r in rows)
    else:
        _state[key] = max(after, int(candles[-HORIZON - 2]["timestamp"]))
    _save(rows)
    _status.update(phase="collecting", ts=time.time())
    used = time.process_time() - t0
    time.sleep(min(3.0, used * 8))                              # yield: price feed / app must never stall
    return True


def _loop():
    time.sleep(120)                                             # let the bot start first
    fails = 0
    while True:
        try:
            if not bool(_cfg("level_study_enabled", True)):
                _status["phase"] = "off"
                time.sleep(30)
                continue
            if _rows is None:
                time.sleep(10)
                continue
            _step()
            fails = 0
            time.sleep(CYCLE_GAP_S)
        except Exception as e:
            fails += 1
            _status["last_error"] = f"loop: {type(e).__name__}: {e}"
            time.sleep(min(600, 30 * fails))


def start():
    global _started
    if _started:
        return
    _started = True
    try:
        threading.Thread(target=_loop, name="ai-level-study", daemon=True).start()
    except Exception as e:
        print(f"[LevelStudy] could not start: {e}")
