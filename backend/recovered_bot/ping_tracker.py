"""Lead-time tracker + bot-signal TAKE/SKIP scoreboard.

Read-only toward live bot stores. Paper ping data only written to ping_lead.json.
"""
import time
from collections import defaultdict

# ---- constants (starting guesses) ----
LEAD_LOOKBACK_MIN = 120
LEAD_CAP = 500
MIN_SIGNALS_RELIABLE = 30


def _utc_day_start(ts=None):
    ts = ts if ts is not None else time.time()
    return int(ts // 86400) * 86400


class PingTracker:
    def __init__(self, engine, radar, store_write, store_read):
        self.engine = engine
        self.radar = radar
        self._write = store_write
        self._read = store_read
        self.lead_events = []  # list of dicts
        self._seen_top = set()  # (day, symbol, "gainer"|"loser")
        self.signal_rows = []  # TAKE/SKIP rows
        self._load()

    def _load(self):
        data = self._read() or {}
        self.lead_events = list(data.get("lead") or [])[-LEAD_CAP:]
        self.signal_rows = list(data.get("signals") or [])[-LEAD_CAP:]
        self._seen_top = set(tuple(x) for x in (data.get("seen_top") or []))

    def _save(self):
        self._write({
            "lead": self.lead_events[-LEAD_CAP:],
            "signals": self.signal_rows[-LEAD_CAP:],
            "seen_top": [list(x) for x in self._seen_top],
            "ts": time.time(),
        })

    def tick_lead(self, now=None):
        """When a coin enters today's top-10 gainers/losers, log lead time vs first ping."""
        now = now if now is not None else time.time()
        day = _utc_day_start(now)
        gainers, losers = self.radar.top_bottom_by_change(10)
        for sym, kind, side in (
            *[(s, "gainer", "BUY") for s in gainers],
            *[(s, "loser", "SELL") for s in losers],
        ):
            key = (day, sym, kind)
            if key in self._seen_top:
                continue
            self._seen_top.add(key)
            cs = self.engine.coins.get(sym)
            first_ts = None
            if cs is not None:
                if side == "BUY" and cs.ping_times_buy:
                    # first ping in lookback
                    cutoff = now - LEAD_LOOKBACK_MIN * 60
                    early = [t for t in cs.ping_times_buy if t >= cutoff]
                    first_ts = min(early) if early else None
                elif side == "SELL" and cs.ping_times_sell:
                    cutoff = now - LEAD_LOOKBACK_MIN * 60
                    early = [t for t in cs.ping_times_sell if t >= cutoff]
                    first_ts = min(early) if early else None
            lead_min = None
            move_pct = None
            if first_ts is not None:
                lead_min = (now - first_ts) / 60.0
                if cs and cs.first_ping_price and cs.price:
                    raw = (cs.price - cs.first_ping_price) / cs.first_ping_price * 100.0
                    if side == "SELL":
                        raw = -raw
                    move_pct = raw
            self.lead_events.append({
                "ts": now,
                "day": day,
                "symbol": sym,
                "kind": kind,
                "side": side,
                "had_ping": first_ts is not None,
                "lead_min": round(lead_min, 2) if lead_min is not None else None,
                "move_pct": round(move_pct, 4) if move_pct is not None else None,
            })
            self.lead_events = self.lead_events[-LEAD_CAP:]
        self._save()

    def note_bot_signal(self, symbol, action, ts, trade_result=None):
        """Record TAKE/SKIP vs live bot signal. action = BUY/SELL.
        trade_result optional dict with pnl when trade later closes.
        """
        now = ts or time.time()
        cs = self.engine.coins.get(symbol)
        row = self.engine.row_for(symbol, now=now, side=action) if cs else None
        verdict = "SKIP"
        reason = "no ping"
        if row:
            color = row.get("color") or "none"
            side = row.get("side")
            if side == action and color == "red":
                verdict = "TAKE"
                reason = "same-side red"
            elif side and side != action:
                reason = "opposite side"
            elif row.get("absorbed"):
                reason = "absorbed"
            elif (row.get("move_since_first_ping_pct") or 0) > 1.5:
                reason = "chased"
            elif (row.get("pings_15m") or 0) < 3:
                reason = "thin volume"
            elif color in ("yellow", "red") and side == action:
                verdict = "TAKE"
                reason = "same-side " + color
            else:
                reason = "no ping"
        entry = {
            "ts": now,
            "symbol": symbol,
            "action": action,
            "verdict": verdict,
            "reason": reason,
            "ping_color": (row or {}).get("color"),
            "pings_15m": (row or {}).get("pings_15m"),
            "trade_pnl": None,
        }
        if trade_result is not None:
            entry["trade_pnl"] = trade_result
        self.signal_rows.append(entry)
        self.signal_rows = self.signal_rows[-LEAD_CAP:]
        self._save()

    def attach_trade_result(self, symbol, action, pnl):
        """Attach real paper result to the latest matching signal row."""
        for row in reversed(self.signal_rows):
            if row.get("symbol") == symbol and row.get("action") == action and row.get("trade_pnl") is None:
                row["trade_pnl"] = pnl
                self._save()
                return True
        return False

    def lead_snapshot(self):
        today = _utc_day_start()
        today_ev = [e for e in self.lead_events if e.get("day") == today]
        with_ping = [e for e in today_ev if e.get("had_ping")]
        leads = [e["lead_min"] for e in with_ping if e.get("lead_min") is not None]
        avg = sum(leads) / len(leads) if leads else None
        pct = (100.0 * len(with_ping) / len(today_ev)) if today_ev else 0.0
        sentence = (
            f"Today {len(today_ev)} top-10 entries; {pct:.0f}% had a same-side ping"
            + (f"; average lead {avg:.1f} min." if avg is not None else ".")
        )
        return {
            "today_count": len(today_ev),
            "with_ping_pct": round(pct, 1),
            "avg_lead_min": round(avg, 2) if avg is not None else None,
            "events": today_ev[-40:],
            "sentence": sentence,
            "small_sample": len(today_ev) < 10,
        }

    def score_snapshot(self):
        rows = self.signal_rows
        n = len(rows)
        take = [r for r in rows if r.get("verdict") == "TAKE"]
        skip = [r for r in rows if r.get("verdict") == "SKIP"]
        take_pnl = [r["trade_pnl"] for r in take if isinstance(r.get("trade_pnl"), (int, float))]
        skip_pnl = [r["trade_pnl"] for r in skip if isinstance(r.get("trade_pnl"), (int, float))]
        loss_avoided = sum(-p for p in skip_pnl if p < 0)
        profit_missed = sum(p for p in skip_pnl if p > 0)
        net = loss_avoided - profit_missed
        small = n < MIN_SIGNALS_RELIABLE
        if small:
            verdict = "Small sample, not reliable."
        elif net > 0:
            verdict = "Skipping based on pings would have avoided more loss than profit missed."
        elif net < 0:
            verdict = "Skipping based on pings would have missed more profit than loss avoided."
        else:
            verdict = "Net effect near zero so far."
        return {
            "signals_total": n,
            "take_count": len(take),
            "skip_count": len(skip),
            "take_pnl_sum": round(sum(take_pnl), 2) if take_pnl else 0.0,
            "skip_pnl_sum": round(sum(skip_pnl), 2) if skip_pnl else 0.0,
            "loss_avoided": round(loss_avoided, 2),
            "profit_missed": round(profit_missed, 2),
            "net_effect": round(net, 2),
            "sentence": verdict,
            "small_sample": small,
            "rows": rows[-40:],
        }
