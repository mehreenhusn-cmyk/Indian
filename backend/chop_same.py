"""chop_same.py - E11: WHAT DID THE CURRENT BOT DO ON THE SAME SIGNALS AS b3? READ ONLY: it reads the b3 decisions (chop_b3.db) and the Current bot's closed trades (closed_trades_archive.jsonl). Writes nothing, no network, no order.
Owner (7 Nov 2026): "the b3 card must say what the Current bot did". The two bots run on different timeframes (b3 = 5m, Current bot = 15m), so a "same signal" is matched by rule, not by id:
  same coin + same side (BUY / SELL) + the Current bot opened its trade within +-15 minutes of the b3 signal candle. One Current-bot trade is matched to ONE b3 signal (the nearest in time).
Groups: both took / b3 skipped but the Current bot took (its real result = what the b3 filter would have kept you out of) / b3 took but the Current bot did not / Current bot trades b3 never saw.
Honest limits written in every answer: only CLOSED Current-bot trades are counted; trades opened by the Sniper (source starts with sniper) are left out; the match is by time window, so it is a good guide, not a proof.
API: build(db, data_dir, now=None) -> dict. Never raises."""
import json
import os
import time

VERSION = "chop_same 1 (E11)"
WINDOW_S = 15 * 60
DAY = 86400


def _f(v, d=0.0):
    try:
        return float(v)
    except Exception:
        return d


def _current_trades(data_dir):
    out = []
    p = os.path.join(os.path.realpath(data_dir), "closed_trades_archive.jsonl")
    if not os.path.isfile(p):
        return out
    seen = set()
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
            except Exception:
                continue
            if not isinstance(t, dict):
                continue
            src = str(t.get("source") or "").lower()
            if src.startswith("sniper") or str(t.get("bot") or "b1").lower() == "b2":
                continue
            k = (t.get("id"), t.get("closed_at_ts"))
            if k in seen:
                continue
            seen.add(k)
            ot = _f(t.get("opened_at_ts"), 0.0)
            if ot <= 0 or t.get("pnl_usdt") is None:
                continue
            out.append({"sym": str(t.get("symbol") or "").upper(), "side": "BUY" if str(t.get("action") or "").upper() == "BUY" else "SELL",
                        "opened": ot, "net": _f(t.get("pnl_usdt"))})
    return out


def _empty(label):
    return {"scope": label, "current_trades": 0, "both": {"n": 0, "cur_net": 0.0, "b3_net": 0.0}, "b3_skipped": {"n": 0, "cur_net": 0.0, "cur_wins": 0, "cur_losses": 0},
            "b3_only": {"n": 0, "b3_net": 0.0}, "cur_only": {"n": 0, "cur_net": 0.0}}


def _group(decs, b3net, cur, since, label):
    g = _empty(label)
    used = set()
    scoped = [c for c in cur if c["opened"] >= since]
    g["current_trades"] = len(scoped)
    by = {}
    for d in decs:
        by.setdefault((d["sym"], d["side"]), []).append(d)
    matched_dec = set()
    for c in scoped:
        best, bd = None, None
        for d in by.get((c["sym"], c["side"]), ()):
            gap = abs(c["opened"] - d["ts"])
            if gap <= WINDOW_S and (bd is None or gap < bd):
                best, bd = d, gap
        if best is None:
            g["cur_only"]["n"] += 1
            g["cur_only"]["cur_net"] += c["net"]
            continue
        matched_dec.add(best["id"])
        if best["action"] == "TAKE":
            g["both"]["n"] += 1
            g["both"]["cur_net"] += c["net"]
            g["both"]["b3_net"] += b3net.get(best["trade_id"], 0.0)
        else:
            g["b3_skipped"]["n"] += 1
            g["b3_skipped"]["cur_net"] += c["net"]
            g["b3_skipped"]["cur_wins" if c["net"] > 0 else "cur_losses"] += 1
    for d in decs:
        if d["action"] == "TAKE" and d["id"] not in matched_dec and d["ts"] >= since:
            g["b3_only"]["n"] += 1
            g["b3_only"]["b3_net"] += b3net.get(d["trade_id"], 0.0)
    for k in ("both", "b3_skipped", "b3_only", "cur_only"):
        for kk, v in list(g[k].items()):
            if isinstance(v, float):
                g[k][kk] = round(v, 2)
    return g


def _lines(g):
    L = []
    n = g["current_trades"]
    if n == 0:
        return ["No closed Current-bot trade in this period yet."]
    s, b, bo, co = g["b3_skipped"], g["both"], g["b3_only"], g["cur_only"]
    L.append("The Current bot closed %d trades. b3 had a signal on the same coin and side for %d of them." % (n, s["n"] + b["n"]))
    if s["n"]:
        if s["cur_net"] < 0:
            L.append("b3 skipped %d of them. The Current bot made %+.2f USDT on those (%d lost, %d won), so the b3 filter would have kept you out of a loss." % (s["n"], s["cur_net"], s["cur_losses"], s["cur_wins"]))
        else:
            L.append("b3 skipped %d of them. The Current bot made %+.2f USDT on those (%d lost, %d won), so the b3 filter would have missed a gain." % (s["n"], s["cur_net"], s["cur_losses"], s["cur_wins"]))
    if b["n"]:
        L.append("Both took %d: the Current bot made %+.2f USDT, b3 made %+.2f USDT (b3 uses its own entry, size and exit)." % (b["n"], b["cur_net"], b["b3_net"]))
    if bo["n"]:
        L.append("b3 took %d trades that the Current bot did not take (b3 net %+.2f USDT, closed ones only)." % (bo["n"], bo["b3_net"]))
    if co["n"]:
        L.append("%d Current-bot trades (%+.2f USDT) had no b3 signal near them: b3 did not look at that coin or time." % (co["n"], co["cur_net"]))
    return L


def build(db, data_dir, now=None):
    now = int(time.time() if now is None else now)
    out = {"version": VERSION, "paper_only": True, "state": "OK", "window_min": WINDOW_S // 60, "today": None, "all": None, "lines": [], "notes": [
        "Matched by coin + side + opened within 15 minutes of the b3 signal. Only closed Current-bot trades. Sniper trades are left out."]}
    try:
        rows = db.execute("SELECT id, symbol, candle_ts, side, action, trade_id FROM decisions WHERE side IS NOT NULL AND action IN ('TAKE','SKIP') ORDER BY candle_ts").fetchall()
        decs = [{"id": r[0], "sym": str(r[1]).upper(), "ts": float(r[2]), "side": r[3], "action": r[4], "trade_id": r[5]} for r in rows]
        b3net = {r[0]: _f(r[1]) for r in db.execute("SELECT id, net_usdt FROM trades WHERE status!='OPEN' AND net_usdt IS NOT NULL").fetchall()}
        if not decs:
            out["state"] = "NO_B3"
            out["lines"] = ["b3 has no decisions yet, so there is nothing to compare. Switch b3 ON and wait."]
            return out
        cur = _current_trades(data_dir)
        first = decs[0]["ts"]
        a = now - now % DAY
        out["today"] = _group(decs, b3net, cur, max(a, first), "today")
        out["all"] = _group(decs, b3net, cur, first, "since b3 started")
        out["lines"] = _lines(out["today"]) if out["today"]["current_trades"] else _lines(out["all"])
        out["lines_scope"] = "today" if out["today"]["current_trades"] else "since b3 started"
    except Exception as e:
        out["state"] = "error"
        out["lines"] = ["Could not compare: %s" % str(e)[:120]]
    return out
