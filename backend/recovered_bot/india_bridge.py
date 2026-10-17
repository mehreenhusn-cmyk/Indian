"""india_bridge.py - wires the bot's OWN strategy (strategy.ABCDStrategy) into the
India paper engine. No strategy logic is copied or changed here.

Flow per closed candle:  provider candles -> ABCDStrategy.generate_signal()
  -> Signal(BUY/SELL, stop_loss, tp1..tp4) -> engine.on_signal(spot SL / spot TP)
BUY -> buy ITM CE, SELL -> buy ITM PE. SL = the signal candle low/high (exactly as
in crypto); the whole TP1..TP4 ladder goes to the engine, which exits at its
`target_level` and shifts SL after TP1 (see india_paper).
"""


def to_strategy_candles(cs):
    """provider candle (t,o,h,l,c,v) -> the dict format ABCDStrategy expects."""
    return [{"timestamp": int(c["t"].timestamp() * 1000), "open": c["o"],
             "high": c["h"], "low": c["l"], "close": c["c"],
             "volume": c.get("v", 0)} for c in cs]


# Entry-context tags the strategy already computes (metadata only) - kept with the trade for the Strategy Doctor.
TAG_FIELDS = ("entry_zone", "ema_slope_pct", "volume_ratio", "sd_mean", "sd_std", "regime_cross_n", "atr_pct",
              "sd_width_pct", "ema_slope_prev_pct", "ema_slope10_pct", "ema_turn", "adx", "ema_gap_atr", "htf_trend")


def signal_tags(sig, tf_min):
    out = {"timeframe": f"{int(tf_min)}m"}
    for k in TAG_FIELDS:
        v = getattr(sig, k, None)
        if v is not None:
            out[k] = v
    return out


class IndiaStrategyRunner:
    def __init__(self, provider, engine, strategy, tf_min=5, history=300):
        self.p, self.e, self.strategy = provider, engine, strategy
        self.tf, self.history = int(tf_min), history
        self._last = {}     # underlying -> open-time of the last candle already processed

    def run(self, underlying):
        """Call after each closed candle (safe to call more often: a candle is
        only evaluated once). Returns engine result dict (+'signal') or None."""
        u = underlying.upper()
        cs = self.p.get_candles(u, self.tf, self.history)
        if not cs or self._last.get(u) == cs[-1]["t"]:
            return None
        self._last[u] = cs[-1]["t"]
        sig = self.strategy.generate_signal(to_strategy_candles(cs), u, tf_min=self.tf)
        if sig is None:
            return None
        tps = [t for t in (sig.tp1, sig.tp2, sig.tp3, sig.tp4) if t]
        res = self.e.on_signal(u, sig.action, sig.stop_loss, sig.tp1, tps=tps, tags=signal_tags(sig, self.tf))
        res["signal"] = sig
        return res
