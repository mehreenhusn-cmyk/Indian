"""v2_f14_timeline.py - Part 12A: the TRADE TIMELINE (read only). For every paper trade of the current bot (b1, not LIVE-) it builds the story in order:
SIGNAL seen (snapshot time) -> OPENED -> TP1 BANKED (30 percent, if it happened) -> CLOSED (why, net).  Open trades come from the positions table (db.load_positions, read only), closed ones from the same trade archives as the daily report.
Main and Sniper trades share the b1 book: every trade carries g so the app shows them apart. Also gives the last signals (snapshots, Main bot) so the app can show an alert when a NEW one comes. Nothing here stops, opens or changes a trade. A small cache (30 s) keeps the phone polling cheap.
Answer = {made_utc, open[], closed[], signals[], note}. Each trade = {id, g (MAIN or SNIPER, never mixed in one total), sym, side, tf, state, signal_ts, open_ts, booked_ts, booked_pnl, close_ts, exit, net, events[{t, label, note}]}."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f12_join as J
import v2_f1_counts as X
import v2_pnl as P

VERSION = "v2_f14_timeline 1 (Part 12A)"
DAYS, MAX_CLOSED, MAX_SIGNALS, CACHE_SEC = 3, 80, 15, 30
_cache = {"t": 0.0, "root": None, "data": None}
EXIT_WORDS = {"TP": "take profit", "SL": "stop loss", "TRAIL": "trailing stop", "BE": "break-even stop", "TIME": "time exit", "MANUAL": "closed by hand"}


def _ev(t, label, note=""):
    return {"t": t, "label": label, "note": note}


def _closed_trade(r, sn):
    ev = []
    sig = sn.get("t") if sn else None
    if sig:
        ev.append(_ev(sig, "SIGNAL", "z-spike bars: %s" % sn.get("spike_ago") if sn.get("spike_ago") is not None else "signal seen"))
    ev.append(_ev(r["ent"], "OPENED", "%s %s" % (r["side_txt"], r["tf"] or "")))
    if r.get("booked") and r.get("booked_ts"):
        ev.append(_ev(r["booked_ts"], "TP1 BANKED", "30 percent booked, %s USDT" % (round(r["booked_pnl"], 2) if r.get("booked_pnl") is not None else "?")))
    if r.get("close"):
        ev.append(_ev(r["close"], "CLOSED", "%s | net %+.2f USDT" % (EXIT_WORDS.get(r.get("exit"), r.get("exit") or r.get("status") or "?"), r["net"])))
    return {"id": r["id"], "g": r.get("g", "MAIN"), "sym": r["sym"], "side": r["side_txt"], "tf": r["tf"], "state": "CLOSED", "signal_ts": sig, "open_ts": r["ent"], "booked_ts": r.get("booked_ts"), "booked_pnl": r.get("booked_pnl"),
            "close_ts": r.get("close"), "exit": r.get("exit"), "status": r.get("status"), "net": r["net"], "events": ev}


def _open_trades():
    """Open paper positions (b1, not LIVE-) from the positions table. Read only, never raises."""
    try:
        from recovered_bot import db
        pos, _n = db.load_positions()
    except Exception:
        return []
    out = []
    for pid, p in pos.items():
        try:
            if (p.get("bot") or "b1") == "b2" or str(p.get("id") or pid).startswith("LIVE-"):
                continue
            side = "LONG" if str(p.get("action")).upper() in ("BUY", "LONG") else "SHORT"
            ts = p.get("opened_at_ts")
            tp = p.get("tp_hit_levels") or []
            ev = [_ev(ts, "OPENED", "%s %s" % (side, p.get("timeframe") or p.get("tf") or ""))]
            if tp:
                ev.append(_ev(p.get("booked_ts"), "TP1 BANKED", "TP levels hit: %s" % list(tp)))
            out.append({"id": p.get("id") or pid, "g": "SNIPER" if str(p.get("source") or "").lower().startswith("sniper") else "MAIN", "sym": p.get("symbol"), "side": side, "tf": p.get("timeframe") or p.get("tf"), "state": "OPEN", "signal_ts": None, "open_ts": ts, "booked_ts": p.get("booked_ts"),
                        "booked_pnl": p.get("booked_pnl"), "close_ts": None, "exit": None, "net": None, "peak_roi": p.get("max_roi_pct"), "worst_roi": p.get("min_roi_pct"), "events": ev})
        except Exception:
            continue
    out.sort(key=lambda a: a.get("open_ts") or 0, reverse=True)
    return out


def build(root, fee_roi=1.0):
    now = time.time()
    snaps = J.load_snaps(root)
    rows = []
    for r in J.closed_rows(root, fee_roi, with_sniper=True):
        if r["ent"] >= now - DAYS * 86400:
            r["side_txt"] = "LONG" if r["side"] == 1 else "SHORT"
            rows.append(r)
    rows.sort(key=lambda a: a.get("close") or a["ent"], reverse=True)
    closed = [_closed_trade(r, J.match(snaps, r["sym"], r["side"], r["tf"], r["ent"])) for r in rows[:MAX_CLOSED]]
    flat = [(t, x) for v in snaps.values() for t, x in v]
    flat.sort(key=lambda a: a[0], reverse=True)
    sigs = [{"t": t, "sym": x.get("sym"), "side": x.get("side"), "tf": x.get("tf")} for t, x in flat[:MAX_SIGNALS]]
    return {"tool": VERSION, "made_utc": P.fmt_ts(now), "read_only": True, "open": _open_trades(), "closed": closed, "signals": sigs, "days": DAYS, "groups": ["MAIN", "SNIPER"],
            "note": "Last %d days, newest first. Signal time = the snapshot (only from Part 10 on). Paper money only." % DAYS}


def answer(root, fee_roi=1.0):
    """Cached build (30 s) so the phone polling does not read the archives every time."""
    root = os.path.realpath(root)
    if _cache["data"] is not None and _cache["root"] == root and time.time() - _cache["t"] < CACHE_SEC:
        return _cache["data"]
    try:
        data = build(root, fee_roi)
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:120])}
    _cache.update(t=time.time(), root=root, data=data)
    return data
