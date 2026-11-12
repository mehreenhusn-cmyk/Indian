"""v2_f6d_amd_low.py - FILTER STUDY Part 13 (bot Part 13): the VIDEO'S FULL CHECKLIST, on PRICE candles and on Z-SCORE candles, with 3 exit ways (read-only).
Reuses 5A / 5C / 6B / 6C (all must be in the repo). Measures only. No rule, no setting, no order, no network. Hindsight replay of the bot's own paper trades: a candidate for a log test, not a rule.
Why: Part 6C showed the AMD pattern ALONE loses in TRAIN and TEST. The video itself says AMD alone is not enough. So here the WHOLE video checklist is tested, the signal candle is candle 3 (c1, c2 = the 2 candles before):
  EMA   price on the right side of the EMA50 (long: above, short: below)
  ZSMA  Z200 on the right side of its own SMA (Z-SMA 200 = average of the last Z200 values; needs 100+ values, 200 = the real one)
  PULL  price close to the EMA50 (LOW third of the distance, cut made on TRAIN only)
  AMD_P the owner's video AMD (c1 against the trade, c2 sweeps beyond c1, c3 with the trade, c1 open beyond c2 open) on the PRICE candles
  AMD_Z the same AMD pattern on the Z-SCORE CANDLES (the owner's lower indicator shows Z as candles: Z of open / high / low / close of each bar, same 200-bar window of closes)
  Short = mirror of long. SETS (each also says how much each check adds):  EMA+ZSMA | EMA+ZSMA+PULL | FULL_PRICE (+AMD_P) | FULL_Z (+AMD_Z) | FULL_BOTH (+AMD_P and AMD_Z)
3 EXIT WAYS, same trade, same fee:
  BOT    the bot's way now: 30% at TP1, the rest with a TRAIL_33 trail (stand-in for the real trail; TP1 never touched = the trade as it was)
  VIDEO  stop beyond the AMD sweep (c2 low for long, c2 high for short), 70% at 1:2 (2 x the stop distance), the last 30% with the TRAIL_33 trail. Stop and target in one candle = stop first (pessimistic). Neither = left at the end of the real trade.
  ENTRY  the 30% at TP1 as BOT, but after TP1 the stop moves to the entry price
JUDGED per set, exit and side (ALL / LONG / SHORT): average net per trade of the trades that PASS the set vs the rest, TRAIN (first 60% by time) and TEST (last 40%). HOLDS only when the set makes profit AND beats the rest in BOTH halves with 30+ trades in each half.
BEATS_REST_BUT_STILL_LOSES = better than the rest, still minus. TOO_FEW = under 30 trades in a half (the video is strict, this will often happen: Part 9 real data answers that). FAILS = no.
Main and Sniper are never added together. Only paper trades. Fewer than 60 replayed trades = NOT ENOUGH DATA.  Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f6d_amd_low.py --data /home/owl/owl_data --out -"""
import argparse
import bisect
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f5a_exits as A
import v2_f5c_booking as BK
import v2_f6b_entry as B

X, K, F, IP, E, I, P = A.X, A.K, A.F, A.IP, A.E, A.I, A.P

VERSION = "v2_f6d_amd_low 1 (Filter Part 13)"
ZN, ZSMA_MIN = 200, 100
MIN_HALF = 30
SETS = ("EMA+ZSMA", "EMA+ZSMA+PULL", "FULL_PRICE", "FULL_Z", "FULL_BOTH")
EXITS = ("BOT", "VIDEO", "ENTRY")
SIDES = (("ALL", None), ("LONG", 1), ("SHORT", -1))
_pre = {}


# ----------------------------------------------------------------------------- Z candles
def _prefix(S):
    """Prefix sums of the closes of one candle series (cached), for the O(1) rolling mean / SD."""
    k = id(S)
    if k not in _pre or _pre[k][0] is not S:     # the cache keeps S itself, so a freed series can never hand its id() (and its old sums) to a new one
        p1, p2, a, b = [0.0], [0.0], 0.0, 0.0
        for x in S["c"]:
            a += x
            b += x * x
            p1.append(a)
            p2.append(b)
        _pre.clear()
        _pre[k] = (S, p1, p2)
    return _pre[k][1], _pre[k][2]


def zcandle(S, j, n=ZN):
    """Z of open / high / low / close of bar j against the mean and SD of the last n closes up to bar j. -> (zo, zh, zl, zc) or None."""
    if j < 0 or j + 1 < n:
        return None
    p1, p2 = _prefix(S)
    if j + 1 >= len(p1):                           # bar j is not in this series
        return None
    m = (p1[j + 1] - p1[j + 1 - n]) / n
    sd = math.sqrt(max((p2[j + 1] - p2[j + 1 - n]) / n - m * m, 0.0))
    if sd <= 0:
        return None
    return tuple((S[k][j] - m) / sd for k in ("o", "h", "l", "c"))


def zsma_ok(S, i0, side):
    """Z200 of the close in the trade direction above the average of the last Z200 values. -> (bool or None, values used)."""
    lo, vals = max(ZN - 1, i0 - ZN + 1), []
    for j in range(lo, i0 + 1):
        zc = zcandle(S, j)
        if zc:
            vals.append(zc[3])
    if len(vals) < ZSMA_MIN:
        return None, len(vals)
    return side * (vals[-1] - sum(vals) / len(vals)) > 0, len(vals)


def amd_pattern(side, a, b, d):
    """a, b, d = (o, h, l, c) of c1, c2, c3. -> video AMD yes / no. Short is flipped (values and high / low swapped) and then read as long."""
    if side == -1:
        a, b, d = [(-x[0], -x[2], -x[1], -x[3]) for x in (a, b, d)]
    basic = a[3] < a[0] and b[2] < a[2] and d[3] > d[0]
    return bool(basic and a[0] > b[0])


def flags(S, i0, side):
    """All checks at the signal candle (c3). A value None = not computable (too little history)."""
    if i0 < 2:
        return None
    ema = S["ema_s"][i0]
    if not ema:
        return None
    c = S["c"][i0]
    f = {"ema": side * (c - ema) > 0, "dist": side * (c - ema) / ema * 100.0}
    f["zsma"], f["zsma_n"] = zsma_ok(S, i0, side)
    pc = [(S["o"][j], S["h"][j], S["l"][j], S["c"][j]) for j in (i0 - 2, i0 - 1, i0)]
    f["amd_p"] = amd_pattern(side, *pc)
    zc = [zcandle(S, j) for j in (i0 - 2, i0 - 1, i0)]
    f["amd_z"] = None if None in zc else amd_pattern(side, *zc)
    return f


# ----------------------------------------------------------------------------- exits
def video_exit(S, i0, end0, side, ep, fee_px):
    """Stop beyond the sweep candle, 70% at 1:2, 30% trail. -> (blended exit price, kind) or None when the stop is not on the right side of the entry."""
    stop = S["l"][i0 - 1] if side == 1 else S["h"][i0 - 1]
    risk = (ep - stop) * side
    if risk <= 0:
        return None
    tgt = ep + side * 2.0 * risk
    o, h, l = S["o"], S["h"], S["l"]
    for j in range(i0 + 1, end0 + 1):
        ps = A.hit_level(-side, o[j], h[j], l[j], stop)
        if ps is not None:                                           # stop first, also when the target is in the same candle
            return ps, "STOP"
        pt = A.hit_level(side, o[j], h[j], l[j], tgt)
        if pt is not None:
            p2, _j2 = A.simulate("TRAIL_33", S, j, end0, side, ep, fee_px, None, None, {})
            return 0.7 * pt + 0.3 * p2, "TARGET"
    return S["c"][end0], "OPEN"


def replay_trade(S, i0, end0, r):
    side, ep, lev, inv, fee = r["side"], r.get("entry_price"), r.get("lev"), r.get("invest"), r.get("fee_roi")
    if not (side and ep and lev and inv and fee is not None) or end0 <= i0:
        return None
    fl = flags(S, i0, side)
    if fl is None:
        return None
    y5 = BK.replay_trade(S, i0, end0, r)
    if y5 is None:
        return None
    if y5.get("tp1"):
        s = y5["s"]
        bot, ent = s["TRAIL_33|NONE|h0"]["n"][0], s["TRAIL_33|ENTRY|h0"]["n"][0]
    else:
        bot = ent = y5["calib"]
    end = min(end0, i0 + 1 + A.MAX_BARS)
    ve = video_exit(S, i0, end, side, ep, fee / lev)
    nets = {"BOT": round(bot, 4), "ENTRY": round(ent, 4), "VIDEO": None if ve is None else round(A.money(side, ep, ve[0], lev, fee, inv), 4)}
    return {"nets": nets, "video_kind": None if ve is None else ve[1]}, fl


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
            res = replay_trade(S, i0, end0, r)
            if res is None:
                cov["no_money_numbers"] += 1
                continue
            r["y"], r["fl"] = res
            cov["replayed"] += 1


# ----------------------------------------------------------------------------- judging
def member(r, name, cut):
    """True / False / None (not computable) for one trade and one set."""
    f = r["fl"]
    parts = [f["ema"], f["zsma"]]
    if name != "EMA+ZSMA":
        parts.append(None if f["dist"] is None or cut is None else f["dist"] < cut)
    if name in ("FULL_PRICE", "FULL_BOTH"):
        parts.append(f["amd_p"])
    if name in ("FULL_Z", "FULL_BOTH"):
        parts.append(f["amd_z"])
    if any(p is None for p in parts):
        return None
    return all(parts)


def stat(rs, ex):
    v = [r["y"]["nets"][ex] for r in rs if r["y"]["nets"][ex] is not None]
    return {"n": len(v), "net": round(sum(v), 2), "avg": round(sum(v) / len(v), 3) if v else None}


def verdict(a, b, ra, rb):
    if min(a["n"], b["n"]) < MIN_HALF:
        return "TOO_FEW"
    if ra["avg"] is None or rb["avg"] is None:
        return "TOO_FEW"
    beats = a["avg"] > ra["avg"] and b["avg"] > rb["avg"]
    if beats and a["avg"] > 0 and b["avg"] > 0:
        return "HOLDS"
    return "BEATS_REST_BUT_STILL_LOSES" if beats else "FAILS"


def set_block(tr, te, cut, name, sd):
    def sel(rs):
        rs = [r for r in rs if sd is None or r["side"] == sd]
        yes, no = [], []
        for r in rs:
            m = member(r, name, cut)
            if m is True:
                yes.append(r)
            elif m is False:
                no.append(r)
        return yes, no
    ytr, ntr = sel(tr)
    yte, nte = sel(te)
    out = {"trades_train": len(ytr), "trades_test": len(yte)}
    for ex in EXITS:
        a, b, ra, rb = stat(ytr, ex), stat(yte, ex), stat(ntr, ex), stat(nte, ex)
        out[ex] = {"train": a, "test": b, "rest_train_avg": ra["avg"], "rest_test_avg": rb["avg"], "verdict": verdict(a, b, ra, rb)}
    return out


def scope_report(rs):
    if len(rs) < A.MIN_SCOPE:
        return {"label": "NOT ENOUGH DATA", "replayed_trades": len(rs), "need": A.MIN_SCOPE}
    tr, te, cut = A.split_rows(rs)
    dcut = B.tertile_cuts([r["fl"]["dist"] for r in tr if r["fl"]["dist"] is not None])[0]
    out = {"replayed_trades": len(rs), "split_utc": P.fmt_ts(cut), "pull_cut_low_third_dist_pct": dcut,
           "with_zsma_pct": round(100.0 * sum(1 for r in rs if r["fl"]["zsma"] is not None) / len(rs), 1),
           "with_zcandles_pct": round(100.0 * sum(1 for r in rs if r["fl"]["amd_z"] is not None) / len(rs), 1)}
    holds = []
    for sn, sd in SIDES:
        blk = {}
        for name in SETS:
            blk[name] = set_block(tr, te, dcut, name, sd)
            for ex in EXITS:
                if blk[name][ex]["verdict"] == "HOLDS":
                    holds.append("%s %s %s" % (sn, name, ex))
        out[sn] = blk
    out["holds"] = holds
    out["how_to_read"] = "Per set and exit: average net per trade of the trades that pass vs the rest, TRAIN and TEST. HOLDS needs profit AND beating the rest in BOTH halves with 30+ trades in each. TOO_FEW is common for the strict sets."
    return out


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST", "sets": list(SETS), "exits": list(EXITS)}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    src = K.load_rows(root)
    if not src or not src.get("rows"):
        X.build_report(root, fee_roi)
        src = K.load_rows(root)
    rows, dropped = K.prepare((src or {}).get("rows") or [])
    cov = {"replayed": 0, "no_candles": 0, "warmup": 0, "no_entry_close_side_tf": 0, "no_money_numbers": 0, "candles_used": False}
    con = F.open_ro(root)
    if con is None:
        rep["error"] = "No candle store (v2_market.db): needed for the video checklist test."
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
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades. Hindsight replay.",
                    "Candle 3 = the signal candle. Entry price = the bot's real entry (the video enters at the close of candle 3, nearly the same).",
                    "Z candles = Z of open / high / low / close of each bar vs the last 200 closes. Z-SMA needs 100+ Z values (200 = the real one).",
                    "BOT exit uses TRAIL_33 as a stand-in for the bot's real trail. TOO_FEW is an honest answer: Part 9 real data decides."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 13: the video's full checklist on price and Z candles (read-only)")
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
