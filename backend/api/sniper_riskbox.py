"""api/sniper_riskbox.py - OwlSniper RISK BOX route (Part 11 / FILE 22): ONE read-only route GET /api/v2/sniper_riskbox?symbol=BTCUSDT&tf=5m&side=LONG&size=10&lev=1
It gives the Risk Box of owl_sniper_riskbox.py for ONE coin: what happened in similar past trades (win %, expected R and USDT, median + 75th-percentile time, worst case), or NOT_ENOUGH_DATA with no number when fewer than 30 similar trades exist.
Read only: the saved candles and the saved trades are only read, nothing is written, no order, no network.
Light on the phone: the POOL of past examples (the slow part: trades + candle replay + labels) is built once and cached for POOL_SEC (10 minutes), only ONE build runs at a time (a second call gets the old pool, or state "busy" when there is none).
The signal part (newest closed candle of the coin) is quick and cached 20 s per request. symbol must be letters / digits (max 24), tf 5m or 15m, side LONG or SHORT (empty = the Sniper's own raw signal on the newest candle), size 0.5 to 1000 USDT, lev 1 to 20 (defaults 10 USDT, 1x = the Sniper paper size).
Same switch as the other V2 routes: 404 until the file v2_api_enabled exists in the data folder, and off for good while the file v2_sniper_off exists.
Answer (Part 50 adds extras {edge, scalp, stay, session, lines}: 4 plain lines under the box, also when the box itself is NOT_ENOUGH_DATA): state (OK / NOT_ENOUGH_DATA / NO_SIGNAL / busy / error / off), text (one plain line), lines, n, min_n, pool_n, same_n, win_pct, win_low95_pct, exp_r, exp_r_low, exp_usdt, median_secs, p75_secs, median_win_secs, mae_p90_r, worst_r, by_source (counts per source, never added), risk_usdt, stop_pct, pool_age_sec, paper_only (always true).
NOT MOUNTED yet. To mount (owner says "mount ok"), add 4 lines to api_server.py after the sniper paper block, same try / except style:
    try:
        from api.sniper_riskbox import make_router as _sniper_riskbox_router
        app.include_router(_sniper_riskbox_router(require_api_token, DATA_DIR))
    except Exception as _e:
        print(f"[startup] sniper riskbox route skipped: {_e}")"""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_bridge_learn as BL
import owl_sniper_feed as F
import owl_sniper_riskbox as RB
import owl_sniper_tf as TF
from api.sniper import api_enabled

VERSION = "api/sniper_riskbox 1 (Part 11)"
PATH = "/api/v2/sniper_riskbox"
POOL_SEC, ANSWER_SEC, POOL_LIMIT, MAX_ANSWERS = 600, 20, 2000, 64
_pool = {"ts": 0.0, "pool": None}
MTF_SEC, MTF_RETRY_SEC = 3600, 600                          # PART 51: the confluence study is rebuilt at most once an hour (a failed build is retried after 10 minutes)
_mtf = {"ts": 0.0, "rep": None, "running": False, "fail_ts": 0.0}
_answers = {}
_build_lock, _mem_lock = threading.Lock(), threading.Lock()


def _bad(text, st=400):
    return st, {"state": "error", "text": text, "lines": [text], "paper_only": True}


def _get_pool(data_dir, now):
    """-> (pool or None, age, refreshing). One build at a time; an old pool is better than none."""
    with _mem_lock:
        pool, ts = _pool["pool"], _pool["ts"]
    if pool is not None and now - ts < POOL_SEC:
        return pool, now - ts, False
    if not _build_lock.acquire(blocking=False):
        return pool, (now - ts if pool is not None else None), True
    try:
        try:
            ex = BL.load_examples(data_dir, POOL_LIMIT)[0]
            new = RB.build_pool(ex)
            new["reports"] = RB.build_reports(ex, now)          # PART 50: edge decay + session reports, cached with the pool
        except Exception:                                      # a damaged file must never stop the backend; keep the old pool
            return pool, (now - ts if pool is not None else None), False
        with _mem_lock:
            _pool["ts"], _pool["pool"] = now, new
            _answers.clear()
        return new, 0.0, False
    finally:
        _build_lock.release()


def _get_mtf(data_dir, now):
    """PART 51: -> the cached confluence study or None. A slow build runs in ONE background thread; the box never waits for it."""
    with _mem_lock:
        rep, ts, running, fail = _mtf["rep"], _mtf["ts"], _mtf["running"], _mtf["fail_ts"]
        if (rep is not None and now - ts < MTF_SEC) or running or (rep is None and now - fail < MTF_RETRY_SEC):
            return rep
        _mtf["running"] = True

    def work():
        try:
            new = RB.build_mtf(data_dir)
        except Exception:
            new = None
        with _mem_lock:
            if new is not None:
                _mtf["rep"], _mtf["ts"] = new, time.time()
            else:
                _mtf["fail_ts"] = time.time()
            _mtf["running"] = False
            _answers.clear()
    threading.Thread(target=work, daemon=True).start()
    return rep


def riskbox_answer(data_dir, symbol, tf="5m", side=None, size=10.0, lev=1.0, now=None):
    """-> (http status, body). Never raises."""
    now = time.time() if now is None else now
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(data_dir), F.OFF_FILE)):
        return 200, {"state": "off", "text": "The Sniper is switched off (file v2_sniper_off).", "lines": ["The Sniper is switched off (file v2_sniper_off)."], "paper_only": True}
    sym = str(symbol or "").strip().upper()
    if not sym.isalnum() or len(sym) > 24:
        return _bad("The coin name is not valid.")
    if tf not in TF.SUPPORTED:
        return _bad("The interval must be one of: %s." % ", ".join(TF.SUPPORTED))
    side = (str(side).strip().upper() or None) if side else None
    if side not in (None, "LONG", "SHORT"):
        return _bad("The side must be LONG or SHORT (or empty).")
    try:
        size, lev = float(size), float(lev)
    except (TypeError, ValueError):
        return _bad("Size and leverage must be numbers.")
    if not (0.5 <= size <= 1000.0) or not (1.0 <= lev <= 20.0):
        return _bad("Size must be 0.5 to 1000 USDT and leverage 1 to 20.")
    key = (sym, tf, side, round(size, 4), round(lev, 4))
    with _mem_lock:
        hit = _answers.get(key)
    if hit and now - hit[0] < ANSWER_SEC:
        return 200, dict(hit[1], answer_age_sec=round(now - hit[0], 1))
    pool, age, refreshing = _get_pool(data_dir, now)
    if pool is None:
        return 200, {"state": "busy", "text": "The Risk Box is reading the saved trades and candles. Open this page again in a minute.", "lines": ["The Risk Box is reading the saved trades and candles. Open this page again in a minute."], "paper_only": True}
    try:
        body = RB.for_symbol(data_dir, sym, tf, side, size, lev, pool=pool, now=now, mtf=_get_mtf(data_dir, now))
    except Exception as e:
        return 200, {"state": "error", "text": "The Risk Box could not be built: %s." % str(e)[:80], "lines": ["The Risk Box could not be built."], "paper_only": True}
    body.update(paper_only=True, route_version=VERSION, pool_age_sec=None if age is None else round(age, 1), pool_n=pool["n"], refreshing=refreshing)
    with _mem_lock:
        if len(_answers) >= MAX_ANSWERS:
            _answers.clear()
        _answers[key] = (now, body)
    return 200, body


def make_router(require_api_token, data_dir):
    """Mounted by api_server.py only after the owner says "mount ok": 1 GET route behind the app's token check."""
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_riskbox(symbol: str = "", tf: str = "5m", side: str = "", size: float = 10.0, lev: float = 1.0):
        st, body = await asyncio.to_thread(riskbox_answer, data_dir, symbol, tf, side, size, lev)
        return JSONResponse(body, status_code=st)

    return r
