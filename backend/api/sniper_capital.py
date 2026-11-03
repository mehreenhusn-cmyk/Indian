"""api/sniper_capital.py - OwlSniper SMALL-CAPITAL route (Part 34 / FILE 29): ONE read-only route GET /api/v2/sniper_capital?capital=10&stop=0.5&lev=10&book=learn&risk=1
It joins two pure files for ONE card: owl_sniper_capital.py (what ONE trade may look like at this capital: the size ladder, the day limits) and owl_sniper_grow.py (today's good / bad day throttle, the growth plan, the daily + weekly view).
PAPER ONLY, READ ONLY: nothing is opened, closed or written, no order, no network. The closed Sniper paper trades are only read from the paper trade store (same store the Sniper paper bridge uses).
THE BOOK: book=learn (default, the tiny LEARN trades, source sniper_learn) or book=real (source sniper, the real-gate paper trades). ONE book per answer, never added; the answer names it. Other bots (Dual, Brain, main) are not used here.
THE SIMULATION (said plainly in the answer): the saved Sniper paper trades have tiny sizes, so their USDT is not the small account's USDT. Each trade's result in R (pnl / (size x lev x stop %), after fees) is replayed at the owner's capital with 1R = capital x risk % (fixed, no compounding inside the replay). A trade with no real stop price or no result is dropped, never guessed. Win %, days and counts are the real ones.
Params: capital 5 to 100000 USDT (default 10), stop 0.1 to 5 % (default 0.5, for the size ladder / one-trade size), lev 1 to 10 (default 10, capped by the capital file), risk 0.25 to 2 % (default 1), book learn / real.
Same switch as the other V2 routes: 404 until the file v2_api_enabled exists in the data folder, and off for good while the file v2_sniper_off exists. Cached 30 s per request.
Answer: state (OK / NOT_ENOUGH_DATA / off / error), text, lines, book, n_trades, capital, one_trade (size_trade answer), ladder (rows), report (throttle, plan, daily, weekly, capital_now), simulated (always true), paper_only (always true).
NOT MOUNTED yet. To mount (owner says "mount ok"), add 4 lines to api_server.py after the sniper paper block, same try / except style:
    try:
        from api.sniper_capital import make_router as _sniper_capital_router
        app.include_router(_sniper_capital_router(require_api_token, DATA_DIR))
    except Exception as _e:
        print(f"[startup] sniper capital route skipped: {_e}")"""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import owl_sniper_capital as CP
import owl_sniper_feed as F
import owl_sniper_grow as GR
import owl_sniper_paper as SP
from api.sniper import api_enabled

VERSION = "api/sniper_capital 1 (Part 34)"
PATH = "/api/v2/sniper_capital"
ANSWER_SEC, MAX_ANSWERS, ROW_LIMIT = 30, 32, 3000
BOOKS = {"learn": SP.LEARN_SOURCE, "real": SP.SOURCE}
_answers = {}
_lock = threading.Lock()


def _bad(text, st=400):
    return st, {"state": "error", "text": text, "lines": [text], "paper_only": True, "simulated": True}


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def to_r_trades(rows, source, capital, risk_pct):
    """Closed paper rows of ONE source -> [{ts, pnl_usdt, r_net}] replayed at the owner's capital. 1R = capital x risk %. Rows without a real stop / size / result are dropped."""
    out, dropped = [], 0
    one_r = capital * risk_pct / 100.0
    for t in rows or ():
        if not isinstance(t, dict) or t.get("source") != source:
            continue
        entry, sl, inv, lev = _f(t.get("entry_price")), _f(t.get("signal_stop_loss")), _f(t.get("invest_usdt")), _f(t.get("leverage")) or 1.0
        pnl, ts = _f(t.get("pnl_usdt")), _f(t.get("closed_at_ts"))
        if not entry or entry <= 0 or sl is None or not inv or inv <= 0 or pnl is None or not ts:
            dropped += 1
            continue
        stop_pct = abs(entry - sl) / entry * 100.0
        risk = inv * lev * stop_pct / 100.0
        if stop_pct <= 0 or risk <= 0:
            dropped += 1
            continue
        r = pnl / risk
        out.append({"ts": ts, "r_net": r, "pnl_usdt": r * one_r})
    return out, dropped


def _rows(data_dir):
    from recovered_bot import trade_store
    return trade_store.get_recent_closed(limit=ROW_LIMIT, net=True, bot=SP.BOT)


def capital_answer(data_dir, capital=10.0, stop=0.5, lev=10.0, risk=1.0, book="learn", now=None, rows_fn=None):
    """-> (http status, body). Never raises. rows_fn lets a caller give the closed rows (default: the paper trade store)."""
    now = time.time() if now is None else now
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    if os.path.exists(os.path.join(os.path.realpath(data_dir), F.OFF_FILE)):
        t = "The Sniper is switched off (file v2_sniper_off)."
        return 200, {"state": "off", "text": t, "lines": [t], "paper_only": True, "simulated": True}
    cap, st, lv, rk = _f(capital), _f(stop), _f(lev), _f(risk)
    if None in (cap, st, lv, rk) or not (5.0 <= cap <= 100000.0) or not (0.1 <= st <= 5.0) or not (1.0 <= lv <= 10.0) or not (0.25 <= rk <= 2.0):
        return _bad("Capital must be 5 to 100000 USDT, stop 0.1 to 5 %, leverage 1 to 10, risk 0.25 to 2 %.")
    if book not in BOOKS:
        return _bad("The book must be learn or real.")
    key = (round(cap, 4), round(st, 4), round(lv, 4), round(rk, 4), book)
    with _lock:
        hit = _answers.get(key)
    if hit and now - hit[0] < ANSWER_SEC:
        return 200, dict(hit[1], answer_age_sec=round(now - hit[0], 1))
    try:
        rows = (rows_fn or _rows)(data_dir)
    except Exception:
        t = "The paper trade store is not available in this backend, so no growth view can be built."
        return 200, {"state": "error", "text": t, "lines": [t], "paper_only": True, "simulated": True}
    try:
        trades, dropped = to_r_trades(rows, BOOKS[book], cap, rk)
        c = CP.cfg({"risk_pct": rk, "lev": lv})
        rep = GR.report(trades, cap, None, now, None, c)
        one = CP.size_trade(cap, st, c, lv, (), cap, [t["pnl_usdt"] for t in trades if GR.day_key(t["ts"]) == GR.day_key(now)])
        lad = CP.ladder(cap, c)
    except Exception as e:
        t = "The capital view could not be built: %s." % str(e)[:80]
        return 200, {"state": "error", "text": t, "lines": [t], "paper_only": True, "simulated": True}
    lines = ["Book: %s (%s paper trades, %d usable, %d dropped for no real stop or result)." % (book.upper(), BOOKS[book], len(trades), dropped)] + rep["lines"] + one["lines"]
    lines.append("Replay at %.2f USDT with 1R = %.4f USDT (%.2f%%). Results of the saved paper trades in R; USDT is simulated, not real." % (cap, cap * rk / 100.0, rk))
    body = {"state": "NOT_ENOUGH_DATA" if rep["plan"]["state"] == "NOT_ENOUGH_DATA" else "OK", "text": lines[1], "lines": lines, "version": VERSION, "book": book, "n_trades": len(trades), "dropped": dropped,
            "capital": cap, "risk_pct": rk, "lev": lv, "one_trade": one, "ladder": lad["rows"], "report": rep, "simulated": True, "paper_only": True}
    with _lock:
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
    async def v2_sniper_capital(capital: float = 10.0, stop: float = 0.5, lev: float = 10.0, risk: float = 1.0, book: str = "learn"):
        st, body = await asyncio.to_thread(capital_answer, data_dir, capital, stop, lev, risk, book)
        return JSONResponse(body, status_code=st)

    return r
