"""india_api.py - REST routes for the India paper mode (/api/india/*).
Added to api_server.py with two lines; reuses its token guard. Independent of the
crypto routes."""
from typing import Optional

import asyncio
import json
import os

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse


def make_router(require_api_token, data_dir):
    from recovered_bot.india_runtime import get_runtime
    r = APIRouter(prefix="/api/india")

    def rt():
        return get_runtime(data_dir)

    @r.get("/status")
    def status(_a=Depends(require_api_token)):
        return rt().status()

    @r.get("/positions")
    def positions(_a=Depends(require_api_token)):
        return {"positions": rt().positions()}

    @r.get("/ticks")
    def ticks(opt: Optional[str] = None, _a=Depends(require_api_token)):
        """Live index + optional option LTPs (tiny, lock-free). opt=comma symbols, capped 40."""
        return rt().ticks(opt=opt)

    # ---- Part 7: live price PUSH. The app opens one socket and gets prices without asking every 0.8 s. -----
    def _strip(o):
        """Drop the keys that change on every look (ages / clocks) so only real price moves count as 'changed'."""
        if isinstance(o, dict):
            return {k: _strip(v) for k, v in o.items() if k not in ("age_ms", "at", "now", "speed")}
        return o

    @r.websocket("/ws_ticks")
    async def ws_ticks(ws: WebSocket):
        tok = os.environ.get("API_TOKEN", "").strip()
        if tok and ws.query_params.get("token", "") != tok:
            await ws.close(code=4401)
            return
        await ws.accept()
        syms = []

        async def reader():
            nonlocal syms
            try:
                while True:
                    m = json.loads(await ws.receive_text())
                    if isinstance(m, dict) and isinstance(m.get("opt"), list):
                        syms = [str(x) for x in m["opt"] if str(x).strip()][:40]
            except Exception:
                return

        rtask = asyncio.create_task(reader())
        last_sig, last_sent = None, 0.0
        try:
            import time as _t
            while not rtask.done():
                d = rt().ticks(opt=list(syms))  # lock-free, reads the price the broker socket already pushed
                sig = json.dumps(_strip(d), sort_keys=True, default=str)
                now = _t.time()
                # send the moment a price changed; otherwise a 1 s heartbeat keeps ages / speed fresh
                if sig != last_sig or now - last_sent >= 1.0:
                    await ws.send_text(json.dumps(d, default=str))
                    last_sig, last_sent = sig, now
                await asyncio.sleep(0.15)
        except (WebSocketDisconnect, RuntimeError):
            pass
        except Exception:
            pass
        finally:
            rtask.cancel()

    @r.get("/candles")
    def candles(underlying: str = "NIFTY", limit: int = 150, tf: Optional[int] = None,
                _a=Depends(require_api_token)):
        try:
            return rt().candles(underlying, max(10, min(limit, 800)), tf)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @r.get("/option_candles")
    def option_candles(key: str, limit: int = 300, tf: Optional[int] = None,
                       _a=Depends(require_api_token)):
        try:
            return rt().option_candles(key, max(10, min(limit, 800)), tf)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @r.get("/trades")
    def trades(limit: int = 100, _a=Depends(require_api_token)):
        return {"trades": rt().trades(max(1, min(limit, 500)))}

    @r.get("/stats")
    def stats(_a=Depends(require_api_token)):
        """Stats tab: win rate, R:R, expectancy, drawdown, equity curve (india_stats.py)."""
        return rt().stats()

    @r.get("/doctor")
    def doctor(_a=Depends(require_api_token)):
        """Strategy Doctor for India trades (read-only, india_doctor.py)."""
        return rt().doctor()

    @r.post("/start")
    def start(_a=Depends(require_api_token)):
        rt().start()
        return rt().status()

    @r.post("/stop")
    def stop(_a=Depends(require_api_token)):
        rt().stop()
        return rt().status()

    @r.post("/reset")
    def reset(_a=Depends(require_api_token)):
        rt().reset()
        return rt().status()

    @r.post("/close_all")
    def close_all(_a=Depends(require_api_token)):
        return {"closed": rt().close_all()}

    @r.post("/close/{pos_id}")
    def close_one(pos_id: int, _a=Depends(require_api_token)):
        res = rt().close_one(pos_id)
        if res is None:
            raise HTTPException(status_code=404, detail="position not found")
        return {"closed": res}

    @r.get("/settings")
    def get_settings(_a=Depends(require_api_token)):
        return rt().settings

    @r.post("/settings")
    def set_settings(payload: dict, _a=Depends(require_api_token)):
        try:
            return rt().update_settings(payload)
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.get("/chain")
    def chain(underlying: str = "NIFTY", expiry: Optional[str] = None, width: int = 10,
              _a=Depends(require_api_token)):
        try:
            return rt().chain(underlying, expiry, max(3, min(width, 25)))
        except (ValueError, KeyError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/pin")
    def pin(payload: dict, _a=Depends(require_api_token)):
        try:
            spec = {k: v for k, v in payload.items() if k not in ("underlying", "side")}
            return {"pins": rt().set_pin(payload["underlying"], payload["side"], spec)}
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/pin/clear")
    def pin_clear(payload: dict = None, _a=Depends(require_api_token)):
        payload = payload or {}
        return {"pins": rt().clear_pins(payload.get("underlying"), payload.get("side"))}

    @r.post("/day_mode")
    def day_mode(payload: dict, _a=Depends(require_api_token)):
        try:
            return rt().set_day_mode(payload.get("mode"), int(payload.get("depth", 1)))
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.get("/report")
    def report(start: Optional[str] = None, end: Optional[str] = None,
               underlying: Optional[str] = None, period: Optional[str] = None,
               _a=Depends(require_api_token)):
        try:
            return rt().report(start, end, underlying, period)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.get("/trades.csv")
    def trades_csv(start: Optional[str] = None, end: Optional[str] = None,
                   underlying: Optional[str] = None, period: Optional[str] = None,
                   _a=Depends(require_api_token)):
        return PlainTextResponse(rt().trades_csv(start, end, underlying, period), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=india_trades.csv"})

    # ---- broker connect (Part 1: works with any registered broker) ----
    @r.get("/broker")
    def broker(_a=Depends(require_api_token)):
        return rt().broker_info()

    @r.post("/broker/connect")
    def broker_connect(payload: dict, _a=Depends(require_api_token)):
        from recovered_bot.india_broker import BrokerError
        name = str(payload.get("broker", "")).lower()
        creds = payload.get("creds") or None       # None = use the saved key
        try:
            return rt().connect_broker(name, creds)
        except BrokerError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/broker/balance")
    def broker_balance(payload: dict, _a=Depends(require_api_token)):
        from recovered_bot.india_broker import BrokerError
        try:
            return rt().refresh_balance(str(payload.get("broker", "")).lower())
        except BrokerError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/broker/login_url")
    def broker_login_url(payload: dict, _a=Depends(require_api_token)):
        from recovered_bot.india_broker import BrokerError
        try:
            return rt().broker_login_url(str(payload.get("broker", "")).lower(),
                                         payload.get("app_id"), payload.get("redirect_url"))
        except BrokerError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @r.post("/broker/disconnect")
    def broker_disconnect(_a=Depends(require_api_token)):
        return rt().disconnect_broker()

    @r.post("/broker/forget")
    def broker_forget(payload: dict, _a=Depends(require_api_token)):
        return rt().forget_broker(str(payload.get("broker", "")).lower())

    # ---- India Telegram signals (token / chat id are saved on the server, never returned in full) ----
    def tg():
        t = rt().tg
        if t is None:
            raise HTTPException(status_code=503, detail="India Telegram is not available")
        return t

    @r.get("/telegram")
    def telegram_info(_a=Depends(require_api_token)):
        return tg().info()

    @r.post("/telegram")
    def telegram_save(payload: dict, _a=Depends(require_api_token)):
        try:
            tg().save_creds(payload.get("bot_token"), payload.get("chat_id"))
            patch = {k: payload[k] for k in ("tg_enabled", "tg_tf") if k in payload}
            if "enabled" in payload:
                patch["tg_enabled"] = payload["enabled"]
            if "tf" in payload:
                patch["tg_tf"] = payload["tf"]
            if patch:
                rt().update_settings(patch)
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return tg().info()

    @r.post("/telegram/test")
    def telegram_test(_a=Depends(require_api_token)):
        ok, msg = tg().send_test()
        return {"ok": ok, "message": msg, **tg().info()}

    @r.post("/telegram/demo")
    def telegram_demo(_a=Depends(require_api_token)):
        ok, msg = tg().send_demo_signal()
        return {"ok": ok, "message": "Demo signal sent" if ok else msg, **tg().info()}

    @r.post("/telegram/check")
    def telegram_check(_a=Depends(require_api_token)):
        ok, msg = tg().check_token()
        return {"ok": ok, "message": msg, **tg().info()}

    @r.post("/telegram/find_chat")
    def telegram_find_chat(_a=Depends(require_api_token)):
        ok, msg = tg().find_chat()
        return {"ok": ok, "message": msg, **tg().info()}

    @r.post("/telegram/forget")
    def telegram_forget(_a=Depends(require_api_token)):
        tg().forget()
        return tg().info()

    return r
