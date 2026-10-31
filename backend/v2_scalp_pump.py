"""v2_scalp_pump.py - Part 53: SCALP LAB 4 of 8 (backend, read-only, HYPOTHETICAL replay). Category PUMP_DUMP: "after a fast PUMP (up) or DUMP (down) on the saved candles, what would a quick trade WITH the move (FOLLOW) or AGAINST it (FADE) have done?"
The rule is written down BEFORE any test (README4 9.7) with its own definition + version. Starting values are marked NV = not validated, they sit in the constants. This works on the saved 3m / 5m candles ONLY (no top-20 list, no cohort), so every event can be replayed.
THE RULE (candle-close execution, nothing looks ahead):
  IMPULSE = on a closed candle the close is at least MOVE_PCT % above (PUMP) / below (DUMP) the close IMPULSE_CANDLES candles earlier, the candle itself closes in that direction,
            and its volume is at least VOL_X x the median volume of the 50 candles before it (no volume history = no event, nothing guessed).
  EPISODE = after a signal the same kind of signal is ignored for COOLDOWN candles of that coin (one pump is one event, not twelve).
  FOLLOW  = PUMP -> LONG, DUMP -> SHORT (version 1).   FADE = PUMP -> SHORT, DUMP -> LONG (version 2).   The two are different hypotheses with their OWN definition and ledger, never added together.
  ENTRY   = close of the signal candle. RISK = RISK_FRAC x the impulse size (in % of the entry); STOP = entry -/+ that risk, TARGET = entry +/- R_MULT x risk, EXIT = target, stop or MAX_HOLD candles
            (v2_replay.simulate: stop and target in one candle = STOP). Risk outside MIN_RISK_PCT..MAX_RISK_PCT = SKIPPED_RISK (counted, never forced).
Each signal ends in ONE status per mode: TRADED (outcome TARGET / STOP / TIME / PENDING / UNAVAILABLE), SKIPPED_RISK. Nothing is counted as 0 or bridged over a candle gap.
PUMP and DUMP (= the LONG / SHORT side inside one version) are always reported apart. Older = TRAIN, newest 30% of signal times = HOLDOUT. A BASELINE of ordinary candles (every 12th, same risk %, same R) is shown beside it.
Under 30 finished = "too few to say anything". Fees + slippage taken off (v2_replay). No win rate, no prediction, no order, nothing is written (the runner of Part 54 saves records). The TSI / Z words at the signal candle are CONTEXT only, never a filter.
Run (Termux):  python3 backend/v2_scalp_pump.py [--data DIR] [--days N]     Route: GET /api/v2/scalp_pump[?days=N] (api/v2_data.py), N = 1 to 7 (default 1)."""
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

VERSION = "v2_scalp_pump 1 (Part 53)"
CATEGORY = "PUMP_DUMP"
MODES = {"FOLLOW": 1, "FADE": 2}          # mode -> definition version (own ledger each)
IMPULSE_CANDLES = 6                      # the move is measured over 6 closed candles (NV)
MOVE_PCT = 3.0                           # at least 3 % close to close (NV)
VOL_X = 3.0                              # volume at least 3 x the median of the 50 candles before (NV)
VOL_LOOK = 50
COOLDOWN = 12                            # candles of one coin and one kind ignored after a signal (NV)
RISK_FRAC = 0.4                          # risk = 40 % of the impulse size (NV)
R_MULT = 1.5
MAX_HOLD = 24                            # candles (NV)
MIN_RISK_PCT = 0.2
MAX_RISK_PCT = 4.0
WARMUP_SECS = 6 * 3600
BASE_EVERY = 12
MAX_EVENTS = 200
KIND_SIDE = {"FOLLOW": {"PUMP": "LONG", "DUMP": "SHORT"}, "FADE": {"PUMP": "SHORT", "DUMP": "LONG"}}


def definition(mode):
    s = KIND_SIDE[mode]
    return {"entry": "close of a candle that closed %.1f %% or more away from the close %d candles earlier (up = PUMP, down = DUMP) with volume >= %.1f x the 50-candle median; PUMP -> %s, DUMP -> %s" % (MOVE_PCT, IMPULSE_CANDLES, VOL_X, s["PUMP"], s["DUMP"]),
            "invalidation": "no volume history = no event; the same kind of signal of one coin is ignored for %d candles; risk outside %.1f to %.1f %% = skipped" % (COOLDOWN, MIN_RISK_PCT, MAX_RISK_PCT),
            "stop": "%.0f %% of the impulse size away from the entry (adverse side)" % (RISK_FRAC * 100),
            "exit": "target = entry +/- %.1f x risk; stop; or time exit; stop first when both are in one candle" % R_MULT,
            "max_hold": "%d candles" % MAX_HOLD, "fees": "%.2f%% per side (v2_replay)" % R.FEE_PCT, "slippage": "%.2f%% per side (v2_replay)" % R.SLIP_PCT,
            "window": "closed 3m / 5m candles of one gap-free run, execution at candle close", "mode": mode}


def _prices(entry, side, risk):
    sg = 1 if side == "LONG" else -1
    return entry * (1 - sg * risk / 100.0), entry * (1 + sg * R_MULT * risk / 100.0)


def scan_run(run, step, first, now, sym, iv):
    """All impulses of ONE gap-free run whose signal candle is at or after `first`. -> list of event dicts (one per signal, with a trade result for each mode)."""
    out, last = [], {"PUMP": -10 ** 9, "DUMP": -10 ** 9}
    ind = None
    for k in range(IMPULSE_CANDLES, len(run)):
        if run[k][0] < first:
            continue
        c0, c1 = run[k - IMPULSE_CANDLES][4], run[k][4]
        move = (c1 - c0) / c0 * 100.0
        kind = "PUMP" if move >= MOVE_PCT and c1 > run[k][1] else "DUMP" if move <= -MOVE_PCT and c1 < run[k][1] else None
        if kind is None or k - last[kind] < COOLDOWN or k < VOL_LOOK:
            continue
        med = R._med([x[5] for x in run[k - VOL_LOOK:k]])
        if not med or run[k][5] < VOL_X * med:
            continue
        last[kind] = k
        ind = ind or I.compute(run)
        s = I.state(ind, k)
        risk = abs(move) * RISK_FRAC
        ev = {"symbol": sym, "interval": iv, "kind": kind, "signal_ts": run[k][0], "signal_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(run[k][0])), "entry": c1,
              "move_pct": round(move, 3), "vol_x": round(run[k][5] / med, 2), "risk_pct": round(risk, 3),
              "context": {"tsi_vs_signal": s["tsi_vs_signal"], "z_vs_sma": s["z_vs_sma"], "band_zone": s["band_zone"], "price_vs_ema": s["price_vs_ema"]}, "modes": {}}
        for mode in MODES:
            side = KIND_SIDE[mode][kind]
            if not MIN_RISK_PCT <= risk <= MAX_RISK_PCT:
                ev["modes"][mode] = {"side": side, "status": "SKIPPED_RISK"}
                continue
            stop, target = _prices(c1, side, risk)
            r = R.simulate(run, k, side, stop, target, MAX_HOLD, step, now)
            m = {"side": side, "status": "TRADED", "outcome": r["status"], "stop": stop, "target": target}
            if r["status"] in R.FINISHED_STATUSES:
                m.update(exit_price=r["exit_price"], hold_candles=r["hold_candles"], gross_pct=round(r["gross_pct"], 4), net_pct=round(r["net_pct"], 4), same_candle=r["same_candle"])
            ev["modes"][mode] = m
        out.append(ev)
    return out


def baseline(run, step, first, now, risk_pct):
    """Ordinary candles: every BASE_EVERY-th candle, both sides, the SAME risk % and R. -> {side: [(status, net_pct)]} finished only."""
    res = {"LONG": [], "SHORT": []}
    if not risk_pct:
        return res
    for i in range(VOL_LOOK, len(run), BASE_EVERY):
        if run[i][0] < first:
            continue
        for side in R.SIDES:
            stop, target = _prices(run[i][4], side, risk_pct)
            r = R.simulate(run, i, side, stop, target, MAX_HOLD, step, now)
            if r["status"] in R.FINISHED_STATUSES:
                res[side].append((r["status"], r["net_pct"]))
    return res


def records(events, cut, mode):
    """The finished TRADED results of ONE mode as dicts for v2_scalp_store.add_record (the runner of Part 54 calls it, with version MODES[mode]). Nothing is saved here."""
    out = []
    for e in events:
        m = e["modes"][mode]
        if m.get("outcome") in R.FINISHED_STATUSES:
            out.append(dict(symbol=e["symbol"], interval=e["interval"], side=m["side"], signal_ts=e["signal_ts"], sample=R.sample_of(e["signal_ts"], cut), entry=e["entry"],
                            exit_price=m["exit_price"], status=m["outcome"], hold_candles=m["hold_candles"], gross_pct=m["gross_pct"], net_pct=m["net_pct"]))
    return out


def build(con, now=None, days=None):
    """-> the report dict (read-only). days = 1 to 7 (default 1) = how far back the signals are taken. Raises ValueError on a bad days value."""
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
            events.extend(scan_run(run, D.STEP[iv], first, now, s, iv))
            runs_used.append((run, D.STEP[iv]))
    done = [e["signal_ts"] for e in events if any(m.get("outcome") in R.FINISHED_STATUSES for m in e["modes"].values())]
    cut = R.holdout_cut(done)
    rep = {"ready": True, "version": VERSION, "category": CATEGORY, "days": days, "symbols_used": used, "signals": len(events), "holdout_from_utc": None if cut is None else time.strftime("%Y-%m-%d %H:%M", time.gmtime(cut)),
           "kinds": {k: sum(1 for e in events if e["kind"] == k) for k in ("PUMP", "DUMP")}, "modes": {},
           "notes": ["HYPOTHETICAL replay of saved candles, no order, nothing written; fees and slippage taken off; raw price %, not leveraged",
                     "FOLLOW (with the move) and FADE (against it) are two separate hypotheses with their own definition and ledger; PUMP and DUMP (LONG / SHORT inside a mode) are never added",
                     "the move only matters if it differs from the baseline AND n is large; under 30 finished = too few to say anything",
                     "all numbers (3 % over 6 candles, volume 3 x, risk 40 % of the impulse, 1.5 R, 24 candles, cooldown 12, costs 0.05 + 0.02 %) are starting values, not validated"]}
    for mode in MODES:
        sides = {}
        for sd in R.SIDES:
            kind = "PUMP" if KIND_SIDE[mode]["PUMP"] == sd else "DUMP"
            ms = [(e, e["modes"][mode]) for e in events if e["modes"][mode]["side"] == sd]
            rows = {"TRAIN": [], "HOLDOUT": []}
            outc = {"TARGET": 0, "STOP": 0, "TIME": 0, "PENDING": 0, "UNAVAILABLE": 0}
            for e, m in ms:
                if m["status"] == "TRADED":
                    outc[m["outcome"]] += 1
                    if m["outcome"] in R.FINISHED_STATUSES:
                        rows[R.sample_of(e["signal_ts"], cut)].append((m["outcome"], m["net_pct"]))
            rp = R._med([e["risk_pct"] for e, m in ms])
            base = []
            for run, step in runs_used:
                base.extend(baseline(run, step, first, now, rp).get(sd, []))
            sides[sd] = {"kind": kind, "signals": len(ms), "skipped_risk": sum(1 for e, m in ms if m["status"] == "SKIPPED_RISK"), "traded_outcomes": outc,
                         "risk_pct_median": None if rp is None else round(rp, 3), "TRAIN": R.summarize(rows["TRAIN"]), "HOLDOUT": R.summarize(rows["HOLDOUT"]), "baseline": R.summarize(base),
                         "events": [dict({k: v for k, v in e.items() if k != "modes"}, **m) for e, m in ms][-MAX_EVENTS:]}
        rep["modes"][mode] = {"definition_version": MODES[mode], "definition": definition(mode), "sides": sides}
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
    for m in rep["modes"].values():
        for sd in m["sides"].values():
            sd["events"] = sd["events"][-3:]
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
