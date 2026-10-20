"""Regression: _swr keys can be tuples (('ab_board', ''), ('book', 0, 1)) as well as strings. A tuple key must not crash
the refresh (it used to: 'tuple' object has no attribute 'startswith'). Run: python3 test/test_swr_tuple_key.py"""
import asyncio, os, sys, threading, time
src = open(os.path.join(os.path.dirname(__file__), "..", "backend", "api_server.py"), encoding="utf-8").read()
a, b = src.index("# ---- LAG FIX"), src.index("_FLAG_CACHE = {}")
class A: pass
_ns = {"asyncio": asyncio, "sys": sys, "threading": threading, "time": time}
exec(src[a:b], _ns)
for _k, _v in _ns.items():
    setattr(A, _k, _v)

async def main():
    for key in (("ab_board", ""), ("book", 0, 1), "vision_state:40", "coach"):
        v = await A._swr(key, 5.0, lambda: {"ok": key == key})
        assert v == {"ok": True}, (key, v)
    print("tuple + string keys ok")

asyncio.run(main())
print("ALL PASS")
