"""v2_f1_counts.py - FILTER STUDY Part 1: COUNTS + LABELS + ENTRY NUMBERS + SD SHAPE (read-only). Main and Sniper are always separate.
Why: README_FILTER.md. We want to know WHY fake signals come, without killing the long rallies / dumps. This file only MEASURES. It makes no rule, changes no setting, no position, no order.
Reads:  closed_trades_archive.jsonl + closed_trades_archive_b2.jsonl (same readers as Money Map, Part 5; duplicates counted once), v2_market.db (candles + cohort_official, read-only).
Writes: v2_filter_trades.json in the data folder (one compact row per trade, for Parts 2 to 4 to reuse) and the summary JSON (the ONE file the owner sends back).
Groups: MAIN = every paper trade that is not Sniper; SNIPER = source sniper (real gate) + sniper_learn (LEARN lane, shown as lane). Only PAPER rows are studied; live rows are only counted.
Day = crypto day, 00:00 UTC = 5:30 AM IST. Never India market time. Durations over 60 min are written as hours + minutes.
1) COUNTS    trades per group x timeframe (3m / 5m / 15m), wins / losses, net (fee-correct), exit kinds, trades per day, hold time.
2) LABELS    per trade: WIN / LOSS / FLAT (net), exit kind (SL, TP, OPPOSITE = opposite-signal exit, TIME, MANUAL, OTHER), best ROI seen (mfe), worst (mae), give-back (mfe minus close).
3) ENTRY NUMBERS  at the signal candle (the last CLOSED candle before the entry), from the saved candles:
   % from day open (and with the trade side), signal candle size + wick against the side, distance from EMA50, candles since the EMA50 cross, volume vs the 20-candle average,
   TP4 / TP1 distance vs fee, nth trade of that coin that day, coin rank in today's top-10 (gainer or loser list) and whether the trade side is WITH or AGAINST that list, days in the list.
4) SD SHAPE  Z zone (SD band level), band width trend (expanding / flat / squeezing), centre line direction, how often the shape flipped in the last 50 candles,
   and setup status at entry: is band (Z zone) + TSI + EMA cloud agreeing (3/3 COMPLETE, 2/3 FORMING, 0-1/3 WEAK).
Bucket edges are only for GROUPING numbers so they can be read. They are NOT rules and NOT cut-offs: cut-offs come from the data in Parts 2 to 4.
Fewer than 30 trades in a bucket = NOT ENOUGH DATA (facts shown, no conclusion). Candles come from the same engine as the live Sniper (owl_sniper_engine, same settings if the model file exists, else defaults).
CHECK still open (README_FILTER): the Python Z-score must match the Pine Z-score. Until that is checked, read Z buckets as 'engine Z'.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f1_counts.py --data /home/owl/owl_data --out -     (summary goes to the screen / redirect it to a file)
Options: --out FILE|-   --fee-roi 1.0 (fee % of ROI for OLD trades with no fee)   --no-candles (counts + labels only)"""
import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_engine as E
import owl_sniper_feed as F
import owl_sniper_ind_pairs as IP
import owl_sniper_tf as TF
import v2_defs as D
import v2_inventory as I
import v2_money_hour as M
import v2_pnl as P
import v2_setup_finder as SF

VERSION = "v2_f1_counts 1 (Filter Part 1)"
MIN_N = 30
ROWS_FILE = "v2_filter_trades.json"
LOOK = 400                                   # candles read before the first entry of a coin (SD length is 200)
TFS = ("3m", "5m", "15m")
GROUPS = ("MAIN", "SNIPER")

# ----------------------------------------------------------------------------- bucket names (grouping only)
EDGES = {
    "z": ([-3, -2, -1, 0, 1, 2, 3], ["z < -3", "-3..-2", "-2..-1", "-1..0", "0..1", "1..2", "2..3", "z >= 3"]),
    "z_side": ([-2, -1, 0, 1, 2], ["< -2", "-2..-1", "-1..0", "0..1", "1..2", ">= 2"]),
    "pump_side": ([-5, -2, 0, 2, 5, 10], ["< -5%", "-5..-2%", "-2..0%", "0..2%", "2..5%", "5..10%", ">= 10%"]),
    "size": ([0.3, 0.6, 1, 2], ["< 0.3%", "0.3-0.6%", "0.6-1%", "1-2%", ">= 2%"]),
    "wick": ([0.1, 0.25, 0.5], ["< 10%", "10-25%", "25-50%", ">= 50%"]),
    "ema50": ([0.3, 0.7, 1.5, 3], ["< 0.3%", "0.3-0.7%", "0.7-1.5%", "1.5-3%", ">= 3%"]),
    "cross": ([3, 10, 30, 100], ["< 3", "3-9", "10-29", "30-99", ">= 100"]),
    "vol": ([0.7, 1.2, 2, 4], ["< 0.7x", "0.7-1.2x", "1.2-2x", "2-4x", ">= 4x"]),
    "tp4fee": ([1, 2, 4, 8], ["< 1x", "1-2x", "2-4x", "4-8x", ">= 8x"]),
    "tp1fee": ([0.5, 1, 2, 4], ["< 0.5x", "0.5-1x", "1-2x", "2-4x", ">= 4x"]),
    "nth": ([2, 3, 4], ["1st", "2nd", "3rd", "4th+"]),
    "age": ([2, 3], ["1 day", "2 days", "3+ days"]),
}
CATS = {
    "shape": ["EXPANDING", "FLAT", "SQUEEZING"],
    "band_dir": ["WITH side", "FLAT", "AGAINST side"],
    "flips": ["STABLE (0-2)", "CHANGING (3-6)", "JUMPY (7+)"],
    "setup": ["COMPLETE (3/3)", "FORMING (2/3)", "WEAK (0-1/3)"],
    "list_side": ["WITH list", "AGAINST list", "not in top-10"],
    "rank": ["1", "2", "3", "4", "5"],
    "exit": ["SL", "TP", "OPPOSITE", "TIME", "MANUAL", "OTHER"],
}
TABLES = (("exit", "exit_b"), ("setup", "setup_b"), ("z", "z_b"), ("z_side", "z_side_b"), ("shape", "shape_b"), ("band_dir", "band_dir_b"), ("flips", "flips_b"),
          ("pump_side", "pump_b"), ("size", "size_b"), ("wick", "wick_b"), ("ema50", "ema50_b"), ("cross", "cross_b"), ("vol", "vol_b"), ("tp4fee", "tp4fee_b"),
          ("tp1fee", "tp1fee_b"), ("nth", "nth_b"), ("list_side", "list_b"), ("rank", "rank_b"), ("age", "age_b"))


def bucket(v, key):
    """Number -> readable bucket name ('n/a' when there is no number)."""
    if v is None:
        return "n/a"
    edges, names = EDGES[key]
    for e, nm in zip(edges, names):
        if v < e:
            return nm
    return names[-1]


def fmt_dur(minutes):
    """Over 60 min = hours + minutes (owner rule), never '220 min'."""
    if minutes is None:
        return "n/a"
    m = int(round(minutes))
    return "%d min" % m if m <= 60 else ("%d h %02d min" % (m // 60, m % 60) if m % 60 else "%d h" % (m // 60))


def utc_day(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")


# ----------------------------------------------------------------------------- trades + labels
def load_trades(root):
    """All closed rows of both archives, duplicates once. -> (rows, source status)."""
    rows, seen, st = [], set(), {}
    for name, file_bot in P.FILES:
        got, s = P.read_jsonl(os.path.join(root, name), [root])
        st[name] = s
        for t in got:
            k = P.tkey(t)
            if k in seen:
                continue
            seen.add(k)
            t["_box"] = P.box_of(t, file_bot)
            rows.append(t)
    return rows, st


def group_of(t):
    src = str(t.get("source") or "").lower()
    return "SNIPER" if src.startswith("sniper") else "MAIN"


def lane_of(t):
    src = str(t.get("source") or "").lower()
    return "LEARN" if "learn" in src else ("REAL_GATE" if src.startswith("sniper") else "-")


def tf_of(t):
    v = str(t.get("timeframe") or "").strip().lower()
    return v if v in TFS else "unknown"


def side_of(t):
    a = str(t.get("action") or "").upper()
    return 1 if a in ("BUY", "LONG") else (-1 if a in ("SELL", "SHORT") else 0)


def exit_kind(status):
    s = str(status or "").upper()
    if "REVERS" in s or "OPPOSITE" in s:
        return "OPPOSITE"
    if "SL" in s or "STOP" in s:
        return "SL"
    if "TP" in s:
        return "TP"
    if "TIME" in s:
        return "TIME"
    if "MANUAL" in s or "CLOSE_ALL" in s:
        return "MANUAL"
    return "OTHER"


def label_trade(t, fee_roi):
    """One closed trade -> flat dict with its label numbers. Entry numbers are added later."""
    net = M.net_fee_correct(t, fee_roi)
    ent, from_close = M.entry_ts(t)
    cl = P.num(t, "closed_at_ts")
    roi, mfe, mae = P.num(t, "roi_pct"), P.num(t, "max_roi_pct"), P.num(t, "min_roi_pct")
    hold = (cl - ent) / 60.0 if cl and ent and not from_close and cl >= ent else None
    return {"id": t.get("id"), "sym": t.get("symbol"), "g": group_of(t), "lane": lane_of(t), "tf": tf_of(t), "side": side_of(t), "box": t.get("_box"),
            "ent": ent, "ent_from_close": bool(from_close), "close": cl, "net": net, "invest": P.num(t, "invest_usdt"), "lev": P.num(t, "leverage"),
            "res": "NO_PNL" if net is None else ("WIN" if net > 0 else ("LOSS" if net < 0 else "FLAT")),
            "exit_b": exit_kind(t.get("status")), "status": t.get("status"), "mfe": mfe, "mae": mae, "roi": roi,
            "giveback": max(0.0, mfe - roi) if mfe is not None and roi is not None else None,
            "hold_min": hold, "hold_text": fmt_dur(hold), "entry_price": P.num(t, "entry_price"),
            "tp1": P.num(t, "signal_tp1"), "tp4": P.num(t, "signal_tp4"), "fee_roi": P.num(t, "fee_roi_pct") if P.num(t, "fee_roi_pct") is not None else fee_roi,
            "regime_cross_n": P.num(t, "regime_cross_n")}


def add_nth(rows):
    """nth trade of that coin that day (all paper trades of the coin, any group, by entry time)."""
    day = {}
    for r in sorted((x for x in rows if x["ent"] and not x["ent_from_close"]), key=lambda x: x["ent"]):
        k = (r["sym"], utc_day(r["ent"]))
        day[k] = day.get(k, 0) + 1
        r["nth"] = day[k]
        r["nth_b"] = bucket(day[k], "nth")
    for r in rows:
        r.setdefault("nth", None)
        r.setdefault("nth_b", "n/a")


# ----------------------------------------------------------------------------- candles -> entry numbers
def load_cohort(con):
    """{(day, symbol): (kind, rank)} and the set of days per symbol (top 5 gainers + top 5 losers every 00:00 UTC)."""
    cohort = {}
    if con is None:
        return cohort
    try:
        for day, kind, rank, sym in con.execute("SELECT day, kind, rank, symbol FROM cohort_official").fetchall():
            cohort[(str(day)[:10], sym)] = (str(kind).upper(), int(rank))
    except Exception:
        pass
    return cohort


def cohort_numbers(r, cohort):
    day = utc_day(r["ent"])
    hit = cohort.get((day, r["sym"]))
    if not hit:
        return {"list_b": "not in top-10", "rank_b": "n/a", "age_b": "n/a", "list_kind": None, "list_rank": None, "list_days": 0}
    kind, rank = hit
    with_list = (kind.startswith("GAIN") and r["side"] == 1) or (kind.startswith("LOS") and r["side"] == -1)
    days, d = 0, datetime.datetime.strptime(day, "%Y-%m-%d")
    while (d.strftime("%Y-%m-%d"), r["sym"]) in cohort and days < 30:
        days += 1
        d -= datetime.timedelta(days=1)
    return {"list_b": "WITH list" if with_list else "AGAINST list", "rank_b": str(rank), "age_b": bucket(days, "age"), "list_kind": kind, "list_rank": rank, "list_days": days}


def shape_numbers(S, i, side):
    """SD band shape at candle i: width trend, centre direction, flips in the last 50 candles, Z zone."""
    out = {}
    m, d, z = S["sma"], S["sd"], S["z"]
    width = lambda j: (d[j] / m[j] * 100.0) if m[j] and d[j] is not None else None
    w0, w1 = width(i), width(i - 20) if i >= 20 else None
    ch = (w0 / w1 - 1.0) * 100.0 if w0 is not None and w1 else None
    out["width_pct"], out["width_chg20_pct"] = w0, ch
    out["shape_b"] = "n/a" if ch is None else ("EXPANDING" if ch > 5 else ("SQUEEZING" if ch < -5 else "FLAT"))
    sl = (m[i] - m[i - 20]) / m[i - 20] * 100.0 if i >= 20 and m[i] and m[i - 20] else None
    out["center_slope20_pct"] = sl
    out["band_dir_b"] = "n/a" if sl is None else ("FLAT" if abs(sl) < 0.1 else ("WITH side" if sl * side > 0 else "AGAINST side"))
    signs, flips = [], 0
    for j in range(max(5, i - 49), i + 1):
        a, b = width(j), width(j - 5)
        if a is not None and b:
            signs.append(1 if a > b else -1)
    for k in range(1, len(signs)):
        flips += signs[k] != signs[k - 1]
    out["shape_flips50"] = flips if signs else None
    out["flips_b"] = "n/a" if not signs else ("STABLE (0-2)" if flips <= 2 else ("CHANGING (3-6)" if flips <= 6 else "JUMPY (7+)"))
    out["z"] = z[i]
    out["z_b"] = bucket(z[i], "z")
    out["z_side"] = z[i] * side if z[i] is not None else None
    out["z_side_b"] = bucket(out["z_side"], "z_side")
    return out


def setup_numbers(S, i, side, cfg):
    """Do band (Z zone) + TSI + EMA cloud agree with the trade side at the signal candle?"""
    z, hist, tsi, cloud = S["z"][i], S["hist"][i], S["tsi"][i], S["cloud"][i]
    if None in (z, hist, cloud) or side == 0:
        return {"setup_b": "n/a", "z_ok": None, "tsi_ok": None, "ema_ok": None, "tsi_zero_ok": None, "raw_agrees": None}
    zok = (cfg["z_lo"] < z < cfg["z_hi"]) if side == 1 else (-cfg["z_hi"] < z < -cfg["z_lo"])
    tok, eok = hist * side > 0, cloud == side
    n = int(zok) + int(tok) + int(eok)
    try:
        raw = E.raw_signal(S, i).get("side")
        agrees = None if raw is None else ((raw == "LONG") == (side == 1))
    except Exception:
        agrees = None
    return {"setup_b": "COMPLETE (3/3)" if n == 3 else ("FORMING (2/3)" if n == 2 else "WEAK (0-1/3)"), "z_ok": zok, "tsi_ok": tok, "ema_ok": eok,
            "tsi_zero_ok": (tsi * side > 0) if tsi is not None else None, "raw_agrees": agrees}


def candle_numbers(S, run, idx, i, r):
    """Size, wick, pump from day open, EMA50 distance, candles since the EMA50 cross, volume ratio, TP vs fee."""
    o, h, l, c = S["o"][i], S["h"][i], S["l"][i], S["c"][i]
    rng, side = h - l, r["side"]
    out = {"sig_t": S["t"][i], "size_pct": rng / c * 100.0}
    out["size_b"] = bucket(out["size_pct"], "size")
    if rng > 0 and side:
        wick = (h - max(o, c)) / rng if side == 1 else (min(o, c) - l) / rng      # the wick on the side the trade runs to = rejection against the trade
        out["wick_against"] = wick
        out["wick_b"] = bucket(wick, "wick")
    else:
        out["wick_against"], out["wick_b"] = None, "n/a"
    d0 = idx.get(S["t"][i] - S["t"][i] % 86400)
    pump = (c / S["o"][d0] - 1.0) * 100.0 if d0 is not None else None
    out["pct_day_open"] = pump
    out["pump_b"] = bucket(pump * side, "pump_side") if pump is not None and side else "n/a"
    es = S["ema_s"][i]
    out["ema50_dist_pct"] = (c - es) / c * 100.0 if es else None
    out["ema50_b"] = bucket(abs(out["ema50_dist_pct"]), "ema50") if out["ema50_dist_pct"] is not None else "n/a"
    n_cross = None
    if es:
        sg, n_cross = c > es, 0
        for j in range(i, max(-1, i - 500), -1):
            if S["ema_s"][j] is None or (S["c"][j] > S["ema_s"][j]) != sg:
                break
            n_cross += 1
    out["since_ema50_cross"] = n_cross
    out["cross_b"] = bucket(n_cross, "cross")
    vols = [run[j][5] for j in range(max(0, i - 20), i)]
    avg = sum(vols) / len(vols) if vols else 0
    out["vol_ratio"] = run[i][5] / avg if avg > 0 else None
    out["vol_b"] = bucket(out["vol_ratio"], "vol")
    ep, lev, fee = r["entry_price"], r["lev"], r["fee_roi"]
    fee_px = fee / lev if fee and lev else None                                  # round-trip fee as % of PRICE
    for k, key in (("tp4", "tp4fee"), ("tp1", "tp1fee")):
        dist = abs(r[k] - ep) / ep * 100.0 if r.get(k) and ep else None
        out[k + "_pct"] = dist
        out[key + "_x"] = dist / fee_px if dist is not None and fee_px else None
        out[key + "_b"] = bucket(out[key + "_x"], key)
    return out


class Candles:
    """Read-only candles of one (coin, timeframe), cut at gaps, with the engine numbers for each gap-free run."""

    def __init__(self, con, cfg_by_tf):
        self.con, self.cfg_by_tf = con, cfg_by_tf

    def load(self, sym, tf, t0, t1):
        base, fac = ("5m", 3) if tf == "15m" else (tf, 1)
        step = D.STEP[base]
        rows = D.candles_from_store(self.con, sym, base, t0 - LOOK * step * fac, t1 + step * fac)
        good, _bad = D.clean_candles(rows, base)
        out = []
        for run in SF.runs(good, base):
            a = TF.aggregate(run, "15m") if tf == "15m" else run
            if len(a) < 60:
                continue
            try:
                S = E.build_features(a, self.cfg_by_tf[tf])
            except (ValueError, KeyError, IndexError, TypeError):
                continue
            out.append((S, a, {t: j for j, t in enumerate(S["t"])}))
        return out, step * fac


def entry_numbers(rows, con, cohort, cfg_by_tf, cov):
    """Fill the entry numbers of every trade that has a coin, a timeframe with candles, and an entry time."""
    store, groups = Candles(con, cfg_by_tf), {}
    for r in rows:
        if r["box"] and not str(r["box"]).startswith("paper"):
            cov["skipped_live"] += 1
        elif not r["sym"] or not r["ent"] or r["ent_from_close"]:
            cov["no_entry_time"] += 1
        elif r["tf"] == "unknown":
            cov["no_timeframe"] += 1
        elif r["side"] == 0:
            cov["no_side"] += 1
        else:
            groups.setdefault((r["sym"], r["tf"]), []).append(r)
    for (sym, tf), rs in groups.items():
        runs, step = store.load(sym, tf, min(x["ent"] for x in rs), max(x["ent"] for x in rs))
        for r in rs:
            sig_t = int((r["ent"] - step) // step * step)                        # open of the last candle that was already CLOSED at the entry
            hit = next(((S, a, idx, idx[sig_t]) for S, a, idx in runs if sig_t in idx), None)
            if hit is None:
                cov["no_candles"] += 1
                continue
            S, a, idx, i = hit
            if i < E.warmup_end(S):
                cov["warmup"] += 1
                continue
            r.update(candle_numbers(S, a, idx, i, r))
            r.update(shape_numbers(S, i, r["side"]))
            r.update(setup_numbers(S, i, r["side"], cfg_by_tf[tf]))
            r.update(cohort_numbers(r, cohort))
            cov["with_numbers"] += 1


# ----------------------------------------------------------------------------- summaries
def stats(rs):
    n = len(rs)
    nets = [r["net"] for r in rs if r["net"] is not None]
    w, lo = sum(1 for x in nets if x > 0), sum(1 for x in nets if x < 0)
    holds = [r["hold_min"] for r in rs if r.get("hold_min") is not None]
    mfe = [r["mfe"] for r in rs if r.get("mfe") is not None]
    gb = [r["giveback"] for r in rs if r.get("giveback") is not None]
    o = {"trades": n, "wins": w, "losses": lo, "win_pct": round(w * 100.0 / len(nets), 1) if nets else None, "net_usdt": round(sum(nets), 3),
         "avg_net_usdt": round(sum(nets) / len(nets), 4) if nets else None, "avg_hold": fmt_dur(sum(holds) / len(holds)) if holds else "n/a",
         "avg_mfe_roi_pct": round(sum(mfe) / len(mfe), 2) if mfe else None, "avg_giveback_roi_pct": round(sum(gb) / len(gb), 2) if gb else None}
    if n < MIN_N:
        o["label"] = "NOT ENOUGH DATA"
    return o


def counts_block(rows):
    """Question 1: how many trades on 3m / 5m / 15m, Main vs Sniper separate (+ Sniper lanes, exit kinds, per day)."""
    out = {}
    for g in GROUPS:
        gr = [r for r in rows if r["g"] == g]
        blk = {"all": stats(gr), "by_timeframe": {tf: stats([r for r in gr if r["tf"] == tf]) for tf in TFS + ("unknown",)},
               "exit_kinds": {k: sum(1 for r in gr if r["exit_b"] == k) for k in CATS["exit"]}}
        days = {utc_day(r["close"]) for r in gr if r["close"]}
        blk["active_days"] = len(days)
        blk["trades_per_active_day"] = round(len(gr) / len(days), 1) if days else None
        blk["first_close_utc"] = P.fmt_ts(min(r["close"] for r in gr if r["close"])) if any(r["close"] for r in gr) else None
        blk["last_close_utc"] = P.fmt_ts(max(r["close"] for r in gr if r["close"])) if any(r["close"] for r in gr) else None
        if g == "SNIPER":
            blk["by_lane"] = {ln: stats([r for r in gr if r["lane"] == ln]) for ln in ("REAL_GATE", "LEARN")}
        out[g] = blk
    return out


def tables_block(rows):
    """Every entry number as buckets: trades, wins, net per bucket, Main and Sniper separate."""
    out = {}
    for g in GROUPS:
        gr, blk = [r for r in rows if r["g"] == g], {}
        for tname, key in TABLES:
            names = EDGES[tname][1] if tname in EDGES else CATS[tname]
            blk[tname] = {nm: stats([r for r in gr if r.get(key) == nm]) for nm in names if any(r.get(key) == nm for r in gr)}
            na = [r for r in gr if r.get(key) in (None, "n/a")]
            if na and key != "exit_b":
                blk[tname]["n/a"] = {"trades": len(na)}
        out[g] = blk
    return out


def build_report(root, fee_roi=1.0, use_candles=True):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "min_trades_per_bucket": MIN_N, "day_start": "00:00 UTC = 5:30 AM IST"}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    trades, st = load_trades(root)
    rep["sources"] = st
    rows = [label_trade(t, fee_roi) for t in trades]
    live = [r for r in rows if r["box"] and not str(r["box"]).startswith("paper")]
    paper = [r for r in rows if not (r["box"] and not str(r["box"]).startswith("paper"))]
    rep["rows_total"], rep["live_rows_not_studied"] = len(rows), len(live)
    add_nth(paper)
    cov = {"with_numbers": 0, "no_candles": 0, "warmup": 0, "no_entry_time": 0, "no_timeframe": 0, "no_side": 0, "skipped_live": 0, "candles_used": False}
    con = F.open_ro(root) if use_candles else None
    if con is not None:
        cov["candles_used"] = True
        cfg_by_tf = {}
        for tf in TFS:
            try:
                cfg_by_tf[tf] = IP.load_cfg(root, "15m" if tf == "15m" else "5m")[0]
            except Exception:
                cfg_by_tf[tf] = dict(E.DEFAULTS)
        try:
            entry_numbers(paper, con, load_cohort(con), cfg_by_tf, cov)
        finally:
            con.close()
    else:
        rep["note"] = "No candle store (or --no-candles): only counts and labels are made."
    rep["entry_number_coverage"] = cov
    rep["counts"] = counts_block(paper)
    rep["tables"] = tables_block(paper)
    rep["rows_file"] = {"name": ROWS_FILE, "rows": len(paper), "saved": F.write_json(root, ROWS_FILE, {"tool": VERSION, "made_utc": rep["made_utc"], "rows": paper})}
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades are studied.",
                    "Buckets only group numbers so they can be read. No bucket is a rule. Fewer than %d trades = NOT ENOUGH DATA." % MIN_N,
                    "nth trade of the day counts closed paper trades only; skipped signals (signals table) join in Part 2.",
                    "Top-10 = daily 00:00 UTC list of 5 gainers + 5 losers (cohort_official). A coin that entered the list later in the day shows 'not in top-10'.",
                    "Python Z-score vs Pine Z-score is still to be checked (README_FILTER). Z buckets are the engine Z."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 1: counts + labels + entry numbers + SD shape (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out", default="-")
    ap.add_argument("--fee-roi", type=float, default=1.0)
    ap.add_argument("--no-candles", action="store_true")
    a = ap.parse_args(argv)
    rep = build_report(I.find_data_dir(a.data), a.fee_roi, not a.no_candles)
    txt = json.dumps(rep, indent=1, ensure_ascii=False, default=str)
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
