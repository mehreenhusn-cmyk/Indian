"""api/sniper.py - OwlSniper Part S5 of 7: ONE read-only route GET /api/v2/sniper for the Flutter screen (Part S6). Same style as api/v2_reports_route.py.
It only READS the two result files of owl_sniper_feed.py (v2_sniper_live.json, v2_sniper_model.json) and shows them as one answer. It sends no order, writes no trade and changes no old file.
The only thing it does besides reading: it calls owl_sniper_feed.kick(), which starts the refresh as its OWN low-priority process when the live file is older than 4.5 minutes (see owl_sniper_feed.py), so the page fills by itself and nobody needs a Termux command.
Same switch as the other V2 routes: it stays OFF (404, enabled False) until the file v2_api_enabled exists in the data folder. Also off for good while the file v2_sniper_off exists.
MOUNTED in Round 24 (api_server.py, after the Fees + tax block, wrapped in try / except so a bad file never stops the backend). Round 24 adds, read-only and each part wrapped on its own (a failing part gives {"state": "error"}, never a crash):
  compare     Sniper vs main bot (owl_sniper_cmp.build): the Sniper's TEST-day replay next to the bot's real paper trades, one word only with 15+ trades each side
  executor    owl_sniper_exec.status: mode paper, armed or not, kill switch, today's result (the arm code is never shown; arming stays a Termux command, never a route)
  capital     the 10 USDT base with the fee, slippage, round-trip cost and worst-case loss (Capital Shield pillar)
  barrier_rule  the triple-barrier rule in numbers (profit K_TP x ATR, stop K_SL x ATR, hold candles), so the screen can explain the lines
and ONE new route GET /api/v2/sniper_live: the live scan with retries (owl_sniper_live.scan_live): fresh cards with their triple-barrier lines. At most one scan per 25 s (cached), one at a time.
Answer (all plain text and numbers, nothing is made up when a file is missing): ready, refreshing, status, headline, banner (TRENDING / SIDEWAYS / MIXED / UNKNOWN), counts, regimes, floor, floor_verified, cards (newest first),
equity ({all, floor, test_trades}), lines (the Insight Report), floor_check, curve (win rate per win-chance cut on TEST days), sd_curve (SD length 20..200), updated_ago_sec, model_ago_sec, watch_only (always true)."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F

VERSION = "api/sniper 2 (Part S5 + Round 24)"
PATH = "/api/v2/sniper"
FLAG_NAME = "v2_api_enabled"
LIVE_PATH = "/api/v2/sniper_live"
LIVE_TTL = 25                   # seconds: one live scan serves every call inside this time
_live_cache, _live_lock = {"ts": 0, "body": None}, threading.Lock()
WAIT_TEXT = "OwlSniper has not run yet. It starts by itself; open this page again in a few minutes."


def api_enabled(data_dir):
    p = os.path.join(os.path.realpath(data_dir), FLAG_NAME)
    try:
        if os.path.islink(p) or not os.path.isfile(p):
            return False
        with open(p, "r", encoding="utf-8") as f:
            return f.read(10).strip().lower() in ("1", "on", "true", "yes")
    except OSError:
        return False


def _ago(saved_at, now):
    try:
        return max(0, int(now - int(saved_at)))
    except (TypeError, ValueError):
        return None


def build(live, model, refreshing, now, extra=None):
    """The two saved dicts (either may be None) -> the answer dict. Pure function: no file, no network."""
    live, model = live or {}, model or {}
    body = {"version": VERSION, "ready": live.get("status") == "OK", "refreshing": bool(refreshing), "status": live.get("status") or "NO_DATA_YET",
            "headline": live.get("headline") or WAIT_TEXT, "banner": live.get("banner") or "UNKNOWN", "counts": live.get("counts") or {}, "regimes": live.get("regimes") or {},
            "coins_scanned": live.get("coins_scanned") or 0, "stale_coins": live.get("stale_coins") or 0, "floor": live.get("floor", 0.85),
            "floor_verified": bool(live.get("floor_verified")), "cards": live.get("cards") or [], "equity": model.get("equity"), "lines": model.get("lines") or [],
            "floor_check": model.get("floor_check"), "curve": model.get("curve") or [], "sd_curve": model.get("sd_curve") or [], "verdict": model.get("verdict"),
            "model_status": model.get("status"), "coins_in_model": len(model.get("coins") or []), "updated_ago_sec": _ago(live.get("saved_at"), now),
            "model_ago_sec": _ago(model.get("saved_at"), now), "watch_only": True, "note": "WATCH ONLY: this page never sends an order."}
    body.update(extra or {})
    return body


def _part(fn, *a):
    """One optional part of the answer. A failing part must never break the page."""
    try:
        return fn(*a)
    except Exception:
        return {"state": "error"}


def extras(data_dir, now):
    """Round 24: the three read-only add-ons (each imported and run on its own)."""
    def compare():
        import owl_sniper_cmp as CMP
        return CMP.build(data_dir, now)

    def executor():
        import owl_sniper_exec as EX
        return EX.status(data_dir, now)

    def rule():
        import owl_sniper_barriers as BR
        return {"k_tp": BR.K_TP, "k_sl": BR.K_SL, "hold_candles": BR.HOLD, "atr_len": BR.ATR_LEN,
                "text": "Every signal gets 3 exits set before the trade: profit at %.1f x ATR, stop at %.1f x ATR, and a time limit of %d candles. If one candle touches both, the stop counts first." % (BR.K_TP, BR.K_SL, BR.HOLD)}
    def capital():
        import owl_sniper_engine_c1 as C
        worst = 10.0 * (C.MAX_SL_PCT + C.cost_pct()) / 100.0
        return {"base_usdt": 10.0, "fee_pct": C.FEE_PCT, "slip_pct": C.SLIP_PCT, "round_trip_pct": round(C.cost_pct(), 4), "max_stop_pct": C.MAX_SL_PCT, "min_stop_pct": C.MIN_SL_PCT,
                "worst_loss_usdt": round(worst, 3)}      # the widest allowed stop plus the round-trip cost on the 10 USDT base (an upper bound, not a promise)
    return {"compare": _part(compare), "executor": _part(executor), "barrier_rule": _part(rule), "capital": _part(capital)}


def live_answer(data_dir, now=None, interval="5m"):
    """-> (http status, body). The live scan with retries, cached for LIVE_TTL seconds, one scan at a time. Never raises."""
    now = int(time.time() if now is None else now)
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    c = _live_cache
    if c["body"] is not None and now - c["ts"] < LIVE_TTL:
        return 200, c["body"]
    if not _live_lock.acquire(blocking=False):
        return (200, c["body"]) if c["body"] is not None else (200, {"status": "BUSY", "note": "A live scan is running. Try again in a few seconds.", "cards": [], "watch_only": True})
    try:
        import owl_sniper_live as LV
        body = LV.scan_live(data_dir, now, interval)
        c["ts"], c["body"] = now, body
        return 200, body
    except Exception:
        return 503, {"error": "the live scan could not be made right now"}
    finally:
        _live_lock.release()


def answer(data_dir, now=None):
    """-> (http status, body dict). Never raises."""
    now = int(time.time() if now is None else now)
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    try:
        started = F.kick(data_dir, now)
        live, model = F.read_json(data_dir, F.LIVE_FILE), F.read_json(data_dir, F.MODEL_FILE)
        return 200, build(live, model, started or F.lock_busy(data_dir, now), now, extras(data_dir, now))
    except Exception:
        return 503, {"error": "the sniper page could not be made right now"}


def make_router(require_api_token, data_dir):
    """Mounted by api_server.py (Round 24): 2 GET routes behind the app's token check."""
    import asyncio
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)

    @r.get(LIVE_PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_live():
        st, body = await asyncio.to_thread(live_answer, data_dir)
        return JSONResponse(body, status_code=st)
    return r
