"""
Binance Top-10 Gainers/Losers 5m Scanner -> Telegram
Single-file version. Strategy = EMA(50) crossover + SD-band (SMA200 +/- stdev)
TP1-4 ladder, ported 1:1 from UPDATED.txt. No other indicator used as signal.
"""
import logging
import math
import time
from datetime import datetime, timezone

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================================================================
# CONFIG
# ================================================================

# --- Telegram (DEMO bot/chat for testing — replace before going live) ---
TELEGRAM_BOT_TOKEN = "8994572465:AAHyScKAq_V0FzVYnijJvOBuvMws2RbrRck"
TELEGRAM_CHAT_ID   = "885150597"
TELEGRAM_IS_DEMO   = True
BOT_NAME           = "HUSSAIN"

# --- Binance (USDT-M Futures) ---
BINANCE_FUTURES_BASE = "https://fapi.binance.com"
TIMEFRAME             = "5m"
TOP_N                 = 10      # top N gainers + top N losers -> 20 symbols
WATCHLIST_REFRESH_SEC = 60
SCAN_INTERVAL_SEC     = 15
REQUEST_TIMEOUT_SEC   = 10

# Only ever send a signal if its candle closed within this many seconds ago.
# Guarantees fresh/latest signals only — never an old/stale one. Locked to
# 25s (was 240s) for 1:1 Pine Script parity with the real execution
# pipeline's own signal-age gate (backend/recovered_bot/app.py,
# MAX_SIGNAL_AGE_SEC) - still comfortably above SCAN_INTERVAL_SEC (15s) so
# normal scan-cadence jitter never false-trips this.
MAX_SIGNAL_AGE_SEC = 25

# --- Strategy params (from UPDATED.txt) ---
SD_LOOKBACK    = 200   # `len` — SMA + stdev lookback
EMA_LENGTH     = 50    # `emaLength` — crossover EMA
CANDLE_HISTORY = 260   # candles fetched per symbol

LOG_FILE = "scanner.log"

log = logging.getLogger("bot")


# ================================================================
# BINANCE CLIENT
# ================================================================

def _get(path, params=None):
    url = BINANCE_FUTURES_BASE + path
    resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SEC)
    resp.raise_for_status()
    return resp.json()


_day_open_cache = {"date": None, "opens": {}}


def _current_utc_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _fetch_day_open(symbol):
    try:
        kl = _get("/fapi/v1/klines", {"symbol": symbol, "interval": "1d", "limit": 1})
        if kl:
            return symbol, float(kl[0][1])
    except Exception:
        pass
    return symbol, None


def _refresh_day_opens(symbols):
    today = _current_utc_date()
    if _day_open_cache["date"] == today and _day_open_cache["opens"]:
        return _day_open_cache["opens"]
    log.info("Fetching UTC day-open prices for %d symbols (once per day)...", len(symbols))
    opens = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(_fetch_day_open, s) for s in symbols]
        for fut in as_completed(futures):
            symbol, open_price = fut.result()
            if open_price:
                opens[symbol] = open_price
    _day_open_cache["date"] = today
    _day_open_cache["opens"] = opens
    log.info("Day-open cache refreshed: %d symbols", len(opens))
    return opens


def get_top_movers(top_n=None):
    """
    Returns a list of dicts, gainers first then losers:
    {"symbol": "GPSUSDT", "type": "Gainer"|"Loser", "rank": 1, "pct24h": -13.027}
    Ranked by UTC calendar-day % change (matches Binance app Ranking page),
    restricted to USDT perpetuals (excludes dated contracts like BTCUSDT_231229).
    """
    top_n = top_n or TOP_N
    price_data = _get("/fapi/v1/ticker/price")
    price_map = {
        d["symbol"]: float(d["price"])
        for d in price_data
        if d.get("symbol", "").endswith("USDT") and "_" not in d.get("symbol", "")
    }
    day_opens = _refresh_day_opens(list(price_map.keys()))

    calc = []
    for symbol, cur_price in price_map.items():
        open_price = day_opens.get(symbol)
        if not open_price:
            continue
        pct = (cur_price - open_price) / open_price * 100.0
        calc.append({"symbol": symbol, "pct24h": pct})

    ranked = sorted(calc, key=lambda d: d["pct24h"], reverse=True)

    movers = []
    for i, d in enumerate(ranked[:top_n], start=1):
        movers.append({"symbol": d["symbol"], "type": "Gainer", "rank": i, "pct24h": d["pct24h"]})
    for i, d in enumerate(ranked[-top_n:][::-1], start=1):  # biggest loser first
        movers.append({"symbol": d["symbol"], "type": "Loser", "rank": i, "pct24h": d["pct24h"]})

    return movers


def get_price(symbol):
    data = _get("/fapi/v1/ticker/price", {"symbol": symbol})
    return float(data["price"])


def get_klines(symbol, interval=None, limit=None):
    interval = interval or TIMEFRAME
    limit = limit or CANDLE_HISTORY

    raw = _get("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})

    candles = []
    for row in raw:
        open_time, o, h, l, c, v, close_time = row[0], row[1], row[2], row[3], row[4], row[5], row[6]
        candles.append({
            "open_time": open_time,
            "open": float(o), "high": float(h), "low": float(l), "close": float(c),
            "close_time": close_time,
        })
    return candles


# ================================================================
# STRATEGY (EMA50 crossover + SD-band TP1-4 ladder)
# ================================================================

def _sma(values):
    return sum(values) / len(values)


def _stdev_population(values):
    mean = _sma(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _ema_series(closes, length):
    n = len(closes)
    ema = [None] * n
    if n < length:
        return ema

    k = 2 / (length + 1)
    seed = _sma(closes[:length])
    ema[length - 1] = seed

    prev = seed
    for i in range(length, n):
        prev = closes[i] * k + prev * (1 - k)
        ema[i] = prev
    return ema


def _sd_bands(closes_window):
    sma = _sma(closes_window)
    sd = _stdev_population(closes_window)
    return {
        "zero": sma, "p1": sma + sd, "p2": sma + 2 * sd, "p3": sma + 3 * sd,
        "n1": sma - sd, "n2": sma - 2 * sd, "n3": sma - 3 * sd,
    }


def _tp_ladder_long(entry_price, b):
    n3, n2, n1, zero = b["n3"], b["n2"], b["n1"], b["zero"]
    p1, p2, p3 = b["p1"], b["p2"], b["p3"]

    if entry_price < n3:
        return n3, n2, n1, zero
    elif entry_price < n2:
        return n2, n1, zero, p1
    elif entry_price < n1:
        return n1, zero, p1, p2
    elif entry_price < zero:
        return zero, p1, p2, p3
    elif entry_price < p1:
        return p1, p2, p3, p3
    elif entry_price < p2:
        return p2, p3, p3, p3
    else:
        return p3, p3, p3, p3


def _tp_ladder_short(entry_price, b):
    n3, n2, n1, zero = b["n3"], b["n2"], b["n1"], b["zero"]
    p1, p2, p3 = b["p1"], b["p2"], b["p3"]

    if entry_price > p3:
        return p3, p2, p1, zero
    elif entry_price > p2:
        return p2, p1, zero, n1
    elif entry_price > p1:
        return p1, zero, n1, n2
    elif entry_price > zero:
        return zero, n1, n2, n3
    elif entry_price > n1:
        return n1, n2, n3, n3
    else:
        return n2, n3, n3, n3


def evaluate(candles):
    """candles: closed candles only, oldest first. Returns a signal dict or None."""
    needed = max(SD_LOOKBACK, EMA_LENGTH) + 2
    if len(candles) < needed:
        return None

    closes = [c["close"] for c in candles]
    ema = _ema_series(closes, EMA_LENGTH)

    i = len(candles) - 1
    prev_close, curr_close = closes[i - 1], closes[i]
    prev_ema, curr_ema = ema[i - 1], ema[i]

    if prev_ema is None or curr_ema is None:
        return None

    cross_up = prev_close <= prev_ema and curr_close > curr_ema
    cross_down = prev_close >= prev_ema and curr_close < curr_ema
    if not (cross_up or cross_down):
        return None

    signal_candle = candles[i]
    entry_price = signal_candle["close"]
    sl_price = signal_candle["low"] if cross_up else signal_candle["high"]

    window = closes[i - SD_LOOKBACK + 1: i + 1]
    bands = _sd_bands(window)

    if cross_up:
        tp1, tp2, tp3, tp4 = _tp_ladder_long(entry_price, bands)
        direction = "LONG"
        pct = lambda tp: (tp - entry_price) / entry_price * 100
        sl_pct = (entry_price - sl_price) / entry_price * 100
    else:
        tp1, tp2, tp3, tp4 = _tp_ladder_short(entry_price, bands)
        direction = "SHORT"
        pct = lambda tp: (entry_price - tp) / entry_price * 100
        sl_pct = (sl_price - entry_price) / entry_price * 100

    return {
        "direction": direction, "entry": entry_price, "sl": sl_price, "sl_pct": sl_pct,
        "tp1": tp1, "tp1_pct": pct(tp1), "tp2": tp2, "tp2_pct": pct(tp2),
        "tp3": tp3, "tp3_pct": pct(tp3), "tp4": tp4, "tp4_pct": pct(tp4),
        "candle_close_time": signal_candle["close_time"],
    }


# ================================================================
# TELEGRAM
# ================================================================

def send_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True}

    for attempt in (1, 2):
        try:
            resp = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT_SEC)
            if resp.status_code == 200:
                return True
            log.warning("Telegram send failed (attempt %d): %s %s", attempt, resp.status_code, resp.text)
        except requests.RequestException as e:
            log.warning("Telegram send error (attempt %d): %s", attempt, e)
    return False


def format_signal(symbol, signal, mover, live_price):
    header = "🟢 LONG SIGNAL" if signal["direction"] == "LONG" else "🔴 SHORT SIGNAL"
    market_label = f"{mover['type']} #{mover['rank']}"
    candle_utc = datetime.fromtimestamp(
        signal["candle_close_time"] / 1000, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S")
    chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}.P"

    lines = [
        header,
        "--------------------------",
        f"Symbol    : {symbol}",
        f"Timeframe : {TIMEFRAME}",
        f"Market    : {market_label}",
        f"Binance 24h: {mover['pct24h']:+.3f}%",
        "--------------------------",
        f"Entry      : {signal['entry']:.8f}",
        f"Live Price : {live_price:.8f}",
        f"Stop Loss  : {signal['sl']:.8f} ({signal['sl_pct']:.2f}%)",
        f"TP1        : {signal['tp1']:.8f} ({signal['tp1_pct']:.2f}%)",
        f"TP2        : {signal['tp2']:.8f} ({signal['tp2_pct']:.2f}%)",
        f"TP3        : {signal['tp3']:.8f} ({signal['tp3_pct']:.2f}%)",
        f"TP4        : {signal['tp4']:.8f} ({signal['tp4_pct']:.2f}%)",
        "--------------------------",
        f"Candle UTC : {candle_utc}",
        f"Chart      : {chart_url}",
        f"Bot        : {BOT_NAME}",
    ]
    return "\n".join(lines)


# ================================================================
# SCANNER LOOP
# ================================================================

class Scanner:
    def __init__(self):
        self.watchlist = []
        self.movers_info = {}
        self.last_watchlist_refresh = 0.0
        self.last_signal_key = {}

    def refresh_watchlist(self):
        try:
            movers = get_top_movers(TOP_N)
        except Exception as e:
            log.error("Failed to refresh top movers: %s", e)
            return

        new_watchlist = [m["symbol"] for m in movers]
        new_info = {m["symbol"]: m for m in movers}

        added = set(new_watchlist) - set(self.watchlist)
        removed = set(self.watchlist) - set(new_watchlist)
        if added:
            log.info("Watchlist added: %s", sorted(added))
        if removed:
            log.info("Watchlist removed: %s", sorted(removed))
            for sym in removed:
                self.last_signal_key.pop(sym, None)

        self.watchlist = new_watchlist
        self.movers_info = new_info
        self.last_watchlist_refresh = time.time()
        log.info("Watchlist (%d symbols): %s", len(self.watchlist), self.watchlist)

    def scan_symbol(self, symbol):
        try:
            candles = get_klines(symbol, TIMEFRAME, CANDLE_HISTORY)
        except Exception as e:
            log.warning("Klines fetch failed for %s: %s", symbol, e)
            return

        if len(candles) < 3:
            return

        closed_candles = candles[:-1]
        signal = evaluate(closed_candles)
        if not signal:
            return

        key = (signal["candle_close_time"], signal["direction"])
        if self.last_signal_key.get(symbol) == key:
            return

        age_sec = time.time() - (signal["candle_close_time"] / 1000)
        if age_sec > MAX_SIGNAL_AGE_SEC:
            log.info("Skipping stale signal for %s (candle closed %.0fs ago)", symbol, age_sec)
            self.last_signal_key[symbol] = key
            return

        self.last_signal_key[symbol] = key

        mover = self.movers_info.get(symbol, {"type": "Gainer", "rank": 0, "pct24h": 0.0})

        try:
            live_price = get_price(symbol)
        except Exception as e:
            log.warning("Live price fetch failed for %s: %s", symbol, e)
            live_price = signal["entry"]

        text = format_signal(symbol, signal, mover, live_price)
        ok = send_message(text)
        log.info("Signal %s %s entry=%.8f sent=%s", symbol, signal["direction"], signal["entry"], ok)

    def run_forever(self):
        log.info("Scanner starting — timeframe=%s top_n=%d demo_telegram=%s",
                  TIMEFRAME, TOP_N, TELEGRAM_IS_DEMO)

        self.refresh_watchlist()

        while True:
            try:
                if time.time() - self.last_watchlist_refresh >= WATCHLIST_REFRESH_SEC:
                    self.refresh_watchlist()

                for symbol in list(self.watchlist):
                    self.scan_symbol(symbol)

                time.sleep(SCAN_INTERVAL_SEC)

            except KeyboardInterrupt:
                log.info("Scanner stopped by user.")
                break
            except Exception as e:
                log.error("Unexpected error in main loop: %s", e)
                time.sleep(SCAN_INTERVAL_SEC)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_FILE)],
    )
    Scanner().run_forever()
