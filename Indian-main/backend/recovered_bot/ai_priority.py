"""
ai_priority.py - "the screen comes first".

The phone has few CPU cores. When you open the AI tab, the Shadow Lab (strategy replay) should not compete with
the screen you are looking at. The API calls touch() on every AI request; background workers ask app_busy()
and pace themselves slower while it is True.  Nothing is skipped, only slowed down while the app is in use.

READ-ONLY. Never touches a trade. Never raises.
"""
import time

APP_BUSY_WINDOW_S = 25.0        # the app counts as "in use" this long after its last AI request
_last_touch = 0.0


def touch():
    """Called by the API on every /api/ai/* request (not by /api/ai/health)."""
    global _last_touch
    _last_touch = time.time()


def app_busy(window=APP_BUSY_WINDOW_S):
    try:
        return (time.time() - _last_touch) < window
    except Exception:
        return False


def pace(idle_s, busy_s):
    """How long a background worker should sleep: idle_s when nobody uses the app, busy_s while the app is open."""
    return busy_s if app_busy() else idle_s


def status():
    ago = time.time() - _last_touch if _last_touch else None
    return {"app_in_use": app_busy(), "last_app_request_ago_s": round(ago, 1) if ago is not None else None}
