"""v2_f4_filters.py - FILTER STUDY Part 4: THE FILTER LAB (read-only). Main and Sniper always separate; scopes ALL timeframes and 5m only (the bot runs on 5m).
Measures only. No rule, no setting, no order, no network. It does NOT change the bot: it only tells which "block this trade" filters would have paid, on data the filter never saw.
Reads: v2_filter_trades.json (Part 1 rows) + v2_filter_moves.json (Part 3A moves). If a file is missing it makes it first (both are read-only too). Needs v2_f1_counts.py, v2_f2_fakes.py, v2_f3a_moves.py.
HOW A FILTER IS JUDGED (each filter ALONE, time-ordered, never random):
  SPLIT     trades sorted by entry time. TRAIN = first 60%, TEST = last 40%. Cut-offs are chosen on TRAIN only. TEST is only for judging.
  FILTER    "BLOCK a trade when ..." Two families:
            BUCKET  = a Part 1 / Part 2 bucket (Z zone, SD shape, setup status, wick, nth trade, list side, session ...). Fixed names, nothing tuned.
            CUTOFF  = a number (candle size, wick, EMA50 distance, volume ratio, TP vs fee, % from day open ...) blocked below or above a cut. Cuts are the TRAIN deciles (10%..90%); the best one per
                      number and direction is picked on TRAIN only (needs 10+ blocked trades and zero moves lost on TRAIN), then shown on TEST.
            A trade with no number for that field is never blocked (kept).
  NUMBERS   per half: trades blocked, winners cut, losers cut (net below zero), FAKES cut (Part 2 definition), net of the blocked trades, NET GAIN (= money saved: minus the net of the blocked trades),
            MOVES LOST = rallies / dumps of 3%+ (Part 3A) that were caught by at least one trade before and by NONE after the filter (big = 5%+). The owner's rule: do not kill the rallies.
  VERDICT   PASS = 10+ blocked in both halves, net gain above zero in BOTH halves, zero moves lost in BOTH halves.   HELPS_BUT_LOSES_MOVES = gain in both halves but a move is lost.
            FAILS_TEST = gain on TRAIN, not on TEST (looked good by luck / overfit).   NO_HELP = no gain on TRAIN.   TOO_FEW = under 10 blocked in a half.   (No moves file = PASS_NO_MOVE_CHECK, do not trust.)
  LUCK      for PASS and the stack: how often a RANDOM block of the same number of TEST trades saves as much (200 tries, fixed seed). Low % = not luck.
  PROTECT   the buckets whose trades make the most money in both halves: never block these.
  STACK     filters that qualify on TRAIN alone (10+ blocked, gain, zero moves lost) are added one by one while TRAIN gain grows and TRAIN moves lost stay zero; the stack is then judged on TEST.
Honest limits: about 100+ filters are tried per group and scope, so a few look good by luck: only a PASS with a low LUCK % is a candidate for Part 7, and even then it is a candidate, not a rule.
Fewer than 60 trades in a scope = NOT ENOUGH DATA. Day = 00:00 UTC = 5:30 AM IST. Durations over 60 min are written as hours + minutes.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f4_filters.py --data /home/owl/owl_data --out -"""
import argparse
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f1_counts as X
import v2_f2_fakes as K
import v2_f3a_moves as A
import v2_inventory as I
import v2_money_hour as M
import v2_pnl as P

VERSION = "v2_f4_filters 1 (Filter Part 4)"
MIN_BLOCK = 10                     # blocked trades needed in a half before it counts
MIN_SCOPE = 60                     # trades needed in a scope (30 per half)
TRAIN_FRAC = 0.6
CUT_PCTS = (10, 20, 30, 40, 50, 60, 70, 80, 90)
TRIALS = 200
SCOPES = (("all", None), ("5m", "5m"))
NUMBERS = (("size_pct", "candle size %", "size_pct"), ("wick_against", "wick against side (share)", "wick_against"), ("ema50_abs", "distance from EMA50 %", "ema50_abs"),
           ("since_ema50_cross", "candles since EMA50 cross", "since_ema50_cross"), ("vol_ratio", "volume vs 20-candle average", "vol_ratio"),
           ("tp4fee_x", "TP4 distance vs fee (x)", "tp4fee_x"), ("tp1fee_x", "TP1 distance vs fee (x)", "tp1fee_x"), ("nth", "nth trade of the coin today", "nth"),
           ("z_side", "Z with the trade side", "z_side"), ("pump_side", "% from day open with the trade side", "pump_side"), ("shape_flips50", "SD shape flips in 50 candles", "shape_flips50"),
           ("width_chg20_pct", "band width change 20 candles %", "width_chg20_pct"), ("slope_side", "centre line slope 20 candles with the side %", "slope_side"),
           ("list_rank", "top-10 rank", "list_rank"), ("list_days", "days in the top-10 list", "list_days"), ("chop_n", "EMA crosses in the chop window", "regime_cross_n"))


# ----------------------------------------------------------------------------- rows
def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def derive(r):
    """Adds the few helper numbers that are not stored as they are (abs / with-side versions)."""
    side = r.get("side") or 0
    d = num(r.get("ema50_dist_pct"))
    r["ema50_abs"] = abs(d) if d is not None else None
    p = num(r.get("pct_day_open"))
    r["pump_side"] = p * side if p is not None and side else None
    s = num(r.get("center_slope20_pct"))
    r["slope_side"] = s * side if s is not None and side else None
    if r.get("list_kind") is None:
        r["list_rank"] = r["list_days"] = None


def load_json(root, name):
    try:
        with open(os.path.join(root, name), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def bucket_filters():
    """Every fixed bucket as (title, row key, bucket name). Session is added to the Part 1 / 2 buckets."""
    out = [(t, k, nm) for t, k, names in K.table_defs() for nm in names]
    return out + [("session", "session", nm) for nm, _a, _b in M.SESSIONS]


# ----------------------------------------------------------------------------- one scope = rows + moves + split
def make_scope(rows, moves):
    rows = sorted((r for r in rows if r.get("ent") and not r.get("ent_from_close")), key=lambda r: r["ent"])
    if len(rows) < MIN_SCOPE:
        return None
    cut_t = rows[int(len(rows) * TRAIN_FRAC)]["ent"]
    by_sym = {}
    for i, r in enumerate(rows):
        by_sym.setdefault(r["sym"], []).append(i)
    parts = {"train": {"idx": [], "moves": []}, "test": {"idx": [], "moves": []}}
    for i, r in enumerate(rows):
        parts["train" if r["ent"] < cut_t else "test"]["idx"].append(i)
    for m in moves:
        d = 1 if m["dir"] == "RALLY" else -1
        ms = [i for i in by_sym.get(m["sym"], []) if rows[i]["side"] == d and rows[i]["ent"] <= m["t1"] and (rows[i].get("close") or 2 ** 40) >= m["t0"]]
        if ms:
            parts["train" if m["t0"] < cut_t else "test"]["moves"].append((ms, m["size_pct"]))
    return {"rows": rows, "cut_t": cut_t, "parts": parts}


def evaluate(rows, blocked, part):
    """Numbers of one half for one filter (blocked = set of row positions)."""
    cut = [rows[i] for i in part["idx"] if i in blocked]
    net_cut = sum(r["net"] for r in cut)
    lost = [size for ms, size in part["moves"] if all(i in blocked for i in ms)]
    n = len(part["idx"])
    return {"blocked": len(cut), "blocked_pct": round(len(cut) * 100.0 / n, 1) if n else None, "winners_cut": sum(1 for r in cut if r["kind"] == "WIN"),
            "losers_cut": sum(1 for r in cut if r["net"] < 0), "fakes_cut": sum(1 for r in cut if r["kind"] == "FAKE"), "net_blocked": round(net_cut, 3),
            "net_gain": round(-net_cut, 3), "moves_lost": len(lost), "big_moves_lost": sum(1 for s in lost if s >= 5)}


def verdict(tr, te, have_moves):
    if tr["blocked"] < MIN_BLOCK or te["blocked"] < MIN_BLOCK:
        return "TOO_FEW"
    if tr["net_gain"] > 0 and te["net_gain"] > 0:
        if tr["moves_lost"] or te["moves_lost"]:
            return "HELPS_BUT_LOSES_MOVES"
        return "PASS" if have_moves else "PASS_NO_MOVE_CHECK"
    return "FAILS_TEST" if tr["net_gain"] > 0 else "NO_HELP"


def luck(sc, n_block, gain, rng):
    """% of random blocks (same count, TEST trades) that save at least as much as the filter did."""
    pool = [sc["rows"][i]["net"] for i in sc["parts"]["test"]["idx"]]
    if n_block <= 0 or n_block > len(pool):
        return None
    hit = sum(1 for _ in range(TRIALS) if -sum(rng.sample(pool, n_block)) >= gain)
    return round(hit * 100.0 / TRIALS, 1)


def judge(sc, name, family, blocked, have_moves, extra=None):
    tr, te = (evaluate(sc["rows"], blocked, sc["parts"][p]) for p in ("train", "test"))
    out = {"filter": name, "family": family, "verdict": verdict(tr, te, have_moves), "train": tr, "test": te}
    if extra:
        out.update(extra)
    return out


# ----------------------------------------------------------------------------- the two families
def bucket_results(sc, have_moves):
    out, rows = [], sc["rows"]
    for title, key, nm in bucket_filters():
        blocked = {i for i, r in enumerate(rows) if r.get(key) == nm}
        if blocked:
            out.append((judge(sc, "BLOCK %s = %s" % (title, nm), "BUCKET", blocked, have_moves), blocked))
    return out


def quantiles(vals):
    vals = sorted(vals)
    cuts = []
    for p in CUT_PCTS:
        c = vals[min(len(vals) - 1, int(len(vals) * p / 100.0))]
        if c not in cuts:
            cuts.append(c)
    return cuts


def cutoff_results(sc, have_moves):
    """Per number and direction: the best TRAIN cut (10+ blocked, zero moves lost), then its TEST result."""
    out, rows = [], sc["rows"]
    train_idx = sc["parts"]["train"]["idx"]
    for key, label, field in NUMBERS:
        vals = [num(rows[i].get(field)) for i in train_idx]
        vals = [v for v in vals if v is not None]
        if len(vals) < MIN_SCOPE // 2:
            out.append(({"filter": "BLOCK %s" % label, "family": "CUTOFF", "verdict": "NO_NUMBERS", "numbers_on_train": len(vals)}, None))
            continue
        cuts = quantiles(vals)
        for direction in ("below", "above"):
            best, tried = None, 0
            for c in cuts:
                blocked = {i for i, r in enumerate(rows) if num(r.get(field)) is not None and (num(r.get(field)) < c if direction == "below" else num(r.get(field)) >= c)}
                ev = evaluate(rows, blocked, sc["parts"]["train"])
                tried += 1
                if ev["blocked"] >= MIN_BLOCK and ev["moves_lost"] == 0 and ev["net_gain"] > 0 and (best is None or ev["net_gain"] > best[0]["net_gain"]):
                    best = (ev, c, blocked)
            name = "BLOCK %s %s %s" % (label, "<" if direction == "below" else ">=", "?")
            if best is None:
                out.append(({"filter": name.replace("?", "(no cut)"), "family": "CUTOFF", "verdict": "NO_TRAIN_CUT_PASSES", "cuts_tried": tried}, None))
                continue
            ev, c, blocked = best
            nm = "BLOCK %s %s %s" % (label, "<" if direction == "below" else ">=", round(c, 3))
            out.append((judge(sc, nm, "CUTOFF", blocked, have_moves, {"cut": round(c, 4), "cuts_tried": tried, "picked_on": "TRAIN only"}), blocked))
    return out


# ----------------------------------------------------------------------------- stack + protect
def stack(sc, cands, have_moves, rng):
    """Greedy on TRAIN only; judged on TEST."""
    rows, tr_part = sc["rows"], sc["parts"]["train"]
    pool = [(j, b) for j, b in cands if b and j["train"]["blocked"] >= MIN_BLOCK and j["train"]["net_gain"] > 0 and j["train"]["moves_lost"] == 0]
    pool.sort(key=lambda x: -x[0]["train"]["net_gain"])
    total, cur, steps = set(), 0.0, []
    for j, b in pool:
        new = total | b
        ev = evaluate(rows, new, tr_part)
        if ev["net_gain"] > cur and ev["moves_lost"] == 0:
            total, cur = new, ev["net_gain"]
            steps.append({"added": j["filter"], "train_net_gain_after": ev["net_gain"], "test_net_gain_after": evaluate(rows, total, sc["parts"]["test"])["net_gain"]})
    if not steps:
        return {"result": "NO_STACK: no filter qualified on TRAIN"}
    res = judge(sc, "STACK of %d filters" % len(steps), "STACK", total, have_moves)
    res["steps"] = steps
    res["luck_random_as_good_pct"] = luck(sc, res["test"]["blocked"], res["test"]["net_gain"], rng)
    return res


def protect(sc, cands):
    """Buckets whose trades earn the most in BOTH halves: blocking them would lose the most money."""
    keep = [j for j, b in cands if j["family"] == "BUCKET" and j["train"]["blocked"] >= MIN_BLOCK and j["test"]["blocked"] >= MIN_BLOCK and j["train"]["net_gain"] < 0 and j["test"]["net_gain"] < 0]
    keep.sort(key=lambda j: j["train"]["net_gain"] + j["test"]["net_gain"])
    return [{"bucket": j["filter"].replace("BLOCK ", ""), "trades_train": j["train"]["blocked"], "trades_test": j["test"]["blocked"], "net_train": j["train"]["net_blocked"],
             "net_test": j["test"]["net_blocked"]} for j in keep[:8]]


# ----------------------------------------------------------------------------- report
def short(j):
    return {k: j[k] for k in ("filter", "family", "verdict", "cut", "luck_random_as_good_pct", "train", "test") if k in j}


def scope_report(rows, moves, have_moves, seed):
    sc = make_scope(rows, moves)
    if sc is None:
        return {"label": "NOT ENOUGH DATA", "trades": len(rows), "need": MIN_SCOPE}
    rng = random.Random(seed)
    base = {p: K.counts([sc["rows"][i] for i in sc["parts"][p]["idx"]]) for p in ("train", "test")}
    base_moves = {p: {"moves_caught": len(sc["parts"][p]["moves"]), "big_caught_5pct_plus": sum(1 for _m, s in sc["parts"][p]["moves"] if s >= 5)} for p in ("train", "test")}
    cands = bucket_results(sc, have_moves) + cutoff_results(sc, have_moves)
    judged = [(j, b) for j, b in cands if "train" in j]
    for j, b in judged:
        if j["verdict"] == "PASS" or j["verdict"] == "PASS_NO_MOVE_CHECK":
            j["luck_random_as_good_pct"] = luck(sc, j["test"]["blocked"], j["test"]["net_gain"], rng)
    byv = {}
    for j, _b in judged:
        byv.setdefault(j["verdict"], []).append(j)
    by_test = lambda v: sorted(byv.get(v, []), key=lambda j: -j["test"]["net_gain"])
    ts = lambda t: P.fmt_ts(t) if t else None
    return {"trades": len(sc["rows"]), "train_trades": len(sc["parts"]["train"]["idx"]), "test_trades": len(sc["parts"]["test"]["idx"]),
            "train_from_utc": ts(sc["rows"][0]["ent"]), "split_utc": ts(sc["cut_t"]), "test_to_utc": ts(sc["rows"][-1]["ent"]),
            "baseline": base, "baseline_moves_3pct_plus": base_moves, "filters_tried": len(cands), "verdict_counts": {k: len(v) for k, v in sorted(byv.items())},
            "PASS": [short(j) for j in by_test("PASS") + by_test("PASS_NO_MOVE_CHECK")][:10],
            "HELPS_BUT_LOSES_MOVES": [short(j) for j in by_test("HELPS_BUT_LOSES_MOVES")][:8],
            "FAILS_TEST_examples": [short(j) for j in sorted(byv.get("FAILS_TEST", []), key=lambda j: -j["train"]["net_gain"])[:5]],
            "cutoffs_per_number": [short(j) if "train" in j else j for j, _b in cands if j["family"] == "CUTOFF"],
            "stack": stack(sc, judged, have_moves, rng), "PROTECT_never_block": protect(sc, judged)}


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST", "min_blocked_per_half": MIN_BLOCK,
           "split": "time-ordered: first %d%% = TRAIN, last %d%% = TEST (never random)" % (TRAIN_FRAC * 100, 100 - TRAIN_FRAC * 100)}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    src = K.load_rows(root)
    if not src or not src.get("rows"):
        X.build_report(root, fee_roi)
        rep["note_rows"] = "v2_filter_trades.json was missing: Part 1 was run first."
        src = K.load_rows(root)
    mv = load_json(root, A.MOVES_FILE)
    if not mv or not mv.get("moves"):
        try:
            A.build_report(root)
        except Exception as e:                                           # read-only study: never stop the whole lab for the moves file
            rep["note_moves_error"] = str(e)[:200]
        mv = load_json(root, A.MOVES_FILE)
    moves = [m for m in ((mv or {}).get("moves") or []) if (m.get("list") or {}).get("kind") != "CONTROL" and (m.get("size_pct") or 0) >= 3.0]
    have_moves = bool(moves)
    rows, dropped = K.prepare((src or {}).get("rows") or [])
    for r in rows:
        derive(r)
    rep["rows_used"], rep["rows_without_net_result"], rep["moves_used_3pct_plus"] = len(rows), dropped, len(moves)
    rep["moves_check"] = "ON" if have_moves else "NOT AVAILABLE: no moves file (needs the candle store, Part 3A). Do not trust any PASS."
    rep["rows_file_made_utc"], rep["moves_file_made_utc"] = (src or {}).get("made_utc"), (mv or {}).get("made_utc")
    for gi, g in enumerate(X.GROUPS):
        grs = [r for r in rows if r["g"] == g]
        rep[g] = {nm: scope_report([r for r in grs if tf is None or r["tf"] == tf], moves, have_moves, 7 + gi * 10 + si) for si, (nm, tf) in enumerate(SCOPES)}
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades. TEST trades never choose a cut-off.",
                    "A PASS is a candidate for Part 7, not a rule. Look at LUCK % (low = good), at both halves, and at how many trades were blocked.",
                    "NET GAIN = money saved by blocking (minus the net of the blocked trades). Fee-correct net from Part 1. Hindsight numbers: a live filter sees the same signal only once.",
                    "MOVES LOST counts only moves that a trade of that scope caught before; a move caught by two trades is lost only if the filter blocks both.",
                    "Rows come from Part 1 and moves from Part 3A; if trades changed since, run Part 1 and 3A again first.",
                    "Python Z vs Pine Z is still unchecked (README_FILTER), so Z numbers are the engine Z."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 4: filter lab, train / test (read-only)")
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
