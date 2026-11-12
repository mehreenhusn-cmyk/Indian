"""v2_f13_week.py - FILTER STUDY Part 15 (bot Part 15): the WEEK TEST on REAL joined data (read-only). Measures only. No rule, no setting, no order, no network.
Reads v2_f12_join.jsonl (Part 11: every closed paper trade of the current bot WITH the state numbers the bot saw at the signal and the real net WITH the TP1 booking). No candle replay: the numbers are what the bot really saw, the result is what really happened.
Only trades with a snapshot are used. TRAIN = first 60% by time, TEST = last 40%. Scopes: all timeframes, then 3m / 5m / 15m alone, then LONG / SHORT alone.
WINNERS vs LOSERS: median of every state number for trades that ended plus vs minus (and for the big winners = top quarter by net).
PART 17C adds: price on the right side of EMA50 (p_ok), lower-pane Z candle on the right side of ITS EMA50 (l_ok), both (p_ok and l_ok), the gainer / loser list tag (WITH / AGAINST / not in top-10), and an EMA GATE VIEW (per gate: trades per day kept, net kept, blocked, loss avoided, profit missed, net gain, train and test) on REAL data.\nBUCKETS (real net per bucket, TRAIN and TEST): z100 / z200 / z_vs_sma / run / dist / slope / width in thirds (cuts made on TRAIN only), Z SPIKE (none, 0-6, 7-24, 25-48 bars ago), AMD basic / reclaim / video, session, side, timeframe.
FLAG = LOSER / WINNER only when the net has the same sign in BOTH halves and both halves have 30+ trades (same rule as Part 6B). MIXED = signs differ. TOO_FEW = under 30 in a half.
LUCK CHECK: with many buckets some flags appear by pure chance (both halves same sign is a coin flip). The report counts the eligible buckets and the flags found; flags found close to half of the eligible buckets = nothing proven.
DAYS: under 7 days saved = EARLY_LOOK (a look, not a test). Under 60 trades = NOT ENOUGH DATA. Part 9 / 10 / 11 must have run for the numbers to exist (snapshot + join).
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f13_week.py --data /home/owl/owl_data --out -"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f5a_exits as A
import v2_f6b_entry as B
import v2_f12_join as J

I, P = A.I, A.P

VERSION = "v2_f13_week 2 (Filter Part 15 + 17C)"
MIN_ROWS, MIN_DAYS = 60, 7
NUM = ("z100", "z200", "z_vs_sma", "run", "dist", "slope", "width")
SPIKE_B = ("none", "0-6", "7-24", "25-48")
LIST_B = ("WITH list", "AGAINST list", "not in top-10", "n/a")
SCOPES = (("all", None, None), ("3m", "tf", "3m"), ("5m", "tf", "5m"), ("15m", "tf", "15m"), ("LONG", "side", 1), ("SHORT", "side", -1))


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def med(v):
    v = sorted(x for x in v if x is not None)
    return None if not v else round(v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2.0, 3)


def spike_of(r):
    a = r.get("spike_ago")
    return "none" if a is None else ("0-6" if a <= 6 else ("7-24" if a <= 24 else "25-48"))


def yn(key):
    return lambda r: "n/a" if r.get(key) is None else ("yes" if r.get(key) else "no")


def tert_fn(cuts, key):
    lo, hi = cuts

    def fn(r):
        v = num(r.get(key))
        return "n/a" if v is None or lo is None else ("LOW" if v < lo else ("MID" if v < hi else "HIGH"))
    return fn


def state_profile(rs):
    """Median of every state number: all trades, winners (net > 0), losers (net <= 0), big winners (top quarter by net)."""
    srt = sorted(rs, key=lambda r: r["net"], reverse=True)
    groups = {"all": rs, "winners": [r for r in rs if r["net"] > 0], "losers": [r for r in rs if r["net"] <= 0], "big_winners_top_quarter": srt[:max(1, len(srt) // 4)]}
    out = {}
    for name, g in groups.items():
        out[name] = dict({"trades": len(g), "net_usdt": round(sum(r["net"] for r in g), 2)}, **{k: med([num(r.get(k)) for r in g]) for k in NUM})
    return out


def both_ok(r):
    p, l = r.get("p_ok"), r.get("l_ok")
    return "n/a" if p is None or l is None else ("yes" if p and l else "no")


def gate_view(rs, tr, te):
    """Part 17C: the owner's questions for each EMA50 gate on REAL trades: kept per day, kept net, blocked, loss avoided (blocked losers), profit missed (blocked winners), net gain = avoided - missed. Gate fails when the value is False (no)."""
    def one(g, fn):
        kept = [r for r in g if fn(r) == "yes"]
        blk = [r for r in g if fn(r) == "no"]
        if not kept and not blk:
            return {"kept": 0, "blocked": 0}
        avoided = -sum(r["net"] for r in blk if r["net"] < 0)
        missed = sum(r["net"] for r in blk if r["net"] > 0)
        days = max(1, len({r.get("day") for r in g if r.get("day") is not None}))
        return {"kept": len(kept), "kept_per_day": round(len(kept) / days, 1), "kept_net": round(sum(r["net"] for r in kept), 2), "blocked": len(blk), "blocked_net": round(sum(r["net"] for r in blk), 2),
                "loss_avoided": round(avoided, 2), "profit_missed": round(missed, 2), "net_gain": round(avoided - missed, 2)}
    out = {}
    for name, fn in (("P_price", yn("p_ok")), ("L_lower", yn("l_ok")), ("P+L_both", both_ok)):
        v = {"all": one(rs, fn), "train": one(tr, fn), "test": one(te, fn)}
        ok = all(v[k].get("blocked", 0) >= 30 and v[k].get("kept", 0) >= 30 and v[k].get("net_gain", 0) > 0 for k in ("train", "test"))
        v["verdict"] = "CANDIDATE_FOR_LOG_TEST" if ok else "NOT_PROVEN"
        out[name] = v
    return out


def scope_report(rs):
    if len(rs) < MIN_ROWS:
        return {"label": "NOT ENOUGH DATA", "trades": len(rs), "need": MIN_ROWS}
    tr, te, cut = A.split_rows(rs)
    tables = {}
    for k in NUM:
        cuts = B.tertile_cuts([num(r.get(k)) for r in tr])
        tables[k] = {"cuts_from_train": cuts, "buckets": B.bucket_table(tr, te, tert_fn(cuts, k), ("LOW", "MID", "HIGH", "n/a"))}
    tables["z_spike"] = B.bucket_table(tr, te, spike_of, SPIKE_B)
    for k in ("amd_basic", "amd_reclaim", "amd_video"):
        tables[k] = B.bucket_table(tr, te, yn(k), ("yes", "no", "n/a"))
    tables["price_ok_EMA50"] = B.bucket_table(tr, te, yn("p_ok"), ("yes", "no", "n/a"))
    tables["lower_ok_EMA50"] = B.bucket_table(tr, te, yn("l_ok"), ("yes", "no", "n/a"))
    tables["both_ok_EMA50"] = B.bucket_table(tr, te, both_ok, ("yes", "no", "n/a"))
    tables["gainer_loser_list"] = B.bucket_table(tr, te, lambda r: str(r.get("list_b") or "n/a"), LIST_B)
    tables["session"] = B.bucket_table(tr, te, lambda r: str(r.get("session")), sorted({str(r.get("session")) for r in rs}))
    tables["side"] = B.bucket_table(tr, te, lambda r: str(r.get("side")), ("1", "-1"))
    tables["timeframe"] = B.bucket_table(tr, te, lambda r: str(r.get("tf")), ("3m", "5m", "15m"))
    eligible, flags = 0, []
    for name, t in tables.items():
        bk = t.get("buckets", t)
        for b, v in bk.items():
            if b == "n/a" or v["flag"] == "TOO_FEW":
                continue
            eligible += 1
            if v["flag"] in ("LOSER", "WINNER"):
                flags.append("%s=%s %s" % (name, b, v["flag"]))
    booked = [r for r in rs if r.get("booked")]
    rest = [r for r in rs if not r.get("booked")]
    return {"trades": len(rs), "split_utc": P.fmt_ts(cut), "net_usdt": round(sum(r["net"] for r in rs), 2), "win_pct": B.half(rs)["win_pct"], "train": B.half(tr), "test": B.half(te),
            "banked_at_tp1": {"trades": len(booked), "net_usdt": round(sum(r["net"] for r in booked), 2), "not_banked_trades": len(rest), "not_banked_net_usdt": round(sum(r["net"] for r in rest), 2)},
            "state_profile": state_profile(rs), "ema_gate_view": gate_view(rs, tr, te), "tables": tables,
            "luck_check": {"eligible_buckets": eligible, "flags_found": len(flags), "expected_by_luck_about": round(eligible / 2.0, 1), "flags": flags,
                           "read": "Flags found close to half of the eligible buckets = nothing proven. Only a flag that also stays in the next week is worth a log test."}}


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST", "source": J.JOIN_FILE}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    allr = J.read_all(root)
    legacy = sum(1 for r in allr if r.get("g") is None)
    rows = [r for r in allr if r.get("g") == "MAIN" and r.get("snap") and num(r.get("net")) is not None and num(r.get("ent")) is not None]
    days = sorted({r.get("day") for r in rows if r.get("day") is not None})
    rep.update({"join_lines": len(allr), "legacy_lines_without_group_left_out": legacy, "trades_with_snapshot": len(rows), "days": len(days), "first_day": J.day_text(days[0]) if days else None, "last_day": J.day_text(days[-1]) if days else None})
    rep["label"] = "NOT ENOUGH DATA" if len(rows) < MIN_ROWS else ("EARLY_LOOK (under %d days)" % MIN_DAYS if len(days) < MIN_DAYS else "WEEK_TEST")
    if not rows:
        rep["note"] = "No joined trades yet. Part 9 / 10 (snapshot) and Part 11 (join) must run for a few days first. Check the daily report: snapshots and JOIN line above 0."
        return rep
    short = sum(1 for r in rows if num(r.get("zsma_n")) is not None and r["zsma_n"] < 100)
    rep["trades_with_short_zsma"] = short
    for name, key, val in SCOPES:
        rep[name] = scope_report([r for r in rows if key is None or r.get(key) == val])
    rep["notes"] = ["REAL data: the numbers are what the bot saw at the signal, the net is the real paper result with the TP1 booking. No replay bias.",
                    "Under 7 days = EARLY_LOOK: a look, not a test. A flag counts only when TRAIN and TEST agree with 30+ trades each, and the luck check does not say 'nothing proven'.",
                    "MAIN bot only: Sniper trades are not in the join, and join lines without the group tag (written before this fix) are left out. Paper money only. A flag is a question for a LOG test (not a rule, no trade is stopped)."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 15: week test on real joined data (read-only)")
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
