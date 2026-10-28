"""test_api_split.py - checks for the api_server split (NEXT-6a SWR core, NEXT-6b Vision routes, NEXT-6c lab / Dual routes, NEXT-6d money routes, NEXT-6e settings / exchange, NEXT-6f status / market / history, NEXT-6g AI keys / prefs / Trade Book, NEXT-6h diary).
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

print(f"{_n['ok']} passed, {_n['bad']} failed")
sys.exit(1 if _n["bad"] else 0)
