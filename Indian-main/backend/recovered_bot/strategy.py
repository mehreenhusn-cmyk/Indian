from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple, List, Dict

from .utils import setup_logger

logger = setup_logger("StrategyEngine")


@dataclass
class Signal:
    symbol: str
    action: str
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    tp4: float
    signal_time: str
    current_price: float
    candle_index: int = 0
    # Entry-context tags for the AI Assistant (ai_stats.py). Pure metadata -
    # they never influence whether a signal fires or where SL/TP sit.
    entry_zone: Optional[str] = None       # e.g. "-2sd..-1sd" - where price sat in the SD bands at entry
    ema_slope_pct: Optional[float] = None  # EMA change over the last 3 candles, % (sign = direction)
    volume_ratio: Optional[float] = None   # signal-candle volume / average of previous 20 candles
    sd_mean: Optional[float] = None        # SD basis at the signal candle (mean of the lookback closes)
    sd_std: Optional[float] = None         # ... and its std-dev - lets paper_trader track the trade's SD path
    # Market-regime tags at entry (AI only, never used to allow/block a trade):
    regime_cross_n: Optional[int] = None   # EMA50 crosses in the last 20 closed candles (incl. this one): 1 = clean, 3+ = choppy
    atr_pct: Optional[float] = None        # ATR(14) as % of close - how violent candles were
    sd_width_pct: Optional[float] = None   # 1 SD as % of the SD mean - how wide the SD bands are
    # EMA slope shape at entry (AI only, metadata - never used to allow/block a trade):
    ema_slope_prev_pct: Optional[float] = None   # EMA change over the 3 candles BEFORE the last 3, %
    ema_slope10_pct: Optional[float] = None      # EMA change over the last 10 candles, %
    ema_turn: Optional[str] = None               # "turning up" / "turning down" / "steady up" / "steady down" / "flat"


class ABCDStrategy:

    def __init__(
        self,
        lookback_len: int = 200,
        ema_length: int = 50
    ):
        self.lookback_len = lookback_len
        self.ema_length = ema_length

    def _compute_ema(self, closes: List[float]) -> List[Optional[float]]:
        """Pine-style EMA, SMA-seeded on the first `ema_length` closes.
        1:1 with scanner/5mins_scanner_binance_top10_bothside.py::_ema_series."""
        n = len(closes)
        length = self.ema_length
        ema: List[Optional[float]] = [None] * n
        if n < length:
            return ema
        k = 2 / (length + 1)
        prev = sum(closes[:length]) / length
        ema[length - 1] = prev
        for i in range(length, n):
            prev = closes[i] * k + prev * (1 - k)
            ema[i] = prev
        return ema

    def _rolling_mean_std(self, closes: List[float]) -> Tuple[float, float]:
        window = closes[-self.lookback_len:]
        n = len(window)
        mean = sum(window) / n
        variance = sum((x - mean) ** 2 for x in window) / n
        std = variance ** 0.5
        return mean, std

    def calculate_tp_levels(
        self,
        entry_price: float,
        is_long: bool,
        levels: Dict[str, float]
    ) -> Tuple[float, float, float, float]:

        onesd = levels["onesd"]
        twosd = levels["twosd"]
        threesd = levels["threesd"]
        neg_onesd = levels["neg_onesd"]
        neg_twosd = levels["neg_twosd"]
        neg_threesd = levels["neg_threesd"]
        zero_price = levels["zero_price"]

        if is_long:
            if entry_price < neg_threesd:
                return (neg_threesd, neg_twosd, neg_onesd, zero_price)
            elif entry_price < neg_twosd:
                return (neg_twosd, neg_onesd, zero_price, onesd)
            elif entry_price < neg_onesd:
                return (neg_onesd, zero_price, onesd, twosd)
            elif entry_price < zero_price:
                return (zero_price, onesd, twosd, threesd)
            elif entry_price < onesd:
                return (onesd, twosd, threesd, threesd)
            elif entry_price < twosd:
                return (twosd, threesd, threesd, threesd)
            else:
                return (threesd, threesd, threesd, threesd)
        else:
            if entry_price > threesd:
                return (threesd, twosd, onesd, zero_price)
            elif entry_price > twosd:
                return (twosd, onesd, zero_price, neg_onesd)
            elif entry_price > onesd:
                return (onesd, zero_price, neg_onesd, neg_twosd)
            elif entry_price > zero_price:
                return (zero_price, neg_onesd, neg_twosd, neg_threesd)
            elif entry_price > neg_onesd:
                return (neg_onesd, neg_twosd, neg_threesd, neg_threesd)
            elif entry_price > neg_twosd:
                return (neg_twosd, neg_threesd, neg_threesd, neg_threesd)
            else:
                return (neg_twosd, neg_threesd, neg_threesd, neg_threesd)

    @staticmethod
    def _zone_label(price: float, levels: Dict[str, float]) -> str:
        """Which SD band `price` sits in, using the same levels TP1-4 come from."""
        bounds = (
            ("neg_threesd", "<-3sd"),
            ("neg_twosd", "-3sd..-2sd"),
            ("neg_onesd", "-2sd..-1sd"),
            ("zero_price", "-1sd..mean"),
            ("onesd", "mean..+1sd"),
            ("twosd", "+1sd..+2sd"),
            ("threesd", "+2sd..+3sd"),
        )
        for key, label in bounds:
            if price < levels[key]:
                return label
        return ">+3sd"

    @staticmethod
    def _entry_context(candles: List[Dict], ema_values: List[Optional[float]]):
        """(ema_slope_pct, volume_ratio) - each None if it can't be computed."""
        slope = None
        try:
            a, b = ema_values[-1], ema_values[-4]
            if a is not None and b:
                slope = round((a - b) / b * 100.0, 4)
        except Exception:
            slope = None
        vol_ratio = None
        try:
            vols = [float(c.get("volume") or 0.0) for c in candles]
            prev = vols[-21:-1]
            avg = sum(prev) / len(prev) if prev else 0.0
            if avg > 0:
                vol_ratio = round(vols[-1] / avg, 2)
        except Exception:
            vol_ratio = None
        return slope, vol_ratio

    @staticmethod
    def _slope_context(ema_values: List[Optional[float]]):
        """(prev_3_candle_slope %, 10_candle_slope %, turn label) - each None if it can't
        be computed. Pure read of the EMA series; the strategy's rules do not use it."""
        def pct(i, j):
            try:
                a, b = ema_values[i], ema_values[j]
                return round((a - b) / b * 100.0, 4) if (a is not None and b) else None
            except Exception:
                return None
        now, prev, s10 = pct(-1, -4), pct(-4, -7), pct(-1, -11)
        turn = None
        if now is not None and prev is not None:
            eps = 0.005   # % - below this the EMA is treated as flat
            if abs(now) < eps and abs(prev) < eps:
                turn = "flat"
            elif now > 0 and prev <= 0:
                turn = "turning up"
            elif now < 0 and prev >= 0:
                turn = "turning down"
            else:
                turn = "steady up" if now > 0 else "steady down"
        return prev, s10, turn

    @staticmethod
    def _regime_context(candles: List[Dict], closes: List[float],
                        ema_values: List[Optional[float]], mean: float, std: float):
        """(regime_cross_n, atr_pct, sd_width_pct) - each None if not computable.
        Pure metadata for the AI Assistant; read-only on the candle data."""
        cross_n = None
        try:
            n = 0
            for i in range(len(closes) - 20, len(closes)):
                if i < 1 or ema_values[i] is None or ema_values[i - 1] is None:
                    continue
                up = closes[i - 1] <= ema_values[i - 1] and closes[i] > ema_values[i]
                dn = closes[i - 1] >= ema_values[i - 1] and closes[i] < ema_values[i]
                if up or dn:
                    n += 1
            cross_n = n
        except Exception:
            cross_n = None
        atr_pct = None
        try:
            trs = []
            for i in range(len(candles) - 14, len(candles)):
                h, l = float(candles[i]["high"]), float(candles[i]["low"])
                pc = float(candles[i - 1]["close"])
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            if trs and closes[-1] > 0:
                atr_pct = round(sum(trs) / len(trs) / closes[-1] * 100.0, 4)
        except Exception:
            atr_pct = None
        sd_width_pct = None
        try:
            if mean and mean > 0:
                sd_width_pct = round(std / mean * 100.0, 4)
        except Exception:
            sd_width_pct = None
        return cross_n, atr_pct, sd_width_pct

    def generate_signal(
        self,
        candles: List[Dict],
        symbol: str,
        tf_min: Optional[int] = None
    ) -> Optional[Signal]:
        """candles: CLOSED candles only, oldest first (dict key "timestamp" =
        candle OPEN time in ms). tf_min lets signal_time be stamped with the
        candle CLOSE time like the scanner does - the app's 25s signal-age gate
        measures from that; measured from the open time it was always >= one
        full candle old and so always "stale"."""

        if len(candles) < max(self.lookback_len, self.ema_length) + 2:
            return None

        closes = [float(c["close"]) for c in candles]
        ema_values = self._compute_ema(closes)

        last_close = closes[-1]
        prev_close = closes[-2]
        last_ema = ema_values[-1]
        prev_ema = ema_values[-2]

        if prev_ema is None or last_ema is None:
            return None

        cross_up = (prev_close <= prev_ema) and (last_close > last_ema)
        cross_down = (prev_close >= prev_ema) and (last_close < last_ema)

        if not cross_up and not cross_down:
            return None

        mean, std = self._rolling_mean_std(closes)
        levels = {
            "zero_price": mean,
            "onesd": mean + std,
            "twosd": mean + 2 * std,
            "threesd": mean + 3 * std,
            "neg_onesd": mean - std,
            "neg_twosd": mean - 2 * std,
            "neg_threesd": mean - 3 * std,
        }

        last_candle = candles[-1]
        ts = last_candle.get("timestamp")
        if ts is not None:
            close_ms = int(ts) + int(tf_min) * 60_000 - 1 if tf_min else int(ts)
            signal_time_str = datetime.fromtimestamp(
                close_ms / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")
        else:
            signal_time_str = ""

        entry_zone = self._zone_label(last_close, levels)
        ema_slope_pct, volume_ratio = self._entry_context(candles, ema_values)
        slope_prev, slope10, ema_turn = self._slope_context(ema_values)
        regime_cross_n, atr_pct, sd_width_pct = self._regime_context(candles, closes, ema_values, mean, std)

        if cross_up:
            entry_price = last_close
            stop_loss = float(last_candle["low"])
            tp1, tp2, tp3, tp4 = self.calculate_tp_levels(
                entry_price, True, levels
            )
            return Signal(
                symbol=symbol,
                action="BUY",
                entry_price=entry_price,
                stop_loss=stop_loss,
                tp1=tp1, tp2=tp2, tp3=tp3, tp4=tp4,
                signal_time=signal_time_str,
                current_price=entry_price,
                candle_index=len(candles) - 1,
                entry_zone=entry_zone,
                ema_slope_pct=ema_slope_pct,
                volume_ratio=volume_ratio,
                sd_mean=mean,
                sd_std=std,
                regime_cross_n=regime_cross_n,
                atr_pct=atr_pct,
                sd_width_pct=sd_width_pct,
                ema_slope_prev_pct=slope_prev, ema_slope10_pct=slope10, ema_turn=ema_turn,
            )

        entry_price = last_close
        stop_loss = float(last_candle["high"])
        tp1, tp2, tp3, tp4 = self.calculate_tp_levels(
            entry_price, False, levels
        )
        return Signal(
            symbol=symbol,
            action="SELL",
            entry_price=entry_price,
            stop_loss=stop_loss,
            tp1=tp1, tp2=tp2, tp3=tp3, tp4=tp4,
            signal_time=signal_time_str,
            current_price=entry_price,
            candle_index=len(candles) - 1,
            entry_zone=entry_zone,
            ema_slope_pct=ema_slope_pct,
            volume_ratio=volume_ratio,
            sd_mean=mean,
            sd_std=std,
            regime_cross_n=regime_cross_n,
            atr_pct=atr_pct,
            sd_width_pct=sd_width_pct,
            ema_slope_prev_pct=slope_prev, ema_slope10_pct=slope10, ema_turn=ema_turn,
        )
