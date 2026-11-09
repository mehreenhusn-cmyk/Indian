"""v2_f1b_learn.py - FILTER STUDY Part 1B: what did Sniper LEARN really learn, and what is b3 doing? (read-only, Question 8 of README_FILTER).
Measures only. No rule, no setting, no order. Opens chop_b3.db READ-ONLY (never creates it). No network.
Reads:  v2_sniper_learn.json (LEARN state), the closed paper trades (same readers as Part 1; lane LEARN = source sniper_learn, lane REAL_GATE = source sniper),
        v2_filter_trades.json from Part 1 (entry numbers, optional: used when it exists), v2_sniper_lessons.json (optional), chop_b3.db (optional, b3 is OFF by default).
SNIPER LEARN block:
  state      switch, floor, size, kill switch, closed n / wins / losses / pnl as LEARN counted them, orders made vs opened, the 30-trade verdict line.
  trades     LEARN vs REAL_GATE from the archive: n, win %, net, exit kinds, sides, timeframes; per UTC day (last 14); LEARNING CURVE = blocks of 10 closed trades in time order
             and first half vs second half (is it getting better? facts, no verdict under 30 trades); check that the archive count matches the LEARN counter.
  numbers    LEARN trades split by the Part 1 entry numbers (setup status, SD shape, list side, nth of day) when v2_filter_trades.json is there.
  lessons    the Sniper's own lessons file, trimmed.
b3 block (chop_b3.db):
  totals     decisions TAKE / SKIP, skips judged vs waiting, closed paper trades, win %, net, open trades.
  ledger     RALLY_MISSED vs LOSS_AVOIDED (count + USDT, what-if at FULL size, net of cost), per rule, per score band, per UTC day (last 14), 10 biggest missed rallies.
Day = 00:00 UTC = 5:30 AM IST. Durations over 60 min are hours + minutes. Fewer than 30 rows = NOT ENOUGH DATA.
Run (VPS):  cd /home/owl/Indian-main/backend && python3 v2_f1b_learn.py --data /home/owl/owl_data --out -"""
import argparse
import datetime
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_f1_counts as X
import v2_inventory as I
import v2_pnl as P

VERSION = "v2_f1b_learn 1 (Filter Part 1B)"
MIN_N = 30
LEARN_FILE, LESSONS_FILE, B3_DB = "v2_sniper_learn.json", "v2_sniper_lessons.json", "chop_b3.db"
FULL_USDT = 10.0                      # chop_bot.FULL_USDT: b3 what-if money is per FULL-size trade
SCORE_BANDS = ((40, "< 40"), (60, "40-59"), (70, "60-69"), (80, "70-79"), (1000, ">= 80"))
NUMBER_TABLES = (("setup_b", "setup status"), ("shape_b", "SD band shape"), ("z_side_b", "Z zone (with side)"), ("list_b", "gainer / loser list"), ("nth_b", "nth trade of the day"))


def day_of(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")


def read_json(root, name):
    try:
        with open(os.path.join(root, name), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def trim(o, depth=3, n=12):
    """Small copy of a json value (depth and list length limited) so a big file never floods the report."""
    if depth <= 0:
        return "..."
    if isinstance(o, dict):
        return {str(k): trim(v, depth - 1, n) for k, v in list(o.items())[:40]}
    if isinstance(o, list):
        return [trim(v, depth - 1, n) for v in o[-n:]]
    return o if not isinstance(o, str) else o[:200]


def label(n):
    return {"label": "NOT ENOUGH DATA"} if n < MIN_N else {}


# ----------------------------------------------------------------------------- SNIPER LEARN
def learn_state(root, archive_learn):
    s = read_json(root, LEARN_FILE)
    if not isinstance(s, dict):
        return {"present": False, "note": "No LEARN state file yet (v2_sniper_learn.json)."}
    cl, orders = s.get("closed") or {}, s.get("orders") or []
    opened = sum(1 for o in orders if isinstance(o, dict) and o.get("opened"))
    n = cl.get("n", 0)
    out = {"present": True, "enabled": s.get("enabled"), "floor": s.get("floor"), "size_usdt": s.get("size_usdt"), "max_open": s.get("max_open"),
           "kill_on": (s.get("kill") or {}).get("on"), "kill_reason": (s.get("kill") or {}).get("reason") or None, "open_now": len(s.get("open") or {}),
           "closed_by_learn_counter": {"n": n, "wins": cl.get("wins", 0), "losses": cl.get("losses", 0), "pnl_usdt": cl.get("pnl", 0.0)},
           "orders_kept": len(orders), "orders_opened": opened, "orders_not_opened": len(orders) - opened,
           "verdict": "LEARN trades %d of 30. %s" % (n, "NOT ENOUGH DATA for a verdict yet." if n < 30 else "Enough trades to judge (still paper).")}
    out["archive_learn_trades"] = len(archive_learn)
    out["counter_matches_archive"] = None if not archive_learn else (abs(len(archive_learn) - n) <= 2)
    if s.get("log"):
        out["last_log_lines"] = [str(x)[:160] for x in s["log"][-6:]]
    return out


def curve(rows):
    """Learning curve in time order: blocks of 10 closed LEARN trades + first half vs second half."""
    rs = sorted((r for r in rows if r.get("net") is not None and r.get("close")), key=lambda r: r["close"])
    blocks = []
    for k in range(0, len(rs) - len(rs) % 10, 10):
        b = rs[k:k + 10]
        blocks.append({"trades": "%d-%d" % (k + 1, k + 10), "win_pct": round(sum(1 for r in b if r["net"] > 0) * 10.0, 1), "net_usdt": round(sum(r["net"] for r in b), 4),
                       "from_utc": P.fmt_ts(b[0]["close"])})
    half = len(rs) // 2
    out = {"blocks_of_10": blocks[-20:], "closed_trades": len(rs)}
    if len(rs) >= MIN_N:
        out["first_half"], out["second_half"] = X.stats(rs[:half]), X.stats(rs[half:])
        out["reading"] = "Facts only: compare win_pct and avg_net_usdt of the two halves. No verdict is made here."
    else:
        out["label"] = "NOT ENOUGH DATA"
    return out


def per_day(rows, days=14):
    by = {}
    for r in rows:
        if r.get("close"):
            by.setdefault(day_of(r["close"]), []).append(r)
    return {d: X.stats(by[d]) for d in sorted(by)[-days:]}


def learn_trades(rows):
    out = {}
    for lane in ("LEARN", "REAL_GATE"):
        rs = [r for r in rows if r["lane"] == lane]
        blk = {"all": X.stats(rs), "by_timeframe": {tf: X.stats([r for r in rs if r["tf"] == tf]) for tf in X.TFS if any(r["tf"] == tf for r in rs)},
               "by_side": {nm: X.stats([r for r in rs if r["side"] == sd]) for nm, sd in (("LONG", 1), ("SHORT", -1)) if any(r["side"] == sd for r in rs)},
               "exit_kinds": {k: sum(1 for r in rs if r["exit_b"] == k) for k in X.CATS["exit"] if any(r["exit_b"] == k for r in rs)},
               "last_14_days": per_day(rs)}
        if lane == "LEARN":
            blk["learning_curve"] = curve(rs)
        out[lane] = blk
    return out


def learn_numbers(rows, filt_rows):
    """LEARN trades split by the Part 1 entry numbers (needs v2_filter_trades.json)."""
    if not filt_rows:
        return {"present": False, "note": "v2_filter_trades.json not found: run Part 1 (v2_f1_counts.py) first, then run this again."}
    by_id = {str(r.get("id")): r for r in filt_rows}
    got = []
    for r in rows:
        f = by_id.get(str(r.get("id")))
        if r["lane"] == "LEARN" and f and f.get("setup_b") is not None:
            got.append(f)
    out = {"present": True, "learn_trades_with_numbers": len(got), "tables": {}}
    for key, title in NUMBER_TABLES:
        names = sorted({g.get(key) for g in got if g.get(key)})
        out["tables"][title] = {nm: X.stats([g for g in got if g.get(key) == nm]) for nm in names}
    return out


# ----------------------------------------------------------------------------- b3
def ro_db(root):
    path = os.path.join(root, B3_DB)
    if not os.path.isfile(path):
        return None
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def usdt(pct):
    return round((pct or 0.0) / 100.0 * FULL_USDT, 3)


def band(score):
    if score is None:
        return "no score"
    return next(nm for top, nm in SCORE_BANDS if score < top)


def b3_block(root):
    db = ro_db(root)
    if db is None:
        return {"present": False, "note": "b3 has no database yet (chop_b3.db). It is OFF by default, so this is normal until it is switched on."}
    try:
        out = {"present": True, "what_if_note": "SKIP money = what the skipped signal would have made at FULL size (%.0f USDT), net of cost. A what-if, never a real trade." % FULL_USDT}
        dc = db.execute("SELECT COUNT(*) n, COALESCE(SUM(action='TAKE'),0) t, COALESCE(SUM(action='SKIP'),0) s, MIN(candle_ts) a, MAX(candle_ts) b FROM decisions").fetchone()
        out["decisions"] = {"all": dc["n"], "take": dc["t"], "skip": dc["s"], "first_utc": P.fmt_ts(dc["a"]) if dc["a"] else None, "last_utc": P.fmt_ts(dc["b"]) if dc["b"] else None}
        out["skips"] = {"judged": db.execute("SELECT COUNT(*) FROM decisions WHERE action='SKIP' AND v_final=1 AND v_label IN ('RALLY_MISSED','LOSS_AVOIDED')").fetchone()[0],
                        "waiting_for_verdict": db.execute("SELECT COUNT(*) FROM decisions WHERE action='SKIP' AND v_final=0").fetchone()[0]}
        tr = db.execute("SELECT COUNT(*) n, COALESCE(SUM(net_usdt>0),0) w, COALESCE(SUM(net_usdt),0) usdt FROM trades WHERE status='CLOSED'").fetchone()
        out["trades"] = {"closed": tr["n"], "wins": tr["w"], "win_pct": round(tr["w"] * 100.0 / tr["n"], 1) if tr["n"] else None, "net_usdt": round(tr["usdt"], 3),
                         "open_now": db.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0], **label(tr["n"])}
        sk = {r["v_label"]: r for r in db.execute("SELECT v_label, COUNT(*) n, COALESCE(SUM(v_net),0) net FROM decisions WHERE action='SKIP' AND v_final=1 AND v_label IN ('RALLY_MISSED','LOSS_AVOIDED') GROUP BY v_label").fetchall()}
        rm, la = sk.get("RALLY_MISSED"), sk.get("LOSS_AVOIDED")
        out["ledger"] = {"rally_missed": {"n": rm["n"] if rm else 0, "usdt_what_if": usdt(rm["net"]) if rm else 0.0},
                         "loss_avoided": {"n": la["n"] if la else 0, "usdt_what_if": usdt(-la["net"]) if la else 0.0}}
        j = (rm["n"] if rm else 0) + (la["n"] if la else 0)
        out["ledger"].update(label(j))
        out["per_rule"] = [dict(r, usdt=usdt(r["net"]) if r["action"] == "TAKE" else usdt(-r["net"]), right_pct=round(100.0 * r["ok_n"] / r["judged"], 1), **label(r["judged"]))
                           for r in rows(db, "SELECT action, rule, COUNT(*) judged, COALESCE(SUM(v_label IN ('WIN','LOSS_AVOIDED')),0) ok_n, COALESCE(SUM(v_net),0) net FROM decisions "
                                             "WHERE v_final=1 AND v_label IN ('WIN','LOSS','RALLY_MISSED','LOSS_AVOIDED') GROUP BY action, rule ORDER BY judged DESC LIMIT 30")]
        for r in out["per_rule"]:
            r.pop("net", None)
        bands, days = {}, {}
        for r in rows(db, "SELECT action, score, candle_ts, v_final, v_label FROM decisions"):
            b = bands.setdefault(band(r["score"]), {"take": 0, "skip": 0, "judged": 0, "right": 0})
            b["take" if r["action"] == "TAKE" else "skip"] += 1
            if r["v_final"] and r["v_label"] in ("WIN", "LOSS", "RALLY_MISSED", "LOSS_AVOIDED"):
                b["judged"] += 1
                b["right"] += r["v_label"] in ("WIN", "LOSS_AVOIDED")
            d = days.setdefault(day_of(r["candle_ts"]), {"take": 0, "skip": 0})
            d["take" if r["action"] == "TAKE" else "skip"] += 1
        out["per_score_band"] = {nm: dict(bands[nm], right_pct=round(bands[nm]["right"] * 100.0 / bands[nm]["judged"], 1) if bands[nm]["judged"] else None, **label(bands[nm]["judged"]))
                                 for _t, nm in SCORE_BANDS + ((0, "no score"),) if nm in bands}
        out["per_day_last_14"] = {d: days[d] for d in sorted(days)[-14:]}
        out["biggest_missed_rallies"] = [{"symbol": r["symbol"], "side": r["side"], "when_utc": P.fmt_ts(r["candle_ts"]), "rule": r["rule"], "score": r["score"], "would_net_pct": round(r["v_net"], 2),
                                         "would_usdt": usdt(r["v_net"]), "why": (r["why"] or "")[:120]}
                                        for r in rows(db, "SELECT symbol, side, candle_ts, rule, score, v_net, why FROM decisions WHERE action='SKIP' AND v_final=1 AND v_label='RALLY_MISSED' ORDER BY v_net DESC LIMIT 10")]
        return out
    except sqlite3.Error as e:
        return {"present": True, "error": "could not read chop_b3.db: %s" % str(e)[:120]}
    finally:
        db.close()


# ----------------------------------------------------------------------------- report
def build_report(root, fee_roi=1.0):
    root = os.path.realpath(root)
    rep = {"tool": VERSION, "made_utc": P.fmt_ts(time.time()), "read_only": True, "min_rows_per_block": MIN_N, "day_start": "00:00 UTC = 5:30 AM IST"}
    if not os.path.isdir(root):
        rep["error"] = "data folder not found"
        return rep
    trades, _st = X.load_trades(root)
    allr = [X.label_trade(t, fee_roi) for t in trades]
    snip = [r for r in allr if r["g"] == "SNIPER" and not (r["box"] and not str(r["box"]).startswith("paper"))]
    filt = (read_json(root, X.ROWS_FILE) or {}).get("rows")
    rep["sniper_learn"] = {"state": learn_state(root, [r for r in snip if r["lane"] == "LEARN"]), "trades": learn_trades(snip), "entry_numbers": learn_numbers(snip, filt)}
    les = read_json(root, LESSONS_FILE)
    rep["sniper_learn"]["lessons"] = trim(les) if les else {"present": False, "note": "No lessons file yet (v2_sniper_lessons.json)."}
    rep["b3"] = b3_block(root)
    rep["notes"] = ["Read-only. Nothing in trading was changed.",
                    "LEARN trades are tiny (1 USDT, 1x) and take sideways signals on purpose, so their win % is NOT the real bot's win %.",
                    "b3 what-if money is at FULL size. TAKE money is its real paper result.",
                    "To compare b3 with the Current bot on the same signals use chop_same.py (already in the repo)."]
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Filter study Part 1B: Sniper LEARN report + b3 log report (read-only)")
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
