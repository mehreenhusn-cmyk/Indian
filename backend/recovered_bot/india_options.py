"""india_options.py - broker-agnostic option picker for Nifty / BankNifty / FinNifty.

Pure logic (no network, no broker import) so paper mode and any future broker
adapter (Tradebulls...) share it. Strategy runs on the SPOT index; a LONG/BUY
signal buys a CE, a SHORT/SELL signal buys a PE (options are only ever bought).
"""
from datetime import date
from math import floor

# strike step per underlying. Lot size and expiry are NOT hardcoded: both change
# by exchange circular, so they always come from the broker's contract list.
UNDERLYINGS = {
    "NIFTY":     {"step": 50},
    "BANKNIFTY": {"step": 100},
    "FINNIFTY":  {"step": 50},
}
MODES = ("ITM", "ATM", "OTM")


def _lo(spot, step):
    return int(spot // step) * step


def itm_strike(spot, option_type, step, depth=1):
    """Strike `depth` steps in the money. depth=1 -> nearest ITM strike.
    CE is ITM below spot, PE is ITM above spot. If spot sits exactly on a
    strike, that strike is ATM, so depth=1 goes one full step in."""
    if option_type not in ("CE", "PE") or depth < 1 or step <= 0:
        raise ValueError("bad option_type/depth/step")
    lo = _lo(spot, step)
    on_strike = abs(spot - lo) < 1e-9
    if option_type == "CE":
        base = lo - step if on_strike else lo
        return base - (depth - 1) * step
    base = lo + step
    return base + (depth - 1) * step


def otm_strike(spot, option_type, step, depth=1):
    """Strike `depth` steps out of the money (CE above spot, PE below)."""
    if option_type not in ("CE", "PE") or depth < 1 or step <= 0:
        raise ValueError("bad option_type/depth/step")
    lo = _lo(spot, step)
    on_strike = abs(spot - lo) < 1e-9
    if option_type == "CE":
        return lo + step + (depth - 1) * step
    base = lo - step if on_strike else lo
    return base - (depth - 1) * step


def atm_strike(spot, step):
    return int(floor(spot / step + 0.5)) * step


def strike_for(spot, option_type, step, mode="ITM", depth=1):
    mode = str(mode).upper()
    if mode == "ITM":
        return itm_strike(spot, option_type, step, depth)
    if mode == "OTM":
        return otm_strike(spot, option_type, step, depth)
    if mode == "ATM":
        return atm_strike(spot, step)
    raise ValueError(f"unknown mode {mode!r}")


def option_type_for(action):
    a = str(action).strip().upper()
    if a in ("LONG", "BUY"):
        return "CE"
    if a in ("SHORT", "SELL"):
        return "PE"
    raise ValueError(f"unknown action {action!r}")


def pick_expiry(expiries, today=None, min_days=1):
    """Nearest expiry that is at least `min_days` away (default skips
    expiry-day, where theta/gamma is brutal). Falls back to the nearest
    future expiry if nothing satisfies min_days."""
    today = today or date.today()
    fut = sorted(e for e in expiries if e >= today)
    for e in fut:
        if (e - today).days >= min_days:
            return e
    return fut[0] if fut else None


def expiry_pool(contracts, underlying, otype, today=None, min_days=1, expiry=None):
    """-> (expiry, [contracts of that expiry/type sorted by strike])"""
    u = underlying.upper()
    pool = [c for c in contracts if c["underlying"] == u and c["type"] == otype]
    exp = expiry or pick_expiry({c["expiry"] for c in pool}, today, min_days)
    if exp is None:
        return None, []
    return exp, sorted((c for c in pool if c["expiry"] == exp), key=lambda c: c["strike"])


def by_strike(pool, strike):
    for c in pool:
        if c["strike"] == strike:
            return c
    return None


def by_premium(pool, ltp_fn, target):
    """Contract whose premium is closest to `target` (ignores dead quotes)."""
    best, best_d, best_ltp = None, None, None
    for c in pool:
        ltp = ltp_fn(c)
        if not ltp or ltp <= 0:
            continue
        d = abs(ltp - target)
        if best_d is None or d < best_d:
            best, best_d, best_ltp = c, d, ltp
    return best, best_ltp


def pick_affordable(pool, otype, preferred_strike, ltp_fn, budget, cost_fn,
                    min_premium=0.0):
    """Start at the preferred strike and walk toward CHEAPER strikes (higher for CE,
    lower for PE) until one fits `budget`. Never goes below `min_premium`.
    -> (contract, ltp, reason)  (contract None => reason says why)"""
    if otype == "CE":
        cands = sorted((c for c in pool if c["strike"] >= preferred_strike),
                       key=lambda c: c["strike"])
    else:
        cands = sorted((c for c in pool if c["strike"] <= preferred_strike),
                       key=lambda c: -c["strike"])
    cheapest = None
    for c in cands:
        ltp = ltp_fn(c)
        if not ltp or ltp <= 0:
            continue
        if ltp < min_premium:
            break      # only gets cheaper from here
        cost = cost_fn(c, ltp)
        cheapest = cost if cheapest is None else min(cheapest, cost)
        if cost <= budget:
            return c, ltp, ""
    if cheapest is None:
        return None, None, "no strike at/above min premium"
    return None, None, f"needs Rs{cheapest:,.0f}, have Rs{budget:,.0f}"


def pick_contract(contracts, underlying, action, spot, today=None,
                  depth=1, min_days=1, mode="ITM"):
    """contracts: iterable of dicts with keys
         underlying, expiry(date), strike, type('CE'/'PE'), lot, key
    Returns the matching contract dict, or None (caller must refuse to trade)."""
    u = underlying.upper()
    if u not in UNDERLYINGS:
        raise ValueError(f"unsupported underlying {underlying!r}")
    otype = option_type_for(action)
    exp, pool = expiry_pool(contracts, u, otype, today, min_days)
    if exp is None:
        return None
    return by_strike(pool, strike_for(spot, otype, UNDERLYINGS[u]["step"], mode, depth))
