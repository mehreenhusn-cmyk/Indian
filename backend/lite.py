"""lite.py - ONE switch for LITE mode (Round 1, 25 Nov 2026). Read README5 "PHONE LITE" first.

LITE mode keeps ONLY the current crypto bot (+ its scanner) and the Indian market runtime. Everything else is switched OFF on purpose, so the
phone stays cool and the app stays light:
  vision_ai, dual_lab, smart_brain, pa_layer, vol_layer, v2_runner, load_meters, memwatch, swr_prewarm, sniper (all routes + loops + the
  mounted v2 / lab / chop routes), ping_worker.
Telegram is NOT switched off any more (26 Nov 2026, owner's request): the current bot and India send to Telegram exactly as before.
The Pump / Dump scanner (pd_runner.py, api/pd_route.py) is the ONE new background job the owner asked for in LITE; it is not a lite-off feature
(its own switch is in the app, or OWL_PUMPDUMP=0 for the backend).
Nothing is deleted: the code and all trade data stay in the repo / data folder. LITE is ON by default.
Turn LITE off for a test only with the environment variable OWL_LITE=0 (never by deleting a guard).

Use in code:   import lite;   if not lite.off("dual_lab"):  start it
off(name) is True when LITE is on (= do NOT start it) and prints ONE line per name. GET /api/lite shows what was kept off.
Rule for every Claude: do not re-enable a switched-off feature unless the owner says so in plain words."""
import os
import threading

VERSION = "lite 2 (Round 1 + Telegram back + PD scanner allowed, 26 Nov 2026)"
_skipped = []
_lock = threading.Lock()


def is_lite():
    v = os.environ.get("OWL_LITE")
    if v is None:
        return True                      # default: LITE is ON
    return str(v).strip().lower() not in ("0", "false", "off", "no")


def off(name):
    """True = LITE is on, the feature `name` must NOT start. Logs one line the first time per name."""
    if not is_lite():
        return False
    with _lock:
        if name not in _skipped:
            _skipped.append(name)
            print(f"[lite] {name} stays OFF (LITE mode; OWL_LITE=0 turns LITE off)")
    return True


def summary():
    """For GET /api/lite and the owner's check."""
    return {"lite": is_lite(), "version": VERSION, "env_OWL_LITE": os.environ.get("OWL_LITE"), "kept_off": list(_skipped)}
