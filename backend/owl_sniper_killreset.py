"""owl_sniper_killreset.py - OwlSniper LEARN kill switch DAILY AUTO-RESET (R3 follow-up). PAPER ONLY. Edits only the LEARN state file (v2_sniper_learn state), through owl_sniper_learn's own load / save.
Problem: the LEARN kill switch (0.5 USDT lost in one UTC day) stayed ON until the owner ran reset_kill, so exploring stopped for days.
Rule: a kill that was switched on BY THE DAILY LOSS LIMIT is switched off again when a NEW UTC day starts. A kill with any other reason (the owner's own switch) is NEVER touched. The reset is written to the LEARN log.
The daily loss limit itself stays: if the new day loses 0.5 USDT again, the switch trips again. The REAL gate's kill switch (owl_sniper_exec) is not touched.
API: maybe_reset(d, now=None) -> True when a reset was made. Never raises."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_learn as LN

VERSION = "owl_sniper_killreset 1"
AUTO_REASON = "daily LEARN loss limit reached"          # the exact text owl_sniper_learn.record_close writes when the limit trips


def maybe_reset(d, now=None):
    now = time.time() if now is None else now
    try:
        s = LN._load(d)
        k = s.get("kill") or {}
        if not k.get("on") or k.get("reason") != AUTO_REASON or s.get("day") == LN._day(now):
            return False
        s["kill"] = {"on": False, "reason": ""}
        s["day"], s["day_pnl"] = LN._day(now), 0.0
        LN._log(s, now, "LEARN kill switch reset by itself (new UTC day)")
        LN._save(d, s)
        return True
    except Exception:
        return False
