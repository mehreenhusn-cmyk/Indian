"""india_reports.py - P&L reports over the closed-trade list (terminal 'Trades' tab)."""
import csv
import io
from datetime import date, timedelta


def _d(x):
    if x is None or x == "":
        return None
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def filter_trades(closed, start=None, end=None, underlying=None, reason=None):
    a, b = _d(start), _d(end)
    out = []
    for t in closed:
        d = t["closed_at"].date()
        if a and d < a or b and d > b:
            continue
        if underlying and t["underlying"] != underlying.upper():
            continue
        if reason and t["reason"] != reason:
            continue
        out.append(t)
    return out


def totals(trades):
    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gp, gl = sum(t["pnl"] for t in wins), -sum(t["pnl"] for t in losses)
    return {"trades": n, "wins": len(wins), "win_pct": round(100 * len(wins) / n, 1) if n else 0.0,
            "gross": round(sum(t["gross_pnl"] for t in trades), 2),
            "fees": round(sum(t["fees"] for t in trades), 2),
            "net": round(sum(t["pnl"] for t in trades), 2),
            "best": round(max((t["pnl"] for t in trades), default=0), 2),
            "worst": round(min((t["pnl"] for t in trades), default=0), 2),
            "profit_factor": round(gp / gl, 2) if gl else None}


def period_summary(closed, today):
    """Today / last 7 days / last 30 days (counted back from `today` = the engine's own date)."""
    out = {}
    for key, back in (("today", 0), ("d7", 6), ("d30", 29)):
        tr = filter_trades(closed, start=today - timedelta(days=back), end=today)
        out[key] = totals(tr)
    return out


def daily_summary(trades):
    days = {}
    for t in trades:
        d = t["closed_at"].date().isoformat()
        r = days.setdefault(d, {"date": d, "trades": 0, "wins": 0, "gross": 0.0, "fees": 0.0, "net": 0.0})
        r["trades"] += 1
        r["wins"] += 1 if t["pnl"] > 0 else 0
        r["gross"] += t["gross_pnl"]
        r["fees"] += t["fees"]
        r["net"] += t["pnl"]
    return [{**r, "gross": round(r["gross"], 2), "fees": round(r["fees"], 2),
             "net": round(r["net"], 2)} for r in sorted(days.values(), key=lambda r: r["date"])]


def equity_curve(trades, capital):
    eq, out = float(capital), []
    for t in sorted(trades, key=lambda t: t["closed_at"]):
        eq += t["pnl"]
        out.append({"t": t["closed_at"].isoformat(), "equity": round(eq, 2)})
    return out


def breakdown(trades):
    by = {}
    for t in trades:
        k = f"{t['underlying']} {t['contract']['strike']} {t['contract']['type']}"
        r = by.setdefault(k, {"contract": k, "trades": 0, "net": 0.0})
        r["trades"] += 1
        r["net"] += t["pnl"]
    return sorted(({**r, "net": round(r["net"], 2)} for r in by.values()), key=lambda r: -abs(r["net"]))


def trades_csv(trades):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "underlying", "contract", "side", "qty", "product", "tag", "opened_at",
                "closed_at", "entry_premium", "exit_premium", "entry_spot", "exit_spot",
                "reason", "gross_pnl", "fees", "net_pnl"])
    for t in trades:
        w.writerow([t["id"], t["underlying"], t["contract"]["key"], t["action"], t["qty"],
                    t.get("product", ""), t.get("tag", ""), t["opened_at"], t["closed_at"],
                    t["entry_premium"], t["exit_premium"], round(t["entry_spot"], 2),
                    round(t["exit_spot"], 2), t["reason"], t["gross_pnl"], t["fees"], t["pnl"]])
    return buf.getvalue()
