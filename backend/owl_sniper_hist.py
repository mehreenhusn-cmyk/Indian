"""owl_sniper_hist.py - OwlSniper HISTORY COVERAGE + BACKFILL PLAN (R1 / Round 1 of OWL_BRIEF plan v2). READ ONLY: no network, nothing is written, no trading file is touched.
Why: the learn bridge (owl_sniper_bridge_*.py) needs the saved 5m candles at the time of EVERY closed trade of Dual, Brain and the main bot (400 candles before the entry, 32 after it).
The candle collector only started a few days ago and only follows ~40 coins, so most older trades were skipped (before_candles / no_candles). The store keeps 5m candles for 30 days (v2_store.KEEP_DAYS),
so the older candles can still be asked from the exchange. This file answers, WITHOUT any request: which trades are ready, which can be made ready, which can never be (too old, unsupported interval, hole at the exchange).
It also builds the JOB list (coin, from, to, slots) that owl_sniper_hist_net.py downloads. Only slots that are really missing are listed. Nothing is invented.
Per trade:  ready = every slot of its window is saved | needs_fetch = slots missing, can be asked | known_gap = the exchange has no candle for a slot of the window (never asked again)
            too_old = window starts before the store keeps candles | too_recent = newest candles belong to the normal collector | tf_unsupported / tf_unknown = only 5m and 15m are supported (15m is built from 5m).
Run (Termux):  python3 backend/owl_sniper_hist.py [--data DIR]   -> JSON (the data folder defaults to OWL_DATA_DIR, else ~/owl_data).   Tests: none (owner rule), syntax checked only."""
import argparse
import bisect
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_bridge_label as LB
import owl_sniper_bridge_replay as RP
import owl_sniper_bridge_src as BS
import owl_sniper_feed as F
import owl_sniper_tf as TF
import v2_store as S

VERSION = "owl_sniper_hist 1 (R1)"
STEP = 300                                        # the only saved interval: 5m (15m is built from it)
KEEP_SEC = (S.KEEP_DAYS["candles_5m"] - 1) * 86400   # one day of safety before the store purges its oldest candles
SKIP_NEWEST = 2                                   # the newest candles belong to the normal collector
GAP_LIKE = "exchange returned no candle%"
MERGE_HOLE = 12                                   # runs closer than this many slots become ONE request (a few saved candles are asked again, harmless)
CHUNK = 1000                                      # slots per request (exchange answer limit)


def newest_slot(now_ts):
    return (int(now_ts) // STEP) * STEP - STEP - SKIP_NEWEST * STEP


def record_window(rec, now_ts):
    """-> (lo, hi, None) with open_ts of the first and last 5m slot the bridge needs for this trade, or (None, None, reason)."""
    tf = rec.get("tf")
    if not tf:
        return None, None, "tf_unknown"
    if tf not in TF.SUPPORTED:
        return None, None, "tf_unsupported"
    step, t = TF.step(tf), rec["entry_ts"]
    lo = int((t - (RP.WARM + 2) * step) // STEP * STEP)
    hi = min(int((t + (LB.HOLD + 2) * step) // STEP * STEP), newest_slot(now_ts))
    if lo < now_ts - KEEP_SEC:
        return None, None, "too_old"
    if hi <= lo or t > newest_slot(now_ts) - LB.HOLD * step:
        return None, None, "too_recent"
    return lo, hi, None


def _symbol_state(con, sym, lo, hi):
    """(sorted saved open_ts, sorted open_ts the exchange is known NOT to have) inside [lo, hi]."""
    have = [r[0] for r in con.execute("SELECT open_ts FROM candles WHERE symbol=? AND interval='5m' AND open_ts BETWEEN ? AND ? ORDER BY open_ts", (sym, lo, hi))]
    gap = set()
    for a, b in con.execute("SELECT from_ts, to_ts FROM gap_log WHERE kind='candle' AND symbol=? AND interval='5m' AND reason LIKE ? AND to_ts>=? AND from_ts<=?", (sym, GAP_LIKE, lo, hi)).fetchall():
        gap.update(range(max(a, lo), min(b, hi) + 1, STEP))
    return have, sorted(gap)


def _count(sorted_list, lo, hi):
    return bisect.bisect_right(sorted_list, hi) - bisect.bisect_left(sorted_list, lo)


def _merge(spans):
    out = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1] + STEP:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def _jobs_for(sym, spans, have, gap):
    """Missing slots of the merged spans -> runs -> merged over tiny holes -> chunks of at most CHUNK slots. Newest first."""
    hs, gs, runs = set(have), set(gap), []
    for lo, hi in _merge(spans):
        for t in range(lo, hi + 1, STEP):
            if t in hs or t in gs:
                continue
            if runs and t - runs[-1][1] <= (MERGE_HOLE + 1) * STEP:
                runs[-1][1], runs[-1][2] = t, runs[-1][2] + 1
            else:
                runs.append([t, t, 1])
    jobs = []
    for a, b, n in runs:
        while a <= b:
            e = min(b, a + (CHUNK - 1) * STEP)
            jobs.append({"symbol": sym, "from_ts": a, "to_ts": e, "slots": (e - a) // STEP + 1})
            a = e + STEP
    jobs.sort(key=lambda j: -j["to_ts"])
    return jobs


def plan(d, now_ts=None, records=None, con=None):
    """Offline answer. -> dict (state, by_source, tf_unsupported, symbols, slots_missing, requests_needed, jobs, lines). Never raises."""
    now_ts = int(time.time() if now_ts is None else now_ts)
    out = {"version": VERSION, "state": "OK", "records": 0, "by_source": {}, "tf_unsupported": {}, "symbols": 0, "slots_missing": 0, "requests_needed": 0, "jobs": [], "lines": []}
    own = False
    try:
        if records is None:
            records = BS.collect(d)["records"]
        if con is None:
            con, own = F.open_ro(d), True
        out["records"] = len(records)
        if not records:
            out["state"] = "NO_RECORDS"
            out["lines"].append("No closed trades were found in the data folder: %s" % os.path.realpath(d))
            return out
        if con is None:
            out["state"] = "NO_STORE"
            out["lines"].append("The candle store (v2_market.db) does not exist in the data folder yet.")
            return out
        per, need = out["by_source"], {}
        for r in records:
            b = per.setdefault(r["source"], {"records": 0, "ready": 0, "needs_fetch": 0, "known_gap": 0, "too_old": 0, "too_recent": 0, "tf_unsupported": 0, "tf_unknown": 0})
            b["records"] += 1
            lo, hi, why = record_window(r, now_ts)
            if why:
                b[why] += 1
                if why == "tf_unsupported":
                    out["tf_unsupported"][r["tf"]] = out["tf_unsupported"].get(r["tf"], 0) + 1
                continue
            need.setdefault(r["symbol"], []).append((lo, hi, r["source"]))
        jobs = []
        for sym, items in need.items():
            have, gap = _symbol_state(con, sym, min(i[0] for i in items), max(i[1] for i in items))
            fetch_spans = []
            for lo, hi, src in items:
                n = (hi - lo) // STEP + 1
                h, g = _count(have, lo, hi), _count(gap, lo, hi)
                if h == n:
                    per[src]["ready"] += 1
                elif h + g == n:
                    per[src]["known_gap"] += 1
                else:
                    per[src]["needs_fetch"] += 1
                    fetch_spans.append((lo, hi))
            if fetch_spans:
                jobs += _jobs_for(sym, fetch_spans, have, gap)
        jobs.sort(key=lambda j: -j["to_ts"])
        out["jobs"], out["symbols"] = jobs, len(need)
        out["slots_missing"], out["requests_needed"] = sum(j["slots"] for j in jobs), len(jobs)
        ready = sum(b["ready"] for b in per.values())
        fix = sum(b["needs_fetch"] for b in per.values())
        out["lines"].append("%d closed trades: %d ready for the bridge, %d can be made ready by downloading %d candles in about %d requests." % (len(records), ready, fix, out["slots_missing"], len(jobs)))
        if out["tf_unsupported"]:
            out["lines"].append("Trades on other intervals cannot be used yet (only 5m and 15m): %s." % ", ".join("%s %d" % kv for kv in sorted(out["tf_unsupported"].items())))
        return out
    except Exception as e:                               # a damaged file must never stop the backend
        out["state"], out["lines"] = "error", ["The history plan could not be built: %s." % str(e)[:80]]
        return out
    finally:
        if own and con is not None:
            con.close()


def short(p):
    """The plan without the long job list (small answer for the app)."""
    return {k: v for k, v in p.items() if k != "jobs"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper history coverage plan (read only)")
    ap.add_argument("--data", default=BS.default_dir())
    a = ap.parse_args(argv)
    print(json.dumps(short(plan(a.data)), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
