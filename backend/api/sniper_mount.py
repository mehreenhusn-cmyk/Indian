"""api/sniper_mount.py - ONE helper that mounts the read-only OwlSniper routes of Parts 9 to 47 (Part 46 / FILE 54, app problems added in Part 47). Owner said "mount ok" on 3 Nov 2026.
Why one helper: every route file said "NOT MOUNTED, add 4 lines to api_server.py". Five routes = 20 lines in a 835-line file. Now api_server.py gets ONE block of 5 lines and this file keeps the list.
Routes (each a GET, read only, behind the app's token check, 404 until v2_api_enabled holds 1, off while v2_sniper_off exists; the self log route only writes its own small file):
  /api/v2/sniper_bridge    (Part 9)   learn bridge result per source
  /api/v2/sniper_hist      (R1)       training data health + background candle history download (writes ONLY candles into v2_market.db)
  /api/v2/sniper_autopilot (R3b)      autopilot state + self-relearn loop (writes ONLY v2_sniper_autopilot.json)
  /api/v2/sniper_exitlearn (R4)       booking learner state + self-relearn loop (writes ONLY v2_sniper_exitlearn.json)
  /api/v2/sniper_riskbox   (Part 11)  Risk Box for one coin
  /api/v2/sniper_capital   (Part 34)  small account view
  /api/v2/sniper_prior     (Part 38)  old studies and 'Sniper uses it'
  /api/v2/sniper_selflog   (Part 44)  self log
  /api/v2/app_problems     (Part 47)  App Problems list (read only)
  /api/v2/slow_calls       (Part 2)   calls waiting now + busiest routes (read only)
  /api/v2/btc_lab          (R16b)     BTC's own numbers (BTC is kept out of every total)
  /api/v2/sniper_lessons   (R7)       what the Sniper learned from its own mistakes: tag per trade, setup penalty, 3 lessons of the week (writes ONLY v2_sniper_lessons.json)
  /api/v2/sniper_modes     (R6)       SCALP / SHORT_SWING / SWING mode per market state + judged exit (writes ONLY v2_sniper_modes.json)
  /api/v2/lab_results      (R9)       ONE TestResult list for Z-SMA / SD bands / pairs / combos, EDGE first, filter family + verdict (writes ONLY the four study files v2_sniper_zsma / sdbands / ind_pairs / combo)
  /api/v2/sniper_h2h       (R24a)     Current Bot vs Sniper on the SAME days, % per trade, verdict (read only, writes nothing)
  /api/v2/sniper_grad      (R24b)     graduation checklist: 7 checks PASS / FAIL / WAIT (read only, writes nothing)
  /api/v2/sniper_trades    (R29a)     the trade record: open + closed Sniper trades with signal, basis, entry, TP / SL, expected profit, hold, result, lesson (read only)
  /api/v2/sniper_ctx       (R30)      BTC move / trend + session the Sniper learns from (read only; BTC is never added to a P&L)
  /api/v2/sniper_watch     (R33a)     ranked watchlist: Market Watch favourites + big movers, ARMED / NEAR / WATCH + one line each, ?armed=1 (writes ONLY v2_sniper_watch.json)
  /api/v2/sniper_eva       (Part 17a) expected vs actual per lane: the Risk Box frozen at entry vs the real paper result, no verdict below 30 compared trades (read only)
  /api/v2/sniper_opp       (Part 17a) one STAY / TAKE PROFIT / ROTATE / KEEP line per open Sniper paper trade, rough (read only)
  /api/v2/grad_dual        (Part 17c) graduation gate of the Dual Bot / Brain (v2_graduation.py) + last automatic Scalp Lab / Ledger run (read only)
  /api/v2/data_health      (Part 17d) candle switch + runner, what training data is missing per source, autopilot state, last write of each background file (read only)
  /api/v2/chop*            (Part C3)  the both-indicator PAPER bot b3 on 5m: overview, log, report (read only) + switch ON / OFF + apply learned weights (write only chop_b3.db and chop_b3_weights.json)
  /api/v2/sniper_gates     (R26b)     8 gates PASS / FAIL / WAIT + one reason + the mistakes journal (read only, writes nothing)
Each route is mounted in its OWN try / except: a route file that cannot be imported (a missing file, a typo) is skipped with one line in the startup log and never stops the backend or the other routes.
STATUS is a plain dict the backend keeps in memory: {"mounted": [names], "skipped": [{"name", "why"}]}. The Problems page (Part 47) reads it, so a skipped route shows up there with its reason.
GET /api/v2/sniper_learn is NOT here: it lives in api/sniper_paper.py, which api_server.py already mounts. Nothing here can send an order.
Use (api_server.py, after the sniper paper block):  from api.sniper_mount import mount_all;  mount_all(app, require_api_token, DATA_DIR)"""
import importlib

VERSION = "api/sniper_mount 1 (Part 46)"
ROUTES = (
    ("api.sniper_bridge", "sniper bridge"),
    ("api.sniper_hist", "sniper hist"),
    ("api.sniper_autopilot", "sniper autopilot"),
    ("api.sniper_exitlearn", "sniper exitlearn"),
    ("api.sniper_riskbox", "sniper riskbox"),
    ("api.sniper_capital", "sniper capital"),
    ("api.sniper_prior", "sniper prior"),
    ("api.sniper_selflog", "sniper selflog"),
    ("api.app_problems", "app problems"),
    ("api.btc_lab_route", "btc lab"),
    ("api.sniper_modes", "sniper modes"),
    ("api.sniper_lessons", "sniper lessons"),
    ("api.v2_lab_route", "lab results"),
    ("api.sniper_h2h", "sniper h2h"),
    ("api.sniper_grad", "sniper graduation"),
    ("api.sniper_gates", "sniper gates"),
    ("api.sniper_trades", "sniper trades"),
    ("api.sniper_ctx", "sniper ctx"),
    ("api.sniper_days", "sniper days"),
    ("api.sniper_watch", "sniper watch"),
    ("api.sniper_eva", "sniper eva"),
    ("api.sniper_opp", "sniper opp"),
    ("api.sniper_winners", "sniper winners"),
    ("api.v2_grad_dual", "dual graduation"),
    ("api.v2_data_health", "data health"),
    ("api.route_timing", "slow calls"),
    ("api.chop", "chop b3"),
    ("api.filter_study", "filter study"),   # Part 8A (README_FILTER)
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
