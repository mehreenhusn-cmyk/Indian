"""v2_f12_join.py - FILTER STUDY Part 11 (bot Part 11): DAILY JOIN of the entry snapshot + the real trade result. Read-only for trading, light (no candles, no network).
Why: the snapshot log (v2_f11_snap.jsonl) is cut at 5 MB and the trade archives can be cleaned. This file copies every CLOSED paper trade of the current bot (b1, not LIVE-) together with its snapshot
into ONE file that only grows: v2_f12_join.jsonl (data folder). One line per trade (key = trade id + close time, written once, never changed, never deleted).
A line holds the result (net with booking, exit reason, booked at TP1 or not, booked part, entry / close time, timeframe, side) and the state numbers of the signal (z100, z200, z_vs_sma, spike, run, dist, slope, width, AMD flags, session, hour).
Match rule = the same as the daily report: same coin, side, timeframe; snapshot written from 120 s after to 10 min before the trade opened; the nearest one wins. Trades with no snapshot are saved too (snap = false) so the match rate stays honest.
Only trades that opened after the FIRST snapshot are kept (before that there is nothing to join). Run it every day (runner id f12j) or by hand:  python3 v2_f12_join.py --data /home/owl/owl_data --text
Part 15 reads this file: winners vs losers, spike, AMD, timeframe, train vs test, on REAL entries with booking. Few days = luck. Paper money only. Nothing here stops a trade."""
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

VERSION = "v2_f12_join 1 (Filter Part 11)"
JOIN_FILE = "v2_f12_join.jsonl"
SNAP_FILES = ("v2_f11_snap.jsonl.old", "v2_f11_snap.jsonl")       # old part first
DAY = 86400
KEEP = ("sig_id", "bar_t", "entry_price", "tp1", "tp4", "hour_utc", "session", "cross", "z100", "z200", "zsma", "zsma_n", "z_vs_sma", "run", "dist", "slope", "width",
        "amd_basic", "amd_reclaim", "amd_video", "spike_ago", "spike_max", "spike_bars", "dropped_forming")


def load_snaps(root):
    """All snapshots (old + current file) -> {(sym, side, tf): [(t, snap), ...]} sorted by time."""
    out = {}
    for name in SNAP_FILES:
        try:
            with open(os.path.join(root, name), "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        x = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(x, dict) and x.get("t"):
                        out.setdefault((x.get("sym"), x.get("side"), x.get("tf")), []).append((x["t"], x))
        except OSError:
            pass
    for v in out.values():
        v.sort(key=lambda a: a[0])
    return out


def match(snaps, sym, side, tf, ent):
    """Nearest snapshot of the same coin / side / timeframe, written 120 s after to 10 min before the trade opened. -> snap dict or None."""
    best = None
    for t, sn in snaps.get((sym, "LONG" if side == 1 else "SHORT", tf), ()):
        if -120 <= ent - t <= 600 and (best is None or abs(ent - t) < abs(ent - best[0])):
            best = (t, sn)
    return best[1] if best else None


def closed_rows(root, fee_roi, with_sniper=False):
    """Closed paper trades of b1 (same filter as the daily report) -> list of dicts."""
    raw, _st = X.load_trades(root)
    rows = []
    for t in raw:
        if t.get("_box") != "paper_b1" or str(t.get("id") or "").startswith("LIVE-"):
            continue
        net = M.net_fee_correct(t, fee_roi)
        ent, from_close = M.entry_ts(t)
        if net is None or not ent or from_close:
            continue
        g = X.group_of(t)
        if g == "SNIPER" and not with_sniper:         # the snapshot logger sees MAIN signals only; Sniper trades share the b1 book but never go into the join file
            continue
        rows.append({"key": P.tkey(t), "id": t.get("id"), "g": g, "sym": t.get("symbol"), "side": X.side_of(t), "tf": X.tf_of(t), "ent": ent, "close": P.num(t, "closed_at_ts"), "net": round(net, 4),
                     "exit": X.exit_kind(t.get("status")), "status": t.get("status"), "booked": bool(t.get("split_booked") or t.get("booked_frac")), "booked_frac": P.num(t, "booked_frac"),
                     "booked_pnl": P.num(t, "booked_pnl"), "booked_ts": P.num(t, "booked_ts"), "peak_roi": P.num(t, "max_roi_pct"), "invest": P.num(t, "invest_usdt")})
    return rows


def saved_keys(root):
    """Keys already in the join file + line count. Unreadable lines are skipped, never fixed or deleted."""
    keys, n = set(), 0
    try:
        with open(os.path.join(root, JOIN_FILE), "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                n += 1
                try:
                    k = json.loads(line).get("key")
                except (ValueError, AttributeError):
                    continue
                if k:
                    keys.add(k)
    except OSError:
        pass
    return keys, n


def read_all(root):
    """Every saved line (for Part 15 and for the summary)."""
    out = []
    try:
        with open(os.path.join(root, JOIN_FILE), "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    x = json.loads(line)
                except ValueError:
                    continue
                if isinstance(x, dict):
                    out.append(x)
    except OSError:
        pass
    return out


def update(root, fee_roi=1.0, write=True):
    """Join the closed trades with the snapshots and append the NEW ones. -> (added, matched_added)."""
    snaps = load_snaps(root)
    first = min((v[0][0] for v in snaps.values()), default=None)
    if first is None:
        return 0, 0
    have, _n = saved_keys(root)
    new, hit = [], 0
    for r in sorted(closed_rows(root, fee_roi), key=lambda a: a["ent"]):
        if r["key"] in have or r["ent"] < first:
            continue
        sn = match(snaps, r["sym"], r["side"], r["tf"], r["ent"])
        line = dict(r, snap=bool(sn), day=int(r["ent"] // DAY), joined=int(time.time()))
        if sn:
            hit += 1
            line.update({k: sn.get(k) for k in KEEP})
        new.append(line)
    if new and write:
        with open(os.path.join(root, JOIN_FILE), "a", encoding="utf-8") as f:
            for line in new:
                f.write(json.dumps(line, separators=(",", ":"), default=str) + "\n")
    return len(new), hit


def day_text(d):
    return time.strftime("%d %b", time.gmtime(d * DAY))


def build_report(root, fee_roi=1.0, write=True):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "file": JOIN_FILE}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    try:
        added, hit = update(root, fee_roi, write)
    except Exception as e:                      # never crash the study run
        rep["error"] = "join failed: %s" % str(e)[:160]
        rep["text"] = "JOIN (Part 11): failed - " + rep["error"]
        return rep
    rows = read_all(root)
    days = {}
    for r in rows:
        d = days.setdefault(r.get("day"), {"trades": 0, "with_snapshot": 0, "net": 0.0, "booked": 0})
        d["trades"] += 1
        d["with_snapshot"] += 1 if r.get("snap") else 0
        d["net"] += r.get("net") or 0.0
        d["booked"] += 1 if r.get("booked") else 0
    table = [{"day": day_text(k), "trades": v["trades"], "with_snapshot": v["with_snapshot"], "net_usdt": round(v["net"], 2), "banked_at_tp1": v["booked"]} for k, v in sorted(days.items(), key=lambda a: a[0] or 0)]
    n, m = len(rows), sum(1 for r in rows if r.get("snap"))
    mt = {}
    for r in rows:
        if r.get("snap"):
            mt[r.get("tf")] = mt.get(r.get("tf"), 0) + 1
    rep.update({"added_now": added, "added_with_snapshot": hit, "total_saved": n, "total_with_snapshot": m, "match_pct": round(100.0 * m / n, 1) if n else None, "days_saved": len(days),
                "with_snapshot_by_tf": mt, "days": table[-14:], "note": "Part 15 needs 7+ days. Under 30 trades in a group = luck, not proof. Never deleted, never changed."})
    ln = ["JOIN (Part 11): file %s | saved %d trades, %d with snapshot (%s%%), %d days | added now %d" % (JOIN_FILE, n, m, rep["match_pct"], len(days), added)]
    for t in table[-5:]:
        ln.append("%s: %d trades, %d with snapshot, net %+.1f, banked %d" % (t["day"], t["trades"], t["with_snapshot"], t["net_usdt"], t["banked_at_tp1"]))
    if n and m < 0.6 * n:
        ln.append("Match rate under 60%: many trades have no snapshot (3m before Part 10, or bot held too few candles). Tell Claude.")
    if not n:
        ln.append("Nothing joined yet: no closed trade after the first snapshot, or no snapshot file. Check again in a day.")
    ln.append("7+ days needed for Part 15. Paper money only.")
    rep["text"] = "\n".join(ln)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 11: daily join of snapshot + trade result")
    ap.add_argument("--data")
    ap.add_argument("--out", default="-")
    ap.add_argument("--text", action="store_true")
    ap.add_argument("--dry", action="store_true", help="do not write the join file")
    ap.add_argument("--fee-roi", type=float, default=1.0)
    a = ap.parse_args(argv)
    rep = build_report(I.find_data_dir(a.data), a.fee_roi, not a.dry)
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
