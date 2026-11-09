"""v2_f6_decisions.py - FILTER STUDY Part 6: THE ENTER / WAIT / REJECT / NO_TRADE LOG (read-only). Main and Sniper always separate; scopes ALL timeframes and 5m only.
Measures only. No rule, no setting, no order, no network. Needs v2_f1_counts.py, v2_f1b_learn.py, v2_f2_fakes.py, v2_f3a_moves.py, v2_f4_filters.py, v2_f5a_exits.py. Reads v2_filter_trades.json (Part 1 rows), v2_filter_moves.json (Part 3A moves),
candles from v2_market.db, and chop_b3.db (b3 decision log, optional, read-only). Missing files are made first (all read-only).
THE FRAMEWORK (fixed definitions, nothing tuned) - every signal gets ONE of four words, with the reason, from two things measured at the signal candle:
  SETUP  band (Z zone) + TSI + EMA cloud agree with the trade side: COMPLETE 3/3, FORMING 2/3, WEAK 0-1/3 (Part 1 definition).
  CURVE  slope = price move of the last 5 candles WITH the trade side (% per candle); FLAT_EPS = 25th percentile of |slope| at the signal candle of the TRAIN trades of that timeframe (first 60% by time, TEST never touches it).
         FLAT = |slope| <= FLAT_EPS.  AGAINST = slope below -FLAT_EPS.  TURNING = slope with the side but smaller than 3 candles earlier.  RUNNING = slope with the side and not shrinking.
  ORDER  CURVE FLAT -> NO_TRADE (sideways, nothing to catch).  CURVE AGAINST or SETUP WEAK -> REJECT.  SETUP COMPLETE and CURVE RUNNING -> ENTER.  Everything else -> WAIT (watch: setup still forming or the curve is turning).
HOW THE LOG IS JUDGED (hindsight, on the real paper trades; the log has one row per trade in v2_filter_decisions.json):
  by_decision   per word: trades, wins, FAKES (Part 2 definition), net, in ALL / TRAIN / TEST (time-ordered, first 60% / last 40%).
  filters       "take only ENTER", "block NO_TRADE", "block REJECT", "block NO_TRADE + REJECT" judged like Part 4: net gain in both halves, moves lost (3%+ rallies / dumps of Part 3A caught before and by no trade after),
                verdict PASS / HELPS_BUT_LOSES_MOVES / FAILS_TEST / NO_HELP / TOO_FEW, LUCK % (random block of the same size on TEST).
  wait_test     WAIT trades: how many turned into ENTER within the next 3 candles; their net if entered late (at that candle close, same exit as the real trade ended) vs the net of the real entry; WAIT trades that never turned ENTER: their net.
  b3_overlay    every b3 decision (TAKE / SKIP) is given the same word from the saved 5m candles. Table: my word x b3 action x b3 verdict (WIN / LOSS / RALLY_MISSED / LOSS_AVOIDED / waiting) with count and net.
                b3 SKIP verdict money is b3's what-if at FULL size.
Honest limits: the four words are definitions made from the owner's own idea (README_FILTER: FLAT = ignore, TURNING = watch, RUNNING = enter), not fitted to money. If "take only ENTER" does not PASS, the words are a log, not a gate.
Fewer than 60 trades in a scope = NOT ENOUGH DATA. Day = 00:00 UTC = 5:30 AM IST. Durations over 60 min are written as hours + minutes.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f6_decisions.py --data /home/owl/owl_data --out -"""
import argparse
import bisect
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_engine as E
import owl_sniper_feed as F
import owl_sniper_ind_pairs as IP
import v2_f1_counts as X
import v2_f1b_learn as L
import v2_f2_fakes as K
import v2_f3a_moves as A3
import v2_f4_filters as Fm
import v2_f5a_exits as A5
import v2_inventory as I
import v2_pnl as P

VERSION = "v2_f6_decisions 1 (Filter Part 6)"
LOG_FILE = "v2_filter_decisions.json"
SLOPE_N, TURN_BARS, WAIT_BARS = 5, 3, 3
WORDS = ("ENTER", "WAIT", "NO_TRADE", "REJECT")
SCOPES = (("all", None), ("5m", "5m"))


# ----------------------------------------------------------------------------- the four words
def slope(S, j, side):
    """Price move of the last 5 candles WITH the trade side, % per candle."""
    if j < SLOPE_N or not S["c"][j - SLOPE_N]:
        return None
    return side * (S["c"][j] / S["c"][j - SLOPE_N] - 1.0) * 100.0 / SLOPE_N


def curve_state(s, p, eps):
    if s is None:
        return None
    if abs(s) <= eps:
        return "FLAT"
    if s < -eps:
        return "AGAINST"
    return "TURNING" if p is not None and s < p else "RUNNING"


def decide(setup, curve):
    if curve is None or not setup or setup == "n/a":
        return "NO_DATA"
    if curve == "FLAT":
        return "NO_TRADE"
    if curve == "AGAINST" or setup.startswith("WEAK"):
        return "REJECT"
    return "ENTER" if setup.startswith("COMPLETE") and curve == "RUNNING" else "WAIT"


def state_at(S, j, side, cfg, eps):
    s, p = slope(S, j, side), slope(S, j - TURN_BARS, side)
    setup = X.setup_numbers(S, j, side, cfg)["setup_b"]
    curve = curve_state(s, p, eps)
    return decide(setup, curve), curve, setup, s


def decide_trade(S, i0, end0, r, cfg, eps):
    """The word at the signal candle + the WAIT test (does it turn ENTER within 3 candles; money if entered late)."""
    word, curve, setup, s = state_at(S, i0, r["side"], cfg, eps)
    d = {"decision": word, "curve": curve, "setup": setup, "slope": round(s, 4) if s is not None else None, "late_bar": None, "late_net": None, "calib_net": None}
    ep, lev, inv, fee = r.get("entry_price"), r.get("lev"), r.get("invest"), r.get("fee_roi")
    if ep and lev and inv and fee is not None and end0 > i0:
        d["calib_net"] = round(A5.money(r["side"], ep, S["c"][end0], lev, fee, inv), 4)
        if word == "WAIT":
            for j in range(i0 + 1, min(i0 + WAIT_BARS, end0 - 1) + 1):
                if state_at(S, j, r["side"], cfg, eps)[0] == "ENTER":
                    d["late_bar"] = j - i0
                    d["late_net"] = round(A5.money(r["side"], S["c"][j], S["c"][end0], lev, fee, inv), 4)
                    break
    return d


# ----------------------------------------------------------------------------- candles -> words
def load_ctx(rows, store, cov):
    groups, ctx = {}, []
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
            ctx.append((r, S, i0, bisect.bisect_right(S["t"], r["close"]) - 1))
    return ctx


def flat_eps(ctx):
    """FLAT_EPS per timeframe = 25th percentile of |slope| at the signal candle of TRAIN trades."""
    if not ctx:
        return {}
    ents = sorted(c[0]["ent"] for c in ctx)
    cut, eps = ents[int(len(ents) * A5.TRAIN_FRAC)], {}
    for tf in X.TFS:
        v = sorted(abs(slope(S, i0, r["side"])) for r, S, i0, _e in ctx if r["tf"] == tf and r["ent"] < cut and slope(S, i0, r["side"]) is not None)
        if len(v) >= 10:
            eps[tf] = v[int(len(v) * 0.25)]
    return eps


def decide_all(rows, con, cfg_by_tf, cov):
    store = X.Candles(con, cfg_by_tf)
    ctx = load_ctx(rows, store, cov)
    eps = flat_eps(ctx)
    for r, S, i0, e0 in ctx:
        if r["tf"] in eps:
            r["d6"] = decide_trade(S, i0, e0, r, cfg_by_tf[r["tf"]], eps[r["tf"]])
            cov["decided"] += 1
    return eps, store


# ----------------------------------------------------------------------------- b3 overlay
def side_num(v):
    v = str(v or "").upper()
    return 1 if v in ("LONG", "BUY") else (-1 if v in ("SHORT", "SELL") else 0)


def b3_overlay(root, store, cfg, eps5):
    db = L.ro_db(root)
    if db is None:
        return {"present": False, "note": "b3 has no database yet (chop_b3.db). It is OFF by default, so this is normal until it is switched on."}
    try:
        decs = L.rows(db, "SELECT symbol, side, candle_ts, action, v_final, v_label, v_net FROM decisions")
    except Exception as e:
        return {"present": True, "error": "could not read decisions: %s" % str(e)[:120]}
    finally:
        db.close()
    if eps5 is None:
        return {"present": True, "decisions_read": len(decs), "note": "No FLAT_EPS for 5m (not enough 5m trades with candles), so the words cannot be made."}
    by_sym, table, done = {}, {}, 0
    for d in decs:
        by_sym.setdefault(d["symbol"], []).append(d)
    for sym, ds in by_sym.items():
        runs, step = store.load(sym, "5m", min(x["candle_ts"] for x in ds), max(x["candle_ts"] for x in ds))
        for d in ds:
            t, side = int(d["candle_ts"] - d["candle_ts"] % step), side_num(d["side"])
            hit = next(((S, idx[t]) for S, _a, idx in runs if t in idx), None)
            if hit is None or not side or hit[1] < E.warmup_end(hit[0]):
                continue
            word = state_at(hit[0], hit[1], side, cfg, eps5)[0]
            lab = (d["v_label"] if d["v_final"] else "waiting") or "waiting"
            cell = table.setdefault(word, {}).setdefault(str(d["action"]), {}).setdefault(lab, {"n": 0, "net_usdt": 0.0})
            cell["n"] += 1
            cell["net_usdt"] = round(cell["net_usdt"] + (d["v_net"] or 0.0), 3)
            done += 1
    return {"present": True, "decisions_read": len(decs), "decisions_given_a_word": done, "table_my_word_x_b3_action_x_b3_verdict": table}


# ----------------------------------------------------------------------------- report
def split_counts(sc, rs_idx):
    rows = sc["rows"]
    out = {"all": K.counts([rows[i] for i in rs_idx])}
    for p in ("train", "test"):
        part = set(sc["parts"][p]["idx"])
        out[p] = K.counts([rows[i] for i in rs_idx if i in part])
    return out


def wait_test(rows):
    w = [r for r in rows if r["d6"]["decision"] == "WAIT"]
    late = [r for r in w if r["d6"]["late_bar"] is not None and r["d6"]["late_net"] is not None and r["d6"]["calib_net"] is not None]
    never = [r for r in w if r["d6"]["late_bar"] is None]
    s = lambda rs, f: round(sum(f(r) for r in rs), 3)
    return {"wait_trades": len(w), "turned_ENTER_within_3_candles": len(late), "late_entry_net_usdt": s(late, lambda r: r["d6"]["late_net"]), "same_trades_real_entry_replay_net_usdt": s(late, lambda r: r["d6"]["calib_net"]),
            "same_trades_real_net_usdt": s(late, lambda r: r["net"]), "never_turned_ENTER": len(never), "never_turned_ENTER_real_net_usdt": s(never, lambda r: r["net"]),
            **({"label": "NOT ENOUGH DATA"} if len(w) < 30 else {})}


def scope_report(rows, moves, have_moves, seed):
    sc = Fm.make_scope(rows, moves)
    if sc is None:
        return {"label": "NOT ENOUGH DATA", "trades": len(rows), "need": Fm.MIN_SCOPE}
    rs, rng = sc["rows"], random.Random(seed)
    word = lambda i: rs[i]["d6"]["decision"]
    by = {w: split_counts(sc, [i for i in range(len(rs)) if word(i) == w]) for w in WORDS + ("NO_DATA",) if any(word(i) == w for i in range(len(rs)))}
    sets = {"take only ENTER": lambda w: w != "ENTER", "block NO_TRADE": lambda w: w == "NO_TRADE", "block REJECT": lambda w: w == "REJECT", "block NO_TRADE + REJECT": lambda w: w in ("NO_TRADE", "REJECT")}
    filt = []
    for name, f in sets.items():
        blocked = {i for i in range(len(rs)) if word(i) != "NO_DATA" and f(word(i))}
        j = Fm.judge(sc, name, "WORDS", blocked, have_moves)
        j["luck_random_as_good_pct"] = Fm.luck(sc, j["test"]["blocked"], j["test"]["net_gain"], rng)
        filt.append(Fm.short(j))
    return {"trades": len(rs), "split_utc": P.fmt_ts(sc["cut_t"]), "by_decision": by, "filters": filt, "wait_test": wait_test(rs),
            "how_often": {w: round(sum(1 for i in range(len(rs)) if word(i) == w) * 100.0 / len(rs), 1) for w in WORDS}}


def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "day_start": "00:00 UTC = 5:30 AM IST",
           "framework": "SETUP (band + TSI + EMA agree) x CURVE (slope of 5 candles with the side). FLAT -> NO_TRADE; AGAINST or WEAK -> REJECT; COMPLETE + RUNNING -> ENTER; else WAIT."}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    src = K.load_rows(root)
    if not src or not src.get("rows"):
        X.build_report(root, fee_roi)
        rep["note_rows"] = "v2_filter_trades.json was missing: Part 1 was run first."
        src = K.load_rows(root)
    mv = Fm.load_json(root, A3.MOVES_FILE)
    if not mv or not mv.get("moves"):
        try:
            A3.build_report(root)
        except Exception as e:
            rep["note_moves_error"] = str(e)[:200]
        mv = Fm.load_json(root, A3.MOVES_FILE)
    moves = [m for m in ((mv or {}).get("moves") or []) if (m.get("list") or {}).get("kind") != "CONTROL" and (m.get("size_pct") or 0) >= 3.0]
    have_moves = bool(moves)
    rep["moves_check"] = "ON (%d moves of 3%%+)" % len(moves) if have_moves else "NOT AVAILABLE: no moves file. Do not trust any PASS."
    rows, dropped = K.prepare((src or {}).get("rows") or [])
    cov = {"decided": 0, "no_candles": 0, "warmup": 0, "no_entry_close_side_tf": 0}
    con = F.open_ro(root)
    if con is None:
        rep["error"] = "No candle store (v2_market.db): the log needs candles."
        return rep
    cfg_by_tf = {}
    for tf in X.TFS:
        try:
            cfg_by_tf[tf] = IP.load_cfg(root, "15m" if tf == "15m" else "5m")[0]
        except Exception:
            cfg_by_tf[tf] = dict(E.DEFAULTS)
    try:
        eps, store = decide_all(rows, con, cfg_by_tf, cov)
        rep["b3_overlay"] = b3_overlay(root, store, cfg_by_tf["5m"], eps.get("5m"))
    finally:
        con.close()
    rep["rows_used"], rep["rows_without_net_result"], rep["coverage"] = len(rows), dropped, cov
    rep["FLAT_EPS_pct_per_candle (from TRAIN signal candles)"] = {tf: round(v, 4) for tf, v in eps.items()}
    done = [r for r in rows if r.get("d6")]
    for gi, g in enumerate(X.GROUPS):
        grs = [r for r in done if r["g"] == g]
        rep[g] = {nm: scope_report([r for r in grs if tf is None or r["tf"] == tf], moves, have_moves, 11 + gi * 10 + si) for si, (nm, tf) in enumerate(SCOPES)}
    log = [{"sym": r["sym"], "ent": r["ent"], "g": r["g"], "tf": r["tf"], "side": r["side"], "decision": r["d6"]["decision"], "curve": r["d6"]["curve"], "setup": r["d6"]["setup"],
            "slope": r["d6"]["slope"], "late_bar": r["d6"]["late_bar"], "kind": r["kind"], "net": r["net"]} for r in done]
    rep["log_file"] = {"name": LOG_FILE, "rows": len(log), "saved": F.write_json(root, LOG_FILE, {"tool": VERSION, "made_utc": rep["made_utc"], "rows": log})}
    rep["notes"] = ["Main and Sniper are never added together. Only paper trades. The four words are fixed definitions, not fitted to money.",
                    "A PASS for 'take only ENTER' or a block filter is a candidate for Part 7, not a rule. Look at both halves, moves lost and LUCK %.",
                    "wait_test late-entry money assumes entry at the close of the candle where the word turned ENTER and the same exit as the real trade.",
                    "b3 overlay: the word is made at b3's decision candle on 5m; b3 SKIP verdict money is b3's what-if at FULL size.",
                    "Python Z vs Pine Z is still unchecked (README_FILTER), so band numbers are the engine Z."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 6: ENTER / WAIT / REJECT / NO_TRADE log (read-only)")
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
