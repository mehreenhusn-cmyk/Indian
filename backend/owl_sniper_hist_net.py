"""owl_sniper_hist_net.py - OwlSniper HISTORY BACKFILL, the ONLY network file of R1 (R1 / Round 1 of OWL_BRIEF plan v2). PAPER SIDE ONLY: it fills the CANDLE STORE and nothing else.
It takes the job list of owl_sniper_hist.plan() (coin, from, to) and downloads the missing 5m candles from the SAME public klines address as v2_candles.py, so older trades of Dual, Brain and the main bot can be replayed by the learn bridge.
Safety (same spirit as v2_candles.py): ONE fixed address, a plain GET with exactly five query words (symbol, interval, startTime, endTime, limit), the interval is always 5m, nothing else can be asked (hist_get refuses every other address).
No login, no account call, no trading file, no trading import. ONLY candles the exchange really returns are saved; a slot the exchange does not return becomes a gap_log row ("exchange returned no candle (history)") and is never asked again - never bridged, never invented.
Switch: the SAME file as the candle collector (v2_candles_enabled): OFF = nothing happens. Also off while the file v2_sniper_off exists. At most BUDGET (60) requests per run, 0.2 s between requests. A failing coin is skipped, retried later, and after 3 failures it rests for 24 hours.
Each coin chunk is ONE transaction. When the store is at its cap nothing is written. Candles older than the store keeps (30 days for 5m) are never asked, because the store would purge them again.
Run (Termux, optional):  python3 backend/owl_sniper_hist_net.py --plan | --once [--data DIR]        The backend also runs it by itself every 10 minutes (api/sniper_hist.py).        Tests: none (owner rule), syntax checked only."""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_bridge_src as BS
import owl_sniper_feed as F
import owl_sniper_hist as H
import v2_candles as K
import v2_candles_deep as DP
import v2_store as S

VERSION = "owl_sniper_hist_net 1 (R1)"
BASE = K.BASE
QUERY_WORDS = ["endTime", "interval", "limit", "startTime", "symbol"]
STEP, BUDGET, PAUSE_SEC, LOOP_SEC, IDLE_SEC, FIRST_WAIT = 300, 60, 0.2, 600, 3600, 60
REASON = "exchange returned no candle (history)"
REST_AFTER, REST_SEC = 3, 86400
_fails = {}                                            # symbol -> [count, last failure ts] (memory only)


def hist_url(symbol, from_ts, to_ts, limit):
    q = [("symbol", symbol), ("interval", "5m"), ("startTime", int(from_ts) * 1000), ("endTime", int(to_ts) * 1000), ("limit", int(limit))]
    return BASE + "?" + urllib.parse.urlencode(q)


def hist_get(url, timeout=K.TIMEOUT):
    """The ONLY thing this module may call: BASE plus exactly the five query words, 5m, numbers in range. Anything else is refused before a request is made."""
    u = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    if url.split("?")[0] != BASE or sorted(q) != QUERY_WORDS or any(len(v) != 1 for v in q.values()) or not K._symbol_ok(q["symbol"][0]) or q["interval"][0] != "5m" \
            or not all(q[k][0].isdigit() for k in ("startTime", "endTime", "limit")) or not 1 <= int(q["limit"][0]) <= K.MAX_LIMIT \
            or not 10 ** 12 < int(q["startTime"][0]) <= int(q["endTime"][0]) < 10 ** 13:
        raise K.FetchFailed("address not allowed")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "owl-sniper-hist"}), timeout=timeout) as r:
        raw = r.read(K.MAX_BYTES + 1)
    if len(raw) > K.MAX_BYTES:
        raise K.FetchFailed("answer too big")
    return json.loads(raw.decode("utf-8"))


def _ask(get, sleep, job, counter):
    last = "unknown"
    for n in range(K.TRIES):
        counter[0] += 1
        try:
            rows = get(hist_url(job["symbol"], job["from_ts"], job["to_ts"], job["slots"]))
            if isinstance(rows, list):
                return rows
            last = "wrong answer"
        except Exception as e:
            last = type(e).__name__
        if n < K.TRIES - 1:
            sleep(1)
    raise K.FetchFailed(last)


def fill_job(con, job, now_ts, get, sleep, counter):
    """One chunk -> (saved, gaps). Raises K.FetchFailed when the exchange could not be asked."""
    rows = _ask(get, sleep, job, counter)
    got, _bad = K.parse_klines(rows, "5m", now_ts)
    want = set(range(job["from_ts"], job["to_ts"] + 1, STEP))
    got = [c for c in got if c[0] in want]
    have = {c[0] for c in got}
    saved = gaps = 0
    con.execute("BEGIN IMMEDIATE")
    try:
        for c in got:
            saved += bool(S.add_candle(con, job["symbol"], "5m", *c))
        saved_now = {r[0] for r in con.execute("SELECT open_ts FROM candles WHERE symbol=? AND interval='5m' AND open_ts BETWEEN ? AND ?", (job["symbol"], job["from_ts"], job["to_ts"]))}
        for a, b in DP._runs(sorted(t for t in want if t not in have and t not in saved_now), STEP):
            gaps += bool(S.add_gap(con, "candle", job["symbol"], "5m", a, b, REASON, now_ts))
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return saved, gaps


def _resting(sym, now_ts):
    c = _fails.get(sym)
    return bool(c and c[0] >= REST_AFTER and now_ts - c[1] < REST_SEC)


def run_once(d, now_ts=None, get=hist_get, sleep=time.sleep, budget=BUDGET, p=None):
    """One run. -> {state, requests, saved, gaps, failed, left, lines}. Never raises for a bad coin; a store problem is reported."""
    now_ts = int(time.time() if now_ts is None else now_ts)
    if not K.is_enabled(d):
        return {"state": "OFF", "lines": ["The candle collector switch is OFF, so no history is downloaded."]}
    if os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
        return {"state": "SNIPER_OFF", "lines": ["The Sniper is switched off (file v2_sniper_off)."]}
    p = p or H.plan(d, now_ts)
    if p["state"] != "OK":
        return {"state": p["state"], "lines": p["lines"]}
    jobs = [j for j in p["jobs"] if not _resting(j["symbol"], now_ts)]
    if not jobs:
        return {"state": "NOTHING_TO_DO", "left": 0, "lines": p["lines"]}
    con = S.open_store(d)
    try:
        if not S.can_write(con):
            S.add_health(con, now_ts, "HIST_FULL_PAUSED", "store at the cap, nothing written")
            return {"state": "FULL_PAUSED", "left": len(jobs), "lines": ["The candle store is full, so no history is saved."]}
        counter, saved, gaps, failed, done, stopped, fails = [0], 0, 0, 0, 0, False, []
        for j in jobs:
            if counter[0] >= budget:
                stopped = True
                break
            before, done = counter[0], done + 1
            try:
                s, g = fill_job(con, j, now_ts, get, sleep, counter)
                saved, gaps = saved + s, gaps + g
                _fails.pop(j["symbol"], None)
            except K.FetchFailed as e:
                failed += 1
                c = _fails.setdefault(j["symbol"], [0, now_ts])
                c[0], c[1] = c[0] + 1, now_ts
                fails.append("%s: %s" % (j["symbol"], e))
            if counter[0] > before:
                sleep(PAUSE_SEC)
        state = "BUDGET_STOPPED" if stopped else ("PARTIAL" if failed else "OK")
        if fails:
            S.add_health(con, now_ts, "HIST_FETCH_FAILED", "; ".join(fails[:6]))
        S.add_health(con, now_ts, "HIST_" + state, "jobs %d, requests %d, saved %d, gaps %d, failed %d" % (len(jobs), counter[0], saved, gaps, failed))
        return {"state": state, "requests": counter[0], "saved": saved, "gaps": gaps, "failed": failed, "left": len(jobs) - done + failed,
                "lines": ["History download: %d requests, %d candles saved, %d holes noted, %d failed." % (counter[0], saved, gaps, failed)]}
    finally:
        con.close()


def loop_forever(d, state, sleep=time.sleep):
    """Background loop (a daemon thread started by api/sniper_hist.py). state = a dict the route reads. Never raises."""
    sleep(FIRST_WAIT)
    while True:
        try:
            res = run_once(d)
        except Exception as e:
            res = {"state": "error", "lines": ["The history download stopped: %s." % str(e)[:80]]}
        res["ts"] = int(time.time())
        state["last"], state["turns"] = res, state.get("turns", 0) + 1
        sleep(IDLE_SEC if res.get("state") in ("NOTHING_TO_DO", "OFF", "SNIPER_OFF", "NO_RECORDS", "NO_STORE") else LOOP_SEC)


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper history backfill (candle store only)")
    g = ap.add_mutually_exclusive_group(required=True)
    for k in ("plan", "once"):
        g.add_argument("--" + k, action="store_true")
    ap.add_argument("--data", default=BS.default_dir())
    a = ap.parse_args(argv)
    try:
        print(json.dumps(H.short(H.plan(a.data)) if a.plan else run_once(a.data), indent=1))
    except (S.StoreRefused, OSError) as e:
        print("STOP:", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
