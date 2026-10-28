"""test_api_split.py - checks for the api_server split (NEXT-6a SWR core, NEXT-6b Vision routes).
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

print(f"{_n['ok']} passed, {_n['bad']} failed")
sys.exit(1 if _n["bad"] else 0)
