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
  step        sync, then offer the newest cards to EX.route() (Part 4): the REAL gate first (only while ARMED), else the LEARN gate (paper only, tag LEARN, own size and state). Used by the background loop in api/sniper_paper.py every ~20 s.
  enter_symbol  the PAPER ENTER button: the same route, for one coin. Not armed -> the real gate says "OFF (not armed)" and the LEARN gate may still open a tiny paper LEARN trade (the answer says lane LEARN).
Arming stays a 2-step Termux command (owl_sniper_exec.py arm / confirm). No route can arm."""
import os
import sys
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owl_sniper_barriers as BR
import owl_sniper_corr as CR
import owl_sniper_eva_hook as EVH
import owl_sniper_exec as EX
import owl_sniper_explore as XP
import owl_sniper_feed as F
import owl_sniper_killreset as KR
import owl_sniper_learn as LN
import owl_sniper_mistakes as MS
import owl_sniper_record as REC
import owl_sniper_xrules as XR
import owl_sniper_tf as TF

VERSION = "owl_sniper_paper 1 (Round 30)"
MAP_FILE = "v2_sniper_paper.json"          # {"ids": {client id: {"trade_id": n, "ts": n}}}
SOURCE, BOT = "sniper", "b1"
LEARN_SOURCE = "sniper_learn"                # PART 4: LEARN paper trades carry this source (and tag LEARN, trigger text "OwlSniper LEARN ..."), so they can always be told apart from real-gate trades
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
            learn = o.get("tag") == LN.TAG
            p.update(invest_usdt=float(o["invest_usdt"]), leverage=float(o.get("leverage") or 1.0), btc_fixed_size=False,
                     trigger="OwlSniper %s%s signal (win chance %.0f%%, stop %.2f%%)" % ("EXPLORE " if o.get("xp") else ("LEARN " if learn else ""), o["side"], 100.0 * float(o.get("confidence") or 0.0), float(o.get("stop_pct") or 0.0)),
                     sl_type="OwlSniper stop (%.2f%%)" % float(o.get("stop_pct") or 0.0), timeframe=INTERVAL)
            if learn:
                p.update(tag=LN.TAG, sniper_id=o.get("id"), sniper_regime=o.get("regime"), sniper_conf=o.get("confidence"))
        pt._save()
        return True
    except Exception:
        return False


CORR = {"checked": 0, "blocked": 0, "last": None}   # PART 49 (memory only): how often the cluster check ran / said no, and the last no ({ts, symbol, gate, text})


def _corr_block(d, pt, o, now):
    """PART 49 / FILE 58: does the NEW paper trade join too many same-direction trades that move together? '' = it may open. Else the plain BLOCKED text.
    Open trades = the Sniper paper trades still open (both lanes). Each counts as 1 R (R units, not USDT, so a tiny LEARN trade and a real-gate trade weigh the same).
    This check only ADDS a reason to say no: if it fails for any reason the trade opens exactly as before. Paper only, nothing is written."""
    try:
        with pt._lock:
            op = [{"symbol": p.get("symbol"), "side": "LONG" if p.get("action") == "BUY" else "SHORT", "risk_r": 1.0}
                  for p in pt._positions.values() if p.get("source") in (SOURCE, LEARN_SOURCE) and not p.get("outdated_reason")]
        r = CR.build(d, op, {"symbol": o["symbol"], "side": o["side"], "risk_r": 1.0}, INTERVAL, now)
        CORR["checked"] += 1
        if r.get("decision") == "BLOCKED":
            CORR["blocked"] += 1
            CORR["last"] = {"ts": int(now), "symbol": o["symbol"], "gate": r.get("gate"), "text": r.get("text")}
            return str(r.get("text") or "BLOCKED: too many trades that move together.")
    except Exception:
        pass
    return ""


def _corr_note(r, symbol, now):
    """The route says gate 'opener' for any refusal; when the cluster check was the reason (same coin, within 5 s), say so (gate 'corr' + its plain text)."""
    last = CORR.get("last")
    if isinstance(r, dict) and r.get("gate") == "opener" and last and last.get("symbol") == symbol and abs(now - last.get("ts", 0)) <= 5:
        return dict(r, gate="corr", text=last.get("text") or r.get("text"))
    return r


def _learned_tp(d, o):
    """R4: only for the paper LEARN lane. When the booking learner (owl_sniper_exitlearn) is LEARNED_EXIT for this market state (it beat the fixed 2R on unseen days) the profit line moves to its R multiple of the stop distance.
    Stop, size and entry are untouched. Any problem or the owner switch (file v2_exitlearn_off) = the order stays as it is."""
    try:
        import owl_sniper_exitlearn as XL
        import owl_sniper_tpsl as TS                                   # R32a: a learned stop + profit COMBO (both lines) comes first
        o2 = TS.apply(d, o, INTERVAL)
        if o2 is not o:
            return o2
        k = XL.live_tp_r(d, o.get("regime"), INTERVAL)
        e, sl = float(o["entry"]), float(o["stop"])
        if not k or e <= 0 or abs(e - sl) <= 0:
            return o
        return dict(o, take_profit=e + abs(e - sl) * k if o["side"] == "LONG" else e - abs(e - sl) * k, exit_rule="tp%gR" % k)
    except Exception:
        return o


def make_opener(d, pt, now=None, learn=False):
    """-> opener(order) for EX.decide() / LN.decide(). True only when ONE paper trade is open and noted. learn=True: the trade gets source \"sniper_learn\"."""
    def opener(o):
        try:
            if learn:
                o.update(XR.plan(d, _learned_tp(d, o)))                   # R32b: arm A / B + the rule's profit line; update in place so the trade record shows the real lines
            tp = o.get("take_profit")
            if not isinstance(tp, (int, float)) or tp <= 0:
                return False                                            # the triple barrier needs its profit line
            if o["symbol"] in pt.get_open_symbols():
                return False                                            # never touch a trade of another bot
            why = "" if o.get("xp") else _corr_block(d, pt, o, time.time() if now is None else now)      # R26a: EXPLORE paper trades may pile up on purpose (that is the data)
            if why:
                print("[sniper paper] %s not opened: %s" % (o["symbol"], why))      # PART 49: too many same-direction trades that move together
                return False
            tid = pt.open_paper_trade(_signal(o), source=LEARN_SOURCE if learn else SOURCE, bot=BOT)
            if tid is None:
                return False
            if not _force_base(pt, tid, o):
                pt.close_position_manual(tid)
                return False
            XR.note(d, o, tid, now)                                        # R32b: remember arm, rule, size, stop distance of this trade
            _map_put(d, o["id"], tid, time.time() if now is None else now)   # a failed note is not fatal: sync() can still find the trade by coin + time
            return True
        except Exception:
            return False
    return opener


def _find_open(pt, o):
    with pt._lock:
        for tid, p in pt._positions.items():
            if p.get("source") == (LEARN_SOURCE if o.get("tag") == LN.TAG else SOURCE) and p.get("symbol") == o.get("symbol") and (p.get("opened_at_ts") or 0) >= o.get("created", 0) - 5:
                return tid
    return None


def _sync_lane(d, pt, ts, now, load, record_close, broken):
    """Close the loop for the open orders of ONE lane (REAL: executor book, LEARN: learn book)."""
    out = {"closed": 0, "time_exit": 0, "released": 0}
    try:
        st = load(d)
    except broken:
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
                record_close(d, cid, 0.0, now)                         # no trade behind the slot: free it (result counted as 0)
                out["released"] += 1
            continue
        if tid in live:
            if age >= hold:
                r = pt.close_position_manual(tid) or {}
                out["time_exit"] += 1 if r.get("ok") else 0
            continue
        row = rows.get(tid)
        if row is not None:
            record_close(d, cid, float(row.get("pnl_usdt") or 0.0), now)
            out["closed"] += 1
        elif age > hold + UNKNOWN_SEC:
            record_close(d, cid, 0.0, now)
            out["released"] += 1
    return dict(out, state="ok")


def sync(d, pt, ts, now=None):
    """Close the loop for every open Sniper order, REAL and LEARN. Never raises. -> small dict (what was done)."""
    now = time.time() if now is None else now
    a = _sync_lane(d, pt, ts, now, EX._load, EX.record_close, EX.StateBroken)
    b = _sync_lane(d, pt, ts, now, LN._load, LN.record_close, LN.StateBroken)
    out = {k: a[k] + b[k] for k in ("closed", "time_exit", "released")}
    out["state"] = "broken" if "broken" in (a["state"], b["state"]) else ("idle" if a["state"] == b["state"] == "idle" else "ok")
    out["learn_state"] = b["state"]
    return out


def _cards(d):
    live = F.read_json(d, F.LIVE_FILE) or {}
    real = [c for c in (live.get("cards") or []) if isinstance(c, dict) and c.get("action") in ("SNIPER_LONG", "SNIPER_SHORT")]
    return real + XP.cards(d), live.get("floor_verified") is True       # R26a: + the fresh EXPLORE cards (they are routed to the LEARN lane only)


def step(d, pt, ts, now=None):
    """One turn of the background loop. Never raises. Every card goes to EX.route(): REAL gate first, then LEARN. `why` counts the gate that stopped the cards (for the Sniper tab)."""
    now = time.time() if now is None else now
    with LOCK:
        try:
            KR.maybe_reset(d, now)                                    # a LEARN kill that the daily loss limit switched on is released on a new UTC day
            res = {"sync": sync(d, pt, ts, now)}
            res["xrules"] = XR.manage(d, pt, now)                        # R32b: arm B exits (stop to entry, trail, time line) for open Sniper paper trades only
            XP.maybe_scan(d, now)                                     # R26a: once per candle step, makes the EXPLORE cards
            MS.maybe_refresh(d, now, force=res["sync"].get("closed", 0) > 0)   # R26b: tag the closed trades, update the blocked combos + the journal
            if os.path.exists(os.path.join(os.path.realpath(d), F.OFF_FILE)):
                return dict(res, auto="off")
            cards, verified = _cards(d)
            ro, lo = make_opener(d, pt, now), make_opener(d, pt, now, learn=True)
            opened, why = [], {}
            for c in cards:                                           # newest first; the REAL cap is 1, the LEARN cap is 5 (each lane keeps its own cap)
                r = EX.route(d, c, verified, now, INTERVAL, ro, lo)
                r = _corr_note(r, c.get("symbol"), now)
                if r["decision"] == "OPEN":
                    opened.append({"symbol": c.get("symbol"), "lane": r["lane"]})
                    REC.note_open(d, c, r.get("order"), now)                  # R29a: keep signal, basis, expected profit and hold of this trade
                    EVH.freeze_async(d, r.get("order"), now)                    # Part 17a: freeze the Risk Box answer (EVA), own thread
                else:
                    k = "%s:%s" % (r["lane"], r.get("gate") or "none")
                    why[k] = why.get(k, 0) + 1
            return dict(res, auto="opened" if opened else "waiting", opened=opened, cards=len(cards), why=why)
        except Exception as e:
            return {"auto": "error", "text": str(e)[:120]}


def enter_symbol(d, pt, ts, symbol, now=None):
    """PAPER ENTER for one coin -> the route's answer {decision, gate, text, order, lane, real_gate, real_text}. Never raises."""
    now = time.time() if now is None else now
    with LOCK:
        try:
            sync(d, pt, ts, now)
            cards, verified = _cards(d)
            card = next((c for c in cards if c.get("symbol") == symbol), None)
            if card is None:
                return {"decision": "BLOCKED", "gate": "signal", "text": "There is no live Sniper signal for %s right now." % symbol, "order": None}
            r = _corr_note(EX.route(d, card, verified, now, INTERVAL, make_opener(d, pt, now), make_opener(d, pt, now, learn=True)), symbol, now)
            if r.get("decision") == "OPEN":
                REC.note_open(d, card, r.get("order"), now)                       # R29a
                EVH.freeze_async(d, r.get("order"), now)                          # Part 17a
            return r
        except Exception as e:
            return {"decision": "BLOCKED", "gate": "error", "text": "The paper entry could not be made (%s)." % str(e)[:80], "order": None}
