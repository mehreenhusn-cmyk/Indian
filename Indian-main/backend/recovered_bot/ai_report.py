"""
ai_report.py - ONE text file with everything an outside AI needs to understand the bot's problem and suggest fixes.
Read-only: it only READS closed trades, settings (secrets left out), the Strategy Doctor and the Filter Lab results.

Open  http://127.0.0.1:8000/api/report  in the phone browser -> it downloads owl_report.txt -> send that file to any AI.
"""
import math
import time
from datetime import datetime, timezone

_SECRET_WORDS = ("key", "secret", "token", "pass", "chat", "auth", "pin", "license")

PROMPT = """READ ME FIRST (instructions for the AI that receives this file)
The owner trades with a bot (paper mode) built on TWO TradingView indicators and is losing money. He is not a coder.
Please answer in simple Hinglish (Hindi in English letters, short sentences), with numbers from THIS file only (do not invent figures):
 1. Where exactly does the strategy lose money? START with the 'LEAKAGE SUMMARY' section (already calculated), then check it against
    the Doctor, the Filter Lab and the trade table (zones, timeframes, hold times, fees, coins, sides). Name the 3 biggest leaks with numbers.
 2. Which of the two indicators' readings (SD bands + EMA50 from 'Special 13'; TSI + Z-score from 'Special Master') could filter
    the bad entries, and which could not? Say clearly when the data is too small or when a pattern is not confirmed.
 3. What 2-3 concrete rule changes would you test first (entry filter, stop-loss placement, exit/profit booking, timeframe)?
    For each: why, what data in this file supports it, and how to test it on paper before using it.
 4. DIRECTION vs STOP-LOSS: the owner suspects the entry direction is often right and only the SL is too tight. Use the Filter Lab's
    'DIRECTION CHECK' and 'STOP-LOSS TEST' sections plus the Doctor's 'in profit first' numbers: how often was the direction right?
    Does a wider SL (previous candle / last 3 candles / swing / ATR) or 'SL to entry + fee buffer after TP1' really pay AFTER fees,
    in BOTH the older and the newer half? Say which SL variant to try on paper first and why.
 5. Bollinger Band filters (separate section): which one, if any, avoids losses without missing profits ('loss avoided' vs 'profit missed')?
 6. What data is missing that would settle the open questions?
Be honest: if the evidence says 'no clear edge', say so.
"""

STRATEGY = """THE BOT'S STRATEGY (exactly as coded in strategy.py)
- Entry: close of a CLOSED candle crosses EMA50 (up = BUY, down = SELL). Timeframes used: 3m, 5m, 15m. Coins: Binance futures top gainers/losers.
- Stop-loss: the signal candle's LOW (BUY) or HIGH (SELL) - often very tight.
- Targets: TP1..TP4 are the next SD levels (mean, +-1SD, +-2SD, +-3SD of a 200-candle rolling mean/std of closes) beyond the entry price.
  Default exit target = TP4; stop-loss moves to entry after TP1 is touched; opposite EMA50 cross ends the trade.
- Leverage 10x; fee about 1% of ROI per trade (price move 0.1% round trip) - at 10x a trade must gain about +1 ROI point just to pay the fee.
- Z-score and TSI are NOT used by the bot to allow or block trades (they were only recorded on new trades).
"""

INDICATORS = """THE TWO INDICATORS
- Special 13 (main chart): 200-candle SMA with +-1/2/3 SD bands, EMA50 (entry), entry/SL/TP1-4 table.
- Special Master (lower pane): Z-score = (close - SMA200)/STDEV200 (so it is the price position inside the same SD bands, in SD units);
  TSI (25/13/13 slow) with signal line; histogram = TSI - signal; reversal-warning arrows (histogram shrinking + Z turning from beyond +-1).
- Because Z is just the position inside the SD bands, 'Z>0' means price is above the mean line, so Z and the SD zone carry mostly the SAME information.
"""

GLOSSARY = """HOW TO READ THE NUMBERS (simple words)
- ROI points: profit or loss as % of the money put in (at 10x leverage a 0.1% price move = 1 ROI point). Fee is already inside.
- USDT columns in the trade table are the reliable money numbers.
- SD zone / Z-score: where price sits inside the 200-candle mean +-1/2/3 SD bands. Z>0 = above the mean line.
- TSI: momentum line; 'TSI with trade' = histogram (TSI minus its signal line) points the same way as the trade.
- BE: after TP1 the stop-loss moves to entry (a 'BE' exit is about zero before fees, so after fees it is a small loss).
- SKIP group in the Doctor: trades that fall in the zones the Doctor suggests avoiding (not a rule the bot follows).
- 'Confirmed' = helped in BOTH the older and the newer part of the data. Many ideas are tested on the same data, so keep a confirmed idea on paper first.
- 'Loss avoided' / 'profit missed' = what a rule would have saved and what it would have given up.
"""

CAVEATS = """DATA CAVEATS
- Doctor/CSV: real paper trades. ROI is in ROI points (% of money put in, fee inside); USDT columns are the reliable money numbers.
- Trades with |ROI| > 400 points are dropped as bad price ticks.
- TSI/Z were not recorded at entry on older trades, so the Doctor cannot test them; the Filter Lab replay does (on Binance candles, no slippage).
- SL test = the same signals replayed with another SL; signals are treated one by one (no max-open limit, no slippage).
- Filter Lab = replay of the same strategy on the last days of candles; many filters are tested on the same data, so one lucky 'CONFIRMED' is possible.
"""


def _num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _iso(ts):
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _settings():
    try:
        from . import settings_store
        d = settings_store.get_all() or {}
    except Exception:
        return "settings: not readable"
    lines = []
    for k in sorted(d):
        if any(w in k.lower() for w in _SECRET_WORDS):
            continue
        v = d[k]
        if isinstance(v, (str, int, float, bool)) or v is None:
            lines.append(f"  {k} = {v}")
    return "SETTINGS (secrets left out)\n" + "\n".join(lines[:120])


def _doctor_text(rep):
    if not isinstance(rep, dict) or not rep.get("ok"):
        return "STRATEGY DOCTOR: not available"
    L = ["STRATEGY DOCTOR SUMMARY"]
    ov = rep.get("overall") or {}
    L.append(f"  trades {ov.get('n')}, win rate {ov.get('win_rate')}%, net {ov.get('net_pnl')} USDT, fees {ov.get('fee_total')} USDT")
    for h in rep.get("headline") or []:
        L.append("  - " + str(h))
    ls = rep.get("loss_story") or {}
    L.append(f"  loss story: losers {ls.get('losers')}, never green {ls.get('never_green')}, green then lost {ls.get('green_then_lost')}, "
             f"hit TP1 then lost {ls.get('hit_tp1_then_lost')}, avg peak of losers {ls.get('avg_peak_green_losers')} ROI pts")
    for ln in (rep.get("post_exit") or {}).get("lines") or []:
        L.append("  post-exit: " + str(ln))
    L.append("  SD ZONE AT ENTRY (n, win%, avg ROI pts, USDT):")
    for z in rep.get("sd_zones") or []:
        for side in ("buy", "sell"):
            s = z.get(side) or {}
            if s.get("n"):
                L.append(f"    {z['zone']:12s} {side.upper():4s} n={s['n']:4d} win={s['wr']:5.1f}% avg={s['avg']:+7.2f} usdt={s['usdt']:+8.1f}")
    for r in rep.get("sd_rules") or []:
        b = r.get("blocked") or {}
        k = r.get("kept") or {}
        L.append(f"  rule '{r.get('label')}': blocked n={b.get('n')} usdt={b.get('usdt')} | kept n={k.get('n')} usdt={k.get('usdt')}")
    for m in rep.get("mistakes") or []:
        L.append(f"  {m.get('title')}:")
        for b in m.get("buckets") or []:
            L.append(f"    {b['label']}: n={b['n']} win={b['wr']}% avg={b['avg']}")
    for kind in ("avoid", "take"):
        for a in rep.get(kind) or []:
            L.append(f"  {kind.upper()} candidate: {a.get('title')} / {a.get('label')} status={a.get('status')} "
                     f"train avg {a.get('avg_train')} (n {a.get('n_train')}) test avg {a.get('avg_test')} (n {a.get('n_test')})")
    v = rep.get("verdict") or {}
    for key, title in (("hold", "HOLD TIME"), ("timeframe", "TIMEFRAME"), ("side", "SIDE"), ("time_of_day", "TIME OF DAY"), ("entry_zone", "ENTRY ZONE")):
        rows = v.get(key) or []
        if rows:
            L.append(f"  {title}:")
            for r in rows:
                L.append(f"    {r.get('label')}: n={r.get('n')} win={r.get('win_rate')}% avg={r.get('avg_roi')} net={r.get('net')} ({r.get('status')})")
    idx = [r for r in (v.get("index") or []) if (r.get("n") or 0) >= 8]
    idx.sort(key=lambda r: r.get("net") or 0)
    if idx:
        L.append("  COINS with 8+ trades, worst 8 and best 5 by net USDT:")
        for r in idx[:8] + idx[-5:]:
            L.append(f"    {r['label']}: n={r['n']} win={r['win_rate']}% net={r['net']}")
    return "\n".join(L)


def _lab_text():
    try:
        import filter_lab
    except Exception:
        return "FILTER LAB: module not available"
    out = []
    for tf in ("3m", "5m", "15m"):
        j = filter_lab._JOBS.get(tf)
        if j and j["state"] == "done":
            out.append(j["text"])
        elif j and j["state"] == "running":
            out.append(f"FILTER LAB {tf}: still running - open /api/report again in a minute")
        else:
            out.append(f"FILTER LAB {tf}: not run yet - open /api/filter_lab?tf={tf} once, wait, then download this report again")
    return "\n\n".join(out)


COLS = ("opened_utc", "symbol", "side", "tf", "zone", "hold_min", "roi_pts", "pnl_usdt", "fee_usdt", "exit_reason",
        "peak_roi", "tp_hit", "adx", "ema_gap_atr", "htf", "cross_n20", "atr_pct", "sd_width_pct", "ema_slope_pct", "ema_turn")


def _csv(limit=3000):
    try:
        from . import trade_store, strategy_doctor
        raw = trade_store.get_all_closed(limit, net=True)
        rows = strategy_doctor._clean_trades(raw)
    except Exception as e:
        return f"CLOSED TRADES CSV: not readable ({type(e).__name__})"
    L = ["CLOSED TRADES CSV (oldest first; empty = not recorded)", ",".join(COLS)]
    for r in rows[-limit:]:
        t = r["t"]
        o, c = _num(t.get("opened_at_ts")), _num(t.get("closed_at_ts"))
        hold = round((c - o) / 60.0, 1) if (o and c and c >= o) else ""
        fee = _num(t.get("fee_usdt"))
        if fee is None:
            fee = (_num(t.get("invest_usdt")) or 0.0) * (_num(t.get("fee_roi_pct")) or 0.0) / 100.0
        vals = [_iso(o), t.get("symbol"), r["act"], t.get("timeframe"), t.get("entry_zone"), hold, round(r["roi"], 2), round(r["pnl"], 3),
                round(fee, 3), t.get("clean_exit_reason") or t.get("reason") or t.get("status"), t.get("peak_roi_pct"), t.get("tp_hit_levels"),
                t.get("adx"), t.get("ema_gap_atr"), t.get("htf_trend"), t.get("regime_cross_n"), t.get("atr_pct"), t.get("sd_width_pct"),
                t.get("ema_slope_pct"), t.get("ema_turn")]
        L.append(",".join("" if v is None else str(v).replace(",", ";") for v in vals))
    return "\n".join(L)


def _hold_min(t):
    o, c = _num(t.get("opened_at_ts")), _num(t.get("closed_at_ts"))
    return (c - o) / 60.0 if (o and c and c >= o) else None


def _fee_usdt(t):
    fee = _num(t.get("fee_usdt"))
    if fee is None:
        fee = (_num(t.get("invest_usdt")) or 0.0) * (_num(t.get("fee_roi_pct")) or 0.0) / 100.0
    return fee


def _tp_n(v):
    if isinstance(v, (list, tuple)):
        return len(v)
    x = _num(v)
    return int(x) if x is not None else 0


def _bucket_hold(m):
    if m is None:
        return None
    return ("1) under 5 min" if m < 5 else "2) 5-15 min" if m < 15 else "3) 15-30 min" if m < 30 else "4) 30-60 min" if m < 60 else "5) over 60 min")


def _groups(rows, keyfn):
    g = {}
    for r in rows:
        k = keyfn(r)
        if k is not None and k != "":
            g.setdefault(str(k), []).append(r)
    out = []
    for k, rs in g.items():
        net = sum(x["pnl"] for x in rs)
        out.append((k, len(rs), net, 100.0 * sum(1 for x in rs if x["pnl"] > 0) / len(rs)))
    return sorted(out, key=lambda x: x[0])


def leak_text(rows):
    """LEAKAGE SUMMARY from cleaned trades (strategy_doctor._clean_trades rows). Pure function: no I/O."""
    n = len(rows)
    if n < 10:
        return f"LEAKAGE SUMMARY: only {n} usable closed trades - too few to say anything."
    net = sum(r["pnl"] for r in rows)
    fees = sum(_fee_usdt(r["t"]) or 0.0 for r in rows)
    wins = sum(1 for r in rows if r["pnl"] > 0)
    L = ["LEAKAGE SUMMARY (calculated from the closed trades below; USDT, fee already inside every trade result)",
         f"- {n} trades, win rate {100.0 * wins / n:.0f}%, NET {net:+.0f} USDT. Fees paid {fees:.0f} USDT, so WITHOUT fees the result would be about {net + fees:+.0f} USDT.",
         f"- Average fee per trade {fees / n:.2f} USDT vs average net per trade {net / n:+.2f} USDT."]
    losers = [r for r in rows if r["pnl"] < 0]
    if losers:
        first = [r for r in losers if (_num(r["t"].get("peak_roi_pct")) or 0.0) > 0]
        tp1 = [r for r in losers if _tp_n(r["t"].get("tp_hit_levels")) >= 1]
        L.append(f"- Of {len(losers)} losing trades, {len(first)} ({100.0 * len(first) / len(losers):.0f}%) were in profit first, "
                 f"and {len(tp1)} ({100.0 * len(tp1) / len(losers):.0f}%) had already hit TP1 before ending as a loss.")
    sec = [("BY HOLD TIME", lambda r: _bucket_hold(_hold_min(r["t"]))),
           ("BY TIMEFRAME", lambda r: r["t"].get("timeframe")),
           ("BY SIDE", lambda r: r["act"]),
           ("BY EXIT REASON", lambda r: r["t"].get("clean_exit_reason") or r["t"].get("reason") or r["t"].get("status")),
           ("BY SD ZONE AT ENTRY", lambda r: r["t"].get("entry_zone"))]
    leaks = []
    for title, fn in sec:
        gs = _groups(rows, fn)
        if not gs:
            continue
        L.append(title + " (n | net USDT | win%)")
        for k, c, g_net, w in gs:
            L.append(f"  {k}: {c} | {g_net:+.0f} | {w:.0f}%")
            if c >= 20:
                leaks.append((g_net, title.replace("BY ", "").lower(), k, c, w))
    leaks.sort()
    if leaks:
        L.append("BIGGEST LEAKS (groups with 20+ trades, worst net first)")
        for g_net, t, k, c, w in leaks[:5]:
            L.append(f"  {t}: {k} -> {g_net:+.0f} USDT over {c} trades (win {w:.0f}%)")
    return "\n".join(L)


def _leak_section():
    try:
        from . import trade_store, strategy_doctor
        rows = strategy_doctor._clean_trades(trade_store.get_all_closed(5000, net=True))
        return leak_text(rows)
    except Exception as e:
        return f"LEAKAGE SUMMARY: failed ({type(e).__name__})"


def _download_dirs():
    import os
    c = [os.environ.get("OWL_DOWNLOAD_DIR"), os.path.expanduser("~/storage/downloads"), "/sdcard/Download", "/storage/emulated/0/Download"]
    return [d for d in c if d]


def save_to_downloads(text=None):
    """Writes the report into the phone's Download folder (the backend runs on the same phone in Termux).
    -> {"ok", "path", "bytes", "hint"}"""
    import os
    text = text if text is not None else build_text()
    name = "owl_report_" + datetime.now().strftime("%Y%m%d_%H%M") + ".txt"
    for d in _download_dirs():
        try:
            if os.path.isdir(d) and os.access(d, os.W_OK):
                path = os.path.join(d, name)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                return {"ok": True, "path": path, "bytes": len(text.encode("utf-8")), "hint": ""}
        except Exception:
            continue
    try:                                     # fallback: next to the bot's data, so nothing is lost
        base = os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/owl_data")
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        path = ""
    return {"ok": False, "path": path, "bytes": len(text.encode("utf-8")),
            "hint": "Phone Download folder is not reachable from Termux. Run  termux-setup-storage  once in Termux, allow storage, then press Download again."}


def build_text():
    parts = [f"OWL BOT FULL REPORT - made {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", "", PROMPT, STRATEGY, INDICATORS, GLOSSARY, CAVEATS,
             _leak_section()]
    try:
        from . import strategy_doctor
        parts.append(_doctor_text(strategy_doctor.build(5000)))
    except Exception as e:
        parts.append(f"STRATEGY DOCTOR: failed ({type(e).__name__})")
    parts.append(_lab_text())
    parts.append(_settings())
    parts.append(_csv())
    return "\n\n".join(parts) + "\n"
