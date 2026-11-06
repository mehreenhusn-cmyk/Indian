"""chop_ledger.py - Part C3 (README_CHOP): READ-ONLY views of chop_b3.db for the b3 tab (C4): today / all-time numbers, the SKIP LEDGER (rally missed, loss avoided), the rule report, the Missed Rally alarm,
and the self-learning SUGGESTION. The only function that writes anything is apply_weights(), and it is called only by the owner's OK button (POST /api/v2/chop_apply).
All money numbers for SKIPs are "if this skipped signal had been taken at FULL size (chop_bot.FULL_USDT), net of cost" - a what-if, never a real trade. TAKE numbers are the real paper results.
RIGHT / WRONG: a TAKE is right when it won; a SKIP is right when the trade would have lost (LOSS_AVOIDED). A SKIP that would have won is a RALLY_MISSED.
Needs: chop_bot.py (database layout), chop_score.py (suggest_weights, load_weights, save_weights), chop_filter.py (constants)."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chop_bot as B
import chop_filter as F
import chop_score as S

VERSION = "chop_ledger 1 (Part C3)"
RALLY_ALARM_PCT = 1.0          # a skipped signal that would have made 1% or more (net) raises the Missed Rally alarm
UP, DOWN = ("WIN", "RALLY_MISSED"), ("LOSS", "LOSS_AVOIDED")


def _rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def _usdt(net_pct):
    return round(net_pct / 100.0 * B.FULL_USDT, 3)


def totals(db, since_ts=0):
    """Numbers from since_ts (UTC seconds) on: real closed paper trades + the Skip Ledger. Skips still waiting for their verdict are counted apart."""
    tr = db.execute("SELECT COUNT(*) n, COALESCE(SUM(net_usdt>0),0) w, COALESCE(SUM(net_usdt),0) usdt FROM trades WHERE status='CLOSED' AND exit_ts>=?", (since_ts,)).fetchone()
    dc = db.execute("SELECT COALESCE(SUM(action='TAKE'),0) t, COALESCE(SUM(action='SKIP' AND v_label IS NOT 'NA'),0) s FROM decisions WHERE candle_ts>=?", (since_ts,)).fetchone()
    sk = {r["v_label"]: r for r in db.execute("SELECT v_label, COUNT(*) n, COALESCE(SUM(v_net),0) net FROM decisions WHERE action='SKIP' AND v_final=1 AND v_label IN ('RALLY_MISSED','LOSS_AVOIDED') AND candle_ts>=? GROUP BY v_label", (since_ts,)).fetchall()}
    wait = db.execute("SELECT COUNT(*) FROM decisions WHERE action='SKIP' AND v_final=0 AND candle_ts>=?", (since_ts,)).fetchone()[0]
    rm, la = sk.get("RALLY_MISSED"), sk.get("LOSS_AVOIDED")
    return {"closed": tr["n"], "wins": tr["w"], "profit_usdt": round(tr["usdt"], 3), "taken": dc["t"], "skipped": dc["s"],
            "rally_missed_n": rm["n"] if rm else 0, "rally_missed_usdt": _usdt(rm["net"]) if rm else 0.0,
            "loss_avoided_n": la["n"] if la else 0, "loss_avoided_usdt": _usdt(-la["net"]) if la else 0.0, "skips_waiting": wait}


def overview(db, now=None):
    now = int(now if now is not None else time.time())
    d0 = now // 86400 * 86400
    return {"interval": B.INTERVAL, "day": time.strftime("%Y-%m-%d", time.gmtime(now)), "on": B.is_on(db),
            "today": totals(db, d0), "all": totals(db, 0), "open": db.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0],
            "note": "SKIP money = what the skipped trade would have made at full size (10 USDT), after cost. Not a real trade."}


def open_trades(db, prices=None):
    out = _rows(db, "SELECT * FROM trades WHERE status='OPEN' ORDER BY id DESC")
    for t in out:
        px = (prices or {}).get(t["symbol"])
        if px:
            w = 1 if t["side"] == "BUY" else -1
            t["last_px"] = px
            t["upnl_pct"] = round((px - t["entry_px"]) * w / t["entry_px"] * 100.0 - F.COST_PCT, 3)
            t["upnl_usdt"] = round(t["upnl_pct"] / 100.0 * t["invest"], 3)
    return out


def closed_trades(db, limit=50):
    return _rows(db, "SELECT * FROM trades WHERE status='CLOSED' ORDER BY id DESC LIMIT ?", (int(limit),))


def decisions(db, limit=50):
    out = _rows(db, "SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (int(limit),))
    for d in out:
        try:
            d["parts"] = json.loads(d["parts"]) if d["parts"] else None
        except ValueError:
            d["parts"] = None
        d["verdict"] = ("right" if d["v_label"] in ("WIN", "LOSS_AVOIDED") else "wrong" if d["v_label"] in ("LOSS", "RALLY_MISSED") else None) if d["v_final"] else None
    return out


def missed_rallies(db, limit=10):
    """The Missed Rally alarm: skipped signals that would have made RALLY_ALARM_PCT or more. Each row says which rule blocked it."""
    return _rows(db, "SELECT id, symbol, side, candle_ts, rule, why, score, v_net, v_exit FROM decisions WHERE action='SKIP' AND v_final=1 AND v_label='RALLY_MISSED' AND v_net>=? ORDER BY id DESC LIMIT ?",
                 (RALLY_ALARM_PCT, int(limit)))


def rule_report(db):
    """Per rule: how many judged decisions, right / wrong, and the money the rule made (TAKE) or saved (SKIP, negative = it cost a rally), per full-size trade."""
    out = []
    for r in db.execute("SELECT action, rule, COUNT(*) n, COALESCE(SUM(v_label IN ('WIN','LOSS_AVOIDED')),0) ok_n, COALESCE(SUM(v_net),0) net FROM decisions "
                        "WHERE v_final=1 AND v_label IN ('WIN','LOSS','RALLY_MISSED','LOSS_AVOIDED') GROUP BY action, rule ORDER BY n DESC").fetchall():
        money = _usdt(r["net"]) if r["action"] == "TAKE" else _usdt(-r["net"])
        out.append({"action": r["action"], "rule": r["rule"], "judged": r["n"], "right": r["ok_n"], "wrong": r["n"] - r["ok_n"],
                    "right_pct": round(100.0 * r["ok_n"] / r["n"], 1), "usdt": money,
                    "says": ("made" if money >= 0 else "lost") if r["action"] == "TAKE" else ("saved" if money >= 0 else "cost a rally of")})
    return out


def weight_rows(db):
    rows = []
    for r in db.execute("SELECT parts, v_net FROM decisions WHERE v_final=1 AND v_net IS NOT NULL AND parts IS NOT NULL AND v_label IN ('WIN','LOSS','RALLY_MISSED','LOSS_AVOIDED') ORDER BY id").fetchall():
        try:
            rows.append({"parts": json.loads(r["parts"]), "net_pct": float(r["v_net"])})
        except (ValueError, TypeError):
            continue
    return rows


def suggestions(db, data_dir):
    """The learning PROPOSAL (nothing is saved): chop_score.suggest_weights on every judged decision, with the weights now in use."""
    cur = S.load_weights(B.weights_path(data_dir))
    s = S.suggest_weights(weight_rows(db), cur)
    s["current_weights"] = cur
    return s


def apply_weights(db, data_dir):
    """The owner's OK: save the proposed weights to chop_b3_weights.json. Refuses when there is not enough data or nothing to change."""
    s = suggestions(db, data_dir)
    if not s["enough"] or not s["changes"]:
        return {"saved": False, "note": s.get("note") or "no change is supported by both the train and the test part yet", "rows": s["rows"]}
    S.save_weights(B.weights_path(data_dir), s["new_weights"])
    return {"saved": True, "changes": s["changes"], "weights": s["new_weights"], "rows": s["rows"]}
