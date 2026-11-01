"""v2_bt_compare.py - Part X1: THREE-WAY COMPARISON of one UTC day (backend, read-only). Mock screens 06 (Today's result) and 09 (Brain Trader today).
Three arms, all NET of fee (+ slippage for the Brain), in USDT, and NEVER added together:
  Owl Brain        the Brain's own CLOSED paper trades of that day (v2_brain_trader.db, source PAPER by default), real saved numbers.
  Current Bot      the main paper bot's closed trades of that day (closed_trades_archive.jsonl, box paper_b1, same loader as the Results screen). Old trades without a fee get it estimated.
  Take-All         what the Brain's rule would have made if it had taken EVERY idea that had a direction at the signal candle, also the ideas it put on WAIT or SKIP (never NO_OPINION, never a guard refusal).
                   Same BT-01 stop / target / max hold / fee / slippage, one trade per coin at a time, worked out on the SAVED candles (v2_replay.simulate). An idea whose end is not known yet is left out.
                   It is a SIMULATION, the Brain numbers are not: it says how much the Brain's waiting / skipping added or cost. Coins are capped (SIM_COINS) to keep the answer fast; the cap is said in the answer.
HONEST LIMITS (also in the answer): the Brain and the Current Bot are DIFFERENT trades (other coins, other times), so this is a comparison of results, not of the same signals. The Take-All line is the only
one that uses the Brain's own ideas. Day = UTC day = the app's day. No win rate, no forecast, nothing is saved, nothing is traded.
Part M2: month_view() = one month as a calendar (route brain_month).
Part E5: a fourth number brain_bt02 = the closed SHADOW trades of BT-02 (same entry rule, the Brain decides the exit) next to the PAPER BT-01 (only when source=PAPER).
Also gives: the Brain's decision counts of the day (taken / waited / skipped / no opinion), gross / fees / slippage of its closed trades, worst dip and losing streak of the day, and a CALENDAR of the last days
(Brain and Current Bot only, Take-All is not worked out for calendar days) for the day-calendar screen (X2).
Run (Termux, optional):  python3 backend/v2_bt_compare.py [--data DIR] [--day YYYY-MM-DD] [--source PAPER]  -> the plain lines."""
import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_guard as G
import v2_bt_rules as R
import v2_bt_sim as SM
import v2_bt_state as ST
import v2_bt_store as B
import v2_bt_verdict as VD
import v2_defs as D
import v2_replay as V
import v2_results as RS

VERSION = "v2_bt_compare 1 (Part X1)"
DAY = 86400
SIM_COINS = 15                                          # Take-All is worked out for at most this many coin / interval pairs per answer (the most ideas first)
CAL_DAYS = 30
IDEAS = ("OPEN_LONG", "OPEN_SHORT", "WAIT", "SKIP")


def day_bounds(day, now):
    """'2026-11-01' or None (= today) -> (start_ts, end_ts, label). A bad text = ValueError."""
    if day:
        try:
            a = int(datetime.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc).timestamp())
        except ValueError:
            raise ValueError("day must look like 2026-11-01")
    else:
        a = now - now % DAY
    return a, a + DAY, datetime.datetime.fromtimestamp(a, datetime.timezone.utc).strftime("%Y-%m-%d")


def brain_day(con, source, a, b):
    """The Brain's closed trades that closed inside [a, b): numbers, and its decision counts of the day."""
    q = ("SELECT c.close_ts, c.net_usdt, c.gross_pct, c.fee_pct, c.slip_pct, o.size_usdt FROM bt_trade_close c JOIN bt_trade_open o ON o.trade_id=c.trade_id "
         "WHERE o.source=? AND c.close_ts>=? AND c.close_ts<? ORDER BY c.close_ts, c.trade_id")
    rows = con.execute(q, (source, a, b)).fetchall()
    tr = [{"ts": r[0], "net": r[1]} for r in rows]
    cnt = dict(con.execute("SELECT decision, COUNT(*) FROM bt_decision WHERE source=? AND close_ts>=? AND close_ts<? GROUP BY decision", (source, a, b)).fetchall())
    allc = sum(cnt.values())
    kinds = {"taken": cnt.get("OPEN_LONG", 0) + cnt.get("OPEN_SHORT", 0), "waited": cnt.get("WAIT", 0), "skipped": cnt.get("SKIP", 0), "no_opinion": cnt.get("NO_OPINION", 0)}
    return {"closed": len(rows), "net_usdt": round(sum(r[1] for r in rows), 2), "gross_usdt": round(sum(r[2] / 100.0 * r[5] for r in rows), 2),
            "fees_usdt": round(-sum(r[3] / 100.0 * r[5] for r in rows), 2), "slippage_usdt": round(-sum(r[4] / 100.0 * r[5] for r in rows), 2),
            "decisions": dict(kinds, total=allc), "drawdown": VD.drawdown(VD.equity(tr)), "streak": VD.streak(tr), "equity": VD.thin(VD.equity(tr))}


def bot_rows(data_dir):
    """[(closed_ts, net_usdt)] of the main paper bot (box paper_b1), oldest first. paper_b2 is never added."""
    boxes, _skipped = RS.load(data_dir, 1.0)
    return sorted((int(ts), float(n)) for ts, n, _t in boxes.get("paper_b1", []))


def take_all(con, data_dir, source, a, b, now, cap=SIM_COINS):
    """Simulated Take-All of the day. -> numbers + how many ideas were counted / left out. Nothing is saved."""
    q = ("SELECT symbol, interval, close_ts, side FROM bt_decision WHERE source=? AND close_ts>=? AND close_ts<? AND decision IN (%s) AND state IS NOT NULL "
         "ORDER BY symbol, interval, close_ts" % ",".join("'%s'" % x for x in IDEAS))
    by = {}
    for s, iv, ts, side in con.execute(q, (source, a, b)):
        by.setdefault((s, iv), []).append((ts, side))
    pairs = sorted(by, key=lambda k: -len(by[k]))
    out = {"ideas": sum(len(v) for v in by.values()), "taken": 0, "unknown_end": 0, "no_candles": 0, "coins_used": 0, "coins_left_out": max(0, len(pairs) - cap), "net_usdt": 0.0}
    for sym, iv in pairs[:cap]:
        run = SM.load_run(data_dir, sym, iv)
        step = D.STEP[iv]
        if len(run) < 2:
            out["no_candles"] += len(by[(sym, iv)])
            continue
        out["coins_used"] += 1
        ctx, at, busy = ST.prepare(run), {c[0] + step: k for k, c in enumerate(run)}, -1
        for ts, side in by[(sym, iv)]:
            i = at.get(ts)
            if i is None or i <= busy:
                out["no_candles"] += 1 if i is None else 0
                continue
            lv = R._levels(ctx, {}, i, side)
            if lv is None or lv[1] <= 0 or lv[2] <= 0:
                out["no_candles"] += 1
                continue
            sim = V.simulate(run, i, side, lv[1], lv[2], R.MAX_HOLD, step, now)
            if sim["status"] not in SM.FINISHED:
                out["unknown_end"] += 1
                continue
            out["taken"] += 1
            out["net_usdt"] += (sim["gross_pct"] - 2 * (R.FEE_PCT + R.SLIP_PCT)) / 100.0 * R.SIZE_USDT
            busy = i + sim["hold_candles"]
    out["net_usdt"] = round(out["net_usdt"], 2)
    return out


def calendar(brain_con, bot, source, now):
    """The last CAL_DAYS days, newest first: Brain net + Current Bot net + counts (no Take-All here)."""
    start = now - now % DAY - (CAL_DAYS - 1) * DAY
    days = {}
    for ts, net in B_rows(brain_con, source, start):
        d = days.setdefault((ts - ts % DAY), {"brain": 0.0, "brain_n": 0, "bot": 0.0, "bot_n": 0})
        d["brain"] += net
        d["brain_n"] += 1
    for ts, net in bot:
        if ts >= start:
            d = days.setdefault((ts - ts % DAY), {"brain": 0.0, "brain_n": 0, "bot": 0.0, "bot_n": 0})
            d["bot"] += net
            d["bot_n"] += 1
    return [{"day": datetime.datetime.fromtimestamp(k, datetime.timezone.utc).strftime("%Y-%m-%d"), "brain_usdt": round(v["brain"], 2), "brain_trades": v["brain_n"],
             "bot_usdt": round(v["bot"], 2), "bot_trades": v["bot_n"]} for k, v in sorted(days.items(), reverse=True)]


def B_rows(con, source, since):
    return B.closed_rows(con, source, since) if con is not None else []


def lines_of(r):
    br, bt, ta = r["brain"], r["current_bot"], r["take_all"]
    xs = ["%s: Owl Brain %+.2f USDT (%d closed), Current Bot %+.2f USDT (%d closed), Take-All %+.2f USDT (%d simulated ideas)." % (r["day"], br["net_usdt"], br["closed"], bt["net_usdt"], bt["closed"], ta["net_usdt"], ta["taken"])]
    if ta["taken"] and br["closed"]:
        d = br["net_usdt"] - ta["net_usdt"]
        xs.append("Against Take-All the Brain's waiting and skipping %s %.2f USDT today (a simulation, one day, evidence is thin)." % ("added" if d >= 0 else "cost", abs(d)))
    xs.append("The Brain and the Current Bot are different trades, so this is not a same-signal test.")
    return xs


def build(data_dir, source="PAPER", day=None, now=None):
    if source not in B.SOURCES:
        raise ValueError("source must be REPLAY, PAPER or SHADOW")
    now = int(time.time() if now is None else now)
    a, b, label = day_bounds(day, now)
    con = B.open_ro(data_dir)
    bot = bot_rows(data_dir)
    try:
        if con is None:
            bt2 = {"closed": 0, "net_usdt": 0.0}
            brain, ta = brain_day_empty(), {"ideas": 0, "taken": 0, "unknown_end": 0, "no_candles": 0, "coins_used": 0, "coins_left_out": 0, "net_usdt": 0.0}
        else:
            brain, ta = brain_day(con, source, a, b), take_all(con, data_dir, source, a, b, now)
            b2 = brain_day(con, "SHADOW", a, b) if source == "PAPER" else None             # Part E5: BT-02 (the Brain decides the exit) runs in SHADOW beside the PAPER BT-01
            bt2 = {"closed": b2["closed"], "net_usdt": b2["net_usdt"]} if b2 else {"closed": 0, "net_usdt": 0.0}
        cal = calendar(con, bot, source, now)
    finally:
        if con is not None:
            con.close()
    mine = [x for x in bot if a <= x[0] < b]
    cap = G.DEFAULTS["capital_usdt"]
    arms = {"brain": brain, "current_bot": {"closed": len(mine), "net_usdt": round(sum(x[1] for x in mine), 2)}, "take_all": ta, "brain_bt02": bt2}
    for k, v in arms.items():
        v["pct_of_capital"] = round(v["net_usdt"] / cap * 100.0, 2)
    r = dict(arms, ready=con is not None, framework=VERSION, source=source, day=label, live="LOCKED", capital_usdt=cap, calendar=cal)
    r["lines"] = lines_of(r)
    r["lines"].append("BT-01 (PAPER) %+.2f USDT, %d closed. BT-02 (SHADOW, the Brain decides the exit) %+.2f USDT, %d closed. Different entries in time, so this is a look, not a proof; BT-02 needs weeks of trades first." % (brain["net_usdt"], brain["closed"], bt2["net_usdt"], bt2["closed"]))
    r["note"] = ("Net of fee, USDT. The Brain and the Current Bot are different trades. Take-All is a simulation on saved candles (%d coin(s) used, %d left out by the cap); "
                 "percent = of the %d USDT guard capital. Evidence, not an order." % (ta["coins_used"], ta["coins_left_out"], cap))
    return r


def month_bounds(month, now):
    """'2026-11' or None (= this month, UTC) -> (start_ts, end_ts, label, previous label, next label or None when it is the future). A bad text = ValueError."""
    try:
        d = datetime.datetime.strptime(month, "%Y-%m") if month else datetime.datetime.fromtimestamp(now, datetime.timezone.utc).replace(day=1, tzinfo=None)
    except ValueError:
        raise ValueError("month must look like 2026-11")
    d = d.replace(day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    nxt, prv = (d + datetime.timedelta(days=32)).replace(day=1), (d - datetime.timedelta(days=1)).replace(day=1)
    ts = lambda x: int(x.replace(tzinfo=datetime.timezone.utc).timestamp())
    cur = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m")
    return ts(d), ts(nxt), d.strftime("%Y-%m"), prv.strftime("%Y-%m"), (nxt.strftime("%Y-%m") if nxt.strftime("%Y-%m") <= cur else None)


def month_view(data_dir, source="PAPER", month=None, now=None):
    """Part M2: ONE UTC month as a calendar (mock 16 idea). Per day: Brain net + trades and Current Bot net + trades (never added). Month numbers: Brain net, Current Bot net, best / worst day, trades, profit / loss days (counts, no win-rate headline),
    worst dip of the Brain, running-net line by day. Read-only; first_weekday 0 = Monday so the screen can leave the empty cells."""
    if source not in B.SOURCES:
        raise ValueError("source must be REPLAY, PAPER or SHADOW")
    now = int(time.time() if now is None else now)
    a, b, label, prv, nxt = month_bounds(month, now)
    con = B.open_ro(data_dir)
    try:
        rows = [(ts, n) for ts, n in B_rows(con, source, a) if ts < b]
    finally:
        if con is not None:
            con.close()
    bot = [(ts, n) for ts, n in bot_rows(data_dir) if a <= ts < b]
    days = {}
    for key, xs in (("brain", rows), ("bot", bot)):
        for ts, n in xs:
            d = days.setdefault(int((ts - a) // DAY) + 1, {"brain": 0.0, "brain_n": 0, "bot": 0.0, "bot_n": 0})
            d[key] += n
            d[key + "_n"] += 1
    out = [{"day": k, "brain_usdt": round(v["brain"], 2), "brain_trades": v["brain_n"], "bot_usdt": round(v["bot"], 2), "bot_trades": v["bot_n"]} for k, v in sorted(days.items())]
    brain_days = [x for x in out if x["brain_trades"]]
    best = max(brain_days, key=lambda x: x["brain_usdt"]) if brain_days else None
    worst = min(brain_days, key=lambda x: x["brain_usdt"]) if brain_days else None
    tr = [{"ts": ts, "net": n} for ts, n in rows]
    line, run = [], 0.0
    for x in brain_days:
        run += x["brain_usdt"]
        line.append(round(run, 2))
    n_days = int((b - a) // DAY)
    return {"ready": True, "framework": VERSION, "source": source, "live": "LOCKED", "month": label, "prev": prv, "next": nxt, "days_in_month": n_days, "first_weekday": datetime.datetime.fromtimestamp(a, datetime.timezone.utc).weekday(),
            "days": out, "brain_usdt": round(sum(n for _t, n in rows), 2), "brain_trades": len(rows), "bot_usdt": round(sum(n for _t, n in bot), 2), "bot_trades": len(bot),
            "profit_days": sum(1 for x in brain_days if x["brain_usdt"] > 0), "loss_days": sum(1 for x in brain_days if x["brain_usdt"] < 0), "days_with_trades": len(brain_days),
            "best_day": best, "worst_day": worst, "drawdown": VD.drawdown(VD.equity(tr)), "equity": line,
            "note": "Net of fee, USDT, UTC days (the app's day). The Brain and the Current Bot are different trades and are never added. Counts of profit and loss days, no win-rate headline. Evidence, not an order."}


def brain_day_empty():
    return {"closed": 0, "net_usdt": 0.0, "gross_usdt": 0.0, "fees_usdt": 0.0, "slippage_usdt": 0.0, "decisions": {"taken": 0, "waited": 0, "skipped": 0, "no_opinion": 0, "total": 0},
            "drawdown": VD.drawdown([]), "streak": VD.streak([]), "equity": VD.thin([])}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--day", default=None)
    ap.add_argument("--source", default="PAPER", choices=B.SOURCES)
    a = ap.parse_args(argv)
    print("\n".join(build(a.data, a.source, a.day)["lines"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
