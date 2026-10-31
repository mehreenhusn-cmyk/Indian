"""api/v2_ledger_route.py - Part 41: KNOWLEDGE LEDGER 3 of 4 - read-only routes for the Ledger screen (Part 42).
  GET /api/v2/ledger                       -> newest version of every finding (sample size AND denominator on each), status words, what changed since the last review
  GET /api/v2/ledger/{finding_id}?version=N -> all versions of one finding (kept, failed ones too) with a diff between neighbours + the trace chain of version N (default newest) with its GAPS
Reads v2_ledger.db (Parts 39 + 40) opened READ-ONLY (mode=ro): it creates no file, no table, writes nothing, changes no setting, touches no position or order, imports no trading code, no network.
Same switch as the other V2 routes: OFF (404) until the file v2_api_enabled exists in the data folder; behind the app's own token check. No ledger file yet = a normal EMPTY answer (not an error).
The answer goes through the Part 5 redaction before it leaves. A problem = a short fixed text (no path, no traceback). Lists are capped (200 findings, 50 versions, 500 chain items; the answer says when it cut).
The findings are NOT ranked by win rate (README 9.8). NOT mounted yet: api_server.py needs the owner's ok for the 6-line block (Part 41 reply has it)."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import v2_inv_redact as R
import v2_ledger as L
import v2_ledger_trace as T
from api import v2_data as D

VERSION = "v2_ledger_route 1 (Part 41)"
PATH = "/api/v2/ledger"
ID_RE = re.compile(r"^F-\d{4,8}$")
CAP_FINDINGS, CAP_VERSIONS, CAP_ITEMS = 200, 50, 500


def _clean(body):
    return json.loads(R.safe_report(json.loads(json.dumps(body, default=str))))


def answer(data_dir, finding_id=None, version=None):
    """-> (http status, body dict). Never raises."""
    if not D.api_enabled(data_dir):
        return 404, {"enabled": False, "note": "the V2 data API is off"}
    try:
        if finding_id is None:
            try:
                rows, ch = L.latest(data_dir, True), L.changes_since_review(data_dir, True)
            except FileNotFoundError:
                return 200, _clean({"tool": VERSION, "findings": [], "statuses": list(L.STATUSES), "note": "the ledger is empty: nothing stored yet"})
            cut = len(rows) > CAP_FINDINGS
            return 200, _clean({"tool": VERSION, "read_only": True, "statuses": list(L.STATUSES), "findings": rows[:CAP_FINDINGS], "cut": cut,
                                "changes_since": ch["since"], "changes": ch["changes"][:CAP_FINDINGS],
                                "note": "not ranked by win rate; every result shows sample_size and its denominator"})
        if not ID_RE.match(finding_id):
            return 400, {"error": "bad finding id"}
        try:
            hist = L.history(data_dir, finding_id, True)
        except FileNotFoundError:
            hist = []
        if not hist:
            return 404, {"error": "no such finding"}
        diffs = [{"version": b["version"], "changed": L.diff(a, b)} for a, b in zip(hist, hist[1:])]
        chain = T.trace(data_dir, finding_id, version, True)
        if chain.get("error"):
            return 404, {"error": "no such version"}
        items = chain.get("items", [])
        chain["items"], chain["items_cut"] = items[:CAP_ITEMS], len(items) > CAP_ITEMS
        return 200, _clean({"tool": VERSION, "read_only": True, "finding_id": finding_id, "versions": hist[-CAP_VERSIONS:],
                            "versions_cut": len(hist) > CAP_VERSIONS, "diffs": diffs[-CAP_VERSIONS:], "chain": chain})
    except R.RedactionFailed:
        return 503, {"error": "the answer was refused: secret-looking text"}
    except Exception:
        return 503, {"error": "the ledger could not be read right now"}


def make_router(require_api_token, data_dir):
    """Mounted by api_server.py (after the owner's ok): 2 GET routes behind the token check."""
    import asyncio
    from typing import Optional
    from fastapi import APIRouter, Depends
    from fastapi.responses import JSONResponse
    r = APIRouter()

    @r.get(PATH, dependencies=[Depends(require_api_token)])
    async def v2_ledger():
        st, body = await asyncio.to_thread(answer, data_dir)
        return JSONResponse(body, status_code=st)

    @r.get(PATH + "/{finding_id}", dependencies=[Depends(require_api_token)])
    async def v2_ledger_one(finding_id: str, version: Optional[int] = None):
        st, body = await asyncio.to_thread(answer, data_dir, finding_id, version)
        return JSONResponse(body, status_code=st)
    return r
