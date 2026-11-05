"""owl_sniper_eva_hook.py - Part 17a: the WIRE between a Sniper paper trade and EVA (expected vs actual, owl_sniper_eva.py). PAPER ONLY, no order code, nothing is paused or changed.
When a Sniper paper trade opens, owl_sniper_paper.py calls freeze_async(). This file then asks the Risk Box (owl_sniper_riskbox.for_symbol) what the past says for this setup and FREEZES that answer into v2_sniper_eva.json
(owl_sniper_eva.record_expected: first write wins, only a Risk Box with state OK is saved, never a made-up number).
Speed: the Risk Box pool is slow to build on a phone, so (1) the work runs in its OWN daemon thread (the paper loop never waits) and (2) the pool is kept in memory for POOL_TTL seconds and shared by every trade.
Honest limit: the Risk Box reads the newest saved candle at the moment the thread runs, so if the pool had to be built first (a few seconds) the box can be one candle newer than the entry. Never raises.
API: freeze(d, order, now=None) -> True if saved; freeze_async(d, order, now=None) -> starts the thread; lane_of(order) -> EXPLORE / LEARN / REAL (same rule as owl_sniper_record)."""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "owl_sniper_eva_hook 1 (Part 17a)"
INTERVAL = "5m"
POOL_TTL = 1800.0                     # the Risk Box pool is rebuilt at most every 30 minutes
_POOL = {"t": 0.0, "pool": None}
_LOCK = threading.Lock()              # one pool build at a time; other entries wait for it, then reuse it


def lane_of(order):
    import owl_sniper_learn as LN
    o = order or {}
    return "EXPLORE" if o.get("xp") else ("LEARN" if o.get("tag") == LN.TAG else "REAL")


def _pool(d, now):
    with _LOCK:
        if _POOL["pool"] is not None and now - _POOL["t"] < POOL_TTL:
            return _POOL["pool"]
        import owl_sniper_bridge_learn as BL
        import owl_sniper_riskbox as RB
        ex = BL.load_examples(d, 2000)[0]
        pool = RB.build_pool(ex)
        pool["reports"] = RB.build_reports(ex, now)
        _POOL["t"], _POOL["pool"] = now, pool
        return pool


def freeze(d, order, now=None):
    """Risk Box for this order's coin + side -> frozen expectation. False when there is no order id, no Risk Box OK, or anything fails."""
    try:
        import owl_sniper_eva as EVA
        import owl_sniper_riskbox as RB
        o = order or {}
        if not o.get("id") or not o.get("symbol"):
            return False
        now = time.time() if now is None else now
        box = RB.for_symbol(d, o["symbol"], INTERVAL, o.get("side"), float(o.get("invest_usdt") or 10.0), float(o.get("leverage") or 1.0), pool=_pool(d, now), now=now)
        return EVA.record_expected(d, o["id"], box, lane_of(o), now)
    except Exception:
        return False


def freeze_async(d, order, now=None):
    """Start the freeze in a daemon thread. Never raises, never blocks the paper loop."""
    try:
        threading.Thread(target=freeze, args=(d, dict(order or {}), now), name="owl-sniper-eva", daemon=True).start()
        return True
    except Exception:
        return False
