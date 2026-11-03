"""owl_sniper_corr.py - OwlSniper CORRELATION check (Part 43 / FILE 52). PAPER ONLY, REPORT ONLY: it gives a plain OK / BLOCKED answer for the caller, it opens, closes and changes nothing. Read only, no network, nothing written.
The question: "Five LONGs on five coins are not five bets. If the market dips they all lose together. How many same-direction trades are too many?"
How it works (plain words):
  1. MEASURED closeness of two coins = the correlation of their 5m returns over the last day (288 returns, both coins on the same candles, gap-free run only). Fewer than 100 shared returns = unknown.
  2. CLUSTER = same-direction open trades that are close (correlation 0.70 or more, or the same coin). Linked trades join one cluster (A~B and B~C = one cluster). An UNKNOWN pair is ASSUMED close (coins move together; the line says "assumed").
     A cluster counts as ONE risk slot. Its open risk is the SUM of its trades in R, because they can all lose together (nothing is netted down). A LONG and a SHORT are never in one cluster and one does NOT hedge the other here (conservative).
  3. check(open, new): the new trade is BLOCKED if the cluster it would join already holds MAX_PER_CLUSTER (2) trades, or its open risk plus the new trade would pass CLUSTER_RISK_R (2.0 R). Else OK. Both limits are STARTING values the owner may tune inside LIMITS (anything outside is clamped).
     The size, the 85% floor, the daily loss limit and the max open of owl_sniper_capital.py still decide on their own; this file only ADDS one more reason to say no. It never raises a size or lowers a gate.
  4. EVIDENCE (loss_together): do the saved trades of different coins on the same candle and the same side really lose together? Over-dispersion test of the losses per (interval, side, candle) group:
     TOGETHER (z above 2), NO_CLEAR_LINK, or NOT_ENOUGH_DATA below 30 such groups. Info only: it says whether the rule has a reason in the owner's own data; it does not change the limits by itself.
Not wired: nothing calls check() yet (the caller is the executor / paper opener, a later small edit; the open trades come from the caller). Only build() reads the saved candles.
API: pearson(a, b), returns(series), pair_corr(sa, sb), clusters(open, rho), check(open, new, series=None, over=None), loss_together(examples), build(d, open, new, tf="5m", now=None). CLI:
  python3 backend/owl_sniper_corr.py --file FILE.json            ({open: [{symbol, side, risk_r}], new: {symbol, side, risk_r}, series: {SYM: [[ts, close], ...]}})
  python3 backend/owl_sniper_corr.py --data DIR --file FILE.json (candles are read from the saved store instead of `series`)."""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = "owl_sniper_corr 1 (Part 43)"
WINDOW = 288                # 5m returns = one day
MIN_OVERLAP = 100           # shared returns before a correlation is trusted
LIMITS = {"corr_min": (0.5, 0.95), "max_per_cluster": (1, 3), "cluster_risk_r": (1.0, 3.0)}
DEFAULTS = {"corr_min": 0.70, "max_per_cluster": 2, "cluster_risk_r": 2.0}
MIN_GROUPS = 30             # (interval, side, candle) groups before the loss-together test speaks


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def cfg(over=None):
    """Defaults + the owner's values, every one clamped into LIMITS (a bad value falls back to the default)."""
    out = dict(DEFAULTS)
    for k, (lo, hi) in LIMITS.items():
        v = _num((over or {}).get(k))
        if v is not None:
            out[k] = min(hi, max(lo, v))
    out["max_per_cluster"] = int(out["max_per_cluster"])
    return out


def pearson(a, b):
    """Correlation of two equal-length number lists, or None (too short, flat, bad numbers)."""
    n = len(a)
    if n < 3 or n != len(b):
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def returns(series):
    """[[ts, close], ...] -> {ts: simple return from the candle before}. Bad / non-positive closes are skipped, and a return is never made across a skipped candle."""
    pts = sorted((_num(t), _num(c)) for t, c in (series or []))
    out, prev = {}, None
    for t, c in pts:
        if t is None or c is None or c <= 0:
            prev = None
            continue
        if prev is not None:
            out[t] = c / prev - 1.0
        prev = c
    return out


def pair_corr(sa, sb):
    """Two series -> {rho, n} on the shared candle times (newest WINDOW returns), or None when fewer than MIN_OVERLAP are shared."""
    ra, rb = returns(sa), returns(sb)
    ts = sorted(set(ra) & set(rb))[-WINDOW:]
    if len(ts) < MIN_OVERLAP:
        return None
    rho = pearson([ra[t] for t in ts], [rb[t] for t in ts])
    return None if rho is None else {"rho": round(rho, 3), "n": len(ts)}


def clusters(open_trades, rho=None, c=None):
    """Same-direction trades -> clusters {side, symbols, n, risk_r, assumed}. rho(a, b) -> number or None (None = unknown = assumed close). Same coin = close."""
    c = c or cfg()
    ts = [{"symbol": str(t.get("symbol")), "side": t.get("side"), "risk_r": _num(t.get("risk_r")) or 1.0} for t in open_trades or [] if t.get("side") in ("LONG", "SHORT")]
    par, assumed = list(range(len(ts))), set()

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    for i in range(len(ts)):
        for j in range(i + 1, len(ts)):
            if ts[i]["side"] != ts[j]["side"]:
                continue
            if ts[i]["symbol"] == ts[j]["symbol"]:
                r = 1.0
            else:
                r = rho(ts[i]["symbol"], ts[j]["symbol"]) if rho else None
            if r is None:
                assumed.update((i, j))
            if r is None or r >= c["corr_min"]:
                par[find(i)] = find(j)
    g = {}
    for i, t in enumerate(ts):
        g.setdefault(find(i), []).append(i)
    return [{"side": ts[m[0]]["side"], "symbols": [ts[i]["symbol"] for i in m], "n": len(m), "risk_r": round(sum(ts[i]["risk_r"] for i in m), 3),
             "last": (len(ts) - 1) in m, "assumed": any(i in assumed for i in m) and len(m) > 1} for m in g.values()]


def check(open_trades, new, series=None, over=None):
    """May the NEW trade join the open ones? -> {decision OK / BLOCKED / UNKNOWN, gate, text, cluster, slots_now, slots_after, paper_only}. Never raises on bad input.
    series = {SYMBOL: [[ts, close], ...]} (optional): without candles every pair is assumed close, which is the safe side."""
    c = cfg(over)
    base = {"paper_only": True, "report_only": True, "limits": c, "version": VERSION}
    if not isinstance(new, dict) or new.get("side") not in ("LONG", "SHORT") or not new.get("symbol"):
        return dict(base, decision="UNKNOWN", gate="input", text="The new trade has no coin or side: nothing was checked.", cluster=None, slots_now=None, slots_after=None)
    cache = {}

    def rho(a, b):
        k = tuple(sorted((a, b)))
        if k not in cache:
            p = pair_corr((series or {}).get(a), (series or {}).get(b)) if series and a in series and b in series else None
            cache[k] = None if p is None else p["rho"]
        return cache[k]

    now = clusters(open_trades, rho, c)
    after = clusters(list(open_trades or []) + [new], rho, c)
    mine = next((x for x in after if x["last"]), None)         # the cluster that holds the new trade (it is the last one in the list)
    nr = _num(new.get("risk_r")) or 1.0
    hold = (mine["n"] - 1) if mine else 0
    risk_before = (mine["risk_r"] - nr) if mine else 0.0
    out = dict(base, cluster=mine, slots_now=len(now), slots_after=len(after))
    names = ", ".join(mine["symbols"][:-1]) if mine and hold else ""
    tail = " (pairs without enough candles are assumed close)" if mine and mine["assumed"] else ""
    if hold >= c["max_per_cluster"]:
        return dict(out, decision="BLOCKED", gate="cluster_count", text="BLOCKED: %d %s trades already move together (%s)%s. They count as ONE risk; the limit is %d per group." % (hold, new["side"], names, tail, c["max_per_cluster"]))
    if hold and risk_before + nr > c["cluster_risk_r"] + 1e-9:
        return dict(out, decision="BLOCKED", gate="cluster_risk", text="BLOCKED: this group would risk %.1f R together (%s + the new trade)%s; the limit is %.1f R." % (risk_before + nr, names, tail, c["cluster_risk_r"]))
    if hold:
        return dict(out, decision="OK", gate="", text="OK: it joins %d %s trade(s) that move together (%s): group risk %.1f R of %.1f R%s." % (hold, new["side"], names, risk_before + nr, c["cluster_risk_r"], tail))
    return dict(out, decision="OK", gate="", text="OK: no open %s trade moves together with %s (%d risk slot(s) after it)." % (new["side"], new["symbol"], len(after)))


def loss_together(examples):
    """Bridge examples -> do same-side trades of the SAME candle lose together more than luck? Over-dispersion of losses per (interval, side, candle) group of 2+ trades.
    -> {state TOGETHER / NO_CLEAR_LINK / NOT_ENOUGH_DATA, groups, trades, loss_pct, z, text}. Info only."""
    g, n_all, n_loss = {}, 0, 0
    for e in examples or []:
        r, t = _num((e.get("label") or {}).get("r_net")), _num(e.get("entry_ts"))
        if r is None or t is None or not e.get("tf") or e.get("side") not in ("LONG", "SHORT"):
            continue
        step = {"3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400}.get(str(e["tf"]), 300)
        g.setdefault((e["tf"], e["side"], int(t // step)), []).append(1 if r <= 0 else 0)
        n_all, n_loss = n_all + 1, n_loss + (1 if r <= 0 else 0)
    multi = [v for v in g.values() if len(v) >= 2]
    if n_all == 0 or len(multi) < MIN_GROUPS:
        return {"state": "NOT_ENOUGH_DATA", "groups": len(multi), "trades": n_all, "loss_pct": None, "z": None,
                "text": "NOT ENOUGH DATA: %d candles with 2+ same-side trades, %d needed. The limits above stay as a safe guess." % (len(multi), MIN_GROUPS)}
    p = n_loss / float(n_all)
    if p <= 0 or p >= 1:
        return {"state": "NO_CLEAR_LINK", "groups": len(multi), "trades": n_all, "loss_pct": round(100 * p, 1), "z": None, "text": "All trades lost or all won: nothing to compare."}
    x = sum((sum(v) - len(v) * p) ** 2 / (len(v) * p * (1 - p)) for v in multi)
    z = (x - len(multi)) / math.sqrt(2.0 * len(multi))
    st = "TOGETHER" if z > 2.0 else "NO_CLEAR_LINK"
    txt = ("Same-side trades on the same candle lose together more than luck would give (z %.1f over %d candles). The one-risk rule has a reason in your own data." % (z, len(multi))) if st == "TOGETHER" else \
        "No clear sign that same-side trades on the same candle lose together (z %.1f over %d candles). The rule stays as a safe guess, not as a proof." % (z, len(multi))
    return {"state": st, "groups": len(multi), "trades": n_all, "loss_pct": round(100 * p, 1), "z": round(z, 2), "text": txt}


def build(d, open_trades, new, tf="5m", now=None, over=None):
    """check() with the candles read from the saved store (read only, never created). A coin without candles is simply unknown = assumed close. Never raises."""
    try:
        import owl_sniper_feed as F
        import owl_sniper_tf as TF
        import v2_defs as D
        import v2_setup_finder as SF
        now = time.time() if now is None else now
        syms = {str(t.get("symbol")) for t in list(open_trades or []) + [new or {}] if t.get("symbol")}
        con, series = F.open_ro(d), {}
        if con is not None:
            try:
                base, step = TF.base(tf), TF.step(tf)
                for s in syms:
                    good, _bad = D.clean_candles(D.candles_from_store(con, s, base, now - (WINDOW + 5) * step, now), base)
                    runs = SF.runs(good, base)
                    if runs:
                        series[s] = [[c[0], c[4]] for c in runs[-1]]
            finally:
                con.close()
        r = check(open_trades, new, series, over)
        r["candles_read"] = sorted(series)
        return r
    except Exception as e:  # a broken file must never break the caller
        r = check(open_trades, new, None, over)
        r["note"] = "Candles could not be read (%s): every pair was assumed close." % type(e).__name__
        return r


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper correlation check (paper only, report only)")
    ap.add_argument("--file", required=True, help="JSON: {open: [...], new: {...}, series: {SYM: [[ts, close], ...]}}")
    ap.add_argument("--data", default=None, help="read the candles from this data folder instead of `series`")
    ap.add_argument("--tf", default="5m")
    a = ap.parse_args(argv)
    with open(a.file) as f:
        j = json.load(f)
    r = build(a.data, j.get("open"), j.get("new"), a.tf, None, j.get("over")) if a.data else check(j.get("open"), j.get("new"), j.get("series"), j.get("over"))
    print(json.dumps(r, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
