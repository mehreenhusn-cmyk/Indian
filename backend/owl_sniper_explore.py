"""owl_sniper_explore.py - OwlSniper R26a: EXPLORE paper trades. PAPER ONLY. No real order, no live path.
Why: the win-chance model needs 30 TRAIN trades, so while it was not trained the scanner returned 0 cards, the LEARN lane got no signal and Sniper learned nothing.
What: once per 5m candle this looks at every coin (read-only market store) and makes an EXPLORE card from the plain indicator signal (EMA30/50 cross + TSI + Z-Score, no model needed, regime NOT a gate).
The card says: not a qualified signal, win chance unknown. It goes to the LEARN lane only (owl_sniper_exec.route, xp card), never to the real 85% gate. Win AND loss are both data.
Size / caps live in owl_sniper_learn.py (XP_*): 100 USDT margin, 10x, many open, own daily runaway cap. Stop is the SD line; if it is outside the 0.2-1.9% gate range it is moved inside it (card says stop_moved). Target = 2R first guess (the exit learner may move it).
R33 (Part 13, owner: "the Sniper MUST take trades, mistakes are fine"): when the plain signal gives fewer than FILL_MIN cards in a candle step, FILL cards are added: the FILL_MAX most-moving coins (last 3 candles), side = the way they just moved, same stop / target / LEARN gate / tiny size / paper only. Card says fill = True and "no signal, learning trade". Win AND loss are data. The only stops stay the LEARN caps (open trades, daily runaway cap) and the kill switch.
Result file: v2_sniper_explore.json {saved_at, scanned, stale, cards[]}. Nothing else is written. Dart/app part comes in R26b / R29."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_engine_b as B
import owl_sniper_feed as F
import owl_sniper_tf as TF

VERSION = "owl_sniper_explore 2 (R26a + R33 FILL)"
FILE = "v2_sniper_explore.json"
INTERVAL = F.INTERVAL
LOOKBACK = 3                       # the newest 3 candles are checked (the LEARN gate accepts a signal up to 3 candle steps old)
RR = 2.0                           # first guess for the target: 2 x the stop distance
SL_MIN, SL_MAX = 0.2, 1.9          # inside the engine gate range 0.15 - 2.0 %
KEEP = 80
FILL_MIN, FILL_MAX = 3, 4          # R33: fewer than FILL_MIN signal cards in a step -> top up with up to FILL_MAX learning (FILL) cards
FILL_BACK = 3                      # a FILL card follows the move of the last 3 candles
_last = {"bucket": None}


def _card(sym, S, i, sig):
    side, e = sig["side"], float(S["c"][i])
    raw = B.stop_price(S, i, side)
    if raw is None or e <= 0:
        return None
    dist = ((e - raw) if side == "LONG" else (raw - e)) / e * 100.0
    d = min(SL_MAX, max(SL_MIN, dist if dist > 0 else SL_MIN))
    moved = abs(d - dist) > 1e-9
    sign = -1.0 if side == "LONG" else 1.0
    sl, tp = e * (1.0 + sign * d / 100.0), e * (1.0 - sign * RR * d / 100.0)
    basis = list(sig.get("why") or []) + ["Market regime at entry: %s" % sig.get("regime")]
    return {"symbol": sym, "action": "SNIPER_LONG" if side == "LONG" else "SNIPER_SHORT", "side": side, "tag": "EXPLORE", "explore": True, "xp": True,
            "reason": "EXPLORE: " + "; ".join(basis[:2]), "basis": basis, "confidence": None, "floor_verified": False,
            "entry_price": round(e, 8), "stop_loss": round(sl, 8), "take_profit": round(tp, 8), "stop_pct": round(d, 3), "stop_moved": moved, "rr": RR,
            "regime": sig.get("regime"), "t": S["t"][i], "z": None if sig.get("z") is None else round(sig["z"], 3), "sd_len": S["cfg"]["sd_len"],
            "report": "Not a qualified signal. Win chance is unknown. EXPLORE paper trade: it is taken to learn from the win or the loss."}


def _fill_cards(fills, have):
    """FILL cards: the most-moving coins that have no signal card yet. Side = the way the last FILL_BACK candles moved. Never raises."""
    out = []
    try:
        for mv, sym, S in sorted(fills, key=lambda x: -abs(x[0])):
            if len(out) >= FILL_MAX or len(have) + len(out) >= FILL_MIN + FILL_MAX:
                break
            if sym in have or mv == 0:
                continue
            i = S["n"] - 1
            sig = {"side": "LONG" if mv > 0 else "SHORT", "regime": None, "z": None,
                   "why": ["No signal: learning trade, %s %.2f%% in the last %d candles" % ("up" if mv > 0 else "down", abs(mv) * 100.0, FILL_BACK)]}
            c = _card(sym, S, i, sig)
            if c:
                c["fill"] = True
                c["reason"] = "EXPLORE FILL: " + sig["why"][0]
                out.append(c)
    except Exception:
        pass
    return out


def scan(d, now=None):
    """One look at every coin -> the EXPLORE cards of the newest candles (saved). Never raises."""
    now = int(time.time() if now is None else now)
    out = {"version": VERSION, "saved_at": now, "interval": INTERVAL, "scanned": 0, "stale": 0, "cards": []}
    try:
        con = F.open_ro(d)
        if con is None:
            out["state"] = "NO_DATA"
            return out
        step, cards, fills = TF.step(INTERVAL), [], []
        try:
            for sym in F.symbols(con, INTERVAL, F.MAX_COINS):
                run = F.newest_run(F.load_tail(con, sym, INTERVAL), INTERVAL)
                if not run or run[-1][0] + F.STALE_STEPS * step < now:
                    out["stale"] += 1
                    continue
                try:
                    S = B.build_features(run)
                except ValueError:
                    continue
                out["scanned"] += 1
                if S["n"] > FILL_BACK + 1 and float(S["c"][S["n"] - 1 - FILL_BACK]) > 0:
                    fills.append((float(S["c"][S["n"] - 1]) / float(S["c"][S["n"] - 1 - FILL_BACK]) - 1.0, sym, S))
                for i in range(S["n"] - 1, max(S["n"] - 1 - LOOKBACK, 0), -1):
                    sig = B.raw_signal(S, i)
                    c = _card(sym, S, i, sig) if sig.get("side") else None
                    if c:
                        cards.append(c)
        finally:
            con.close()
        n_sig = len(cards)
        if n_sig < FILL_MIN:
            cards += _fill_cards(fills, set(c["symbol"] for c in cards))
        cards.sort(key=lambda c: c.get("t") or 0, reverse=True)
        out.update(state="OK", cards=cards[:KEEP], signal_cards=n_sig, fill_cards=len(cards) - n_sig)
    except Exception as e:
        out["state"] = "ERROR"
        out["text"] = str(e)[:80]
    F.write_json(d, FILE, out)
    return out


def maybe_scan(d, now=None):
    """Runs scan() at most once per candle step (cheap for the phone). -> the result or None."""
    now = time.time() if now is None else now
    b = int(now // TF.step(INTERVAL))
    if _last["bucket"] == b:
        return None
    _last["bucket"] = b
    return scan(d, now)


def cards(d, now=None):
    """The saved EXPLORE cards that are still fresh (newest first)."""
    now = time.time() if now is None else now
    lim = F.STALE_STEPS * TF.step(INTERVAL)
    return [c for c in ((F.read_json(d, FILE) or {}).get("cards") or []) if isinstance(c, dict) and now - (c.get("t") or 0) <= lim]
