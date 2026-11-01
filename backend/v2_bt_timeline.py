"""v2_bt_timeline.py - Part M4a: BRAIN AND ACTIVITY TIMELINE (backend, read-only). Idea of mock picture 13.
ONE UTC day as a list of events, newest first: what the Owl Brain did (took a trade / put it on WAIT / skipped it, opened, closed) and what the Current Bot did
(main paper bot, box paper_b1, same loader as the Results screen: opened and closed trades), side by side in time. Plus a per-coin table: coins where BOTH acted that day
are marked, so you can see "the Brain skipped it, the bot took it" (or the other way round) with each side's net. Nothing is added across the two, nothing is saved, nothing is traded.
HONEST LIMITS (also in the answer): the Current Bot only shows trades that are already CLOSED (the archive holds nothing else), so its open trades are not on the line;
the Brain's WAIT / SKIP lines are capped (newest 40) and NO_OPINION is only counted; the Brain decides on candle closes, the bot on its own timing, so two events on one coin are
a look, not proof of the same signal. Day = UTC day = the app's day; every event also carries the clock in IST (UTC+5:30).
Reads v2_brain_trader.db read-only (a read never creates it) and the bot archive files. No network, no write, no trading import. Route: GET /api/v2/brain_timeline?source=PAPER&day=YYYY-MM-DD (api/v2_brain_views.py).
Run (Termux, optional):  python3 backend/v2_bt_timeline.py [--data DIR] [--day YYYY-MM-DD] [--source PAPER]"""
import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_compare as CP
import v2_bt_store as B
import v2_results as RS

VERSION = "v2_bt_timeline 1 (Part M4a)"
DAY = 86400
IST = 19800
WAIT_SKIP_CAP = 40                                       # newest WAIT / SKIP lines kept; taken trades and all opens / closes are always kept
EVENT_CAP = 150
COIN_CAP = 15


def _clock(ts, add=0):
    return datetime.datetime.fromtimestamp(int(ts) + add, datetime.timezone.utc).strftime("%H:%M")


def _ev(ts, who, kind, symbol, side, text, net=None, interval=None, reason=None):
    e = {"ts": int(ts), "utc": _clock(ts), "ist": _clock(ts, IST), "who": who, "kind": kind, "symbol": symbol or "-", "side": side or "-", "text": text}
    if net is not None:
        e["net_usdt"] = round(float(net), 2)
    if interval:
        e["interval"] = interval
    if reason:
        e["reason"] = str(reason)[:90]
    return e


def brain_events(con, source, a, b):
    """-> (events, counts). Decisions of candle closes inside [a, b) plus trade opens and closes inside [a, b)."""
    ev, no_op = [], 0
    rows = con.execute("SELECT close_ts, symbol, interval, side, decision, state, reason, version FROM bt_decision WHERE source=? AND close_ts>=? AND close_ts<? ORDER BY close_ts DESC", (source, a, b)).fetchall()
    held = 0
    for ts, sym, iv, side, dec, state, reason, ver in rows:
        if dec == "NO_OPINION":
            no_op += 1
            continue
        if dec in ("OPEN_LONG", "OPEN_SHORT"):
            ev.append(_ev(ts, "BRAIN", "TAKE", sym, side, "Brain (%s) decided to take it" % ver + (" (%s)" % state if state else ""), interval=iv, reason=reason))
        elif held < WAIT_SKIP_CAP:
            held += 1
            ev.append(_ev(ts, "BRAIN", dec, sym, side, "Brain (%s) put it on WAIT" % ver if dec == "WAIT" else "Brain (%s) skipped it" % ver, interval=iv, reason=reason))
    for ts, sym, iv, side, entry, ver in con.execute("SELECT open_ts, symbol, interval, side, entry, version FROM bt_trade_open WHERE source=? AND open_ts>=? AND open_ts<?", (source, a, b)).fetchall():
        ev.append(_ev(ts, "BRAIN", "OPEN", sym, side, "Paper trade (%s) opened at %s" % (ver, entry), interval=iv))
    q = ("SELECT c.close_ts, o.symbol, o.interval, o.side, c.exit_reason, c.net_usdt, o.version FROM bt_trade_close c JOIN bt_trade_open o ON o.trade_id=c.trade_id "
         "WHERE o.source=? AND c.close_ts>=? AND c.close_ts<?")
    for ts, sym, iv, side, why, net, ver in con.execute(q, (source, a, b)).fetchall():
        ev.append(_ev(ts, "BRAIN", "CLOSE", sym, side, "Paper trade (%s) closed (%s)" % (ver, why), net=net, interval=iv))
    return ev, {"no_opinion": no_op, "decisions_shown": held, "decisions_all": len(rows) - no_op}


def bot_events(data_dir, a, b):
    """-> (events, ok). Closed trades of the main paper bot (box paper_b1): an OPEN line when it opened inside the day, a CLOSE line when it closed inside the day."""
    try:
        boxes, _skipped = RS.load(data_dir, 1.0)
    except Exception:
        return [], False
    ev = []
    for ts, net, t in boxes.get("paper_b1", []):
        sym = str(t.get("symbol") or "").upper() or None
        side = str(t.get("side") or t.get("direction") or "").upper() or None
        o = t.get("opened_at_ts")
        try:
            o = float(o) if o not in (None, "") else None
        except (TypeError, ValueError):
            o = None
        if o is not None and a <= o < b:
            ev.append(_ev(o, "BOT", "OPEN", sym, side, "Bot opened a paper trade"))
        if a <= ts < b:
            ev.append(_ev(ts, "BOT", "CLOSE", sym, side, "Bot closed the trade", net=net))
    return ev, True


def coins(events):
    """Per coin: how many Brain / Bot lines, the net of closed trades of each (apart), and whether BOTH acted that day."""
    m = {}
    for e in events:
        if e["symbol"] == "-":
            continue
        c = m.setdefault(e["symbol"], {"symbol": e["symbol"], "brain_lines": 0, "bot_lines": 0, "brain_net_usdt": 0.0, "bot_net_usdt": 0.0, "brain_took": False, "brain_skipped": False})
        c["brain_lines" if e["who"] == "BRAIN" else "bot_lines"] += 1
        if "net_usdt" in e:
            c["brain_net_usdt" if e["who"] == "BRAIN" else "bot_net_usdt"] += e["net_usdt"]
        if e["who"] == "BRAIN" and e["kind"] in ("TAKE", "OPEN"):
            c["brain_took"] = True
        if e["who"] == "BRAIN" and e["kind"] in ("SKIP", "WAIT"):
            c["brain_skipped"] = True
    out = []
    for c in m.values():
        c["both"] = c["brain_lines"] > 0 and c["bot_lines"] > 0
        c["brain_net_usdt"], c["bot_net_usdt"] = round(c["brain_net_usdt"], 2), round(c["bot_net_usdt"], 2)
        out.append(c)
    out.sort(key=lambda c: (not c["both"], -(c["brain_lines"] + c["bot_lines"]), c["symbol"]))
    return out[:COIN_CAP]


def build(data_dir, source="PAPER", day=None, now=None):
    if source not in B.SOURCES:
        raise ValueError("source must be REPLAY, PAPER or SHADOW")
    now = int(time.time() if now is None else now)
    a, b, label = CP.day_bounds(day, now)
    con = B.open_ro(data_dir)
    try:
        bev, counts = brain_events(con, source, a, b) if con is not None else ([], {"no_opinion": 0, "decisions_shown": 0, "decisions_all": 0})
    finally:
        if con is not None:
            con.close()
    kev, bot_ok = bot_events(data_dir, a, b)
    allv = sorted(bev + kev, key=lambda e: (-e["ts"], e["who"]))
    total = len(allv)
    d0 = datetime.datetime.fromtimestamp(a, datetime.timezone.utc)
    today = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).strftime("%Y-%m-%d")
    nxt = (d0 + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    cl = [e for e in bev if e["kind"] == "CLOSE"]
    bcl = [e for e in kev if e["kind"] == "CLOSE"]
    return {"ready": True, "framework": VERSION, "source": source, "live": "LOCKED", "day": label, "prev": (d0 - datetime.timedelta(days=1)).strftime("%Y-%m-%d"),
            "next": nxt if nxt <= today else None, "events": allv[:EVENT_CAP], "events_total": total, "events_cut": max(0, total - EVENT_CAP),
            "brain": {"took": sum(1 for e in bev if e["kind"] == "TAKE"), "waited": sum(1 for e in bev if e["kind"] == "WAIT"), "skipped": sum(1 for e in bev if e["kind"] == "SKIP"),
                      "closed": len(cl), "net_usdt": round(sum(e["net_usdt"] for e in cl), 2), "no_opinion": counts["no_opinion"],
                      "wait_skip_cut": max(0, counts["decisions_all"] - sum(1 for e in bev if e["kind"] in ("TAKE", "WAIT", "SKIP")))},
            "bot": {"ok": bot_ok, "opened": sum(1 for e in kev if e["kind"] == "OPEN"), "closed": len(bcl), "net_usdt": round(sum(e["net_usdt"] for e in bcl), 2)},
            "coins": coins(allv), "note": ("Net of fee, USDT, UTC day (clock also in IST). The Current Bot shows only trades that are already closed. Brain WAIT / SKIP lines are capped at %d "
                                           "and NO_OPINION is only counted. The Brain and the bot are different trades and are never added. Two events on one coin are a look, not proof of the same signal. "
                                           "Evidence, not an order." % WAIT_SKIP_CAP)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Brain and Activity timeline of one UTC day (read-only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or ".")
    ap.add_argument("--day", default=None)
    ap.add_argument("--source", default="PAPER")
    a = ap.parse_args(argv)
    r = build(a.data, a.source, a.day)
    print("%s  %s  Brain: took %d, waited %d, skipped %d, closed %d (%+.2f USDT)  Bot: opened %d, closed %d (%+.2f USDT)" % (
        r["day"], r["source"], r["brain"]["took"], r["brain"]["waited"], r["brain"]["skipped"], r["brain"]["closed"], r["brain"]["net_usdt"], r["bot"]["opened"], r["bot"]["closed"], r["bot"]["net_usdt"]))
    for e in r["events"][:30]:
        print("%s IST  %-5s %-5s %-12s %-5s %s%s" % (e["ist"], e["who"], e["kind"], e["symbol"], e["side"], e["text"], (" %+.2f" % e["net_usdt"]) if "net_usdt" in e else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
