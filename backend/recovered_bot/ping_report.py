"""Ping Lab report: ONE text file that explains the Ping Lab to any other AI.

What was built, where the idea came from, why, how it works, the real numbers so far,
and an honest verdict (profit or not, useful or not, how reliable).

Read-only: it only reads ping_state.json / ping_trades.json / ping_lead.json written by
ping_worker.py. It never touches the live bot, owl.db or any bot file. Never raises.
"""
import os
import time
from collections import defaultdict
from datetime import datetime, timezone

from . import ping_store

# ---- constants (starting guesses) ----
FEE_ROUND_TRIP_PCT = 0.08      # assumed futures taker fee, both sides, on the position (not on margin)
MIN_TRADES_RELIABLE = 30       # fewer closed paper trades than this = "not enough to judge"
MIN_TRADES_PER_VARIANT = 10
RECENT_TRADES_SHOWN = 25
STALE_AFTER_SEC = 10.0

_PROMPT = """HOW TO USE THIS FILE (for the AI reading it)
This is a report from a PAPER-ONLY test called "Ping Lab" inside a crypto trading app. No real money is used.
Please read it and answer, in simple words:
1. Do you understand what was built, why, and how it works?
2. Do the numbers show a profit after fees? Is the sample big enough to trust? (be strict)
3. Is the ping idea useful as a FILTER for the main bot's signals (Score tab) and as an EARLY WARNING for top-10 coins (Lead tab)?
4. What is the single most important thing to test or fix next? Do not suggest adding many features.
"""

_ABOUT = """1. WHAT WAS BUILT
Ping Lab = a separate, paper-only test system that rebuilds an old "volume ping" website idea.
A ping = one closed 1-minute candle where the NET taker volume (buy volume minus sell volume, in USDT)
is far bigger than normal for that coin. Positive net = BUY ping, negative net = SELL ping.
It runs as its own process (ping_worker.py), in parallel with the live bot, and only READS the live bot's signals.
It never changes, closes or opens any live bot trade, and it is kept away from AI Vision.

2. WHERE THE IDEA CAME FROM
The owner used the CryptoZyzz "Binance Volume Monitor" website (now dead): 1-minute net volume pings,
colour yellow at 3 pings and red at 5 pings in the hour, counters reset every hour.
Because the site is gone, the rules were rebuilt from his old screenshots and then checked against fresh screenshots.

3. WHY IT WAS BUILT
- Fewer fake signals: the main bot enters on an EMA50 cross, and many of those fail. Question: would a same-side ping have warned us?
- Catch coins EARLIER: the owner watches a fixed daily top-10 gainers / top-10 losers list. Question: does a ping show up BEFORE a coin enters that list?
- Test only. Nothing here is a trading recommendation until the numbers prove it.
"""

_HOW = """4. HOW IT WORKS (data flow)
Binance futures WebSocket (/market URLs)
  -> radar (miniTicker of all coins: price, 24h change -> daily top gainers / losers, watchlist)
  -> collector (1m klines of watchlist + candidate coins, 100 candles of history fetched first)
  -> engine (detects pings, counts them per 5m / 15m / 60m / hour, colour, "absorbed" flag, EMA30 / EMA50)
  -> Ping Bot (paper trades) + Tracker (Lead + Score)  -> ping_state.json (every ~2 s)
  -> backend routes /api/ping/* -> app Ping tab (Live / Bot / Score / Lead).

Files: backend/ping_worker.py (own process), backend/recovered_bot/ping_radar.py, ping_collector.py, ping_engine.py,
ping_bot.py, ping_tracker.py, ping_signal_bridge.py, ping_store.py, ping_api.py, ping_report.py (this file),
frontend/lib/screens/ping_tab_screen.dart, frontend/lib/widgets/ping_widgets.dart.
"""


def _g(mod, name, default):
    try:
        return getattr(mod, name)
    except Exception:
        return default


def _rules_text():
    try:
        from . import ping_engine as E
        from . import ping_bot as B
    except Exception as e:
        return f"5. RULES\n(could not load the rule constants: {type(e).__name__})\n"
    sl = f"{_g(B, 'SL_MIN_PCT', '?')}% to {_g(B, 'SL_MAX_PCT', '?')}%"
    return (
        "5. THE RULES (live values read from the code)\n"
        f"Ping: closed 1m candle with |net taker volume| >= max({_g(E, 'PING_MIN_USDT', '?')} USDT, {_g(E, 'PING_Z', '?')} x median of recent net volume).\n"
        f"Colour: yellow at {_g(E, 'YELLOW_MIN', '?')} pings, red at {_g(E, 'RED_MIN', '?')} pings in the same hour (hour counters reset every hour).\n"
        f"Absorbed: >= {_g(E, 'ABSORB_PINGS', '?')} pings in {int(_g(E, 'ABSORB_WINDOW_SEC', 0)) // 60} min but price moved less than {_g(E, 'ABSORB_MOVE_PCT', '?')}%.\n"
        "Ping Bot variants (each variant trades LONG and SHORT, paper only):\n"
        f"  A = ping + price on the right side of EMA30   (needs {_g(B, 'EMA_READY_FAST', '?')} closed 1m candles first)\n"
        f"  B = ping + price on the right side of EMA50   (needs {_g(B, 'EMA_READY_SLOW', '?')} closed 1m candles first)\n"
        "  C = ping only (no EMA)\n"
        f"Entry: >= {_g(B, 'ENTRY_PINGS_5M', '?')} same-side pings in 5 min AND >= {_g(B, 'ENTRY_PINGS_15M', '?')} in 15 min, 5-min net volume has the same sign,\n"
        f"  not chased (move since first ping <= {_g(B, 'MAX_CHASE_PCT', '?')}%), not absorbed.\n"
        f"Stop loss: last {_g(B, 'SL_LOOKBACK', '?')} 1m lows (LONG) / highs (SHORT), limited to {sl} from entry.\n"
        "Targets: TP1..TP4 at 1R, 2R, 3R, 4R (R = entry-to-SL distance), 25% of the position closed at each.\n"
        "SL ladder: after TP1 SL -> entry, after TP2 SL -> TP1, after TP3 SL -> TP2, TP4 closes everything.\n"
        f"Other exits: 'signal' (5m net flips against the trade and price is on the wrong side of EMA30), 'time_stop' ({_g(B, 'TIME_STOP_MIN', '?')} min with no TP hit).\n"
        f"Size: {_g(B, 'MARGIN_USDT', '?')} USDT margin x {_g(B, 'LEVERAGE', '?')}x leverage per trade, max {_g(B, 'PING_MAX_OPEN', '?')} open per variant. SHORT is marked experimental.\n"
        "Score tab: for every NEW live-bot (Bot 1) signal the worker asks 'what did the ping look like then?' -> TAKE (same-side yellow/red ping) or SKIP.\n"
        "  Later it attaches the real paper result of that signal. loss avoided = losses of SKIPPED signals; profit missed = profits of SKIPPED signals.\n"
        "Lead tab: when a coin enters today's top-10 gainers / losers, did it already have a same-side ping, and how many minutes earlier (lead time)?\n"
    )


def _mt(m):
    """minutes -> text, over 60 min = hours + minutes (owner rule)"""
    try:
        from timefmt import mins as _fm
        return _fm(m) if _fm(m) != "-" else "--"
    except Exception:
        return _f(m, 1) + " min"


def _f(v, d=2):
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "--"


def _ts(v):
    try:
        return datetime.fromtimestamp(float(v), timezone.utc).strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return "--"


def _num(v):
    try:
        x = float(v or 0.0)
        return x if x == x and abs(x) != float("inf") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _stats(trades):
    n = len(trades)
    pcts = [_num(t.get("pnl_pct")) for t in trades]
    usdt = [_num(t.get("pnl_usdt")) for t in trades]
    wins = sum(1 for p in pcts if p > 0)
    gross = sum(pcts)
    net = sum(p - FEE_ROUND_TRIP_PCT for p in pcts)
    holds = []
    for t in trades:
        try:
            holds.append((float(t["exit_ts"]) - float(t["opened_ts"])) / 60.0)
        except (KeyError, TypeError, ValueError):
            pass
    return {
        "n": n,
        "wins": wins,
        "win_pct": (100.0 * wins / n) if n else None,
        "gross_pct": gross,
        "net_pct": net,
        "usdt": sum(usdt),
        "avg_hold": (sum(holds) / len(holds)) if holds else None,
    }


def _stat_line(label, st):
    if not st["n"]:
        return f"  {label}: 0 closed trades"
    return (f"  {label}: {st['n']} closed, win {_f(st['win_pct'], 0)}%, gross {_f(st['gross_pct'])}% , "
            f"after est. fees {_f(st['net_pct'])}% (sum of trade %), approx {_f(st['usdt'])} USDT, avg hold {_mt(st['avg_hold'])}")


def _bot_section(closed, snap_bot):
    out = ["7. PING BOT RESULTS (paper, closed trades)"]
    out.append(f"Closed trades stored: {len(closed)}. Open now: {len((snap_bot or {}).get('open') or [])}.")
    out.append(f"Fee assumption: {FEE_ROUND_TRIP_PCT}% round trip on the position, applied per trade. Prices are the last price at trigger (no slippage).")
    out.append(_stat_line("ALL", _stats(closed)))
    for v in ("A", "B", "C"):
        out.append(_stat_line(f"Variant {v}", _stats([t for t in closed if t.get("variant") == v])))
    for s in ("LONG", "SHORT"):
        out.append(_stat_line(f"Side {s}", _stats([t for t in closed if t.get("side") == s])))
    reasons = defaultdict(int)
    for t in closed:
        reasons[str(t.get("exit_reason") or "?")] += 1
    if reasons:
        out.append("  Exit reasons: " + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])))
    coins = {t.get("symbol") for t in closed}
    out.append(f"  Different coins traded: {len(coins)}. Note: A, B and C often enter the SAME ping at the same price, so one real event can show up as 2-3 similar trades.")
    skips = (snap_bot or {}).get("skips_recent") or []
    if skips:
        sk = defaultdict(int)
        for s in skips:
            sk[str(s.get("reason") or "?")] += 1
        out.append("  Recent skipped entries (reason): " + ", ".join(f"{k} {v}" for k, v in sk.items()))
    out.append(f"  Last {RECENT_TRADES_SHOWN} closed trades (newest first): time UTC | coin | variant | side | exit | pnl%")
    for t in closed[:RECENT_TRADES_SHOWN]:
        out.append(f"    {_ts(t.get('exit_ts'))} | {t.get('symbol')} | {t.get('variant')} | {t.get('side')} | {t.get('exit_reason')} | {_f(t.get('pnl_pct'))}%")
    return "\n".join(out)


def _score_section(score):
    s = score or {}
    out = ["8. SCORE: PING vs THE LIVE BOT'S SIGNALS (Bot 1)"]
    out.append(f"Signals compared: {s.get('signals_total', 0)}. TAKE (ping agreed): {s.get('take_count', 0)}. SKIP (no same-side ping): {s.get('skip_count', 0)}.")
    out.append(f"Loss avoided by skipping: {_f(s.get('loss_avoided'))}. Profit missed by skipping: {_f(s.get('profit_missed'))}. Net effect: {_f(s.get('net_effect'))} (positive = ping filter would have helped).")
    out.append(f"Tracker verdict: {s.get('sentence', '--')}")
    reasons = defaultdict(int)
    for r in (s.get("rows") or []):
        if r.get("verdict") == "SKIP":
            reasons[str(r.get("reason") or "?")] += 1
    if reasons:
        out.append("Why signals were skipped: " + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])))
    out.append("Caution: only signals that arrived AFTER the worker started are compared (older ones had no ping data), so right after any restart/reset 'SKIP' is common just because there was no ping history yet.")
    return "\n".join(out)


def _lead_section(lead):
    L = lead or {}
    out = ["9. LEAD: DID A PING COME BEFORE THE COIN ENTERED TODAY'S TOP 10?"]
    out.append(f"Today's top-10 entries seen: {L.get('today_count', 0)}. With a same-side ping before entry: {_f(L.get('with_ping_pct'), 1)}%. Average lead time: {_f(L.get('avg_lead_min'), 1)} min.")
    out.append(f"Tracker sentence: {L.get('sentence', '--')}")
    out.append("Caution: coins already in the top 10 when the worker starts are NOT counted as entries. A low % early in the day or right after a reset mostly reflects missing history, not a weak idea.")
    return "\n".join(out)


def _health_section(snap):
    out = ["10. HEALTH OF THE WORKER"]
    if not snap:
        out.append("No snapshot file found. The ping worker is not running or has never written data.")
        return "\n".join(out)
    h = snap.get("health") or {}
    try:
        age = time.time() - float(snap.get("ts"))
    except (TypeError, ValueError):
        age = None
    stale = age is None or age > STALE_AFTER_SEC
    out.append(f"Snapshot age: {_f(age, 1)} s ({'STALE - worker probably stopped' if stale else 'fresh'}).")
    out.append(f"Build: {h.get('build_tag')}. WebSocket: {h.get('ws_state')}. Uptime: {_f(h.get('uptime_sec'), 0)} s. Last message age: {_f(h.get('last_msg_age_sec'), 1)} s.")
    out.append(f"Coins in radar: {h.get('radar_coins')}. Candidate coins with 1m data: {h.get('candidate_count')}. Radar messages: {h.get('radar_msgs')}. Kline messages: {h.get('kline_msgs')}.")
    out.append(f"Link to live-bot signals (read-only): {h.get('signal_link')}.")
    rows = snap.get("rows") or []
    buy = sum(1 for r in rows if isinstance(r, dict) and r.get("side") == "BUY")
    sell = sum(1 for r in rows if isinstance(r, dict) and r.get("side") == "SELL")
    red = sum(1 for r in rows if isinstance(r, dict) and r.get("color") == "red")
    out.append(f"Coins with a ping right now: {len(rows)} ({buy} BUY, {sell} SELL, {red} red). Watchlist size: {len(snap.get('watchlist') or [])}.")
    return "\n".join(out)


def _verdict(closed, score):
    n = len(closed)
    st = _stats(closed)
    lines = ["11. HONEST VERDICT (generated by simple rules, not by an AI)"]
    if n < MIN_TRADES_RELIABLE:
        lines.append(f"- NOT ENOUGH DATA: only {n} closed paper trades (need at least {MIN_TRADES_RELIABLE}, better 100+). No profit or loss claim can be trusted yet.")
    elif st["net_pct"] > 0:
        lines.append(f"- Ping Bot is POSITIVE after est. fees ({_f(st['net_pct'])}% summed over {n} trades). Still paper only; check it holds on different days and market moods.")
    else:
        lines.append(f"- Ping Bot is NOT profitable after est. fees ({_f(st['net_pct'])}% summed over {n} trades). Do not use it to trade.")
    for v in ("A", "B", "C"):
        sv = _stats([t for t in closed if t.get("variant") == v])
        if 0 < sv["n"] < MIN_TRADES_PER_VARIANT:
            lines.append(f"- Variant {v}: only {sv['n']} trades, too few to compare with the others.")
    s = score or {}
    total = int(s.get("signals_total") or 0)
    if total < 30:
        lines.append(f"- Score filter: only {total} live-bot signals compared (need 30+). Cannot say yet if pings would have avoided bad signals.")
    else:
        net = float(s.get("net_effect") or 0.0)
        lines.append("- Score filter: " + ("skipping by ping would have HELPED (more loss avoided than profit missed)." if net > 0 else "skipping by ping would NOT have helped (it would have missed more profit than the loss it avoided)."))
    lines.append("- Benefit today: this is a test tool. It becomes useful only if (a) Score shows a clear positive net effect over many signals, or (b) Lead shows pings arriving well before top-10 entry for a good share of coins.")
    return "\n".join(lines)


_LIMITS = """12. KNOWN LIMITS (be honest about these)
- Paper only. Entry = last price at trigger, no slippage, no order-book depth, no partial fills.
- pnl% per trade is price move only; the fee line is an ASSUMPTION (0.08% round trip). Real fees/funding may differ.
- pnl USDT is approximate (remaining size after partial TPs is estimated).
- Variants A, B, C share the same ping events, so trades are NOT independent. Count events, not trades.
- Binance retired the old futures WebSocket URLs on 2026-04-23; the worker uses the /market URLs.
- Score / Lead data was reset on 2026-10-23 after fixes, so history is short.
- The old website's exact thresholds are unknown; constants here are starting guesses rebuilt from screenshots.
- SHORT side is experimental.
"""


def _read_all():
    snap = ping_store.read_state() or {}
    trades = ping_store.read_trades() or {}
    closed = [t for t in (trades.get("closed") or []) if isinstance(t, dict)]
    return snap, closed


def build_text():
    parts = [f"OWL PING LAB REPORT - made {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", ""]
    try:
        snap, closed = _read_all()
    except Exception as e:
        return "\n".join(parts) + f"Could not read the ping files: {type(e).__name__}: {e}\n"
    sections = [
        lambda: _PROMPT, lambda: _ABOUT, lambda: _HOW, _rules_text,
        lambda: "6. CURRENT STATE\n(see sections 7-10)\n",
        lambda: _bot_section(closed, snap.get("bot")),
        lambda: _score_section(snap.get("score")),
        lambda: _lead_section(snap.get("lead")),
        lambda: _health_section(snap),
        lambda: _verdict(closed, snap.get("score")),
        lambda: _LIMITS,
    ]
    for fn in sections:
        try:
            parts.append(fn())
        except Exception as e:                     # one broken section must not kill the report
            parts.append(f"(section failed: {type(e).__name__})")
        parts.append("")
    return "\n".join(parts)


def _download_dirs():
    c = [os.environ.get("OWL_DOWNLOAD_DIR"), os.path.expanduser("~/storage/downloads"), "/sdcard/Download", "/storage/emulated/0/Download"]
    return [d for d in c if d]


def save_to_downloads(text=None):
    """Writes the report into the phone's Download folder. -> {"ok", "path", "bytes", "hint"}"""
    text = text if text is not None else build_text()
    name = "owl_ping_report_" + datetime.now().strftime("%Y%m%d_%H%M") + ".txt"
    for d in _download_dirs():
        try:
            if os.path.isdir(d) and os.access(d, os.W_OK):
                path = os.path.join(d, name)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                return {"ok": True, "path": path, "bytes": len(text.encode("utf-8")), "hint": ""}
        except Exception:
            continue
    path = ""
    try:                                           # fallback: next to the bot's data so nothing is lost
        base = os.path.expanduser(os.environ.get("OWL_DATA_DIR") or "~/owl_data")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        path = ""
    return {"ok": False, "path": path, "bytes": len(text.encode("utf-8")),
            "hint": "Phone Download folder is not reachable from Termux. Run  termux-setup-storage  once, allow storage, then press Download again."}
