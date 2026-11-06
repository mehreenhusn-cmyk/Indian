"""api/sniper_opp.py - OwlSniper Part 17a: ONE read-only route GET /api/v2/sniper_opp = for every OPEN Sniper paper trade ONE plain line: STAY / TAKE PROFIT / ROTATE / KEEP (owl_sniper_opp.report). Report only: nothing is closed or opened.
Inputs, all existing: the open trades of the trade record (owl_sniper_record: id, trade_id, symbol, opened_at, margin, leverage, stop %), the live NET paper P&L of each open trade (paper_trader._fresh_snapshot, the same number the Positions page shows),
and the Risk Box numbers FROZEN at the entry (owl_sniper_eva: exp_r, median_secs, p75_secs). R now = live net P&L / 1R in USDT (1R = margin x leverage x stop %).
A trade with no frozen Risk Box (box was not OK, or it opened before Part 17a) or no live P&L gets KEEP and the reason in plain words. The advice is ROUGH: the average of similar past trades, not a forecast of this one.
alts (the better PROVEN setups) is empty for now: no feed of proven alternatives is wired yet, so ROTATE cannot fire and the line says no better proven setup is available. 404 until v2_api_enabled exists, off while v2_sniper_off exists. Cached 10 s. Mounted by api/sniper_mount.py."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_eva as EVA
import owl_sniper_feed as F
import owl_sniper_opp as OPP
import owl_sniper_record as REC
from api.sniper import api_enabled

VERSION = "api/sniper_opp 1 (Part 17a)"
PATH = "/api/v2/sniper_opp"
_CACHE = {"t": 0.0, "body": None}


def _live_pnl():
    """{paper trade id: net P&L in USDT} of the open paper trades. {} when the paper trader is not in this process or has no price."""
    try:
        from recovered_bot import paper_trader as pt
        return {x["id"]: x["pnl_usdt"] for x in pt._fresh_snapshot("b1") if isinstance(x, dict) and x.get("pnl_usdt") is not None}
    except Exception:
        return {}


def build(d, now, pnl=None):
    rec = REC.build(d, now, 30)
    exp = EVA.load_expected(d)
    pnl = _live_pnl() if pnl is None else pnl
    trades, notes, meta = [], [], {}
    for r in rec.get("open") or []:
        inv, lev, sp = (REC._num(r.get(k)) for k in ("invest_usdt", "leverage", "stop_pct"))
        live = pnl.get(r.get("trade_id")) if r.get("trade_id") is not None else None
        meta[r["id"]] = {"symbol": r.get("symbol"), "side": r.get("side"), "trade_id": r.get("trade_id"), "lane": r.get("lane")}
        if live is None or None in (inv, lev, sp) or sp <= 0 or inv <= 0:
            notes.append(dict(meta[r["id"]], id=r["id"], decision="KEEP", text="Nothing to do. The live price is not available for this trade right now. The stop or the target will close it."))
            continue
        risk = inv * lev * sp / 100.0
        e = exp.get(r["id"])
        trades.append({"id": r["id"], "age_secs": now - (REC._num(r.get("opened_at")) or now), "r_net_now": live / risk, "risk_usdt": risk, "box": dict(e, state="OK") if e else None})
    out = OPP.report(trades, alts=(), can_open=True)
    rows = [dict(meta.get(x["id"], {}), **x) for x in out["rows"]] + notes
    n = {k: sum(1 for x in rows if x["decision"] == k) for k in ("KEEP", "STAY", "TAKE_PROFIT", "ROTATE")}
    text = "No open Sniper trade." if not rows else "%d open: %d take profit, %d rotate, %d stay, %d keep (no advice)." % (len(rows), n["TAKE_PROFIT"], n["ROTATE"], n["STAY"], n["KEEP"])
    return {"version": VERSION, "state": "OK" if rows else "NO_TRADES", "counts": n, "rows": rows, "text": text, "rough": True, "paper_only": True, "report_only": True}


def answer(d, now=None):
    if not api_enabled(d):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
        return 200, {"state": "off", "paper_only": True, "rows": [], "text": "The Sniper is switched off (file v2_sniper_off)."}
    t = time.time() if now is None else now
    if _CACHE["body"] is not None and now is None and t - _CACHE["t"] < 10:
        return 200, _CACHE["body"]
    try:
        body = build(d, t)
    except Exception as e:
        return 200, {"state": "error", "text": "%s: %s" % (type(e).__name__, str(e)[:80]), "rows": [], "paper_only": True}
    if now is None:
        _CACHE["t"], _CACHE["body"] = t, body
    return 200, body


def make_router(require_api_token, data_dir):
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_sniper_opp():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)
    return r
