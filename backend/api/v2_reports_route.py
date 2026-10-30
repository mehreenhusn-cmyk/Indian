"""api/v2_reports_route.py - Part 62: REPORTS 2 of 3 - ONE read-only route GET /api/v2/fees_tax for the Part 61 fees + tax report (backend half; the screen is frontend/lib/screens/reports_screen.dart).
It calls v2_reports.build_report() and sends the answer through the Part 5 redaction (scrub + secret check) before it leaves. It only READS the closed-trade files, writes nothing, changes no setting,
touches no position or order. Same switch as the other V2 routes: OFF (404 "off") until the file v2_api_enabled exists in the data folder. Behind the app's own token check.
The list of source files (sources) is NOT sent to the app (it is in the Part 61 JSON file only). A problem = a short fixed text (no path, no traceback). Mounted by api_server.py after the owner's ok.
Tests: python3 test/test_v2_reports_route.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import v2_inv_redact as R
import v2_reports as RP
from api import v2_data as D

VERSION = "v2_reports_route 1 (Part 62)"
PATH = "/api/v2/fees_tax"


def answer(data_dir, fee_roi=1.0, build=None):
    """-> (http status, body dict). Never raises."""
    if not D.api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    try:
        rep = (build or RP.build_report)(data_dir, fee_roi)
        if not isinstance(rep, dict) or rep.get("error"):
            return 503, {"error": "the trade files could not be read"}
        rep = {k: v for k, v in rep.items() if k != "sources"}
        return 200, json.loads(R.safe_report(rep))
    except R.RedactionFailed:
        return 503, {"error": "the report was refused: secret-looking text"}
    except Exception:
        return 503, {"error": "the report could not be made right now"}


def make_router(require_api_token, data_dir):
    """Mounted by api_server.py (after the owner's ok): 1 GET route behind the token check."""
    import asyncio
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_fees_tax():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)
    return r
