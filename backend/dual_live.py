"""BE2b: price of RIGHT NOW for every open Dual Bot coin, in ONE request.
Before, dual_lab asked Binance one coin at a time and only for the first 14 coins (A-Z), so open trades on other coins
showed Live '--'. Here one bulk call returns every price; a short cache keeps the phone light. Display only, no trading rule.
Any failure returns {} and dual_lab falls back to its old one-by-one way."""
import time

CACHE_S = 4.0
_c = {"t": 0.0, "map": {}}


def prices(syms, fetch=None):
    """-> {symbol: price} for the asked symbols that Binance knows. Never raises."""
    try:
        now = time.time()
        if not _c["map"] or now - _c["t"] >= CACHE_S:
            if fetch is None:
                from recovered_bot import binance_client
                fetch = binance_client.get_active_usdt_symbols
            m = fetch()
            if isinstance(m, dict) and m:
                _c["map"], _c["t"] = dict(m), now
        out = {}
        for s in syms:
            v = _c["map"].get(s)
            if isinstance(v, (int, float)) and v > 0:
                out[s] = float(v)
        return out
    except Exception:
        return {}
