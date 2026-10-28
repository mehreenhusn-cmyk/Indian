"""test_api_split.py - checks for the api_server split (NEXT-6a SWR core, NEXT-6b Vision routes, NEXT-6c lab / Dual routes, NEXT-6d money routes, NEXT-6e settings / exchange, NEXT-6f status / market / history, NEXT-6g AI keys / prefs / Trade Book, NEXT-6h diary + coach, NEXT-6i rest of the AI routes, NEXT-6j WebSocket).
Run: cd backend && python3 test_api_split.py     (no network; imports api_server with a temp HOME, starts no bot)
"""
import asyncio
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="owl_split_")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_n = {"ok": 0, "bad": 0}


def check(name, cond):
    _n["ok" if cond else "bad"] += 1
    print(("PASS " if cond else "FAIL ") + name)


import api_server as A
import api.swr as S
import api.vision as V
import api.dual as D
import api.trade as T
import api.settings as ST
import api.status as SS
import api.ai_book as AB
import api.ai_pages as AP
import api.ws as WS
import api.ai_core as AC
import api.ai_reports as AR
import api.ai_live as AL
import api.ai_chats as ACH
import hashlib

# 6a: api_server shares the SAME objects as api/swr.py (not copies)
for n in ("_SWR", "_SWR_TASK", "_SWR_JOBS", "_TIMING", "_HEAVY_NOW", "_HEAVY_LOCK", "_HEAVY_POOL", "_LIGHT_POOL",
          "_REPLAY_POOL", "_LIGHT_KEYS", "_swr", "_swr_start", "_swr_refresh", "_swr_warmer", "_timed_call", "_eff_ttl"):
    check(f"api_server.{n} is api.swr.{n}", getattr(A, n) is getattr(S, n))

# 6a: SWR behaves: first call builds, second (fresh) call returns the cached value, no second build
calls = {"n": 0}


def build(x):
    calls["n"] += 1
    return {"x": x, "n": calls["n"]}


async def _go():
    a = await S._swr("split_test", 60.0, build, 7)
    b = await S._swr("split_test", 60.0, build, 7)
    return a, b


a, b = asyncio.run(_go())
check("swr builds once and serves the cached answer", a == b and calls["n"] == 1)
check("swr slow-build rule: cheap builds keep their ttl", S._eff_ttl("split_test", 15.0) == 15.0)

# 6b: the 17 vision routes exist, in the same order, with the same methods
EXPECTED = [
    ("/api/vision/state", "GET"),
    ("/api/vision/image/{item_id}", "GET"),
    ("/api/vision/guide", "GET"),
    ("/api/vision/notes", "POST"),
    ("/api/vision/lessons", "GET"),
    ("/api/vision/rule", "POST"),
    ("/api/vision/pumpdump", "GET"),
    ("/api/vision/pumpdump/seed", "POST"),
    ("/api/vision/compare", "GET"),
    ("/api/vision/day_view", "GET"),
    ("/api/vision/evidence", "GET"),
    ("/api/vision/lab", "GET"),
    ("/api/vision/notebook_digest", "GET"),
    ("/api/vision/own", "POST"),
    ("/api/vision/day", "GET"),
    ("/api/vision/days", "GET"),
    ("/api/vision/exits", "GET"),
]
got = []
for r in A.app.routes:
    subs = [r]
    if not hasattr(r, "path"):
        sub = getattr(r, "router", None) or getattr(r, "original_router", None)
        pre = getattr(r, "prefix", "") or ""
        subs = [x for x in (sub.routes if sub else [])]
        for x in subs:
            if hasattr(x, "path") and x.path.startswith(pre + "/api/vision"):
                got.append((pre + x.path, ",".join(sorted(x.methods or []))))
    elif r.path.startswith("/api/vision"):
        got.append((r.path, ",".join(sorted(r.methods or []))))
check("vision routes: same 17 paths + methods, same order", got == EXPECTED)
check("vision router has a make_router(require_api_token)", callable(V.make_router))

# 6c: the lab / dual / archive / layers / smart_brain routes (21) keep path, method and order
EXPECTED_DUAL = [
    ("/api/filter_lab", "GET"),
    ("/api/filter_lab_all", "GET"),
    ("/api/variant_lab", "GET"),
    ("/api/doctor_summary", "GET"),
    ("/api/doctor_filter", "GET"),
    ("/api/health_meter", "GET"),
    ("/api/scoreboard", "GET"),
    ("/api/scan_lab", "GET"),
    ("/api/tag_lab", "GET"),
    ("/api/dual_lab", "GET"),
    ("/api/archive", "GET"),
    ("/api/dual_desk", "GET"),
    ("/api/archive_check", "GET"),
    ("/api/archive_export", "GET"),
    ("/api/archive_export_save", "GET"),
    ("/api/dual_universe", "GET"),
    ("/api/layers/pa", "GET"),
    ("/api/layers/vol", "GET"),
    ("/api/smart_brain", "GET"),
    ("/api/dual_lab/report", "GET"),
    ("/api/dual_lab/report_save", "GET"),
]


def _walk(routes, pre=""):
    for x in routes:
        if hasattr(x, "path"):
            yield (pre + x.path, ",".join(sorted(getattr(x, "methods", None) or [])))
        else:
            sub = getattr(x, "router", None) or getattr(x, "original_router", None)
            if sub is not None:
                yield from _walk(sub.routes, pre + (getattr(x, "prefix", "") or ""))


_SRC = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_server.py"), encoding="utf-8").read()


def src_has(s):
    return _SRC.count(s)


allr = list(_walk(A.app.routes))
got_dual = [x for x in allr if x in set(EXPECTED_DUAL)]
check("dual routes: same 21 paths + methods, same order", got_dual == EXPECTED_DUAL and len(EXPECTED_DUAL) == 21)
check("dual router takes safe_status and returns a router", callable(D.make_router))
check("health_meter works through the passed safe_status (late-bound lambda)",
      any(p == "/api/health_meter" for p, m in allr))
check("api_server.py includes the dual router once", src_has("_dual_make_router(lambda mod: _safe_status(mod))") == 1)

# The routes that must stay protected still ask for the token (POST routes)
posts = [p for p, m in EXPECTED if m == "POST"]
check("vision POST routes kept (notes, rule, pumpdump/seed, own)", len(posts) == 4)

# Source guards: nothing of the moved code is left behind in api_server.py
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_server.py"), encoding="utf-8").read()
check("api_server.py no longer defines _swr", "async def _swr(" not in src)
check("api_server.py no longer defines vision_state", "async def vision_state(" not in src)
check("api_server.py no longer defines filter_lab_page / smart_brain_api", "async def filter_lab_page(" not in src and "async def smart_brain_api(" not in src)
check("api_server.py includes the vision router once", src.count("_vision_make_router(require_api_token)") == 1)

# 6d: the 10 money routes (close / flatten / TP / SL / reconcile) keep path, method and order
EXPECTED_TRADE = [
    ("/api/close/{trade_id}", "POST"),
    ("/api/close_all", "POST"),
    ("/api/flatten", "POST"),
    ("/api/preview_close_all", "GET"),
    ("/api/close_all_profit", "POST"),
    ("/api/close_all_loss", "POST"),
    ("/api/set_target_tp/{trade_id}", "POST"),
    ("/api/trail_sl/{trade_id}", "POST"),
    ("/api/move_sl_breakeven/{trade_id}", "POST"),
    ("/api/reconcile", "POST"),
]
got_trade = [x for x in allr if x in set(EXPECTED_TRADE)]
check("trade routes: same 10 paths + methods, same order", got_trade == EXPECTED_TRADE)
_i = [allr.index(x) for x in EXPECTED_TRADE]
check("trade routes sit together, in one block", _i == list(range(_i[0], _i[0] + 10)))
_j = allr.index(("/api/binance/test-connection", "POST"))
check("trade block comes right before /api/binance/test-connection (old place)", _i[-1] + 1 == _j)
check("trade router takes require_api_token + bot_arg and returns a router", callable(T.make_router))
check("api_server.py includes the trade router once", src.count("_trade_make_router(require_api_token, _bot_arg)") == 1)
_TS = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "trade.py"), encoding="utf-8").read()
check("9 of the 10 trade routes still ask for the API token (only preview_close_all never did)",
      _TS.count("Depends(require_api_token)") == 9)
check("flatten order kept: close live first, THEN switch live trading off",
      _TS.index("exchange.close_position_market") < _TS.index("settings_store.update(live_trading_enabled=False)"))
check("api_server.py no longer defines the money routes",
      all(("async def " + n + "(") not in src for n in ("close_one", "close_all", "flatten", "preview_close_all",
          "close_all_profit", "close_all_loss", "set_target_tp", "trail_sl", "move_sl_breakeven", "reconcile")))
check("/api/ai/live/panic was NOT moved (part 6i)", "/api/ai/live/panic" in src)


# 6e + 6f: settings / exchange (6 routes) and status / market / history (21 routes) keep path, method and order
EXPECTED_SETTINGS = [
    ("/api/settings", "GET"), ("/api/settings", "POST"), ("/api/backup/export", "POST"),
    ("/api/binance/test-connection", "POST"), ("/api/exchange", "GET"), ("/api/exchange/switch", "POST"),
]
EXPECTED_STATUS = [
    ("/", "GET"), ("/health", "GET"),
    ("/api/status", "GET"), ("/api/system", "GET"), ("/api/ops", "GET"), ("/api/load_report", "GET"), ("/api/load_report/daily", "GET"),
    ("/api/positions", "GET"), ("/api/market", "GET"), ("/api/signals", "GET"), ("/api/btc/live", "GET"),
    ("/api/btc/signals", "GET"), ("/api/daily-report", "GET"),
    ("/api/alerts", "GET"), ("/api/history", "GET"), ("/api/equity", "GET"), ("/api/calendar", "GET"), ("/api/candles/{symbol}", "GET"),
]
allr = list(_walk(A.app.routes))
check("settings routes: same 6 paths + methods, same order", [x for x in allr if x in set(EXPECTED_SETTINGS)] == EXPECTED_SETTINGS)
check("status routes: same 18 paths + methods, same order", [x for x in allr if x in set(EXPECTED_STATUS)] == EXPECTED_STATUS)
check("binance test + exchange routes still sit right after the trade block",
      allr.index(("/api/binance/test-connection", "POST")) == allr.index(("/api/reconcile", "POST")) + 1)
check("settings + exchange factories exist", callable(ST.make_router_settings) and callable(ST.make_router_exchange))
check("status factories exist", all(callable(getattr(SS, n)) for n in ("make_router_basic", "make_router_system", "make_router_market", "make_router_history")))
for _inc in ("_status_basic_router()", "_status_system_router(_display_status, DATA_DIR)", "_status_market_router(_display_status, _bot_arg)",
             "_status_history_router(_bot_arg)", "_st_settings_router(require_api_token, DATA_DIR)", "_st_exchange_router(require_api_token)"):
    check("api_server.py includes " + _inc + " once", src.count(_inc) == 1)
_SS = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "status.py"), encoding="utf-8").read()
_SE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "settings.py"), encoding="utf-8").read()
check("REST handlers that must stay off the event loop are still plain def (status, positions, market, signals, alerts, history, equity)",
      all(("\n        def " + n + "(") in _SS or ("\n    def " + n + "(") in _SS for n in ("get_status", "get_positions", "get_market", "get_signals", "get_alerts", "get_history", "get_equity")))
check("settings secrets stay masked (mask prefix + 8 AI keys + binance + telegram)",
      all(k in _SE for k in ("binance_api_secret", "telegram_bot_token", "ai8_api_key", "_mask_settings(settings_store.get_all())")))
check("settings routes still ask for the API token (get + post + backup + binance test + switch = 5)", _SE.count("Depends(require_api_token)") == 5)
check("api_server.py no longer defines the moved handlers",
      all(("async def " + n + "(") not in src and ("\ndef " + n + "(") not in src for n in
          ("root", "health", "get_status", "get_system", "get_ops", "get_positions", "get_market", "get_signals", "get_btc_live", "get_btc_signals",
           "daily_report_endpoint", "get_alerts", "get_history", "get_equity", "get_calendar", "get_candles", "get_settings", "update_settings",
           "export_backup", "binance_test_connection", "get_exchange", "switch_exchange", "_attach_signal_results", "_mask_settings")))

# 6g: AI keys (5), app prefs (2), Trade Book (2) keep path, method and order
EXPECTED_AIBOOK = [
    ("/api/ai/vkeys", "GET"), ("/api/ai/vkeys/add", "POST"), ("/api/ai/vkeys/test", "POST"), ("/api/ai/vkeys/detect", "POST"),
    ("/api/ai/vkeys/clear", "POST"), ("/api/app_prefs", "GET"), ("/api/app_prefs", "POST"),
    ("/api/ai/book", "GET"), ("/api/ai/path", "GET"),
]
allr = list(_walk(A.app.routes))
check("AI keys / prefs / book routes: same 9 paths + methods, same order", [x for x in allr if x in set(EXPECTED_AIBOOK)] == EXPECTED_AIBOOK)
check("ai_book factories exist", callable(AB.make_router_keys) and callable(AB.make_router_book))
check("api_server.py includes the AI keys router once", src.count("_ai_keys_router(require_api_token, DATA_DIR)") == 1)
check("api_server.py includes the Trade Book router once", src.count("_ai_book_router()") == 1)
check("_swr_prewarm still finds ai_book_endpoint (the same handler object the route uses)",
      callable(getattr(A, "ai_book_endpoint", None)) and any(getattr(r, "endpoint", None) is A.ai_book_endpoint for r in A.app.routes if hasattr(r, "path") and r.path == "/api/ai/book"))
_AB = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "ai_book.py"), encoding="utf-8").read()
check("AI key routes: 4 POST routes + app prefs POST ask for the API token (5)", _AB.count("Depends(require_api_token)") == 5)
check("api_server.py no longer defines the 6g handlers",
      all(("async def " + n + "(") not in src for n in ("ai_vkeys_status", "ai_vkeys_add", "ai_vkeys_test", "ai_vkeys_detect", "ai_vkeys_clear",
          "app_prefs_get", "app_prefs_set", "_book_refresh", "ai_path_endpoint")) and "def _book_go(" not in src)
check("the AI book / AI path routes still use the light pool (not the heavy lock)", "_LIGHT_POOL" in _AB)

# 6h part 1: Trade Diary (API + page) moved to api/ai_pages.py; the page text is byte for byte the old one
allr = list(_walk(A.app.routes))
check("diary routes: /api/ai/diary then /diary, in the old place (right after /api/ai/levels)",
      allr.index(("/diary", "GET")) == allr.index(("/api/ai/diary", "GET")) + 1 and allr.index(("/api/ai/diary", "GET")) == allr.index(("/api/ai/levels", "GET")) + 1)
check("diary page text is byte for byte the old one (sha256)",
      hashlib.sha256(AP._DIARY_HTML.encode()).hexdigest() == "cb7ebdc1f605eaa7e1cf1d7d3c2938f92812e4f642e94ab63df8ed3c17bcbdef")
check("api_server.py includes the diary router once", src.count("_ai_diary_router()") == 1)
check("api_server.py no longer defines the diary handlers / page text",
      "async def ai_diary_endpoint(" not in src and "async def ai_diary_page(" not in src and "_DIARY_HTML" not in src)
check("ai_pages diary factory exists", callable(AP.make_router_diary))

# 6h part 2: AI Coach (4 API routes + page) moved to api/ai_pages.py; page text byte for byte; prewarm handler kept
allr = list(_walk(A.app.routes))
_COACH = [("/api/ai/coach", "GET"), ("/api/ai/coach/reset", "POST"), ("/api/ai/plan/config", "POST"), ("/api/ai/coach/config", "POST"), ("/coach", "GET")]
_ic = allr.index(_COACH[0])
check("coach routes: same 5 paths + methods, same order, in the old place (right after /api/ai/free_trade)",
      allr[_ic:_ic + 5] == _COACH and allr[_ic - 1] == ("/api/ai/free_trade", "GET") and allr[_ic + 5] == ("/api/ai/desk/reset", "POST"))
check("coach page text is byte for byte the old one (sha256)",
      hashlib.sha256(AP._COACH_HTML.encode()).hexdigest() == "ed04d0baa6fdaab1d9732d1813ce9ecd73de48afe13a75aab6b9b91086a43441")
check("api_server.py includes the coach router once and no longer defines the handlers / page text",
      src.count("_ai_coach_router(require_api_token)") == 1 and "async def ai_coach_endpoint(" not in src and "_COACH_HTML" not in src)
check("_swr_prewarm still reaches the coach handler (same object that the /api/ai/coach route uses)",
      callable(getattr(A, "ai_coach_endpoint", None)) and any(getattr(r, "endpoint", None) is A.ai_coach_endpoint for r in A.app.routes if getattr(r, "path", "") == "/api/ai/coach"))
_AP = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "ai_pages.py"), encoding="utf-8").read()
check("coach POST routes still ask for the API token (3)", _AP.count("Depends(require_api_token)") == 3)

# 6i: the last 49 routes (ask / reports / lab / observer / tools / live / chats) moved to 4 api/ files; same paths, methods and order
_AI49 = [
    ("/api/ai/ask", "POST"), ("/api/ai/trade-audit-context", "GET"), ("/api/ai/insights", "GET"), ("/api/ai/doctor", "GET"),
    ("/api/report/save", "GET"), ("/api/report/app", "GET"), ("/api/report/app_save", "GET"), ("/api/report", "GET"),
    ("/api/ai/health", "GET"), ("/api/ai/pair_replay", "GET"), ("/api/ai/lab", "GET"), ("/api/ai/ab_board", "GET"), ("/api/ai/reading", "GET"),
    ("/api/ai/exit_study", "GET"), ("/api/ai/wait_study", "GET"), ("/api/ai/recipe", "GET"), ("/api/ai/desk", "GET"), ("/api/ai/levels", "GET"),
    ("/api/ai/observer", "GET"), ("/api/ai/pick", "GET"), ("/api/ai/selfsignal", "GET"), ("/api/ai/free_trade", "GET"),
    ("/api/ai/desk/reset", "POST"), ("/api/ai/advice", "GET"), ("/api/ai/ab_board/reset", "POST"), ("/api/ai/learning", "GET"),
    ("/api/ai/backup", "GET"), ("/api/ai/backup/run", "POST"), ("/api/ai/backup/restore", "POST"),
    ("/api/ai/live", "GET"), ("/api/ai/live/keys", "POST"), ("/api/ai/live/keys/clear", "POST"), ("/api/ai/live/check", "POST"),
    ("/api/ai/live/config", "POST"), ("/api/ai/live/enable", "POST"), ("/api/ai/live/disable", "POST"), ("/api/ai/live/panic", "POST"),
    ("/api/ai/live/reset", "POST"), ("/api/ai/lab/replay", "POST"), ("/api/ai/shadow", "GET"), ("/api/ai/digest/send", "POST"),
    ("/api/ai/history", "GET"), ("/api/ai/history/clear", "POST"), ("/api/ai/chats", "GET"), ("/api/ai/chats", "POST"),
    ("/api/ai/chats/rename", "POST"), ("/api/ai/chats/delete", "POST"), ("/api/ai/chats/active", "POST"), ("/api/ai/app_health", "GET"),
]
allr = list(_walk(A.app.routes))
check("6i: the 49 AI routes exist once each, in the old order", len(_AI49) == 49 and [x for x in allr if x in set(_AI49)] == _AI49)
check("6i: api_server.py no longer defines any of the 49 handlers",
      not any(("async def " + n + "(") in src for n in ("ai_ask", "ai_trade_audit_context", "ai_insights", "ai_doctor", "report_save", "app_report", "app_report_save", "full_report",
                                                       "ai_health", "ai_pair_replay", "ai_lab", "ai_observer_endpoint", "ai_pick_endpoint", "ai_selfsignal_endpoint", "ai_desk_reset",
                                                       "ai_live_status", "ai_live_panic", "ai_chats_list", "ai_history", "ai_app_health_report")))
check("6i: the 4 modules + their factories exist", all(callable(f) for f in (AC.make_router_ask, AC.make_router_lab, AC.make_router_observer, AR.make_router_reports,
                                                                                AL.make_router_tools, AL.make_router_live, ACH.make_router_chats)))
check("6i: the start-up warm-up still reaches all 8 handlers it calls directly",
      all(callable(getattr(A, n, None)) for n in ("ai_book_endpoint", "ai_coach_endpoint", "ai_pick_endpoint", "ai_ab_board_endpoint", "ai_desk_endpoint",
                                                  "ai_observer_endpoint", "ai_levels_endpoint", "ai_advice_endpoint")))
_AL = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "ai_live.py"), encoding="utf-8").read()
check("6i: all 14 token-protected routes (resets, backup run / restore, every AI Live route) still ask for the API token", _AL.count("_auth=Depends(require_api_token)") == 14)
check("6i: every api/ file is under 250 lines", all(sum(1 for _ in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", f), encoding="utf-8")) < 250
                                                    for f in ("ai_core.py", "ai_reports.py", "ai_live.py", "ai_chats.py")))

# 6j: WebSocket moved to api/ws.py; /ws is still the LAST route; old names are thin links
allr = list(_walk(A.app.routes))
check("/ws is still the last route", allr[-1] == ("/ws", ""))
check("api_server shares the SAME manager / _dumps / ConnectionManager objects as api/ws.py",
      A.manager is WS.manager and A._dumps is WS._dumps and A.ConnectionManager is WS.ConnectionManager)
check("same limits: 3 sockets, 10 s send timeout, 0.25 s cadence",
      A.MAX_SOCKETS == 3 and A.SEND_TIMEOUT_SEC == 10.0 and A.BROADCAST_INTERVAL_SEC == 0.25 and WS.BROADCAST_INTERVAL_SEC == 0.25)
check("api_server.py no longer defines the websocket code",
      "class ConnectionManager" not in src and "@app.websocket" not in src and "async def websocket_endpoint" not in src)
check("start-up still has _status_broadcaster and _snapshot_msg", callable(A._status_broadcaster) and callable(A._snapshot_msg))
_snap = A._snapshot_msg()
check("snapshot message is FULL_STATE_SNAPSHOT json", '"FULL_STATE_SNAPSHOT"' in _snap and _snap.startswith('{"type": "init"'))


async def _mgr():
    class _W:
        def __init__(self):
            self.sent = []
            self.closed = False

        async def accept(self):
            pass

        async def send_text(self, m):
            self.sent.append(m)

        async def close(self):
            self.closed = True
    m = WS.ConnectionManager()
    ws = [_W() for _ in range(5)]
    for w in ws:
        await m.connect(w)
    n, dropped = await m.broadcast("x")
    return len(m.active_connections), n, dropped, ws


_a, _n2, _d, _ws = asyncio.run(_mgr())
check("manager keeps the newest 3 sockets, closes the older ones, broadcast reaches 3", _a == 3 and _n2 == 3 and _d == 0 and _ws[0].closed and _ws[1].closed and _ws[4].sent == ["x"])

print(f"{_n['ok']} passed, {_n['bad']} failed")
sys.exit(1 if _n["bad"] else 0)
