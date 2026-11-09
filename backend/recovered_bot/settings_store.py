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
    "btc_fixed": True,        # True = BTCUSDT is always on the bot watchlist (even when not in the top-10 gainers/losers) and trades with its own size below. PAPER only.
    "btc_margin": 1000.0,     # USDT margin of every BTCUSDT paper trade
    "btc_leverage": 10,       # leverage of every BTCUSDT paper trade
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
    "doctor_enabled": False,     # Strategy Doctor / Labs switch. False = their background jobs stay off and the app hides them. Nothing is deleted; set True to bring them back.
    "old_labs_locked": True,     # MASTER LOCK: Strategy Lab, Scan Lab and the old AI Shadow Lab refuse to start while True (Vision AI, Dual Bot, Ping are not affected).
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
    "vision_enabled": False,      # OFF by default (28 Oct): not started at boot. needs the AI key from Settings > AI Assistant; without it the tab shows a setup note
    "vision_max_per_min": 6,      # AI calls per minute (free tiers are small); extra signals wait in line or time out
    "vision_max_calls_day": 200,  # AI calls per 24 h (your budget). 0 = no limit. New signals stop first, open-trade checks get 50% extra
    "vision_max_open": 8,         # AI virtual trades open at once
    "vision_review_candles": 4,   # an open AI trade is re-read every N closed candles (plus when its target is touched). 4 keeps free quotas alive; the hard stop is checked every tick anyway
    "vision_own_daily_loss_cap": 0,   # AI own-scan: stop scanning for the day after this many USDT of net loss. 0 = NO daily loss limit
    "vision_own_max_calls_hour": 0,    # AI own-scan: AI calls per hour. 0 = no limit (default now: your own keys decide the real limit)
    "vision_cap_enabled": False,   # paper capital manager for AI Own (ai_capital.py): grade gate, daily target/loss lock, risk sizing. PAPER only
    "vision_cap_start": 100.0,    # AI Own paper account start balance (USDT)
    "vision_cap_target": 0.0,    # daily profit lock (USDT): at this net, AI Own stops opening trades until 5:30 AM IST. 0 = off. NOT a goal to force
    "vision_cap_loss": 0.0,      # daily loss lock (USDT). 0 = off
    "vision_cap_risk": 2.0,       # USDT lost if the stop hits, per trade. Leverage changes the margin, never this
    "vision_cap_max_open": 2,     # AI Own trades open at once
    "vision_cap_explore": True,   # while fewer than 40 setups are resolved (grade U), allow trades at half risk so the AI can learn
    # ---- AI Own FREE MONEY mode (paper only). ON = no daily loss/target lock, no max-open limit, no grade gate, no 3% stop limit.
    # AI Own then trades its own paper account: margin per trade x leverage. The bot's own settings are never touched.
    "vision_own_free_money": True,
    "vision_own_margin": 100.0,   # USDT margin per AI Own trade (position = margin x leverage)
    "vision_own_lev": 10,         # leverage for AI Own trades only
    "vision_max_risk_pct": 3.0,   # an AI stop further than this (% of price) is refused: the trade is skipped
    "vision_only_opened": True,   # judge only signals the bot really opened (False = every signal)
    "vision_notes": "",           # the owner's own notes about the indicators, added to the AI guide (edited in the app)
    "vision_lessons_enabled": True,  # learning notebook (ai_vision_lessons.py): a lesson after every closed AI trade + rules you approve. Uses a few cheap text calls in idle time
    # ---- optional BACKUP AI key for the Vision AI: used automatically when the main key runs out of quota ----
    "ai_switch_pct": 90,          # a key that used this % of its daily budget goes to the end of the line (next key answers first)
    "ai_slot_day_limit": 200,     # default daily call budget per key (set aiN_day_limit for one key, e.g. ai2_day_limit)
    "ai2_provider": "mistral",    # "mistral" or "groq" (both have a free plan), or "openai" / "gemini" / "anthropic"
    "ai2_api_key": "",            # SECURITY: never hardcode - paste via Settings only
    "ai2_model": "",              # optional; "" = a sensible vision model for that provider
    "ai3_provider": "groq",      # extra free key #3: "mistral", "groq", "gemini", "openrouter" ... (empty key = slot unused)
    "ai3_api_key": "",            # SECURITY: never hardcode - paste via Settings only
    "ai3_model": "",              # optional
    "ai4_provider": "groq",      # extra free key #4: "mistral", "groq", "gemini", "openrouter" ... (empty key = slot unused)
    "ai4_api_key": "",            # SECURITY: never hardcode - paste via Settings only
    "ai4_model": "",              # optional
    "ai5_provider": "mistral",   # extra key slot #5: the key is detected automatically when pasted in Settings > AI keys
    "ai5_api_key": "",            # SECURITY: never hardcode - paste via Settings only
    "ai5_model": "",
    "ai6_provider": "mistral",   # extra key slot #6: the key is detected automatically when pasted in Settings > AI keys
    "ai6_api_key": "",            # SECURITY: never hardcode - paste via Settings only
    "ai6_model": "",
    "ai7_provider": "mistral",   # extra key slot #7: the key is detected automatically when pasted in Settings > AI keys
    "ai7_api_key": "",            # SECURITY: never hardcode - paste via Settings only
    "ai7_model": "",
    "ai8_provider": "mistral",   # extra key slot #8: the key is detected automatically when pasted in Settings > AI keys
    "ai8_api_key": "",            # SECURITY: never hardcode - paste via Settings only
    "ai8_model": "",
    # ---- the older AI modules (Coach, Pick, Desk, Shadow Lab, trackers ...). OFF = no background threads, no heavy work.
    "legacy_ai_enabled": False,
    # ---- AI MASTER OFF (Part 0, 9 Nov 2026): True = every AI switch is forced OFF at each backend start
    # (legacy_ai_enabled, vision_enabled, ai_enabled) and the daily AI backup zip does not start. Set False to allow AI again.
    "ai_master_off": True,
    # ---- Part 7 gates (README_FILTER): "off" | "log" (only writes what it would block) | "block" (skips the entry). Current bot, 5m only.
    "f7_gates_mode": "off",
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
            # one-time: the old default of 12 AI Own calls per hour is lifted (0 = no limit). A value you set
            # yourself later is kept; the flag makes sure this runs only once.
            if not _settings.get("_mig_own_hour_unlimited"):
                if _settings.get("vision_own_max_calls_hour") == 12:
                    _settings["vision_own_max_calls_hour"] = 0
                _settings["_mig_own_hour_unlimited"] = True
                _src = "backup"          # forces the save below
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
