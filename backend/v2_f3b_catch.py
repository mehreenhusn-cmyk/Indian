"""v2_f3b_catch.py - FILTER STUDY Part 3B: DID THE BOTS CATCH THE REAL MOVES? (read-only). Needs Part 3A (v2_filter_moves.json) and Part 1 (v2_filter_trades.json); a missing file is made first by running that Part.
For every move of 3A on a coin the bots work on (IN_LIST and TRADED_ONLY coin-days; CONTROL coins are not traded, so they are left out) and for Main and Sniper SEPARATELY (the same move can be caught by one and missed by the other):
  ALREADY_IN   a same-direction trade was opened more than 1 h before the move started and was still open in it.
  EARLY / MID / LATE  the earliest same-direction trade of that group that was open during the move, by how much of the move's PRICE travel was already done at its entry price: up to 1/3, up to 2/3, more.
  WRONG_WAY    no same-direction trade, but an opposite-direction trade was opened during the move (it traded against the move).
  MISSED_COIN_TRADED   no trade in the move, although the group traded this coin that same day.
  MISSED_NOT_TRADED    the group did not trade this coin that day at all.
  1/3 and 2/3 only split "how early"; they are not trading rules. CAUGHT = ALREADY_IN + EARLY + MID + LATE.
CAPTURE: for caught moves, price % the earliest trade really made (ROI / leverage) divided by the size of the move. Low capture = caught but exited early (or got stopped). Facts only.
MAIN MISSES, WHY: if the signals table (owl.db) is there: was there a same-direction signal during the move that the bot SKIPPED (with the skip reason), or no signal at all?
b3 (chop_b3.db, if present): for the same moves, did b3 TAKE it, SKIP it (saw the signal, said no), or see nothing?
CATCH RATE by move feature (3%+ tier): start pump, start speed, how explosive the start was, duration, session, list side vs direction.
Fewer than 30 moves in a bucket = NOT ENOUGH DATA. Durations over 60 min are hours + minutes. Day = 00:00 UTC = 5:30 AM IST.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f3b_catch.py --data /home/owl/owl_data --out -"""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f1_counts as X
import v2_f3a_moves as A
import v2_inventory as I
import v2_money_hour as M
import v2_pnl as P

VERSION = "v2_f3b_catch 1 (Filter Part 3B)"
MIN_N = 30
PRE_H = 3600
CAUGHT = ("ALREADY_IN", "EARLY", "MID", "LATE")
CATS = CAUGHT + ("WRONG_WAY", "MISSED_COIN_TRADED", "MISSED_NOT_TRADED")


def load_json(root, name):
    try:
        with open(os.path.join(root, name), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def classify(m, trs, traded_day):
    """-> (category, earliest same-side trade or None)."""
    d = 1 if m["dir"] == "RALLY" else -1
    same = sorted((r for r in trs if r["side"] == d and r["ent"] <= m["t1"] and (r["close"] or 2 ** 40) >= m["t0"]), key=lambda r: r["ent"])
    if same:
        r = same[0]
        if r["ent"] < m["t0"] - PRE_H:
            return "ALREADY_IN", r
        ep, span = r.get("entry_price"), m["p1"] - m["p0"]
        prog = (ep - m["p0"]) / span if ep and span else 0.0
        return ("EARLY" if prog <= 1 / 3 else ("MID" if prog <= 2 / 3 else "LATE")), r
    if any(r["side"] == -d and m["t0"] <= r["ent"] <= m["t1"] for r in trs):
        return "WRONG_WAY", None
    return ("MISSED_COIN_TRADED" if traded_day else "MISSED_NOT_TRADED"), None


def capture(m, r):
    if not r or r.get("roi") is None or not r.get("lev") or not m["size_pct"]:
        return None
    return (r["roi"] / r["lev"]) / m["size_pct"]


def counts(ms, cls):
    n = len(ms)
    c = {k: sum(1 for m in ms if cls[id(m)][0] == k) for k in CATS}
    caught = sum(c[k] for k in CAUGHT)
    caps = [capture(m, cls[id(m)][1]) for m in ms if cls[id(m)][0] in CAUGHT]
    caps = sorted(x for x in caps if x is not None)
    out = {"moves": n, **c, "caught": caught, "catch_rate_pct": round(caught * 100.0 / n, 1) if n else None,
           "early_catch_rate_pct": round((c["ALREADY_IN"] + c["EARLY"]) * 100.0 / n, 1) if n else None}
    if caps:
        out["capture_median_pct"], out["capture_avg_pct"] = round(caps[len(caps) // 2] * 100, 1), round(sum(caps) / len(caps) * 100, 1)
    cm = [m["size_pct"] for m in ms if cls[id(m)][0] in CAUGHT]
    mm = [m["size_pct"] for m in ms if cls[id(m)][0].startswith("MISSED")]
    out["avg_size_pct_caught"], out["avg_size_pct_missed"] = (round(sum(cm) / len(cm), 2) if cm else None), (round(sum(mm) / len(mm), 2) if mm else None)
    out["net_usdt_of_catching_trades"] = round(sum(cls[id(m)][1]["net"] for m in ms if cls[id(m)][1] and cls[id(m)][1].get("net") is not None), 3)
    if n < MIN_N:
        out["label"] = "NOT ENOUGH DATA"
    return out


def features(ms, cls):
    """Catch rate per move feature (all moves of the tier)."""
    def tab(fn, names):
        res = {}
        for nm in names:
            g = [m for m in ms if fn(m) == nm]
            if g:
                k = sum(1 for m in g if cls[id(m)][0] in CAUGHT)
                res[nm] = {"moves": len(g), "caught": k, "catch_rate_pct": round(k * 100.0 / len(g), 1), **({"label": "NOT ENOUGH DATA"} if len(g) < MIN_N else {})}
        return res
    pump = (X.EDGES["pump_side"][0], X.EDGES["pump_side"][1])
    return {"start_pump_with_move": tab(lambda m: A.bucket(m["start_pump_pct"], pump), pump[1]),
            "start_speed": tab(lambda m: A.bucket(m["speed_pct_h"], A.SPEED), A.SPEED[1]),
            "start_of_move": tab(lambda m: A.bucket(m["first3_share"], A.FIRST3), A.FIRST3[1]),
            "duration": tab(lambda m: A.bucket(m["minutes"], A.DUR), A.DUR[1]),
            "session": tab(lambda m: M.session_of(m["start_hour"]), [s[0] for s in M.SESSIONS]),
            "direction": tab(lambda m: m["dir"], ["RALLY", "DUMP"]),
            "list_side_vs_direction": tab(lambda m: "%s coin: %s" % (m["list"]["list_kind"], m["dir"]) if m["list"].get("list_kind") else "not in list", ["GAINER coin: RALLY", "GAINER coin: DUMP", "LOSER coin: RALLY", "LOSER coin: DUMP", "not in list"])}


# ----------------------------------------------------------------------------- Main signals + b3
def find_owl_db(root):
    for p in (os.path.join(root, "owl.db"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "owl.db")):
        if os.path.isfile(p):
            return p
    return None


def ro(path):
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    con.execute("PRAGMA query_only=ON")
    return con


def load_signals(root):
    p = find_owl_db(root)
    if not p:
        return None
    try:
        con = ro(p)
        try:
            rows = con.execute("SELECT symbol, action, recorded_at, opened, skip_reason FROM signals WHERE recorded_at IS NOT NULL").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    out = {}
    for s, a, t, o, why in rows:
        out.setdefault(s, []).append((t, 1 if str(a).upper() in ("BUY", "LONG") else -1, o, why))
    return out


def why_missed(ms, cls, sigs):
    """For Main misses: a same-direction signal was SKIPPED (reason) or there was no signal."""
    res, reasons = {"SIGNAL_SKIPPED": 0, "SIGNAL_OPENED_OTHER_BOT": 0, "NO_SIGNAL": 0}, {}
    for m in ms:
        if not cls[id(m)][0].startswith("MISSED"):
            continue
        d = 1 if m["dir"] == "RALLY" else -1
        hit = sorted(s for s in sigs.get(m["sym"], []) if s[1] == d and m["t0"] - 300 <= s[0] <= m["t1"])
        if not hit:
            res["NO_SIGNAL"] += 1
        elif any(s[2] for s in hit):
            res["SIGNAL_OPENED_OTHER_BOT"] += 1
        else:
            res["SIGNAL_SKIPPED"] += 1
            k = str(hit[0][3] or "no reason recorded")[:60]
            reasons[k] = reasons.get(k, 0) + 1
    return {"missed_moves": sum(res.values()), **res, "top_skip_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:10])}


def b3_overlay(root, ms):
    path = os.path.join(root, "chop_b3.db")
    if not os.path.isfile(path):
        return {"present": False, "note": "b3 has no database yet (it is OFF by default)."}
    try:
        con = ro(path)
        try:
            rows = con.execute("SELECT symbol, side, action, candle_ts FROM decisions").fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        return {"present": True, "error": str(e)[:100]}
    by = {}
    for s, sd, a, t in rows:
        by.setdefault(s, []).append((t, 1 if str(sd).upper() in ("BUY", "LONG") else -1, a))
    out = {"TAKE": 0, "SKIP_ONLY": 0, "NO_SIGNAL": 0}
    for m in ms:
        d = 1 if m["dir"] == "RALLY" else -1
        hit = [x for x in by.get(m["sym"], []) if x[1] == d and m["t0"] - 900 <= x[0] <= m["t1"]]
        out["TAKE" if any(x[2] == "TAKE" for x in hit) else ("SKIP_ONLY" if hit else "NO_SIGNAL")] += 1
    return {"present": True, "moves": len(ms), **out, "note": "b3 only has decisions since it was switched on, so old moves show NO_SIGNAL."}


# ----------------------------------------------------------------------------- report
def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "min_moves_per_bucket": MIN_N, "day_start": "00:00 UTC = 5:30 AM IST"}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    mv = load_json(root, A.MOVES_FILE)
    if not mv or not mv.get("moves"):
        A.build_report(root)
        mv = load_json(root, A.MOVES_FILE)
    tr = load_json(root, X.ROWS_FILE)
    if not tr or not tr.get("rows"):
        X.build_report(root, fee_roi)
        tr = load_json(root, X.ROWS_FILE)
    if not mv or not mv.get("moves"):
        rep["error"] = "No moves found (needs the candle store; run Part 3A)."
        return rep
    moves = [m for m in mv["moves"] if m["list"]["kind"] != "CONTROL"]
    rep["definition"], rep["moves_file_made_utc"] = mv.get("definition"), mv.get("made_utc")
    rep["moves_on_bot_coin_days"], rep["control_moves_left_out"] = len(moves), len(mv["moves"]) - len(moves)
    rows = [r for r in (tr or {}).get("rows", []) if r.get("ent") and not r.get("ent_from_close") and r.get("side")]
    sigs = load_signals(root)
    rep["signals_table"] = "found" if sigs is not None else "not found (Main miss reasons skipped)"
    for g in X.GROUPS:
        by, days = {}, set()
        for r in rows:
            if r["g"] == g:
                by.setdefault(r["sym"], []).append(r)
                days.add((r["sym"], X.utc_day(r["ent"])))
        cls = {id(m): classify(m, by.get(m["sym"], []), (m["sym"], m["day"]) in days) for m in moves}
        blk = {"tiers": {}}
        for t in A.TIERS:
            ms = [m for m in moves if m["size_pct"] >= t]
            tb = {"all": counts(ms, cls), "rally": counts([m for m in ms if m["dir"] == "RALLY"], cls), "dump": counts([m for m in ms if m["dir"] == "DUMP"], cls)}
            if t == A.TIERS[0]:
                tb["catch_rate_by_move_feature"] = features(ms, cls)
            if g == "MAIN" and sigs is not None:
                tb["why_missed"] = why_missed(ms, cls, sigs)
            blk["tiers"]["%d%%+" % t] = tb
        rep[g] = blk
    rep["b3"] = {"%d%%+" % t: b3_overlay(root, [m for m in moves if m["size_pct"] >= t]) for t in A.TIERS}
    rep["notes"] = ["Main and Sniper are never added together; the same move can be caught by one and missed by the other.",
                    "A catching trade is not proof the filter should change: a trade that caught a move can still have lost money. Compare capture and net.",
                    "Moves come from 3A (zigzag definition in the output). Control coins are left out because the bots do not trade them.",
                    "Cut-offs are not made here. Part 4 (filter lab) tests which filters keep the caught moves and cut the fakes."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 3B: were the real moves caught? (read-only)")
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
