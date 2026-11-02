"""v2_candles.py - Part 17: COLLECTORS 4 of 5 - closed 3m / 5m candles for at most 40 coins, with gap refill from public klines. OFF until the owner switches it on
(kill-switch = the file v2_candles_enabled in the data folder, separate from the ticker switch). Coins = cohort of the last 2 days first, then the newest ticker_snapshot, max 40. Each run asks ONLY for what is missing (nothing missing = no request).
Only CLOSED candles are saved. Start = last 500 candles (about 41 hours on 5m); a stop of up to 999 candles is refilled; an older hole or a candle the exchange does not return goes to gap_log - never bridged.
Rate budget: at most 90 requests per run, retries included (the rest waits). Public GET only: ONE address + 3 fixed query words, no key / signature / order code (guard test).
A failed coin is skipped and retried next run (no gap written). Each coin+interval is saved in ONE transaction. No trading file is touched.
Run (Termux, optional):  python3 backend/v2_candles.py --on | --off | --status | --once | --loop        Tests: python3 test/test_v2_candles.py"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_defs as D
import v2_inventory as I
import v2_store as S

VERSION = "v2_candles 1 (Part 17)"
BASE = "https://fapi.binance.com/fapi/v1/klines"            # the ONLY address this module may call
FLAG_NAME = "v2_candles_enabled"
INTERVALS = ("3m", "5m")
MAX_SYMBOLS, BUDGET, INITIAL, MAX_LIMIT, TRIES, TIMEOUT, MAX_BYTES, LOOP_SEC = 40, 90, 500, 1000, 2, 10, 2_000_000, 60


class FetchFailed(Exception):
    """The request failed or was refused (short text, safe to print)."""


def _symbol_ok(s):
    return isinstance(s, str) and s.endswith("USDT") and s.isalnum() and s.isupper() and len(s) <= 20


def flag_path(data_dir):
    return os.path.join(os.path.realpath(data_dir), FLAG_NAME)


def is_enabled(data_dir):
    p = flag_path(data_dir)
    try:
        if os.path.islink(p) or not os.path.isfile(p):
            return False
        with open(p, "r", encoding="utf-8") as f:
            return f.read(10).strip().lower() in ("1", "on", "true", "yes")
    except OSError:
        return False


def set_enabled(data_dir, on):
    p = flag_path(data_dir)
    if os.path.islink(p):
        raise S.StoreRefused("the switch file must not be a link")
    with open(p, "w", encoding="utf-8") as f:
        f.write("1\n" if on else "0\n")


def kline_url(symbol, interval, limit):
    return BASE + "?" + urllib.parse.urlencode([("symbol", symbol), ("interval", interval), ("limit", int(limit))])


def http_get(url, timeout=TIMEOUT):
    u = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    if url.split("?")[0] != BASE or sorted(q) != ["interval", "limit", "symbol"] or any(len(v) != 1 for v in q.values()) \
            or not _symbol_ok(q["symbol"][0]) or q["interval"][0] not in INTERVALS or not q["limit"][0].isdigit() or not 1 <= int(q["limit"][0]) <= MAX_LIMIT:
        raise FetchFailed("address not allowed")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "owl-v2-candles"}), timeout=timeout) as r:
        raw = r.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise FetchFailed("answer too big")
    return json.loads(raw.decode("utf-8"))


def parse_klines(rows, interval, now_ts):
    """-> (closed candles on the grid, number dropped as bad). The forming candle is dropped silently; it is not an error."""
    step, out, bad = D.STEP[interval], [], 0
    for r in rows if isinstance(rows, list) else []:
        try:
            ts, o, h, l, c, v = int(r[0]) // 1000, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])
        except (TypeError, ValueError, IndexError):
            bad += 1
            continue
        if ts % step or ts + step > now_ts:
            bad += 0 if ts % step == 0 else 1
            continue
        out.append((ts, o, h, l, c, v))
    good, b2 = D.clean_candles(out, interval)
    return good, bad + b2


def pick_symbols(con, now_ts, cap=MAX_SYMBOLS):
    out = []

    def add(s):
        if _symbol_ok(s) and s not in out and len(out) < cap:
            out.append(s)
    for (day,) in con.execute("SELECT DISTINCT day FROM cohort_official ORDER BY day DESC LIMIT 2").fetchall():
        for (s,) in con.execute("SELECT symbol FROM cohort_official WHERE day=? ORDER BY kind, rank", (day,)).fetchall():
            add(s)
    last = con.execute("SELECT MAX(run_ts) FROM ticker_snapshot").fetchone()[0]
    if last is not None and last >= now_ts - 86400:
        for (s,) in con.execute("SELECT symbol FROM ticker_snapshot WHERE run_ts=? ORDER BY MIN(COALESCE(rank_gain,999), COALESCE(rank_loss,999)), COALESCE(rank_gain,999), symbol", (last,)).fetchall():
            add(s)
    return out


def known_until(con, symbol, interval):
    """Newest open_ts we already KNOW about: a saved candle or a recorded gap. Nothing newer is asked again and again."""
    a = con.execute("SELECT MAX(open_ts) FROM candles WHERE symbol=? AND interval=?", (symbol, interval)).fetchone()[0]
    b = con.execute("SELECT MAX(to_ts) FROM gap_log WHERE kind='candle' AND symbol=? AND interval=?", (symbol, interval)).fetchone()[0]
    return max([x for x in (a, b) if x is not None], default=None)


def _fetch(get, sleep, symbol, interval, limit, counter):
    last = "unknown"
    for n in range(TRIES):
        counter[0] += 1
        try:
            rows = get(kline_url(symbol, interval, limit))
            if isinstance(rows, list):
                return rows
            last = "wrong answer"
        except Exception as e:
            last = type(e).__name__
        if n < TRIES - 1:
            sleep(1)
    raise FetchFailed(last)


def refill_one(con, symbol, interval, now_ts, get, sleep, counter):
    """Returns (saved, gaps). Raises FetchFailed when the exchange could not be asked. Zero requests when nothing is missing."""
    step = D.STEP[interval]
    newest = now_ts // step * step - step                      # open_ts of the newest CLOSED candle
    known = known_until(con, symbol, interval)
    if known is None:
        start, old_gap = newest - (INITIAL - 1) * step, None
    else:
        missing = (newest - known) // step
        if missing <= 0:
            return 0, 0
        start = max(known + step, newest - (MAX_LIMIT - 2) * step)
        old_gap = (known + step, start - step) if start > known + step else None
    rows = _fetch(get, sleep, symbol, interval, (newest - start) // step + 2, counter)    # +1 for the forming candle
    got, _ = parse_klines(rows, interval, now_ts)
    got = [c for c in got if start <= c[0] <= newest]
    have = {c[0] for c in got}
    saved = gaps = 0
    con.execute("BEGIN IMMEDIATE")
    try:
        for c in got:
            saved += bool(S.add_candle(con, symbol, interval, *c))
        holes = [t for t in range(start, newest + 1, step) if t not in have]
        runs = []
        for t in holes:
            if runs and t - runs[-1][1] == step:
                runs[-1][1] = t
            else:
                runs.append([t, t])
        for a, b in runs:
            gaps += bool(S.add_gap(con, "candle", symbol, interval, a, b, "exchange returned no candle", now_ts))
        if old_gap:
            gaps += bool(S.add_gap(con, "candle", symbol, interval, old_gap[0], old_gap[1], "too old to refill (over %d candles)" % (MAX_LIMIT - 1), now_ts))
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return saved, gaps


def run_once(con, data_dir, now_ts=None, get=http_get, sleep=time.sleep, budget=BUDGET):
    now_ts = int(time.time() if now_ts is None else now_ts)
    if not is_enabled(data_dir):
        return {"state": "OFF"}
    if not S.can_write(con):
        S.add_health(con, now_ts, "CANDLES_FULL_PAUSED", "store at the cap, nothing written")
        return {"state": "FULL_PAUSED"}
    syms = pick_symbols(con, now_ts)
    if not syms:
        S.add_health(con, now_ts, "CANDLES_NO_SYMBOLS", "no cohort or ticker rows yet")
        return {"state": "NO_SYMBOLS"}
    counter, saved, gaps, failed, stopped, fails = [0], 0, 0, 0, False, []
    for sym in syms:
        for iv in INTERVALS:
            if counter[0] >= budget:
                stopped = True
                break
            before = counter[0]
            try:
                s, g = refill_one(con, sym, iv, now_ts, get, sleep, counter)
                saved, gaps = saved + s, gaps + g
            except FetchFailed as e:
                failed += 1
                fails.append("%s %s: %s" % (sym, iv, e))
            if counter[0] > before:
                sleep(0.1)                                      # gentle: one request at a time
        if stopped:
            break
    if fails:                                                   # Part 85b: WHICH coins failed and why (the Brain says it when a coin has no data)
        S.add_health(con, now_ts, "CANDLES_FETCH_FAILED", "; ".join(fails[:6]))
    state = "BUDGET_STOPPED" if stopped else ("PARTIAL" if failed else "OK")
    S.add_health(con, now_ts, "CANDLES_" + state, "coins %d, requests %d, saved %d, gaps %d, failed %d" % (len(syms), counter[0], saved, gaps, failed))
    return {"state": state, "coins": len(syms), "requests": counter[0], "saved": saved, "gaps": gaps, "failed": failed}


def loop(data_dir, once_fn=run_once, sleep=time.sleep, clock=time.time, max_runs=None):
    n, con = 0, S.open_store(data_dir)
    try:
        while max_runs is None or n < max_runs:
            n += 1
            try:
                print(time.strftime("%H:%M:%S", time.gmtime(clock())), once_fn(con, data_dir))
            except Exception as e:                              # one bad run never ends the loop
                print("run error:", type(e).__name__)
            sleep(LOOP_SEC)
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl 3m/5m candle collector (OFF by default)")
    g = ap.add_mutually_exclusive_group(required=True)
    for k in ("on", "off", "status", "once", "loop"):
        g.add_argument("--" + k, action="store_true")
    ap.add_argument("--data")
    a = ap.parse_args(argv)
    d = I.find_data_dir(a.data)
    try:
        if a.on or a.off:
            set_enabled(d, a.on)
        if a.status or a.on or a.off:
            print("candle switch: %s | %s" % ("ON" if is_enabled(d) else "OFF", VERSION))
            return 0
        if a.loop:
            loop(d)
            return 0
        con = S.open_store(d)
        print(run_once(con, d))
        con.close()
    except (S.StoreRefused, OSError) as e:
        print("STOP:", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
