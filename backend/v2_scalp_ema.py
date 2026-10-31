"""v2_scalp_ema.py - Part 52: SCALP LAB 3 of 8 (backend, read-only, HYPOTHETICAL replay). Category EMA_RETEST: "after the close crossed EMA50, did a RETEST of EMA50 give a clean quick entry, and what would it have done?"
The rule is written down BEFORE any test (README4 9.7) and has its own definition + version (DEFINITION below, DEF_VERSION 1). Starting values are marked NV = not validated, they sit in the constants.
THE RULE (candle-close execution, the first price anybody could have used):
  CROSS   = the bot's own rule on a closed candle: close crosses EMA50 up (BUY) or down (SELL) (v2_scalp_ind.ema_cross). BUY -> side LONG, SELL -> side SHORT.
  RETEST  = within RETEST_WINDOW candles after the cross, the first candle that TOUCHES EMA50 (LONG: low <= EMA50, SHORT: high >= EMA50) and CLOSES back on the trend side. The entry price is that candle's close.
  INVALID = before / at the retest a candle closes on the wrong side of EMA50 (LONG: close below, SHORT: close above) -> no entry, counted as INVALIDATED (checked first).
  STOP    = the retest candle's low (LONG) / high (SHORT). TARGET = entry +/- R_MULT x risk. EXIT = target, stop, or MAX_HOLD candles (v2_replay.simulate: stop and target in one candle = STOP).
  RISK    = distance entry-to-stop in % of the entry; outside MIN_RISK_PCT..MAX_RISK_PCT the setup is SKIPPED_RISK (too tight to trade after fees / too wide), counted, never forced.
Each cross ends in exactly ONE status: TRADED (with its outcome TARGET / STOP / TIME / PENDING / UNAVAILABLE), SKIPPED_RISK, INVALIDATED, NO_RETEST (window over), PENDING (window not over yet) or UNAVAILABLE (a candle gap before the window ended). Nothing is counted as 0 or bridged.
LONG and SHORT are always reported apart. Older signals = TRAIN, the newest 30% of signal times = HOLDOUT (v2_replay.holdout_cut). A BASELINE of ordinary candles (every 12th, same risk % and same R, per side) is shown beside it:
a retest means something only if it differs from the baseline AND n is large. Fewer than 30 finished = "too few to say anything". Fees + slippage are taken off (v2_replay costs); no win rate, no prediction, no order, nothing is written (the runner of Part 54 saves records).
Uses only the owner's EMA50 for the rule; the TSI / Z words at the signal candle are only CONTEXT on each event (for the later Combined category), never a filter.
Run (Termux):  python3 backend/v2_scalp_ema.py [--data DIR] [--days N]     Route: GET /api/v2/scalp_ema[?days=N] (api/v2_data.py), N = 1 to 7 (default 1)."""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_defs as D
import v2_replay as R
import v2_scalp_ind as I
import v2_setup_finder as SF
import v2_store as S

VERSION = "v2_scalp_ema 1 (Part 52)"
CATEGORY = "EMA_RETEST"
DEF_VERSION = 1
RETEST_WINDOW = 12               # candles after the cross in which the retest must come (NV)
R_MULT = 1.5                     # target = 1.5 x the risk (NV)
MAX_HOLD = 24                    # candles (NV)
MIN_RISK_PCT = 0.05              # below this the stop is too tight to trade after fees (NV)
MAX_RISK_PCT = 2.0               # above this the stop is too wide for a scalp (NV)
WARMUP_SECS = 20 * 3600          # candles taken before the window so EMA50 exists at its start
BASE_EVERY = 12
MAX_EVENTS = 200
SIDE = {"BUY": "LONG", "SELL": "SHORT"}
STATUSES = ("TRADED", "SKIPPED_RISK", "INVALIDATED", "NO_RETEST", "PENDING", "UNAVAILABLE")
DEFINITION = {
    "entry": "close of the first candle after an EMA50 cross that touches EMA50 and closes back on the trend side, within %d candles" % RETEST_WINDOW,
    "invalidation": "a candle closes on the wrong side of EMA50 before / at the retest",
    "stop": "low (LONG) / high (SHORT) of the retest candle",
    "exit": "target = entry +/- %.1f x risk; stop; or time exit; stop first when both are in one candle" % R_MULT,
    "max_hold": "%d candles" % MAX_HOLD,
    "fees": "%.2f%% per side (v2_replay)" % R.FEE_PCT,
    "slippage": "%.2f%% per side (v2_replay)" % R.SLIP_PCT,
    "window": "closed 3m / 5m candles of one gap-free run, execution at candle close",
}


def _retest(run, ind, k, side):
    """-> (status, j). status RETEST (j = the retest candle), INVALIDATED, NO_RETEST, PENDING or UNAVAILABLE. Needs ind aligned with run."""
    last = min(k + RETEST_WINDOW, len(run) - 1)
    for j in range(k + 1, last + 1):
        e, c = ind["ema50"][j], ind["close"][j]
        if e is None:
            return "UNAVAILABLE", None
        if (side == "LONG" and c < e) or (side == "SHORT" and c > e):
            return "INVALIDATED", None
        if (side == "LONG" and run[j][3] <= e) or (side == "SHORT" and run[j][2] >= e):
            return "RETEST", j
    return ("NO_RETEST", None) if k + RETEST_WINDOW < len(run) else ("PENDING", None)


def scan_run(run, step, first, now, sym, iv):
    """All crosses of ONE gap-free run whose cross candle is at or after `first`. -> (indicator series of the run, list of event dicts; statuses in the module text)."""
    ind = I.compute(run)
    out = []
    for k in range(1, len(run)):
        cross = I.ema_cross(ind, k)
        if cross is None or run[k][0] < first:
            continue
        side = SIDE[cross]
        ev = {"symbol": sym, "interval": iv, "side": side, "cross_ts": run[k][0], "cross_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(run[k][0]))}
        st, j = _retest(run, ind, k, side)
        if st == "PENDING" and run[k][0] + step * (RETEST_WINDOW + 1) <= now:
            st = "UNAVAILABLE"            # the run ended early (a gap) and the window is over in real time
        if st != "RETEST":
            ev["status"] = st
            out.append(ev)
            continue
        entry = run[j][4]
        stop = run[j][3] if side == "LONG" else run[j][2]
        risk = abs(entry - stop) / entry * 100.0
        ev.update(signal_ts=run[j][0], retest_utc=time.strftime("%Y-%m-%d %H:%M", time.gmtime(run[j][0])), entry=entry, stop=stop, risk_pct=round(risk, 3))
        s = I.state(ind, j)
        ev["context"] = {"tsi_vs_signal": s["tsi_vs_signal"], "z_vs_sma": s["z_vs_sma"], "band_zone": s["band_zone"]}
        if not MIN_RISK_PCT <= risk <= MAX_RISK_PCT:
            ev["status"] = "SKIPPED_RISK"
            out.append(ev)
            continue
        target = entry + R_MULT * (entry - stop) if side == "LONG" else entry - R_MULT * (stop - entry)
        r = R.simulate(run, j, side, stop, target, MAX_HOLD, step, now)
        ev["status"], ev["outcome"] = "TRADED", r["status"]
        if r["status"] in R.FINISHED_STATUSES:
            ev.update(exit_price=r["exit_price"], hold_candles=r["hold_candles"], gross_pct=round(r["gross_pct"], 4), net_pct=round(r["net_pct"], 4), same_candle=r["same_candle"])
        out.append(ev)
    return ind, out


def baseline(run, step, first, now, risk_pct):
    """Ordinary candles: every BASE_EVERY-th candle, both sides, the SAME risk % and R. -> {side: [(status, net_pct)]} finished only."""
    res = {"LONG": [], "SHORT": []}
    if not risk_pct:
        return res
    for i in range(I.EMA_LEN, len(run), BASE_EVERY):
        if run[i][0] < first:
            continue
        e = run[i][4]
        for side, sgn in (("LONG", 1), ("SHORT", -1)):
            r = R.simulate(run, i, side, e * (1 - sgn * risk_pct / 100.0), e * (1 + sgn * R_MULT * risk_pct / 100.0), MAX_HOLD, step, now)
            if r["status"] in R.FINISHED_STATUSES:
                res[side].append((r["status"], r["net_pct"]))
    return res


def records(events, cut, version=DEF_VERSION):
    """The finished TRADED events as dicts for v2_scalp_store.add_record (the runner of Part 54 calls it). Nothing is saved here."""
    return [dict(symbol=e["symbol"], interval=e["interval"], side=e["side"], signal_ts=e["signal_ts"], sample=R.sample_of(e["signal_ts"], cut), entry=e["entry"], exit_price=e["exit_price"],
                 status=e["outcome"], hold_candles=e["hold_candles"], gross_pct=e["gross_pct"], net_pct=e["net_pct"]) for e in events if e.get("outcome") in R.FINISHED_STATUSES]


def build(con, now=None, days=None):
    """-> the report dict (read-only). days = 1 to 7 (default 1) = how far back the crosses are taken. Raises ValueError on a bad days value."""
    now = int(time.time() if now is None else now)
    if days in (None, ""):
        days = 1
    if not str(days).isdigit() or not 1 <= int(days) <= 7:
        raise ValueError("days must be a whole number from 1 to 7")
    days = int(days)
    first = now - days * 86400
    a = first - WARMUP_SECS
    syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM candles WHERE open_ts>=? AND open_ts<=?", (a, now))]
    events, runs_used, used = [], [], 0
    for s in sorted(syms):
        best = (None, [])
        for iv in ("5m", "3m"):
            good, _bad = D.clean_candles(D.candles_from_store(con, s, iv, a, now), iv)
            if len(good) > len(best[1]):
                best = (iv, good)
        iv, good = best
        if iv is None:
            continue
        used += 1
        for run in SF.runs(good, iv):
            ind, ev = scan_run(run, D.STEP[iv], first, now, s, iv)
            events.extend(ev)
            runs_used.append((run, D.STEP[iv], iv))
    traded = [e for e in events if e["status"] == "TRADED"]
    cut = R.holdout_cut([e["signal_ts"] for e in traded if e.get("outcome") in R.FINISHED_STATUSES])
    cells = {sd: {"statuses": {k: 0 for k in STATUSES}, "outcomes": {"TARGET": 0, "STOP": 0, "TIME": 0, "PENDING": 0, "UNAVAILABLE": 0}, "risk": [], "rows": {"TRAIN": [], "HOLDOUT": []}} for sd in R.SIDES}
    for e in events:
        c = cells[e["side"]]
        c["statuses"][e["status"]] += 1
        if "risk_pct" in e:
            c["risk"].append(e["risk_pct"])
        if e["status"] == "TRADED":
            c["outcomes"][e["outcome"]] += 1
            if e.get("outcome") in R.FINISHED_STATUSES:
                c["rows"][R.sample_of(e["signal_ts"], cut)].append((e["outcome"], e["net_pct"]))
    base = {sd: [] for sd in R.SIDES}
    for sd in R.SIDES:
        rp = R._med(cells[sd]["risk"])
        for run, step, iv in runs_used:
            for side, rows in baseline(run, step, first, now, rp).items():
                base[side].extend(rows)
    rep = {"ready": True, "version": VERSION, "category": CATEGORY, "definition_version": DEF_VERSION, "definition": DEFINITION, "days": days, "symbols_used": used,
           "holdout_from_utc": None if cut is None else time.strftime("%Y-%m-%d %H:%M", time.gmtime(cut)), "sides": {},
           "notes": ["HYPOTHETICAL replay of saved candles, no order, nothing written; fees and slippage taken off; raw price %, not leveraged",
                     "LONG and SHORT are never added; TRAIN is older, HOLDOUT is the newest 30% of signal times",
                     "a retest matters only if it differs from the baseline AND n is large; under 30 finished = too few to say anything",
                     "all numbers in the rule (12 candles, 1.5 R, 24 candles, risk 0.05 to 2.0 %, 0.05 + 0.02 % costs) are starting values, not validated"]}
    for sd in R.SIDES:
        c = cells[sd]
        med = R._med(c["risk"])
        rep["sides"][sd] = {"crosses": sum(c["statuses"].values()), "statuses": c["statuses"], "traded_outcomes": c["outcomes"], "risk_pct_median": None if med is None else round(med, 3),
                            "risk_n": len(c["risk"]), "TRAIN": R.summarize(c["rows"]["TRAIN"]), "HOLDOUT": R.summarize(c["rows"]["HOLDOUT"]), "baseline": R.summarize(base[sd]),
                            "events": [e for e in events if e["side"] == sd][-MAX_EVENTS:]}
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--days", default="1")
    a = ap.parse_args(argv)
    path = S.store_path(a.data)
    if not os.path.isfile(path):
        print(json.dumps({"ready": False, "note": "the market store is not created yet"}))
        return 0
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    try:
        con.execute("PRAGMA query_only=ON")
        rep = build(con, None, a.days)
    finally:
        con.close()
    for sd in rep["sides"].values():
        sd["events"] = sd["events"][-3:]
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
