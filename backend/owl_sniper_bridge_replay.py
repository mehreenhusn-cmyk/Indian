"""owl_sniper_bridge_replay.py - OwlSniper LEARN BRIDGE, step 2 of 3 (Part 7 / FILE 10). READ ONLY: the market store is opened read-only, nothing is written, no network, no order code.
Step 1 (owl_sniper_bridge_src.py) gives one flat record per closed trade of Dual / Brain / main bot. This step goes back to the saved candles of that coin and asks:
"What did the Sniper's own indicators say on the candle where this trade was entered?" The answer is one FEATURE ROW per trade. Step 3 (FILE 11) then adds the labels (win / loss, R, MAE, MFE).
How a row is made:
  1. The signal candle = the LAST candle that was already CLOSED at entry_ts (open_ts + step <= entry_ts). Dual / Brain enter exactly at that close (lag 0). The main bot may open a little later: up to 1 candle of lag is accepted, more = skipped.
  2. The indicators are built with the SAME code and the SAME settings as the live scan (owl_sniper_engine.build_features, config from v2_sniper_model.json; defaults when that file is missing).
  3. NO LOOK-AHEAD, by construction: the candle list is cut right after the signal candle before anything is computed, so a later candle cannot reach the row. The labels of step 3 are the only place that looks forward.
  4. 15m = complete quarter-hour buckets of real 5m candles (owl_sniper_tf.py), gaps are never bridged (every run is gap-free).
A row: uid, source, symbol, tf, side (the TRADE's side), entry_ts, candle_open_ts, entry_lag_s, regime, feat {z, hist, gap_pct, vi_ratio, dir} = EXACTLY the 4 numbers + direction the Sniper's win-chance model learns from,
  extra {tsi, cloud_dir, sd_pct, dist_sma_pct, stop_line_pct, ret_1, ret_3, ret_12, range_pct, body_pct, vol_ratio, sniper_side, sniper_agrees}  (sniper_agrees = the Sniper's own raw rule would have given the same side on that candle).
Rows that cannot be made are SKIPPED and counted by reason: tf_unknown, tf_not_supported, no_store, no_candles, before_candles (older than the saved candles), candle_gap, warmup, bad_candles. Nothing is guessed.
Run (Termux, optional):  python3 backend/owl_sniper_bridge_replay.py [--data DIR] [--since-days N] [--limit N] [--sources dual,brain,main] [--sample N]  -> JSON summary."""
import argparse
import bisect
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_bridge_src as B
import owl_sniper_engine as E
import owl_sniper_feed as F
import owl_sniper_tf as TF
import v2_defs as D
import v2_setup_finder as SF

VERSION = "owl_sniper_bridge_replay 1 (Part 7)"
WARM = 400                # candles read before the first needed entry (SD 200 + regime 50 + indicator warm-up, with spare)
MAX_LAG_STEPS = 1.0       # an entry may be at most this many candles after the close of its signal candle
VOL_WIN = 20


def load_cfg(d, tf):
    """The settings the live Sniper uses (v2_sniper_model.json -> model.config). -> (cfg, 'model' | 'defaults')."""
    try:
        m = F.read_json(d, TF.files(tf)[0]) or {}
        c = (m.get("model") or {}).get("config")
    except Exception:
        c = None
    return (dict(E.DEFAULTS, **c), "model") if isinstance(c, dict) else (dict(E.DEFAULTS), "defaults")


def _pct(a, b):
    return None if not b else round((a / b - 1.0) * 100.0, 4)


def make_row(rec, S, vols, i, lag):
    """The feature row of ONE trade at signal candle i of series S (S holds no candle after i that this row reads). None = not ready (warm-up)."""
    if i < E.warmup_end(S) or i < 1:
        return None
    side = rec["side"]
    d = 1 if side == "LONG" else -1
    c, vi, via = S["c"][i], S["vi"][i], S["vi_avg"][i]
    sig = E.raw_signal(S, i)
    sl = E.stop_price(S, i, side)
    prev = vols[max(0, i - VOL_WIN):i]
    avg_v = sum(prev) / len(prev) if prev else 0.0
    feat = {"z": S["z"][i], "hist": S["hist"][i], "gap_pct": S["gap_pct"][i], "vi_ratio": vi / via if via else None, "dir": d}
    if any(v is None for v in feat.values()):
        return None
    extra = {"tsi": S["tsi"][i], "cloud_dir": (S["cloud"][i] or 0) * d, "sd_pct": round(S["sd"][i] / c * 100.0, 4), "dist_sma_pct": round((c - S["sma"][i]) / c * 100.0, 4),
             "stop_line_pct": None if sl is None else round(((c - sl) if d > 0 else (sl - c)) / c * 100.0, 4),
             "ret_1": _pct(c, S["c"][i - 1]), "ret_3": _pct(c, S["c"][i - 3]) if i >= 3 else None, "ret_12": _pct(c, S["c"][i - 12]) if i >= 12 else None,
             "range_pct": round((S["h"][i] - S["l"][i]) / c * 100.0, 4), "body_pct": _pct(c, S["o"][i]),
             "vol_ratio": round(vols[i] / avg_v, 4) if avg_v > 0 else None, "sniper_side": sig["side"], "sniper_agrees": sig["side"] == side}
    return {"uid": rec["uid"], "source": rec["source"], "symbol": rec["symbol"], "tf": rec["tf"], "side": side, "entry_ts": rec["entry_ts"],
            "candle_open_ts": S["t"][i], "entry_lag_s": round(lag, 3), "regime": E.regime_at(S, i), "feat": feat, "extra": extra}


def _group(con, sym, tf, recs, cfg, max_lag, bump):
    """All records of ONE coin + interval: read its candles once, find every signal candle, build the features once per gap-free run (cut after the last needed candle)."""
    step = TF.step(tf)
    t_lo, t_hi = min(r["entry_ts"] for r in recs), max(r["entry_ts"] for r in recs)
    raw = D.candles_from_store(con, sym, TF.base(tf), t_lo - (WARM + 2) * step, t_hi)
    good, _bad = D.clean_candles(raw, TF.base(tf))
    runs = [x for x in (TF.aggregate(r, tf) for r in SF.runs(good, TF.base(tf))) if x]
    if not runs:
        for r in recs:
            bump(r, "no_candles")
        return []
    starts, stamps, need = [x[0][0] for x in runs], [[c[0] for c in x] for x in runs], {}
    for r in recs:
        k = bisect.bisect_right(starts, r["entry_ts"] - step) - 1
        if k < 0:
            bump(r, "before_candles")
            continue
        i = bisect.bisect_right(stamps[k], r["entry_ts"] - step) - 1
        lag = r["entry_ts"] - (stamps[k][i] + step)
        if lag < -1e-6 or lag > max_lag * step + 1e-6:
            bump(r, "candle_gap")
            continue
        need.setdefault(k, []).append((r, i, max(0.0, lag)))
    rows = []
    for k, items in need.items():
        cut = max(i for _r, i, _l in items) + 1
        try:
            S = E.build_features(runs[k][:cut], cfg)                  # nothing after the last needed signal candle is even read
        except (ValueError, KeyError, IndexError, TypeError):
            for r, _i, _l in items:
                bump(r, "bad_candles")
            continue
        vols = [c[5] for c in runs[k][:cut]]
        for r, i, lag in items:
            row = make_row(r, S, vols, i, lag)
            if row is None:
                bump(r, "warmup")
            else:
                rows.append(row)
    return rows


def replay(d, records, max_lag_steps=MAX_LAG_STEPS):
    """Bridge records -> {rows (oldest first), skipped {reason: n}, by_source {name: {records, rows, skipped}}, cfg_source}. Never raises."""
    by = {}
    out = {"version": VERSION, "rows": [], "skipped": {}, "by_source": by, "cfg_source": {}}

    def bump(r, why):
        b = by.setdefault(r["source"], {"records": 0, "rows": 0, "skipped": {}})
        b["skipped"][why] = b["skipped"].get(why, 0) + 1
        out["skipped"][why] = out["skipped"].get(why, 0) + 1

    groups = {}
    for r in records:
        by.setdefault(r["source"], {"records": 0, "rows": 0, "skipped": {}})["records"] += 1
        if not r.get("tf"):
            bump(r, "tf_unknown")
        elif r["tf"] not in TF.SUPPORTED:
            bump(r, "tf_not_supported")
        else:
            groups.setdefault((r["symbol"], r["tf"]), []).append(r)
    con = None
    try:
        con = F.open_ro(d) if groups else None
        for (sym, tf), recs in groups.items():
            if con is None:
                for r in recs:
                    bump(r, "no_store")
                continue
            if tf not in out["cfg_source"]:
                cfg, src = load_cfg(d, tf)
                out["cfg_source"][tf] = (cfg, src)
            try:
                out["rows"].extend(_group(con, sym, tf, recs, out["cfg_source"][tf][0], max_lag_steps, bump))
            except Exception:                                       # one bad coin never stops the others
                for r in recs:
                    bump(r, "bad_candles")
    finally:
        if con is not None:
            con.close()
    out["cfg_source"] = {tf: src for tf, (_c, src) in out["cfg_source"].items()}
    out["rows"].sort(key=lambda x: x["entry_ts"])
    for x in out["rows"]:
        by[x["source"]]["rows"] += 1
    return out


def summary(res):
    """Small printable view. Sources stay apart (different bots, different size and leverage)."""
    n_in = sum(b["records"] for b in res["by_source"].values())
    return {"version": res["version"], "records_in": n_in, "rows": len(res["rows"]), "skipped": res["skipped"], "by_source": res["by_source"], "cfg_source": res["cfg_source"],
            "agree": {s: [sum(1 for x in res["rows"] if x["source"] == s and x["extra"]["sniper_agrees"]), sum(1 for x in res["rows"] if x["source"] == s)] for s in res["by_source"]},
            "note": "READ ONLY. agree = [rows where the Sniper's own raw rule gave the same side, rows]. Labels (win / loss, R, MAE, MFE) come in step 3."}


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper bridge step 2: candle replay at each entry time -> feature rows (read only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or ".")
    ap.add_argument("--since-days", type=float, default=None)
    ap.add_argument("--limit", type=int, default=0, help="only the newest N records (keeps the phone light)")
    ap.add_argument("--sources", default=",".join(B.SOURCES))
    ap.add_argument("--sample", type=int, default=0)
    a = ap.parse_args(argv)
    srcs = tuple(s for s in a.sources.split(",") if s in B.SOURCES)
    got = B.collect(a.data, srcs, time.time() - a.since_days * 86400 if a.since_days else None)
    recs = got["records"][-a.limit:] if a.limit > 0 else got["records"]
    res = replay(a.data, recs)
    out = summary(res)
    if a.sample > 0:
        out["sample"] = res["rows"][-a.sample:]
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
