"""v2_bt_dash.py - Part M3: BRAIN DASHBOARD (backend, read-only). Mock pictures 11 (Owl home) and 15 (Crypto dashboard), taken as IDEAS, only with REAL numbers.
ONE answer for the home screen, for ONE source (PAPER by default; REPLAY and SHADOW are never added to it):
  today        the Brain's closed trades of today (UTC day): net, gross, fees, slippage, closed count, percent of the guard capital, and the Current Bot's net of today (a separate number).
  decisions    today's Brain decisions: taken / waited / skipped / no opinion (the 'Today Signals' box).
  open         Brain trades that are still open: long, short, total.
  pace30       the last 30 days: Brain net, Current Bot net, trades of each. The Brain and the Current Bot are DIFFERENT trades, so these are two separate numbers, never added.
  risk         the DAILY LOSS CAP of the guard (v2_bt_guard): cap in USDT, used today (a net loss only), percent used, hit yes / no, kill switch on / off. Used = today's net loss of this source, 0 when today is in profit.
  recent       the last 8 days (oldest first) with Brain net and Bot net, for the strip at the bottom of the screen.
  all_time     the Brain's net and the number of closed trades over its whole history (NOT an account balance: no equity is invented).
  why          the Brain's own sentence from the Part L1 trend (IMPROVING / WORSE / NOT CLEAR / EARLY HINT / NOT ENOUGH DATA), with its luck warning.
Nothing is saved, nothing is traded. Reads v2_brain_trader.db read-only, and the Current Bot's archive through the same loader as the Results screen. No network, no write, no trading import.
Route /api/v2/brain_dash?source=PAPER (api/v2_data.py) calls build().
Run (Termux, optional):  python3 backend/v2_bt_dash.py [--data DIR] [--source PAPER]  -> the plain lines."""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_compare as CP
import v2_bt_guard as G
import v2_bt_progress as PG
import v2_bt_review as RV
import v2_bt_store as B

VERSION = "v2_bt_dash 1 (Part M3)"
DAY = 86400
RECENT = 8


def open_counts(con, source):
    """Brain trades with no close yet, split by side."""
    q = ("SELECT o.side, COUNT(*) FROM bt_trade_open o LEFT JOIN bt_trade_close c ON c.trade_id=o.trade_id WHERE o.source=? AND c.trade_id IS NULL GROUP BY o.side")
    d = dict(con.execute(q, (source,)).fetchall())
    return {"long": d.get("LONG", 0), "short": d.get("SHORT", 0), "total": sum(d.values())}


def risk_of(con, source, now):
    """The daily loss cap of the guard and how much of it today's net loss has used. A profit day uses 0."""
    cfg = G.get_config(con)
    cap = cfg["capital_usdt"] * cfg["daily_loss_cap_pct"] / 100.0
    used = max(0.0, -G.daily_net(con, source, now))
    pct = used / cap * 100.0 if cap > 0 else 0.0
    return {"cap_usdt": round(cap, 2), "cap_pct": cfg["daily_loss_cap_pct"], "capital_usdt": cfg["capital_usdt"], "used_usdt": round(used, 2), "used_pct": round(pct, 1),
            "hit": bool(cap > 0 and used >= cap), "kill_switch": bool(G.is_killed(con))}


def pace_of(cal):
    """The calendar of the compare part (newest first, up to 30 days) -> two separate sums."""
    return {"days": len(cal), "brain_usdt": round(sum(d["brain_usdt"] for d in cal), 2), "brain_trades": sum(d["brain_trades"] for d in cal),
            "bot_usdt": round(sum(d["bot_usdt"] for d in cal), 2), "bot_trades": sum(d["bot_trades"] for d in cal)}


def build(data_dir, source="PAPER", now=None):
    if source not in B.SOURCES:
        raise ValueError("source must be REPLAY, PAPER or SHADOW")
    now = int(time.time() if now is None else now)
    con = B.open_ro(data_dir)
    if con is None:
        return {"ready": False, "framework": VERSION, "source": source, "live": "LOCKED", "note": "No Brain Trader file yet: nothing has been saved. Run the Brain tick first."}
    bot = CP.bot_rows(data_dir)
    a = now - now % DAY
    try:
        brain = CP.brain_day(con, source, a, a + DAY)
        cal = CP.calendar(con, bot, source, now)
        trades = RV.closed_trades(con, source)
        opened, risk = open_counts(con, source), risk_of(con, source, now)
    finally:
        con.close()
    cap = G.DEFAULTS["capital_usdt"]
    bot_today = round(sum(n for ts, n in bot if a <= ts < a + DAY), 2)
    tr = PG.trend(trades)
    today = {k: brain[k] for k in ("closed", "net_usdt", "gross_usdt", "fees_usdt", "slippage_usdt")}
    today.update(pct_of_capital=round(brain["net_usdt"] / cap * 100.0, 2), bot_net_usdt=bot_today, bot_pct_of_capital=round(bot_today / cap * 100.0, 2))
    recent = [{"day": d["day"], "brain_usdt": d["brain_usdt"], "bot_usdt": d["bot_usdt"]} for d in reversed(cal[:RECENT])]
    return {"ready": True, "framework": VERSION, "source": source, "live": "LOCKED", "capital_usdt": cap, "today": today, "decisions": brain["decisions"], "open": opened, "pace30": pace_of(cal),
            "risk": risk, "recent": recent, "all_time": {"net_usdt": round(sum(t["net"] for t in trades), 2), "closed": len(trades)}, "why": {"word": tr["word"], "text": tr["text"]},
            "note": "Closed pretend trades, net of fee (the Brain also net of slippage), USDT. The Brain and the Current Bot are different trades, never added. Percent = of the %d USDT guard capital. No account balance is shown because none is real. LIVE is locked." % cap}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--source", default="PAPER", choices=B.SOURCES)
    a = ap.parse_args(argv)
    r = build(a.data, a.source)
    if not r["ready"]:
        print(r["note"])
        return 0
    t, k, p = r["today"], r["risk"], r["pace30"]
    print("Today: Brain %+.2f USDT (%d closed), Current Bot %+.2f USDT." % (t["net_usdt"], t["closed"], t["bot_net_usdt"]))
    print("30 days: Brain %+.2f USDT (%d trades), Current Bot %+.2f USDT (%d trades)." % (p["brain_usdt"], p["brain_trades"], p["bot_usdt"], p["bot_trades"]))
    print("Daily loss cap: %.2f of %.2f USDT used (%.1f%%)%s." % (k["used_usdt"], k["cap_usdt"], k["used_pct"], " - CAP HIT" if k["hit"] else ""))
    print("Open: %d long, %d short. %s: %s" % (r["open"]["long"], r["open"]["short"], r["why"]["word"], r["why"]["text"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
