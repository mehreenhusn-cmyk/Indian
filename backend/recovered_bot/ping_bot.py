"""Paper Ping Bot: variants A/B/C x LONG/SHORT on candidate coins.

Never touches live bot stores. Paper only. Margin 100 USDT x 10.
"""
import time
from collections import defaultdict

# ---- constants (starting guesses) ----
PING_MAX_OPEN = 10
MARGIN_USDT = 100.0
LEVERAGE = 10
ENTRY_PINGS_5M = 3
ENTRY_PINGS_15M = 5
MAX_CHASE_PCT = 1.5
SL_LOOKBACK = 10
SL_MIN_PCT = 0.3
SL_MAX_PCT = 1.2
TP_FRACTIONS = (0.25, 0.25, 0.25, 0.25)  # TP1..TP4
TIME_STOP_MIN = 30
TRADES_CAP = 1000
BOT_SAVE_SEC = 60.0   # unchanged state is written at most this often
EMA_READY_FAST = 30   # closed 1m candles needed before EMA30 is trusted
EMA_READY_SLOW = 50   # closed 1m candles needed before EMA50 is trusted
VARIANTS = ("A", "B", "C")  # A=EMA30, B=EMA50, C=ping only


def _utc_day_key(ts=None):
    ts = ts if ts is not None else time.time()
    return int(ts // 86400)  # 00:00 UTC day index


class PaperTrade:
    __slots__ = (
        "id", "symbol", "variant", "side", "entry", "sl", "tp", "size_usdt",
        "opened_ts", "first_ping_ts", "pings_5m", "pings_15m",
        "tp_hits", "remaining", "exit_ts", "exit_price", "exit_reason",
        "pnl_pct", "pnl_usdt", "experimental",
    )

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.tp_hits = 0
        self.remaining = 1.0
        self.exit_ts = None
        self.exit_price = None
        self.exit_reason = None
        self.pnl_pct = 0.0
        self.pnl_usdt = 0.0

    def to_dict(self):
        return {s: getattr(self, s) for s in self.__slots__}


class PingBot:
    def __init__(self, engine, store_write_trades, store_read_trades):
        self.engine = engine
        self._write = store_write_trades
        self._read = store_read_trades
        self.open = {}  # (symbol, variant, side) -> PaperTrade
        self.closed = []  # newest first, capped
        self.skips = []  # recent skip log
        self._seq = 0
        self._load()

    def _load(self):
        data = self._read() or {}
        self.closed = list(data.get("closed") or [])[-TRADES_CAP:]
        self._seq = int(data.get("seq") or 0)

    def _save(self):
        self._write({
            "seq": self._seq,
            "closed": self.closed[-TRADES_CAP:],
            "open": [t.to_dict() for t in self.open.values()],
            "ts": time.time(),
        })

    def _maybe_save(self, now):
        sig = (len(self.open), len(self.closed), self._seq,
               tuple(str(t.tp_hits) for t in self.open.values()))
        if sig != getattr(self, "_last_sig", None) or now - getattr(self, "_last_save", 0.0) >= BOT_SAVE_SEC:
            self._last_sig = sig
            self._last_save = now
            self._save()

    def tick(self, now=None):
        """Evaluate entries on candidates + manage open trades."""
        now = now if now is not None else time.time()
        for sym, cs in list(self.engine.coins.items()):
            if cs.last_ping_ts is None:
                continue
            for variant in VARIANTS:
                for side in ("LONG", "SHORT"):
                    self._try_entry(sym, cs, variant, side, now)
        self._manage_open(now)
        self._maybe_save(now)

    def _try_entry(self, sym, cs, variant, side, now):
        key = (sym, variant, side)
        if key in self.open:
            return
        open_count = sum(1 for k in self.open if k[1] == variant)
        if open_count >= PING_MAX_OPEN:
            return

        ping_side = "BUY" if side == "LONG" else "SELL"
        times = cs.ping_times_buy if ping_side == "BUY" else cs.ping_times_sell
        p5 = sum(1 for t in times if t >= now - 300)
        p15 = sum(1 for t in times if t >= now - 900)
        if p5 < ENTRY_PINGS_5M or p15 < ENTRY_PINGS_15M:
            return
        # 5 min net same sign
        if ping_side == "BUY" and cs.recent_net <= 0:
            return
        if ping_side == "SELL" and cs.recent_net >= 0:
            return

        # EMA filter
        close = cs.price
        if variant == "A":
            if cs.ema30 is None or cs.n_closes < EMA_READY_FAST:
                return  # EMA30 not warmed up yet
            if side == "LONG" and not (close > cs.ema30):
                return
            if side == "SHORT" and not (close < cs.ema30):
                return
        elif variant == "B":
            if cs.ema50 is None or cs.n_closes < EMA_READY_SLOW:
                return  # EMA50 not warmed up yet
            if side == "LONG" and not (close > cs.ema50):
                return
            if side == "SHORT" and not (close < cs.ema50):
                return

        move = 0.0
        if cs.first_ping_price and cs.first_ping_price > 0 and close > 0:
            raw = (close - cs.first_ping_price) / cs.first_ping_price * 100.0
            if ping_side == "SELL":
                raw = -raw
            move = raw
        if move > MAX_CHASE_PCT:
            self._skip(sym, variant, side, "chased", now)
            return
        if getattr(cs, "last_ping_side", None) == ping_side:
            # absorbed check via engine row
            row = self.engine.row_for(sym, now=now, side=ping_side)
            if row and row.get("absorbed"):
                self._skip(sym, variant, side, "absorbed", now)
                return

        # SL from last 10 highs/lows
        entry = close  # last price at trigger (simplest; see notes)
        if side == "LONG":
            lows = list(cs.low_hist)[-SL_LOOKBACK:] or [entry]
            raw_sl = min(lows)
            dist_pct = max(SL_MIN_PCT, min(SL_MAX_PCT, (entry - raw_sl) / entry * 100.0 if entry else SL_MIN_PCT))
            sl = entry * (1.0 - dist_pct / 100.0)
        else:
            highs = list(cs.high_hist)[-SL_LOOKBACK:] or [entry]
            raw_sl = max(highs)
            dist_pct = max(SL_MIN_PCT, min(SL_MAX_PCT, (raw_sl - entry) / entry * 100.0 if entry else SL_MIN_PCT))
            sl = entry * (1.0 + dist_pct / 100.0)
        R = abs(entry - sl)
        if R <= 0:
            return
        if side == "LONG":
            tps = [entry + R * i for i in range(1, 5)]
        else:
            tps = [entry - R * i for i in range(1, 5)]

        self._seq += 1
        trade = PaperTrade(
            id=self._seq,
            symbol=sym,
            variant=variant,
            side=side,
            entry=entry,
            sl=sl,
            tp=tps,
            size_usdt=MARGIN_USDT * LEVERAGE,
            opened_ts=now,
            first_ping_ts=cs.first_ping_ts,
            pings_5m=p5,
            pings_15m=p15,
            experimental=(side == "SHORT"),
        )
        self.open[key] = trade

    def _skip(self, sym, variant, side, reason, now):
        self.skips.append({
            "ts": now, "symbol": sym, "variant": variant, "side": side, "reason": reason,
        })
        self.skips = self.skips[-200:]

    def _manage_open(self, now):
        done = []
        for key, tr in list(self.open.items()):
            cs = self.engine.coins.get(tr.symbol)
            if cs is None or cs.price <= 0:
                continue
            px = cs.price
            # SL
            hit_sl = (tr.side == "LONG" and px <= tr.sl) or (tr.side == "SHORT" and px >= tr.sl)
            if hit_sl:
                self._close(tr, px, "sl", now)
                done.append(key)
                continue
            # TPs
            while tr.tp_hits < 4:
                tp = tr.tp[tr.tp_hits]
                hit = (tr.side == "LONG" and px >= tp) or (tr.side == "SHORT" and px <= tp)
                if not hit:
                    break
                tr.tp_hits += 1
                tr.remaining -= TP_FRACTIONS[tr.tp_hits - 1]
                # SL ladder
                if tr.tp_hits == 1:
                    tr.sl = tr.entry
                elif tr.tp_hits == 2:
                    tr.sl = tr.tp[0]
                elif tr.tp_hits == 3:
                    tr.sl = tr.tp[1]
                if tr.tp_hits == 4:
                    self._close(tr, px, "tp4", now)
                    done.append(key)
                    break
            if key in done:
                continue
            # signal exit: 5m net flips opposite beyond a crude T, or 2 candles no ping past EMA30
            if cs.ema30 is not None:
                if tr.side == "LONG" and cs.recent_net < 0 and px < cs.ema30:
                    self._close(tr, px, "signal", now)
                    done.append(key)
                    continue
                if tr.side == "SHORT" and cs.recent_net > 0 and px > cs.ema30:
                    self._close(tr, px, "signal", now)
                    done.append(key)
                    continue
            # time stop
            if tr.tp_hits == 0 and now - tr.opened_ts >= TIME_STOP_MIN * 60:
                self._close(tr, px, "time_stop", now)
                done.append(key)
        for k in done:
            self.open.pop(k, None)

    def _close(self, tr, price, reason, now):
        tr.exit_ts = now
        tr.exit_price = price
        tr.exit_reason = reason
        if tr.side == "LONG":
            tr.pnl_pct = (price - tr.entry) / tr.entry * 100.0
        else:
            tr.pnl_pct = (tr.entry - price) / tr.entry * 100.0
        # approximate USDT on remaining size
        tr.pnl_usdt = tr.pnl_pct / 100.0 * tr.size_usdt * max(tr.remaining, 0.25)
        # booked partials at TPs already roughly in remaining
        self.closed.insert(0, tr.to_dict())
        self.closed = self.closed[:TRADES_CAP]

    def snapshot(self):
        by_var = defaultdict(lambda: {"open": 0, "closed": 0, "pnl_usdt": 0.0})
        for t in self.open.values():
            by_var[t.variant]["open"] += 1
        for d in self.closed:
            v = d.get("variant", "?")
            by_var[v]["closed"] += 1
            by_var[v]["pnl_usdt"] += float(d.get("pnl_usdt") or 0)
        return {
            "open": [t.to_dict() for t in self.open.values()],
            "closed_recent": self.closed[:30],
            "skips_recent": self.skips[-30:],
            "by_variant": dict(by_var),
            "sentence": self._sentence(by_var),
        }

    def _sentence(self, by_var):
        parts = []
        for v in VARIANTS:
            b = by_var.get(v) or {}
            parts.append(f"{v}: {b.get('open', 0)} open, {b.get('closed', 0)} closed")
        return "Paper ping bot running. " + "; ".join(parts) + ". SHORT is experimental."
