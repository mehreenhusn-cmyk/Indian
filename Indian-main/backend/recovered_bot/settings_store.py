import json
import os
import threading
from . import safe_io

_lock = threading.Lock()
_settings_file = None
_defaults = {
    "timeframe": "5m",  # Configurable strategy/scanner candle timeframe - one of
                          # "1m"/"3m"/"5m"/"15m"/"1h" (see exchange.py's
                          # TIMEFRAME_LABEL_TO_MIN). Read fresh by app.py on every
                          # watchlist/candle poll (never cached), so changing this
                          # in Settings takes effect on the very next poll cycle -
                          # no app restart needed.
    "invest_amount": 10.0,
    "tp_mode": "percent",      # "percent" or "usdt"
    "tp_value": 3.0,
    "sl_value": 1.5,
    "leverage": 1,
    "auto_execute": True,
    "inr_rate": 91.5,
    "daily_target_usdt": 3.0,
    "daily_loss_limit_usdt": 20.0,
    "max_open_trades": 0,     # 0 = no limit. N = the bot never holds more than N trades at one time
                                # (paper + live); a new signal is skipped while N are already open.
    "daily_gate_enabled": True,  # IST schedule: OFF 01:30, no trades 05:30-09:30, back ON 09:30 (see day_gate.py)
    "block_sell_on_gainer": False,  # True = no SELL on a top-10 GAINER until price crosses SD0 from above to below
    "block_buy_on_loser": False,    # True = no BUY on a top-10 LOSER until price crosses SD0 from below to above
    "symbol_auto_override": {},  # symbol -> bool; per-coin auto-trade on/off (missing = default True)
    "symbol_trade_mode": {},  # symbol -> "OFF"/"BUY"/"SELL"/"BOTH"; per-coin direction filter
                                # (missing = default "BOTH"). Replaces the old single AUTO/OFF
                                # button on Market Watch rows with a 4-way cycle.
    "favorites": [],  # list of favorited symbols for Market Watch
    "theme": "light",  # "light" or "dark" - applied on next app start
    "telegram_bot_token": "",  # SECURITY: never hardcode this in source - paste your
                                 # BotFather token here via Settings, after rotating any
                                 # previously-exposed one.
    "telegram_chat_id": "",
    # --- Exchange (see exchange.py) ---
    "active_exchange": "binance",  # "binance" is the only supported value - KuCoin fully
                                     # excluded. Kept as a settings key (rather than removed
                                     # outright) only so exchange.py/reconciliation.py's own
                                     # "isn't binance -> skip" guards keep working unchanged.
    # --- Live trading (Binance USDT-M Futures) - see binance_client.py/binance_trader.py ---
    "live_trading_enabled": False,  # master switch - OFF by default, must be turned on
                                      # explicitly in Settings after credentials are set.
    "binance_api_key": "",       # SECURITY: never hardcode - paste via Settings only,
    "binance_api_secret": "",     # generated at binance.com -> API Management with
                                    # Futures Trading permission enabled (Futures Transfer
                                    # permission NOT needed).
    "position_size_mode": "fixed",  # "fixed" (USDT amount) or "percent_balance" (% of
                                      # live futures account balance) - user picks in Settings.
    "position_size_value": 10.0,  # USDT if fixed mode, percent (e.g. 5 = 5%) if percent_balance mode
    "live_leverage": 3,  # separate from paper-trading's own "leverage" so a paper test
                           # value never accidentally becomes the real leverage
    # day_open_prices / day_open_key used to cache a "since 5:30 AM IST"
    # price snapshot for Market Watch's gainers/losers - removed, that list
    # now uses Binance's own rolling 24h % directly (matches the Binance
    # app, and matches what _topup_positions() already used). Old values
    # left harmless if present in an existing settings file on someone's
    # device; nothing reads these keys anymore.
    "lab_enabled": True,         # Shadow Lab (ai_shadow_lab.py): read-only replay of the strategy on 3m/5m/15m for the AI to learn from. False = fully off.
    "lab_replay_days": 14,       # how many days back the one-time replay goes
    "lab_max_symbols": 40,       # most coins the lab scans (watchlist first, then the bot's most-traded coins)
    "lab_tfs": "3m,5m,15m",      # timeframes the lab runs the strategy on
    "sd_track_enabled": True,    # record SD band size/shape while trades are open (ai_sd_tracker.py)
    "fee_roi_pct": 1.0,          # round-trip exchange fee as % of ROI taken off every PAPER trade
                                   # at close (Binance taker 0.05% x2 sides x 10x = ~1%). 0 = no fee.
    "scalp_close_roi_pct": 0.0,  # 0 = disabled. If >0, ANY open position closes itself the
                                   # instant ITS OWN roi_pct reaches this value - independent
                                   # of every other open position and independent of the
                                   # signal's own TP1-4/SL levels. For fast small-target
                                   # scalping (e.g. 10%) instead of waiting for TP4. Read
                                   # live every monitor tick, not frozen at position-open
                                   # time, so raising/lowering it applies to already-open
                                   # positions immediately too.
    "trail_mode": "step1",     # Trailing stop steps for open paper trades (Strategy TP mode only):
                                 # "off"   = SL to entry after TP1 (old behaviour)
                                 # "step1" = TP1 -> SL entry, TP2 -> SL TP1, TP3 -> SL TP2
                                 # "step2" = TP2 -> SL entry, TP3 -> SL TP1 (slower, more room)
                                 # Applies live to already-open trades too. See paper_trader.py.
    # --- AI Assistant (chat) - see ai_assistant.py ---
    "ai_enabled": False,       # master switch - OFF by default
    "ai_provider": "openai",   # "openai", "gemini" or "anthropic" (Claude)
    "ai_api_key": "",          # SECURITY: never hardcode - paste via Settings only
    "ai_model": "",            # optional model override ("" = automatic: newest working model
                                 # for the provider, with fallback if a name is retired)
    # ---- Vision AI (ai_vision.py): reads a chart image on every bot signal, trades its own virtual account ----
    "vision_enabled": True,       # needs the AI key from Settings > AI Assistant; without it the tab shows a setup note
    "vision_max_per_min": 6,      # AI calls per minute (free tiers are small); extra signals wait in line or time out
    "vision_max_calls_day": 200,  # AI calls per 24 h (your budget). 0 = no limit. New signals stop first, open-trade checks get 50% extra
    "vision_max_open": 8,         # AI virtual trades open at once
    "vision_review_candles": 2,   # an open AI trade is re-read every N closed candles (plus when its target is touched)
    "vision_max_risk_pct": 3.0,   # an AI stop further than this (% of price) is refused: the trade is skipped
    "vision_only_opened": True,   # judge only signals the bot really opened (False = every signal)
    "vision_notes": "",           # the owner's own notes about the indicators, added to the AI guide (edited in the app)
    # ---- the older AI modules (Coach, Pick, Desk, Shadow Lab, trackers ...). OFF = no background threads, no heavy work.
    "legacy_ai_enabled": False,
}
_settings = dict(_defaults)


def init(path):
    global _settings_file
    _settings_file = path
    _load()


def _load():
    if not _settings_file:
        return
    data, _src = safe_io.read_json_safe(_settings_file, "settings")
    if isinstance(data, dict):
        with _lock:
            _settings.update(data)
        if _src == "backup":
            _save()  # put a good main file back right away


def _save():
    if not _settings_file:
        return
    try:
        with _lock:
            text = json.dumps(_settings)
        safe_io.write_json_atomic(_settings_file, text)
    except Exception as e:
        print(f"[settings_store] SAVE FAILED: {e}")


def get_all():
    with _lock:
        return dict(_settings)


def get(key, default=None):
    with _lock:
        return _settings.get(key, default)


def update(**kwargs):
    with _lock:
        _settings.update(kwargs)
    _save()


def get_symbol_auto(symbol, default=True):
    """Per-coin auto-trade override. Returns True/False; if the symbol has no
    override saved yet, returns `default` (does NOT write anything)."""
    with _lock:
        overrides = _settings.get("symbol_auto_override", {})
        if symbol not in overrides:
            return default
        return bool(overrides[symbol])


def set_symbol_auto(symbol, enabled):
    """Turn auto-trade on/off for exactly one symbol, leaving every other
    symbol and the global auto_execute setting untouched."""
    with _lock:
        overrides = dict(_settings.get("symbol_auto_override", {}))
        overrides[symbol] = bool(enabled)
        _settings["symbol_auto_override"] = overrides
    _save()


_MODE_CYCLE = ["OFF", "BUY", "SELL", "BOTH"]


def get_symbol_mode(symbol, default="BOTH"):
    """Per-coin trade-direction filter: OFF (never auto-trade this symbol),
    BUY (only take BUY signals), SELL (only take SELL signals), or BOTH
    (take either direction - old default AUTO behavior). If nothing has been
    saved for this symbol yet, falls back to the legacy symbol_auto_override
    bool (False -> OFF, True -> BOTH) so upgrades from the old single
    AUTO/OFF button don't silently reset anyone's per-coin choice, then to
    `default`."""
    with _lock:
        modes = _settings.get("symbol_trade_mode", {})
        if symbol in modes and modes[symbol] in _MODE_CYCLE:
            return modes[symbol]
        legacy = _settings.get("symbol_auto_override", {})
        if symbol in legacy:
            return "BOTH" if legacy[symbol] else "OFF"
        return default


def set_symbol_mode(symbol, mode):
    """Set the trade-direction filter for exactly one symbol. mode must be
    one of OFF/BUY/SELL/BOTH."""
    if mode not in _MODE_CYCLE:
        return
    with _lock:
        modes = dict(_settings.get("symbol_trade_mode", {}))
        modes[symbol] = mode
        _settings["symbol_trade_mode"] = modes
    _save()


def cycle_symbol_mode(symbol):
    """Advance one symbol's mode to the next in OFF -> BUY -> SELL -> BOTH ->
    OFF and return the new mode - used by the Market Watch row tap handler."""
    current = get_symbol_mode(symbol)
    next_mode = _MODE_CYCLE[(_MODE_CYCLE.index(current) + 1) % len(_MODE_CYCLE)]
    set_symbol_mode(symbol, next_mode)
    return next_mode


def get_favorite(symbol):
    """Returns True if symbol is favorited on Market Watch, else False."""
    with _lock:
        favs = _settings.get("favorites", [])
        return symbol in favs


def set_favorite(symbol, enabled):
    """Add or remove a symbol from the favorites list."""
    with _lock:
        favs = list(_settings.get("favorites", []))
        if enabled and symbol not in favs:
            favs.append(symbol)
        elif not enabled and symbol in favs:
            favs.remove(symbol)
        _settings["favorites"] = favs
    _save()
