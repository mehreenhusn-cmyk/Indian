"""owl_sniper_watch.py - OwlSniper R33a (Part 15): the WATCHLIST SCAN ENGINE. PAPER ONLY, READ ONLY. No order, no live path, no new background worker.
Why: the Sniper only looked at "all coins" in one flat pile. The owner wants a short ranked list: the coins he cares about (Market Watch favourites) plus the coins that are moving now, with ONE plain line each: is a plan ARMED, is one close, or is it only moving.
What: one look at the saved 5m candles (market store, read only, same helpers as owl_sniper_explore.py). For every coin worth watching:
  WATCHLIST = Market Watch favourites (settings.json "favorites") + the TOP_MOVERS coins that moved most in the last hour. A coin that is both is marked BOTH.
  ARMED     = the plain signal (EMA cross + TSI + Z-Score, owl_sniper_engine_b.raw_signal) is on in the newest LOOKBACK candles. An armed row carries a preview of entry, stop and target (the same maths as an EXPLORE card). Win chance is NOT known: armed is not a promise.
  NEAR      = no signal, but the two EMAs are less than NEAR_GAP percent apart (a cross may come soon).
  MOVER/FAV = nothing yet, shown so the owner sees the coin and why it is on the list.
  MODE      = SCALP / SHORT_SWING / SWING of the coin's market state (owl_sniper_modes.mode_for). When that state has no learned verdict the mode is SHORT_SWING and mode_learned is false (the default, nothing is claimed).
Rank: ARMED first (newest first), then NEAR, then the rest by size of the 1 h move. armed_only = only the armed rows.
Writes ONE own file: v2_sniper_watch.json. Reads the market store read only, never writes it. Nothing here opens, closes or changes a trade. Dart cards come in Part 16.
API: scan(d, now=None, keep=KEEP), fresh(d, now=None) (saved result or a new scan when older than one candle step), pick_rows(res, armed_only). CLI: python3 backend/owl_sniper_watch.py [--data DIR]"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_engine_b as B
import owl_sniper_explore as EX
import owl_sniper_feed as F
import owl_sniper_tf as TF

VERSION = "owl_sniper_watch 1 (R33a)"
FILE = "v2_sniper_watch.json"
INTERVAL = F.INTERVAL
LOOKBACK = 3                      # an armed signal may be up to 3 candles old (same as the LEARN gate and EXPLORE)
MOVE_BACK = 12                    # the "1 h move" = 12 candles of 5m
MOVE_SHORT = 3                    # the "15 min move" = 3 candles
TOP_MOVERS = 10                   # the coins that moved most in the last hour join the list
NEAR_GAP = 0.10                   # EMA gap under 0.10 % of price = a cross may be close
KEEP = 30
NOTE = "ARMED = the plain signal is on. Win chance is unknown, this is not a promise. Paper only."


def favorites(d):
    """Market Watch favourites from settings.json (upper case), [] when missing. Never raises."""
    try:
        favs = (F.read_json(d, "settings.json") or {}).get("favorites") or []
        return [str(s).upper() for s in favs if isinstance(s, str)]
    except Exception:
        return []


def _mode(d, regime):
    """(mode, learned). The default SHORT_SWING when the state has no learned verdict."""
    try:
        import owl_sniper_modes as M
        m = M.mode_for(d, regime, INTERVAL)
        return (m, True) if m else ("SHORT_SWING", False)
    except Exception:
        return "SHORT_SWING", False


def _move(S, back):
    n = S["n"]
    if n <= back or float(S["c"][n - 1 - back]) <= 0:
        return None
    return (float(S["c"][n - 1]) / float(S["c"][n - 1 - back]) - 1.0) * 100.0


def row_for(d, sym, S, in_fav, in_mov):
    """ONE watchlist row from the indicator series of a coin. Never raises."""
    n = S["n"]
    i_new = n - 1
    mv1, mv15 = _move(S, MOVE_BACK), _move(S, MOVE_SHORT)
    regime = B.regime_at(S, i_new)
    mode, learned = _mode(d, regime)
    row = {"symbol": sym, "source": "BOTH" if in_fav and in_mov else ("FAV" if in_fav else "MOVER"), "state": "WATCH", "armed": False, "side": None, "age": None,
           "move_15m_pct": None if mv15 is None else round(mv15, 2), "move_1h_pct": None if mv1 is None else round(mv1, 2),
           "regime": regime, "mode": mode, "mode_learned": learned, "price": round(float(S["c"][i_new]), 8), "t": S["t"][i_new]}
    for i in range(i_new, max(n - 1 - LOOKBACK, 0), -1):
        sig = B.raw_signal(S, i)
        if sig.get("side"):
            c = EX._card(sym, S, i, sig)
            age = i_new - i
            row.update(state="ARMED", armed=True, side=sig["side"], age=age, regime=sig.get("regime") or regime)
            if c:
                row.update(entry_price=c["entry_price"], stop_loss=c["stop_loss"], take_profit=c["take_profit"], stop_pct=c["stop_pct"], rr=c["rr"])
            row["reason"] = "%s armed %s: %s. Mode %s%s." % (sig["side"], "on the newest candle" if age == 0 else "%d candle%s ago" % (age, "" if age == 1 else "s"),
                                                             (sig.get("why") or ["signal"])[0], mode, "" if learned else " (default)")
            return row
    gap = S["gap_pct"][i_new] if S.get("gap_pct") else None
    if gap is not None and gap < NEAR_GAP:
        row.update(state="NEAR", reason="No signal yet, but the two EMAs are only %.2f%% apart: a cross may come soon. Market %s." % (gap, regime.lower()))
    else:
        mvtxt = "no move data" if mv1 is None else "%s%.2f%% in the last hour" % ("+" if mv1 >= 0 else "", mv1)
        row["reason"] = "%s, no signal yet. %s." % ("Your favourite" if row["source"] != "MOVER" else "Big mover", mvtxt)
    return row


def rank_key(r):
    tier = 0 if r["state"] == "ARMED" else (1 if r["state"] == "NEAR" else 2)
    return (tier, r["age"] if r["age"] is not None else 99, -abs(r["move_1h_pct"] or 0.0))


def scan(d, now=None, keep=KEEP):
    """One look at the saved candles -> the ranked watchlist (saved). Never raises."""
    now = int(time.time() if now is None else now)
    out = {"version": VERSION, "saved_at": now, "interval": INTERVAL, "note": NOTE, "paper_only": True, "scanned": 0, "stale": 0, "fav_n": 0, "armed_n": 0, "near_n": 0, "rows": []}
    try:
        favs = set(favorites(d))
        con = F.open_ro(d)
        if con is None:
            out["state"] = "NO_DATA"
            out["text"] = "No candle store yet."
            F.write_json(d, FILE, out)
            return out
        step, series = TF.step(INTERVAL), {}
        try:
            for sym in F.symbols(con, INTERVAL, F.MAX_COINS):
                run = F.newest_run(F.load_tail(con, sym, INTERVAL), INTERVAL)
                if not run or run[-1][0] + F.STALE_STEPS * step < now:
                    out["stale"] += 1
                    continue
                try:
                    series[sym] = B.build_features(run)
                except ValueError:
                    continue
                out["scanned"] += 1
        finally:
            con.close()
        movers = sorted(((abs(_move(S, MOVE_BACK) or 0.0), sym) for sym, S in series.items()), reverse=True)
        top = set(sym for m, sym in movers[:TOP_MOVERS] if m > 0)
        rows = [row_for(d, sym, S, sym in favs, sym in top) for sym, S in series.items() if sym in favs or sym in top]
        rows.sort(key=rank_key)
        for k, r in enumerate(rows, 1):
            r["rank"] = k
        out.update(state="OK", rows=rows[:keep], fav_n=len([s for s in series if s in favs]), armed_n=sum(r["state"] == "ARMED" for r in rows),
                   near_n=sum(r["state"] == "NEAR" for r in rows))
        out["text"] = "%d coins watched, %d armed, %d close to a signal." % (len(rows), out["armed_n"], out["near_n"]) if rows else "No favourite or big mover has fresh candles right now."
    except Exception as e:
        out["state"] = "ERROR"
        out["text"] = str(e)[:80]
    F.write_json(d, FILE, out)
    return out


def fresh(d, now=None):
    """The saved result when it is younger than one candle step, else a new scan."""
    now = time.time() if now is None else now
    old = F.read_json(d, FILE)
    if old and old.get("state") == "OK" and now - (old.get("saved_at") or 0) < TF.step(INTERVAL):
        return old
    return scan(d, now)


def pick_rows(res, armed_only=False):
    """The result with only the armed rows when asked (counts stay the same)."""
    if not armed_only:
        return res
    out = dict(res)
    out["rows"] = [r for r in (res.get("rows") or []) if r.get("armed")]
    out["armed_only"] = True
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper watchlist scan (paper only, read only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    a = ap.parse_args(argv)
    r = scan(a.data)
    print(r.get("state"), r.get("text"))
    for x in r.get("rows") or []:
        print("%2d %-12s %-6s %-5s %s" % (x["rank"], x["symbol"], x["state"], x["source"], x["reason"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
