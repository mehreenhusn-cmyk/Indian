"""india_paper.py - paper-trading engine for Nifty/BankNifty/FinNifty OPTION BUYING.

Strategy runs on the SPOT index and calls on_signal(underlying, action, sl_spot,
tp_spot, tps=[tp1..tp4]). LONG buys a CE, SHORT buys a PE. SL/TP are SPOT levels.

Exit rules (mirror the crypto bot, candle-close based):
  * SL fires only when a candle CLOSES beyond it (wick alone never stops you out).
    A gap-open beyond the SL exits at the open.
  * TP ladder TP1..TP4, final target = `target_level` (default 4).
  * TP1 touched -> SL moves to entry (`breakeven`); `trail_mode` step1/step2 trail it
    further. SL moves apply from the NEXT candle.
  * INTRADAY squares off at `squareoff`; CARRY keeps overnight but is force-closed
    on the contract's expiry day. Optional emergency premium stop (`emergency_pct`).
Contract choice: ticked pin > day mode (ITM/ATM/OTM chips, resets every day) > ITM
default; with `fit_balance` it steps to cheaper strikes until the cost fits cash.
Fully separate from the crypto paper_trader.
"""
import json
import logging
from datetime import date, datetime, time

try:
    from . import india_options as opt, india_calendar as cal
except ImportError:
    import india_options as opt, india_calendar as cal

log = logging.getLogger("india_paper")

DEFAULTS = {
    "capital": 200000.0,
    "lots": 1,
    "itm_depth": 1,           # depth of the default ITM pick (1 = nearest ITM)
    "min_days_to_expiry": 1,  # skip expiry-day contracts (CARRY forces >= 2)
    "entry_start": time(9, 20),
    "entry_end": time(15, 0),
    "squareoff": time(15, 15),
    "slip_pct": 0.002,        # entry/exit slippage on premium
    "min_slip": 0.05,
    "product": "INTRADAY",    # INTRADAY | CARRY
    "target_level": 4,        # final exit at TP<n>
    "breakeven": True,        # TP1 -> SL to entry
    "trail_mode": "off",      # off | step1 | step2 (same meaning as crypto)
    "fit_balance": True,      # step to cheaper strikes until cost <= budget
    "budget_pct": 0.95,       # share of cash one trade may use
    "min_premium": 20.0,      # never buy near-worthless options
    "pin_fallback": True,     # ticked strike unaffordable -> affordable pick (else skip)
    "emergency_pct": 0.0,     # exit if premium falls this fraction below entry (0 = off)
    "max_loss_pct": 0.0,      # skip trade if est. loss at SL > this % of cash (0 = off)
    # Charges - VERIFY against your broker/current exchange circulars.
    "brokerage_flat": 20.0,
    "stt_sell_pct": 0.001,
    "txn_pct": 0.0003503,
    "gst_pct": 0.18,
    "stamp_buy_pct": 0.00003,
}
TRAIL_MODES = ("off", "step1", "step2")
PRODUCTS = ("INTRADAY", "CARRY")


def _tick(x):
    return max(round(round(x / 0.05) * 0.05, 2), 0.05)


class IndiaPaperEngine:
    def __init__(self, provider, settings=None, state_path=None, restore=False):
        self.p = provider
        self.s = {**DEFAULTS, **(settings or {})}
        self.cash = float(self.s["capital"])
        self.open, self.closed, self._n = {}, [], 0
        self.state_path = state_path
        self.pins = {}        # (underlying, "CE"/"PE") -> spec dict
        self.day_mode = None  # {"mode": "OTM", "depth": 2} or None
        self._day = provider.now().date()
        if restore:
            self._load()

    # ------------------------------------------------------- day / pins ---
    def _roll_day(self, now):
        """Ticked strikes and the ITM/ATM/OTM chip reset to default every new day."""
        if self._day != now.date():
            self._day = now.date()
            self.pins.clear()
            self.day_mode = None

    def set_pin(self, underlying, side, spec):
        self._roll_day(self.p.now())
        u, side = underlying.upper(), side.upper()
        if u not in opt.UNDERLYINGS or side not in ("CE", "PE"):
            raise ValueError("bad underlying/side")
        t = spec.get("type")
        if t == "strike":
            spec = {"type": "strike", "strike": int(spec["strike"])}
        elif t == "premium":
            if float(spec["target"]) <= 0:
                raise ValueError("target premium must be > 0")
            spec = {"type": "premium", "target": float(spec["target"])}
        elif t == "mode":
            m = str(spec["mode"]).upper()
            if m not in opt.MODES:
                raise ValueError("bad mode")
            spec = {"type": "mode", "mode": m, "depth": max(1, int(spec.get("depth", 1)))}
        else:
            raise ValueError("pin type must be strike|premium|mode")
        self.pins[(u, side)] = spec

    def clear_pins(self, underlying=None, side=None):
        for k in list(self.pins):
            if (underlying is None or k[0] == underlying.upper()) and \
               (side is None or k[1] == side.upper()):
                del self.pins[k]

    def set_day_mode(self, mode, depth=1):
        self._roll_day(self.p.now())
        if mode is None:
            self.day_mode = None
            return
        m = str(mode).upper()
        if m not in opt.MODES:
            raise ValueError("bad mode")
        self.day_mode = {"mode": m, "depth": max(1, int(depth))}

    # ---------------------------------------------------------- helpers ---
    def fees(self, price, qty, side):
        s, turn = self.s, price * qty
        brk = min(s["brokerage_flat"], 0.0003 * turn) if turn else 0.0
        txn = s["txn_pct"] * turn
        stt = s["stt_sell_pct"] * turn if side == "SELL" else 0.0
        stamp = s["stamp_buy_pct"] * turn if side == "BUY" else 0.0
        return round(brk + txn + stt + stamp + s["gst_pct"] * (brk + txn), 2)

    def _slip(self, ltp):
        return max(ltp * self.s["slip_pct"], self.s["min_slip"])

    def entry_cost(self, c, ltp):
        """Cash needed to buy `lots` lots of contract c at premium ltp (incl. slippage+fees)."""
        qty = c["lot"] * self.s["lots"]
        entry = _tick(ltp + self._slip(ltp))
        return entry * qty + self.fees(entry, qty, "BUY")

    def _entry_ok(self, now):
        if not cal.is_trading_day(now.date()):
            return False, "market holiday" if now.weekday() < 5 else "weekend"
        if not (self.s["entry_start"] <= now.time() < self.s["entry_end"]):
            return False, "outside entry window"
        return True, ""

    # ---------------------------------------------------- contract pick ---
    def select(self, u, otype, spot, now):
        """-> (contract, ltp, tag, reason). tag: PIN | DAY | AUTO | FALLBACK."""
        s = self.s
        step = opt.UNDERLYINGS[u]["step"]
        min_days = max(int(s["min_days_to_expiry"]), 2 if s["product"] == "CARRY" else 0)
        _, pool = opt.expiry_pool(self.p.get_contracts(u), u, otype, now.date(), min_days)
        if not pool:
            return None, None, "", "no matching contract"
        ltp_fn = lambda c: self.p.get_option_ltp(c)
        budget = self.cash * float(s["budget_pct"])

        def base_pick(mode, depth, tag):
            want = opt.strike_for(spot, otype, step, mode, depth)
            if s["fit_balance"]:
                c, ltp, why = opt.pick_affordable(pool, otype, want, ltp_fn, budget,
                                                  self.entry_cost, s["min_premium"])
                return c, ltp, tag, why
            c = opt.by_strike(pool, want)
            ltp = ltp_fn(c) if c else None
            return c, ltp, tag, ("" if c else "strike not listed")

        dm = self.day_mode or {"mode": "ITM", "depth": int(s["itm_depth"])}
        base_tag = "DAY" if self.day_mode else "AUTO"
        pin = self.pins.get((u, otype))
        if not pin:
            return base_pick(dm["mode"], dm["depth"], base_tag)
        if pin["type"] == "mode":
            return base_pick(pin["mode"], pin["depth"], "PIN")
        if pin["type"] == "strike":
            c = opt.by_strike(pool, pin["strike"])
            ltp = ltp_fn(c) if c else None
        else:
            c, ltp = opt.by_premium(pool, ltp_fn, pin["target"])
        if not c or not ltp or ltp <= 0:
            if s["pin_fallback"]:
                return base_pick(dm["mode"], dm["depth"], "FALLBACK")
            return None, None, "", "pinned contract not available"
        cost = self.entry_cost(c, ltp)
        if cost > budget:
            if s["pin_fallback"]:
                return base_pick(dm["mode"], dm["depth"], "FALLBACK")
            return None, None, "", f"pinned needs Rs{cost:,.0f}, have Rs{budget:,.0f}"
        return c, ltp, "PIN", ""

    def _est_loss(self, c, entry, qty, sl_spot, spot):
        if getattr(self.p, "supports_reprice", False):
            x = self.p.get_option_ltp(c, spot=sl_spot) or 0.0
            return max(entry - x, 0.0) * qty
        return abs(spot - sl_spot) * 0.5 * qty      # rough delta-0.5 estimate

    # ----------------------------------------------------------- entries ---
    def on_signal(self, underlying, action, sl_spot, tp_spot, tps=None):
        u = underlying.upper()
        a = "LONG" if opt.option_type_for(action) == "CE" else "SHORT"
        otype = "CE" if a == "LONG" else "PE"
        now = self.p.now()
        self._roll_day(now)
        ok, why = self._entry_ok(now)
        if not ok:
            return {"ok": False, "reason": why}
        for pos in list(self.open.values()):
            if pos["underlying"] != u:
                continue
            if pos["action"] == a:
                return {"ok": False, "reason": "already open"}
            self._close(pos, "OPPOSITE", self.p.get_spot(u))
        spot = self.p.get_spot(u)
        good = (sl_spot < spot < tp_spot) if a == "LONG" else (tp_spot < spot < sl_spot)
        if not good:
            return {"ok": False, "reason": "SL/TP not on correct side of spot"}
        c, ltp, tag, why = self.select(u, otype, spot, now)
        if not c:
            return {"ok": False, "reason": why or "no matching contract"}
        qty = c["lot"] * self.s["lots"]
        entry = _tick(ltp + self._slip(ltp))
        fee = self.fees(entry, qty, "BUY")
        cost = entry * qty + fee
        if cost > self.cash:
            return {"ok": False, "reason": f"insufficient cash ({cost:.0f} > {self.cash:.0f})"}
        ml = float(self.s["max_loss_pct"])
        if ml > 0:
            loss = self._est_loss(c, entry, qty, sl_spot, spot)
            if loss > self.cash * ml / 100.0:
                return {"ok": False, "reason": f"risk too high (est. loss Rs{loss:,.0f})"}
        tps = [float(t) for t in (tps or [tp_spot]) if t]
        self.cash -= cost
        self._n += 1
        pos = dict(id=self._n, underlying=u, action=a, contract=c, qty=qty,
                   entry_premium=entry, entry_spot=spot, sl_spot=float(sl_spot),
                   sl_initial=float(sl_spot), tp_spot=float(tp_spot), tps=tps,
                   target=max(1, min(int(self.s["target_level"]), len(tps))),
                   tp_hit=0, product=self.s["product"], tag=tag,
                   buy_fee=fee, opened_at=now)
        self.open[pos["id"]] = pos
        self._save()
        return {"ok": True, "trade": pos}

    # ------------------------------------------------------------- exits ---
    def _close(self, pos, reason, exit_spot):
        ltp = self.p.get_option_ltp(pos["contract"], spot=exit_spot) or 0.0
        exit_p = _tick(ltp - self._slip(ltp))
        fee = self.fees(exit_p, pos["qty"], "SELL")
        proceeds = exit_p * pos["qty"] - fee
        self.cash += proceeds
        cost = pos["entry_premium"] * pos["qty"] + pos["buy_fee"]
        fees = round(pos["buy_fee"] + fee, 2)
        pnl = round(proceeds - cost, 2)
        rec = {**pos, "exit_premium": exit_p, "exit_spot": exit_spot,
               "reason": reason, "sell_fee": fee, "closed_at": self.p.now(),
               "pnl": pnl, "fees": fees, "gross_pnl": round(pnl + fees, 2)}
        self.open.pop(pos["id"], None)
        self.closed.append(rec)
        self._save()
        return rec

    def _shift_sl(self, pos, level):
        """SL shift after a TP is touched; takes effect from the next candle."""
        mode, entry, tps = self.s["trail_mode"], pos["entry_spot"], pos["tps"]
        if mode == "step1":
            new = entry if level == 1 else tps[level - 2]
        elif mode == "step2":
            new = None if level < 2 else (entry if level == 2 else tps[level - 3])
        else:
            new = entry if (self.s["breakeven"] and level >= 1) else None
        if new is None:
            return
        pos["sl_spot"] = max(pos["sl_spot"], new) if pos["action"] == "LONG" \
            else min(pos["sl_spot"], new)

    def on_tick(self):
        """Call once per closed candle. Returns trades closed this call."""
        now, done = self.p.now(), []
        self._roll_day(now)
        for pos in list(self.open.values()):
            if pos["opened_at"] == now:
                continue
            u, long_ = pos["underlying"], pos["action"] == "LONG"
            spot = self.p.get_spot(u)
            cd = self.p.get_last_candle(u) or {"o": spot, "h": spot, "l": spot, "c": spot}
            sl, tps = pos["sl_spot"], pos["tps"]
            ep = float(self.s["emergency_pct"])
            res = None
            if ep > 0:
                ltp = self.p.get_option_ltp(pos["contract"]) or 0.0
                if 0 < ltp <= pos["entry_premium"] * (1 - ep):
                    res = ("ESL", spot)
            lbl = "TSL" if pos["tp_hit"] > 0 else "SL"
            if res is None and ((long_ and cd["o"] <= sl) or (not long_ and cd["o"] >= sl)):
                res = (lbl + "(GAP)", cd["o"])
            if res is None and ((long_ and cd["c"] <= sl) or (not long_ and cd["c"] >= sl)):
                res = (lbl, cd["c"])            # candle-close SL
            if res is None:
                level = 0
                for i in range(len(tps), 0, -1):
                    if (long_ and cd["h"] >= tps[i - 1]) or (not long_ and cd["l"] <= tps[i - 1]):
                        level = i
                        break
                if level >= pos["target"]:
                    res = (f"TP{pos['target']}", tps[pos["target"] - 1])
                elif level > pos["tp_hit"]:
                    pos["tp_hit"] = level
                    self._shift_sl(pos, level)
            if res is None and now.time() >= self.s["squareoff"]:
                if pos["product"] == "INTRADAY":
                    res = ("SQUAREOFF", spot)
                elif pos["contract"]["expiry"] <= now.date():
                    res = ("EXPIRY", spot)
            if res:
                done.append(self._close(pos, res[0], res[1]))
        if self.open and not done:
            self._save()
        return done

    def close_one(self, pos_id, reason="MANUAL"):
        pos = self.open.get(int(pos_id))
        if not pos:
            return None
        return self._close(pos, reason, self.p.get_spot(pos["underlying"]))

    def close_all(self, reason="MANUAL"):
        return [self._close(p, reason, self.p.get_spot(p["underlying"]))
                for p in list(self.open.values())]

    # ------------------------------------------------------------- stats ---
    def mark(self, pos):
        """Live mark-to-market of an open position (estimated exit after slippage + fees)."""
        ltp = self.p.get_option_ltp(pos["contract"]) or 0.0
        xp = _tick(ltp - self._slip(ltp)) if ltp > 0 else 0.0
        cost = pos["entry_premium"] * pos["qty"] + pos["buy_fee"]
        est = xp * pos["qty"] - self.fees(xp, pos["qty"], "SELL") - cost
        return {"premium": round(ltp, 2), "unrealized": round(est, 2),
                "unrealized_pct": round(100 * est / cost, 2) if cost else 0.0,
                "spot": round(self.p.get_spot(pos["underlying"]), 2)}

    def summary(self):
        """Terminal header numbers: Day / Realised / Unrealised / Total / charges."""
        today = self.p.now().date()
        tt = [t for t in self.closed if t["closed_at"].date() == today]
        realized_today = round(sum(t["pnl"] for t in tt), 2)
        unreal = round(sum(self.mark(p)["unrealized"] for p in self.open.values()), 2)
        total_realized = round(sum(t["pnl"] for t in self.closed), 2)
        capital = float(self.s["capital"])
        return {"day_pnl": round(realized_today + unreal, 2),
                "realized_today": realized_today, "unrealized": unreal,
                "total_pnl": round(total_realized + unreal, 2),
                "total_realized": total_realized,
                "fees_today": round(sum(t["fees"] for t in tt), 2),
                "fees_total": round(sum(t["fees"] for t in self.closed), 2),
                "trades_today": len(tt), "wins_today": sum(1 for t in tt if t["pnl"] > 0),
                "cash": round(self.cash, 2), "capital": capital,
                "equity": round(capital + total_realized + unreal, 2)}

    def stats(self):
        n = len(self.closed)
        wins = sum(1 for t in self.closed if t["pnl"] > 0)
        return {"trades": n, "wins": wins,
                "win_pct": round(100 * wins / n, 1) if n else 0.0,
                "net_pnl": round(sum(t["pnl"] for t in self.closed), 2),
                "fees": round(sum(t["fees"] for t in self.closed), 2),
                "cash": round(self.cash, 2), "open": len(self.open)}

    def _load(self):
        """Bring back cash, open positions and closed trades after a backend restart (live source only)."""
        if not self.state_path:
            return
        try:
            with open(self.state_path) as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return
        try:
            def dt(x):
                return x if x is None or isinstance(x, datetime) else datetime.fromisoformat(str(x))

            def fix(r):
                r = dict(r)
                for k in ("opened_at", "closed_at"):
                    if k in r:
                        r[k] = dt(r[k])
                c = dict(r.get("contract") or {})
                if isinstance(c.get("expiry"), str):
                    c["expiry"] = date.fromisoformat(c["expiry"][:10])
                r["contract"] = c
                return r
            opened = [fix(r) for r in raw.get("open", [])]
            closed = [fix(r) for r in raw.get("closed", [])]
        except Exception:
            log.exception("india_paper restore failed - starting fresh")
            return
        self.cash = float(raw.get("cash", self.cash))
        self.open = {int(r["id"]): r for r in opened}
        self.closed = closed
        self._n = max([r["id"] for r in opened + closed] or [0])

    def _save(self):
        if not self.state_path:
            return
        try:
            with open(self.state_path, "w") as f:
                json.dump({"cash": self.cash, "open": list(self.open.values()),
                           "closed": self.closed}, f, default=str, indent=1)
        except Exception:
            log.exception("india_paper save failed")
