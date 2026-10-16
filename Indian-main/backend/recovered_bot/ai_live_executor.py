"""
ai_live_executor.py - STAGE 2 (file 4 of 4): turns the AI Coach's decisions into REAL Binance orders on the AI's own account.

The AI Coach keeps deciding exactly as it does in paper (same entries, same exits, same day plan). This file only MIRRORS
those decisions, one coach event at a time, on its own worker thread (so a slow network can never block the coach):
  open  -> guard check -> isolated margin + leverage -> MARKET entry -> confirm the position exists -> place the stop.
           No stop = no trade: if the stop cannot be placed the position is closed at once and the system halts.
  stop  -> the coach moved its stop (entry / trail). The NEW stop is placed first, the old one cancelled after, so a
           position is never without a stop. A stop is only ever TIGHTENED, never loosened.
  close -> cancel the stop, close the position reduce-only, then read the real fills for the real P&L (fees included).
Every 15 s a reconcile compares the exchange with the books: a position that vanished (the stop was hit) is settled; a
position without a resting stop gets one again; a position the AI does not know about is reported and NOT touched.
Master switch OFF or halted: no NEW trades, but open ones are still protected and closed normally.
panic(): halts, cancels every stop and closes every position on the AI account (that account is the AI's alone).
Honest limits: the real P&L can differ from the paper P&L (slippage, funding, partial fills); first run with a tiny margin.
"""
import json
import os
import queue
import re
import threading
import time

from . import ai_live_guard as G
from .ai_live_client import Client, ApiError, AMBIGUOUS

RECONCILE_S = 15.0
STOP_PUSH_MIN_S = 5.0
_sleep = time.sleep                      # tests replace this

_lock = threading.RLock()                # the books
_io = threading.RLock()                  # one exchange conversation at a time
_q = queue.Queue(maxsize=500)
_st = {"open": {}, "closed": [], "events": [], "upnl": 0.0, "balance": None, "last_reconcile": 0.0, "unknown": []}
_path = None
_client = None
_started = False


# ------------------------------------------------------------------ setup / persistence
def init(ai_dir):
    global _path
    _path = os.path.join(ai_dir, "live_trades.json")
    try:
        if os.path.isfile(_path):
            with open(_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            with _lock:
                _st["open"] = dict(d.get("open") or {})
                _st["closed"] = list(d.get("closed") or [])[-500:]
                _st["events"] = list(d.get("events") or [])[-200:]
    except Exception as e:
        print(f"[AILive] load: {e}")


def _save():
    if not _path:
        return
    try:
        with _lock:
            snap = {"open": _st["open"], "closed": _st["closed"][-500:], "events": _st["events"][-200:]}
            tmp = _path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(snap, f)
            os.replace(tmp, _path)
    except Exception as e:
        print(f"[AILive] save: {e}")


def set_client(c):
    global _client
    _client = c


def client():
    global _client
    if _client is None:
        _client = Client()
    return _client


def _event(text):
    with _lock:
        _st["events"].append({"t": time.time(), "text": str(text)[:300]})
        _st["events"] = _st["events"][-200:]
    print(f"[AILive] {text}")


# ------------------------------------------------------------------ small helpers
def _cid(bid, tag):
    return ("ai" + re.sub(r"[^A-Za-z0-9_-]", "", str(bid))[-20:] + tag)[:36]


def _close_side(side):
    return "SELL" if side == "BUY" else "BUY"


def _today():
    t0 = G.day_start()
    with _lock:
        return round(sum(float(c.get("pnl") or 0.0) for c in _st["closed"] if float(c.get("t1") or 0) >= t0), 4)


def _wait_position(sym, want, tries=6, delay=0.5):
    """Poll until a position on `sym` exists (want=True) or is gone (want=False). Returns the position or None."""
    c = client()
    for _ in range(tries):
        ps = c.positions(sym)
        if want and ps:
            return ps[0]
        if not want and not ps:
            return None
        _sleep(delay)
    ps = c.positions(sym)
    return ps[0] if (want and ps) else (ps[0] if (not want and ps) else None)


# ------------------------------------------------------------------ public entry from the coach (never blocks)
def submit(kind, v, px=None, reason=""):
    try:
        bid = str(v.get("bot_id"))
        if kind == "open":
            if not G.is_on():
                return
        else:
            with _lock:
                if bid not in _st["open"]:
                    return
        snap = {k: v.get(k) for k in ("bot_id", "sym", "side", "entry", "sl", "trail", "lev", "tps", "hit")}
        _q.put_nowait((kind, snap, px, str(reason)[:200]))
    except queue.Full:
        _event("event queue full: a coach event was dropped")
    except Exception as e:
        print(f"[AILive] submit: {e}")


# ------------------------------------------------------------------ handlers (worker thread only)
def _open(s):
    bid, sym, side = str(s["bot_id"]), s["sym"], s["side"]
    with _lock:
        if bid in _st["open"]:
            return
        n_open, upnl = len(_st["open"]), _st["upnl"]
    ok, why = G.check(n_open, _today(), upnl)
    if not ok:
        _event("%s %s not opened for real: %s" % (sym, side, why))
        return
    cfg = G.cfg()
    with _io:
        c = client()
        if c.dual_side():
            G.halt("the AI account is in hedge mode; switch it to one-way mode in Binance, then reset")
            _event("HALTED: the AI account is in hedge mode")
            return
        if c.positions(sym):
            _event("%s skipped for real: a position on this coin already exists on the AI account" % sym)
            return
        lev = max(1, int(min(float(s.get("lev") or 1), cfg["max_leverage"])))
        margin = float(G.margin_for(sym))         # global margin, lowered by this coin's own cap if it has one
        if c.balance() < margin:
            _event("%s skipped for real: free balance is below the margin per trade (%.2f)" % (sym, margin))
            return
        price = c.price(sym)
        if price <= 0:
            _event("%s skipped for real: no price" % sym)
            return
        sl = float(s["sl"])
        if (side == "BUY" and sl >= price) or (side == "SELL" and sl <= price):
            _event("%s skipped for real: price is already beyond the stop" % sym)
            return
        qty = c.round_qty(sym, margin * lev / price)
        if qty <= 0 or qty * price < c.min_notional(sym):
            _event("%s skipped for real: margin %.2f at %dx is below this coin's minimum order size" % (sym, margin, lev))
            return
        c.set_margin_type(sym, "ISOLATED")
        c.set_leverage(sym, lev)
        try:
            c.market(sym, side, qty, cid=_cid(bid, "o"))
        except ApiError as e:
            if e.code in AMBIGUOUS or e.code == 0:
                pos = _wait_position(sym, True)
                if not pos:
                    G.halt("an entry order's result is unknown (%s); check the AI account, then reset" % e.msg[:60])
                    _event("HALTED: entry result unknown for %s" % sym)
                    return
            else:
                _event("%s real entry rejected by Binance: %s" % (sym, e.msg[:120]))
                return
        pos = _wait_position(sym, True)
        if not pos:
            G.halt("an entry was sent but no position appeared; check the AI account, then reset")
            _event("HALTED: %s entry not confirmed" % sym)
            return
        qty_real = abs(pos["amt"])
        try:
            stop = c.place_stop(sym, _close_side(side), sl)
        except Exception as e:
            _event("%s stop could not be placed (%s): closing the position now" % (sym, str(e)[:100]))
            try:
                c.market(sym, _close_side(side), qty_real, reduce_only=True, cid=_cid(bid, "x"))
            except Exception as e2:
                _event("EMERGENCY CLOSE FAILED for %s: %s" % (sym, str(e2)[:100]))
            G.halt("a stop could not be placed on %s; the position was closed (or must be closed by hand)" % sym)
            return
        now = time.time()
        with _lock:
            real_entry = pos["entry"] or price
            paper = float(s.get("entry") or 0)
            # Positive = the real fill was WORSE than the paper entry (long filled higher / short filled lower), in percent.
            slip = round(((real_entry - paper) if side == "BUY" else (paper - real_entry)) / paper * 100.0, 4) if paper > 0 else None
            _st["open"][bid] = {"bot_id": bid, "sym": sym, "side": side, "qty": qty_real, "entry": real_entry, "paper_entry": paper or None, "slip_pct": slip,
                                "stop_px": stop["price"], "stops": [{"id": stop["id"], "kind": stop["kind"]}],
                                "t0": now, "t0_ms": int(now * 1000), "lev": lev, "margin": margin, "pushed": now}
        _event("%s %s opened for real: %.6g at %.6g, %dx, stop %.6g" % (sym, "LONG" if side == "BUY" else "SHORT", qty_real, pos["entry"] or price, lev, stop["price"]))
    _save()


def _stop(s):
    bid = str(s["bot_id"])
    with _lock:
        rec = _st["open"].get(bid)
        if not rec:
            return
        new = s["trail"] if s.get("trail") is not None else s["sl"]
        if new is None:
            return
        new, last = float(new), float(rec["stop_px"])
        long_ = rec["side"] == "BUY"
        tighter = (new > last) if long_ else (new < last)
        if not tighter or abs(new - last) / max(abs(last), 1e-12) < 1e-6 or time.time() - rec["pushed"] < STOP_PUSH_MIN_S:
            return
        sym, old_stops = rec["sym"], list(rec["stops"])
    with _io:
        c = client()
        try:
            fresh = c.place_stop(sym, _close_side(rec["side"]), new)      # NEW stop first ...
        except ApiError as e:
            _event("%s stop not moved (the old stop stays): %s" % (sym, e.msg[:100]))
            with _lock:
                rec["pushed"] = time.time()
            return
        for o in old_stops:                                                # ... old one cancelled after
            try:
                c.cancel_stop(sym, o)
            except Exception as e:
                _event("%s old stop could not be cancelled (%s)" % (sym, str(e)[:80]))
        with _lock:
            rec["stops"], rec["stop_px"], rec["pushed"] = [{"id": fresh["id"], "kind": fresh["kind"]}], fresh["price"], time.time()
    _event("%s real stop moved to %.6g" % (sym, fresh["price"]))
    _save()


def _finish(bid, reason, by):
    """Read the real fills, book the closed trade, drop the open record. Caller holds _io."""
    with _lock:
        rec = _st["open"].get(bid)
    if not rec:
        return
    c = client()
    res = {"pnl": 0.0, "fee": 0.0, "n": 0}
    for _ in range(3):
        try:
            res = c.trades_since(rec["sym"], rec["t0_ms"] - 1000)
        except Exception:
            res = {"pnl": 0.0, "fee": 0.0, "n": 0}
        if res["n"] >= 2:
            break
        _sleep(1.0)
    net = round(res["pnl"] - res["fee"], 4)
    row = {"bot_id": bid, "sym": rec["sym"], "side": rec["side"], "qty": rec["qty"], "entry": rec["entry"], "t0": rec["t0"],
           "t1": time.time(), "pnl": net, "fee": round(res["fee"], 4), "fills": res["n"], "reason": str(reason)[:160], "by": by,
           "margin": rec["margin"], "paper_entry": rec.get("paper_entry"), "slip_pct": rec.get("slip_pct"), "roi": round(net / rec["margin"] * 100.0, 2) if rec.get("margin") else None}
    with _lock:
        _st["closed"].append(row)
        _st["closed"] = _st["closed"][-500:]
        _st["open"].pop(bid, None)
    _event("%s real trade closed (%s): %+.4f USDT after fees" % (rec["sym"], by, net))
    _save()


def _close(s, reason):
    bid = str(s["bot_id"])
    with _lock:
        rec = _st["open"].get(bid)
    if not rec:
        return
    sym = rec["sym"]
    with _io:
        c = client()
        for o in list(rec["stops"]):
            try:
                c.cancel_stop(sym, o)
            except Exception as e:
                _event("%s stop cancel failed before close (%s)" % (sym, str(e)[:80]))
        ps = c.positions(sym)
        if ps:
            try:
                c.market(sym, _close_side(rec["side"]), abs(ps[0]["amt"]), reduce_only=True, cid=_cid(bid, "c"))
            except ApiError as e:
                _event("%s REAL CLOSE FAILED (%s): will retry at the next check" % (sym, e.msg[:100]))
                try:                                                       # never leave it without a stop
                    fresh = c.place_stop(sym, _close_side(rec["side"]), rec["stop_px"])
                    with _lock:
                        rec["stops"] = [{"id": fresh["id"], "kind": fresh["kind"]}]
                except Exception:
                    pass
                return
            _wait_position(sym, False)
            _finish(bid, reason or "closed by the AI", "AI close")
        else:
            _finish(bid, reason or "closed by the exchange stop", "exchange stop")


def _handle(item):
    kind, s, px, reason = item
    try:
        if kind == "open":
            _open(s)
        elif kind == "stop":
            _stop(s)
        elif kind == "close":
            _close(s, reason)
    except ApiError as e:
        _event("%s %s failed on Binance: %s" % (s.get("sym"), kind, e.msg[:120]))
    except Exception as e:
        _event("%s %s error: %s: %s" % (s.get("sym"), kind, type(e).__name__, str(e)[:100]))


# ------------------------------------------------------------------ reconcile
def reconcile():
    with _lock:
        recs = dict(_st["open"])
    if not recs and not G.view()["enabled"]:
        return
    with _io:
        c = client()
        try:
            pos = {p["symbol"]: p for p in c.positions()}
            bal = c.balance()
        except Exception as e:
            _event("reconcile could not read the AI account: %s" % str(e)[:100])
            return
        upnl = sum((p["mark"] - p["entry"]) * p["amt"] for p in pos.values())
        for bid, rec in recs.items():
            sym = rec["sym"]
            p = pos.get(sym)
            if not p:
                try:
                    for o in c.open_stops(sym):
                        c.cancel_stop(sym, o)
                except Exception:
                    pass
                _finish(bid, "the exchange stop closed it", "exchange stop")
                continue
            try:
                if not c.open_stops(sym):
                    fresh = c.place_stop(sym, _close_side(rec["side"]), rec["stop_px"])
                    with _lock:
                        rec["stops"] = [{"id": fresh["id"], "kind": fresh["kind"]}]
                    _event("%s had no resting stop: a new one was placed at %.6g" % (sym, fresh["price"]))
            except Exception as e:
                _event("%s HAS NO STOP and one could not be placed (%s): closing it" % (sym, str(e)[:80]))
                try:
                    c.market(sym, _close_side(rec["side"]), abs(p["amt"]), reduce_only=True, cid=_cid(bid, "r"))
                    _wait_position(sym, False)
                    _finish(bid, "closed: its stop could not be restored", "safety close")
                except Exception as e2:
                    _event("SAFETY CLOSE FAILED for %s: %s" % (sym, str(e2)[:80]))
                G.halt("a stop could not be restored on %s" % sym)
        known = {r["sym"] for r in recs.values()}
        unknown = sorted(s for s in pos if s not in known)
        with _lock:
            fresh_unknown = [u for u in unknown if u not in _st["unknown"]]
            _st["unknown"], _st["upnl"], _st["balance"], _st["last_reconcile"] = unknown, round(upnl, 4), bal, time.time()
        if fresh_unknown:
            _event("a position the AI did not open exists on the AI account (%s). It is NOT touched." % ", ".join(fresh_unknown))


# ------------------------------------------------------------------ owner actions
def verify():
    """Connection check used before switching on. {"ok", "why", "balance"}."""
    try:
        with _io:
            c = client()
            if c.dual_side():
                G.note_verified(False)
                return {"ok": False, "why": "The AI account is in hedge mode. Switch it to one-way mode in Binance.", "balance": None}
            bal = c.balance()
        G.note_verified(True)
        return {"ok": True, "why": "Connected. Free balance %.2f USDT, one-way mode." % bal, "balance": bal}
    except ApiError as e:
        G.note_verified(False)
        return {"ok": False, "why": "Binance said: %s" % e.msg[:140], "balance": None}
    except Exception as e:
        G.note_verified(False)
        return {"ok": False, "why": "Could not check: %s" % type(e).__name__, "balance": None}


def panic(why="PANIC button"):
    G.halt(why)
    closed = []
    with _io:
        c = client()
        try:
            positions = c.positions()
        except Exception as e:
            _event("PANIC: could not read positions (%s)" % str(e)[:80])
            return {"ok": False, "closed": [], "error": str(e)[:100]}
        for p in positions:
            sym = p["symbol"]
            try:
                for o in c.open_stops(sym):
                    c.cancel_stop(sym, o)
                c.market(sym, "SELL" if p["amt"] > 0 else "BUY", abs(p["amt"]), reduce_only=True, cid=_cid(sym, "p"))
                closed.append(sym)
            except Exception as e:
                _event("PANIC: %s could not be closed (%s)" % (sym, str(e)[:80]))
        _sleep(1.0)
        with _lock:
            ids = list(_st["open"].keys())
        for bid in ids:
            _finish(bid, "PANIC: closed by the owner", "panic")
    _event("PANIC done: closed %s" % (", ".join(closed) or "nothing"))
    return {"ok": True, "closed": closed}


def _slip_view():
    """Real-vs-paper entry slippage over the last real trades (caller holds _lock). Positive = real fills were worse."""
    xs = [float(c["slip_pct"]) for c in _st["closed"][-50:] if c.get("slip_pct") is not None]
    xs += [float(o["slip_pct"]) for o in _st["open"].values() if o.get("slip_pct") is not None]
    if not xs:
        return {"n": 0, "avg_pct": None, "worst_pct": None}
    return {"n": len(xs), "avg_pct": round(sum(xs) / len(xs), 4), "worst_pct": round(max(xs), 4)}


def status():
    from . import ai_live_keys
    with _lock:
        t0 = G.day_start()
        today = [c for c in _st["closed"] if float(c.get("t1") or 0) >= t0]
        return {"guard": G.view(), "key": {"has": ai_live_keys.has_keys(), "mask": ai_live_keys.mask()},
                "open": list(_st["open"].values()), "closed": list(reversed(_st["closed"][-20:])),
                "today": {"pnl": round(sum(float(c.get("pnl") or 0) for c in today), 4), "n": len(today)},
                "upnl": _st["upnl"], "balance": _st["balance"], "unknown": list(_st["unknown"]),
                "slip": _slip_view(), "last_reconcile": _st["last_reconcile"], "events": list(reversed(_st["events"][-25:])),
                "confirm_text": G.CONFIRM_TEXT}


# ------------------------------------------------------------------ worker
def _loop():
    last = 0.0
    while True:
        try:
            item = _q.get(timeout=1.0)
            _handle(item)
        except queue.Empty:
            pass
        except Exception as e:
            print(f"[AILive] worker: {e}")
        try:
            if time.time() - last >= RECONCILE_S:
                last = time.time()
                reconcile()
        except Exception as e:
            print(f"[AILive] reconcile: {e}")


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="ai-live", daemon=True).start()
