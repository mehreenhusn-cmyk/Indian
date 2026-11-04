"""api/dual.py - Lab, Dual Bot, archive, layers and Smart Brain routes, moved out of api_server.py (NEXT-6c).

filter_lab, variant_lab, doctor_*, health_meter, scoreboard, scan_lab, tag_lab, dual_lab (+ report), archive (+ check / export),
dual_desk, dual_universe, layers (pa / vol), smart_brain. Same code, same paths, same order.
api_server.py includes this router at the exact place the routes used to be.
"""
import asyncio
import time

from fastapi import APIRouter

from recovered_bot import trade_store
from api.swr import _swr, _TIMING, _HEAVY_NOW


def make_router(safe_status):
    """safe_status(mod) = api_server._safe_status (passed in, it is defined later in api_server.py)."""
    r = APIRouter()

    @r.get("/api/filter_lab")
    async def filter_lab_page(tf: str = "5m", days: int = 7, restart: int = 0):
        """Filter Lab (filter_lab.py): replays the bot's own strategy on Binance candles and tests Z / TSI / chop / reward
        filters on older vs newer signals. Plain text for the phone browser. One-shot, own thread, read-only."""
        from fastapi.responses import PlainTextResponse
        try:
            import filter_lab
            return PlainTextResponse(filter_lab.job_status(tf, max(1, min(days, 30)), restart=bool(restart)))
        except Exception as e:
            return PlainTextResponse(f"Filter Lab is not available: {type(e).__name__}: {e}")


    @r.get("/api/filter_lab_all")
    async def filter_lab_all(start: int = 0, restart: int = 0, days: int = 7):
        """App button: start=1 runs 3m, 5m and 15m one after the other; without start it only reports the progress (JSON). Read-only replay."""
        try:
            import filter_lab
            if start:
                filter_lab.start_all(max(1, min(days, 30)), restart=bool(restart))
            return filter_lab.status_all()
        except Exception as e:
            return {"running": False, "error": f"{type(e).__name__}: {e}", "tfs": {}}


    @r.get("/api/variant_lab")
    async def variant_lab_api(start: int = 0, days: int = 14):
        """Strategy Lab (variant_lab.py): the bot's own signals replayed under many scenarios (wider SL, hold till opposite signal, TSI/Z,
        Bollinger, EMA bands ...) and compared with the bot, older vs newer data. start=1 runs 3m, 5m, 15m in one background thread.
        Without start it only returns the saved result / progress (JSON). Read-only, never touches trading."""
        try:
            import variant_lab
            if start:
                variant_lab.start(max(3, min(days, 30)))
            return variant_lab.status()
        except Exception as e:
            return {"running": False, "error": f"{type(e).__name__}: {e}", "tfs": {}}


    @r.get("/api/doctor_summary")
    async def doctor_summary_api():
        """Top 3 plain actions for the Strategy Doctor screen (doctor_extra.py). Read-only, uses the cached Doctor + scoreboard."""
        try:
            import doctor_extra, scoreboard
            from recovered_bot import strategy_doctor
            d = await _swr("doctor", 60.0, strategy_doctor.build, 5000)
            b = await _swr("scoreboard", 20.0, scoreboard.build, 5000)
            out = doctor_extra.summary(d, b)
            try:                                           # chips for the timeframe / coin filter
                out["options"] = doctor_extra.options(await asyncio.to_thread(trade_store.get_all_closed, 5000, True))   # file parse off the event loop
            except Exception:
                out["options"] = {"tfs": [], "coins": []}
            return out
        except Exception as e:
            return {"ok": False, "actions": [], "error": f"{type(e).__name__}: {e}"}


    @r.get("/api/doctor_filter")
    async def doctor_filter_api(tf: str = "", coin: str = ""):
        """Strategy Doctor for ONE timeframe and/or ONE coin (doctor_extra.py). Read-only."""
        import doctor_extra
        return await asyncio.to_thread(doctor_extra.filtered, tf, coin, 5000)


    @r.get("/api/health_meter")
    async def health_meter_api():
        """OK / SLOW + plain lines (doctor_extra.py). Cheap: reads the timings the server already keeps."""
        import doctor_extra
        now = time.time()
        held = round(now - _HEAVY_NOW["since"], 1) if _HEAVY_NOW["key"] else 0.0
        return doctor_extra.health(_TIMING, _HEAVY_NOW["key"], held, safe_status("ai_cpu_meter"))


    @r.get("/api/scoreboard")
    async def scoreboard_api():
        """Final Scoreboard (scoreboard.py): one verdict per idea, Strategy Lab replay (3m/5m/15m) + the bot's saved closed trades side by side.
        Read-only: it only reads the saved Strategy Lab result and the trade archive. Never touches trading."""
        try:
            import scoreboard
            return await _swr("scoreboard", 20.0, scoreboard.build, 5000)
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "groups": [], "headline": []}


    @r.get("/api/scan_lab")
    async def scan_lab_api(start: str = ""):
        """Scan Lab (scan_lab.py): entry line (EMA30/50, SMA30/50, mean), timeframe 3m-2h, fixed majors vs movers, SD-band support/resistance.
        start=quick (majors, 15m/1h/2h), start=full (all, slow) or start=sd (SD length 200 vs 100/150/50) runs it in one background thread. Without start it only returns the saved
        short answer / progress (JSON). Read-only, never touches trading."""
        try:
            import scan_lab
            if start in ("quick", "full", "sd"):
                scan_lab.start(start)
            return scan_lab.status()
        except Exception as e:
            return {"running": False, "error": f"{type(e).__name__}: {e}", "summary": None}


    @r.get("/api/tag_lab")
    async def tag_lab_api(start: str = "", tf: str = "5m", days: int = 7):
        """Tag Lab (tag_lab.py): which combination of the main chart signal + the Z candle / TSI / ZSM tags makes money, which exit suits it, and a luck check.
        start=run starts one test (own low-priority process, 3m/5m/15m, 1-14 days). Without start it only returns the saved result + progress.
        Plain code, no AI key. Read-only, never touches trading."""
        try:
            import tag_lab
            if start == "run":
                await asyncio.to_thread(tag_lab.start, tf, days)
            return await asyncio.to_thread(tag_lab.status, tf)
        except Exception as e:
            return {"running": False, "error": f"{type(e).__name__}: {e}", "result": None}


    @r.get("/api/dual_lab")
    async def dual_lab_api(action: str = ""):
        """Dual Bot (dual_lab.py): paper bot that reads BOTH indicators and learns by itself (no AI key). Runs as its own low-priority process.
        action=start / stop switches it. Only reads one small file, so it never slows the live bot."""
        try:
            import dual_lab
            if action == "start":
                dual_lab.set_enabled(True)
            elif action == "stop":
                dual_lab.set_enabled(False)
            await asyncio.to_thread(dual_lab.ensure_running)
            view = await asyncio.to_thread(dual_lab.status)
            try:
                import dual_today                                   # R16a: the Dual screen's "Today" comes from the permanent archive too (dual_lab keeps only 600 trades)
                return await asyncio.to_thread(dual_today.overlay, view)
            except Exception:
                return view
        except Exception as e:
            return {"running": False, "enabled": False, "error": f"{type(e).__name__}: {e}"}


    @r.get("/api/archive")
    async def archive_api():
        """Long-term archive (trade_archive.py): how many trades and learning rows are saved for ever, and when the last save was. Read-only, small."""
        try:
            import trade_archive
            return await asyncio.to_thread(trade_archive.status)
        except Exception as e:
            return {"state": "error", "text": f"Archive problem: {type(e).__name__}: {e}"}


    @r.get("/api/dual_desk")
    async def dual_desk_api():
        """Dual Bot desk (dual_desk.py): today's finished / open trades split by source (today / 7-day names) and 5m / 15m, from the archive. Small, read-only."""
        try:
            import dual_desk
            return await asyncio.to_thread(dual_desk.desk)
        except Exception as e:
            return {"state": "error", "err": f"{type(e).__name__}: {e}"}


    @r.get("/api/archive_check")
    async def archive_check_api():
        """Does the archive hold every finished trade of the JSON file (archive_tools.check)? Read-only, small."""
        try:
            import archive_tools
            return await asyncio.to_thread(archive_tools.check)
        except Exception as e:
            return {"state": "error", "text": f"Archive check error: {type(e).__name__}: {e}"}


    @r.get("/api/archive_export")
    async def archive_export_api(days: int = 0, all_states: int = 0):
        """Finished trades of the archive as a CSV file (open it in the phone browser). days=N = last N days, all_states=1 = open trades too."""
        try:
            import archive_tools
            from fastapi.responses import Response
            text = await asyncio.to_thread(archive_tools.export_csv, None, days or None, not all_states)
            return Response(text, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=owl_archive.csv"})
        except Exception as e:
            return {"state": "error", "text": f"Archive export error: {type(e).__name__}: {e}"}


    @r.get("/api/archive_export_save")
    async def archive_export_save():
        """App button (More > Downloads): writes owl_trades_<date>.csv into the phone Download folder. Same CSV as /api/archive_export."""
        try:
            import os, archive_tools
            from datetime import datetime
            from recovered_bot import ai_report
            text = await asyncio.to_thread(archive_tools.export_csv, None, None, True)
            name = "owl_trades_" + datetime.now().strftime("%Y%m%d_%H%M") + ".csv"
            for d in ai_report._download_dirs():
                if os.path.isdir(d) and os.access(d, os.W_OK):
                    path = os.path.join(d, name)
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(text)
                    return {"ok": True, "path": path, "bytes": len(text.encode("utf-8")), "hint": ""}
            return {"ok": False, "path": "", "bytes": len(text.encode("utf-8")), "hint": "No Download folder found. Use Share or Copy instead."}
        except Exception as e:
            return {"ok": False, "path": "", "bytes": 0, "hint": f"CSV export failed: {type(e).__name__}: {e}"}


    @r.get("/api/dual_universe")
    async def dual_universe_api():
        """Dual Bot coin sources (universe_7d.py): which 7-day lists are saved, the cap, the last error. Read-only, small."""
        try:
            import universe_7d
            return await asyncio.to_thread(universe_7d.status)
        except Exception as e:
            return {"days": [], "err": f"{type(e).__name__}: {e}"}


    @r.get("/api/layers/pa")
    async def pa_layer_api():
        """Price Action Light (pa_layer.py): what it logged and how its reading of the Dual Bot trades did. Reads one small file."""
        try:
            import pa_layer
            await asyncio.to_thread(pa_layer.ensure_running)
            return await asyncio.to_thread(pa_layer.status)
        except Exception as e:
            return {"running": False, "report": None, "error": f"{type(e).__name__}: {e}"}


    @r.get("/api/layers/vol")
    async def vol_layer_api():
        """Volume Context (vol_layer.py): what it logged and how its reading of the Dual Bot trades did. Reads one small file."""
        try:
            import vol_layer
            await asyncio.to_thread(vol_layer.ensure_running)
            return await asyncio.to_thread(vol_layer.status)
        except Exception as e:
            return {"running": False, "report": None, "error": f"{type(e).__name__}: {e}"}


    @r.get("/api/smart_brain")
    async def smart_brain_api(action: str = ""):
        """Smart Brain (smart_brain.py): scores and explains Dual Bot setups. Only reads one small file; never touches Dual Bot v1.
        action=start / stop switches the Brain only."""
        try:
            import smart_brain
            if action == "start":
                smart_brain.set_enabled(True)
            elif action == "stop":
                smart_brain.set_enabled(False)
            elif action == "gate_on":
                smart_brain.set_gate(True)
            elif action == "gate_off":
                smart_brain.set_gate(False)
            await asyncio.to_thread(smart_brain.ensure_running)
            return await asyncio.to_thread(smart_brain.status)
        except Exception as e:
            return {"running": False, "enabled": False, "state": "error", "state_text": "Smart Brain error", "error": f"{type(e).__name__}: {e}",
                    "signals": [], "hours": [], "repeat_loss": [], "patterns": [], "bands": [], "watch": [], "trust": {}}


    @r.get("/api/dual_lab/report")
    async def dual_lab_report():
        """Dual Bot report as text (dual_lab.build_report): every trade, the retest check, setups, lessons. Read-only."""
        from fastapi.responses import PlainTextResponse
        try:
            import dual_lab
            txt = await asyncio.to_thread(dual_lab.build_report)
        except Exception as e:
            txt = f"Dual Bot report failed: {type(e).__name__}: {e}"
        return PlainTextResponse(txt, headers={"Content-Disposition": 'attachment; filename="owl_dualbot_report.txt"'})


    @r.get("/api/dual_lab/report_save")
    async def dual_lab_report_save():
        """App button: writes owl_dualbot_report_<date>.txt into the phone Download folder."""
        try:
            import dual_lab
            return await asyncio.to_thread(dual_lab.save_report)
        except Exception as e:
            return {"ok": False, "path": "", "bytes": 0, "hint": f"Dual Bot report failed: {type(e).__name__}: {e}"}

    return r
