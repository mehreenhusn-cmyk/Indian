"""doctor_extra.py - three small READ-ONLY helpers for the crypto Strategy Doctor screen.

* summary()  : top 3 plain actions (do / avoid / wait) from the Doctor report + the Final scoreboard.
* filtered() : the same Doctor report, but only for one timeframe and/or one coin.
* health()   : is the backend slow? (OK / SLOW + plain lines).
Nothing here touches the bot, its settings or strategy.py. Every function never raises.
"""
import time

try:
    from recovered_bot import strategy_doctor as SD, trade_store
except Exception:  # pragma: no cover
    SD = trade_store = None


def _tf(v):
    s = str(v or "").strip().lower().rstrip("m")
    return f"{s}m" if s.isdigit() else ""


def summary(doctor, board):
    """doctor = strategy_doctor report, board = scoreboard.build() dict. Pure function. -> {"actions": [max 3]}."""
    doctor = doctor if isinstance(doctor, dict) else {}
    board = board if isinstance(board, dict) else {}
    acts = []
    conf = [r for r in (doctor.get("avoid") or []) if isinstance(r, dict) and r.get("status") == "confirmed"]
    if conf:
        r = conf[0]
        saved = r.get("saved_usdt")
        extra = f" (would have saved {saved:+.0f} USDT)" if isinstance(saved, (int, float)) else ""
        what = " - ".join(x for x in (str(r.get("title") or ""), str(r.get("label") or "")) if x) or "this group"
        acts.append({"kind": "AVOID", "text": f"Skip: {what}{extra}"})
    elif doctor.get("enough"):
        acts.append({"kind": "WAIT", "text": "No avoid rule is confirmed yet. Nothing found so far survived the check on newer trades."})
    else:
        acts.append({"kind": "WAIT", "text": f"Doctor is still learning ({doctor.get('sample', 0)} of {doctor.get('min_sample', '?')} trades)."})
    helps = [r for r in (board.get("top") or []) if isinstance(r, dict) and r.get("verdict") == "helps"]
    if helps:
        acts.append({"kind": "DO", "text": "Safe to try on paper: " + "; ".join(r.get("title", "") for r in helps[:2])})
    elif board.get("total"):
        acts.append({"kind": "WAIT", "text": "Change nothing yet: no idea beat the bot in BOTH the replay and your saved trades."})
    else:
        acts.append({"kind": "WAIT", "text": "Replay is not run yet. Open the Final scoreboard and tap Run tests."})
    bs = board.get("bot_saved") or {}
    ov = doctor.get("overall") or {}
    if ov.get("n"):
        acts.append({"kind": "FACT", "text": f"Bot so far: {ov.get('net_pnl', 0):+.0f} USDT on {ov['n']} trades, win {ov.get('win_rate', 0):.0f}% (fees {ov.get('fee_total', 0):.0f})."})
    elif bs.get("n"):
        acts.append({"kind": "FACT", "text": f"Bot so far: {bs.get('net', 0):+.0f} ROI points on {bs['n']} saved trades."})
    return {"ok": True, "actions": acts[:3], "t": time.time()}


def options(raw):
    """Timeframes and coins that exist in the saved trades (for the filter chips)."""
    rows = SD._clean_trades(raw) if SD else []
    tfs, coins = {}, {}
    for r in rows:
        t = r["t"]
        a = _tf(t.get("timeframe"))
        c = str(t.get("symbol") or "").upper()
        if a:
            tfs[a] = tfs.get(a, 0) + 1
        if c:
            coins[c] = coins.get(c, 0) + 1
    top = sorted(coins.items(), key=lambda kv: -kv[1])[:8]
    return {"tfs": sorted(tfs, key=lambda x: int(x[:-1])), "coins": [c for c, _ in top]}


def filtered(tf="", coin="", limit=5000):
    """Doctor report for one timeframe (e.g. '5m') and/or one coin. Empty = all."""
    try:
        raw = trade_store.get_all_closed(int(limit or 5000), net=True)
        want_tf, want_coin = _tf(tf), str(coin or "").upper()
        keep = [t for t in raw
                if (not want_tf or _tf(t.get("timeframe")) == want_tf)
                and (not want_coin or str(t.get("symbol") or "").upper() == want_coin)]
        rep = SD.build_from(keep)
        try:
            from recovered_bot import doctor_verdict
            rep["verdict"] = doctor_verdict.build([x["t"] for x in SD._clean_trades(keep)], unit="USDT", studies=True)
        except Exception:
            pass
        rep["filter"] = {"tf": want_tf, "coin": want_coin, "of_total": len(raw), "options": options(raw)}
        return SD._finite(rep)
    except Exception as e:
        return {"ok": False, "sample": 0, "enough": False, "min_sample": 0,
                "headline": ["Could not apply this filter."], "error": f"{type(e).__name__}: {e}"}


def health(screens=None, heavy_by=None, held_for=0.0, cpu=None):
    """screens = {name: [last_wait_s, last_run_s, finished_at]} (api_server's _TIMING). Pure function."""
    lines, slow = [], False
    if heavy_by:
        lines.append(f"A heavy screen ('{heavy_by}') has been running for {held_for:.0f}s.")
        slow = slow or held_for > 30
    worst = None
    for k, v in (screens or {}).items():
        try:
            wait, run = float(v[0]), float(v[1])
        except Exception:
            continue
        if worst is None or wait + run > worst[1]:
            worst = (str(k), wait + run, wait)
    if worst:
        lines.append(f"Slowest screen: {worst[0]} took {worst[1]:.1f}s (waited {worst[2]:.1f}s).")
        slow = slow or worst[1] > 20
    if isinstance(cpu, dict) and isinstance(cpu.get("process_cpu_pct"), (int, float)):
        lines.append(f"Bot is using {cpu['process_cpu_pct']:.0f}% of one CPU core.")
        slow = slow or cpu["process_cpu_pct"] > 90
    if not lines:
        lines.append("Nothing is running slowly.")
    return {"state": "SLOW" if slow else "OK", "lines": lines[:4]}
