"""api/v2_verdict_views.py - Round 3: the `verdicts` route of the V2 data API = one verdict card per study (see v2_verdicts.py for the card schema and the rules).
Same pattern as api/v2_brain_views.py: a read-only view(con, params, now, data_dir) -> dict; api/v2_data.py merges VIEWS and answers the names in NAMES without a market-store
connection (v2_verdicts opens the store itself, mode=ro, and works without it). Token check and the v2_api_enabled switch stay in v2_data.py. No network, no write, no trading import."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import v2_verdicts as VD


def v_verdicts(con, p, now, d):
    """Round 3: GET /api/v2/verdicts -> {ready, cards, counts, made_utc, note}. One card per study; a study that fails becomes a NOT_ENOUGH_DATA card, never an error. Read-only."""
    return VD.build(d, now)


VIEWS = {"verdicts": v_verdicts}
NAMES = tuple(VIEWS)
