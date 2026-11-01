"""api/sniper.py - OwlSniper Part S5 of 7: ONE read-only route GET /api/v2/sniper for the Flutter screen (Part S6). Same style as api/v2_reports_route.py.
It only READS the two result files of owl_sniper_feed.py (v2_sniper_live.json, v2_sniper_model.json) and shows them as one answer. It sends no order, writes no trade and changes no old file.
The only thing it does besides reading: it calls owl_sniper_feed.kick(), which starts the refresh as its OWN low-priority process when the live file is older than 4.5 minutes (see owl_sniper_feed.py), so the page fills by itself and nobody needs a Termux command.
Same switch as the other V2 routes: it stays OFF (404, enabled False) until the file v2_api_enabled exists in the data folder. Also off for good while the file v2_sniper_off exists.
NOT MOUNTED YET. api_server.py is protected; it needs the owner's "mount ok", then these 4 lines after the Fees + tax block (each block is wrapped, so a bad file never stops the backend):
    try:
        from api.sniper import make_router as _sniper_router
        app.include_router(_sniper_router(require_api_token, DATA_DIR))
    except Exception as _e:
        print(f"[startup] sniper route skipped: {_e}")
Answer (all plain text and numbers, nothing is made up when a file is missing): ready, refreshing, status, headline, banner (TRENDING / SIDEWAYS / MIXED / UNKNOWN), counts, regimes, floor, floor_verified, cards (newest first),
equity ({all, floor, test_trades}), lines (the Insight Report), floor_check, curve (win rate per win-chance cut on TEST days), sd_curve (SD length 20..200), updated_ago_sec, model_ago_sec, watch_only (always true)."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_feed as F

VERSION = "api/sniper 1 (Part S5)"
PATH = "/api/v2/sniper"
FLAG_NAME = "v2_api_enabled"
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


def build(live, model, refreshing, now):
    """The two saved dicts (either may be None) -> the answer dict. Pure function: no file, no network."""
    live, model = live or {}, model or {}
    body = {"version": VERSION, "ready": live.get("status") == "OK", "refreshing": bool(refreshing), "status": live.get("status") or "NO_DATA_YET",
            "headline": live.get("headline") or WAIT_TEXT, "banner": live.get("banner") or "UNKNOWN", "counts": live.get("counts") or {}, "regimes": live.get("regimes") or {},
            "coins_scanned": live.get("coins_scanned") or 0, "stale_coins": live.get("stale_coins") or 0, "floor": live.get("floor", 0.85),
            "floor_verified": bool(live.get("floor_verified")), "cards": live.get("cards") or [], "equity": model.get("equity"), "lines": model.get("lines") or [],
            "floor_check": model.get("floor_check"), "curve": model.get("curve") or [], "sd_curve": model.get("sd_curve") or [], "verdict": model.get("verdict"),
            "model_status": model.get("status"), "coins_in_model": len(model.get("coins") or []), "updated_ago_sec": _ago(live.get("saved_at"), now),
            "model_ago_sec": _ago(model.get("saved_at"), now), "watch_only": True, "note": "WATCH ONLY: this page never sends an order."}
    return body


def answer(data_dir, now=None):
    """-> (http status, body dict). Never raises."""
    now = int(time.time() if now is None else now)
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    try:
        started = F.kick(data_dir, now)
        live, model = F.read_json(data_dir, F.LIVE_FILE), F.read_json(data_dir, F.MODEL_FILE)
        return 200, build(live, model, started or F.lock_busy(data_dir, now), now)
    except Exception:
        return 503, {"error": "the sniper page could not be made right now"}


def make_router(require_api_token, data_dir):
    """Mounted by api_server.py after the owner's "mount ok": 1 GET route behind the app's token check."""
    import asyncio
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)
    return r
