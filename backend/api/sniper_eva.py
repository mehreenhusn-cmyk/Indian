"""api/sniper_eva.py - OwlSniper Part 17a: ONE read-only route GET /api/v2/sniper_eva = EXPECTED vs ACTUAL (owl_sniper_eva.report) for the Sniper paper trades.
Expected = the Risk Box answer frozen at the entry (owl_sniper_eva_hook, file v2_sniper_eva.json). Actual = the closed paper result of the SAME trade from the trade record (owl_sniper_record): R = pnl USDT / 1R in USDT, where
1R in USDT = margin x leverage x stop % (the Risk Box's own rule). The paper P&L is already net of fees. The time-to-result is the real hold time; the dip (MAE) is not measured here, so that line stays empty.
Below 30 compared trades per lane the answer says NOT_ENOUGH_DATA and gives NO number. Lanes (EXPLORE / LEARN / REAL) are judged apart. Report only: nothing is paused. 404 until v2_api_enabled exists, off while v2_sniper_off exists.
Cached 20 s. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_eva as EVA
import owl_sniper_feed as F
import owl_sniper_record as REC
from api.sniper import api_enabled

VERSION = "api/sniper_eva 1 (Part 17a)"
PATH = "/api/v2/sniper_eva"
_CACHE = {"t": 0.0, "body": None}


def actuals(d, now):
    """Closed Sniper trades WITH a record -> [{uid, r_net, secs, mae_r, mfe_r, result, entry_ts}]. A trade with no result number is skipped."""
    out = []
    for t in (REC.build(d, now, 100).get("closed") or []):
        inv, lev, sp, pnl = (REC._num(t.get(k)) for k in ("invest_usdt", "leverage", "stop_pct", "pnl_usdt"))
        if not t.get("id") or None in (inv, lev, sp, pnl) or sp <= 0 or inv <= 0:
            continue
        risk = inv * lev * sp / 100.0
        out.append({"uid": t["id"], "r_net": round(pnl / risk, 4), "secs": REC._num(t.get("held_sec")), "mae_r": None, "mfe_r": None, "result": t.get("exit_reason"), "entry_ts": REC._num(t.get("opened_at"))})
    return out


def answer(d, now=None):
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
        return 200, {"state": "off", "paper_only": True, "text": "The Sniper is switched off (file v2_sniper_off)."}
    t = time.time() if now is None else now
    if _CACHE["body"] is not None and now is None and t - _CACHE["t"] < 20:
        return 200, _CACHE["body"]
    try:
        body = EVA.report(d, actuals(d, t), t)
        body["min_n"] = EVA.MIN_N
    except Exception as e:
        return 200, {"state": "error", "text": "%s: %s" % (type(e).__name__, str(e)[:80]), "paper_only": True}
    if now is None:
        _CACHE["t"], _CACHE["body"] = t, body
    return 200, body


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_eva():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)
    return r
