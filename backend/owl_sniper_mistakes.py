"""owl_sniper_mistakes.py - OwlSniper R26b: LEARN FROM MISTAKES. PAPER ONLY. Reads the closed Sniper paper trades, writes ONE own file (v2_sniper_mistakes.json). No order code.
Owner wish (rule 29): every closed trade gets a mistake tag, and the Sniper must STOP REPEATING a losing combo instead of buying the same loss again and again.
Tag = the R7 tag of owl_sniper_lessons.tag_trade (EXIT_ERROR / SIDEWAYS_LOSS / ENTRY_ERROR / OTHER_LOSS / GOOD / UNKNOWN). Not a new rule: one source of truth.
COMBO = coin | side | market state (for example SOLUSDT|LONG|SIDEWAYS). A combo is BLOCKED for the EXPLORE lane when its last 3 closed trades were ALL mistakes AND all lost money.
The block rests BLOCK_SEC (24 h) after the last loss; then the combo may try once more and learns again (a win clears it, a new loss streak blocks it again). A block never touches the real gate or the Current Bot.
JOURNAL = the newest 30 closed trades, each with one plain lesson sentence. The app shows it (Sniper tab, Mistakes card).
API: build(d, now), maybe_refresh(d, now, force), blocked(d, symbol, side, regime, now) -> '' or the plain reason, view(d). CLI: python3 backend/owl_sniper_mistakes.py [--data DIR] [--save]"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_feed as F
import owl_sniper_lessons as LS

VERSION = "owl_sniper_mistakes 1 (R26b)"
FILE = "v2_sniper_mistakes.json"
LAST_N, BLOCK_SEC, KEEP_J, MAX_ROWS = 3, 24 * 3600, 30, 1500
EVERY, MIN_GAP = 900, 120                     # refresh at most every 15 min, or 2 min after a trade closed
LESSON = {"EXIT_ERROR": "Reached +%.1fR, then gave it back. Book part of the profit earlier.",
          "SIDEWAYS_LOSS": "Lost in a choppy market that gave no room. Stay out of sideways time.",
          "ENTRY_ERROR": "Price went against the entry at once. The entry was early or a fake signal.",
          "OTHER_LOSS": "Went a little our way, then failed. Check the stop and the exit.",
          "GOOD": "Good trade: profit kept.", "UNKNOWN": "Not enough data on this trade to judge it."}
_last, _cache = {"ts": 0.0}, {"ts": 0.0, "data": None}


def _num(v):
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def combo_key(symbol, side, regime):
    return "%s|%s|%s" % (str(symbol or "?").upper(), str(side or "?").upper(), str(regime or "?").upper())


def build(d, now=None):
    """Archive -> tags, blocked combos, journal. Never raises."""
    now = time.time() if now is None else now
    out = {"version": VERSION, "paper_only": True, "made": int(now), "state": "NO_TRADES_YET", "trades": 0, "counts": {}, "blocked": {}, "journal": [], "rule": "A combo rests %d h after %d losses in a row." % (BLOCK_SEC // 3600, LAST_N)}
    try:
        rows, bad = LS.read_own(d)
        rows = rows[-MAX_ROWS:]
        if bad:
            out["problem"] = str(bad)[:80]
        if not rows:
            return out
        by, counts, jr = {}, {}, []
        for t in rows:
            tag, info = LS.tag_trade(t)
            side = "LONG" if str(t.get("action") or "").upper() == "BUY" else "SHORT"
            key = combo_key(t.get("symbol"), side, t.get("sniper_regime"))
            pnl, ts = _num(t.get("pnl_usdt")) or 0.0, _num(t.get("closed_at_ts")) or 0.0
            counts[tag] = counts.get(tag, 0) + 1
            if tag != "UNKNOWN":
                by.setdefault(key, []).append((tag, pnl, ts))
            text = LESSON[tag] % info.get("mfe_r", 0.0) if tag == "EXIT_ERROR" else LESSON[tag]
            jr.append({"t": int(ts), "symbol": t.get("symbol"), "side": side, "regime": str(t.get("sniper_regime") or "?").upper(), "tag": tag, "pnl": round(pnl, 4), "text": text})
        for key, seq in by.items():
            last = seq[-LAST_N:]
            if len(last) < LAST_N or not all(g in LS.MISTAKES and p < 0 for g, p, _t in last):
                continue
            until = last[-1][2] + BLOCK_SEC
            if until > now:
                sym, side, reg = key.split("|")
                cost = round(-sum(p for _g, p, _t in last), 2)
                out["blocked"][key] = {"symbol": sym, "side": side, "regime": reg, "losses": LAST_N, "cost_usdt": cost, "until": int(until),
                                       "text": "%s %s in a %s market lost its last %d trades (%.2f USDT). It rests until %s UTC." % (sym, side, reg.lower(), LAST_N, cost, time.strftime("%d %b %H:%M", time.gmtime(until)))}
        out.update(state="LEARNING", trades=len(rows), counts=counts, journal=sorted(jr, key=lambda x: -x["t"])[:KEEP_J])
    except Exception as e:
        out["state"], out["problem"] = "ERROR", "%s: %s" % (type(e).__name__, str(e)[:80])
    return out


def maybe_refresh(d, now=None, force=False):
    """Rebuilds and saves the file at most every EVERY s (MIN_GAP s when a trade just closed). -> the result or None."""
    now = time.time() if now is None else now
    if now - _last["ts"] < (MIN_GAP if force else EVERY):
        return None
    _last["ts"] = now
    st = build(d, now)
    F.write_json(d, FILE, st)
    _cache.update(ts=0.0, data=None)
    return st


def view(d):
    """The saved file (small cache of 30 s). None when it does not exist yet."""
    if time.time() - _cache["ts"] > 30:
        _cache.update(ts=time.time(), data=F.read_json(d, FILE))
    return _cache["data"]


def blocked(d, symbol, side, regime, now=None):
    """'' = the combo may open. Else the plain reason. Any problem = '' (a missing file never stops a trade)."""
    now = time.time() if now is None else now
    try:
        b = ((view(d) or {}).get("blocked") or {}).get(combo_key(symbol, side, regime))
        return str(b.get("text") or "Blocked: repeated losses.") if b and (b.get("until") or 0) > now else ""
    except Exception:
        return ""


def main(argv=None):
    ap = argparse.ArgumentParser(description="OwlSniper mistakes memory (paper only)")
    ap.add_argument("--data", default=os.environ.get("OWL_DATA_DIR") or os.path.expanduser("~/storage/shared/owl_data"))
    ap.add_argument("--save", action="store_true")
    a = ap.parse_args(argv)
    st = build(a.data)
    if a.save:
        F.write_json(a.data, FILE, st)
    print(json.dumps(dict(st, journal=st["journal"][:5]), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
