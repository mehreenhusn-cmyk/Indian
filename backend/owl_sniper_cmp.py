"""owl_sniper_cmp.py - OwlSniper Round 21: SNIPER vs MAIN BOT (backend, read-only). Nothing is traded, nothing is saved, no network, no order code.
Two questions, one answer:
  1. WHOLE PERIOD   the Sniper's TEST-day trades (a REPLAY on saved candles with fees + slippage, 10 USDT base, from v2_sniper_model.json) next to the main paper bot's REAL closed trades
                    (box paper_b1, closed_trades_archive.jsonl, never paper_b2, never live) over the same number of days. Net USDT, trades, average per trade as % of the money put in.
  2. SAME COIN NOW  for every live Sniper card (SNIPER_LONG / SNIPER_SHORT): is the main bot in that coin right now, and whose ENTRY price is better? (reuses v2_bt_botcmp.build)
HONEST LIMITS (also in the answer): the Sniper numbers are a replay, the bot numbers are real paper trades; trade sizes, coins and days differ; the bot uses leverage. So this is two results side by side, not a
same-signal test. A word (SNIPER AHEAD / BOT AHEAD) is only given when BOTH sides have 15+ trades and the gap is clear; else NOT ENOUGH DATA or TOO CLOSE. No promise, no forecast.
Run (Termux, optional):  python3 backend/owl_sniper_cmp.py [--data DIR]  -> JSON."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_feed as F
import v2_bt_botcmp as BC
import v2_pnl as P

VERSION = "owl_sniper_cmp 1 (Round 21)"
MIN_TRADES = 15                 # both sides need this many trades for a word
CLEAR_GAP_PCT = 0.05            # average per trade must differ by at least 0.05 points of the money put in
MAX_CARDS = 10
DEFAULT_DAYS = 7


def sniper_side(model):
    """Sniper TEST numbers from the saved model file (None-safe). -> {trades, net_usdt, avg_pct, days}."""
    eq = (model or {}).get("equity") or {}
    n, curve = int(eq.get("test_trades") or 0), eq.get("all") or []
    net = float(curve[-1]) if curve else 0.0
    days = ((model or {}).get("split") or {}).get("test_days")
    return {"trades": n, "net_usdt": round(net, 4), "avg_pct": round(net / n / 10.0 * 100.0, 3) if n else None, "days": days, "base_usdt": 10.0}


def bot_side(data_dir, days, now):
    """The main paper bot's CLOSED trades of the last `days` days (box paper_b1). avg_pct = net USDT / money put in (invest_usdt), not leveraged ROI."""
    root = os.path.realpath(data_dir)
    rows, _st = P.read_jsonl(os.path.join(root, P.FILES[0][0]), [root])
    n = net = inv = 0.0
    wins = 0
    for t in rows:
        ts, pnl = P.num(t, "closed_at_ts"), P.num(t, "pnl_usdt")
        if ts is None or pnl is None or P.box_of(t, "b1") != "paper_b1" or t.get("source") == "sniper" or not 0 <= now - ts <= days * 86400:
            continue
        n += 1
        net += pnl
        wins += 1 if pnl > 0 else 0
        inv += P.num(t, "invest_usdt") or 0.0
    avg = (net / inv * 100.0) if inv > 0 else None
    return {"trades": int(n), "net_usdt": round(net, 4), "wins": wins, "losses": int(n) - wins, "avg_pct": None if avg is None else round(avg, 3), "days": days}


def verdict(sn, bt):
    """One word. Never a word on thin data, never on a small gap."""
    if sn["trades"] < MIN_TRADES or bt["trades"] < MIN_TRADES or sn["avg_pct"] is None or bt["avg_pct"] is None:
        return "NOT_ENOUGH_DATA", "Each side needs %d or more trades. Sniper %d, main bot %d." % (MIN_TRADES, sn["trades"], bt["trades"])
    gap = sn["avg_pct"] - bt["avg_pct"]
    if abs(gap) < CLEAR_GAP_PCT:
        return "TOO_CLOSE", "Average per trade is %.2f%% (Sniper) and %.2f%% (main bot): no clear gap." % (sn["avg_pct"], bt["avg_pct"])
    word = "SNIPER_AHEAD" if gap > 0 else "BOT_AHEAD"
    return word, "Average per trade: Sniper %.2f%%, main bot %.2f%% of the money put in. Different trades and sizes, so this is a hint, not a proof." % (sn["avg_pct"], bt["avg_pct"])


def same_coin(data_dir, live, now):
    """For each live Sniper order card: the main bot's position in that coin and the entry-price difference (BC.build does the work)."""
    rows = []
    for c in (live or {}).get("cards") or []:
        if c.get("action") not in ("SNIPER_LONG", "SNIPER_SHORT") or not c.get("symbol"):
            continue
        b = BC.build(data_dir, c["symbol"], c.get("entry_price"), c.get("side"), now)
        v = b.get("versus")
        if v and v.get("text"):
            v = dict(v, text=v["text"].replace("The Brain's", "The Sniper's").replace("the Brain's", "the Sniper's"))   # botcmp was written for the Brain: say Sniper here
        rows.append({"symbol": c["symbol"], "sniper_side": c.get("side"), "sniper_entry": c.get("entry_price"), "bot_state": b.get("state"), "bot_side": b.get("side"),
                     "bot_entry": b.get("entry"), "versus": v, "text": b.get("text")})
        if len(rows) >= MAX_CARDS:
            break
    return rows


def build(data_dir, now=None, days=None):
    now = float(time.time() if now is None else now)
    model, live = F.read_json(data_dir, F.MODEL_FILE), F.read_json(data_dir, F.LIVE_FILE)
    sn = sniper_side(model)
    d = int(days or sn["days"] or DEFAULT_DAYS)
    bt = bot_side(data_dir, d, now)
    word, text = verdict(sn, bt)
    return {"version": VERSION, "ready": model is not None, "verdict": word, "text": text, "days": d, "sniper": sn, "bot": bt, "same_coin": same_coin(data_dir, live, now),
            "caveat": "Sniper = replay on saved candles (10 USDT base, fees + slippage). Main bot = real paper trades (paper_b1, leverage). Different coins, days and sizes. Watch only: nothing is traded.",
            "live": "LOCKED"}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--days", type=int, default=None)
    a = ap.parse_args(argv)
    print(json.dumps(build(a.data, None, a.days), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
