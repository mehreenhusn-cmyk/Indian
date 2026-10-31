"""v2_bt_review.py - Part 88a: BRAIN TRADER NIGHT REVIEW (backend, read-only). It groups the CLOSED paper trades of ONE source (PAPER by default, sources are never mixed) by what the chart said at the entry
and says, for every group, how it did: trades, net USDT after fee + slippage, net per trade, older half vs newer half, and ONE word: USE, AVOID, MIXED or NOT ENOUGH DATA.
Rule (same as Part 80): USE / AVOID need 30+ trades AND the same sign in the older and the newer half of the group's history; 30+ trades with disagreeing halves = MIXED; under 30 = NOT ENOUGH DATA. No win rate, no forecast.
Groups (dimensions): market state + side, SD zone, SD width state, TSI with / against the trade, Z vs Z-SMA with / against the trade, histogram (red storm) with / against the trade, TSI + Z agreement, clash, volume note.
'with the trade' = TSI above its signal for a LONG, below it for a SHORT (so LONG and SHORT lines can be read together). Trades made before Part 86a have no storm / clash tag: they are left out of those two groups, never guessed.
'New today' = the group crossed the 30-trade line during today's UTC day (= the app's day). lines_of() and grade() are used again by v2_bt_filter.py and v2_bt_playbook.py.
Words only: nothing here changes the Brain, the live bot or any rule. Reads v2_brain_trader.db read-only. No network, no write, no trading import.
Run (Termux, optional):  python3 backend/v2_bt_review.py [--source PAPER]  -> the plain lines."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_bt_store as B

VERSION = "v2_bt_review 1 (Part 88a)"
MIN_N, DAY, SHOW = 30, 86400, 8
DIMS = (("state", "Market state + side"), ("zone", "SD zone"), ("width", "SD width"), ("tsi", "TSI vs the trade"), ("z", "Z vs Z-SMA"), ("storm", "Histogram (red storm)"),
        ("agree", "TSI + Z agreement"), ("clash", "Clash tags"), ("volume", "Volume note"))


def lines_of(t, side, state=None):
    """Plain group labels of ONE trade idea from its saved tags. A label is None when the tag was not saved (never guessed)."""
    lg = side == "LONG"
    o = {"state": None if not state else "%s %s" % (state, side), "zone": t.get("sd_zone"), "width": t.get("width_state"), "volume": t.get("volume_tag")}
    v = t.get("tsi_vs_signal")
    o["tsi"] = None if v is None else "TSI with the trade" if (v == "ABOVE") == lg else "TSI against the trade"
    v = t.get("z_vs_sma")
    o["z"] = None if v not in ("ABOVE", "BELOW") else "Z with the trade" if (v == "ABOVE") == lg else "Z against the trade"
    v = t.get("storm")
    o["storm"] = None if v is None else "%s, %s" % ("histogram with the trade" if v.startswith("GREEN") == lg else "histogram against the trade", "growing" if v.endswith("BUILDING") else "fading")
    v = t.get("agreement")
    o["agree"] = None if v is None else "TSI + Z disagree" if v == "DISAGREE" else "TSI + Z agree with the trade" if (v == "AGREE_UP") == lg else "TSI + Z agree against the trade"
    o["clash"] = None if t.get("storm") is None else ("clash seen" if t.get("clash") else "no clash")
    return o


def grade(items):
    """items = [(ts, net_usdt)] -> n, net, average, older / newer half net, same sign, verdict."""
    it = sorted(items)
    n = len(it)
    net = sum(x[1] for x in it)
    old, new = sum(x[1] for x in it[:n // 2]), sum(x[1] for x in it[n // 2:])
    same = n >= 2 and ((net > 0 and old > 0 and new > 0) or (net < 0 and old < 0 and new < 0))
    v = "NOT ENOUGH DATA" if n < MIN_N else ("USE" if net > 0 else "AVOID") if same else "MIXED"
    return {"n": n, "net_usdt": round(net, 2), "avg_usdt": round(net / n, 3) if n else 0.0, "older_net": round(old, 2), "newer_net": round(new, 2), "same_sign": same, "verdict": v}


def closed_trades(con, source):
    """Closed trades of ONE source, oldest close first: ts, net, side, symbol, interval, sample, state, tags."""
    q = ("SELECT c.close_ts, c.net_usdt, o.side, o.symbol, o.interval, o.sample, d.state, d.snapshot FROM bt_trade_open o JOIN bt_trade_close c ON c.trade_id=o.trade_id "
         "LEFT JOIN bt_decision d ON d.version=o.version AND d.source=o.source AND d.symbol=o.symbol AND d.interval=o.interval AND d.close_ts=o.open_ts AND d.side=o.side WHERE o.source=? ORDER BY c.close_ts, c.trade_id")
    out = []
    for ts, net, side, sym, iv, smp, st, snap in con.execute(q, (source,)):
        try:
            tg = (json.loads(snap or "{}").get("tags") or {})
        except ValueError:
            tg = {}
        out.append({"ts": ts, "net": net, "side": side, "symbol": sym, "interval": iv, "sample": smp, "state": st, "tags": tg, "lines": lines_of(tg, side, st)})
    return out


def groups(trades, dim):
    g = {}
    for t in trades:
        lab = t["lines"].get(dim)
        if lab is not None:
            g.setdefault(lab, []).append(t)
    return g


def review(trades, day_start):
    out = []
    for dim, title in DIMS:
        rows = []
        for lab, ts in groups(trades, dim).items():
            r = grade([(t["ts"], t["net"]) for t in ts])
            r["label"] = lab
            r["new_today"] = r["n"] >= MIN_N and sum(1 for t in ts if t["ts"] < day_start) < MIN_N
            rows.append(r)
        rows.sort(key=lambda r: r["net_usdt"])
        hidden = max(0, len(rows) - SHOW)
        if hidden:
            rows = rows[:SHOW // 2] + rows[-(SHOW // 2):]
        out.append({"dim": dim, "title": title, "rows": rows, "hidden": hidden})
    return out


def build(data_dir, source="PAPER", now=None):
    now = int(time.time() if now is None else now)
    if source not in B.SOURCES:
        raise ValueError("source must be REPLAY, PAPER or SHADOW")
    con = B.open_ro(data_dir)
    if con is None:
        return {"ready": False, "source": source, "lines": ["No Brain Trader file yet. Run the Brain tick or a replay first."], "note": "no Brain Trader file yet"}
    try:
        trades = closed_trades(con, source)
    finally:
        con.close()
    a = now - now % DAY
    today = [t for t in trades if t["ts"] >= a]
    dims = review(trades, a)
    rows = [dict(r, dim=d["title"]) for d in dims for r in d["rows"]]
    use, avoid = [r for r in rows if r["verdict"] == "USE"], [r for r in rows if r["verdict"] == "AVOID"]
    new = [r for r in rows if r["new_today"]]
    lines = ["%s: %d closed paper trades in all, %d today, net today %+.2f USDT after fee + slippage (pretend money)." % (source, len(trades), len(today), sum(t["net"] for t in today))]
    if len(trades) < MIN_N:
        lines.append("Too few closed trades to learn anything yet (need %d in a group). The Brain keeps exploring and says USE or AVOID only with evidence." % MIN_N)
    for r in new:
        lines.append("New today: %s - %s reached %d trades, now %s (net %+.2f USDT)." % (r["dim"], r["label"], r["n"], r["verdict"], r["net_usdt"]))
    for r in avoid[:3]:
        lines.append("AVOID candidate: %s - %s lost %.2f USDT in %d trades, in both halves of its history." % (r["dim"], r["label"], -r["net_usdt"], r["n"]))
    for r in use[:3]:
        lines.append("USE candidate: %s - %s made %.2f USDT in %d trades, in both halves of its history." % (r["dim"], r["label"], r["net_usdt"], r["n"]))
    return {"ready": True, "framework": VERSION, "source": source, "total_closed": len(trades), "today": {"closed": len(today), "net_usdt": round(sum(t["net"] for t in today), 2)}, "dims": dims, "use": use, "avoid": avoid,
            "new_today": new, "lines": lines, "note": "Closed paper trades only, net of fee + slippage. USE / AVOID need 30+ trades and the same sign in both halves. Evidence, not an order; it never changes the live bot."}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--source", default="PAPER", choices=B.SOURCES)
    a = ap.parse_args(argv)
    print("\n".join(build(a.data, a.source)["lines"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
