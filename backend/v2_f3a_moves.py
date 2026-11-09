"""v2_f3a_moves.py - FILTER STUDY Part 3A: FIND THE REAL MOVES (rallies and dumps) in the saved 5m candles. Read-only. Question: "which long moves were there, and what do they look like?"
Part 3B then checks which of these moves the bots caught, caught late, missed, or traded the wrong way. 3A only finds and describes them. No rule, no setting, no order, no network.
Reads:  v2_market.db (5m candles + cohort_official, read-only), the closed paper trades (only to know which coin-days the bots traded). Writes: v2_filter_moves.json in the data folder (every move, for 3B) and the summary.
HOW A MOVE IS FOUND (one coin, one crypto day 00:00-24:00 UTC = 5:30 AM IST, 5m closes; a day needs 250+ of 288 candles):
  ZIGZAG: a leg goes on while price makes new extremes. It ENDS when price falls back (rally) / bounces back (dump) by 1/3 of the leg so far, and at least 1.0% of price. The next leg starts at that extreme.
  A leg of 3% or more is a MOVE. Tiers: 3%+, 5%+, 10%+ (RALLY = up leg, DUMP = down leg). A move still running at 24:00 UTC ends there (marked DAY_END).
  The 1/3 and the 1.0% are DEFINITIONS of "where one move ends", not trading rules. They are written in the output so a different choice can be tried later. A move that crosses 00:00 UTC is cut in two (the owner's day).
COIN-DAYS studied: IN_LIST (the coin was in that day's 00:00 UTC top-5 gainers / top-5 losers list; the list is made BEFORE the day starts, so no look-ahead), TRADED (a paper bot traded the coin that day),
  and CONTROL (up to --control other coins with candles, all their days) so we can see what a normal coin does. Coins in the list are in it BECAUSE they moved the day before: compare IN_LIST with CONTROL, not with zero.
NUMBERS per move: size %, duration (hours + minutes), speed (% per hour), share of the move made in the first 3 candles (slow or explosive start), % from day open when the move STARTED (with the move direction:
  positive = the move started after the coin had already run that way), start hour (UTC + IST), nth move of that coin-day, list side.
SUMMARY (per tier): coin-days, coin-days with a move, moves per coin-day, RALLY vs DUMP, IN_LIST vs CONTROL, start hour, session, duration, start pump, start speed, nth move of the day.
Fewer than 30 moves in a bucket = NOT ENOUGH DATA. Durations over 60 min are hours + minutes.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f3a_moves.py --data /home/owl/owl_data --out -     Options: --control 40  --cap-days 0 (0 = all days)"""
import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_feed as F
import v2_defs as D
import v2_f1_counts as X
import v2_inventory as I
import v2_money_hour as M
import v2_pnl as P

VERSION = "v2_f3a_moves 1 (Filter Part 3A)"
MOVES_FILE = "v2_filter_moves.json"
MIN_N = 30
STEP = 300
DAY_CANDLES, MIN_DAY_CANDLES = 288, 250
RETRACE, MIN_REV_PCT, MIN_MOVE_PCT = 1.0 / 3.0, 1.0, 3.0
TIERS = (3.0, 5.0, 10.0)
DUR = ([30, 60, 120, 240], ["< 30 min", "30 min - 1 h", "1 - 2 h", "2 - 4 h", ">= 4 h"])
FIRST3 = ([0.2, 0.4, 0.6], ["< 20% (slow start)", "20-40%", "40-60%", ">= 60% (explosive start)"])
SPEED = ([1, 3, 6], ["< 1 %/h", "1-3 %/h", "3-6 %/h", ">= 6 %/h"])
NTH = ([2, 3], ["1st", "2nd", "3rd+"])


def bucket(v, spec):
    if v is None:
        return "n/a"
    for e, nm in zip(spec[0], spec[1]):
        if v < e:
            return nm
    return spec[1][-1]


# ----------------------------------------------------------------------------- zigzag
def legs_of(c):
    """Closes of one day -> legs [(dir, i0, i1, p0, p1, ended_by)], dir +1 up / -1 down. See the file doc for the end rule."""
    n, out = len(c), []
    if n < 2:
        return out
    lo = hi = (0, c[0])
    d, st, ex = 0, None, None
    for i in range(1, n):
        p = c[i]
        if d == 0:
            lo, hi = (i, p) if p < lo[1] else lo, (i, p) if p > hi[1] else hi
            if hi[1] / lo[1] - 1.0 >= MIN_REV_PCT / 100.0:
                d, st, ex = (1, lo, hi) if lo[0] < hi[0] else (-1, hi, lo)
            continue
        if (d == 1 and p > ex[1]) or (d == -1 and p < ex[1]):
            ex = (i, p)
            continue
        leg, back = abs(ex[1] - st[1]), abs(p - ex[1])
        if back >= max(RETRACE * leg, MIN_REV_PCT / 100.0 * ex[1]):
            out.append((d, st[0], ex[0], st[1], ex[1], "RETRACE"))
            d, st, ex = -d, ex, (i, p)
    if d != 0:
        out.append((d, st[0], ex[0], st[1], ex[1], "DAY_END"))
    return out


def move_row(sym, day, t, c, leg, nth, lst):
    d, i0, i1, p0, p1, why = leg
    size = abs(p1 / p0 - 1.0) * 100.0
    mins = max(1, i1 - i0) * STEP / 60.0
    first3 = abs(c[min(i0 + 3, i1)] - p0) / abs(p1 - p0) if p1 != p0 else None
    day_open = c[0]
    pump = (p0 / day_open - 1.0) * 100.0 * d
    h = datetime.datetime.fromtimestamp(t[i0], datetime.timezone.utc).hour
    return {"sym": sym, "day": day, "dir": "RALLY" if d == 1 else "DUMP", "t0": t[i0], "t1": t[i1], "p0": p0, "p1": p1, "size_pct": round(size, 2), "minutes": round(mins, 1),
            "duration": X.fmt_dur(mins), "speed_pct_h": round(size / (mins / 60.0), 2), "first3_share": round(first3, 3) if first3 is not None else None,
            "start_pump_pct": round(pump, 2), "start_hour": h, "nth": nth, "end": why, "list": lst}


def day_moves(sym, day, t, c, lst):
    out, nth = [], 0
    for leg in legs_of(c):
        if abs(leg[4] / leg[3] - 1.0) * 100.0 >= MIN_MOVE_PCT:
            nth += 1
            out.append(move_row(sym, day, t, c, leg, nth, lst))
    return out


# ----------------------------------------------------------------------------- data
def traded_days(root):
    """{(symbol, UTC day)} of every paper trade (entry time, else close time)."""
    trades, _st = X.load_trades(root)
    out = set()
    for t in trades:
        r = X.label_trade(t, 1.0)
        ts = r["ent"] or r["close"]
        if r["sym"] and ts and not (r["box"] and not str(r["box"]).startswith("paper")):
            out.add((r["sym"], X.utc_day(ts)))
    return out


def symbols(con):
    return [r[0] for r in con.execute("SELECT symbol, COUNT(*) n FROM candles WHERE interval='5m' GROUP BY symbol ORDER BY n DESC").fetchall()]


def study(con, cohort, traded, control_n, cap_days):
    listed = {s for (_d, s) in cohort} | {s for (s, _d) in traded}
    syms = symbols(con)
    ctrl = [s for s in syms if s not in listed][:control_n]
    use = [s for s in syms if s in listed] + ctrl
    cov = {"coins": len(use), "control_coins": len(ctrl), "coin_days": 0, "days_skipped_short": 0, "coin_days_in_list": 0, "coin_days_traded": 0, "coin_days_control": 0}
    moves, cdays = [], []
    for sym in use:
        good, _bad = D.clean_candles(D.candles_from_store(con, sym, "5m", 0, 2 ** 31), "5m")
        byday = {}
        for r in good:
            byday.setdefault(r[0] - r[0] % 86400, []).append(r)
        days = sorted(byday)
        if cap_days:
            days = days[-cap_days:]
        for d0 in days:
            rows = byday[d0]
            day = X.utc_day(d0)
            if len(rows) < MIN_DAY_CANDLES:
                cov["days_skipped_short"] += 1
                continue
            hit = cohort.get((day, sym))
            in_list, was_traded = hit is not None, (sym, day) in traded
            if not (in_list or was_traded or sym in ctrl):
                continue
            kind = "CONTROL" if not (in_list or was_traded) else ("IN_LIST" if in_list else "TRADED_ONLY")
            cov["coin_days"] += 1
            cov["coin_days_" + {"IN_LIST": "in_list", "TRADED_ONLY": "traded", "CONTROL": "control"}[kind]] += 1
            lst = {"kind": kind, "list_kind": hit[0] if hit else None, "rank": hit[1] if hit else None, "traded": was_traded}
            ms = day_moves(sym, day, [r[0] for r in rows], [r[4] for r in rows], lst)
            moves.extend(ms)
            cdays.append({"sym": sym, "day": day, "kind": kind, "traded": was_traded, "moves": len(ms)})
    return moves, cdays, cov


# ----------------------------------------------------------------------------- summary
def tier_block(moves, cdays, tier):
    ms = [m for m in moves if m["size_pct"] >= tier]
    cnt = {}
    for m in ms:
        cnt[(m["sym"], m["day"])] = cnt.get((m["sym"], m["day"]), 0) + 1
    cd = [dict(c, n=cnt.get((c["sym"], c["day"]), 0)) for c in cdays]
    out = {"moves": len(ms), "coin_days": len(cd), "coin_days_with_a_move": sum(1 for c in cd if c["n"]), **({"label": "NOT ENOUGH DATA"} if len(ms) < MIN_N else {})}
    out["rallies"], out["dumps"] = sum(1 for m in ms if m["dir"] == "RALLY"), sum(1 for m in ms if m["dir"] == "DUMP")
    out["by_coin_day_kind"] = {}
    for k in ("IN_LIST", "TRADED_ONLY", "CONTROL"):
        c = [x for x in cd if x["kind"] == k]
        if c:
            mm = [m for m in ms if m["list"]["kind"] == k]
            out["by_coin_day_kind"][k] = {"coin_days": len(c), "moves": len(mm), "moves_per_coin_day": round(len(mm) / len(c), 2), "share_of_coin_days_with_a_move_pct": round(sum(1 for x in c if x["n"]) * 100.0 / len(c), 1)}
    lk = {}
    for m in ms:
        if m["list"]["list_kind"]:
            k = "%s coin: %s" % (m["list"]["list_kind"], m["dir"])
            lk[k] = lk.get(k, 0) + 1
    out["list_side_vs_move_direction"] = lk
    h = {}
    for m in ms:
        h.setdefault(m["start_hour"], []).append(m)
    out["start_hour"] = {"%02d UTC (%s IST)" % (k, M.ist_label(k)): len(v) for k, v in sorted(h.items())}
    out["start_session"] = {nm: sum(1 for m in ms if M.session_of(m["start_hour"]) == nm) for nm, _a, _b in M.SESSIONS}
    for key, spec, name in (("minutes", DUR, "duration"), ("speed_pct_h", SPEED, "speed"), ("first3_share", FIRST3, "start_of_move")):
        out[name] = {nm: sum(1 for m in ms if bucket(m[key], spec) == nm) for nm in spec[1]}
    out["start_pump_with_move"] = {nm: sum(1 for m in ms if bucket(m["start_pump_pct"], (X.EDGES["pump_side"][0], X.EDGES["pump_side"][1])) == nm) for nm in X.EDGES["pump_side"][1]}
    out["nth_move_of_coin_day"] = {nm: sum(1 for m in ms if bucket(m["nth"], NTH) == nm) for nm in NTH[1]}
    out["avg_size_pct"] = round(sum(m["size_pct"] for m in ms) / len(ms), 2) if ms else None
    out["avg_duration"] = X.fmt_dur(sum(m["minutes"] for m in ms) / len(ms)) if ms else "n/a"
    out["still_running_at_day_end"] = sum(1 for m in ms if m["end"] == "DAY_END")
    return out


def build_report(root, control_n=40, cap_days=0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "min_moves_per_bucket": MIN_N, "day_start": "00:00 UTC = 5:30 AM IST",
           "definition": {"leg_ends_when_price_falls_back_by": "1/3 of the leg so far, and at least %.1f%% of price" % MIN_REV_PCT, "move_if_leg_at_least_pct": MIN_MOVE_PCT, "tiers_pct": list(TIERS),
                          "note": "These are definitions of where a move ends, not trading rules."}}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    con = F.open_ro(root)
    if con is None:
        rep["error"] = "No candle store (v2_market.db) yet: nothing to study."
        return rep
    try:
        moves, cdays, cov = study(con, X.load_cohort(con), traded_days(root), control_n, cap_days)
    finally:
        con.close()
    rep["coverage"] = cov
    rep["tiers"] = {"%d%%+" % t: tier_block(moves, cdays, t) for t in TIERS}
    rep["moves_file"] = {"name": MOVES_FILE, "moves": len(moves), "saved": F.write_json(root, MOVES_FILE, {"tool": VERSION, "made_utc": rep["made_utc"], "definition": rep["definition"], "coin_days": cdays, "moves": moves})}
    rep["notes"] = ["Read-only. IN_LIST coins are in the list because they moved before the day: compare IN_LIST with CONTROL, not with zero.",
                    "A move that crosses 00:00 UTC is cut in two. Moves still running at day end are counted and marked.",
                    "Part 3B reads v2_filter_moves.json and checks which moves the bots caught, caught late, missed, or traded the wrong way."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 3A: find rallies and dumps (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--out", default="-")
    ap.add_argument("--control", type=int, default=40)
    ap.add_argument("--cap-days", type=int, default=0)
    a = ap.parse_args(argv)
    txt = json.dumps(build_report(I.find_data_dir(a.data), a.control, a.cap_days), indent=1, ensure_ascii=False, default=str)
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
