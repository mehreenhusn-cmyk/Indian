"""v2_f6b_entry.py - FILTER STUDY Part 6B: ENTRY LAB (read-only). Reuses the replay engine of Part 5A (v2_f5a_exits.py) and the loading of Part 5C, so those files must be in the repo.
Measures only. No rule, no setting, no order, no network. Writes nothing in the data folder except the summary file given by --out (the Part 8A runner passes it).
WHY (owner, 10 Nov 2026): the bot takes every signal and only 13.5% of trades win. Exit booking is already studied (5A / 5B / 5C). This Part studies the ENTRY side with three questions:
 1. LOOKBACK: the bot uses Z lookback 200 (copied from a video made for slow markets). On 5m crypto 200 candles = 16 h 40 min, so one pump stretches the mean and SD for the whole next day.
    Is a shorter or longer lookback better at telling a trend trade from a fake one?  Z lookback 50 / 100 / 200 / 300 are compared on the SAME trades.
 2. ENTRY TYPE: instead of entering at the real entry (A = market, as the bot does), place a LIMIT order after the signal candle:
      B3  = limit at the close of the signal candle, waits 3 candles
      C12 = limit at the EMA50 value of the signal candle (pullback to EMA50), waits 12 candles
      D3  = limit at the EMA50 value, waits only 3 candles
    If the limit is not touched in time the trade is SKIPPED. The exit is the real exit of that trade (CALIB, same as 5A / 5C), so only the entry price and the skip change.
    Risk the owner named: a rally that never comes back is missed. So skipped winners are counted in USDT.
 3. RALLY PHASE: how far had price already run before the signal? (a) run-up of the last 12 candles with the trade side, (b) distance from EMA50 with the trade side (near EMA = pullback, far = chase),
    (c) how many candles ago Z went beyond 3 in the trade direction (the video says a Z spike is followed by a pullback). Buckets are cut on TRAIN only (tertiles) and judged on TEST.
Time of day (hour / session) and top-10 side / rank are already in Part 2, they are not repeated here.
TRAIN = first 60% by time, TEST = last 40% (never random). Main and Sniper are never added together. Only paper trades. About 20 questions are asked, so some answers look good by luck: a result is a candidate for a log test, not a rule.
Honest limits: hindsight replay, limit fills are assumed at the level (no slippage, no queue), the real exit price is kept even though the entry price is different, the stop distance of the real trade is not changed.
Day = 00:00 UTC = 5:30 AM IST. Durations over 60 min are written as hours + minutes.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f6b_entry.py --data /home/owl/owl_data --out -"""
import argparse
import bisect
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f5a_exits as A

X, K, F, IP, E, I, P = A.X, A.K, A.F, A.IP, A.E, A.I, A.P

VERSION = "v2_f6b_entry 1 (Filter Part 6B)"
LOOKBACKS = (50, 100, 200, 300)
ENTRIES = (("B3 limit at signal close, wait 3", "c", 3), ("C12 limit at EMA50, wait 12", "ema", 12), ("D3 limit at EMA50, wait 3", "ema", 3))
RUN_BARS = 12
SPIKE_BARS = 48
MIN_BUCKET = 30


# ----------------------------------------------------------------------------- features of ONE trade at its signal candle
def z_at(c, i, n):
    """Z of the close at bar i over the last n closes (population SD). None if there is not enough history or no spread."""
    if i + 1 < n:
        return None
    w = c[i + 1 - n:i + 1]
    m = sum(w) / n
    sd = math.sqrt(max(sum(x * x for x in w) / n - m * m, 0.0))
    return None if sd <= 0 else (c[i] - m) / sd


def features(S, i0, side):
    """Numbers at the signal candle, all with the trade side (positive = in the trade direction)."""
    c = S["c"]
    f = {"zl": {}}
    for n in LOOKBACKS:
        z = z_at(c, i0, n)
        f["zl"][n] = None if z is None else z * side
    f["run"] = side * (c[i0] / c[i0 - RUN_BARS] - 1.0) * 100.0 if i0 >= RUN_BARS and c[i0 - RUN_BARS] else None
    ema = S["ema_s"][i0]
    f["dist"] = side * (c[i0] - ema) / ema * 100.0 if ema else None
    f["spike_ago"] = None
    for k in range(0, SPIKE_BARS + 1):
        z = S["z"][i0 - k] if i0 - k >= 0 else None
        if z is not None and z * side >= 3.0:
            f["spike_ago"] = k
            break
    return f


def entry_fill(S, i0, end0, side, kind, wait):
    """Limit order placed after the signal candle. A long buys when price comes DOWN to the level, a short sells when price goes UP to it.
    -> fill price, or None (not touched in time or trade already over)."""
    lvl = S["c"][i0] if kind == "c" else S["ema_s"][i0]
    if not lvl:
        return None
    for j in range(i0 + 1, min(i0 + wait, end0) + 1):
        px = A.hit_level(-side, S["o"][j], S["h"][j], S["l"][j], lvl)
        if px is not None:
            return px
    return None


def replay_trade(S, i0, end0, r):
    side, ep, lev, inv, fee = r.get("side"), r.get("entry_price"), r.get("lev"), r.get("invest"), r.get("fee_roi")
    if not (side and ep and lev and inv and fee is not None) or end0 <= i0:
        return None
    end0 = min(end0, i0 + 1 + A.MAX_BARS)
    cx = S["c"][end0]
    y = {"calib": round(A.money(side, ep, cx, lev, fee, inv), 4), "e": {}}
    for name, kind, wait in ENTRIES:
        px = entry_fill(S, i0, end0, side, kind, wait)
        y["e"][name] = None if px is None else round(A.money(side, px, cx, lev, fee, inv), 4)
    return y


def replay_all(rows, con, cfg_by_tf, cov):
    store, groups = X.Candles(con, cfg_by_tf), {}
    for r in rows:
        if r.get("ent") and not r.get("ent_from_close") and r.get("close") and r["tf"] in X.TFS and r.get("side") and r.get("sym"):
            groups.setdefault((r["sym"], r["tf"]), []).append(r)
        else:
            cov["no_entry_close_side_tf"] += 1
    for (sym, tf), rs in groups.items():
        runs, step = store.load(sym, tf, min(x["ent"] for x in rs), max(x["close"] for x in rs))
        for r in rs:
            sig_t = int((r["ent"] - step) // step * step)
            hit = next(((S, idx) for S, _a, idx in runs if sig_t in idx), None)
            if hit is None:
                cov["no_candles"] += 1
                continue
            S, idx = hit
            i0 = idx[sig_t]
            if i0 < E.warmup_end(S):
                cov["warmup"] += 1
                continue
            end0 = bisect.bisect_right(S["t"], r["close"]) - 1
            y = replay_trade(S, i0, end0, r)
            if y is None:
                cov["no_money_numbers"] += 1
                continue
            r["y"], r["f"] = y, features(S, i0, r["side"])
            cov["replayed"] += 1


# ----------------------------------------------------------------------------- report
def half(rs):
    """Plain result of the REAL trades in a list: trades, win %, net USDT."""
    n = len(rs)
    w = sum(1 for r in rs if r["net"] > 0)
    return {"trades": n, "win_pct": round(100.0 * w / n, 1) if n else None, "net_usdt": round(sum(r["net"] for r in rs), 2)}


def bucket_table(tr, te, fn, order):
    """Real results per bucket in TRAIN and TEST. FLAG = LOSER / WINNER when the net has the same sign in both halves and both have MIN_BUCKET trades."""
    out = {}
    for b in order:
        a, c = half([r for r in tr if fn(r) == b]), half([r for r in te if fn(r) == b])
        flag = "TOO_FEW"
        if a["trades"] >= MIN_BUCKET and c["trades"] >= MIN_BUCKET:
            flag = "LOSER" if a["net_usdt"] < 0 and c["net_usdt"] < 0 else ("WINNER" if a["net_usdt"] > 0 and c["net_usdt"] > 0 else "MIXED")
        out[b] = {"train": a, "test": c, "flag": flag}
    return out


def tertile_cuts(vals):
    v = sorted(x for x in vals if x is not None)
    return (v[len(v) // 3], v[2 * len(v) // 3]) if len(v) >= 30 else (None, None)


def tert(cuts, key):
    lo, hi = cuts

    def fn(r):
        v = r["f"][key]
        return "n/a" if v is None or lo is None else ("LOW" if v < lo else ("MID" if v < hi else "HIGH"))
    return fn


def lookback_block(tr, te):
    """Per lookback: trades with Z in the trade direction OUTSIDE the green zone (>= 1) vs INSIDE (-1 .. 1) vs AGAINST (<= -1)."""
    out = {}
    for n in LOOKBACKS:
        def fn(r, n=n):
            z = r["f"]["zl"][n]
            return "n/a" if z is None else ("WITH_TREND z>=1" if z >= 1.0 else ("AGAINST z<=-1" if z <= -1.0 else "INSIDE_GREEN"))
        out["Z lookback %d" % n] = bucket_table(tr, te, fn, ("WITH_TREND z>=1", "INSIDE_GREEN", "AGAINST z<=-1", "n/a"))
    return out


def spike_fn(r):
    k = r["f"]["spike_ago"]
    return "no spike in %d candles" % SPIKE_BARS if k is None else ("spike 0-6 candles ago" if k <= 6 else "spike 7-24 candles ago" if k <= 24 else "spike 25-48 candles ago")


def entry_block(rs, tr, te):
    """Every entry type vs the real entry (CALIB) on the same trades: change in USDT (TRAIN / TEST), fills, skipped winners and skipped losers."""
    mfes = sorted(r["mfe"] for r in rs if r.get("mfe") is not None)
    rcut = mfes[int(len(mfes) * 0.75)] if mfes else float("inf")
    out = {"calib_net_usdt": round(sum(r["y"]["calib"] for r in rs), 3), "runner_definition": "best ROI at or above %.2f%% (top quarter of this scope)" % rcut}
    for name, _k, _w in ENTRIES:
        def chg(lst):
            tot, n = 0.0, 0
            for r in lst:
                v = r["y"]["e"][name]
                d = (0.0 if v is None else v) - r["y"]["calib"]
                tot += d
                n += 1 if abs(d) > 1e-9 else 0
            return round(tot, 3), n
        a, b = chg(tr), chg(te)
        ru = (chg([r for r in tr if r.get("mfe") is not None and r["mfe"] >= rcut])[0], chg([r for r in te if r.get("mfe") is not None and r["mfe"] >= rcut])[0])
        skipped = [r for r in rs if r["y"]["e"][name] is None]
        sw = [r for r in skipped if r["y"]["calib"] > 0]
        sl = [r for r in skipped if r["y"]["calib"] <= 0]
        if a[1] < A.MIN_CHANGED or b[1] < A.MIN_CHANGED:
            verdict = "TOO_FEW"
        elif a[0] > 0 and b[0] > 0:
            verdict = "BETTER" if ru[0] >= 0 and ru[1] >= 0 else "TRADEOFF"
        else:
            verdict = "UNSTABLE" if (a[0] > 0 or b[0] > 0) else "WORSE"
        out[name] = {"verdict": verdict, "net_usdt": round(out["calib_net_usdt"] + a[0] + b[0], 3), "change_train": a[0], "change_test": b[0], "changed_train_test": [a[1], b[1]],
                     "runners_change_train_test": list(ru), "filled_pct": round(100.0 * (len(rs) - len(skipped)) / len(rs), 1),
                     "skipped_winners": {"n": len(sw), "usdt_lost": round(sum(r["y"]["calib"] for r in sw), 2)},
                     "skipped_losers": {"n": len(sl), "usdt_saved": round(-sum(r["y"]["calib"] for r in sl), 2)}}
    return out


def scope_report(rs):
    if len(rs) < A.MIN_SCOPE:
        return {"label": "NOT ENOUGH DATA", "replayed_trades": len(rs), "need": A.MIN_SCOPE}
    tr, te, cut = A.split_rows(rs)
    run_cuts, dist_cuts = tertile_cuts([r["f"]["run"] for r in tr]), tertile_cuts([r["f"]["dist"] for r in tr])
    order = ("LOW", "MID", "HIGH", "n/a")
    return {"replayed_trades": len(rs), "split_utc": P.fmt_ts(cut),
            "entry_types": entry_block(rs, tr, te),
            "lookback": lookback_block(tr, te),
            "rally_phase": {
                "run_up_last_%d_candles_pct (with trade side)" % RUN_BARS: {"cuts_from_train": list(run_cuts), "buckets": bucket_table(tr, te, tert(run_cuts, "run"), order)},
                "distance_from_EMA50_pct (with trade side, LOW = near EMA = pullback, HIGH = far = chase)": {"cuts_from_train": list(dist_cuts), "buckets": bucket_table(tr, te, tert(dist_cuts, "dist"), order)},
                "z_spike_beyond_3_in_trade_direction": bucket_table(tr, te, spike_fn, ("spike 0-6 candles ago", "spike 7-24 candles ago", "spike 25-48 candles ago", "no spike in %d candles" % SPIKE_BARS))},
            "how_to_read": "entry_types: change_* = USDT gained or lost vs the real entry (CALIB) on the same trades. Tables: real results per bucket, FLAG LOSER / WINNER only when TRAIN and TEST agree."}


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST", "min_changed_trades_per_half": A.MIN_CHANGED, "min_trades_per_bucket_half": MIN_BUCKET,
           "lookbacks": list(LOOKBACKS), "entry_types": [e[0] for e in ENTRIES]}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    src = K.load_rows(root)
    if not src or not src.get("rows"):
        X.build_report(root, fee_roi)
        rep["note_rows"] = "v2_filter_trades.json was missing: Part 1 was run first."
        src = K.load_rows(root)
    rows, dropped = K.prepare((src or {}).get("rows") or [])
    cov = {"replayed": 0, "no_candles": 0, "warmup": 0, "no_entry_close_side_tf": 0, "no_money_numbers": 0, "candles_used": False}
    con = F.open_ro(root)
    if con is None:
        rep["error"] = "No candle store (v2_market.db): the entry lab needs candles."
        rep["coverage"] = cov
        return rep
    cov["candles_used"] = True
    cfg_by_tf = {}
    for tf in X.TFS:
        try:
            cfg_by_tf[tf] = IP.load_cfg(root, "15m" if tf == "15m" else "5m")[0]
        except Exception:
            cfg_by_tf[tf] = dict(E.DEFAULTS)
    try:
        replay_all(rows, con, cfg_by_tf, cov)
    finally:
        con.close()
    rep["rows_used"], rep["rows_without_net_result"], rep["coverage"] = len(rows), dropped, cov
    done = [r for r in rows if r.get("y")]
    for g in X.GROUPS:
        grs = [r for r in done if r["g"] == g]
        rep[g] = {nm: scope_report([r for r in grs if tf is None or r["tf"] == tf]) for nm, tf in A.SCOPES}
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades.",
                    "Entry types keep the real exit price of the trade. A limit that is never touched = trade skipped (0 USDT). Replay is hindsight, fills are assumed at the level.",
                    "Lookback tables use the real result of each trade, grouped by where Z (that lookback) stood at the signal candle. Engine Z is computed here from closes, population SD.",
                    "Only a BETTER entry type in BOTH halves, or a LOSER / WINNER flag that holds in both halves, is worth a log test. Everything else is a question, not a rule."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 6B: entry lab (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out", default="-")
    ap.add_argument("--fee-roi", type=float, default=1.0)
    a = ap.parse_args(argv)
    txt = json.dumps(build_report(I.find_data_dir(a.data), a.fee_roi), indent=1, ensure_ascii=False, default=str)
    if a.out == "-":
        print(txt)
    else:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(txt)
        sys.stderr.write("Written: %s\n" % a.out)
    sys.stderr.write("Nothing was changed in trading. Send the summary file to Claude.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
