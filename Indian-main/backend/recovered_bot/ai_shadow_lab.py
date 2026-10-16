"""
ai_shadow_lab.py - the SHADOW LAB. It runs the bot's OWN strategy (strategy.ABCDStrategy,
unchanged: EMA50 cross, SL = signal candle extreme, TP1-4 from the SD bands) on 3m / 5m / 15m
for the coins the bot trades, WITHOUT opening any trade, and writes down for every signal:

  - what the SD bands, the Z-score and the TSI ("Special Master") looked like at that moment
    (ai_ind_features), plus what the 15m / 1h / 2h charts said (WITH or AGAINST the trade),
  - what would have happened afterwards, replayed from real candles under 5 exit rules:
      T1 / T2 / T3 / T4 = close at that TP, SL fixed at the signal candle extreme,
                          SL moves to entry once TP1 is touched (same as the live bot)
      T4n               = TP4 but WITHOUT the breakeven move
    exits mirror paper_trader._evaluate_candles: SL and a target in the same candle counts
    as SL (conservative), a trade also ends on the opposite EMA50 cross (the bot's REVERSED),
    or after MAX_FWD candles (TIMEOUT).

Then it mines those signals the same way ai_miner does (old 60% finds, new 40% re-checks,
shuffle test for luck) and answers: which scenarios of SD + Special Master + higher timeframe
made the signal win or lose, per timeframe, and what the result would have been if the
CONFIRMED bad scenarios had been skipped.

Safety (same rules as the other AI modules):
  - READ-ONLY: only public Binance candles; never touches orders, positions, settings or the
    bot's own candle caches. Nothing here is used by any trading decision.
  - own daemon thread, one request at a time with a gap, backs off on rate limits (429/418),
    and sleeps after every job in proportion to the CPU it just used so price updates do
    not lag.  Setting lab_enabled (default True) turns it off completely.
  - every public function swallows its own errors.
Honest limits: a replay is not live trading (no slippage, orders assumed always filled), and the
"which coins" list is the bot's CURRENT watchlist plus coins from its closed trades.
"""
import json
import math
import os
import sys
import threading
import time
from bisect import bisect_left

from . import ai_ind_features as F
from .strategy import ABCDStrategy

SIGNAL_TFS = ("3m", "5m", "15m")
CTX_TFS = ("5m", "15m", "1h", "2h")
TF_MS = {"3m": 180_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "2h": 7_200_000}
TF_MIN = {"3m": 3, "5m": 5, "15m": 15, "1h": 60, "2h": 120}
DAY_MS = 86_400_000
SIG_WINDOW = 259            # candles the live bot hands to generate_signal (app.INITIAL_HISTORY_LIMIT)
MAX_FWD = 300               # candles a simulated trade may run before TIMEOUT
LIVE_LIMIT = 700            # candles per live scan = 400 history + 300 forward
RULES = {"T1": (1, True), "T2": (2, True), "T3": (3, True), "T4": (4, True), "T4n": (4, False)}
LIVE_RULE = "T4"            # = what the live bot does by default
ROW_CAP = 20000
MIN_ROWS_MINE = 200
MINE_MAX_ROWS = 4000
_MINE_KINDS = ("z_zone", "z_move", "z_why", "z_why10", "z_recent", "tsi_pos", "tsi_vs_trade", "momentum", "warning",
               "sd_shape", "sd_size", "phase", "htf_5m", "htf_15m", "htf_1h", "htf_2h", "htft_15m", "htft_1h",
               "htft_2h", "htft_5m", "mtf_agree", "market", "sd_zone", "ema_turn", "regime", "volume",
               "direction")
REQ_GAP_S = 0.25
STATS_EVERY_S = 1800
_LABEL_DROP_FOR_TRADES = ("sd_zone", "ema_turn", "regime", "volume", "market")   # the miner already has these

_lock = threading.RLock()
_dir = None
_rows_file = None
_state_file = None
_started = False
_loaded = False
_final = set()                  # keys of rows already on disk
_n_rows_file = 0
_pending = {}                   # (sym, tf) -> {key: row}  (memory only, re-created by every scan)
_state = {"replayed": {}}       # sym -> ms of the last full replay
_next_due = {}                  # (sym, tf) -> ms when the next candle has closed
_ctx_cache = {}                 # sym -> {"S": {tf: slim series}, "next": {tf: ms}}
_bad_symbols = {}               # sym -> ms until which we skip it (400 / unknown symbol)
_pause_until = 0.0
_last_call = 0.0
_stats = {"data": None, "ts": 0.0, "n": -1, "busy": False}
_st = {"phase": "idle", "replay_total": 0, "replay_done": 0, "last_error": None,
       "last_scan": 0.0, "requests": 0, "paused": False}
_idx = {"key": None, "map": {}}
_todo_check = {"ts": 0.0}


# ------------------------------------------------------------------ settings
def _cfg(name, default):
    try:
        from . import settings_store
        v = settings_store.get(name, default)
        return default if v is None else v
    except Exception:
        return default


def enabled():
    return bool(_cfg("lab_enabled", True))


def _tfs():
    raw = str(_cfg("lab_tfs", ",".join(SIGNAL_TFS)))
    out = [x.strip() for x in raw.split(",") if x.strip() in SIGNAL_TFS]
    return tuple(out) or SIGNAL_TFS


# ------------------------------------------------------------------ files
def init(path):
    global _dir, _rows_file, _state_file
    try:
        os.makedirs(path, exist_ok=True)
        _dir = path
        _rows_file = os.path.join(path, "ai_lab_rows.jsonl")
        _state_file = os.path.join(path, "ai_lab_state.json")
    except Exception as e:
        _st["last_error"] = f"init: {e}"


def _ensure_loaded():
    global _loaded, _n_rows_file
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            if _state_file and os.path.exists(_state_file):
                with open(_state_file, "r") as f:
                    d = json.load(f)
                if isinstance(d, dict) and isinstance(d.get("replayed"), dict):
                    _state["replayed"] = {str(k): int(v) for k, v in d["replayed"].items()}
        except Exception:
            pass
        _mk_load()
        try:
            if _rows_file and os.path.exists(_rows_file):
                with open(_rows_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            k = json.loads(line).get("k")
                        except Exception:
                            continue
                        if k:
                            _final.add(k)
                _n_rows_file = len(_final)
        except Exception as e:
            _st["last_error"] = f"load: {e}"


def _save_state():
    try:
        if not _state_file:
            return
        tmp = _state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(_state, f)
        os.replace(tmp, _state_file)
    except Exception:
        pass


def _append_rows(rows):
    global _n_rows_file
    if not rows or not _rows_file:
        return
    with _lock:
        with open(_rows_file, "a") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
                _final.add(r["k"])
        _n_rows_file = len(_final)
    if _n_rows_file > ROW_CAP * 1.15:
        _compact()


def _compact():
    """Keep only the newest ROW_CAP rows (atomic rewrite)."""
    global _n_rows_file
    try:
        rows = _read_rows()
        rows.sort(key=lambda r: r.get("t", 0))
        rows = rows[-ROW_CAP:]
        tmp = _rows_file + ".tmp"
        with open(tmp, "w") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
        with _lock:
            os.replace(tmp, _rows_file)
            _final.clear()
            _final.update(r["k"] for r in rows)
            _n_rows_file = len(_final)
    except Exception as e:
        _st["last_error"] = f"compact: {e}"


_rr_cache = {"sig": None, "rows": []}


def _read_rows():
    if not _rows_file or not os.path.exists(_rows_file):
        return []
    try:
        st = os.stat(_rows_file)
        sig = (_rows_file, st.st_mtime_ns, st.st_size)
        if _rr_cache["sig"] == sig:          # file unchanged: no need to parse it all again (took 26-86 s on the phone)
            return list(_rr_cache["rows"])
    except Exception:
        sig = None
    rows = _read_rows_uncached()
    if sig is not None:
        _rr_cache.update(sig=sig, rows=rows)
    return list(rows)


def _read_rows_uncached():
    out = {}
    with open(_rows_file, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("k"):
                out[r["k"]] = r
    return list(out.values())


# ------------------------------------------------------------------ Binance candles (public, read-only)
def _now_ms():
    try:
        from . import binance_client
        return int(time.time() * 1000 + binance_client.server_time_offset_ms())
    except Exception:
        return int(time.time() * 1000)


def _throttle():
    global _last_call
    with _lock:
        wait = REQ_GAP_S - (time.time() - _last_call)
        _last_call = time.time() + max(wait, 0)
    if wait > 0:
        time.sleep(wait)


def _fetch_raw(symbol, tf, limit=None, start_ms=None):
    """-> raw kline rows (list) or None on error. Handles rate limits and unknown symbols."""
    global _pause_until
    if time.time() < _pause_until:
        return None
    if _bad_symbols.get(symbol, 0) > time.time():
        return None
    from . import binance_client
    params = {"symbol": symbol, "interval": tf, "limit": max(1, min(int(limit or 1500), 1500))}
    if start_ms is not None:
        params["startTime"] = int(start_ms)
    _throttle()
    try:
        data = binance_client._get("/fapi/v1/klines", params)
        _st["requests"] += 1
        return data if isinstance(data, list) else None
    except Exception as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        if code in (418, 429):
            _pause_until = time.time() + (600 if code == 418 else 90)
            _st["paused"] = True
            _st["last_error"] = f"Binance rate limit ({code}) - lab paused"
        elif code == 400:
            _bad_symbols[symbol] = time.time() + 6 * 3600
        else:
            _st["last_error"] = f"fetch {symbol} {tf}: {type(e).__name__}"
        return None


def _to_candles(raw, now_ms):
    out = []
    for r in raw:
        try:
            if int(r[6]) >= now_ms:
                continue                      # still forming - never use it
            out.append({"timestamp": int(r[0]), "open": float(r[1]), "high": float(r[2]),
                        "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])})
        except Exception:
            continue
    return out


def _fetch_limit(symbol, tf, limit):
    raw = _fetch_raw(symbol, tf, limit=limit + 1)
    return _to_candles(raw, _now_ms())[-limit:] if raw else None


def _fetch_range(symbol, tf, start_ms, max_pages=12):
    out, cur, step = {}, int(start_ms), TF_MS[tf]
    for _ in range(max_pages):
        raw = _fetch_raw(symbol, tf, limit=1500, start_ms=cur)
        if raw is None:
            return None
        if not raw:
            break
        for c in _to_candles(raw, _now_ms()):
            out[c["timestamp"]] = c
        cur = int(raw[-1][0]) + step
        if len(raw) < 1500:
            break
    return [out[k] for k in sorted(out)]


# ------------------------------------------------------------------ signals + outcomes
def _candidates(S):
    """Bars where the EMA50 cross happens or is within a hair of happening (the strategy
    itself decides - this only avoids calling it on every candle)."""
    c, e = S["c"], S["e50"]
    for i in range(1, S["n"]):
        if e[i] is None or e[i - 1] is None:
            continue
        a, b = c[i] - e[i], c[i - 1] - e[i - 1]
        if a * b <= 0 or min(abs(a), abs(b)) < 5e-4 * e[i]:
            yield i


def _simulate(S, i, is_long, entry, sl, tps):
    h, l, c = S["h"], S["l"], S["c"]
    n = S["n"]
    end = min(n - 1, i + MAX_FWD)
    opp = S["xdn"] if is_long else S["xup"]
    res = {}
    for name, (lvl, be_mode) in RULES.items():
        tgt = tps[lvl - 1]
        cur_sl, be = sl, False
        got = None
        for j in range(i + 1, end + 1):
            hh, ll = h[j], l[j]
            sl_hit = (ll <= cur_sl) if is_long else (hh >= cur_sl)
            tgt_hit = (hh >= tgt) if is_long else (ll <= tgt)
            if sl_hit:
                got = (cur_sl, "BE" if (be and cur_sl == entry) else "SL", j - i)
                break
            if tgt_hit:
                got = (tgt, "TP", j - i)
                break
            if opp[j]:
                got = (c[j], "REV", j - i)
                break
            if be_mode and not be:
                tp1 = tps[0]
                if ((hh >= tp1) if is_long else (ll <= tp1)) and ((entry > cur_sl) if is_long else (entry < cur_sl)):
                    cur_sl, be = entry, True          # applies from the NEXT candle
        if got is None:
            if end - i >= MAX_FWD:
                got = (c[end], "TIMEOUT", end - i)
            else:
                got = (c[end] if end > i else entry, "OPEN", max(end - i, 0))
        px, why, bars = got
        ret = (px - entry) / entry * 100.0 * (1.0 if is_long else -1.0)
        res[name] = [round(ret, 4), why, bars]
    return res


def _path(S, i, is_long, entry, sl, tp1, bars):
    """Best / worst excursion (% of entry, price move, not ROI) over the `bars` candles the live
    rule (T4) stayed open, + candles until TP1 was first touched / SL first touched (None = never)."""
    h, l = S["h"], S["l"]
    end = min(S["n"] - 1, i + max(1, int(bars)))
    mfe = mae = 0.0
    b_tp1 = b_sl = None
    for j in range(i + 1, end + 1):
        if is_long:
            fav, adv = (h[j] - entry) / entry * 100.0, (entry - l[j]) / entry * 100.0
            hit_tp, hit_sl = h[j] >= tp1, l[j] <= sl
        else:
            fav, adv = (entry - l[j]) / entry * 100.0, (h[j] - entry) / entry * 100.0
            hit_tp, hit_sl = l[j] <= tp1, h[j] >= sl
        mfe, mae = max(mfe, fav), max(mae, adv)
        if b_tp1 is None and hit_tp:
            b_tp1 = j - i
        if b_sl is None and hit_sl:
            b_sl = j - i
    return [round(mfe, 3), round(mae, 3), b_tp1, b_sl]


def _slim(S):
    keep = ("n", "t", "c", "e50", "tsi", "tsl", "z")
    return {k: S[k] for k in keep}


def _clean(d):
    if isinstance(d, dict):
        return {k: _clean(v) for k, v in d.items() if v is not None}
    return d


def _process(sym, tf, candles, ctxS, since_close_ms, mk_now=None, fresh_after_ms=None):
    """All signals the strategy would have fired on `candles` whose candle closed at/after
    since_close_ms -> list of rows (outcomes included, d=1 when every rule has finished)."""
    if len(candles) < F.MIN_BARS + 5:
        return []
    S = F.build(candles)
    strat = ABCDStrategy()
    rows = []
    step = TF_MS[tf]
    first = max(F.MIN_BARS - 1, SIG_WINDOW - 1)
    for i in _candidates(S):
        if i < first:
            continue
        t_close = S["t"][i] + step - 1
        if t_close < since_close_ms:
            continue
        sig = strat.generate_signal(candles[i - SIG_WINDOW + 1:i + 1], sym, TF_MIN[tf])
        if sig is None:
            continue
        ind = F.own_features(S, i)
        if not ind:
            continue
        ctx = {}
        for ctf, CS in (ctxS or {}).items():
            if TF_MS[ctf] <= step:
                continue                      # same / lower timeframe = no new information
            ctx[ctf] = F.ctx_features(CS, F.ctx_index(CS, t_close, TF_MS[ctf]))
        is_long = sig.action == "BUY"
        tps = [sig.tp1, sig.tp2, sig.tp3, sig.tp4]
        out = _simulate(S, i, is_long, float(sig.entry_price), float(sig.stop_loss), tps)
        mm = _path(S, i, is_long, float(sig.entry_price), float(sig.stop_loss), float(sig.tp1),
                   out["T4"][2])
        key = f"{sym}|{tf}|{t_close}|{sig.action[0]}"
        # market context AT SIGNAL TIME: only for a signal that just closed (a scan re-reads older
        # signals too, and today's rank says nothing about where the coin stood hours ago)
        if mk_now is not None and fresh_after_ms is not None and t_close >= fresh_after_ms:
            _mk_seen.setdefault(key, {"side": mk_now["side"], "rank": mk_now["rank"], "at": t_close})
        mk = _mk_seen.get(key)
        try:                                  # the AI studies this finished trade: "kab nikalna behtar, kab hold"
            from . import ai_exit_learn as _XL
            _XL.learn(key, S, i, is_long, float(sig.entry_price), float(sig.stop_loss), tps)
        except Exception:
            pass
        sigd = {"zone": sig.entry_zone, "turn": sig.ema_turn, "cross_n": sig.regime_cross_n,
                "vol": sig.volume_ratio, "slope": sig.ema_slope_pct, "atr": sig.atr_pct}
        rows.append(_clean({
            "k": key, "s": sym, "tf": tf, "a": sig.action,
            "t": t_close, "e": float(sig.entry_price), "sl": float(sig.stop_loss),
            "tp": [float(x) for x in tps], "ind": ind, "ctx": ctx, "sig": sigd, "o": out, "mm": mm,
            "mk": ({"side": mk["side"], "rank": mk["rank"]} if mk else None),
            "d": 1 if all(v[1] != "OPEN" for v in out.values()) else 0}))
        if len(rows) % 25 == 0:
            time.sleep(0.002)
    return rows


_mk_seen = {}                    # row key -> {"side","rank","at"}  market membership when the signal fired
_mk_dirty = {"n": 0, "ts": 0.0}


def _mk_load():
    try:
        f = os.path.join(_dir, "ai_lab_mk.json") if _dir else None
        if f and os.path.exists(f):
            with open(f, "r") as fh:
                d = json.load(fh)
            if isinstance(d, dict):
                _mk_seen.update({str(k): v for k, v in d.items() if isinstance(v, dict)})
    except Exception:
        pass


def _mk_save(force=False):
    """Persist the rank/side map (small; pruned to the last 4 days)."""
    try:
        if not _dir or (not force and time.time() - _mk_dirty["ts"] < 120):
            return
        cut = _now_ms() - 4 * DAY_MS
        for k in [k for k, v in _mk_seen.items() if v.get("at", 0) < cut]:
            _mk_seen.pop(k, None)
        tmp = os.path.join(_dir, "ai_lab_mk.json.tmp")
        with open(tmp, "w") as fh:
            json.dump(_mk_seen, fh, separators=(",", ":"))
        os.replace(tmp, os.path.join(_dir, "ai_lab_mk.json"))
        _mk_dirty["ts"] = time.time()
    except Exception:
        pass


def _market_now(sym):
    """{"side": "G"/"L"/"O", "rank": 1-10} from the bot's own Top-10 gainer / loser list right now
    (O = coin is no longer in either list). None when the list is unavailable."""
    try:
        from . import status as bot_status
        mv = bot_status.get().get("market_movers") or []
        if not mv:
            return None
        cnt = {"gainer": 0, "loser": 0}
        for m in mv:
            cat = m.get("category")
            if cat in cnt:
                cnt[cat] += 1
                if m.get("symbol") == sym:
                    return {"side": "G" if cat == "gainer" else "L", "rank": cnt[cat]}
        return {"side": "O", "rank": 0}
    except Exception:
        return None


def _commit(sym, tf, rows):
    fresh_final, pend = [], {}
    for r in rows:
        if r["k"] in _final:
            continue
        if r.get("d"):
            fresh_final.append(r)
        else:
            pend[r["k"]] = r
    _pending[(sym, tf)] = pend
    if fresh_final:
        _append_rows(fresh_final)


# ------------------------------------------------------------------ jobs
def _watchlist():
    try:
        from . import app as bot_app          # already imported by the server; just reads a set
        wl = sorted(bot_app.watchlist)
        if wl:
            return [str(s) for s in wl]
    except Exception:
        pass
    return []


_tc_cache = {"ts": 0.0, "n": -1, "v": []}


def _trade_coins(limit):
    # SMOOTH FIX 3: this copied 3000 trade dicts on EVERY call. The coin ranking only changes slowly, so it is
    # recomputed at most every 10 minutes (old answer in between). Same result, a fraction of the CPU.
    try:
        import time as _t
        if _tc_cache["v"] and _t.time() - _tc_cache["ts"] < 600:
            return _tc_cache["v"][:limit]
        from . import trade_store
        cnt = {}
        for t in trade_store.get_all_closed(3000, net=False):
            s = t.get("symbol")
            if s:
                cnt[s] = cnt.get(s, 0) + 1
        ranked = [s for s, _ in sorted(cnt.items(), key=lambda kv: -kv[1])][:max(limit, 60)]
        _tc_cache.update(ts=_t.time(), v=ranked)
        return ranked[:limit]
    except Exception:
        return _tc_cache["v"][:limit] if _tc_cache["v"] else []


_sym_cache = {"ts": 0.0, "v": []}


def _replay_symbols():
    if time.time() - _sym_cache["ts"] < 600 and _sym_cache["v"]:
        return _sym_cache["v"]
    cap = max(5, int(_cfg("lab_max_symbols", 40)))
    syms = list(_watchlist())
    for s in _trade_coins(cap):
        if s not in syms:
            syms.append(s)
    _sym_cache.update(ts=time.time(), v=syms[:cap])
    return _sym_cache["v"]


def _ctx_series(sym, start_ms=None):
    """{tf: slim series} for the higher timeframes. start_ms given = replay (long range),
    otherwise a live refresh (last 500 candles), reused until that candle closes."""
    now = _now_ms()
    ent = _ctx_cache.setdefault(sym, {"S": {}, "next": {}})
    for tf in CTX_TFS:
        if start_ms is None and now < ent["next"].get(tf, 0) and tf in ent["S"]:
            continue
        if start_ms is None:
            cs = _fetch_limit(sym, tf, 500)
        else:
            cs = _fetch_range(sym, tf, start_ms - (F.MIN_BARS + 60) * TF_MS[tf])
        if cs and len(cs) > 80:
            ent["S"][tf] = _slim(F.build(cs))
            ent["next"][tf] = cs[-1]["timestamp"] + 2 * TF_MS[tf] + 3000
    return dict(ent["S"])


def _replay_symbol(sym):
    now = _now_ms()
    days = max(1, min(60, int(_cfg("lab_replay_days", 14))))
    horizon = now - days * DAY_MS
    rep = _state["replayed"].get(sym)
    since = horizon if rep is None else max(horizon, rep - 80 * 3600 * 1000)
    ctx = _ctx_series(sym, start_ms=since)
    ok = True
    for tf in _tfs():
        cs = _fetch_range(sym, tf, since - (F.MIN_BARS + 5) * TF_MS[tf])
        if cs is None:
            ok = False
            continue
        _commit(sym, tf, _process(sym, tf, cs, ctx, since))
        _next_due[(sym, tf)] = (cs[-1]["timestamp"] + 2 * TF_MS[tf] + 3000) if cs else now + 60_000
    if ok:
        _state["replayed"][sym] = now
        _save_state()
    return ok


def _live_scan(sym, tf):
    cs = _fetch_limit(sym, tf, LIVE_LIMIT)
    if not cs or len(cs) < F.MIN_BARS + 5:
        _next_due[(sym, tf)] = _now_ms() + 90_000
        return
    ctx = _ctx_series(sym)
    last_close = cs[-1]["timestamp"] + TF_MS[tf] - 1
    _commit(sym, tf, _process(sym, tf, cs, ctx, last_close - MAX_FWD * TF_MS[tf],
                              mk_now=_market_now(sym), fresh_after_ms=last_close - 2 * TF_MS[tf]))
    _mk_save()
    _next_due[(sym, tf)] = cs[-1]["timestamp"] + 2 * TF_MS[tf] + 3000


def _step(todo):
    """One unit of work. Returns True if it did something."""
    global _pause_until
    now_s = time.time()
    if now_s < _pause_until:
        _st["phase"], _st["paused"] = "paused", True
        return False
    _st["paused"] = False
    wl = _watchlist()
    if not wl:
        _st["phase"] = "waiting for watchlist"
        return False
    if not todo and now_s - _todo_check["ts"] > 300:
        _todo_check["ts"] = now_s
        stale = 6 * 3600 * 1000
        now = _now_ms()
        for s in _replay_symbols():
            if now - _state["replayed"].get(s, 0) > stale and _bad_symbols.get(s, 0) < now_s:
                todo.append(s)
        _st["replay_total"], _st["replay_done"] = len(todo), 0
    if todo:
        _st["phase"] = "replay"
        sym = todo.pop(0)
        t0 = time.time()
        _replay_symbol(sym)
        _st["replay_done"] += 1
        _st["last_scan"] = time.time()
        time.sleep(min(3.0, (time.time() - t0) * 0.5))
        if not todo:
            _stats["ts"] = 0.0            # replay finished -> rebuild the numbers soon
        return True
    _st["phase"] = "live"
    now = _now_ms()
    for sym in wl:
        for tf in _tfs():
            if now >= _next_due.get((sym, tf), 0):
                t0 = time.time()
                _live_scan(sym, tf)
                _st["last_scan"] = time.time()
                time.sleep(min(2.0, (time.time() - t0) * 1.0))
                return True
    return False


def _loop():
    time.sleep(75)                       # let the bot start first
    todo = []
    while True:
        try:
            if not enabled():
                _st["phase"] = "off"
                time.sleep(20)
                continue
            _ensure_loaded()
            did = _step(todo)
            if not did and time.time() - _stats["ts"] > STATS_EVERY_S and _n_rows_file >= 30:
                _rebuild_stats()
            # the screen comes first: while the app is open the lab works at a slower pace (nothing is skipped)
            try:
                from . import ai_priority
                time.sleep(ai_priority.pace(0.3 if did else 4.0, 2.5 if did else 8.0))
            except Exception:
                time.sleep(0.3 if did else 4.0)
        except Exception as e:
            _st["last_error"] = f"loop: {type(e).__name__}: {e}"
            time.sleep(15)


def start():
    global _started
    if _started:
        return
    _started = True
    try:
        threading.Thread(target=_loop, name="ai-shadow-lab", daemon=True).start()
    except Exception as e:
        print(f"[ShadowLab] could not start: {e}")


def request_replay():
    """Forget when each coin was last replayed -> everything is replayed again (dedupe keeps it safe)."""
    with _lock:
        _state["replayed"] = {}
    _save_state()
    return True


# ------------------------------------------------------------------ numbers
def _net(ret_pct, lev, fee):
    return ret_pct * lev - fee


def _compact_rows():
    """Finished rows -> light records for mining (tokens as interned strings)."""
    out = []
    for r in _read_rows():
        try:
            ind = r.get("ind")
            if not ind:
                continue
            f = F.labels(r["a"], ind, r.get("ctx"), r.get("sig"))
            f["direction"] = "BUY" if r["a"] == "BUY" else "SELL"
            mk = r.get("mk")
            if mk and mk.get("side") in ("G", "L"):
                f["market"] = "coin is a Top-10 GAINER" if mk["side"] == "G" else "coin is a Top-10 LOSER"
            tok = tuple(sorted(sys.intern(f"{k}={v}") for k, v in f.items() if k in _MINE_KINDS))
            out.append({"t": r["t"], "tf": r["tf"], "s": r["s"], "a": r["a"], "tok": tok, "o": r["o"],
                        "mm": r.get("mm"), "mk": r.get("mk")})
        except Exception:
            continue
    out.sort(key=lambda x: x["t"])
    return out


def _agg(vals):
    n = len(vals)
    if not n:
        return {"n": 0, "win_rate": 0.0, "avg": 0.0, "pf": None, "sum": 0.0}
    pos = [v for v in vals if v > 0]
    neg = [v for v in vals if v <= 0]
    gp, gl = sum(pos), -sum(neg)
    return {"n": n, "win_rate": len(pos) / n * 100.0, "avg": sum(vals) / n,
            "pf": (gp / gl) if gl > 0 else None, "sum": sum(vals),
            "avg_win": (gp / len(pos)) if pos else 0.0, "avg_loss": (gl / len(neg)) if neg else 0.0}


def _breakeven_wr(a):
    aw, al = a.get("avg_win") or 0.0, a.get("avg_loss") or 0.0
    return (al / (aw + al) * 100.0) if (aw + al) > 0 else None


def _rebuild_stats():
    if _stats["busy"]:
        return
    _stats["busy"] = True
    try:
        data = _compute_stats()
        _stats.update(data=data, ts=time.time(), n=_n_rows_file)
    except Exception as e:
        _st["last_error"] = f"stats: {type(e).__name__}: {e}"
        _stats["ts"] = time.time() - STATS_EVERY_S + 300
    finally:
        _stats["busy"] = False


def _compute_stats():
    from . import ai_miner as M
    recs = _compact_rows()
    lev = float(_cfg("leverage", 1) or 1)
    fee = max(0.0, float(_cfg("fee_roi_pct", 1.0) or 0.0))
    out = {"n": len(recs), "leverage": lev, "fee_roi_pct": fee, "tfs": {}, "built": time.time(),
           "live_rule": LIVE_RULE,
           "caveats": ["Replay on real candles, not live trading: no slippage, orders always filled.",
                       "Coins = the bot's current watchlist + coins from its closed trades.",
                       "Signals in the same market move are not independent - trust a scenario only "
                       "when it is CONFIRMED on the newer 40% of the data."]}
    for tf in SIGNAL_TFS:
        rs = [r for r in recs if r["tf"] == tf]
        if not rs:
            continue
        ent = {"n": len(rs), "rules": {}}
        for rule in RULES:
            vals = [_net(r["o"][rule][0], lev, fee) for r in rs if rule in r["o"]]
            a = _agg(vals)
            a["breakeven_wr"] = _breakeven_wr(a)
            a["gross_avg"] = sum(r["o"][rule][0] * lev for r in rs if rule in r["o"]) / max(1, len(vals))
            ent["rules"][rule] = a
        ent["why"] = {}
        for r in rs:
            w = r["o"][LIVE_RULE][1]
            ent["why"][w] = ent["why"].get(w, 0) + 1
        if len(rs) >= MIN_ROWS_MINE:
            try:
                ent.update(_mine_tf(M, rs, lev, fee))
            except Exception as e:
                ent["mine_error"] = f"{type(e).__name__}: {e}"
        else:
            ent["ready"] = False
        out["tfs"][tf] = ent
    return out


def _mine_tf(M, rs, lev, fee):
    rs = rs[-MINE_MAX_ROWS:]
    vals = [_net(r["o"][LIVE_RULE][0], lev, fee) for r in rs]
    toks = [(list(r["tok"]), []) for r in rs]
    n = len(rs)
    cut = int(n * M.SPLIT)
    t_eff = M._null_threshold(toks, vals, cut, 2, 4)
    res = M._mine(toks, vals, cut, max_order=2, t_min=t_eff)
    # 3-way scenarios, only from the facts that already showed some signal on their own / in pairs
    freq = {}
    for key, r in res.items():
        for x in key:
            freq[x] = freq.get(x, 0) + abs(r["t"])
    top = set(sorted(freq, key=lambda x: -freq[x])[:12])
    if top:
        toks3 = [([x for x in c if x in top], []) for c, _s in toks]
        res3 = M._mine(toks3, vals, cut, max_order=3, t_min=t_eff + 0.3)
        for key, r in res3.items():
            if len(key) == 3:
                res[key] = r
    res = M._prune(res)
    sets = [frozenset(r["tok"]) for r in rs]
    items = []
    for key, r in res.items():
        hit = [i for i, s in enumerate(sets) if all(k in s for k in key)]
        a = _agg([vals[i] for i in hit])
        items.append({"label": M._label(key), "order": len(key), "kind": "TAKE" if r["sign"] > 0 else "AVOID",
                      "verdict": r["verdict"], "n": a["n"], "win_rate": a["win_rate"], "avg": a["avg"],
                      "pf": a["pf"], "edge": r["edge"], "n_old": r["n_tr"], "avg_old": r["avg_tr"],
                      "n_new": r["n_te"], "avg_new": r["avg_te"], "_key": key})
    rank = lambda x: -(abs(x["edge"]) * math.sqrt(max(x["n"], 1)))
    conf = sorted([i for i in items if i["verdict"] == "CONFIRMED"], key=rank)
    avoid = [i for i in conf if i["kind"] == "AVOID"]
    take = [i for i in conf if i["kind"] == "TAKE"]
    base = {"all": _agg(vals), "old": _agg(vals[:cut]), "new": _agg(vals[cut:])}
    sim = {"baseline": base}
    if avoid:
        bad = [set(i["_key"]) for i in avoid[:8]]
        keep_i = [i for i, s in enumerate(sets) if not any(all(k in s for k in b) for b in bad)]
        sim["skip_avoid"] = {"skipped": n - len(keep_i),
                             "all": _agg([vals[i] for i in keep_i]),
                             "old": _agg([vals[i] for i in keep_i if i < cut]),
                             "new": _agg([vals[i] for i in keep_i if i >= cut])}
    if take:
        good = [set(i["_key"]) for i in take[:8]]
        pick = [i for i, s in enumerate(sets) if any(all(k in s for k in g) for g in good)]
        sim["only_take"] = {"taken": len(pick), "all": _agg([vals[i] for i in pick]),
                            "old": _agg([vals[i] for i in pick if i < cut]),
                            "new": _agg([vals[i] for i in pick if i >= cut])}
    for lst in (conf, items):
        for i in lst:
            i.pop("_key", None)
    failed = [i for i in items if i["verdict"] == "FAILED"]
    # the other lifecycle stages (ai_learning): found on the old 60% but the new 40% is still too small
    # (VALIDATING), or found on the old part and NOT holding on the new part (REJECTED)
    pend = sorted([i for i in items if i["verdict"] == "UNTESTED"], key=rank)[:8]
    rej = sorted(failed, key=rank)[:8]
    return {"ready": True, "validating": pend, "rejected": rej, "n_mined": n, "n_old": cut, "n_new": n - cut, "t_needed": t_eff,
            "tested": len(items), "confirmed_n": len(conf), "failed_n": len(failed),
            "take": take[:6], "avoid": avoid[:6], "sim": sim}


# ------------------------------------------------------------------ public API
def build_lab(force=False):
    """Cached numbers, rebuilt by the lab thread (every 30 min / after a replay). force=True only
    asks for a rebuild in the background - this never blocks a request. Never raises."""
    try:
        _ensure_loaded()
        if force and not _stats["busy"]:
            threading.Thread(target=_rebuild_stats, name="ai-lab-stats", daemon=True).start()
        d = dict(_stats["data"] or {"n": 0, "tfs": {}})
        d["status"] = status()
        return d
    except Exception:
        return {"n": 0, "tfs": {}, "status": status()}


def status():
    try:
        _ensure_loaded()
        pend = sum(len(v) for v in _pending.values())
        return {"enabled": enabled(), "phase": _st["phase"], "rows": _n_rows_file, "pending": pend,
                "replay_done": _st["replay_done"], "replay_total": _st["replay_total"],
                "requests": _st["requests"], "paused": time.time() < _pause_until,
                "last_error": _st["last_error"], "last_scan": _st["last_scan"],
                "stats_age_s": (time.time() - _stats["ts"]) if _stats["ts"] else None,
                "tfs": list(_tfs()), "days": int(_cfg("lab_replay_days", 14))}
    except Exception:
        return {"enabled": False}


def attach_trades(rows):
    """Copy of `rows` (closed trades) where each trade that matches a lab signal (same coin, same
    timeframe, same side, candle closed within ~2 min before it opened) gets `lab_labels`: the
    SD / Z-score / TSI / higher-timeframe facts of that moment. ai_miner then treats them like
    its own labels. Trades without a match are returned untouched."""
    try:
        if not enabled() or _n_rows_file < 1:
            return rows
        idx = _trade_index()
        if not idx:
            return rows
        out = []
        for t in rows:
            try:
                tf = str(t.get("timeframe") or "")
                ts = float(t.get("opened_at_ts") or 0) * 1000.0
                ent = idx.get((t.get("symbol"), tf, str(t.get("action") or "").upper()))
                if ent and ts > 0:
                    keys, lst = ent
                    j = bisect_left(keys, ts - 120_000)
                    best = None
                    while j < len(lst) and lst[j][0] <= ts + 5_000:
                        best = lst[j]
                        j += 1
                    if best:
                        lab = {}
                        for tok in best[1]:
                            k, v = tok.split("=", 1)
                            if k not in _LABEL_DROP_FOR_TRADES and k != "direction":
                                lab[k] = v
                        t = dict(t)
                        t["lab_labels"] = lab
            except Exception:
                pass
            out.append(t)
        return out
    except Exception:
        return rows


def _trade_index():
    key = int(time.time() // 900)       # rebuilt at most every 15 min (was: after every new finished row)
    if _idx["key"] == key:
        return _idx["map"]
    m = {}
    try:
        for r in _compact_rows():
            m.setdefault((r["s"], r["tf"], r["a"]), []).append((r["t"], r["tok"]))
    except Exception:
        return _idx["map"]
    for k2, v in list(m.items()):
        v.sort(key=lambda x: x[0])
        m[k2] = ([x[0] for x in v], v)
    _idx.update(key=key, map=m)
    return m


def build_text():
    """Short plain-text summary for the AI prompt. '' while there is nothing to say."""
    try:
        d = build_lab()
        if not d.get("tfs"):
            return ""
        L = ["SHADOW LAB (the bot's own EMA50-cross strategy replayed on 3m/5m/15m for many coins, no trades "
             "placed; ROI is net after the app fee, leverage %gx):" % d.get("leverage", 1)]
        for tf, e in d["tfs"].items():
            r = e["rules"].get(LIVE_RULE)
            if not r:
                continue
            head = (f"- {tf}: {e['n']} signals; live rule (TP4 + breakeven after TP1): win {r['win_rate']:.1f}%, "
                    f"avg {r['avg']:+.2f}% ROI")
            if r.get("pf"):
                head += f", PF {r['pf']:.2f}"
            if r.get("breakeven_wr"):
                head += f", break-even win rate about {r['breakeven_wr']:.0f}%"
            L.append(head)
            best = max(e["rules"].items(), key=lambda kv: kv[1]["avg"])
            L.append(f"  best exit rule on {tf}: {best[0]} (avg {best[1]['avg']:+.2f}% ROI, win {best[1]['win_rate']:.1f}%)")
            for tag in ("avoid", "take"):
                for it in (e.get(tag) or [])[:3]:
                    line = (f"  {tag.upper()} [{it['verdict']}]: {it['label']} -> {it['n']} signals, "
                            f"win {it['win_rate']:.0f}%, avg {it['avg']:+.2f}% ROI")
                    if it.get("avg_new") is not None:
                        line += f" (newer data: {it['avg_new']:+.2f}% over {it['n_new']})"
                    L.append(line)
            sk = (e.get("sim") or {}).get("skip_avoid")
            if sk:
                b, nw = e["sim"]["baseline"]["new"], sk["new"]
                L.append(f"  if the CONFIRMED AVOID scenarios were skipped, newer-data avg ROI would go "
                         f"{b['avg']:+.2f}% -> {nw['avg']:+.2f}% ({sk['skipped']} of {e['n_mined']} signals skipped)")
        L.append("Only scenarios marked CONFIRMED held up on newer data; treat the rest as ideas, not facts.")
        return "\n".join(L)
    except Exception:
        return ""
