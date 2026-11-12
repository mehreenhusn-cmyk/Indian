"""v2_f10_daily.py - FILTER STUDY Part 8C + Part 10 (bot Part 8 / 10): DAILY REPORT, new bot vs old bot (read-only, light: no candles, no network).
Reads the closed paper trades of the current bot (box paper_b1, source not live) and the US-session log of bot Part 4 (v2_f9_session_log.jsonl).
Day = 00:00 UTC = 5:30 AM IST. Per day (last 14 days): trades, win %, net USDT, how they closed (TP / SL / other), trades that BANKED at TP1 (Part 5A) vs trades that did not,
and the trades opened inside the US window (default 16-24 UTC = 21:30-05:30 IST) with their real net = what the session gate would have saved.
NEW vs OLD: NEW = trades opened at or after the first booking (the first trade that carries booked_ts), OLD = trades opened in the 7 days before that. Compared per day (trades/day, win %, net/day).
PART 10: REAL-DATA SPIKE CHECK. Each closed paper trade is matched to its Part 9 / 10 snapshot (same coin, side and timeframe, snapshot written up to 10 min before the trade opened). Net is then shown by Z spike bucket (0-6 / 7-24 / 25-48 candles ago / none) and, per timeframe, spike vs no-spike. Trades with no snapshot, or a snapshot that saw fewer than 49 candles of Z, are counted as 'unknown' and never mixed in. Read-only, log only, no trade is stopped.
HONEST LIMITS: booking changes the P&L of a trade, so NEW and OLD are not the same kind of number. A few days is luck, not proof: look at 7 days at least, better 3-4 weeks. Paper money only.
The file prints a short text (key 'text') you can read in the app Share report. Run by hand:  python3 v2_f10_daily.py --data /home/owl/owl_data --text"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f1_counts as X
import v2_inventory as I
import v2_money_hour as M
import v2_pnl as P

VERSION = "v2_f10_daily 2 (Filter Part 10)"
DAYS = 14
DAY = 86400
SESSION_LOG = "v2_f9_session_log.jsonl"
SNAP_LOG = "v2_f11_snap.jsonl"


def window_utc(root):
    """(a, b) UTC hours of the US window from the session gate file, else 16-24."""
    try:
        import v2_f9_session as S
        return S.window()
    except Exception:
        return 16, 24


def in_window(hour, a, b):
    return (a <= hour < b) if a < b else (hour >= a or hour < b)


def day_of(ts):
    return int(ts // DAY)


def day_text(d):
    return time.strftime("%d %b", time.gmtime(d * DAY))


def box(rs):
    n = len(rs)
    w = sum(1 for r in rs if r["net"] > 0)
    tp = sum(1 for r in rs if r["exit_b"] == "TP")
    sl = sum(1 for r in rs if r["exit_b"] == "SL")
    return {"trades": n, "win_pct": round(100.0 * w / n, 1) if n else None, "net_usdt": round(sum(r["net"] for r in rs), 2), "tp": tp, "sl": sl, "other": n - tp - sl}


def per_day(rs):
    days = {}
    for r in rs:
        days.setdefault(day_of(r["ent"]), []).append(r)
    n = len(days)
    t = sum(len(v) for v in days.values())
    w = sum(1 for r in rs if r["net"] > 0)
    return {"days": n, "trades_per_day": round(t / n, 1) if n else None, "win_pct": round(100.0 * w / t, 1) if t else None, "net_per_day": round(sum(r["net"] for r in rs) / n, 2) if n else None}


def session_log(root, since, name=SESSION_LOG):
    """Counts of log lines per day (entries that fell in the window while the gate only logged; also used for the Part 9 snapshots)."""
    out = {}
    try:
        with open(os.path.join(root, name), "r", encoding="utf-8") as f:
            for line in f:
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if x.get("t") and x["t"] >= since:
                    out[day_of(x["t"])] = out.get(day_of(x["t"]), 0) + 1
    except OSError:
        pass
    return out


def load_snaps(root, since):
    """Snapshots since a time -> {(sym, side text, tf): [(t, snap), ...]} sorted by time."""
    out = {}
    try:
        with open(os.path.join(root, SNAP_LOG), "r", encoding="utf-8") as f:
            for line in f:
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if x.get("t") and x["t"] >= since:
                    out.setdefault((x.get("sym"), x.get("side"), x.get("tf")), []).append((x["t"], x))
    except OSError:
        pass
    for v in out.values():
        v.sort(key=lambda a: a[0])
    return out


def spike_bucket(snap):
    """'0-6' / '7-24' / '25-48' / 'none' / 'unknown' (no snapshot, or Z seen on fewer than 49 candles)."""
    if not snap or (snap.get("spike_bars") or 0) < 49:
        return "unknown"
    k = snap.get("spike_ago")
    return "none" if k is None else ("0-6" if k <= 6 else "7-24" if k <= 24 else "25-48")


def spike_report(rows, snaps):
    """Real-data check: net of closed paper trades by Z spike bucket (from the snapshot taken when the signal fired)."""
    first = min((v[0][0] for v in snaps.values()), default=None)
    got, by, by_tf = 0, {}, {}
    for r in rows:
        if first is None or r["ent"] < first:
            continue
        best = None
        for t, sn in snaps.get((r["sym"], "LONG" if r["side"] == 1 else "SHORT", r["tf"]), ()):
            if -120 <= r["ent"] - t <= 600 and (best is None or abs(r["ent"] - t) < abs(r["ent"] - best[0])):
                best = (t, sn)
        b = spike_bucket(best[1] if best else None)
        got += b != "unknown"
        by.setdefault(b, []).append(r)
        if b != "unknown":
            by_tf.setdefault(r["tf"], {}).setdefault("none" if b == "none" else "spike", []).append(r)
    out = {"snapshots_first_utc": P.fmt_ts(first) if first else None, "trades_with_snapshot": got, "by_spike": {k: box(v) for k, v in sorted(by.items())},
           "by_timeframe": {tf: {k: box(v) for k, v in d.items()} for tf, d in sorted(by_tf.items())},
           "note": "Real entry, real booking. 'unknown' = no snapshot matched. Under 30 trades in a group = luck, not proof. Log only."}
    return out


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST"}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    raw, _st = X.load_trades(root)
    rows, sn_rows = [], []
    for t in raw:
        if t.get("_box") != "paper_b1" or str(t.get("id") or "").startswith("LIVE-"):
            continue
        net = M.net_fee_correct(t, fee_roi)
        ent, from_close = M.entry_ts(t)
        if net is None or not ent or from_close:
            continue
        if X.group_of(t) == "SNIPER":                 # Sniper trades sit in the same b1 book: counted SEPARATELY, never inside the Main numbers
            sn_rows.append((ent, net))
            continue
        rows.append({"ent": ent, "net": net, "exit_b": X.exit_kind(t.get("status")), "booked": bool(t.get("split_booked") or t.get("booked_frac")), "booked_ts": P.num(t, "booked_ts"), "sym": t.get("symbol"), "side": X.side_of(t), "tf": X.tf_of(t)})
    if not rows:
        rep["text"] = "No closed paper trades found."
        return rep
    now = time.time()
    a, b = window_utc(root)
    first_day = day_of(now) - DAYS + 1
    lines, days = [], {}
    for r in rows:
        d = day_of(r["ent"])
        if d >= first_day:
            days.setdefault(d, []).append(r)
    logs = session_log(root, first_day * DAY)
    snaps = session_log(root, first_day * DAY, SNAP_LOG)
    table = []
    for d in sorted(days):
        rs = days[d]
        us = [r for r in rs if in_window(time.gmtime(r["ent"]).tm_hour, a, b)]
        bk = [r for r in rs if r["booked"]]
        table.append({"day": day_text(d), "all": box(rs), "banked_at_tp1": box(bk), "not_banked": box([r for r in rs if not r["booked"]]), "us_window": box(us), "us_log_lines": logs.get(d, 0), "snapshots": snaps.get(d, 0)})
    rep["window_utc"] = "%d-%d" % (a, b)
    rep["days"] = table
    rep["snapshots_last_days"] = sum(snaps.values())
    cut = min((r["booked_ts"] for r in rows if r["booked_ts"]), default=None)
    if cut:
        new = [r for r in rows if r["ent"] >= cut]
        old = [r for r in rows if cut - 7 * DAY <= r["ent"] < cut]
        rep["new_vs_old"] = {"cutover_utc": P.fmt_ts(cut), "NEW_since_booking": dict(box(new), **per_day(new)), "OLD_7_days_before": dict(box(old), **per_day(old))}
    else:
        rep["new_vs_old"] = {"note": "no trade with booking yet"}
    us_all = [r for r in rows if r["ent"] >= first_day * DAY and in_window(time.gmtime(r["ent"]).tm_hour, a, b)]
    rep["us_window_last_%d_days" % DAYS] = dict(box(us_all), note="net of these = what the session gate would have saved (it only logs now)")
    sp = spike_report([r for r in rows if r["ent"] >= first_day * DAY], load_snaps(root, first_day * DAY))
    rep["spike_real"] = sp
    sn_d = [(e, n) for e, n in sn_rows if e >= first_day * DAY]
    rep["sniper_separate"] = {"trades": len(sn_d), "net_usdt": round(sum(n for _e, n in sn_d), 2), "days": DAYS, "note": "Sniper trades (source sniper / sniper_learn) are NOT inside any Main number of this report."}
    lines.append("DAILY REPORT (MAIN bot only, paper b1, day starts 5:30 IST)")
    for t in table[-7:]:
        al = t["all"]
        lines.append("%s: %d trades, win %s%%, net %+.1f | banked %d | US window %d trades, net %+.1f" % (t["day"], al["trades"], al["win_pct"], al["net_usdt"], t["banked_at_tp1"]["trades"], t["us_window"]["trades"], t["us_window"]["net_usdt"]))
    nv = rep["new_vs_old"]
    if "NEW_since_booking" in nv:
        n_, o_ = nv["NEW_since_booking"], nv["OLD_7_days_before"]
        lines.append("NEW: %s trades/day, win %s%%, net/day %s (%s days)" % (n_["trades_per_day"], n_["win_pct"], n_["net_per_day"], n_["days"]))
        lines.append("OLD: %s trades/day, win %s%%, net/day %s (%s days)" % (o_["trades_per_day"], o_["win_pct"], o_["net_per_day"], o_["days"]))
    sb = sp["by_spike"]
    lines.append("Z SPIKE on REAL trades (matched %d): " % sp["trades_with_snapshot"] + ("; ".join("%s: %d trades net %+.1f" % (k, v["trades"], v["net_usdt"]) for k, v in sb.items()) if sb else "no match yet") + (" | under 30 per group = luck" if sp["trades_with_snapshot"] < 60 else ""))
    lines.append("Part 9 snapshots (signals with state numbers) in the last %d days: %d" % (DAYS, sum(snaps.values())))
    lines.append("SNIPER (separate, not in the numbers above), last %d days: %d trades, net %+.1f" % (DAYS, len(sn_d), rep["sniper_separate"]["net_usdt"]))
    lines.append("Few days = luck. Look at 7+ days. Paper money only.")
    rep["text"] = "\n".join(lines)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 8C: daily report (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out", default="-")
    ap.add_argument("--text", action="store_true")
    ap.add_argument("--fee-roi", type=float, default=1.0)
    a = ap.parse_args(argv)
    rep = build_report(I.find_data_dir(a.data), a.fee_roi)
    if a.text:
        print(rep.get("text") or rep.get("error"))
        return 0
    txt = json.dumps(rep, indent=1, ensure_ascii=False, default=str)
    if a.out == "-":
        print(txt)
    else:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(txt)
        sys.stderr.write("Written: %s\n" % a.out)
    sys.stderr.write("Nothing was changed in trading.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
