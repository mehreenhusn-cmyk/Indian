"""
ai_notebook_digest.py - a short "use it this way" digest for the Vision Notebook.

Plain counting only (nothing predicted, nothing invented):
  1. The AI's own closed trades: bot-signal trades vs AI Own trades, long vs short, how they exited.
  2. The pump / dump memory (ai_pumpdump): what usually happened after a pump or a dump.
Every number carries its sample size. Below MIN_N the line says "too few yet" and the
"use it this way" advice stays neutral. It only READS; it never changes, blocks or closes a trade.
"""
MIN_N = 20


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _group(trades):
    n = len(trades)
    wins = sum(1 for t in trades if _f(t.get("pnl")) > 0)
    net = round(sum(_f(t.get("pnl")) for t in trades), 2)
    return {"n": n, "wins": wins, "win_rate": round(100.0 * wins / n) if n else None, "net": net}


def _line(label, g):
    if g["n"] == 0:
        return f"{label}: no finished trades yet."
    small = " Too few trades to trust yet." if g["n"] < MIN_N else ""
    return f"{label}: {g['n']} trades, {g['wins']} won ({g['win_rate']}%), net {g['net']:+.2f} USDT.{small}"


def _exit_kind(t):
    r = str(t.get("exit_reason") or "").lower()
    if "stop" in r or "sl" in r.split():
        return "stop"
    if "target" in r or "tp" in r.split():
        return "target"
    if "ai exit" in r:
        return "ai_exit"
    return "other"


def build(V):
    with V._lock:
        trades = [dict(t) for t in V._state.get("trades", []) if t.get("status") == "closed"]
    bot = [t for t in trades if (t.get("source") or "bot") != "own"]
    own = [t for t in trades if (t.get("source") or "bot") == "own"]
    longs = [t for t in trades if t.get("side") == "BUY"]
    shorts = [t for t in trades if t.get("side") == "SELL"]
    gb, go, gl, gs = _group(bot), _group(own), _group(longs), _group(shorts)
    exits = {}
    for t in trades:
        k = _exit_kind(t)
        e = exits.setdefault(k, {"n": 0, "net": 0.0})
        e["n"] += 1
        e["net"] += _f(t.get("pnl"))
    trade_lines = [_line("Bot signals taken by the AI", gb), _line("AI Own trades", go),
                   _line("Longs", gl), _line("Shorts", gs)]
    names = {"stop": "closed on the stop", "target": "closed on the target", "ai_exit": "closed by an AI exit", "other": "closed another way"}
    for k in ("stop", "target", "ai_exit", "other"):
        if k in exits:
            trade_lines.append(f"{exits[k]['n']} trades {names[k]}, net {exits[k]['net']:+.2f} USDT.")

    pump_lines, pd = [], {}
    try:
        from . import ai_pumpdump
        pd = ai_pumpdump.snapshot(1)
        pump_lines = list(pd.get("plain") or [])
    except Exception:
        pass

    use = []
    if len(trades) < MIN_N:
        use.append(f"Only {len(trades)} finished AI trades so far. Treat everything below as a hint, not a rule (needs {MIN_N}+).")
    else:
        if go["n"] >= MIN_N and gb["n"] >= MIN_N and go["net"] < 0 <= gb["net"]:
            use.append("AI Own is losing while bot-signal trades are not. Keep AI Own on paper only.")
        if gl["n"] >= MIN_N and gs["n"] >= MIN_N and abs((gl["win_rate"] or 0) - (gs["win_rate"] or 0)) >= 15:
            better = "longs" if (gl["win_rate"] or 0) > (gs["win_rate"] or 0) else "shorts"
            use.append(f"{better.capitalize()} win clearly more often. Look at why before trusting the weaker side.")
        st = exits.get("stop")
        if st and st["n"] >= MIN_N and st["net"] < 0 and st["n"] > 0.5 * len(trades):
            use.append("More than half the trades end on the stop. Check entries and stop distance, not only the AI.")
    by = (pd.get("stats") or {}).get("by_kind") or {}
    for kind, word in (("pump", "pump"), ("dump", "dump")):
        d = by.get(kind) or {}
        n = int(d.get("n") or 0)
        if n < MIN_N:
            use.append(f"After a {word}: only {n} events so far, so no rule yet. Do not trade on it.")
            continue
        rev, cont = int(d.get("reverse", 0)), int(d.get("continue", 0))
        if rev >= 0.5 * n:
            use.append(f"After a {word} it reversed in {round(100.0 * rev / n)}% of {n} events: do not chase, wait for a reversal sign.")
        elif cont >= 0.5 * n:
            use.append(f"After a {word} it continued in {round(100.0 * cont / n)}% of {n} events: the move often goes on, use the stop-trail.")
        else:
            use.append(f"After a {word} the result is mixed over {n} events: no clear edge.")
    if not use:
        use.append("Nothing stands out yet. Keep collecting trades.")
    return {"ok": True, "closed_n": len(trades), "min_n": MIN_N,
            "trade_lines": trade_lines, "pump_lines": pump_lines, "use": use}
