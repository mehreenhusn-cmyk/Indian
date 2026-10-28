"""api/status.py - basic, status, system, positions, market, signals, BTC, history and candle routes, moved out of api_server.py (NEXT-6f).

root + health, status, system, ops, load_report (+ daily), positions, market, signals, btc live / signals, daily-report,
alerts, history, equity, calendar, candles. Same code, same paths, same order: api_server.py includes the four factories
below at the exact places the routes used to be (the AI-key / app-prefs routes and the Vision router sit between them).
"""
import asyncio
import time

from fastapi import APIRouter

from recovered_bot import settings_store, trade_store, paper_trader, status, db, exchange, telemetry
from api.swr import _swr


def make_router_basic():
    """GET / and GET /health."""
    r = APIRouter()

    @r.get("/")
    async def root():
        return {"status": "OWL Terminal API", "bot_status": status.get().get("status")}


    @r.get("/health")
    async def health():
        return {"status": "healthy"}

    return r


def make_router_system(display_status, data_dir):
    """status, system, ops, load_report. display_status = api_server._display_status, data_dir = api_server.DATA_DIR (passed in, not copied)."""
    r = APIRouter()
    _display_status = display_status
    DATA_DIR = data_dir

    @r.get("/api/status")
    def get_status():
        return _display_status()


    @r.get("/api/system")
    async def get_system():
        """System Load card: cached telemetry only (CPU/RAM/disk, REST calls/min,
        broadcaster cost, candle poll stats, AI assistant, Binance feed). Reads a
        snapshot the sampler thread already built - no work happens per request."""
        snap = telemetry.snapshot()
        try:
            from recovered_bot import loop_watch
            snap = dict(snap, **loop_watch.snapshot())
        except Exception:
            pass
        return snap


    @r.get("/api/ops")
    async def get_ops():
        """Left-swipe Backend panel: which zip is live, uptime, restarts today, last problems (see ops_status.py)."""
        from recovered_bot import ops_status
        return await asyncio.to_thread(ops_status.snapshot, DATA_DIR)


    @r.get("/api/load_report")
    async def load_report_get(hours: float = 4.0):
        """Where is the load? Meters + the main bottleneck for the last 1 / 4 / 24 h (see load_report.py)."""
        from recovered_bot import load_report
        return await asyncio.to_thread(load_report.build, hours)


    @r.get("/api/load_report/daily")
    async def load_report_daily():
        from recovered_bot import load_report
        return {"days": await asyncio.to_thread(load_report.daily_list)}

    return r


def make_router_market(display_status, bot_arg):
    """positions, market, signals, BTC live / signals, daily-report. display_status / bot_arg = api_server's own functions."""
    r = APIRouter()
    _display_status = display_status
    _bot_arg = bot_arg

    @r.get("/api/positions")
    def get_positions(bot: str = "b1"):
        """Standalone positions endpoint - same live/paper exclusivity as the
        open_positions field inside /api/status (see _display_status)."""
        data = _display_status()
        return data.get("open_positions", [])


    @r.get("/api/market")
    def get_market():
        return {"movers": status.get().get("market_movers", [])}


    def _attach_signal_results(sigs):
        """Adds a `result` to every OPENED signal: what its trade did (open / closed + how + P&L).

        Comes from the permanent closed-trade record and the live open positions, matched by
        symbol + signal_no + open time. It does NOT use the Alerts list (that keeps only the last
        250 alerts, which made old signals look 'open' forever). No match -> state 'old'.
        """
        try:
            from collections import defaultdict
            closed = defaultdict(list)
            for t in trade_store.get_all_closed(5000, net=False):
                closed[(t.get("symbol"), t.get("signal_no"))].append(t)
            open_by = defaultdict(list)
            for pos in (status.get().get("open_positions") or []):
                open_by[(pos.get("symbol"), pos.get("signal_no"))].append(pos)
        except Exception:
            return sigs

        def near(trade_ts, rec_ts):
            # the trade opens right after the signal is saved: allow a small window around it
            if not trade_ts or not rec_ts:
                return False
            return -300 <= (float(trade_ts) - float(rec_ts)) <= 1800

        for s in sigs:
            if not s.get("opened"):
                continue
            key = (s.get("symbol"), s.get("signal_no"))
            rec = s.get("recorded_at")
            res = None
            for pos in open_by.get(key, []):
                if near(pos.get("opened_at_ts"), rec):
                    res = {"state": "open", "tp_hit_levels": list(pos.get("tp_hit_levels") or []),
                           "opened_ts": pos.get("opened_at_ts")}
                    break
            if res is None:
                for t in reversed(closed.get(key, [])):
                    if near(t.get("opened_at_ts"), rec):
                        reason = str(t.get("status") or "").replace("CLOSED_", "", 1)
                        try:
                            tag = paper_trader._exit_tag(reason, t)
                        except Exception:
                            tag = "OTHER"
                        res = {"state": "closed", "exit_tag": tag, "pnl": t.get("pnl_usdt"),
                               "target_level": t.get("target_level"),
                               "tp_hit_levels": list(t.get("tp_hit_levels") or []),
                               "opened_ts": t.get("opened_at_ts"), "closed_ts": t.get("closed_at_ts"),
                               "exit_px": t.get("exit_price"), "roi": t.get("roi_pct") or t.get("net_roi_pct")}
                        break
            s["result"] = res or {"state": "old"}
        return sigs


    @r.get("/api/signals")
    def get_signals(bot: str = "b1"):
        _mode = "LIVE" if settings_store.get("live_trading_enabled", False) else None   # LIVE account: real signals only
        # BTC has its own list and numbers (/api/btc/signals): the alt-coin list never includes it.
        return {"signals": _attach_signal_results(db.get_recent_signals(400, bot=_bot_arg(bot), mode=_mode, btc=False))}


    @r.get("/api/btc/live")
    def get_btc_live():
        """BTC live price (from the bot's own Binance push feed, REST fallback) + BTC's own today numbers. Light call: the
        Dashboard tile asks every second."""
        from recovered_bot import market_ws
        price, src, _err = market_ws.get_best_live_price(trade_store.BTC_SYMBOL)
        change = None
        try:
            live = market_ws.get_live(trade_store.BTC_SYMBOL)
            change = live.get("change_pct") if live else None
        except Exception:
            pass
        open_pnl, open_n = 0.0, 0
        try:
            for pos in (status.get().get("open_positions") or []):
                if str(pos.get("symbol")).upper() == trade_store.BTC_SYMBOL:
                    open_n += 1
                    open_pnl += float(pos.get("pnl_usdt") or pos.get("pnl") or 0.0)
        except Exception:
            pass
        st = trade_store.get_btc_stats()
        return {"price": price, "src": src, "change_pct": change, "today_pnl": st["today_pnl_usdt"],
                "today_trades": st["total_trades"], "open": open_n, "open_pnl": round(open_pnl, 4), "ts": time.time()}


    @r.get("/api/btc/signals")
    def get_btc_signals():
        """BTC only: its own signals + trades for Today / Yesterday / Day before (trading day = 5:30 AM IST),
        kept apart from the alt-coin numbers. Each day: signals, opened, skipped, won, lost, P&L."""
        _mode = "LIVE" if settings_store.get("live_trading_enabled", False) else None
        start = trade_store._trading_day_start_ts()
        sigs = _attach_signal_results(db.get_recent_signals(200, bot="b1", mode=_mode, btc=True))
        for s in sigs:
            try:
                no = int(s.get("signal_no") or 0)
                s["btc_no"] = no - trade_store.BTC_NO_BASE if no >= trade_store.BTC_NO_BASE else no
            except Exception:
                pass
        closed = trade_store.get_btc_closed_days(3)
        names = ["Today", "Yesterday", "Day before"]
        days = []
        for i in range(3):
            lo, hi = start - i * 86400, (start - (i - 1) * 86400) if i else float("inf")
            day_sigs = [s for s in sigs if lo <= float(s.get("recorded_at") or 0) < hi]
            opened = sum(1 for s in day_sigs if s.get("opened"))
            open_now = sum(1 for s in day_sigs if (s.get("result") or {}).get("state") == "open")
            c = closed[i]
            days.append({"name": names[i], "signals": len(day_sigs), "opened": opened, "skipped": len(day_sigs) - opened,
                         "open": open_now, "won": c["wins"], "lost": c["losses"], "pnl": c["pnl"]})
        keep = [s for s in sigs if float(s.get("recorded_at") or 0) >= start - 2 * 86400]
        return {"signals": keep, "days": days, "today": trade_store.get_btc_stats(),
                "margin": float(settings_store.get("btc_margin", 1000.0) or 1000.0),
                "leverage": int(settings_store.get("btc_leverage", 10) or 10)}


    @r.get("/api/daily-report")
    async def daily_report_endpoint():
        """Yesterday / today / last 7 days in plain English, rebuilt from the permanent trade archive (cannot disappear)."""
        from recovered_bot import daily_report
        return await _swr("daily_report", 20.0, daily_report.build, 7)

    return r


def make_router_history(bot_arg):
    """alerts, history, equity, calendar, candles."""
    r = APIRouter()
    _bot_arg = bot_arg

    @r.get("/api/alerts")
    def get_alerts():
        rows = status.get().get("alerts", [])
        if settings_store.get("live_trading_enabled", False):
            rows = [a for a in rows if status.alert_is_live(a)]
        return {"alerts": rows}


    @r.get("/api/history")
    def get_history(bot: str = "b1"):
        return {"trades": trade_store.get_recent_closed(50, bot=_bot_arg(bot), live_view=True)}


    @r.get("/api/equity")
    def get_equity(tf: str = "7d", bot: str = "b1"):
        """Dashboard equity curve. tf picks the bucketing:
        - 15m/1h/2h/1d -> fixed-size intraday windows (1d = last 24h in hourly buckets)
        - 3d/7d        -> calendar trading days, 5:30 AM IST boundary (get_equity_curve)
        Falls back to 7d on an unrecognised value instead of erroring."""
        intraday = {"15m": (15, 32), "1h": (60, 24), "2h": (120, 24), "1d": (60, 24)}
        daily = {"3d": 3, "7d": 7}
        if tf in intraday:
            minutes, buckets = intraday[tf]
            return {"curve": trade_store.get_equity_curve_intraday(minutes, buckets, bot=_bot_arg(bot)), "tf": tf}
        days = daily.get(tf, 7)
        return {"curve": trade_store.get_equity_curve(days, bot=_bot_arg(bot)), "tf": tf}


    @r.get("/api/calendar")
    def get_calendar(month: str = "", bot: str = "b1"):
        """Daily P&L calendar for one month (YYYY-MM, default this month). Closed trades only,
        after fee, same trading-day boundary as the Dashboard Today ring."""
        return trade_store.get_daily_calendar(month, bot=_bot_arg(bot))


    @r.get("/api/candles/{symbol}")
    async def get_candles(symbol: str, limit: int = 260, tf: str = None):
        """OHLC candles for the chart screen. Routed through exchange.py, which
        dispatches to Binance USDT-M Futures (the sole supported exchange).
        tf (optional): either a label ("1m"/"3m"/"5m"/"15m"/"1h" - what the
        Flutter app now sends, matching the configured Strategy Timeframe) or
        a bare number of minutes for backwards compatibility - both go through
        exchange.resolve_timeframe(). Defaults to 5m. Runs the blocking REST
        call in a thread so
        it doesn't stall the event loop the WebSocket also runs on.

        CANDLE/SD CONTRACT: default bumped 120 -> 260 to stay >= strategy.py's
        SD lookback (SMA200 + population stdev over the last 200 closes, see
        ABCDStrategy._rolling_mean_std) plus headroom for EMA50 warm-up -
        every current caller (candle_chart.dart's full sheet, app_provider.dart's
        own default) already requests >=200 explicitly, but this keeps the
        endpoint's own contract correct for any caller that omits limit,
        instead of silently under-supplying client-side SD/EMA math.

        include_forming=True: this is a UI/display endpoint only, so unlike
        every strategy call site (app.py, paper_trader.py's reconcile path -
        both call exchange.get_klines() directly with the default
        include_forming=False), the chart is allowed to see the still-forming
        candle as its last row. Signal generation never goes through this
        endpoint, so "closed candle only" for trading decisions is unaffected
        - this only changes what the chart itself is allowed to draw."""
        limit = max(2, min(int(limit), 1500))   # chart lazy-loads older history on pan; 1500 = ~5 days of 5m
        try:
            candles = await asyncio.to_thread(
                exchange.get_klines, symbol, None, limit, True, tf, True
            )
            return {"symbol": symbol, "candles": candles}
        except Exception as e:
            return {"symbol": symbol, "candles": [], "error": str(e)}

    return r
