"""v2_f2_fakes.py - FILTER STUDY Part 2: THE FAKE REPORT (read-only). Questions 2, 3, 4, 5 and 6 of README_FILTER. Main and Sniper always separate.
Measures only. No rule, no setting, no order, no network. Reads v2_filter_trades.json (Part 1 rows: labels + entry numbers). If that file is missing it runs Part 1 first (Part 1 is read-only too).
WHAT IS A "FAKE"? Made only from the trade's own numbers, no tuned cut-off:
  WIN        net result above zero (fee-correct, Part 1).
  GAVE_BACK  net loss, but the trade WAS good for a moment: its best ROI (mfe) was above the round-trip fee, so a net win was possible. Hindsight, nobody exits at the exact peak.
  FAKE       net loss and the best ROI never even covered the fee: the move never paid. (This is the "fake signal".)
  FLAT       net exactly zero.     LOSS_UNKNOWN: loss with no recorded best ROI or fee (counted, never guessed).
  fake % = FAKE / all judged trades.  loss % = (FAKE + GAVE_BACK) / all.
BLOCKS (per Main / Sniper):
  headline   fake / gave-back / win counts per timeframe.
  exits      per exit kind (SL, TP, OPPOSITE = opposite-signal exit, TIME, MANUAL): how many, how many fakes, net, average best ROI, hold time.   (Question 2)
  tables     fake % per bucket of every Part 1 number: Z zone, SD band shape, shape flips, setup status, % from day open (pump), candle size, wick, EMA50 distance, candles since cross,
             volume, TP vs fee, nth trade of the day, top-10 list side / rank, chop (regime_cross_n), side, timeframe.   (Questions 3, 5, 6)
  time       fake % per UTC hour (with the IST clock), per session (ASIA 00-08, EUROPE 08-16, US 16-24 UTC). Day starts 00:00 UTC = 5:30 AM IST.   (Question 4)
  before_win how many losing trades of the SAME coin on the SAME day come before the first winner (coin-days), and coin-days with no winner at all.   (Question 4)
  standouts  the buckets with the highest / lowest fake % (30+ trades), each with a STABLE check: same direction in the first 60% and the last 40% of the time. Facts, no rule.
Honest limits: this report tests about 150 buckets, so a few will look special by luck. A standout is a QUESTION for Part 4 (filter lab, train / test), never a rule. Fewer than 30 trades = NOT ENOUGH DATA.
Durations over 60 min are written as hours + minutes.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f2_fakes.py --data /home/owl/owl_data --out -"""
import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f1_counts as X
import v2_inventory as I
import v2_money_hour as M
import v2_pnl as P

VERSION = "v2_f2_fakes 1 (Filter Part 2)"
MIN_N = 30
HALF_MIN = 10                      # rows needed in each half for the STABLE check
KINDS = ("WIN", "GAVE_BACK", "FAKE", "FLAT", "LOSS_UNKNOWN")
CHOP = ("clean (< 3 crosses)", "choppy (3+ crosses)")
EXTRA = (("side", "side_b", ["LONG", "SHORT"]), ("timeframe", "tf", list(X.TFS)), ("chop", "chop_b", list(CHOP)))


def kind_of(r):
    net = r.get("net")
    if net is None:
        return None
    if net > 0:
        return "WIN"
    if net == 0:
        return "FLAT"
    mfe, fee = r.get("mfe"), r.get("fee_roi")
    if mfe is None or fee is None:
        return "LOSS_UNKNOWN"
    return "GAVE_BACK" if mfe > fee else "FAKE"


def prepare(rows):
    """Adds kind and the small helper buckets (side, chop, hour, session). Rows without a net result are dropped (counted)."""
    out, dropped = [], 0
    for r in rows:
        k = kind_of(r)
        if k is None:
            dropped += 1
            continue
        r["kind"] = k
        r["side_b"] = "LONG" if r.get("side") == 1 else ("SHORT" if r.get("side") == -1 else "n/a")
        rc = r.get("regime_cross_n")
        r["chop_b"] = "n/a" if rc is None else (CHOP[1] if rc >= 3 else CHOP[0])
        if r.get("ent") and not r.get("ent_from_close"):
            h = datetime.datetime.fromtimestamp(r["ent"], datetime.timezone.utc).hour
            r["hour"], r["session"] = h, M.session_of(h)
        else:
            r["hour"], r["session"] = None, None
        out.append(r)
    return out, dropped


def counts(rs):
    """Fake numbers of a list of rows."""
    n = len(rs)
    c = {k: sum(1 for r in rs if r["kind"] == k) for k in KINDS}
    out = {"trades": n, **{k.lower(): v for k, v in c.items() if v or k in ("WIN", "GAVE_BACK", "FAKE")}}
    out["fake_pct"] = round(c["FAKE"] * 100.0 / n, 1) if n else None
    out["loss_pct"] = round((c["FAKE"] + c["GAVE_BACK"]) * 100.0 / n, 1) if n else None
    out["win_pct"] = round(c["WIN"] * 100.0 / n, 1) if n else None
    out["net_usdt"] = round(sum(r["net"] for r in rs), 3)
    if n < MIN_N:
        out["label"] = "NOT ENOUGH DATA"
    return out


def avg(rs, key):
    v = [r[key] for r in rs if r.get(key) is not None]
    return round(sum(v) / len(v), 2) if v else None


def exits_block(rs):
    out = {}
    for k in X.CATS["exit"]:
        e = [r for r in rs if r["exit_b"] == k]
        if not e:
            continue
        h = [r["hold_min"] for r in e if r.get("hold_min") is not None]
        out[k] = dict(counts(e), avg_best_roi_pct=avg(e, "mfe"), avg_giveback_roi_pct=avg(e, "giveback"), avg_hold=X.fmt_dur(sum(h) / len(h)) if h else "n/a")
    return out


def headline(rs):
    return {"all": counts(rs), "by_timeframe": {tf: counts([r for r in rs if r["tf"] == tf]) for tf in X.TFS + ("unknown",) if any(r["tf"] == tf for r in rs)}}


def bucket_names(tname):
    return X.EDGES[tname][1] if tname in X.EDGES else X.CATS[tname]


def table_defs():
    """(title, row key, bucket names) for every table: the Part 1 numbers (not the exit kind) + side / timeframe / chop."""
    defs = [(t, k, bucket_names(t)) for t, k in X.TABLES if t != "exit"]
    return defs + list(EXTRA)


def tables_block(rs):
    out = {}
    for title, key, names in table_defs():
        blk = {nm: counts([r for r in rs if r.get(key) == nm]) for nm in names if any(r.get(key) == nm for r in rs)}
        na = sum(1 for r in rs if r.get(key) in (None, "n/a"))
        if na:
            blk["n/a"] = {"trades": na}
        out[title] = blk
    return out


def time_block(rs):
    t = [r for r in rs if r.get("hour") is not None]
    hours = {}
    for h in range(24):
        x = [r for r in t if r["hour"] == h]
        if x:
            hours["%02d UTC (%s IST)" % (h, M.ist_label(h))] = counts(x)
    sess = {nm: counts([r for r in t if r["session"] == nm]) for nm, _a, _b in M.SESSIONS if any(r["session"] == nm for r in t)}
    return {"trades_with_entry_time": len(t), "per_session": sess, "per_hour": hours}


def before_win(rs):
    """Losing trades of the same coin on the same UTC day before the first winner (coin-days with 2+ trades)."""
    days = {}
    for r in rs:
        if r.get("ent") and not r.get("ent_from_close"):
            days.setdefault((r["sym"], X.utc_day(r["ent"])), []).append(r)
    dist, with_win, no_win, lead_all, lead_fake = {"0": 0, "1": 0, "2": 0, "3+": 0}, 0, 0, [], []
    for seq in days.values():
        seq.sort(key=lambda r: r["ent"])
        first = next((i for i, r in enumerate(seq) if r["kind"] == "WIN"), None)
        if first is None:
            no_win += 1
            continue
        with_win += 1
        lead = seq[:first]
        lead_all.append(len(lead))
        lead_fake.append(sum(1 for r in lead if r["kind"] == "FAKE"))
        dist["3+" if len(lead) >= 3 else str(len(lead))] += 1
    n = with_win + no_win
    return {"coin_days": n, "coin_days_with_a_winner": with_win, "coin_days_with_no_winner": no_win,
            "losing_trades_before_first_winner": dist, "avg_losing_before_first_winner": round(sum(lead_all) / len(lead_all), 2) if lead_all else None,
            "avg_fakes_before_first_winner": round(sum(lead_fake) / len(lead_fake), 2) if lead_fake else None, **({"label": "NOT ENOUGH DATA"} if n < MIN_N else {})}


def fake_pct(rs):
    return sum(1 for r in rs if r["kind"] == "FAKE") * 100.0 / len(rs) if rs else None


def stable(all_rs, bucket_rs):
    """True / False / None: is the bucket's fake % above (or below) the overall fake % in BOTH the first 60% and the last 40% of the time?"""
    ts = sorted(r["ent"] for r in all_rs if r.get("ent"))
    if len(ts) < 2 * HALF_MIN:
        return None
    cut = ts[int(len(ts) * 0.6)]
    sides = []
    for part in (lambda r: r.get("ent") and r["ent"] < cut, lambda r: r.get("ent") and r["ent"] >= cut):
        a, b = [r for r in all_rs if part(r)], [r for r in bucket_rs if part(r)]
        if len(b) < HALF_MIN or not a:
            return None
        sides.append(fake_pct(b) - fake_pct(a))
    return (sides[0] > 0) == (sides[1] > 0) and all(abs(x) > 0.0 for x in sides)


def standouts(rs, tables):
    """Highest / lowest fake % buckets with 30+ trades, each with the STABLE check."""
    base, found, tested = fake_pct(rs), [], 0
    for title, key, names in table_defs():
        for nm in names:
            b = tables.get(title, {}).get(nm)
            if not b or b.get("trades", 0) < 1:
                continue
            tested += 1
            if b["trades"] < MIN_N:
                continue
            brs = [r for r in rs if r.get(key) == nm]
            found.append({"table": title, "bucket": nm, "trades": b["trades"], "fake_pct": b["fake_pct"], "vs_all_pts": round(b["fake_pct"] - base, 1), "win_pct": b["win_pct"],
                          "net_usdt": b["net_usdt"], "stable_both_halves": stable(rs, brs)})
    found.sort(key=lambda x: x["vs_all_pts"])
    return {"all_fake_pct": round(base, 1) if base is not None else None, "buckets_tested": tested, "buckets_with_30_plus": len(found),
            "lowest_fake_pct": found[:8], "highest_fake_pct": list(reversed(found[-8:])),
            "warning": "About %d buckets were looked at, so some look special by luck. Use these as questions for Part 4, not as rules." % tested}


def load_rows(root):
    try:
        with open(os.path.join(root, X.ROWS_FILE), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "min_trades_per_bucket": MIN_N, "day_start": "00:00 UTC = 5:30 AM IST",
           "fake_definition": "FAKE = net loss AND best ROI never covered the round-trip fee. GAVE_BACK = net loss but best ROI was above the fee. No tuned cut-off."}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    src = load_rows(root)
    if not src or not src.get("rows"):
        X.build_report(root, fee_roi)                       # Part 1 (read-only) writes v2_filter_trades.json
        rep["note"] = "v2_filter_trades.json was missing: Part 1 was run first."
        src = load_rows(root)
    rows = (src or {}).get("rows") or []
    rows, dropped = prepare(rows)
    rep["rows_used"], rep["rows_without_net_result"] = len(rows), dropped
    rep["rows_file_made_utc"] = (src or {}).get("made_utc")
    for g in X.GROUPS:
        rs = [r for r in rows if r["g"] == g]
        tb = tables_block(rs)
        rep[g] = {"headline": headline(rs), "exits": exits_block(rs), "time": time_block(rs), "before_first_winner": before_win(rs), "tables": tb, "standouts": standouts(rs, tb)}
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades.",
                    "A bucket only groups numbers so they can be read. Nothing here is a rule. Cut-offs and train / test checks are Part 4.",
                    "Rows come from the Part 1 file; if the trades changed since, run Part 1 again first.",
                    "Python Z vs Pine Z is still unchecked (README_FILTER), so Z buckets are the engine Z."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 2: the fake report (read-only)")
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
