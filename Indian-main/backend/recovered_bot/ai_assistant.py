"""
ai_assistant.py - simple chat-completion bridge for the in-app "AI
Assistant" screen. Calls whichever provider is picked in Settings
(ai_provider: "openai", "gemini" or "anthropic" = Claude) using the user's own API key
(ai_api_key, pasted in Settings - never hardcoded, same rule as the
Telegram/KuCoin keys). Completely separate from the trading/strategy
pipeline - this only answers chat questions, it never places trades or
changes settings itself.

Requires ai_enabled=True and a non-empty ai_api_key; otherwise ask()
returns an ok=False error the frontend can show as a friendly message
instead of a stack trace.
"""
import time
import requests

from . import settings_store, status, paper_trader, trade_store, ai_stats, telemetry

# A position whose price feed hasn't updated in this long is flagged to the
# AI as "stale/stuck" - this is exactly the 2U2USDTM class of bug (dead
# KuCoin feed for a thin/invalid symbol): P&L frozen, Close silently doing
# nothing. Matches paper_trader.py's own GAP_RECONCILE_S-style thinking but
# kept independent/short here since this is just for the chat's awareness,
# not for triggering a reconcile.
_STALE_FEED_AFTER_S = 120
# Within this % of SL, proactively flag it as a risk in the AI's context.
_SL_PROXIMITY_PCT = 0.5

# ---------------------------------------------------------------------------
# DIAGNOSTIC KNOWLEDGE BASE - Binance Futures execution errors + internal
# app states the AI Assistant should be able to explain in plain terms the
# moment a user asks "why did my order fail" / "kya hua is trade ko" style
# questions. This is static reference text (not fetched from Binance) -
# grounded in how THIS codebase actually places/protects orders (see
# binance_trader.py + protection_manager.py's own docstring on
# closePosition=true vs reduceOnly+quantity), so the explanations match what
# is really happening in this app, not a generic API-docs dump. Always
# appended to the system prompt (small, cheap, and it's exactly the kind of
# thing that should never need a live lookup) - the REALTIME alert feed in
# _recent_error_alerts() below supplies the "did THIS actually happen to ME
# just now" half of the picture.
_ERROR_KNOWLEDGE_BASE = """
[EXECUTION ERROR REFERENCE - explain the exact code/message the user is
asking about in plain terms, using this app's own behaviour, not a generic
textbook answer]

- Binance error -4120 (algo/conditional order requirement not met): fires
  when placing a STOP_MARKET/TAKE_PROFIT_MARKET protective order (this
  app's SL and TP orders on LIVE trades) with a missing/invalid required
  field for that order TYPE - e.g. no stopPrice, no workingType, or neither
  closePosition NOR a valid reduceOnly+quantity combo set. This app's own
  protection_manager.py deliberately always sends closePosition=true for
  these orders (not reduceOnly+quantity) exactly to avoid this class of
  rejection - so if this fires, it usually means the SL/TP placement call
  got a malformed price (e.g. a stopPrice that violates Binance's
  PRICE_FILTER tick size for that symbol) rather than a missing field.
  Fix: check the alert's exact stopPrice against the symbol's tick size;
  retrying the placement (which the app does automatically on modify)
  usually succeeds once the price is valid.
- Binance error -2019 (Margin is insufficient): the account does not have
  enough available margin to open/increase this position at the requested
  size + leverage. Fix: lower Invest Amount or Leverage in Settings, add
  more margin to the Binance Futures wallet, or close another open position
  to free up margin. This is NOT a bug in the app - Binance is refusing the
  order at the exchange level before it ever reaches this bot's own
  position tracking.
- Binance error -2022 (ReduceOnly Order is rejected) - "ghost reduce-only":
  a reduceOnly/closePosition order was sent for a symbol where Binance's
  own live position is already flat (zero) or smaller than expected -
  there's nothing left to reduce. This usually means the position was
  already closed on the exchange (manually, by another stop, or by
  liquidation) before this app's own close/SL/TP order reached Binance, so
  the app's local position record is a "ghost" of a position that no
  longer exists exchange-side. Fix: run a reconcile (POST /api/reconcile /
  the app does this automatically on reconnect) - it re-checks every open
  local position against actual candle/price history and closes any ghost
  entries locally so the two sides re-sync.
- WebSocket drops / "market_data_state": RECONNECTING or STALE: the
  Binance Futures price WebSocket (market_ws.py) disconnected - normal on
  mobile data / Android battery-saving killing background sockets, or a
  routine Binance stream reset (Binance recycles Futures WS connections
  periodically). The app auto-reconnects and falls back to REST polling
  for live prices in the meantime, so P&L keeps updating (just possibly a
  few seconds staler) rather than freezing - only a SUSTAINED drop (see the
  stale-feed risk flag below) is actually worth worrying about.
"""

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_OPENAI_MODEL = "gpt-4o-mini"

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
# Tried in order: the model set in Settings first, then these (cheap and fast first). A retired or unknown name
# answers 404 and the next one is tried; any other error (bad key, no credit, rate limit) is reported at once.
_ANTHROPIC_MODELS = ("claude-haiku-4-5-20251001", "claude-sonnet-5-5")

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Tried in order until one works. The user's configured model (Settings > AI
# Assistant > AI model) is always tried FIRST (see ask()/_call_gemini below) -
# this list is only what comes after it. Requested order: 2.5-flash ->
# 1.5-flash-8b -> 1.5-flash, then the older discovery-era fallbacks as an
# extra safety net (some model names get retired and return 404 on v1beta -
# if every name here 404s, _discover_gemini_models() asks Google which
# models this key can actually use). The first one that works is remembered
# for the process life so later calls skip straight to it.
_GEMINI_FALLBACKS = [
    "gemini-2.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash",
    "gemini-flash-lite-latest",
]
_gemini_working_model = None
_GEMINI_RETRYABLE = (429, 503)  # quota / high-demand - worth trying another model or waiting, not a dead end
_GEMINI_MAX_PASSES = 3           # whole-chain retries when EVERY model is 429/503 (real "high demand" spike)
_GEMINI_BACKOFF_BASE = 1.5       # seconds; doubles each extra pass

_STRATEGY_RULES = (
    "\n\nUSER'S STRATEGY (fixed facts - explain trades using these, never contradict them): "
    "ENTRY: candle CLOSE crosses EMA 50 (close above = BUY, close below = SELL), on the "
    "timeframe chosen in Settings. SD LEVELS: rolling mean and population std-dev of the last "
    "200 closes (same as the user's TradingView Z-score indicator); lines are mean (SD 0) and "
    "+/-1, 2, 3 SD. TP1-TP4: the next SD levels beyond the entry's SD zone, in the trade "
    "direction (TP4 is the far target, the position fully closes at the current target). "
    "SL: the signal candle's low (BUY) or high (SELL), fixed for the trade; after TP1 is hit "
    "the SL may move to entry (breakeven). PAYOFF MODEL: this is a 'low win rate, big payoff' "
    "strategy - many small stop-losses and a few large TP wins, so ROI-wise one average win "
    "can equal several average losses. Judge it by payoff ratio, breakeven win rate and "
    "closed + OPEN P&L together - NEVER by win rate alone. Open trades are winners still "
    "running toward TP4 and are not in the win-rate. Never say 'strategy fail hai' from a "
    "low win rate; say what the numbers show (e.g. which SD zone, timeframe, SL distance or "
    "EMA slope loses most, and how much profit losers had before the SL hit). When asked "
    "'kab profit, kab SL, kaunse TF / SD zone me', answer ONLY from the statistics block; if a "
    "group is missing or the sample is low, say the data is still thin. "
    "DAILY CYCLE: the bot runs all day, so results come in phases - a run of quick stop-losses "
    "(SL hunt / choppy, sideways market where EMA50 keeps getting crossed back and forth) "
    "followed later by trending moves where a few trades reach TP and pay for all the small "
    "losses. Use the 'Bot cycle' lines: today vs yesterday, by-hour results, losses in a row, "
    "quick stop-outs and what usually followed earlier bad phases. When the phase hint is "
    "CHOPPY, say it plainly (many quick SLs, strategy usually does not work in this kind of "
    "market) and that earlier bad phases were often followed by profit (only if the numbers "
    "say so); when RECOVERING or NORMAL, say that. You only ADVISE - never say the bot "
    "stopped or will stop opening trades, it keeps running. Never predict the next trade. "
    "DATA QUALITY: the snapshot is current, but it can still be WRONG for some trades. A position "
    "marked OUTDATED had an opposite signal that was skipped or missed (bot was off / restarting / a "
    "gate blocked it), so its P&L may not match what the strategy now says - NEVER call it healthy or "
    "'solid green' without saying so, and tell the user to check it. 'Restart/catch-up' lines mean "
    "peaks, drawdowns and exits for trades during that gap are estimated from 5m candles. Trades tagged "
    "recovered / reversed / outdated / restart_affected are excluded from pattern learning; say that "
    "when it matters. Always keep the real result (all trades) separate from what the AI learns from. "
    "TAKE / AVOID + FAST / SIDEWAYS: when the user asks 'kab trade lena chahiye / kab nahi', 'konse zone me "
    "fast profit', 'kahan sideways', answer ONLY from the SPEED / BEHAVIOUR tables, the market-regime groups "
    "and the FILTER SIMULATION lines in the statistics block - quote each group's own label (FAST / SIDEWAYS / "
    "QUICK-SL), numbers and trade count. Structure: (1) FAST profit zones, (2) SIDEWAYS / QUICK-SL zones, "
    "(3) TAKE candidates, (4) AVOID candidates with the simulated P&L change. Say clearly that these are "
    "HINDSIGHT patterns from past trades (skipping a group also removes its winners), the bot still takes every "
    "signal, and the user decides whether to watch/test a filter. If a group is missing, the sample is LOW, or "
    "there is no regime data yet, say 'abhi data kam hai' - never fill the gap with a guess, never invent a "
    "zone or number, never promise the next trade will behave the same. For a LIVE question like 'abhi ye "
    "trade lun?', you cannot know the next signal; only describe how similar past conditions behaved. "
    "MARKET REVERSAL: for 'market kab palta', 'kis zone / time / condition me profit wapas jaata hai', 'TP1 ke "
    "baad kitni der me palta', 'kis SD level pe top bana' - answer ONLY from the 'MARKET REVERSAL AFTER TP1' "
    "block: give the overall reversal rate, the REVERSAL HOT-SPOTS and HOLDS PROFIT BEST lines, the time-of-day / "
    "session rows, the minutes after TP1, and the SD band where price topped out. Say it is hindsight on past "
    "trades, you cannot predict the next reversal, and if a group has too few trades say 'abhi data kam hai'. "
    "WHEN STRATEGY IS BEST / EATS PROFIT: user's idea - the strategy sometimes makes good profit and sometimes "
    "'khaa jaati hai' (trade goes green, then comes back to flat/loss). When asked 'kab best, kab profit khaa "
    "leti hai', use the 'WHEN THE STRATEGY IS BEST vs WHEN IT EATS PROFIT' lines plus the per-group 'ended by' text. "
    "Explain the TP caveat in simple words: a trade is closed by its target, by SL, or by a scalp/manual close, so a "
    "TP that was never hit can mean two different things - 'market reversed' (SL/TSL) or 'bot/user closed it early' "
    "(SCALP/MANUAL/REVERSED). Always say which one the numbers show; never say 'market did not give TP3' when the "
    "trades were closed early by the bot. "
    "EMA SLOPE: the EMA50 slope is learned two ways - at ENTRY (steep/flat, turning WITH or AGAINST the trade) and "
    "WHILE the trade is open (the 'EMA SLOPE DURING TRADES' lines). For 'ye signal fake tha kya', 'slope palat gaya', "
    "'EMA kab sahi hota hai' answer ONLY from those lines: quote each group's label, trade count, avg net ROI and the "
    "old/new 'steady' tag. A trade whose slope flipped against it before the close is a POSSIBLE fake signal - say "
    "'possible', never 'fake' as a fact, and say it is hindsight on past trades. Judge only from trade patterns, never "
    "from any score; if the slope data is missing or the sample is thin say 'abhi data kam hai'. "
    "TP LADDER: for 'TP1 ke baad TP2/TP3/TP4 kitne time me', 'konse zone me TP2-TP3 hit nahi hote', answer ONLY "
    "from the TP LADDER block - quote reach %, the minutes from entry and 'after TP1', the TP1->TP2 conversion, "
    "and the 'ZONES WHERE TP2/TP3 RARELY HIT' line if present. If minutes are n/a or the group is missing, say the "
    "timing data is still being collected (only trades opened after the latest update carry it). "
    "TWO INDICATORS, ONE STRATEGY: the user has two TradingView scripts built on the SAME maths. (1) MAIN-CHART script: "
    "EMA50 cross (the entry trigger) + SD bands = mean and std-dev of the last 200 closes, with the +/-1, 2, 3 SD "
    "levels (TP1-TP4 come from these). (2) 'Special Master new' (sub-panes): the Z-SCORE = (close - mean200) / std200 "
    "- the SAME mean and SD as the main-chart bands, just shown as 'how many SD away' - plus a TSI momentum pane "
    "(TSI value line, signal line, histogram = TSI - signal, Ob/Os +/-30, reversal arrows). So Z +1 means price sits "
    "on the +1 SD line of the main chart; both views show one thing from two angles, and TSI is the only extra "
    "information (momentum). In the app chart both are drawn with the user's own TradingView settings. "
    "Z-SCORE IS NOT PRICE: Z can FALL while price RISES (and the reverse). The change of Z over a few candles splits "
    "exactly into three parts: PRICE moved, the 200-AVERAGE moved (if the average rises faster than price, price is "
    "'less above' it and Z falls - the average is catching up), and the SD changed (after a spike the SD expands, so "
    "the same distance counts for fewer SD and Z shrinks). Labels z_why / z_why10 in the Shadow Lab block name which "
    "part explains a price-vs-Z disagreement ('price up / Z down: average catching up' or 'SD expanding', and the "
    "mirror for falling price). When the user asks 'Z gir raha hai par price upar ja raha hai kyun', explain it with "
    "these three parts in simple Hinglish, say which part the data shows if a z_why line is available, and say "
    "that Z falling while price rises does NOT by itself mean the move is over - it often means the SD bands are "
    "widening or the average is catching up; only quote win-rate / ROI for such a case if the lab block has it with "
    "a trade count, otherwise say 'abhi data kam hai'. When asked 'kab, kya, kyun, kaise' about the indicators, answer "
    "in that order: WHAT each pane shows now, WHY it moved (price / average / SD), HOW it has behaved in past trades "
    "(only from the lab / miner lines), and never give a score or promise the next move. "
    "FORMAT: write plain text; short lines starting with '- ' for lists and **bold** only for key numbers."
)

_SYSTEM_PROMPT = (
    "Tum OWL Terminal ke andar wale AI Assistant ho - ek crypto futures "
    "paper-trading app. Hamesha natural Roman Hinglish mein baat karo, "
    "jaise ek trading-buddy dost baat karta hai - casual aur seedha tone, "
    "lekin numbers, prices aur trading terms (entry, SL, TP, ROI, P&L, "
    "session, streak) English mein hi rakho, translate mat karo. Neeche "
    "user ke bot ka REALTIME snapshot diya gaya hai (open positions, aaj ka "
    "P&L, 5-min rolling delta, risk flags, aur agar relevant ho to "
    "trade-audit history bhi) - yeh data hamesha abhi ka hai, isi se "
    "sawaalon ke jawab do confidently. Kabhi mat bolo ki tumhare paas "
    "real-time/background data nahi hai ya screenshot maango - woh niche "
    "hamesha diya hua hai. Agar 'Risk flags' section mein kuch hai (stale "
    "price feed, SL ke paas, ya drawdown limit ke paas), toh usko khud se "
    "proactively point out karo, user ke poochhe bina bhi. Tum khud koi "
    "trade place, close, ya modify nahi kar sakte - sirf analyze aur guide "
    "kar sakte ho (yeh baat sach hai, isse mat chupao). Agar user kisi "
    "error code, order failure, 'no live feed', ya kisi bhi execution "
    "problem ke baare mein poochhe (Binance error jaise -4120/-2019/-2022, "
    "ya WebSocket/feed drop), toh neeche diye gaye EXECUTION ERROR "
    "REFERENCE ko use karke exact wajah aur fix Hinglish mein clearly "
    "explain karo - guess mat maaro, reference wahi hai jo neeche diya "
    "gaya hai. Agar 'Recent execution/system issues' section mein kuch "
    "dikh raha hai, usse bhi proactively mention karo agar relevant ho. "
    "Jawab chhote, seedhe aur to-the-point rakho, institutional-confident "
    "tone mein."
    + _ERROR_KNOWLEDGE_BASE
    + _STRATEGY_RULES
)

# Keyword-based trigger for feeding trade-audit telemetry into context -
# only when the user is actually asking for strategy evaluation or mistake
# analysis, not on every message (keeps the context small/cheap otherwise).
_AUDIT_TRIGGER_WORDS = (
    "mistake", "galti", "galat", "review", "analy", "streak", "win rate",
    "winrate", "loss rate", "performance", "strategy", "kaha", "kyu",
    "kyun", "pattern", "session", "audit",
    "profit", "loss", "nuksan", "nuksaan", "faida", "mfe", "mae", "zone",
    "sd ", "ema", "improve", "sudhar", "kab ", "entry", "tp ", "sl ",
    "fail", "kaam", "jeet", "haar", "postmortem", "timeframe", "payoff",
    "open trade", "kaise", "stat", "aaj", "kal", "kitne", "cycle", "choppy",
    "hunt", "market", "phase", "yesterday", "today",
    "lena", "leni", "lun", "skip", "avoid", "take", "fast", "sideways", "regime",
    "chahiye", "volatil", "atr", "band", "tp1", "tp2", "tp3", "tp4", "hit",
    "palt", "reversal", "reverse", "wapas", "khaa", "top ", "peak",
)


_STATS_GUIDANCE = (
    "HOW TO USE THE STATISTICS ABOVE: explain in simple Roman Hinglish when the "
    "strategy loses and when it gives big profit, using ONLY the numbers shown. "
    "If a LOW SAMPLE warning is present, say the data is too small and give only "
    "tentative hints, never firm rules. MFE = best profit a trade saw before "
    "closing (if losers often had big MFE, TP is being taken too late); MAE = "
    "worst dip a trade saw (if winners have small MAE, SL is placed fine). "
    "PAYOFF: if a 'Payoff' line is shown, a win rate below the breakeven win rate is "
    "the real warning, a win rate above it is fine even if low; always mention OPEN "
    "trades' unrealized P&L and the combined closed+open P&L before judging. SL "
    "distance / timeframe groups show where small stop-losses cluster - use them to say "
    "when the SL hits too often. TP1-then-lost count shows profit given back. "
    "PATTERN MINER block: these patterns were found by code on older trades and re-tested on newer "
    "ones. Explain them in simple Hinglish as 'kab lena / kab skip karna / kab sideways hota hai / "
    "kab SL profit kha jata hai'. NEVER give a score, rating or confidence percent. CONFIRMED = held "
    "on newer trades, UNTESTED = newer trades too few, FAILED = it was luck, STABLE = stayed confirmed "
    "over several checks. For the EXIT WHAT-IF lines say clearly they are approximate. "
    "HOLD / WAIT LESSONS tell how many minutes TP1..TP4 usually take and what happened to trades that kept "
    "holding after TP1 - use them to answer 'kitna wait karun'. ML MODEL: say plainly whether it LEARNED "
    "anything or NOT YET; never quote a per-trade probability. "
    "Never invent a number, never promise future profit, and never tell the "
    "user to change the strategy rules - only point out patterns and suggest "
    "what to watch or test. If a group is not listed, the data is too thin."
)


def _wants_audit_context(message):
    low = (message or "").lower()
    return any(w in low for w in _AUDIT_TRIGGER_WORDS)


def _build_audit_context():
    """Compact text summary of trade_store.get_audit_summary() - only
    called when _wants_audit_context() says the user is asking for
    strategy/mistake analysis. Never raises; returns "" on any failure or
    if there's no closed-trade history yet."""
    try:
        audit = trade_store.get_audit_summary(50)
        if not audit.get("sample_size"):
            return ""
        streak = audit.get("current_streak") or {}
        triggers = ", ".join(
            f"{t['reason']} x{t['count']}" for t in (audit.get("common_exit_triggers") or [])[:5]
        )
        lines = [
            f"Trade audit (last {audit['sample_size']} closed trades):",
            f"  Current streak: {streak.get('count', 0)} {streak.get('type') or 'n/a'}(s) in a row",
            f"  Best-performing session: {audit.get('best_session') or 'n/a'}",
            f"  Common exit triggers: {triggers or 'n/a'}",
        ]
        # Code-computed strategy statistics (ai_stats.py): win rate by SD zone /
        # session / EMA slope / volume, plus MFE/MAE. The AI explains these;
        # it must never calculate or guess numbers itself.
        stats_text = ai_stats.build_summary(200)
        if stats_text:
            lines.append("")
            lines.append(stats_text)
            lines.append(_STATS_GUIDANCE)
        return "\n".join(lines)
    except Exception:
        return ""


_pnl_history = []  # [(timestamp, total_open_pnl_usdt), ...] - see _rolling_delta_line()
_PNL_HISTORY_WINDOW_S = 300  # 5 minutes


def _rolling_delta_line(positions):
    """Best-effort 5-min rolling P&L delta, sampled opportunistically each
    time the AI Assistant is actually asked something (there's no separate
    background sampler - this module only runs on-demand). Good enough for
    "how are things moving" style questions during an active chat session;
    honestly says so when there isn't 5 minutes of history yet instead of
    faking a number."""
    now = time.time()
    total_pnl = sum(float(p.get("pnl_usdt") or 0.0) for p in positions)
    _pnl_history.append((now, total_pnl))
    while _pnl_history and now - _pnl_history[0][0] > _PNL_HISTORY_WINDOW_S:
        _pnl_history.pop(0)
    if len(_pnl_history) < 2 or now - _pnl_history[0][0] < 30:
        return "5-Min Rolling Delta: not enough chat activity yet to sample a trend"
    oldest_ts, oldest_pnl = _pnl_history[0]
    delta = total_pnl - oldest_pnl
    span_s = now - oldest_ts
    return (f"5-Min Rolling Delta: open P&L moved {delta:+.2f} USDT over the last "
            f"{span_s / 60:.1f} min of chat activity")


def _risk_flags(positions):
    """Proactive risk lines - stale/dead price feed (the 2U2USDTM bug
    class: P&L frozen, Close silently doing nothing) and near-SL positions.
    Returns [] if nothing to flag."""
    now = time.time()
    flags = []
    for p in positions:
        symbol = p.get("symbol")
        last_ok = p.get("last_ok_ts")
        if last_ok and now - last_ok > _STALE_FEED_AFTER_S:
            age_min = (now - last_ok) / 60
            flags.append(f"  ⚠ {symbol}: NO LIVE PRICE UPDATE for {age_min:.1f} min - price feed "
                         f"looks dead/stale for this symbol (P&L frozen). Close/Flatten will "
                         f"force-close it at the last-known price if asked.")
        if p.get("outdated_reason"):
            flags.append(f"  ⚠ {symbol}: OUTDATED {p.get('action')} position - a {p.get('outdated_signal')} signal "
                         f"came but was not acted on ({p.get('outdated_reason')}). Its P&L may not reflect the "
                         f"current strategy view; do not call it healthy.")
        elif p.get("restart_affected"):
            flags.append(f"  ℹ {symbol}: a restart/data gap happened while this trade was open - its peak/"
                         f"drawdown are estimated from 5m candles.")
        sl = p.get("effective_sl")
        ltp = p.get("ltp")
        entry = p.get("entry_price")
        if sl and ltp and entry:
            try:
                dist_pct = abs(ltp - sl) / entry * 100.0
                if dist_pct <= _SL_PROXIMITY_PCT:
                    flags.append(f"  ⚠ {symbol}: within {dist_pct:.2f}% of SL ({sl:g}) - close to stopping out")
            except ZeroDivisionError:
                pass
    return flags


def _recent_error_alerts(s, within_s=1800, limit=6):
    """Pulls recent execution/system-failure entries straight from the same
    Alerts feed the Alerts screen shows (status.add_alert / upsert_trade_alert
    - see status.py), filtered to the failure-ish ones: LIVE ORDER/CLOSE
    FAILED (carries Binance's real error code+message inside `e`, e.g.
    "...code=-2019 msg=Margin is insufficient..."), UNPROTECTED (SL/TP
    placement failed so the position has no resting exchange-side stop),
    and market-data/WebSocket drop notices. This is the "did this actually
    happen to ME, just now" half of the diagnostic picture - paired with
    the static _ERROR_KNOWLEDGE_BASE above, which explains what any code
    found here actually means and how to fix it. Returns [] on anything
    from "no alerts yet" to a malformed alerts list - never raises."""
    try:
        now = time.time()
        alerts = s.get("alerts") or []
        hits = []
        for a in alerts:
            ts = a.get("ts")
            if ts is None or now - ts > within_s:
                continue
            text = str(a.get("text") or "")
            atype = str(a.get("type") or "")
            low = text.lower()
            is_failure = (
                atype == "error"
                or "failed" in low
                or "unprotected" in low
                or "disconnect" in low
                or "websocket" in low
                or "ghost" in low
            )
            if not is_failure:
                continue
            hits.append(f"  [{a.get('time', '--')}] {text}")
            if len(hits) >= limit:
                break
        return hits
    except Exception:
        return []


def _recent_skips(s, within_s=3600, limit=6):
    """Signals the bot skipped/missed in the last hour, from the same Alerts feed
    the Alerts screen shows - so the AI knows a signal did NOT become a trade."""
    try:
        now = time.time()
        out = []
        for a in (s.get("alerts") or []):
            ts = a.get("ts")
            if ts is None or now - ts > within_s:
                continue
            d = a.get("d") or {}
            if str(a.get("type")) == "skip" or d.get("kind") == "outdated":
                out.append(f"  [{a.get('time', '--')}] {a.get('text')}")
                if len(out) >= limit:
                    break
        return out
    except Exception:
        return []


def _restart_line(s):
    """Last catch-up (restart / data gap) the bot ran, or ''."""
    try:
        r = s.get("last_reconcile") or {}
        if not r or time.time() - float(r.get("ts") or 0) > 6 * 3600:
            return ""
        gap_min = float(r.get("gap_s") or 0) / 60.0
        return (f"Last restart/catch-up: {r.get('trigger')} - gap {gap_min:.1f} min, checked "
                f"{r.get('checked')} open trade(s), {r.get('closed')} closed while away. Signals that fired "
                f"during such a gap may have been missed entirely.")
    except Exception:
        return ""


def _build_context():
    """A compact text snapshot of current bot state, appended to every
    request so the assistant can answer 'what's open right now' style
    questions without the user having to paste anything - includes
    proactive risk flags (stale feed / near-SL) and a rolling P&L delta so
    the assistant can point these out unprompted instead of only answering
    exactly what's asked."""
    try:
        s = status.get()
        positions = s.get("open_positions", [])
        pos_lines = [
            f"  #{p.get('id')} {p.get('symbol')} {p.get('action')} "
            f"entry={p.get('entry_price')} ltp={p.get('ltp')} "
            f"pnl={p.get('pnl_usdt'):+.2f} roi={p.get('roi_pct'):+.2f}%"
            for p in positions
        ]
        today = trade_store.get_today_stats()
        today_pnl = today.get("today_pnl_usdt", 0)
        loss_limit = float(settings_store.get("daily_loss_limit_usdt", 20.0) or 20.0)
        lines = [
            f"[REALTIME TERMINAL STATE]",
            f"Mode: {'LIVE' if settings_store.get('live_trading_enabled', False) else 'PAPER'}",
            f"Bot status: {s.get('status')}",
            f"Today's P&L: {today_pnl:+.2f} USDT (safe daily loss limit: -{loss_limit:.2f} USDT), "
            f"trades: {today.get('total_trades', 0)}, "
            f"win rate: {today.get('win_rate', 0):.1f}%",
            f"Open positions ({len(positions)}):",
        ]
        lines.extend(pos_lines or ["  (none)"])
        # Pre-computed totals from code - the model must quote these, never
        # add up the per-position lines itself (it mis-summed: said +34.60
        # while the real total was +147.85, and "7 green" for 7 of 9).
        try:
            op = ai_stats._open_stats()
            if op.get("n"):
                lines.append(
                    f"TOTAL OPEN (UNREALIZED) P&L: {op['pnl']:+.2f} USDT across {op['n']} open "
                    f"trades - {op['green_n']} in profit, {op['n'] - op['green_n']} not, "
                    f"avg ROI {op['avg_roi']:+.1f}%. Quote exactly these numbers; never sum "
                    f"the lines above yourself, and never reuse P&L numbers from earlier chat "
                    f"turns (they are stale)."
                )
        except Exception:
            pass
        try:
            day0 = trade_store._trading_day_start_ts()
            opened_today = sum(1 for p in positions if float(p.get("opened_at_ts") or 0) >= day0)
            lines.insert(4, f"Trades OPENED today (still open + already closed): "
                            f"{opened_today + int(today.get('total_trades', 0) or 0)} "
                            f"({opened_today} still open, {int(today.get('total_trades', 0) or 0)} closed)")
            cyc = ai_stats.build_cycle()
            if cyc:
                lines.append("\n".join(ai_stats._cycle_lines(cyc)))
        except Exception:
            pass
        lines.append(_rolling_delta_line(positions))
        risk_lines = _risk_flags(positions)
        if today_pnl < 0 and abs(today_pnl) >= loss_limit:
            risk_lines.append(f"  ⚠ Today's drawdown ({today_pnl:.2f} USDT) has reached/exceeded "
                               f"the safe daily loss limit (-{loss_limit:.2f} USDT)")
        if risk_lines:
            lines.append("Risk flags (mention these proactively if relevant):")
            lines.extend(risk_lines)
        rl = _restart_line(s)
        if rl:
            lines.append(rl)
        skip_lines = _recent_skips(s)
        if skip_lines:
            lines.append("Signals skipped / missed in the last hour (these did NOT become trades):")
            lines.extend(skip_lines)
        error_lines = _recent_error_alerts(s)
        if error_lines:
            lines.append("Recent execution/system issues (last 30 min - use the EXECUTION "
                          "ERROR REFERENCE in the system prompt to explain any error code "
                          "here in plain terms if the user asks):")
            lines.extend(error_lines)
        ws_state = s.get("market_data_state")
        if ws_state and ws_state != "LIVE":
            lines.append(f"Market data feed state: {ws_state} (see WebSocket drops in the "
                          f"EXECUTION ERROR REFERENCE if the user asks why prices look stuck)")
        return "\n".join(lines)
    except Exception:
        return "Bot status unavailable."


def _short_error(resp):
    """Human-readable one-liner from a provider's JSON error body instead of
    dumping raw JSON into the chat bubble."""
    try:
        body = resp.json()
        err = body.get("error", body) if isinstance(body, dict) else {}
        msg = err.get("message") if isinstance(err, dict) else None
        if msg:
            return str(msg).strip().splitlines()[0][:220]
    except Exception:
        pass
    return (resp.text or "")[:220]


def _call_openai(api_key, messages, model=None):
    model = model or _OPENAI_MODEL
    resp = requests.post(
        _OPENAI_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "max_tokens": 800},
        timeout=30,
    )
    if resp.status_code != 200:
        return None, f"OpenAI error {resp.status_code} ({model}): {_short_error(resp)}"
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"], None
    except (KeyError, IndexError):
        return None, "OpenAI returned an unexpected response."


def _anthropic_messages(messages):
    """OpenAI-style list -> (system text, Claude messages). Claude wants the first turn from the user and strictly
    alternating roles, so same-role neighbours are merged and a leading assistant turn is dropped."""
    system, out = "", []
    for m in messages:
        if m["role"] == "system":
            system += (m["content"] + "\n\n")
            continue
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"] += "\n\n" + m["content"]
        else:
            out.append({"role": m["role"], "content": m["content"]})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return system.strip(), out


def _call_anthropic(api_key, messages, model=None):
    """Claude (Anthropic Messages API) with the user's own key (Settings > AI Assistant). Returns (reply, error)."""
    system, msgs = _anthropic_messages(messages)
    if not msgs:
        return None, "Claude: nothing to send."
    order = []
    for m in (model,) + _ANTHROPIC_MODELS:
        if m and m not in order:
            order.append(m)
    last = None
    for name in order:
        resp = requests.post(
            _ANTHROPIC_URL,
            headers={"x-api-key": api_key, "anthropic-version": _ANTHROPIC_VERSION, "content-type": "application/json"},
            json={"model": name, "max_tokens": 800, "system": system, "messages": msgs},
            timeout=45,
        )
        if resp.status_code == 404:                    # unknown / retired model name -> next one
            last = f"Claude error 404 ({name}): {_short_error(resp)}"
            continue
        if resp.status_code != 200:
            return None, f"Claude error {resp.status_code} ({name}): {_short_error(resp)}"
        try:
            parts = [b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text"]
        except Exception:
            parts = []
        text = "".join(parts).strip()
        if text:
            return text, None
        return None, "Claude returned an empty answer."
    return None, last or "Claude: no model worked."


def _gemini_contents(messages):
    # Gemini has no separate "system" role - fold it into the first user turn.
    system_text = ""
    contents = []
    for m in messages:
        if m["role"] == "system":
            system_text = m["content"] + "\n\n"
            continue
        role = "model" if m["role"] == "assistant" else "user"
        text = (system_text + m["content"]) if role == "user" and system_text else m["content"]
        system_text = ""
        contents.append({"role": role, "parts": [{"text": text}]})
    return contents


def _discover_gemini_models(api_key):
    """Ask Google which models this key can call generateContent on, best
    guess first (plain 'flash' models, newest name first)."""
    try:
        resp = requests.get(f"{_GEMINI_BASE}/models", params={"key": api_key, "pageSize": 200}, timeout=20)
        if resp.status_code != 200:
            return []
        names = []
        for m in resp.json().get("models", []):
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            name = (m.get("name") or "").replace("models/", "")
            low = name.lower()
            if "flash" not in low:
                continue
            if any(bad in low for bad in ("image", "tts", "live", "audio", "thinking", "exp", "preview", "8b", "lite")):
                continue
            names.append(name)
        return sorted(names, reverse=True)[:3]
    except Exception:
        return []


def _call_gemini(api_key, messages, model=None):
    """Tries the configured model first (Settings > AI Assistant > AI model),
    then the fallback chain, then Google's own model discovery. On a 429/503
    ("high demand") response this does NOT give up immediately - it moves on
    to the next model in the chain right away, and only sleeps/backs off if
    EVERY model in the chain came back 429/503 in the same pass (a real
    capacity spike, not just one busy model) - up to _GEMINI_MAX_PASSES
    whole-chain retries before finally reporting an error. Any other error
    (bad key, invalid request, quota hard-exhausted) still fails fast since
    trying another model won't fix it."""
    global _gemini_working_model
    contents = _gemini_contents(messages)

    # Configured model (explicit Settings override) always goes first, then
    # the last model that actually worked this run, then the fixed fallback
    # chain - de-duplicated, order preserved.
    order = [m for m in [model, _gemini_working_model] + _GEMINI_FALLBACKS if m]
    seen = set()
    order = [m for m in order if not (m in seen or seen.add(m))]

    def attempt(name):
        return requests.post(
            f"{_GEMINI_BASE}/models/{name}:generateContent",
            params={"key": api_key},
            json={"contents": contents},
            timeout=30,
        )

    tried = []
    last_err = None
    discovered = False
    backoff = _GEMINI_BACKOFF_BASE

    for pass_num in range(_GEMINI_MAX_PASSES):
        queue = list(order)
        any_retryable = False
        while queue:
            name = queue.pop(0)
            tried.append(name)
            try:
                resp = attempt(name)
            except requests.exceptions.RequestException as e:
                last_err = f"Gemini network error ({name}): {e}"
                any_retryable = True
                continue

            if resp.status_code == 200:
                data = resp.json()
                try:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                except (KeyError, IndexError):
                    return None, f"Gemini ({name}) returned an empty/blocked response."
                _gemini_working_model = name
                return text, None

            last_err = f"Gemini error {resp.status_code} ({name}): {_short_error(resp)}"

            if resp.status_code in _GEMINI_RETRYABLE:
                any_retryable = True
                continue  # this model is busy right now - move straight to the next one

            if resp.status_code == 404:
                if not queue and not discovered:
                    discovered = True
                    queue = [m for m in _discover_gemini_models(api_key) if m not in tried]
                continue

            return None, last_err   # bad key / invalid request / hard quota - another model won't help

        if not any_retryable:
            break   # nothing in this pass was worth retrying (e.g. only unknown 404s)
        if pass_num < _GEMINI_MAX_PASSES - 1:
            time.sleep(backoff)
            backoff *= 2

    tried_unique = list(dict.fromkeys(tried))
    return None, (f"{last_err} - every configured Gemini model is at high demand right now "
                  f"(tried {', '.join(tried_unique)}). Please try again in a few seconds.")


def ask(user_message, history=None):
    """Counts busy/idle, calls, errors and latency for the System Load card
    (telemetry.py); the actual work is in _ask_impl()."""
    t0 = telemetry.ai_begin()
    ok = False
    try:
        result = _ask_impl(user_message, history)
        ok = bool(result.get("ok"))
        return result
    finally:
        telemetry.ai_end(t0, ok)


def _ask_impl(user_message, history=None):
    """history: optional list of {"role": "user"|"assistant", "content": str}
    from earlier turns in this chat session (frontend keeps it, not us -
    this module is stateless). Returns {"ok": bool, "reply": str} or
    {"ok": False, "error": str}."""
    s = settings_store.get_all()
    if not s.get("ai_enabled"):
        return {"ok": False, "error": "AI Assistant is turned off in Settings."}
    api_key = (s.get("ai_api_key") or "").strip()
    if not api_key:
        return {"ok": False, "error": "No API key set - add one in Settings > AI Assistant."}
    provider = s.get("ai_provider", "openai")
    model = (s.get("ai_model") or "").strip() or None

    context = _build_context()
    if _wants_audit_context(user_message):
        audit_context = _build_audit_context()
        if audit_context:
            context += "\n\n" + audit_context

    messages = [{"role": "system", "content": _SYSTEM_PROMPT + "\n\n" + context}]
    for turn in (history or [])[-10:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": str(turn["content"])})
    messages.append({"role": "user", "content": user_message})

    try:
        if provider == "gemini":
            reply, err = _call_gemini(api_key, messages, model)
        elif provider == "anthropic":
            reply, err = _call_anthropic(api_key, messages, model)
        else:
            reply, err = _call_openai(api_key, messages, model)
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": f"Network error reaching {provider}: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Unexpected error: {e}"}

    if err:
        return {"ok": False, "error": err}
    return {"ok": True, "reply": reply + _summary_card_marker(user_message)}


# Words that mean "give me a summary of how I'm doing". When one of them
# shows up we append a machine-readable [[OWLCARD {...}]] line built from the
# REAL trade_store numbers (never from the model's text, so it can't be wrong
# or hallucinated). The Flutter chat strips it and draws a small stats card;
# an older app build would just show the line as text, harmless.
_SUMMARY_WORDS = ("today", "aaj", "summary", "how did i do", "kaisa", "kaisi",
                  "p&l", "pnl", "win rate", "performance", "result")


_OPEN_WORDS = ("unreleased", "unrealized", "unrealised", "unreleazed", "floating", "open pnl",
               "open p&l", "open trades", "open position")


def _summary_card_marker(user_message):
    try:
        text = (user_message or "").lower()
        import json as _json
        if any(w in text for w in _OPEN_WORDS):
            # Asked about OPEN (unrealized) profit - show that, not today's closed P&L,
            # otherwise the card (-29.88 closed) contradicts the answer (+32.84 open).
            op = ai_stats._open_stats()
            if not op.get("n"):
                return ""
            card = {"kind": "open", "pnl": round(float(op.get("pnl", 0) or 0), 2), "n": int(op["n"]),
                    "green_n": int(op.get("green_n", 0) or 0), "avg_roi": round(float(op.get("avg_roi", 0) or 0), 2)}
            return "\n[[OWLCARD " + _json.dumps(card) + "]]"
        if not any(w in text for w in _SUMMARY_WORDS):
            return ""
        today = trade_store.get_today_stats()
        card = {
            "pnl": round(float(today.get("today_pnl_usdt", 0) or 0), 2),
            "trades": int(today.get("total_trades", 0) or 0),
            "wins": int(today.get("wins", 0) or 0),
            "losses": int(today.get("losses", 0) or 0),
            "win_rate": round(float(today.get("win_rate", 0) or 0), 1),
        }
        return "\n[[OWLCARD " + _json.dumps(card) + "]]"
    except Exception:
        return ""
