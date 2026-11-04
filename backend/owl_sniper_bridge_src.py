"""owl_sniper_bridge_src.py - OwlSniper LEARN BRIDGE, step 1 of 3 (Part 6 / FILE 09). READ ONLY: no network, no order code, nothing is written, nothing is changed.
Why: the Sniper learns only from its own candle replay. Dual Bot (481+ closed), Brain (own trades) and the main bot (3000+ trades) hold far more finished trades, but every bot keeps them in its own shape.
This file reads the CLOSED trades of the three bots and turns each into ONE flat record with a SOURCE tag ("dual" / "brain" / "main"). Step 2 (FILE 10) replays the candles at each entry time, step 3 (FILE 11) puts labels.
Where the trades are read from (read-only):
  dual    dual_archive.db (table trades, status closed; the long-term copy, nothing is ever deleted there). If it is missing: dual_lab_data.json (newest 600 only).
  brain   brain_archive.db (table own). If it is missing: smart_brain_own.json (newest 300 only).
  main    closed_trades_archive.jsonl, paper bot 1 only. Skipped and counted, never mixed in: real/live trades, bot 2, and the Sniper's own paper trades (source sniper / sniper_learn).
Records (one flat dict): uid, source, symbol, tf, side LONG/SHORT, entry_ts, entry_price, stop_price, stop_pct, tp_prices, exit_ts, exit_price, exit_why, bars, tp_hit, net_roi, lev, pnl_usdt, margin_usdt, mfe_roi, mae_roi, taken, ctx.
  Times are UNIX SECONDS. For dual / brain entry_ts is the CLOSE of the signal candle (the bot enters at that close); exit_ts is the close of the exit candle. For main they are opened_at_ts / closed_at_ts.
  net_roi = result in ROI points after the fee, AT THAT BOT'S OWN LEVERAGE (lev says which). Dual / Brain: 10x, fee 1 point. So trades of different sources are NOT comparable by net_roi or pnl_usdt: the source tag exists so books are never added together.
  mfe_roi / mae_roi are what the bot itself recorded (None = not recorded; Dual and Brain store no MAE). Step 2 measures MAE / MFE again from candles, the same way for every source.
Missing or damaged rows are SKIPPED and counted by reason, never guessed. Run (Termux, optional):  python3 backend/owl_sniper_bridge_src.py [--data DIR] [--since-days N] [--include-skipped] [--sample N]  -> JSON summary."""
import argparse
import json
import math
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import btc_lab as BTCL
import trade_archive as TA
import v2_pnl as P

VERSION = "owl_sniper_bridge_src 1 (Part 6)"
SOURCES = ("dual", "brain", "main")
TF_SEC = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}
DUAL_LEV, DUAL_FEE = 10.0, 1.0          # same constants as dual_lab.py (LEV, FEE); Brain uses the same
DUAL_MARGIN, BTC_MARGIN = 100.0, 1000.0  # same as dual_lab.py (MARGIN, BTC_MARGIN)
MAX_ROWS = 20000                         # newest rows per source (keeps the phone light)
OWN_SNIPER = ("sniper", "sniper_learn")  # the Sniper's own paper trades are never fed back as "main bot" data


def default_dir():
    """The data folder when no --data is typed: OWL_DATA_DIR, else ~/owl_data (the same pick as api_server.py), else the current folder."""
    env = os.environ.get("OWL_DATA_DIR")
    if env:
        return os.path.expanduser(env)
    home = os.path.join(os.path.expanduser("~"), "owl_data")
    return home if os.path.isdir(home) else "."


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _sec(v):
    """A time that may be seconds or milliseconds (Dual writes closed_at in seconds, Brain in milliseconds) -> seconds, or None."""
    x = _num(v)
    if x is None or x <= 0:
        return None
    return x / 1000.0 if x > 1e11 else x


def _skip(info, why):
    info["skipped"][why] = info["skipped"].get(why, 0) + 1


def _pct(entry, stop):
    return round(abs(entry - stop) / entry * 100.0, 4) if entry and stop else None


def from_lab(t, source):
    """Dual and Brain share one trade shape (s, f, ct, d, entry, sl, tps, net, end, bars, hit, mfe ...). -> record, or (None, reason)."""
    sym, tf, d = t.get("s"), t.get("f"), _num(t.get("d"))
    if BTCL.skip(sym):                                       # R16b: BTC is the indicator test coin, never a Sniper training example
        return None, "btc_lab"
    step, ct, entry, net = TF_SEC.get(tf), _num(t.get("ct")), _num(t.get("entry")), _num(t.get("net"))
    if not sym or step is None or ct is None or not entry or entry <= 0 or net is None or d not in (1.0, -1.0):
        return None, "bad_row"
    entry_ts, bars, xt = ct / 1000.0 + step, _num(t.get("bars")), _num(t.get("xt"))
    exit_ts = xt / 1000.0 + step if xt is not None else (entry_ts + bars * step if bars is not None else _sec(t.get("closed_at")))
    if exit_ts is not None and exit_ts < entry_ts:
        exit_ts = None
    stop = _num(t.get("sl"))
    margin = _num(t.get("mg")) or (BTC_MARGIN if sym == "BTCUSDT" else DUAL_MARGIN)
    ctx = {k: t.get(k) for k in ("src", "exit", "mode", "stage", "explore", "brain_version") if t.get(k) is not None}
    return {"uid": "%s:%s" % (source, t.get("id")), "source": source, "symbol": sym, "tf": tf, "side": "LONG" if d > 0 else "SHORT",
            "entry_ts": entry_ts, "entry_price": entry, "stop_price": stop, "stop_pct": _pct(entry, stop),
            "tp_prices": [x for x in (_num(v) for v in t.get("tps") or []) if x is not None],
            "exit_ts": exit_ts, "exit_price": _num(t.get("xpx")), "exit_why": t.get("end"), "bars": bars, "tp_hit": _num(t.get("hit")),
            "net_roi": net, "lev": DUAL_LEV, "fee_roi": DUAL_FEE, "pnl_usdt": round(net * margin / 100.0, 4), "margin_usdt": margin,
            "mfe_roi": _num(t.get("mfe")), "mae_roi": None, "taken": t.get("take") is not False, "ctx": ctx}, None


def from_main(t, file_bot="b1"):
    """One row of closed_trades_archive.jsonl (main paper bot 1). -> record, or (None, reason)."""
    if P.box_of(t, file_bot) != "paper_b1" or str(t.get("bot") or "b1").lower() == "b2":
        return None, "other_book"
    if str(t.get("source") or "").lower() in OWN_SNIPER:
        return None, "own_sniper"
    act, entry = str(t.get("action") or "").upper(), _num(t.get("entry_price"))
    t0, t1, roi, pnl = _num(t.get("opened_at_ts")), _num(t.get("closed_at_ts")), _num(t.get("roi_pct")), _num(t.get("pnl_usdt"))
    if not t.get("symbol") or act not in ("BUY", "SELL") or not entry or entry <= 0 or t0 is None or t1 is None or roi is None or pnl is None or t1 < t0:
        return None, "bad_row"
    if BTCL.skip(t.get("symbol")):                           # R16b: BTC is the indicator test coin
        return None, "btc_lab"
    stop = _num(t.get("signal_stop_loss")) or _num(t.get("sl_initial"))
    worst = _num(t.get("min_roi_pct"))
    why = str(t.get("status") or "").replace("CLOSED_", "") or None
    return {"uid": "main:%s:%d" % (t.get("id"), int(t0)), "source": "main", "symbol": t["symbol"], "tf": t.get("timeframe") or None,
            "side": "LONG" if act == "BUY" else "SHORT", "entry_ts": t0, "entry_price": entry, "stop_price": stop, "stop_pct": _pct(entry, stop),
            "tp_prices": [x for x in (_num(t.get("signal_tp%d" % k)) for k in (1, 2, 3, 4)) if x is not None],
            "exit_ts": t1, "exit_price": _num(t.get("exit_price")), "exit_why": why, "bars": None, "tp_hit": len(t.get("tp_hit_levels") or []),
            "net_roi": roi, "lev": _num(t.get("leverage")), "fee_roi": _num(t.get("fee_roi_pct")), "pnl_usdt": pnl, "margin_usdt": _num(t.get("invest_usdt")),
            "mfe_roi": _num(t.get("max_roi_pct")) if _num(t.get("max_roi_pct")) is not None else _num(t.get("peak_roi")),
            "mae_roi": None if worst is None else max(0.0, -worst), "taken": True,
            "ctx": {k: t.get(k) for k in ("trigger", "sl_type", "source", "quality_tag") if t.get(k) is not None}}, None


def _new(where):
    return {"where": where, "rows_seen": 0, "kept": 0, "skipped": {}}


def _db_rows(con, sql, args):
    """JSON text of every row of one query. Rows that are not JSON are counted by the caller."""
    return [r[0] for r in con.execute(sql, args).fetchall()]


def _lab_source(d, source, since_ts, include_skipped):
    """Dual or Brain: the archive db first (full history), the bot's own json file as the fallback (newest rows only)."""
    info, recs, rows = _new("none"), [], []
    try:
        con = TA.open_dual_ro(d) if source == "dual" else TA.open_brain_ro(d)
        if con is not None:
            try:
                cut = " AND t >= %d" % int(since_ts * 1000) if since_ts else ""     # only when asked for; a row without t is never lost by accident
                if source == "dual":
                    marks = "('closed','skipped_done')" if include_skipped else "('closed')"
                    texts = _db_rows(con, "SELECT js FROM trades WHERE status IN %s%s ORDER BY t DESC LIMIT ?" % (marks, cut), (MAX_ROWS,))
                else:
                    texts = _db_rows(con, "SELECT js FROM own WHERE 1=1%s ORDER BY t DESC LIMIT ?" % cut, (MAX_ROWS,))
            finally:
                con.close()
            info["where"] = "archive"
            texts.reverse()                                           # the query was newest-first; records are kept oldest-first
            for tx in texts:
                try:
                    rows.append(json.loads(tx))
                except (TypeError, ValueError):
                    _skip(info, "bad_json")
    except (sqlite3.Error, OSError) as e:
        info["error"] = str(e)[:80]
    if info["where"] == "none":                                   # fallback: the bot's own file
        name, key = ("dual_lab_data.json", "trades") if source == "dual" else ("smart_brain_own.json", "closed")
        try:
            with open(os.path.join(os.path.realpath(d), name), "r", encoding="utf-8") as f:
                rows = [r for r in (json.load(f).get(key) or []) if isinstance(r, dict)]
            info["where"] = "json_file"
        except (OSError, ValueError, AttributeError):
            rows = []
    for t in rows:
        if not isinstance(t, dict):
            _skip(info, "bad_json")
            continue
        info["rows_seen"] += 1
        ok = t.get("status") in (("closed", "skipped_done") if include_skipped and source == "dual" else ("closed",))
        if not ok or t.get("net") is None:
            _skip(info, "not_finished")
            continue
        rec, why = from_lab(t, source)
        if rec is None:
            _skip(info, why)
        elif since_ts and rec["entry_ts"] < since_ts:
            _skip(info, "before_since")
        else:
            recs.append(rec)
    info["kept"] = len(recs)
    return recs, info


def read_dual(d, since_ts=None, include_skipped=False):
    """Dual Bot closed trades (status closed). include_skipped=True also adds the trades the bot did NOT take but simulated to the end (taken=False)."""
    return _lab_source(d, "dual", since_ts, include_skipped)


def read_brain(d, since_ts=None):
    """Brain's OWN finished paper trades."""
    return _lab_source(d, "brain", since_ts, False)


def read_main(d, since_ts=None):
    """Main paper bot (bot 1) closed trades from the long-term jsonl archive."""
    root = os.path.realpath(d)
    rows, st = P.read_jsonl(os.path.join(root, P.FILES[0][0]), [root])
    info = _new("missing" if st.get("status") else "archive")
    if st.get("status"):
        info["error"] = st["status"]
    recs = []
    for t in rows[-MAX_ROWS:]:
        info["rows_seen"] += 1
        rec, why = from_main(t, P.FILES[0][1])
        if rec is None:
            _skip(info, why)
        elif since_ts and rec["entry_ts"] < since_ts:
            _skip(info, "before_since")
        else:
            recs.append(rec)
    info["kept"] = len(recs)
    return recs, info


def collect(d, sources=SOURCES, since_ts=None, include_skipped=False):
    """All requested sources -> {records (oldest first, no duplicate uid), by_source: {name: info + n}}. Never raises; a failing source is reported, the others still come."""
    readers = {"dual": lambda: read_dual(d, since_ts, include_skipped), "brain": lambda: read_brain(d, since_ts), "main": lambda: read_main(d, since_ts)}
    out, seen, by = [], set(), {}
    for name in sources:
        if name not in readers:
            continue
        try:
            recs, info = readers[name]()
        except Exception as e:
            recs, info = [], dict(_new("error"), error=str(e)[:80])
        kept = 0
        for r in recs:
            if r["uid"] in seen:
                _skip(info, "duplicate")
                continue
            seen.add(r["uid"])
            out.append(r)
            kept += 1
        info["kept"] = kept
        by[name] = info
    out.sort(key=lambda r: r["entry_ts"])
    return {"version": VERSION, "records": out, "by_source": by}


def summary(res):
    """Small, printable view: per source counts. Sources are listed apart on purpose (different leverage and size: never one total P&L)."""
    per = {}
    for name, info in res["by_source"].items():
        rs = [r for r in res["records"] if r["source"] == name]
        w = sum(1 for r in rs if r["net_roi"] > 0)
        per[name] = dict(info, wins=w, losses=len(rs) - w, tf_known=sum(1 for r in rs if r["tf"] in TF_SEC),
                         with_stop=sum(1 for r in rs if r["stop_pct"]), symbols=len({r["symbol"] for r in rs}),
                         first_entry_ts=rs[0]["entry_ts"] if rs else None, last_entry_ts=rs[-1]["entry_ts"] if rs else None)
    return {"version": res["version"], "records": len(res["records"]), "by_source": per,
            "note": "READ ONLY. net_roi / pnl_usdt use each bot's own leverage and size: never add sources together."}


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper bridge: closed trades of Dual, Brain, main bot in one format (read only)")
    ap.add_argument("--data", default=default_dir())
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--include-skipped", action="store_true")
    ap.add_argument("--sample", type=int, default=0)
    a = ap.parse_args(argv)
    since = time.time() - a.since_days * 86400 if a.since_days else None
    res = collect(a.data, SOURCES, since, a.include_skipped)
    out = summary(res)
    if a.sample > 0:
        out["sample"] = res["records"][-a.sample:]
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
