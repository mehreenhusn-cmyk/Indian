"""v2_f7c_winners.py - FILTER STUDY Part 7C (bot Part 7): WHAT DID THE WINNING TRADES LOOK LIKE? (read-only).
Reuses Part 5A (v2_f5a_exits.py) and Part 6B (v2_f6b_entry.py): both must be in the repo. Measures only. No rule, no setting, no order, no network.
For every old paper trade the state at the signal candle is written as numbers (no chart photos needed):
  z100 / z200  Z of the close, lookback 100 / 200, with the trade side (positive = in the trade direction)
  run          run-up of the last 12 candles with the trade side (%)
  dist         distance from EMA50 with the trade side (%), near 0 = pullback, high = chase
  slope        EMA50 slope over the last 6 candles with the trade side (%)
  width        band width = SD / mean of the last 100 closes (%), small = squeezed / sideways
  cross        how many times price crossed the middle line recently (the bot's own chop number, row field regime_cross_n)
  spike        Z beyond 3 in the trade direction: 0-6 / 7-24 / 25-48 candles ago, or none (Part 6B)
  side, session (IST sessions), tf
Numbers are cut in thirds (LOW / MID / HIGH) on TRAIN only. TRAIN = first 60% by time, TEST = last 40%. Main and Sniper are never added together.
Output per scope:
  winner_profile   median state of WINNERS (net > 0), RUNNERS (best ROI in the top quarter) and LOSERS
  single           real result per bucket of every state, flag LOSER / WINNER only if TRAIN and TEST agree (>= 30 trades each)
  block_candidates pairs of buckets that LOST money in BOTH halves: money saved, and winners / runners that would have been blocked too
  take_candidates  pairs of buckets that WON money in BOTH halves
HONEST LIMIT: many pairs are tried (the count is written in the report), so some look good by luck. A candidate is only a candidate for a LOG test (bot Part 8), never a rule.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f7c_winners.py --data /home/owl/owl_data --out -
Day = 00:00 UTC = 5:30 AM IST."""
import argparse
import itertools
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f5a_exits as A
import v2_f6b_entry as B

X, K, F, IP, E, I, P = A.X, A.K, A.F, A.IP, A.E, A.I, A.P

VERSION = "v2_f7c_winners 1 (Filter Part 7C)"
NUM = ("z100", "z200", "run", "dist", "slope", "width", "cross")
CAT = ("side", "session", "tf", "spike")
MIN_N = 30
TOP = 10


def state(S, i0, side, r):
    """State numbers of one trade at its signal candle."""
    f = B.features(S, i0, side)
    c, ema = S["c"], S["ema_s"][i0]
    s = {"z100": f["zl"][100], "z200": f["zl"][200], "run": f["run"], "dist": f["dist"], "spike_ago": f["spike_ago"]}
    s["slope"] = side * (ema - S["ema_s"][i0 - 6]) / ema * 100.0 if ema and i0 >= 6 and S["ema_s"][i0 - 6] else None
    w = c[i0 - 99:i0 + 1] if i0 >= 99 else None
    m = sum(w) / 100.0 if w else None
    s["width"] = math.sqrt(max(sum(x * x for x in w) / 100.0 - m * m, 0.0)) / m * 100.0 if w and m else None
    s["cross"] = r.get("regime_cross_n")
    return s


def replay_all(rows, con, cfg_by_tf, cov):
    import bisect
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
            r["st"] = state(S, i0, r["side"], r)
            cov["replayed"] += 1


def labels(r, cuts):
    """Bucket label of every state for one trade (None = not known)."""
    st, out = r["st"], {}
    for n in NUM:
        v, (lo, hi) = st.get(n), cuts[n]
        out[n] = None if v is None or lo is None else ("LOW" if v < lo else ("MID" if v < hi else "HIGH"))
    out["side"], out["session"], out["tf"] = r.get("side_b"), r.get("session"), r.get("tf")
    k = st.get("spike_ago")
    out["spike"] = "none48" if k is None else ("0-6" if k <= 6 else "7-24" if k <= 24 else "25-48")
    return {a: b for a, b in out.items() if b}


def med(v):
    v = sorted(x for x in v if x is not None)
    return round(v[len(v) // 2], 3) if v else None


def profile(rs, rcut):
    grp = {"WINNERS": [r for r in rs if r["net"] > 0], "RUNNERS": [r for r in rs if r.get("mfe") is not None and r["mfe"] >= rcut], "LOSERS": [r for r in rs if r["net"] <= 0]}
    return {g: dict({"trades": len(l)}, **{n: med([r["st"].get(n) for r in l]) for n in NUM}) for g, l in grp.items()}


def pair_search(tr, te, cuts, rcut):
    """All pairs of (state = bucket). Stats per half: n, net, winners n and usdt, runners n."""
    acc = {}
    for half, lst in ((0, tr), (1, te)):
        for r in lst:
            lb = labels(r, cuts)
            r_win, r_run = r["net"] > 0, r.get("mfe") is not None and r["mfe"] >= rcut
            for (fa, fb) in itertools.combinations(sorted(lb), 2):
                a = acc.setdefault(((fa, lb[fa]), (fb, lb[fb])), [[0, 0.0, 0, 0.0, 0], [0, 0.0, 0, 0.0, 0]])[half]
                a[0] += 1
                a[1] += r["net"]
                if r_win:
                    a[2] += 1
                    a[3] += r["net"]
                if r_run:
                    a[4] += 1
    return acc


def pack(key, v):
    (tr, te) = v
    return {"when": "%s=%s AND %s=%s" % (key[0][0], key[0][1], key[1][0], key[1][1]), "trades_train_test": [tr[0], te[0]],
            "net_train_test": [round(tr[1], 1), round(te[1], 1)],
            "winners_inside_train_test": [[tr[2], round(tr[3], 1)], [te[2], round(te[3], 1)]], "runners_inside_train_test": [tr[4], te[4]]}


def scope_report(rs):
    if len(rs) < A.MIN_SCOPE:
        return {"label": "NOT ENOUGH DATA", "replayed_trades": len(rs), "need": A.MIN_SCOPE}
    tr, te, cut = A.split_rows(rs)
    cuts = {n: B.tertile_cuts([r["st"].get(n) for r in tr]) for n in NUM}
    mfes = sorted(r["mfe"] for r in rs if r.get("mfe") is not None)
    rcut = mfes[int(len(mfes) * 0.75)] if mfes else float("inf")
    single = {}
    for n in NUM + CAT:
        single[n] = B.bucket_table(tr, te, lambda r, n=n: labels(r, cuts).get(n, "n/a"), tuple(sorted({labels(r, cuts).get(n, "n/a") for r in rs})))
    acc = pair_search(tr, te, cuts, rcut)
    ok = {k: v for k, v in acc.items() if v[0][0] >= MIN_N and v[1][0] >= MIN_N}
    block = sorted((k for k, v in ok.items() if v[0][1] < 0 and v[1][1] < 0), key=lambda k: max(ok[k][0][1], ok[k][1][1]))[:TOP]
    take = sorted((k for k, v in ok.items() if v[0][1] > 0 and v[1][1] > 0), key=lambda k: -min(ok[k][0][1], ok[k][1][1]))[:TOP]
    return {"replayed_trades": len(rs), "split_utc": P.fmt_ts(cut), "cuts_from_train": {n: list(cuts[n]) for n in NUM}, "runner_definition": "best ROI at or above %.2f%% (top quarter)" % rcut,
            "real_net_train_test": [round(sum(r["net"] for r in tr), 1), round(sum(r["net"] for r in te), 1)], "winner_profile": profile(rs, rcut), "single": single,
            "pairs_tried": len(acc), "pairs_with_enough_trades": len(ok), "block_candidates": [pack(k, ok[k]) for k in block], "take_candidates": [pack(k, ok[k]) for k in take],
            "how_to_read": "block_candidates: net below 0 in BOTH halves; check winners_inside and runners_inside (what a block would also kill). Candidates only: pairs_tried is large, luck is likely."}


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST", "min_trades_per_bucket_half": MIN_N}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    src = K.load_rows(root)
    if not src or not src.get("rows"):
        X.build_report(root, fee_roi)
        src = K.load_rows(root)
    rows, dropped = K.prepare((src or {}).get("rows") or [])
    cov = {"replayed": 0, "no_candles": 0, "warmup": 0, "no_entry_close_side_tf": 0, "candles_used": False}
    con = F.open_ro(root)
    if con is None:
        rep["error"] = "No candle store (v2_market.db)."
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
    done = [r for r in rows if r.get("st")]
    for g in X.GROUPS:
        grs = [r for r in done if r["g"] == g]
        rep[g] = {nm: scope_report([r for r in grs if tf is None or r["tf"] == tf]) for nm, tf in A.SCOPES}
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades. Hindsight.",
                    "Only a block / take pair that holds in BOTH halves, with few winners and runners killed, goes to a LOG test (bot Part 8)."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 7C: winner profile + block / take candidates (read-only)")
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
