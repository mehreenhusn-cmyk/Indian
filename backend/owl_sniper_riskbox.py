"""owl_sniper_riskbox.py - OwlSniper RISK BOX (Part 10 / FILE 21). READ ONLY: the market store is opened read-only, nothing is written, no network, no order code.
The Risk Box answers, before a trade: "In the past, when the indicators looked like THIS, what happened?" It never gives a guess: every number comes from real finished trades with labels (the learn bridge: Dual Bot, Brain, main bot).
How it works (plain words):
  1. POOL = bridge examples (owl_sniper_bridge_learn.load_examples): one row of indicator numbers at the signal candle + the label from the candles AFTER it (win, R after fees, time, worst move). Same signal from two bots counts once.
  2. For a new signal the Box takes the past examples with the SAME interval, SAME side and SAME regime, and keeps those whose four indicator numbers (Z-Score, TSI histogram, EMA cloud width, volatility ratio) are close to the new ones
     (standardized distance <= RADIUS, at most K nearest). Those are the "similar past trades".
  3. n similar trades < MIN_N (30) -> state NOT_ENOUGH_DATA and NO number is shown (owner rule: never a fake number). From 30 on: win %, the low end of its 95% range, expected R (mean, and its low end = mean - 2 standard errors), expected USDT (R x 1R in USDT),
     median and 75th-percentile time to the result, median time of the winners, worst-case move against the trade before the result (90th percentile of MAE, in R) and the worst single result, and the count per source (sources are shown apart, never added).
  Units: R = price move divided by the trade's own stop distance, after fee + slippage (same rule for every source, see owl_sniper_bridge_label). Times are seconds to the END of the result candle.
  1R in USDT = size x leverage x stop distance %. The caller gives it (risk_usdt) or the Box works it out from size_usdt, lev and the stop % of the signal.
PART 50 (FILE 59) adds 4 EXTRA LINES under the box (box["extras"], each line read only from an existing report, never a new number): EDGE (edge decay of this setup family: VALID / WEAK / EXPIRED / NOT_ENOUGH_DATA + kill status, FILE 20), SCALP / SWING label (from the box's own measured times, FILE 26), STAY OR ROTATE (the rule for an open trade, worked out from the box times; the real advice needs a live open trade, so this line says what the rule will be, never a fake decision, FILE 27), SESSION (how this session / hour did for this setup, FILE 42).
Still NOT here: nearest higher interval confluence (FILE 19, owl_sniper_mtf.py has confluence_line, not wired). The slow reports (edge decay + session) are built ONCE with the pool (build_reports) and cached by the route with it.
API: build_pool(examples), build_reports(examples, now=None), extras(box, reports, tf, side, regime, ts=None), risk_box(pool, sig, risk_usdt=None), sig_from_store(d, symbol, tf, side=None, now=None), for_symbol(d, symbol, tf, side=None, size_usdt=10, lev=1, pool=None). CLI:
  python3 backend/owl_sniper_riskbox.py --data DIR --symbol BTCUSDT [--tf 5m] [--side LONG|SHORT] [--limit 2000]  -> JSON.
sig = {symbol, tf, side, regime, feat {z, hist, gap_pct, vi_ratio, dir}, stop_pct}."""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_bridge_learn as BL
import owl_sniper_bridge_replay as RP
import owl_sniper_decay as DC
import owl_sniper_engine as E
import owl_sniper_feed as F
import owl_sniper_prob as P
import owl_sniper_scalp as SC
import owl_sniper_session as SS
import owl_sniper_tf as TF
import v2_defs as D
import v2_setup_finder as SF
try:                                                    # PART 51: the confluence study; a failed import only removes its line
    import owl_sniper_mtf as MTF
except Exception:
    MTF = None

VERSION = "owl_sniper_riskbox 1 (Part 10)"
MIN_N = 30            # fewer similar past trades than this = NOT ENOUGH DATA, no number at all
K = 100               # at most this many nearest similar trades are used
RADIUS = 1.5          # standardized distance (4 numbers); a random pair of trades is about 2.8 apart
STALE_STEPS = 3       # a live candle older than this many candle steps is not used


def quantile(xs, q):
    """Linear-interpolated quantile of a list (q 0..1). None for an empty list."""
    if not xs:
        return None
    s = sorted(xs)
    pos = (len(s) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def build_pool(examples):
    """Bridge examples (row + label) -> {items, mu, sd, n}. Same signal from two bots once (dual, brain, main). Pure, no disk."""
    ex, dup = BL.dedupe(examples)
    items = [{"src": e["source"], "tf": e["tf"], "side": e["side"], "regime": e["regime"], "vec": P.feat_vec(e["feat"]), "r": e["label"]["r_net"], "win": bool(e["label"]["win"]),
              "secs": e["label"]["secs_to_result"], "mae": e["label"]["mae_r"], "mfe": e["label"]["mfe_r"]} for e in ex]
    if not items:
        return {"items": [], "mu": None, "sd": None, "n": 0, "duplicates_dropped": dup}
    mu, sd = P.fit_standardizer([i["vec"] for i in items])
    return {"items": items, "mu": mu, "sd": sd, "n": len(items), "duplicates_dropped": dup}


def _dist(a, b, sd):
    return math.sqrt(sum(((x - y) / s) ** 2 for x, y, s in zip(a, b, sd)))


def _stats(sel, risk_usdt):
    n = len(sel)
    rs, w = [t["r"] for t in sel], sum(1 for t in sel if t["win"])
    mean = sum(rs) / n
    se = math.sqrt(sum((r - mean) ** 2 for r in rs) / (n - 1) / n) if n > 1 else 0.0
    wins_secs = [t["secs"] for t in sel if t["win"]]
    out = {"win_pct": round(100.0 * w / n, 1), "win_low95_pct": round(100.0 * P.wilson_low(w, n), 1), "wins": w, "losses": n - w,
           "exp_r": round(mean, 3), "exp_r_low": round(mean - 2.0 * se, 3), "median_r": round(quantile(rs, 0.5), 3), "worst_r": round(min(rs), 3),
           "median_secs": round(quantile([t["secs"] for t in sel], 0.5)), "p75_secs": round(quantile([t["secs"] for t in sel], 0.75)),
           "median_win_secs": round(quantile(wins_secs, 0.5)) if wins_secs else None, "mae_p90_r": round(quantile([t["mae"] for t in sel], 0.9), 3),
           "by_source": {s: sum(1 for t in sel if t["src"] == s) for s in sorted({t["src"] for t in sel})}}
    if risk_usdt:
        out.update(exp_usdt=round(mean * risk_usdt, 4), exp_usdt_low=round((mean - 2.0 * se) * risk_usdt, 4), worst_usdt=round(min(rs) * risk_usdt, 4), mae_p90_usdt=round(out["mae_p90_r"] * risk_usdt, 4))
    return out


def _mins(sec):
    """Plain time text; over 60 minutes = hours + minutes (owner rule, fixed in Part 50: it used to say '130 min')."""
    if sec < 90:
        return "%d s" % round(sec)
    m = int(round(sec / 60.0))
    if m <= 60:
        return "%d min" % m
    h, mm = divmod(m, 60)
    return "%d h" % h if mm == 0 else "%d h %d min" % (h, mm)


def build_reports(examples, now=None):
    """PART 50: the two slow reports for the extra lines, from the same examples as the pool (same signal from two bots once). Each in its own try: None = could not be built."""
    ex, _dup = BL.dedupe(examples)
    out = {}
    for k, mod in (("decay", DC), ("session", SS)):
        try:
            out[k] = mod.report(ex, now)
        except Exception:
            out[k] = None
    return out


MTF_COINS = 15          # PART 51: the confluence study reads at most this many coins (slow on a phone, so the route builds it in the background)


def build_mtf(d):
    """PART 51: the multi-timeframe confluence study (owl_sniper_mtf.build) for the Risk Box line. Slow, so the route calls it in a background thread and caches it. None = could not be built."""
    if MTF is None:
        return None
    try:
        return MTF.build(d, MTF_COINS)
    except Exception:
        return None


def live_state(d, symbol, tf, now=None):
    """PART 51: UP / DOWN / None = the state of the nearest higher candle (5m -> 15m, 15m -> 30m) of this coin right now. Read only; None when unknown."""
    try:
        plan = MTF.PLAN.get(tf)
        if not plan:
            return None
        now = time.time() if now is None else now
        con = F.open_ro(d)
        if con is None:
            return None
        try:
            raw = D.candles_from_store(con, symbol, TF.BASE, now - 600 * TF.STEP[TF.BASE], now)
        finally:
            con.close()
        good, _bad = D.clean_candles(raw, TF.BASE)
        runs = SF.runs(good, TF.BASE)
        return MTF.htf_state_now(runs[-1], plan[0]) if runs else None
    except Exception:
        return None


def extras(box, reports, tf, side, regime, ts=None, mtf=None, mtf_state=None):
    """PART 50: 4 plain lines under the box -> {edge, scalp, stay, session, lines}. Every line comes from an existing report; a report that is missing says NOT ENOUGH DATA, never a guess. Never raises."""
    reports = reports or {}
    out = {}
    try:
        out["edge"] = DC.for_signal(reports.get("decay"), tf, side, regime)
    except Exception:
        out["edge"] = {"state": "NOT_ENOUGH_DATA", "kill": "OK", "line": "Edge: NOT ENOUGH DATA (the edge report could not be read)."}
    try:
        sc = SC.for_box(box, tf)
        out["scalp"] = {"state": sc["state"], "label": sc["label"], "line": sc["line"]}
    except Exception:
        out["scalp"] = {"state": "NOT_ENOUGH_DATA", "label": "UNKNOWN", "line": "SCALP / SWING: NOT ENOUGH DATA."}
    ok = isinstance(box, dict) and box.get("state") == "OK" and box.get("median_secs") and box.get("p75_secs")
    out["stay"] = {"state": "RULE" if ok else "NOT_ENOUGH_DATA", "line": (
        "Stay or rotate (rule for an open trade, rough): STAY while it is inside the usual time (%s). After that, a small profit may be taken, or rotated only to a PROVEN better setup. Advice needs a live open trade." % _mins(box["median_secs"])
        if ok else "Stay or rotate: NOT ENOUGH DATA (no measured time for this setup yet).")}
    try:
        out["session"] = SS.for_signal(reports.get("session"), tf, ts)
    except Exception:
        out["session"] = {"state": "NOT_ENOUGH_DATA", "line": "Session: NOT ENOUGH DATA (the session report could not be read)."}
    try:                                                       # PART 51: line 5 = higher-interval confluence
        if MTF is None:
            ln = "MTF Confluence: not studied yet (the study file could not be loaded)."
        elif tf not in MTF.PLAN:
            ln = "MTF Confluence: not studied for this interval (only 5m and 15m are studied)."
        elif mtf is None:
            ln = "MTF Confluence: not studied yet (the study is still being built, open the box again in a few minutes)."
        else:
            ln = MTF.confluence_line(mtf, tf, side, mtf_state)
        out["confluence"] = {"state": "AGAINST" if ": Against" in ln else "NOT_STUDIED" if "not studied" in ln else "OK", "line": ln}
    except Exception:
        out["confluence"] = {"state": "NOT_STUDIED", "line": "MTF Confluence: not studied yet."}
    out["lines"] = [out[k]["line"] for k in ("edge", "scalp", "stay", "session", "confluence")]
    return out


def risk_box(pool, sig, risk_usdt=None):
    """The Risk Box of ONE signal. -> dict: state OK / NOT_ENOUGH_DATA / NO_SIGNAL, n, pool_n, text (one plain line), lines, and (state OK only) the numbers. Never raises on a bad signal."""
    base = {"version": VERSION, "state": "NOT_ENOUGH_DATA", "symbol": (sig or {}).get("symbol"), "tf": (sig or {}).get("tf"), "side": (sig or {}).get("side"), "regime": (sig or {}).get("regime"),
            "n": 0, "min_n": MIN_N, "pool_n": pool["n"], "radius": RADIUS, "risk_usdt": risk_usdt, "paper_only": True, "lines": []}
    try:
        feat, side, tf, reg = sig["feat"], sig["side"], sig["tf"], sig["regime"]
        x = P.feat_vec(feat)
        if side not in ("LONG", "SHORT") or any(v is None for v in x):
            raise KeyError("signal")
    except (KeyError, TypeError):
        base.update(state="NO_SIGNAL", text="No signal to rate.")
        base["lines"] = [base["text"]]
        return base
    same = [t for t in pool["items"] if t["tf"] == tf and t["side"] == side and t["regime"] == reg]
    near = sorted(((_dist(x, t["vec"], pool["sd"]), t) for t in same), key=lambda p: p[0]) if same else []
    sel = [t for d, t in near[:K] if d <= RADIUS]
    base.update(same_n=len(same), n=len(sel))
    if len(sel) < MIN_N:
        base["text"] = "NOT ENOUGH DATA: %d similar past trades (need %d). No number is shown." % (len(sel), MIN_N)
        base["lines"] = [base["text"], "Pool: %d finished trades in all, %d with the same interval (%s), side (%s) and regime (%s)." % (pool["n"], len(same), tf, side, reg)]
        return base
    st = _stats(sel, risk_usdt)
    base.update(st, state="OK")
    L = ["Based on %d similar past trades (%s %s, regime %s). Sources: %s." % (len(sel), tf, side, reg, ", ".join("%s %d" % kv for kv in st["by_source"].items())),
         "Win chance %.0f%% (could be as low as %.0f%%). Expected result %+.2f R after fees (low end %+.2f R)." % (st["win_pct"], st["win_low95_pct"], st["exp_r"], st["exp_r_low"]),
         "Typical time to the result: %s (3 of 4 finished within %s)." % (_mins(st["median_secs"]), _mins(st["p75_secs"])),
         "Worst case: price went against the trade by up to %.2f R in 9 of 10 cases; the worst single trade lost %.2f R." % (st["mae_p90_r"], -st["worst_r"])]
    if risk_usdt:
        L.append("With 1R = %.4f USDT: expected %+.4f USDT, worst single trade %+.4f USDT." % (risk_usdt, st["exp_usdt"], st["worst_usdt"]))
    if st["exp_r_low"] <= 0:
        L.append("The low end of the expected result is not above zero: this setup is NOT proven to pay.")
    base["lines"], base["text"] = L, L[1]
    return base


def sig_from_store(d, symbol, tf, side=None, now=None):
    """The newest CLOSED candle of one coin (saved candles, read only) -> sig for risk_box(), or {"state": ...} with a plain reason. side None = the Sniper's raw signal side on that candle."""
    now = time.time() if now is None else now
    if tf not in TF.SUPPORTED:
        return {"state": "tf_not_supported"}
    step, con = TF.step(tf), F.open_ro(d)
    if con is None:
        return {"state": "no_store"}
    try:
        raw = D.candles_from_store(con, symbol, TF.base(tf), now - (RP.WARM + 60) * step, now)
    finally:
        con.close()
    good, _bad = D.clean_candles(raw, TF.base(tf))
    runs = SF.runs(good, TF.base(tf))
    agg = TF.aggregate(runs[-1], tf) if runs else []
    if not agg:
        return {"state": "no_candles"}
    if now - (agg[-1][0] + step) > STALE_STEPS * step:
        return {"state": "stale"}
    cfg, _src = RP.load_cfg(d, tf)
    try:
        S = E.build_features(agg, cfg)
    except (ValueError, KeyError, IndexError, TypeError):
        return {"state": "bad_candles"}
    i = S["n"] - 1
    side = side or E.raw_signal(S, i)["side"]
    if side not in ("LONG", "SHORT"):
        return {"state": "no_signal"}
    row = RP.make_row({"uid": "live", "source": "live", "symbol": symbol, "tf": tf, "side": side, "entry_ts": agg[-1][0] + step}, S, [c[5] for c in agg], i, 0.0)
    if row is None:
        return {"state": "warmup"}
    return {"state": "OK", "symbol": symbol, "tf": tf, "side": side, "regime": row["regime"], "feat": row["feat"], "stop_pct": row["extra"]["stop_line_pct"], "candle_open_ts": row["candle_open_ts"]}


def for_symbol(d, symbol, tf, side=None, size_usdt=10.0, lev=1.0, pool=None, limit=2000, now=None, mtf=None):
    """One call for a route or the CLI: live signal of the coin + the Risk Box. pool=None builds it from the saved files (slow on a phone: a route should pass a cached pool)."""
    sig = sig_from_store(d, symbol, tf, side, now)
    if sig.get("state") != "OK":
        txt = {"no_signal": "The Sniper's own rule gives no signal on the newest candle.", "stale": "The newest candle is too old.", "warmup": "Not enough candles yet for the indicators."}.get(sig["state"], "The candles could not be read (%s)." % sig["state"])
        return {"version": VERSION, "state": "NO_SIGNAL", "symbol": symbol, "tf": tf, "reason": sig["state"], "text": txt, "lines": [txt], "paper_only": True}
    if pool is None:
        ex = BL.load_examples(d, limit)[0]
        pool = build_pool(ex)
        pool["reports"] = build_reports(ex, now)
    risk = size_usdt * lev * sig["stop_pct"] / 100.0 if sig.get("stop_pct") else None
    box = risk_box(pool, sig, risk)
    box["stop_pct"], box["candle_open_ts"], box["size_usdt"], box["lev"] = sig.get("stop_pct"), sig["candle_open_ts"], size_usdt, lev
    box["extras"] = extras(box, pool.get("reports"), tf, sig["side"], sig["regime"], mtf=mtf, mtf_state=live_state(d, symbol, tf, now))        # PART 50 + 51
    return box


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper Risk Box: what happened in similar past trades (read only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or ".")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--side", choices=("LONG", "SHORT"), default=None)
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--size", type=float, default=10.0)
    ap.add_argument("--lev", type=float, default=1.0)
    a = ap.parse_args(argv)
    print(json.dumps(for_symbol(a.data, a.symbol.upper(), a.tf, a.side, a.size, a.lev, limit=a.limit), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
