"""india_stats.py - numbers for the India "Stats" tab, from the paper engine's closed trades.

Pure Python, read-only. All money is Rs after charges (the engine's `pnl` already has brokerage / STT / etc. taken off).
  win_rate, avg_win / avg_loss, rr (average win / average loss), expectancy (Rs per trade), profit_factor,
  net_pnl, fees, max_drawdown (Rs and % of the highest equity), equity curve, split by index / CE-PE / exit reason.
"""
from collections import Counter


def _f(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def _curve(points, keep=160):
    if len(points) <= keep:
        return points
    step = len(points) / float(keep)
    out = [points[int(i * step)] for i in range(keep - 1)]
    out.append(points[-1])
    return out


def _group(trades, key):
    g = {}
    for t in trades:
        g.setdefault(key(t), []).append(t)
    out = []
    for k, rows in sorted(g.items(), key=lambda kv: str(kv[0])):
        n = len(rows)
        w = sum(1 for r in rows if _f(r.get("pnl")) > 0)
        out.append({"label": str(k), "n": n, "win_rate": round(100.0 * w / n, 1),
                    "net": round(sum(_f(r.get("pnl")) for r in rows), 2)})
    return out


def build(closed, capital):
    trades = [t for t in (closed or []) if t.get("pnl") is not None]
    n = len(trades)
    out = {"ok": True, "trades": n, "capital": _f(capital)}
    if n == 0:
        out.update({"wins": 0, "losses": 0, "win_rate": 0.0, "net_pnl": 0.0, "fees": 0.0, "curve": []})
        return out
    pnl = [_f(t["pnl"]) for t in trades]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    wr = len(wins) / n
    gross_win, gross_loss = sum(wins), -sum(losses)
    eq, peak, max_dd, max_dd_pct, curve = _f(capital), _f(capital), 0.0, 0.0, []
    run_w = run_l = best_w = best_l = 0
    for t, x in zip(trades, pnl):
        eq += x
        peak = max(peak, eq)
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd / peak * 100.0 if peak else 0.0
        curve.append({"t": str(t.get("closed_at", ""))[:16], "v": round(eq, 2)})
        if x > 0:
            run_w, run_l = run_w + 1, 0
        elif x < 0:
            run_l, run_w = run_l + 1, 0
        best_w, best_l = max(best_w, run_w), max(best_l, run_l)
    out.update({
        "wins": len(wins), "losses": len(losses), "win_rate": round(wr * 100.0, 1),
        "net_pnl": round(sum(pnl), 2), "fees": round(sum(_f(t.get("fees")) for t in trades), 2),
        "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2),
        "rr": round(avg_win / abs(avg_loss), 2) if avg_loss else None,
        "expectancy": round(wr * avg_win + (1 - wr) * avg_loss, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "max_drawdown": round(max_dd, 2), "max_drawdown_pct": round(max_dd_pct, 2),
        "best_trade": round(max(pnl), 2), "worst_trade": round(min(pnl), 2),
        "max_win_streak": best_w, "max_loss_streak": best_l,
        "curve": _curve(curve),
        "by_index": _group(trades, lambda t: t.get("underlying")),
        "by_side": _group(trades, lambda t: "CE (call)" if t.get("action") == "LONG" else "PE (put)"),
        "by_exit": [{"label": k, "n": v} for k, v in Counter(str(t.get("reason")) for t in trades).most_common()],
    })
    return out
