"""v2_f5c_booking.py - FILTER STUDY Part 5C: SPLIT BOOKING LAB (read-only). Question 7 of README_FILTER (TP booking), second half.
Measures only. No rule, no setting, no order, no network. Reuses the replay engine of Part 5A (v2_f5a_exits.py), so 5A and Part 1 + 2 files must be in the repo.
WHY: Part 5A / 5B replay FULL exits only (one rule leaves with the whole position). The owner's real wish is different:
  (1) book a SMALL part at TP1 so the invested money comes back early and the trade cannot lose any more,
  (2) keep the BIG part running so a real rally is not cut (his indicator pays most in the long rally),
  (3) leave the big part with the exit rule that does not hurt the runners.
HOW IT WORKS: every PAPER trade is replayed candle by candle (same candles, same entry, same fee as 5A). If price touches TP1 inside the real trade:
  leg 1 = FRACTION of the position leaves at the TP1 price (fractions 30% / 50% / 70%).
  leg 2 = the rest leaves with ONE runner rule from the Part 5A set: TP4, TRAIL_25 / 33 / 50, CENTRE, EMA50, BAND2, OPPOSITE.
  Stop variants for leg 2: NONE (the same as 5A) or ENTRY (after TP1 the stop moves to the entry price; same candle = the stop first = pessimistic).
  If TP1 is never touched the trade is left as it really was (CALIB = close of the real closing candle, same as 5A).
  Money: the fee of the round trip is the same, only the exit price is blended (fraction x leg 1 price + rest x leg 2 price).
  Horizons: H0 = leg 2 ends when the real trade ended; H1 = leg 2 may run 24 candles longer (2 h on 5m).
NUMBERS per scheme and scope (Main / Sniper separate, ALL timeframes and 5m only): net USDT, change vs CALIB in TRAIN (first 60%) and TEST (last 40%, time-ordered), trades changed,
  change on RUNNERS (top quarter by best ROI) and on the REST, and MONEY LOCKED = average hours the invested money stayed in the trade (CALIB vs scheme). Lower = money free sooner.
VERDICT (same words as 5A): BETTER = gain in both halves and runners not hurt in either half. TRADEOFF = gain but runners lose. UNSTABLE = one half only. WORSE = no gain. TOO_FEW = under 10 changed trades in a half.
TOP 5 are chosen on TRAIN only (runners not hurt in TRAIN) and judged on TEST. About 96 schemes are looked at per scope, so some look good by luck: a BETTER here is a candidate for a live test, not a rule.
Honest limits: hindsight replay, fills are assumed at the level (no slippage); the fee of a partial close is assumed to be the same total fee; TP2 / TP3 are not in the saved rows, so only TP1 is used as the booking level.
Writes nothing in the data folder except the summary file given by --out (the Part 8A runner passes it). Day = 00:00 UTC = 5:30 AM IST. Durations over 60 min are written as hours + minutes.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f5c_booking.py --data /home/owl/owl_data --out -"""
import argparse
import bisect
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f5a_exits as A

X, K, F, IP, E, I, P = A.X, A.K, A.F, A.IP, A.E, A.I, A.P

VERSION = "v2_f5c_booking 1 (Filter Part 5C)"
FRACS = (0.3, 0.5, 0.7)
RUNNERS = ("TP4", "TRAIL_25", "TRAIL_33", "TRAIL_50", "CENTRE", "EMA50", "BAND2", "OPPOSITE")
STOPS = ("NONE", "ENTRY")
TF_MIN = {"3m": 3, "5m": 5, "15m": 15}


# ----------------------------------------------------------------------------- replay of ONE trade
def tp1_bar(S, i0, end0, side, tp1):
    """First bar after the signal candle, inside the real trade, where TP1 is touched. -> (fill price, bar) or (None, None)."""
    if not tp1:
        return None, None
    for j in range(i0 + 1, end0 + 1):
        px = A.hit_level(side, S["o"][j], S["h"][j], S["l"][j], tp1)
        if px is not None:
            return px, j
    return None, None


def entry_stop_bar(S, j1, end, side, ep):
    """First bar after the TP1 bar where price comes back to the entry price (stop moved to entry). -> (fill price, bar) or (None, None)."""
    for j in range(j1 + 1, end + 1):
        px = A.hit_level(-side, S["o"][j], S["h"][j], S["l"][j], ep)
        if px is not None:
            return px, j
    return None, None


def replay_trade(S, i0, end0, r):
    """Every runner rule x stop x horizon x fraction for one trade row. -> dict or None. y['tp1'] False = TP1 never touched = trade left as it was."""
    side, ep, lev, inv, fee = r["side"], r.get("entry_price"), r.get("lev"), r.get("invest"), r.get("fee_roi")
    if not (side and ep and lev and inv and fee is not None) or end0 <= i0:
        return None
    fee_px = fee / lev
    end1 = min(len(S["t"]) - 1, end0 + A.EXTRA_BARS, i0 + 1 + A.MAX_BARS)
    end0 = min(end0, end1)
    out = {"calib": round(A.money(side, ep, S["c"][end0], lev, fee, inv), 4), "bars": end0 - i0, "tp1": False}
    px1, j1 = tp1_bar(S, i0, end0, side, r.get("tp1"))
    if j1 is None:
        return out
    out["tp1"], out["k1"], out["s"] = True, j1 - i0, {}
    raw = {}
    for hz, end in (("h0", end0), ("h1", end1)):
        ps, js = entry_stop_bar(S, j1, end, side, ep)
        for rule in RUNNERS:
            px2, j2 = A.simulate(rule, S, j1, end, side, ep, fee_px, r.get("tp1"), r.get("tp4"), raw)
            for stop in STOPS:
                q2, k2 = (ps, js) if (stop == "ENTRY" and js is not None and js <= j2) else (px2, j2)
                nets = [round(A.money(side, ep, f * px1 + (1.0 - f) * q2, lev, fee, inv), 4) for f in FRACS]
                out["s"]["%s|%s|%s" % (rule, stop, hz)] = {"n": nets, "k": k2 - i0}
    return out


def replay_all(rows, con, cfg_by_tf, cov):
    """Fills r['y'] for every paper trade that has candles around its entry and its close (same loading as Part 5A)."""
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
            r["y"] = y
            cov["replayed"] += 1


# ----------------------------------------------------------------------------- report
def scheme_delta(rs, key, fi):
    """Change vs CALIB for a list of replayed rows: (sum of change, trades changed). Trades without a TP1 touch are unchanged."""
    tot, n = 0.0, 0
    for r in rs:
        y = r["y"]
        if not y["tp1"]:
            continue
        d = y["s"][key]["n"][fi] - y["calib"]
        tot += d
        n += 1 if abs(d) > 1e-9 else 0
    return round(tot, 3), n


def locked_hours(rs, key, f):
    """Average hours the invested money stayed in the trade: (scheme, CALIB). Leg 1 leaves at the TP1 bar, leg 2 at its own bar."""
    s = c = 0.0
    for r in rs:
        y, step = r["y"], TF_MIN.get(r["tf"], 5) / 60.0
        c += y["bars"] * step
        s += ((f * y["k1"] + (1.0 - f) * y["s"][key]["k"]) if y["tp1"] else y["bars"]) * step
    return round(s / len(rs), 2), round(c / len(rs), 2)


def verdict(a, b, ru):
    if a[1] < A.MIN_CHANGED or b[1] < A.MIN_CHANGED:
        return "TOO_FEW"
    if a[0] > 0 and b[0] > 0:
        return "BETTER" if ru[0] >= 0 and ru[1] >= 0 else "TRADEOFF"
    return "UNSTABLE" if (a[0] > 0 or b[0] > 0) else "WORSE"


def scope_report(rs):
    if len(rs) < A.MIN_SCOPE:
        return {"label": "NOT ENOUGH DATA", "replayed_trades": len(rs), "need": A.MIN_SCOPE}
    mfes = sorted(r["mfe"] for r in rs if r.get("mfe") is not None)
    rcut = mfes[int(len(mfes) * 0.75)] if mfes else float("inf")
    tr, te, cut = A.split_rows(rs)
    is_run = lambda r: r.get("mfe") is not None and r["mfe"] >= rcut
    rtr, rte = [r for r in tr if is_run(r)], [r for r in te if is_run(r)]
    qtr, qte = [r for r in tr if not is_run(r)], [r for r in te if not is_run(r)]
    calib_net, touched = sum(r["y"]["calib"] for r in rs), sum(1 for r in rs if r["y"]["tp1"])
    schemes = {}
    for hz in ("h0", "h1"):
        for rule in RUNNERS:
            for stop in STOPS:
                key = "%s|%s|%s" % (rule, stop, hz)
                for fi, f in enumerate(FRACS):
                    a, b = scheme_delta(tr, key, fi), scheme_delta(te, key, fi)
                    ru = (scheme_delta(rtr, key, fi)[0], scheme_delta(rte, key, fi)[0])
                    rest = (scheme_delta(qtr, key, fi)[0], scheme_delta(qte, key, fi)[0])
                    lk, lc = locked_hours(rs, key, f)
                    name = "%d%% at TP1 + %s%s %s" % (int(f * 100), rule, " (stop to entry)" if stop == "ENTRY" else "", hz.upper())
                    schemes[name] = {"verdict": verdict(a, b, ru), "net_usdt": round(calib_net + scheme_delta(rs, key, fi)[0], 3), "change_train": a[0], "change_test": b[0],
                                     "changed_train_test": [a[1], b[1]], "runners_change_train_test": list(ru), "rest_change_train_test": list(rest), "money_locked_hours": lk, "calib_locked_hours": lc}
    ok = [(n, s) for n, s in schemes.items() if s["changed_train_test"][0] >= A.MIN_CHANGED and s["runners_change_train_test"][0] >= 0]
    top = [dict(scheme=n, **s) for n, s in sorted(ok, key=lambda t: -t[1]["change_train"])[:5]]
    return {"replayed_trades": len(rs), "tp1_touched_trades": touched, "split_utc": P.fmt_ts(cut), "calib_net_usdt": round(calib_net, 3),
            "runner_definition": "best ROI at or above %.2f%% (top quarter of this scope)" % rcut,
            "top5_chosen_on_train_judged_on_test": top, "schemes": schemes,
            "how_to_read": "change_* = USDT gained or lost vs leaving as the real trade did (CALIB). money_locked_hours = how long the invested money stayed in, lower is freer. A scheme is only a candidate when verdict = BETTER."}


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST", "min_changed_trades_per_half": A.MIN_CHANGED,
           "fractions": [int(f * 100) for f in FRACS], "runner_rules": list(RUNNERS), "stops": list(STOPS),
           "horizons": "H0 = leg 2 ends when the real trade ended, H1 = %d candles longer (2 h on 5m, 6 h on 15m)" % A.EXTRA_BARS}
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
        rep["error"] = "No candle store (v2_market.db): the booking lab needs candles."
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
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades.", "Every scheme is compared with CALIB (same entry, exit at the real closing candle). Replay is hindsight: fills are assumed at the level.",
                    "Only TP1 is used as the booking level (TP2 / TP3 are not in the saved rows). Only a BETTER verdict in BOTH halves is worth a live LOG test (Part 7 style: off, log, block).",
                    "Python Z vs Pine Z is still unchecked (README_FILTER), so band numbers are the engine Z."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 5C: split booking lab (read-only)")
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
