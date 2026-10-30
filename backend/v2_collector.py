"""v2_collector.py - Part 16: COLLECTORS 3 of 5 - the 5-minute ticker collector. It is OFF until the owner switches it on (kill-switch = the file v2_collector_enabled in the data folder).
What one run does: ONE public GET of all USDT futures 24h tickers -> top 20 gainers + top 20 losers saved in v2_market.db (ticker_snapshot); at the 00:00 UTC slot ONLY the official cohort
(top 5 gainers + 5 losers of the day that just ended, cohort_official). AUTHENTIC = fetched within 2 min of 00:00 UTC and every cohort ticker closed within 2 min of it; otherwise PROXY (never mixed up).
A late start never writes a cohort for that day (no back-filling of "official" data). Missing 5-min slots are RECORDED in gap_log (collector stopped, fetch failed), never invented.
Safety: public GET only (one fixed address, no key, no signature, no order code - guard test); 3 tries; a checkpoint (meta.collector_last_run_ts) makes a restart or double start harmless;
the store cap pauses writing; no trading file is touched. Not started by the backend yet (needs the owner's own ok, protected-file rule).
Run (Termux, optional):  python3 backend/v2_collector.py --on | --off | --status | --once | --loop        Tests: python3 test/test_v2_collector.py"""
import argparse
import json
import math
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_defs as D
import v2_inventory as I
import v2_store as S

VERSION = "v2_collector 1 (Part 16)"
HOST_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"          # the ONLY address this module may call
FLAG_NAME = "v2_collector_enabled"
SLOT, SNAP_TOP, COHORT_TOP = 300, 20, 5
TRIES, MAX_BYTES, TIMEOUT, FRESH_SEC = 3, 8_000_000, 10, 120


class FetchFailed(Exception):
    """All tries failed (the reason text is short and safe to print)."""


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


def http_get(url, timeout=TIMEOUT):
    if url != HOST_URL:
        raise FetchFailed("address not allowed")
    req = urllib.request.Request(url, headers={"User-Agent": "owl-v2-collector"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise FetchFailed("answer too big")
    return json.loads(raw.decode("utf-8"))


def fetch_tickers(get=http_get, sleep=time.sleep, tries=TRIES):
    last = "unknown"
    for n in range(tries):
        try:
            data = get(HOST_URL)
            if isinstance(data, list) and data:
                return data
            last = "empty or wrong answer"
        except Exception as e:                                   # any network / parse problem = try again
            last = type(e).__name__
        if n < tries - 1:
            sleep(2 ** n)
    raise FetchFailed("%d tries failed (%s)" % (tries, last))


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def parse_tickers(raw):
    """-> ({symbol: dict(open, last, vol, close_ts)}, number skipped). Only clean USDT symbols with prices above zero."""
    out, skipped = {}, 0
    for t in raw if isinstance(raw, list) else []:
        try:
            sym = t["symbol"]
            op, last, vol = _f(t["openPrice"]), _f(t["lastPrice"]), _f(t["quoteVolume"])
            ct = _f(t.get("closeTime"))
        except (KeyError, TypeError):
            skipped += 1
            continue
        if not (isinstance(sym, str) and sym.endswith("USDT") and sym.isalnum() and sym.isupper() and len(sym) <= 20) or sym in out \
                or None in (op, last, vol) or op <= 0 or last <= 0 or vol < 0:
            skipped += 1
            continue
        out[sym] = {"open": op, "last": last, "vol": vol, "close_ts": ct / 1000.0 if ct else None}
    return out, skipped


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _meta_get(con, key):
    r = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return int(r[0]) if r and str(r[0]).lstrip("-").isdigit() else None


def _checkpoint(con, run_ts):
    con.execute("INSERT OR REPLACE INTO meta VALUES ('collector_last_run_ts', ?)", (str(int(run_ts)),))


def run_once(con, data_dir, now_ts=None, get=http_get, sleep=time.sleep):
    now_ts = int(time.time() if now_ts is None else now_ts)
    if not is_enabled(data_dir):
        return {"state": "OFF"}                                  # switched off: no network, no writes
    run_ts = now_ts - now_ts % SLOT
    last = _meta_get(con, "collector_last_run_ts")
    if last is not None and run_ts <= last:
        return {"state": "SKIP_DUPLICATE", "run_ts": run_ts}
    if not S.can_write(con):
        S.add_health(con, now_ts, "FULL_PAUSED", "store at the cap, nothing written")
        return {"state": "FULL_PAUSED", "run_ts": run_ts}
    if last is not None and run_ts - last > SLOT:
        S.add_gap(con, "ticker", "*", "5m", last + SLOT, run_ts - SLOT, "collector was not running", now_ts)
    try:
        raw = fetch_tickers(get, sleep)
    except FetchFailed as e:
        S.add_gap(con, "ticker", "*", "5m", run_ts, run_ts, "fetch failed: %s" % e, now_ts)
        S.add_health(con, now_ts, "FETCH_FAILED", str(e))
        _checkpoint(con, run_ts)
        return {"state": "FETCH_FAILED", "run_ts": run_ts}
    tk, skipped = parse_tickers(raw)
    items = [(s, v["open"], v["last"]) for s, v in tk.items()]
    gain, loss = D.day_open_rank(items, "GAINER", SNAP_TOP), D.day_open_rank(items, "LOSER", SNAP_TOP)
    if gain["status"] == "UNAVAILABLE":
        S.add_gap(con, "ticker", "*", "5m", run_ts, run_ts, "no valid ticker in the answer", now_ts)
        S.add_health(con, now_ts, "NO_VALID_DATA", "skipped %d" % skipped)
        _checkpoint(con, run_ts)
        return {"state": "NO_VALID_DATA", "run_ts": run_ts}
    ranks = {}
    for r in gain["ranks"]:
        ranks[r["symbol"]] = [r["rank"], None]
    for r in loss["ranks"]:
        ranks.setdefault(r["symbol"], [None, None])[1] = r["rank"]
    con.execute("BEGIN IMMEDIATE")                               # snapshot + cohort + checkpoint: all or nothing
    try:
        saved = sum(bool(S.add_snapshot(con, run_ts, s, tk[s]["last"], round((tk[s]["last"] - tk[s]["open"]) / tk[s]["open"] * 100, 4), tk[s]["vol"], g, l)) for s, (g, l) in ranks.items())
        cohort = _cohort(con, tk, items, run_ts, now_ts)
        _checkpoint(con, run_ts)
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    S.add_health(con, now_ts, "OK", "saved %d, skipped %d, cohort %s" % (saved, skipped, cohort))
    return {"state": "OK", "run_ts": run_ts, "saved": saved, "skipped": skipped, "cohort": cohort}


def _cohort(con, tk, items, run_ts, now_ts):
    """Only the exact 00:00 UTC slot. Returns 'NONE' (not midnight), 'AUTHENTIC', 'PROXY' or 'PARTIAL' (fewer than 5 valid on a side, saved as PROXY)."""
    if run_ts % 86400 != 0:
        return "NONE"
    day = _day(run_ts - 1)                                       # the UTC day that has just ended
    picks = {"GAINER": D.day_open_rank(items, "GAINER", COHORT_TOP), "LOSER": D.day_open_rank(items, "LOSER", COHORT_TOP)}
    names = [r["symbol"] for p in picks.values() for r in p["ranks"]]
    fresh = now_ts - run_ts <= FRESH_SEC and bool(names) and all(tk[n]["close_ts"] and abs(tk[n]["close_ts"] - run_ts) <= FRESH_SEC for n in names)
    full = all(p["status"] == "OK" for p in picks.values())
    source = "AUTHENTIC" if fresh and full else "PROXY"
    for kind, p in picks.items():
        for r in p["ranks"]:
            S.add_cohort(con, day, kind, r["rank"], r["symbol"], tk[r["symbol"]]["last"], run_ts, source)
    return source if full else "PARTIAL"


def loop(data_dir, once_fn=run_once, sleep=time.sleep, clock=time.time, max_runs=None):
    n, con = 0, S.open_store(data_dir)
    try:
        while max_runs is None or n < max_runs:
            n += 1
            try:
                print(time.strftime("%H:%M:%S", time.gmtime(clock())), once_fn(con, data_dir))
            except Exception as e:                                # one bad run never ends the loop
                print("run error:", type(e).__name__)
            sleep(SLOT - clock() % SLOT + 2)                      # wake just after the next 5-min slot
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl 5-minute ticker collector (OFF by default)")
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
            print("collector switch: %s | %s" % ("ON" if is_enabled(d) else "OFF", VERSION))
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
