"""v2_radar_outcomes.py - Part 31: RADAR 3 of 6 (backend, read-only). "What did those saved cohort coins do 1 / 2 / 3 / 7 days after the snapshot?"
For every coin of a saved 00:00 UTC cohort (cohort_official, labels AUTHENTIC / PROXY kept as the collector stored them) it finds the price saved NEAR the
horizon time (snapshot time + 1 / 2 / 3 / 7 days, within 1 hour; from ticker_snapshot or a closed 3m / 5m candle) and puts the move since the snapshot price
into ONE class (definition version 1, starting values NOT validated, change them in the constants below):
  GAINER coins: FURTHER_PUMP (up 10% or more) | CONTINUATION (up 3% to 10%) | SIDEWAYS (between -3% and +3%) | REVERSAL (down 3% or more)
  LOSER coins : FURTHER_DUMP (down 10% or more) | CONTINUATION (down 3% to 10%) | SIDEWAYS | REVERSAL (up 3% or more)
  UNRESOLVED = no price saved near the horizon time (the coin was outside the saved data): UNKNOWN, never "flat". PENDING = the horizon is not over yet.
Rules (README4 section 9.5): a horizon that is not finished is labelled PENDING and never judged; a missing price is never invented; AUTHENTIC and PROXY cohorts are
counted apart; days and sides are never added together; counts show how many coins stand behind them; no prediction, no win rate, no pattern claim.
Read-only: the store is opened with mode=ro and is never created here. No network, no trading module, no ledger row.
Part 32: every coin row says whether it STARTS an episode or repeats one (v2_radar_episodes), and the counts are given for all rows and for new episodes only.
Run (Termux):  python3 backend/v2_radar_outcomes.py [--data DIR] [--day YYYY-MM-DD | --days N]     Route: GET /api/v2/radar_outcomes[?day= | ?days=] (Part 31, api/v2_data.py)."""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_radar as RD
import v2_radar_episodes as EP

VERSION = "v2_radar_outcomes 2 (Part 31 + 32)"
DEF_VERSION = 1
HORIZONS = (1, 2, 3, 7)           # days after the cohort snapshot
SIDEWAYS_PCT = 3.0                # starting value (NV): inside this band = SIDEWAYS
STRONG_PCT = 10.0                 # starting value (NV): this much or more in the cohort's direction = FURTHER_PUMP / FURTHER_DUMP
TOL_SEC = 3600                    # a horizon price must be saved within 1 hour of the horizon time
CLASSES = ("FURTHER_PUMP", "FURTHER_DUMP", "CONTINUATION", "SIDEWAYS", "REVERSAL", "UNRESOLVED", "PENDING")


def classify(kind, move):
    """move = % change from the snapshot price to the horizon price (None = no price). -> one class word."""
    if move is None:
        return "UNRESOLVED"
    m = move if kind == "GAINER" else -move           # m above 0 = the same direction as the cohort side
    if m >= STRONG_PCT:
        return "FURTHER_PUMP" if kind == "GAINER" else "FURTHER_DUMP"
    if m >= SIDEWAYS_PCT:
        return "CONTINUATION"
    if m > -SIDEWAYS_PCT:
        return "SIDEWAYS"
    return "REVERSAL"


def price_near(con, sym, target, tol=TOL_SEC):
    """The saved price closest to the target time (within tol): the newer-fitting of a snapshot and a closed candle. -> (gap sec, price, ts, source) or None."""
    best = None
    r = con.execute("SELECT run_ts, price FROM ticker_snapshot WHERE symbol=? AND price>0 AND run_ts BETWEEN ? AND ? ORDER BY ABS(run_ts-?) LIMIT 1",
                    (sym, target - tol, target + tol, target)).fetchone()
    if r:
        best = (abs(r[0] - target), r[1], r[0], "ticker_snapshot")
    for iv, sec in RD.IV_SEC.items():
        c = con.execute("SELECT open_ts, c FROM candles WHERE symbol=? AND interval=? AND c>0 AND open_ts+%d BETWEEN ? AND ? ORDER BY ABS(open_ts+%d-?) LIMIT 1" % (sec, sec),
                        (sym, iv, target - tol, target + tol, target)).fetchone()
        if c:
            cand = (abs(c[0] + sec - target), c[1], c[0] + sec, "candle_" + iv)
            if best is None or cand[0] < best[0]:
                best = cand
    return best


def row_outcomes(con, kind, sym, op, sts, now):
    """-> {"1": {...}, "2": {...}, "3": {...}, "7": {...}} one class per horizon."""
    out = {}
    for h in HORIZONS:
        if not sts or not op or float(op) <= 0:
            out[str(h)] = {"class": "UNRESOLVED", "note": "no snapshot price or time saved for this coin"}
            continue
        target = int(sts) + h * 86400
        if int(now) < target + TOL_SEC:
            out[str(h)] = {"class": "PENDING", "ready_utc": RD._utc(target + TOL_SEC)}
            continue
        p = price_near(con, sym, target)
        if not p:
            out[str(h)] = {"class": "UNRESOLVED", "note": "no price saved within 1 hour of the horizon time: UNKNOWN, not flat"}
            continue
        mv = RD._pct(p[1], op)
        out[str(h)] = {"class": classify(kind, mv), "move_pct": mv, "price": p[1], "price_utc": RD._utc(p[2]), "price_from": p[3]}
    return out



def _count(rows):
    """horizon -> source -> side -> class counts + how many coins. AUTHENTIC and PROXY are never mixed."""
    res = {}
    for r in rows:
        for h, o in r["outcomes"].items():
            e = res.setdefault(h, {}).setdefault(r["source"], {}).setdefault(r["kind"], dict({c: 0 for c in CLASSES}, coins=0))
            e["coins"] += 1
            e[o["class"]] += 1
    return res


def _day(con, day, now, emap):
    rows = con.execute("SELECT kind, rank, symbol, open_price, snap_ts, source FROM cohort_official WHERE day=? ORDER BY kind, rank", (day,)).fetchall()
    if not rows:
        return {"day": day, "status": "MISSING", "rows": [], "note": "no official cohort was saved for this day. It is never filled in from other data."}
    out = []
    for kind, rank, sym, op, sts, src in rows:
        out.append({"kind": kind, "rank": rank, "symbol": sym, "source": src, "snap_utc": RD._utc(sts) if sts else None,
                    "snapshot_price": op, "episode": emap.get((sym, kind, day)), "outcomes": row_outcomes(con, kind, sym, op, sts, now)})
    new = [r for r in out if not (r["episode"] or {}).get("repeat")]
    return {"day": day, "status": "OK", "coins": len(out), "episodes": {"rows": len(out), "new_episodes": len(new), "repeats": len(out) - len(new)},
            "summary": _count(out), "summary_new_episodes_only": _count(new), "rows": out}


def build(con, now=None, day=None, days=None):
    """-> the report dict (read-only). Same day / days choice as Radar 1-2 (default the newest 2 days). Raises ValueError on a bad day / days."""
    now = int(time.time() if now is None else now)
    exp, shown = RD.pick_days(now, day, days)
    emap = EP.mark(EP.episodes(con))
    res = [_day(con, d, now, emap) for d in shown]
    for r in res:
        r["tab"] = RD.tab_label(exp.index(r["day"])) if r["day"] in exp else None
    return {"tool": VERSION, "made_utc": RD._utc(now), "read_only": True, "definition_version": DEF_VERSION, "horizons_days": list(HORIZONS),
            "definition": {"sideways_pct": SIDEWAYS_PCT, "strong_pct": STRONG_PCT, "price_window_sec": TOL_SEC, "classes": list(CLASSES),
                           "note": "starting values, not validated; a class is a description of what the saved prices did, not a forecast"},
            "days": res,
            "notes": ["A horizon that is not over yet is PENDING and never judged; a coin with no saved price near the horizon is UNRESOLVED (unknown), never flat.",
                      "AUTHENTIC and PROXY cohorts are counted apart; days and sides are never added together; every count shows how many coins stand behind it.",
                      "Price near the horizon = a saved 5-minute top-list snapshot or a closed 3m / 5m candle within 1 hour of the horizon time. Coins outside the saved data stay UNRESOLVED.",
                      "Episode rule (Part 32): the same coin on the same side on consecutive days is ONE episode; use summary_new_episodes_only when you count samples.",
                      "No prediction, no win rate, no pattern claim: that needs many episodes AND counterexamples."]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Owl Radar outcomes (read-only)")
    ap.add_argument("--data")
    ap.add_argument("--day")
    ap.add_argument("--days", help="1 to 7: the newest N saved cohorts (default 2)")
    a = ap.parse_args(argv)
    import v2_inventory as I
    import v2_store as S
    path = S.store_path(I.find_data_dir(a.data))
    if not os.path.isfile(path):
        print("The market store is not created yet: nothing to report.")
        return 0
    con = sqlite3.connect("file:%s?mode=ro" % urllib.parse.quote(path), uri=True, timeout=5)
    con.execute("PRAGMA query_only=ON")
    try:
        print(json.dumps(build(con, day=a.day, days=a.days), indent=2, default=str))
    except ValueError as e:
        print("STOP:", e)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
