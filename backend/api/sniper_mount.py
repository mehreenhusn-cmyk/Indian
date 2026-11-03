"""api/sniper_mount.py - ONE helper that mounts the read-only OwlSniper routes of Parts 9 to 47 (Part 46 / FILE 54, app problems added in Part 47). Owner said "mount ok" on 3 Nov 2026.
Why one helper: every route file said "NOT MOUNTED, add 4 lines to api_server.py". Five routes = 20 lines in a 835-line file. Now api_server.py gets ONE block of 5 lines and this file keeps the list.
Routes (each a GET, read only, behind the app's token check, 404 until v2_api_enabled holds 1, off while v2_sniper_off exists; the self log route only writes its own small file):
  /api/v2/sniper_bridge    (Part 9)   learn bridge result per source
  /api/v2/sniper_hist      (R1)       training data health + background candle history download (writes ONLY candles into v2_market.db)
  /api/v2/sniper_riskbox   (Part 11)  Risk Box for one coin
  /api/v2/sniper_capital   (Part 34)  small account view
  /api/v2/sniper_prior     (Part 38)  old studies and 'Sniper uses it'
  /api/v2/sniper_selflog   (Part 44)  self log
  /api/v2/app_problems     (Part 47)  App Problems list (read only)
Each route is mounted in its OWN try / except: a route file that cannot be imported (a missing file, a typo) is skipped with one line in the startup log and never stops the backend or the other routes.
STATUS is a plain dict the backend keeps in memory: {"mounted": [names], "skipped": [{"name", "why"}]}. The Problems page (Part 47) reads it, so a skipped route shows up there with its reason.
GET /api/v2/sniper_learn is NOT here: it lives in api/sniper_paper.py, which api_server.py already mounts. Nothing here can send an order.
Use (api_server.py, after the sniper paper block):  from api.sniper_mount import mount_all;  mount_all(app, require_api_token, DATA_DIR)"""
import importlib

VERSION = "api/sniper_mount 1 (Part 46)"
ROUTES = (
    ("api.sniper_bridge", "sniper bridge"),
    ("api.sniper_hist", "sniper hist"),
    ("api.sniper_riskbox", "sniper riskbox"),
    ("api.sniper_capital", "sniper capital"),
    ("api.sniper_prior", "sniper prior"),
    ("api.sniper_selflog", "sniper selflog"),
    ("api.app_problems", "app problems"),
)
STATUS = {"version": VERSION, "mounted": [], "skipped": []}


def mount_all(app, require_api_token, data_dir):
    """Mounts every route of ROUTES. Never raises. Returns STATUS (also kept in the module)."""
    STATUS["mounted"], STATUS["skipped"] = [], []
    for mod, name in ROUTES:
        try:
            router = importlib.import_module(mod).make_router(require_api_token, data_dir)
            app.include_router(router)
            STATUS["mounted"].append(name)
        except Exception as e:                                   # a bad file must never stop the backend
            why = "%s: %s" % (type(e).__name__, str(e)[:120])
            STATUS["skipped"].append({"name": name, "why": why})
            print("[startup] %s route skipped: %s" % (name, why))
    print("[startup] sniper routes mounted: %d of %d" % (len(STATUS["mounted"]), len(ROUTES)))
    return STATUS
