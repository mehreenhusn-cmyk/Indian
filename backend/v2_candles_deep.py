"""v2_candles_deep.py - Part 17b: DEEP HOLE FILLER for the candle store. Studies need 424 / 448 gap-free 5m candles (about 35 to 37 hours). The normal collector
(v2_candles.py) only refills the newest part, so a coin that came in with a short history, or a collector that was stopped for many hours, keeps an old hole for ever.
This module looks at the last WINDOW (995) closed candles of every collector coin + interval, finds the slots that are NOT saved, and asks the exchange for them
(ONE request per coin + interval, the same public klines address as v2_candles, nothing else). ONLY candles the exchange really returns are saved.
A slot the exchange does not return becomes a gap_log row ("exchange returned no candle (deep check)") and is never asked again - never bridged, never invented.
Slots before a coin was listed collapse into ONE such row. A failed coin is skipped (no gap written) and retried next run. Each coin + interval is ONE transaction.
The newest 2 candles are left to the normal collector. Same switch file as v2_candles (v2_candles_enabled): OFF = nothing happens. At most BUDGET (90) requests per run.
No key, no signature, no order code, no trading file. Run (Termux):  python3 backend/v2_candles_deep.py --plan | --once        Tests: python3 test/test_v2_candles_deep.py"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_candles as K
import v2_defs as D
import v2_inventory as I
import v2_store as S

VERSION = "v2_candles_deep 1 (Part 17b)"
WINDOW = 995                                    # closed candles looked at per coin + interval (the klines answer is at most K.MAX_LIMIT = 1000)
SKIP_NEWEST = 2                                 # the newest candles belong to the normal collector
REASON = "exchange returned no candle (deep check)"


def window_top(now_ts, interval):
    step = D.STEP[interval]
    return (now_ts // step) * step - step - SKIP_NEWEST * step         # open_ts of the newest slot this module looks at


def missing_slots(con, symbol, interval, now_ts, window=WINDOW):
    """Sorted open_ts of the slots in the window that are neither saved nor already known as 'the exchange has no candle'."""
    step, top = D.STEP[interval], window_top(now_ts, interval)
    lo = top - (window - 1) * step
    want = set(range(lo, top + 1, step))
    want -= {r[0] for r in con.execute("SELECT open_ts FROM candles WHERE symbol=? AND interval=? AND open_ts BETWEEN ? AND ?", (symbol, interval, lo, top))}
    for a, b in con.execute("SELECT from_ts, to_ts FROM gap_log WHERE kind='candle' AND symbol=? AND interval=? AND reason LIKE 'exchange returned no candle%' AND to_ts>=? AND from_ts<=?",
                            (symbol, interval, lo, top)).fetchall():
        want -= set(range(a, b + 1, step))
    return sorted(want)


def _runs(slots, step):
    out = []
    for t in slots:
        if out and t - out[-1][1] == step:
            out[-1][1] = t
        else:
            out.append([t, t])
    return out


def fill_one(con, symbol, interval, now_ts, get, sleep, counter):
    """Returns (saved, gaps). Raises K.FetchFailed when the exchange could not be asked. Zero requests when nothing is missing."""
    step, miss = D.STEP[interval], missing_slots(con, symbol, interval, now_ts)
    if not miss:
        return 0, 0
    newest = (now_ts // step) * step - step                             # open_ts of the newest CLOSED candle (same rule as v2_candles)
    rows = K._fetch(get, sleep, symbol, interval, (newest - miss[0]) // step + 2, counter)
    got, _ = K.parse_klines(rows, interval, now_ts)
    want = set(miss)
    got = [c for c in got if c[0] in want]
    have = {c[0] for c in got}
    saved = gaps = 0
    con.execute("BEGIN IMMEDIATE")
    try:
        for c in got:
            saved += bool(S.add_candle(con, symbol, interval, *c))
        for a, b in _runs([t for t in miss if t not in have], step):
            gaps += bool(S.add_gap(con, "candle", symbol, interval, a, b, REASON, now_ts))
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return saved, gaps


def plan(con, now_ts):
    """Offline: how many slots are missing per coin + interval. No request is made."""
    out = []
    for sym in K.pick_symbols(con, now_ts):
        for iv in K.INTERVALS:
            n = len(missing_slots(con, sym, iv, now_ts))
            if n:
                out.append((sym, iv, n))
    return out


def run_once(con, data_dir, now_ts=None, get=K.http_get, sleep=time.sleep, budget=K.BUDGET):
    now_ts = int(time.time() if now_ts is None else now_ts)
    if not K.is_enabled(data_dir):
        return {"state": "OFF"}
    if not S.can_write(con):
        S.add_health(con, now_ts, "DEEP_FULL_PAUSED", "store at the cap, nothing written")
        return {"state": "FULL_PAUSED"}
    syms = K.pick_symbols(con, now_ts)
    if not syms:
        S.add_health(con, now_ts, "DEEP_NO_SYMBOLS", "no cohort or ticker rows yet")
        return {"state": "NO_SYMBOLS"}
    counter, saved, gaps, failed, stopped, fails = [0], 0, 0, 0, False, []
    for sym in syms:
        for iv in K.INTERVALS:
            if counter[0] >= budget:
                stopped = True
                break
            before = counter[0]
            try:
                s, g = fill_one(con, sym, iv, now_ts, get, sleep, counter)
                saved, gaps = saved + s, gaps + g
            except K.FetchFailed as e:
                failed += 1
                fails.append("%s %s: %s" % (sym, iv, e))
            if counter[0] > before:
                sleep(0.1)                                              # gentle: one request at a time
        if stopped:
            break
    if fails:
        S.add_health(con, now_ts, "DEEP_FETCH_FAILED", "; ".join(fails[:6]))
    state = "BUDGET_STOPPED" if stopped else ("PARTIAL" if failed else "OK")
    S.add_health(con, now_ts, "DEEP_" + state, "coins %d, requests %d, saved %d, gaps %d, failed %d" % (len(syms), counter[0], saved, gaps, failed))
    return {"state": state, "coins": len(syms), "requests": counter[0], "saved": saved, "gaps": gaps, "failed": failed}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl deep hole filler for 3m/5m candles (uses the v2_candles switch)")
    g = ap.add_mutually_exclusive_group(required=True)
    for k in ("plan", "once"):
        g.add_argument("--" + k, action="store_true")
    ap.add_argument("--data")
    a = ap.parse_args(argv)
    d = I.find_data_dir(a.data)
    try:
        con = S.open_store(d)
        try:
            if a.plan:
                rows = plan(con, int(time.time()))
                print("%s | candle switch: %s | %d coin+interval pairs have holes, %d slots in all" % (VERSION, "ON" if K.is_enabled(d) else "OFF", len(rows), sum(r[2] for r in rows)))
                for r in sorted(rows, key=lambda x: -x[2])[:10]:
                    print("  %s %s: %d slots missing" % r)
            else:
                print(run_once(con, d))
        finally:
            con.close()
    except (S.StoreRefused, OSError) as e:
        print("STOP:", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
