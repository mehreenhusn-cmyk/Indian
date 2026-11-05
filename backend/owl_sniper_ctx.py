"""owl_sniper_ctx.py - OwlSniper R30 (Part 5): MARKET CONTEXT for the Sniper = BTC move, BTC trend and the session hour. PAPER ONLY, READ ONLY: reads BTCUSDT candles from v2_market.db (read-only connection), writes nothing, no network, no order code.
Why (owner wish, rule 30): the Sniper saw every coin alone. A person who sits 10 years with the market also looks at BTC (is the whole market falling?) and the time of day (Asia / Europe / US). BTC stays OUT of every P&L total: here it is only a set of NUMBERS the Sniper may learn from.
Numbers per signal (the SIGNAL candle only, nothing after it is read = no look-ahead; the row builder turns them into 7 wide numbers, see owl_sniper_feedall_feat):
  btc_1 / btc_3 / btc_12  = BTC close move in % over the last 1 / 3 / 12 candles of the SAME interval as the signal
  btc_trend               = (EMA30 / EMA50 - 1) x 100 of BTC on that interval (needs 50 candles; None before)
  hour                    = UTC hour of the signal candle (0..24), used as sin / cos so 23:00 is next to 00:00
A missing BTC candle gives None for the BTC numbers (counted as missing by wide_vec, never hidden); the hour is always known.
Honest: the EMA starts at the first candle that is read, so replay (long window) and live (short window) differ a little in the first candles; both read 62+ candles before the signal.
API: attach(d, examples) -> {state, attached, btc_missing}   (adds e["btc"] to every feedall example) | live(con, interval, open_ts) -> dict (live card, cached per candle) | view(d, now) -> small dict for the app.
CLI: python3 backend/owl_sniper_ctx.py [--data DIR]"""
import argparse
import bisect
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_feed as F
import owl_sniper_tf as TF
import v2_defs as D
import v2_setup_finder as SF

VERSION = "owl_sniper_ctx 1 (R30)"
BTC, WARM, MAX_LAG = "BTCUSDT", 62, 2          # WARM = candles read before the first signal (EMA50 needs 50); MAX_LAG = how many candles old the BTC candle may be
_CACHE = {}


def _ema(c, n):
    out = [None] * len(c)
    if len(c) < n:
        return out
    k, v = 2.0 / (n + 1), sum(c[:n]) / n
    out[n - 1] = v
    for i in range(n, len(c)):
        v = c[i] * k + v * (1 - k)
        out[i] = v
    return out


def session(hour):
    """Plain name of the market session for a UTC hour (a label for the owner; the model uses sin / cos of the hour)."""
    return "ASIA" if hour < 8 else ("EUROPE" if hour < 13 else ("US" if hour < 21 else "LATE US"))


def _series(rows, tf):
    """BTC candle rows -> gap-free runs [(stamps, closes, ema30, ema50)] on interval tf. Gaps are cut, never bridged."""
    good, _bad = D.clean_candles(rows, TF.base(tf))
    out = []
    for r in SF.runs(good, TF.base(tf)):
        run = TF.aggregate(r, tf)
        if run:
            cl = [x[4] for x in run]
            out.append(([x[0] for x in run], cl, _ema(cl, 30), _ema(cl, 50)))
    return out


def blank(open_ts):
    return {"btc_1": None, "btc_3": None, "btc_12": None, "btc_trend": None, "hour": round((open_ts % 86400) / 3600.0, 3)}


def at(series, open_ts, tf):
    """The context at the signal candle that opened at open_ts. BTC numbers are None when no BTC candle sits within MAX_LAG candles."""
    out, step = blank(open_ts), TF.step(tf)
    for stamps, cl, e30, e50 in series:
        if open_ts < stamps[0] or open_ts > stamps[-1] + MAX_LAG * step:
            continue
        i = bisect.bisect_right(stamps, open_ts) - 1
        if open_ts - stamps[i] > MAX_LAG * step:
            continue
        c = cl[i]

        def mv(k):
            return round((c / cl[i - k] - 1.0) * 100.0, 4) if i >= k and cl[i - k] else None
        tr = None if e30[i] is None or not e50[i] else round((e30[i] / e50[i] - 1.0) * 100.0, 4)
        return dict(out, btc_1=mv(1), btc_3=mv(3), btc_12=mv(12), btc_trend=tr)
    return out


def attach(d, examples):
    """Add e["btc"] to every feedall example (one BTC read per interval). Never raises."""
    res = {"state": "ok", "attached": 0, "btc_missing": 0}
    con = None
    try:
        con = F.open_ro(d)
        if con is None:
            res["state"] = "no market store"
        by = {}
        for e in examples:
            by.setdefault(e["tf"], []).append(e)
        for tf, items in by.items():
            ts = [e.get("candle_open_ts") or (e["entry_ts"] - TF.step(tf)) for e in items]
            ser = []
            if con is not None and ts:
                step = TF.step(tf)
                ser = _series(D.candles_from_store(con, BTC, TF.base(tf), min(ts) - WARM * step, max(ts) + step), tf)
            for e, t in zip(items, ts):
                e["btc"] = at(ser, t, tf)
                res["attached"] += 1
                res["btc_missing"] += 1 if e["btc"]["btc_3"] is None else 0
    except Exception as ex:
        res["state"] = "error: %s: %s" % (type(ex).__name__, str(ex)[:80])
    finally:
        if con is not None:
            con.close()
    return res


def live(con, interval, open_ts):
    """The same numbers for a LIVE card. con = the live scan's read-only connection. One BTC read per candle (all coins share it). Never raises."""
    try:
        key = (interval, int(open_ts))
        if key in _CACHE:
            return _CACHE[key]
        step = TF.step(interval)
        ser = _series(D.candles_from_store(con, BTC, TF.base(interval), open_ts - WARM * step, open_ts + step), interval) if con is not None else []
        if len(_CACHE) > 12:
            _CACHE.clear()
        _CACHE[key] = at(ser, open_ts, interval)
        return _CACHE[key]
    except Exception:
        return blank(open_ts)


def view(d, now=None, interval="5m"):
    """Small answer for the app (GET /api/v2/sniper_ctx): BTC now + session. Read only. Never raises."""
    now = time.time() if now is None else now
    out = {"version": VERSION, "paper_only": True, "state": "ok", "interval": interval, "now": int(now), "session": session((now % 86400) / 3600.0), "btc_counts_in_pnl": False}
    con = None
    try:
        con = F.open_ro(d)
        if con is None:
            return dict(out, state="no_data", text="The market store does not exist yet.")
        step = TF.step(interval)
        rows = D.candles_from_store(con, BTC, TF.base(interval), now - (WARM + 2) * step, now)
        ser = _series(rows, interval)
        if not ser:
            return dict(out, state="no_data", text="No BTC candles saved in the last hours.")
        t = ser[-1][0][-1]
        out.update(ctx=at(ser, t, interval), candle_open_ts=int(t), age_sec=int(now - t - step))
    except Exception as e:
        out.update(state="error", text="%s: %s" % (type(e).__name__, str(e)[:80]))
    finally:
        if con is not None:
            con.close()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper market context (read only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    print(json.dumps(view(ap.parse_args(argv).data), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
