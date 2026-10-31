"""api/v2_data.py - Part 18: COLLECTORS 5 of 5 - READ-ONLY routes that show what the two collectors saved in v2_market.db. 5 routes, all GET, all behind the app's own token check:
/api/v2/status (switches, store size, last run, last health lines) | /api/v2/snapshot (newest top gainers / losers) | /api/v2/cohort (official cohort, newest day or ?day=YYYY-MM-DD)
| /api/v2/candles (?symbol=&interval=3m|5m&limit=) | /api/v2/gaps | /api/v2/summary (Part 36: what happened / tested / learned / unknown) | /api/v2/radar (Part 29: saved cohorts and how those coins moved since). The whole API is OFF until the file v2_api_enabled exists in the data folder (answer 404 "off"); then it still only READS.
Read-only for real: the store is opened with mode=ro + query_only, it is never created here, answers are capped (snapshot 100, candles 500, gaps 200 rows), bad input = 400,
a database problem = 503 with a short fixed text (no path, no SQL). No network, no write, no order code (guard test). make_router(require_api_token, data_dir) is used by api_server.py
ONLY after the owner's own ok (protected file) - until then this file is not mounted and changes nothing. Tests: python3 test/test_v2_api.py"""
import os
import re
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import v2_candles as K
import v2_collector as C
import v2_prepump as PP
import v2_prepump_watch as PW
import v2_radar as RD
import v2_radar_moves as RM
import v2_radar_outcomes as RO
import v2_scalp_ema as SE
import v2_scalp_large3 as SL3
import v2_scalp_large5 as SL5
import v2_scalp_pump as SP
import v2_scalp_report as SR
import v2_screen_check as SC
import v2_scalp_store as SS
import v2_setup_finder as SF
import v2_setup_forward as SW
import v2_store as S
import v2_wickstudy as WK
import v2_wickstudy_reentry as WR

VERSION = "v2_data 1 (Part 18)"
FLAG_NAME = "v2_api_enabled"
CAPS = {"snapshot": 100, "candles": 500, "gaps": 200}
ROUTES = ("status", "snapshot", "cohort", "candles", "gaps", "summary", "radar", "radar_outcomes", "radar_moves", "setups", "setups_forward", "prepump", "prepump_watch", "wickstudy", "wickstudy_forward", "wickstudy_reentry", "scalp_lab", "scalp_ema", "scalp_pump", "scalp_report", "scalp_large3", "scalp_large5", "screen_check")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def api_enabled(data_dir):
    p = os.path.join(os.path.realpath(data_dir), FLAG_NAME)
    try:
        if os.path.islink(p) or not os.path.isfile(p):
            return False
        with open(p, "r", encoding="utf-8") as f:
            return f.read(10).strip().lower() in ("1", "on", "true", "yes")
    except OSError:
        return False


def open_ro(data_dir):
    """Read-only connection, or None when the store does not exist yet (it is NEVER created here)."""
    path = S.store_path(data_dir)
    if not os.path.isfile(path):
        return None
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    con.execute("PRAGMA query_only=ON")
    return con


def _limit(raw, name):
    cap = CAPS[name]
    if raw in (None, ""):
        return min(cap, 100)
    if not str(raw).isdigit() or not 1 <= int(raw) <= cap:
        raise ValueError("limit must be a whole number from 1 to %d" % cap)
    return int(raw)


def _rows(con, sql, args, keys):
    return [dict(zip(keys, r)) for r in con.execute(sql, args).fetchall()]


def v_status(con, p, now, d):
    u = S.usage(con)
    last = con.execute("SELECT value FROM meta WHERE key='collector_last_run_ts'").fetchone()
    last = int(last[0]) if last and str(last[0]).isdigit() else None
    return {"ready": True, "switches": {"ticker": C.is_enabled(d), "candles": K.is_enabled(d)}, "store": u, "last_ticker_run_ts": last, "last_ticker_run_age_sec": None if last is None else max(0, now - last),
            "schema_provisional": bool(con.execute("SELECT value FROM meta WHERE key='schema_provisional'").fetchone()),
            "health": _rows(con, "SELECT ts, status, note FROM collector_health ORDER BY ts DESC, rowid DESC LIMIT 5", (), ("ts", "status", "note"))}


def v_snapshot(con, p, now, d):
    n = _limit(p.get("limit"), "snapshot")
    ts = con.execute("SELECT MAX(run_ts) FROM ticker_snapshot").fetchone()[0]
    rows = [] if ts is None else _rows(con, "SELECT symbol, price, change_pct, volume_usdt, rank_gain, rank_loss FROM ticker_snapshot WHERE run_ts=? "
                                       "ORDER BY MIN(COALESCE(rank_gain,999), COALESCE(rank_loss,999)), COALESCE(rank_gain,999), symbol LIMIT ?", (ts, n),
                                       ("symbol", "price", "change_pct", "volume_usdt", "rank_gain", "rank_loss"))
    return {"ready": True, "run_ts": ts, "rows": rows}


def v_cohort(con, p, now, d):
    day = p.get("day") or None
    if day is not None and not DAY_RE.match(day):
        raise ValueError("day must look like 2026-10-30")
    if day is None:
        day = (con.execute("SELECT MAX(day) FROM cohort_official").fetchone() or [None])[0]
    rows = [] if day is None else _rows(con, "SELECT kind, rank, symbol, open_price, snap_ts, source FROM cohort_official WHERE day=? ORDER BY kind, rank", (day,),
                                       ("kind", "rank", "symbol", "open_price", "snap_ts", "source"))
    return {"ready": True, "day": day, "rows": rows}


def v_radar(con, p, now, d):
    """Part 29 + 30: saved cohorts and how those exact coins moved since (read-only, see v2_radar.py). ?day=YYYY-MM-DD for one day, ?days=N (1 to 7) for the newest N."""
    return RD.build(con, now, p.get("day") or None, p.get("days") or None)


def v_radar_outcomes(con, p, now, d):
    """Part 31 + 32: what the saved cohort coins did 1 / 2 / 3 / 7 days after the snapshot, classes + episode rule (read-only, see v2_radar_outcomes.py). ?day= or ?days=N."""
    return RO.build(con, now, p.get("day") or None, p.get("days") or None)


def v_radar_moves(con, p, now, d):
    """Part 33: max favourable / adverse move, time to peak, drawdown and volume state of the saved cohort coins (read-only, see v2_radar_moves.py). ?day= or ?days=N."""
    return RM.build(con, now, p.get("day") or None, p.get("days") or None)


def v_setups(con, p, now, d):
    """Part 43: EMA-free formation marks on the saved candles (read-only, see v2_setup_finder.py). ?days=N (1 to 7)."""
    return SF.build(con, now, p.get("days") or None)


def v_setups_forward(con, p, now, d):
    """Part 44: what the price did 15 min / 30 min / 1 h / 4 h after each EMA-free formation, with a baseline (read-only, see v2_setup_forward.py). ?days=N (1 to 7)."""
    return SW.build(con, now, p.get("days") or None)


def v_prepump(con, p, now, d):
    """Part 47: when the pumped / dumped cohort coins first stood in the top 20 and how much of the move was still ahead (read-only, see v2_prepump.py). ?day= or ?days=N."""
    return PP.build(con, now, p.get("day") or None, p.get("days") or None)


def v_prepump_watch(con, p, now, d):
    """Part 48: today's Pre-pump / Pre-dump watch lists: coins in today's top 20 compared with the old cases of Part 47, price followed from the first moment (read-only, see v2_prepump_watch.py). ?days=N (1 to 7) = old cohort days used."""
    return PW.build(con, now, p.get("days") or None)


def v_wickstudy(con, p, now, d):
    """Part 58: stop-wick candles (a wick sweeps the swing of the 20 candles before and the close is back inside) marked on the saved candles (read-only, see v2_wickstudy.py). ?days=N (1 to 7)."""
    return WK.build(con, now, p.get("days") or None)


def v_wickstudy_forward(con, p, now, d):
    """Part 59: what the price did 15 min / 30 min / 1 h / 4 h after each stop-wick, with a baseline and the count of wick-tip retakes (read-only, see v2_wickstudy.py). ?days=N (1 to 7)."""
    return WK.build_forward(con, now, p.get("days") or None)


def v_wickstudy_reentry(con, p, now, d):
    """Part 60: HYPOTHETICAL quick re-entry after each stop-wick: delay, status, and the price 15 min / 30 min / 1 h after the entry close (read-only replay, see v2_wickstudy_reentry.py). ?days=N (1 to 7)."""
    return WR.build(con, now, p.get("days") or None)


def v_scalp_lab(con, p, now, d):
    """Part 50: Scalp Lab status = categories, versions and record counts from its OWN file v2_scalp.db (read-only, see v2_scalp_store.py)."""
    return SS.status(d)


def v_scalp_ema(con, p, now, d):
    """Part 52: Scalp Lab category EMA Re-entry / Retest, HYPOTHETICAL replay of the saved candles with a baseline (read-only, see v2_scalp_ema.py). ?days=N (1 to 7)."""
    return SE.build(con, now, p.get("days") or None)


def v_scalp_pump(con, p, now, d):
    """Part 53: Scalp Lab category Pump / Dump, FOLLOW and FADE as two hypotheses, replay of the saved candles with a baseline (read-only, see v2_scalp_pump.py). ?days=N (1 to 7)."""
    return SP.build(con, now, p.get("days") or None)


def v_scalp_report(con, p, now, d):
    """Part 54: Scalp Lab ledger report (placeholder so the name is known; the work is in SR.build, no market store needed)."""
    return {}


def v_scalp_large3(con, p, now, d):
    """Part 55: Scalp Lab large-trade replay on 3m candles, HYPOTHETICAL split entry beside the real trade (read-only, see v2_scalp_large3.py). ?days=N (1 to 365)."""
    return SL3.build(con, d, now, p.get("days") or None)


def v_scalp_large5(con, p, now, d):
    """Part 56: Scalp Lab large-trade replay on 5m + REAL vs hypothetical side by side for 3m and 5m (read-only, see v2_scalp_large5.py). ?days=N (1 to 365)."""
    return SL5.build(con, d, now, p.get("days") or None)


def v_screen_check(con, p, now, d):
    """Part 74: Screenshot Check. ?symbol=BTCUSDT&interval=5m&at=2026-10-31 14:30 (UTC, optional). Evidence block + a separate OPINION block (see v2_screen_check.py). Read-only, never an order."""
    return SC.build(con, p.get("symbol") or "", p.get("interval") or "5m", p.get("at") or "", now)


def v_candles(con, p, now, d):
    sym, iv = p.get("symbol") or "", p.get("interval") or "5m"
    if not K._symbol_ok(sym) or iv not in K.INTERVALS:
        raise ValueError("symbol must be like BTCUSDT and interval 3m or 5m")
    n = _limit(p.get("limit"), "candles")
    rows = _rows(con, "SELECT open_ts, o, h, l, c, v FROM (SELECT * FROM candles WHERE symbol=? AND interval=? ORDER BY open_ts DESC LIMIT ?) ORDER BY open_ts",
                 (sym, iv, n), ("open_ts", "o", "h", "l", "c", "v"))
    gaps = [] if not rows else _rows(con, "SELECT from_ts, to_ts, reason FROM gap_log WHERE kind='candle' AND symbol=? AND interval=? AND to_ts>=? AND from_ts<=? ORDER BY from_ts",
                                     (sym, iv, rows[0]["open_ts"], rows[-1]["open_ts"]), ("from_ts", "to_ts", "reason"))
    return {"ready": True, "symbol": sym, "interval": iv, "rows": rows, "gaps": gaps}


def v_gaps(con, p, now, d):
    n = _limit(p.get("limit"), "gaps")
    return {"ready": True, "rows": _rows(con, "SELECT kind, symbol, interval, from_ts, to_ts, reason FROM gap_log ORDER BY from_ts DESC, rowid DESC LIMIT ?", (n,),
                                         ("kind", "symbol", "interval", "from_ts", "to_ts", "reason"))}


def v_summary(con, p, now, d):
    """Part 36: placeholder entry so the name is known; the real work is in summary_answer (no market store needed)."""
    return {}


VIEWS = {"screen_check": v_screen_check, "scalp_large5": v_scalp_large5, "scalp_large3": v_scalp_large3, "scalp_report": v_scalp_report, "scalp_pump": v_scalp_pump, "scalp_ema": v_scalp_ema, "scalp_lab": v_scalp_lab, "wickstudy_reentry": v_wickstudy_reentry, "wickstudy_forward": v_wickstudy_forward, "wickstudy": v_wickstudy, "prepump_watch": v_prepump_watch, "prepump": v_prepump, "setups_forward": v_setups_forward, "setups": v_setups, "radar": v_radar, "radar_outcomes": v_radar_outcomes, "radar_moves": v_radar_moves, "summary": v_summary, "status": v_status, "snapshot": v_snapshot, "cohort": v_cohort, "candles": v_candles, "gaps": v_gaps}


def summary_answer(data_dir):
    """Part 36: GET /api/v2/summary -> (status, body). Part 35 summaries (what happened / tested / learned / unknown), read-only, through the Part 5 redaction.
    Does not need the market store. A problem = a short fixed text (no path, no traceback)."""
    try:
        import json
        import v2_inv_redact as R
        import v2_summaries as M
        return 200, json.loads(R.safe_report(json.loads(json.dumps(M.build(data_dir), default=str))))
    except Exception as e:
        if e.__class__.__name__ == "RedactionFailed":
            return 503, {"error": "the answer was refused: secret-looking text"}
        return 503, {"error": "the summary could not be made right now"}


def dispatch(name, params, data_dir, now=None):
    """-> (http status, body dict). Never raises."""
    if name not in VIEWS:
        return 404, {"error": "unknown route"}
    if not api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    now = int(time.time() if now is None else now)
    if name == "summary":
        return summary_answer(data_dir)
    if name in ("scalp_lab", "scalp_report"):          # its own file, does not need the market store
        try:
            return 200, (SS.status(data_dir) if name == "scalp_lab" else SR.build(data_dir))
        except (S.StoreRefused, sqlite3.Error):
            return 503, {"error": "the Scalp Lab store is busy or unreadable"}
    try:
        con = open_ro(data_dir)
        if con is None:
            return 200, {"ready": False, "note": "the market store is not created yet"}
        try:
            return 200, VIEWS[name](con, params or {}, now, data_dir)
        finally:
            con.close()
    except ValueError as e:
        return 400, {"error": str(e)}
    except S.StoreRefused:
        return 503, {"error": "the market store path is not safe"}
    except sqlite3.Error:
        return 503, {"error": "the market store is busy or unreadable"}


def make_router(require_api_token, data_dir):
    """Mounted by api_server.py (after the owner's ok): 5 GET routes, each behind the app's token check."""
    import asyncio
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    def add(name):
        async def view(symbol: str = "", interval: str = "", limit: str = "", day: str = "", days: str = "", at: str = ""):
            st, body = await asyncio.to_thread(dispatch, name, {"symbol": symbol, "interval": interval, "limit": limit, "day": day, "days": days, "at": at}, data_dir)
            return JSONResponse(body, status_code=st)
        view.__name__ = "v2_" + name
        r.get("/api/v2/" + name, dependencies=[Depends(require_api_token)])(view)
    for n in ROUTES:
        add(n)
    return r
