"""v2_screen_check.py - Part 74: SCREENSHOT CHECK 1 of 2 (backend, read-only). "Bhai, is coin ka ye screenshot - Brain kya dekhta hai?"
The screenshot is NOT read pixel by pixel. It only tells WHICH COIN and WHEN (symbol + time). The numbers come from the candles the collectors saved:
  1. the newest CLOSED candle at or before that time, inside ONE gap-free run (gaps are never bridged),
  2. the owner's TWO indicators at that candle (v2_scalp_ind: EMA50 + SD bands, TSI + Z-score + Z-SMA; no third indicator),
  3. HISTORY of the same coin: earlier candles that stood in the SAME state (price vs EMA, TSI vs signal, TSI zone, Z vs Z-SMA) and what the close did FWD candles later.
EVIDENCE block = counts + sample size + label. OPINION block (v2_screen_opinion.py) = words, always labelled and kept apart. Never an order, nothing is saved, no network.
Honesty rules: every number at candle i uses only candles 0..i (causal); history counts only candles whose FWD-candle outcome is already finished before the checked candle;
overlapping windows are NOT independent (the note says so); fewer than MIN_SAMPLE similar candles = "NOT ENOUGH DATA", never a percentage. All constants are starting values (NV).
Run (Termux):  python3 backend/v2_screen_check.py --symbol BTCUSDT [--interval 5m] [--at "2026-10-31 14:30"] [--data DIR]   (time = UTC; default = newest candle)
Route: GET /api/v2/screen_check?symbol=BTCUSDT&interval=5m&at=2026-10-31 14:30 (api/v2_data.py)"""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_candles as K
import v2_defs as D
import v2_scalp_ind as SI
import v2_screen_opinion as OP
import v2_setup_finder as SF
import v2_store as S

VERSION = "v2_screen_check 1 (Part 74)"
FWD = 12                  # candles after a similar candle that the outcome looks at (NV)
MOVE_PCT = 0.30           # close FWD candles later: above +0.30 % = UP, below -0.30 % = DOWN, else FLAT (NV)
MIN_SAMPLE = 30           # fewer similar candles than this = NOT ENOUGH DATA
MAX_CANDLES = 6000        # newest candles read per coin and interval
RECENT = 12               # candles shown as the recent picture


def parse_at(text, now):
    """'' / None -> now. 'YYYY-MM-DD HH:MM' (UTC) or a unix number -> seconds. Anything else -> ValueError."""
    t = str(text or "").strip()
    if not t:
        return int(now)
    try:
        if t.replace(".", "", 1).isdigit():
            v = float(t)
            return int(v / 1000.0 if v > 10 ** 11 else v)
        return int(time.mktime(time.strptime(t[:16].replace("T", " "), "%Y-%m-%d %H:%M")) - time.timezone)
    except (ValueError, OverflowError):
        raise ValueError("at must be like 2026-10-31 14:30 (UTC) or a unix time")


def key_of(st):
    """The state a candle is in, as four words. None while any number is missing (never a guess)."""
    if not st["ready"]:
        return None
    return (st["price_vs_ema"], st["tsi_vs_signal"], st["tsi_zone"], st["z_vs_sma"])


def outcome(run, j):
    """UP / DOWN / FLAT of the close FWD candles after candle j (None if the run ends first)."""
    if j + FWD >= len(run):
        return None
    a, b = run[j][4], run[j + FWD][4]
    ch = (b - a) / a * 100.0
    return "UP" if ch > MOVE_PCT else ("DOWN" if ch < -MOVE_PCT else "FLAT")


def history(runs_, target_run, target_i, key):
    """Same coin, same state, earlier and finished. -> counts dict. Candle target_i itself and anything after it never counts."""
    cnt = {"UP": 0, "DOWN": 0, "FLAT": 0}
    for run in runs_:
        if len(run) < SI.EMA_LEN + FWD + 2:
            continue
        ind = SI.compute(run)
        last = (target_i - FWD - 1) if run is target_run else len(run) - FWD - 1
        for j in range(0, last + 1):
            if key_of(SI.state(ind, j)) != key:
                continue
            o = outcome(run, j)
            if o:
                cnt[o] += 1
    n = sum(cnt.values())
    return {"similar_candles": n, "UP": cnt["UP"], "DOWN": cnt["DOWN"], "FLAT": cnt["FLAT"],
            "label": "MEASURED" if n >= MIN_SAMPLE else "NOT ENOUGH DATA (under %d similar candles: too few to say anything)" % MIN_SAMPLE,
            "pct": None if n < MIN_SAMPLE else {k: round(cnt[k] * 100.0 / n, 1) for k in cnt},
            "note": "windows overlap (%d candles each), so these are NOT %d independent tries; read it as a description, not a rule" % (FWD, n)}


def pick_candle(runs_, interval, at):
    """The newest CLOSED candle (open_ts + step <= at) -> (run, index) or (None, None). If it ends more than 2 steps before `at`, the saved candles do not cover that time."""
    step = D.STEP[interval]
    best = None
    for run in runs_:
        for i in range(len(run) - 1, -1, -1):
            if run[i][0] + step <= at:
                if best is None or run[i][0] > best[0][best[1]][0]:
                    best = (run, i)
                break
    if best is None:
        return None, None
    run, i = best
    if at - (run[i][0] + step) > 2 * step:
        return None, None            # collector off or gap: say so, do not use an older picture
    return run, i


def recent_picture(run, i):
    rows = []
    for k in range(max(0, i - RECENT + 1), i + 1):
        o, c = run[k][1], run[k][4]
        rows.append({"t": time.strftime("%H:%M", time.gmtime(run[k][0])), "close": c, "chg_pct": round((c - o) / o * 100.0, 3)})
    return rows


def build_for(candles_rows, symbol, interval, at, now):
    good, bad = D.clean_candles(candles_rows, interval)
    rep = {"ready": True, "version": VERSION, "symbol": symbol, "interval": interval, "asked_at_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(at)),
           "candles_read": len(good), "bad_rows_dropped": bad, "indicators_used": list(SI.INDICATORS_USED),
           "definition": {"similar_state": "price vs EMA50 + TSI vs signal + TSI zone + Z vs Z-SMA are all the same", "outcome": "close %d candles later: UP > +%.2f %%, DOWN < -%.2f %%, else FLAT" % (FWD, MOVE_PCT, MOVE_PCT)},
           "picture_note": "the screenshot only picks coin + time; nothing is read from its pixels"}
    if not good:
        rep.update(status="NO_CANDLES", note="no saved %s candles for %s yet (the collector keeps only coins it follows)" % (interval, symbol))
        rep["opinion"] = OP.opinion(rep)
        return rep
    runs_ = SF.runs(good, interval)
    run, i = pick_candle(runs_, interval, at)
    if run is None:
        rep.update(status="TIME_NOT_COVERED", saved_from_utc=time.strftime("%Y-%m-%d %H:%M", time.gmtime(good[0][0])),
                   saved_to_utc=time.strftime("%Y-%m-%d %H:%M", time.gmtime(good[-1][0])), note="no closed candle of this coin right before that time; nothing is guessed")
        rep["opinion"] = OP.opinion(rep)
        return rep
    ind = SI.compute(run)
    st = SI.state(ind, i)
    rep["status"] = "OK" if st["ready"] else "NOT_ENOUGH_CANDLES"
    rep["candle_utc"] = time.strftime("%Y-%m-%d %H:%M", time.gmtime(run[i][0]))
    rep["candles_in_run_before"] = i + 1
    rep["candles_needed_for_all_numbers"] = SI.need_candles()
    rep["state"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in st.items() if k != "i"}
    rep["ema_distance_pct"] = None if st["ema50"] is None else round((st["close"] - st["ema50"]) / st["ema50"] * 100.0, 3)
    rep["recent"] = recent_picture(run, i)
    key = key_of(st)
    rep["evidence"] = history(runs_, run, i, key) if key else {"similar_candles": 0, "label": "NOT ENOUGH DATA (this candle has fewer than %d candles before it, some numbers do not exist yet)" % SI.need_candles()}
    rep["opinion"] = OP.opinion(rep)
    return rep


def build(con, symbol, interval, at_text, now=None):
    now = int(time.time() if now is None else now)
    if not K._symbol_ok(symbol or "") or interval not in K.INTERVALS:
        raise ValueError("symbol must be like BTCUSDT and interval 3m or 5m")
    at = parse_at(at_text, now)
    if at > now + 60:
        raise ValueError("at is in the future")
    rows = con.execute("SELECT open_ts, o, h, l, c, v FROM (SELECT * FROM candles WHERE symbol=? AND interval=? ORDER BY open_ts DESC LIMIT ?) ORDER BY open_ts", (symbol, interval, MAX_CANDLES)).fetchall()
    return build_for(rows, symbol, interval, at, now)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--symbol", default="")
    ap.add_argument("--interval", default="5m")
    ap.add_argument("--at", default="")
    a = ap.parse_args(argv)
    path = S.store_path(a.data)
    if not os.path.isfile(path):
        print(json.dumps({"ready": False, "note": "the market store is not created yet"}))
        return 0
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    try:
        con.execute("PRAGMA query_only=ON")
        print(json.dumps(build(con, a.symbol.upper(), a.interval, a.at), indent=1))
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
