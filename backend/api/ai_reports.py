"""api/ai_reports.py - the 4 report routes (/api/report/save, /app, /app_save, /api/report), moved out of api_server.py (NEXT-6i). Same code, same paths, same order.
"""
import asyncio

from fastapi import APIRouter


def make_router_reports():
    """Plain-text reports (download + save)."""
    r = APIRouter()

    @r.get("/api/report/save")
    async def report_save():
        """App button: writes owl_report_<date>.txt into the phone's Download folder (see ai_report.save_to_downloads)."""
        try:
            from recovered_bot import ai_report
            return await asyncio.to_thread(ai_report.save_to_downloads)
        except Exception as e:
            return {"ok": False, "path": "", "bytes": 0, "hint": f"Report failed: {type(e).__name__}: {e}"}


    @r.get("/api/report/app")
    async def app_report():
        """Whole-app report text (ai_report.build_app_text): what the app is, dashboard, signals, alerts, AI, backend health, settings (no keys), known problems."""
        from fastapi.responses import PlainTextResponse
        try:
            from recovered_bot import ai_report
            txt = await asyncio.to_thread(ai_report.build_app_text)
        except Exception as e:
            txt = f"Report failed: {type(e).__name__}: {e}"
        return PlainTextResponse(txt, headers={"Content-Disposition": 'attachment; filename="owl_app_report.txt"'})


    @r.get("/api/report/app_save")
    async def app_report_save():
        try:
            from recovered_bot import ai_report
            return await asyncio.to_thread(ai_report.save_app_to_downloads)
        except Exception as e:
            return {"ok": False, "path": "", "bytes": 0, "hint": f"Report failed: {type(e).__name__}: {e}"}


    @r.get("/api/report")
    async def full_report():
        """ONE downloadable text file (ai_report.py): strategy, indicators, settings (no secrets), Doctor summary, Filter Lab results and the
        closed-trades table - to send to any AI. Read-only."""
        from fastapi.responses import PlainTextResponse
        try:
            from recovered_bot import ai_report
            txt = await asyncio.to_thread(ai_report.build_text)
        except Exception as e:
            txt = f"Report failed: {type(e).__name__}: {e}"
        return PlainTextResponse(txt, headers={"Content-Disposition": 'attachment; filename="owl_report.txt"'})

    return r
