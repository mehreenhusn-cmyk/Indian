"""owl_sniper_paper.py - OwlSniper Round 30: the PAPER BRIDGE between the executor gate (owl_sniper_exec.py) and the paper trader (recovered_bot/paper_trader.py).
What this file is: the owner said "paper must work" (Round 30). Nothing in owl_sniper_exec.py changed: every gate (armed, paper, signal, fresh, TRENDING, 85% floor proven, stop range, cap 1, kill switch,
same signal never twice) still runs first. This file only supplies the `opener` the executor was built to accept, and closes the loop afterwards. LIVE ORDERS STILL DO NOT EXIST.
It must run INSIDE the backend process (paper_trader keeps its positions in memory), so it is started by api/sniper_paper.py, never by Termux.
What it does:
  opener      a Sniper order -> one paper trade (source "sniper", bot b1). It refuses when the coin is already open in ANY bot (open_paper_trade would otherwise close that trade as REVERSED), when the
              order has no target price, or when the 10 USDT base / 1x cannot be forced on the new trade (then the trade is closed again at once). The three exits of the triple barrier:
              stop and target are the paper trader's own SL / TP4 (TP1-TP4 are all set to the target, so there is no break-even shift); the time limit is done by sync().
  sync        for every open Sniper order: still open + older than the time limit -> close it at the live price; closed -> report its NET result to the executor (record_close), which frees the slot
              and turns the kill switch on by itself at the daily loss limit. A slot with no trade behind it is freed after a few minutes (result counted as 0, written in the executor log).
  step        sync, then (only when the executor is ARMED) offer the newest cards to the executor. Used by the background loop in api/sniper_paper.py every ~20 s.
  enter_symbol  the PAPER ENTER button: the same gates, for one coin. If the executor is not armed the answer is the plain text "OFF (not armed)".
Arming stays a 2-step Termux command (owl_sniper_exec.py arm / confirm). No route can arm."""
import os
import sys
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_barriers as BR
import owl_sniper_exec as EX
import owl_sniper_feed as F
import owl_sniper_tf as TF

VERSION = "owl_sniper_paper 1 (Round 30)"
MAP_FILE = "v2_sniper_paper.json"          # {"ids": {client id: {"trade_id": n, "ts": n}}}
SOURCE, BOT = "sniper", "b1"
INTERVAL = "5m"
NO_ID_SEC = 180                            # an executor slot with no paper trade behind it is freed after this long
UNKNOWN_SEC = 900                          # a trade that is neither open nor in the closed list is freed after this long (after its time limit)
KEEP_MAP = 200
LOCK = threading.Lock()                    # the background loop and the PAPER ENTER button never run the gates at the same moment


def _map(d):
    m = F.read_json(d, MAP_FILE) or {}
    return m.get("ids") if isinstance(m.get("ids"), dict) else {}


def _map_put(d, cid, trade_id, now):
    ids = _map(d)
    ids[cid] = {"trade_id": int(trade_id), "ts": int(now)}
    if len(ids) > KEEP_MAP:
        for k in sorted(ids, key=lambda x: ids[x].get("ts", 0))[:len(ids) - KEEP_MAP]:
            ids.pop(k, None)
    return F.write_json(d, MAP_FILE, {"version": VERSION, "ids": ids})


def _signal(o):
    """The order -> the small object open_paper_trade reads. TP1 to TP4 all sit on the one target: the Sniper has one profit line, so no TP1 break-even shift can happen."""
    tp, e = float(o["take_profit"]), float(o["entry"])
    return SimpleNamespace(symbol=o["symbol"], action="BUY" if o["side"] == "LONG" else "SELL", entry_price=e, stop_loss=float(o["stop"]), tp1=tp, tp2=tp, tp3=tp, tp4=tp,
                           signal_time=time.strftime("%H:%M:%S"), current_price=e, candle_index=0, signal_no=None)


def _open_ids(pt):
    with pt._lock:
        return {tid: p.get("symbol") for tid, p in pt._positions.items()}


def _force_base(pt, tid, o):
    """The Sniper's capital rules assume 10 USDT at 1x. Put exactly that on the new trade (and a plain label), whatever the Settings say. False = could not."""
    try:
        with pt._lock:
            p = pt._positions.get(tid)
            if p is None:
                return False
            p.update(invest_usdt=float(o["invest_usdt"]), leverage=1.0, btc_fixed_size=False,
                     trigger="OwlSniper %s signal (win chance %.0f%%, stop %.2f%%)" % (o["side"], 100.0 * float(o.get("confidence") or 0.0), float(o.get("stop_pct") or 0.0)),
                     sl_type="OwlSniper stop (%.2f%%)" % float(o.get("stop_pct") or 0.0), timeframe=INTERVAL)
        pt._save()
        return True
    except Exception:
        return False


def make_opener(d, pt, now=None):
    """-> opener(order) for EX.decide(). True only when ONE paper trade is open and noted."""
    def opener(o):
        try:
            tp = o.get("take_profit")
            if not isinstance(tp, (int, float)) or tp <= 0:
                return False                                            # the triple barrier needs its profit line
            if o["symbol"] in pt.get_open_symbols():
                return False                                            # never touch a trade of another bot
            tid = pt.open_paper_trade(_signal(o), source=SOURCE, bot=BOT)
            if tid is None:
                return False
            if not _force_base(pt, tid, o):
                pt.close_position_manual(tid)
                return False
            _map_put(d, o["id"], tid, time.time() if now is None else now)   # a failed note is not fatal: sync() can still find the trade by coin + time
            return True
        except Exception:
            return False
    return opener


def _find_open(pt, o):
    with pt._lock:
        for tid, p in pt._positions.items():
            if p.get("source") == SOURCE and p.get("symbol") == o.get("symbol") and (p.get("opened_at_ts") or 0) >= o.get("created", 0) - 5:
                return tid
    return None


def sync(d, pt, ts, now=None):
    """Close the loop for every open Sniper order. Never raises. -> small dict (what was done)."""
    now = time.time() if now is None else now
    out = {"closed": 0, "time_exit": 0, "released": 0}
    try:
        st = EX._load(d)
    except EX.StateBroken:
        return dict(out, state="broken")
    book = st.get("open") or {}
    if not book:
        return dict(out, state="idle")
    ids, live = _map(d), _open_ids(pt)
    rows = {r.get("id"): r for r in ts.get_recent_closed(limit=300, net=True, bot=BOT) if isinstance(r, dict)}
    hold = BR.HOLD * TF.step(INTERVAL)
    for cid, o in list(book.items()):
        age = now - o.get("created", now)
        tid = (ids.get(cid) or {}).get("trade_id")
        if tid is None:
            tid = _find_open(pt, o)
        if tid is None:
            if age > NO_ID_SEC:
                EX.record_close(d, cid, 0.0, now)                         # no trade behind the slot: free it (result counted as 0)
                out["released"] += 1
            continue
        if tid in live:
            if age >= hold:
                r = pt.close_position_manual(tid) or {}
                out["time_exit"] += 1 if r.get("ok") else 0
            continue
        row = rows.get(tid)
        if row is not None:
            EX.record_close(d, cid, float(row.get("pnl_usdt") or 0.0), now)
            out["closed"] += 1
        elif age > hold + UNKNOWN_SEC:
            EX.record_close(d, cid, 0.0, now)
            out["released"] += 1
    return dict(out, state="ok")


def _cards(d):
    live = F.read_json(d, F.LIVE_FILE) or {}
    return [c for c in (live.get("cards") or []) if isinstance(c, dict) and c.get("action") in ("SNIPER_LONG", "SNIPER_SHORT")], live.get("floor_verified") is True


def step(d, pt, ts, now=None):
    """One turn of the background loop. Never raises."""
    now = time.time() if now is None else now
    with LOCK:
        try:
            res = {"sync": sync(d, pt, ts, now)}
            s = EX.status(d, now)
            if not s.get("ok") or not s.get("armed") or os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
                return dict(res, auto="off")
            cards, verified = _cards(d)
            opener = make_opener(d, pt, now)
            for c in cards:                                           # newest first: the first card that passes every gate is opened, the cap of 1 stops the rest
                r = EX.decide(d, c, verified, now, INTERVAL, opener)
                if r["decision"] == "OPEN":
                    return dict(res, auto="opened", symbol=c.get("symbol"))
            return dict(res, auto="waiting", cards=len(cards))
        except Exception as e:
            return {"auto": "error", "text": str(e)[:120]}


def enter_symbol(d, pt, ts, symbol, now=None):
    """PAPER ENTER for one coin -> the executor's answer {decision, gate, text, order}. Never raises."""
    now = time.time() if now is None else now
    with LOCK:
        try:
            sync(d, pt, ts, now)
            cards, verified = _cards(d)
            card = next((c for c in cards if c.get("symbol") == symbol), None)
            if card is None:
                return {"decision": "BLOCKED", "gate": "signal", "text": "There is no live Sniper signal for %s right now." % symbol, "order": None}
            return EX.decide(d, card, verified, now, INTERVAL, make_opener(d, pt, now))
        except Exception as e:
            return {"decision": "BLOCKED", "gate": "error", "text": "The paper entry could not be made (%s)." % str(e)[:80], "order": None}
