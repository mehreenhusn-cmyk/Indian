"""india_chain.py - option-chain view for the terminal (CALL | strike | PUT).
Built from any DataProvider, so demo and the future Tradebulls feed look the same."""
from datetime import time

try:
    from . import india_options as opt, india_calendar as cal
except ImportError:
    import india_options as opt, india_calendar as cal


def market_status(now):
    if not cal.is_trading_day(now.date()):
        return "CLOSED"
    return "OPEN" if time(9, 15) <= now.time() < time(15, 30) else "CLOSED"


def ticker(eng, unders):
    out = {}
    for u in unders:
        spot = eng.p.get_spot(u)
        pc = eng.p.get_prev_close(u)
        out[u] = {"spot": round(spot, 2),
                  "chg": round(spot - pc, 2) if pc else None,
                  "chg_pct": round(100 * (spot - pc) / pc, 2) if pc else None}
    return out


def build_chain(eng, u, expiry=None, width=10):
    """-> dict for the Option Chain tab. `trade_expiry` is the expiry the engine would
    actually buy from (it skips expiry-day, CARRY needs >= 2 days)."""
    p, s = eng.p, eng.s
    now = p.now()
    u = u.upper()
    spot = p.get_spot(u)
    step = opt.UNDERLYINGS[u]["step"]
    contracts = p.get_contracts(u)
    expiries = sorted({c["expiry"] for c in contracts if c["expiry"] >= now.date()})
    min_days = max(int(s["min_days_to_expiry"]), 2 if s["product"] == "CARRY" else 0)
    trade_exp = opt.pick_expiry(set(expiries), now.date(), min_days)
    exp = expiry if expiry in expiries else (trade_exp or (expiries[0] if expiries else None))
    atm = opt.atm_strike(spot, step)
    budget = eng.cash * float(s["budget_pct"])
    cells = {}
    for c in contracts:
        if c["expiry"] == exp and abs(c["strike"] - atm) <= width * step:
            cells.setdefault(c["strike"], {})[c["type"]] = c
    rows = []
    for k in sorted(cells):
        row = {"strike": k, "atm": k == atm}
        for side in ("CE", "PE"):
            c = cells[k].get(side)
            if not c:
                row[side] = None
                continue
            ltp = p.get_option_ltp(c)
            ref = p.get_option_ref(c)
            cost = eng.entry_cost(c, ltp) if ltp and ltp > 0 else None
            pin = eng.pins.get((u, side))
            row[side] = {
                "key": c["key"], "ltp": round(ltp, 2) if ltp else None,
                "chg": round(ltp - ref, 2) if ltp and ref else None,
                "chg_pct": round(100 * (ltp - ref) / ref, 2) if ltp and ref else None,
                "oi": p.get_oi(c), "lot": c["lot"], "cost": round(cost, 2) if cost else None,
                "affordable": bool(cost is not None and cost <= budget),
                "itm": (k < spot) if side == "CE" else (k > spot),
                "pinned": bool(pin and pin["type"] == "strike" and pin["strike"] == k),
            }
        rows.append(row)
    lot = next((c["lot"] for c in contracts), None)
    return {"underlying": u, "spot": round(spot, 2), "atm": atm, "step": step,
            "expiry": exp, "trade_expiry": trade_exp, "expiries": expiries,
            "lot": lot, "budget": round(budget, 2), "rows": rows,
            "has_oi": any((r.get(sd) or {}).get("oi") is not None for r in rows for sd in ("CE", "PE")),
            "pins": [{"side": k[1], **v} for k, v in eng.pins.items() if k[0] == u],
            "day_mode": eng.day_mode,
            "default_mode": {"mode": "ITM", "depth": int(s["itm_depth"])},
            "status": market_status(now), "as_on": now}
