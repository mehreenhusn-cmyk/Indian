"""owl_sniper_live.py - OwlSniper Round 20: LIVE SCAN WITH RETRIES (backend, plain python). Watch only: no order, no trade, nothing is written to the market store, no file is written at all.
Why: owl_sniper_feed.scan() reads only the SAVED candles, and the collector may be a few candles behind. This file tops those up in memory and scans again, so a card is based on the newest closed candle.
How, in plain words:
  1. For each coin (newest first, at most MAX_COINS) read the saved tail (read-only). If the newest saved candle is older than STALE_STEPS candles, ask the exchange ONLY for the missing closed candles.
  2. The exchange is asked through v2_candles.http_get / kline_url / parse_klines, so the one allowed public address, the 99-candle cap and the 5m / 3m rule of the collector stay in force. No key, no signature.
  3. A failed request is retried TRIES times with a growing pause (1 s, 2 s). One run has a hard budget of BUDGET requests, retries included; coins left over stay as they were and are counted.
  4. A hole is NEVER bridged: the new candles must follow the saved ones with no gap, else the coin is counted as stale (F.newest_run cuts the series at the hole).
  5. The scan itself is owl_sniper_prob.evaluate_live() with the saved model; a signal card also gets its triple-barrier lines (owl_sniper_barriers).
The network is used ONLY when the file v2_candles_enabled is on (the same switch as the candle collector) and v2_sniper_off does not exist. Else the answer is the same scan on saved candles, and it says so.
Run (Termux, optional):  python3 backend/owl_sniper_live.py [--data DIR] [--interval 5m|15m] [--offline]  -> JSON."""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_barriers as BR
import owl_sniper_livewide as LW
import owl_sniper_feed as F
import owl_sniper_prob as P
import owl_sniper_tf as TF
import v2_candles as VC

VERSION = "owl_sniper_live 1 (Round 20)"
MAX_COINS = 20          # a live look at 20 coins costs at most 20 requests plus retries
BUDGET = 30             # hard cap of requests in one run, retries included
TRIES = 3
BASE_STEP = 300         # seconds of one saved 5m candle


def _missing_rows(sym, last_ts, now, get, sleep, budget, stats):
    """Closed 5m candles after last_ts, newest first asked once, with retries. -> list of rows, or None when they could not be had (budget, failure, hole too big)."""
    newest = now // BASE_STEP * BASE_STEP - BASE_STEP
    miss = (newest - last_ts) // BASE_STEP
    if miss <= 0:
        return []
    if miss > VC.MAX_LIMIT - 2:
        return None                                         # too old: the collector's own refill handles it, a live look never bridges a big hole
    for n in range(TRIES):
        if budget[0] <= 0:
            stats["budget_hit"] = True
            return None
        budget[0] -= 1
        stats["requests"] += 1
        try:
            rows = get(VC.kline_url(sym, "5m", miss + 2))
            if isinstance(rows, list):
                got, _bad = VC.parse_klines(rows, "5m", now)
                return [r for r in got if r[0] > last_ts]
        except Exception:
            pass
        if n < TRIES - 1:
            stats["retries"] += 1
            sleep(n + 1)
    return None


def scan_live(d, now=None, interval="5m", network=True, get=None, sleep=None, cap=MAX_COINS):
    """-> dict (never raises on a bad coin): status, counts, cards (same shape as the feed's cards + 'barrier'), requests, retries, topped_up, failed, stale_left, network_used, note."""
    now = int(time.time() if now is None else now)
    model_file, _live_file, _kick = TF.files(interval)
    m = F.read_json(d, model_file) or {}
    out = {"version": VERSION, "saved_at": now, "interval": interval, "status": "NO_MODEL", "counts": {}, "cards": [], "requests": 0, "retries": 0, "topped_up": 0, "failed": 0,
           "stale_left": 0, "network_used": False, "note": "", "watch_only": True}
    eng = P.OwlSniperLive()
    if not (m.get("model") and eng.load_model(m["model"])):
        out["note"] = "No learned model yet (owl_sniper_feed makes it). Nothing was scanned."
        return out
    off = os.path.isfile(os.path.join(os.path.realpath(d), F.OFF_FILE))
    use_net = bool(network) and not off and VC.is_enabled(d)
    out["network_used"] = use_net
    out["note"] = "" if use_net else ("OwlSniper is switched off (file v2_sniper_off); saved candles only." if off else "Saved candles only (the network top-up is off).")
    get, sleep = get or VC.http_get, sleep or time.sleep
    con = F.open_ro(d)
    if con is None:
        out.update(status="NO_DATA", note="The market store does not exist yet.")
        return out
    budget, stats = [BUDGET], {"requests": 0, "retries": 0, "budget_hit": False}
    counts = dict((k, 0) for k in ("STANDBY", "SCANNING_MARKET", "BLOCK_TRADE", "SNIPER_LONG", "SNIPER_SHORT"))
    step, cards = TF.step(interval), []
    try:
        for sym in F.symbols(con, interval, cap):
            rows = F.load_tail(con, sym, interval)
            if not rows:
                continue
            if use_net and rows[-1][0] + F.STALE_STEPS * BASE_STEP < now:
                add = _missing_rows(sym, rows[-1][0], now, get, sleep, budget, stats)
                if add is None:
                    out["failed"] += 1
                elif add:
                    rows, out["topped_up"] = rows + add, out["topped_up"] + 1
            run = F.newest_run(rows, interval)
            if not run or run[-1][0] + F.STALE_STEPS * step < now:
                out["stale_left"] += 1
                continue
            r = eng.evaluate_live(run)
            counts[r["action"]] = counts.get(r["action"], 0) + 1
            if r["action"] in F.SHOW:
                card = F._card(sym, r)
                if r["action"] != "BLOCK_TRADE":
                    S = eng.features(run)
                    card["barrier"] = BR.plan_for_signal(S, S["n"] - 1)
                    w = LW.wide_for_card(S, run, sym, card.get("side") or ("LONG" if r["action"] == "SNIPER_LONG" else "SHORT"), interval)        # R3d: the 20 numbers for the autopilot
                    if w:
                        card["wide"], card["wide_missing"] = w["wide"], w["missing"]
                cards.append(card)
    finally:
        con.close()
    out.update(requests=stats["requests"], retries=stats["retries"], counts=counts, cards=sorted(cards, key=lambda c: c.get("t") or 0, reverse=True),
               status="OK" if sum(counts.values()) else "NO_DATA")
    if stats["budget_hit"]:
        out["note"] = (out["note"] + " The request budget (%d) was used up; the other coins keep their saved candles." % BUDGET).strip()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR", "."))
    ap.add_argument("--interval", default="5m", choices=TF.SUPPORTED)
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(scan_live(a.data, None, a.interval, not a.offline), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
