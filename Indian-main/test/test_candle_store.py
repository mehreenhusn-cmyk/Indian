"""Shared candle store (no network). Run: python3 test/test_candle_store.py"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def main():
    from recovered_bot import binance_client as B
    calls = []
    now = time.time() * 1000
    iv = 5 * 60000
    last_open = int(now // iv * iv)

    def fake_get(path, params=None, fast=False, timeout=None):
        calls.append(dict(params))
        n = int(params["limit"])
        return [[last_open - (n - 1 - i) * iv, "1", "2", "0.5", "1.5", "10"] for i in range(n)]

    B._get = fake_get
    B._kline_cache.clear()

    # closed use: 5 callers, same coin -> 1 REST call; a smaller limit is also a hit
    for lim in (250, 100, 250, 50, 251):
        rows = B.get_klines("AAAUSDT", 5, lim, closed_only=True)
        assert len(rows) == lim and rows[-1]["timestamp"] == last_open, (lim, len(rows))
    assert len(calls) == 1, calls
    # another coin / another timeframe = its own fetch
    B.get_klines("BBBUSDT", 5, 100, closed_only=True)
    B.get_klines("AAAUSDT", 15, 100, closed_only=True)
    assert len(calls) == 3, calls

    # forming-candle display: reused only for a few seconds
    B.get_klines("CCCUSDT", 5, 100)
    B.get_klines("CCCUSDT", 5, 100)
    assert len(calls) == 4, calls
    B._kline_cache[("CCCUSDT", "5m")]["at"] -= 10
    B.get_klines("CCCUSDT", 5, 100)
    assert len(calls) == 5, calls

    # a candle that already closed is NOT served from the store for closed use
    B._kline_cache[("AAAUSDT", "5m")]["rows"] = [[last_open - 2 * iv - i * iv, "1", "2", "0.5", "1.5", "1"] for i in range(300)][::-1]
    B.get_klines("AAAUSDT", 5, 100, closed_only=True)
    assert len(calls) == 6, calls

    st = B.kline_cache_stats()
    assert st["hits"] >= 4 and st["misses"] == 6, st
    print("PASS test_candle_store", st)


if __name__ == "__main__":
    main()
